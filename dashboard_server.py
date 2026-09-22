#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""QA_runner_K 대시보드 - 로컬에서만 뜨는 조회/작성용 웹 페이지.

두 가지 화면을 제공한다.
  /      실행 결과 (PASS/FAIL/확인 필요 + 사유 + 전/후 스크린샷)
  /tcs   TC 관리  - 엑셀을 만들지 않고 화면에서 TC를 작성하고, 그 TC로 프로그램을 돌린다 [NEW v0.4.0]

프로그램(qa_runner_k_gui.py)이 실행되면 백그라운드 스레드로 127.0.0.1에 이 서버를 띄운다.
외부에 노출되는 서버가 아니라 로컬 전용 화면이라는 점에 유의
(TODO: 여러 사람이 같이 쓰려면 EC2 쪽에 같은 API를 붙여 원격 조회/작성으로 확장).
"""

import io
import os
import socket
import threading
import time
import urllib.parse

from flask import Flask, request, send_file, abort, redirect, url_for

import dashboard_auth
import results_store
import tc_excel

# 업로드 엑셀 크기 상한. TC 엑셀은 보통 수십~수백 KB라 10MB면 충분하고,
# 실수로 큰 파일을 올렸을 때 메모리를 물지 않게 한다.
MAX_UPLOAD_BYTES = 10 * 1024 * 1024

# 고정 포트를 먼저 시도한다. 매번 포트가 바뀌면 주소를 북마크할 수 없어서
# "대시보드 링크"를 고정으로 안내하기 위함. 사용 중이면 빈 포트로 자동 대체.
DEFAULT_PORT = 8765

# /healthz 응답에 넣는 표식. 8765 포트를 쓰는 다른 프로그램과 구분하기 위한 것.
APP_MARKER = "qa_runner_k_dashboard"

RESULT_STYLE = {
    "PASS": ("PASS", "#1f9d55", "#e7f8ee"),
    "FAIL": ("FAIL", "#c0392b", "#fdecec"),
    "확인 필요": ("확인 필요", "#b7791f", "#fff6e0"),
}

PRIORITIES = ["P1", "P2", "P3", "P4"]


def create_app(db_path=None):
    app = Flask(__name__)
    app.config["DB_PATH"] = db_path
    app.config["MAX_CONTENT_LENGTH"] = MAX_UPLOAD_BYTES

    # [v0.9.0] 로그인. 내 PC에서 직접 보는 건 그대로 통과하고, 다른 컴퓨터에서 들어오거나
    # 서버 배포 모드(QA_RUNNER_K_REQUIRE_LOGIN=1)면 로그인 화면을 띄운다.
    dashboard_auth.install(app, db_path)

    # [NEW v0.24.0] nginx 하위 경로(/qa-k) 배포 대응. 환경변수가 없으면 아무 것도 안 바뀌므로
    # 내 PC에서 127.0.0.1:8765 로 쓰던 방식은 그대로다.
    app.wsgi_app = PrefixMiddleware(app.wsgi_app,
                                    os.environ.get("QA_RUNNER_K_URL_PREFIX", ""))

    def _reject_cross_site():
        """로컬 전용 서버이지만, 다른 사이트가 브라우저를 통해 POST를 보내는 것(CSRF)은 막는다.
        Origin 헤더가 있고 이 서버가 아니면 거부한다."""
        origin = request.headers.get("Origin")
        if origin and origin.rstrip("/") != request.host_url.rstrip("/"):
            abort(403)

    @app.route("/")
    def index():
        """[v0.12.0] 첫 화면은 '실행 배치 목록'. 배치를 고르면 그 배치의 결과 화면으로 간다.
        run_id 없이 전체를 한 번에 보던 화면은 '전체 보기'로 남겨둔다."""
        run_id = request.args.get("run_id") or None
        sheet = request.args.get("sheet")          # [v0.15.0] 시트(화면)별 필터
        if not run_id and request.args.get("all") != "1":
            return _render_runs(
                results_store.list_runs_summary(sheet=sheet, db_path=app.config["DB_PATH"]),
                request.args.get("msg", ""),
                results_store.list_result_sheets(db_path=app.config["DB_PATH"]), sheet,
                request.args.get("rename"))
        results = results_store.list_results(run_id=run_id, sheet=sheet,
                                             db_path=app.config["DB_PATH"])
        label = (results_store.get_run_label(run_id, db_path=app.config["DB_PATH"])
                 if run_id else "")
        return _render_results(results, run_id, sheet, label)

    @app.route("/runs/delete/<path:run_id>", methods=["POST"])
    def runs_delete(run_id):
        _reject_cross_site()
        try:
            n = results_store.delete_run(run_id, db_path=app.config["DB_PATH"])
            msg = f"실행 내역을 삭제했습니다 ({run_id} · 결과 {n}건 · 스크린샷 포함)"
        except Exception as e:
            msg = f"삭제 실패: {e}"
        return redirect(_u("/?msg=") + urllib.parse.quote(msg))

    @app.route("/runs/rename/<path:run_id>", methods=["POST"])
    def runs_rename(run_id):
        """실행 배치에 프로젝트명을 붙인다. [NEW v0.17.0]"""
        _reject_cross_site()
        try:
            label = results_store.set_run_label(run_id, request.form.get("label"),
                                                db_path=app.config["DB_PATH"])
            msg = (f"프로젝트명을 '{label}' 로 바꿨습니다" if label
                   else "프로젝트명을 지웠습니다 (실행 시각으로 표시됩니다)")
        except Exception as e:
            msg = f"이름 변경 실패: {e}"
        keep = request.form.get("sheet")
        url = _u("/?msg=") + urllib.parse.quote(msg)
        if keep:
            url += "&sheet=" + urllib.parse.quote(keep)
        return redirect(url)

    @app.route("/healthz")
    def healthz():
        """이미 떠 있는 대시보드가 우리 것인지 확인하는 용도. [NEW v0.6.0]
        8765 포트를 다른 프로그램이 쓰고 있을 수도 있어서, 단순 포트 점유 여부로 판단하지 않는다."""
        return {"app": APP_MARKER, "db": results_store.get_db_path()}

    @app.route("/img")
    def img():
        # 스크린샷 저장 기준 디렉터리 하위 파일만 서빙.
        # 이게 없으면 ?path=/etc/passwd 같은 임의 경로를 그대로 읽어줄 수 있어서 필수 체크.
        real = _screenshot_file(request.args.get("path", ""))
        if not real:
            abort(404)
        return send_file(real)

    # [NEW v0.26.0] 오래된 실행 내역 자동 정리.
    # 스크린샷이 계속 쌓이면 서버 디스크가 언젠가 찬다. 크론을 따로 걸면 관리 지점이 하나 늘고
    # 잊히기 쉬워서, 앱이 뜰 때와 하루에 한 번 결과를 받을 때 스스로 정리하게 했다.
    # QA_RUNNER_K_RETAIN_DAYS=0 이면 정리하지 않는다(보관 기간 제한 없음).
    def _retain_days():
        try:
            return int(os.environ.get("QA_RUNNER_K_RETAIN_DAYS", "30"))
        except ValueError:
            return 30

    def _purge_if_due(force=False):
        now = time.time()
        if not force and now - app.config.get("LAST_PURGE", 0) < 86400:
            return
        app.config["LAST_PURGE"] = now
        try:
            runs, lines = results_store.purge_old_runs(_retain_days(),
                                                       db_path=app.config.get("DB_PATH"))
            if runs:
                print(f"[정리] {_retain_days()}일 지난 실행 {runs}건({lines}줄) 삭제", flush=True)
        except Exception as e:
            print(f"[정리] 실패(무시하고 계속): {e}", flush=True)

    app.config["LAST_PURGE"] = 0
    _purge_if_due(force=True)

    # ---- 결과 업로드 API ----                                      [NEW v0.26.0]
    # PC의 프로그램이 실행 결과를 서버로도 보내기 위한 통로.
    # 인증은 쿠키가 아니라 Authorization: Bearer <토큰> 이다 (dashboard_auth.require_api_token).
    # 토큰이 설정돼 있지 않으면 503으로 막힌다 - 설정을 빠뜨린 채 열려 있는 상태를 만들지 않기 위함.
    # 로그인 미들웨어는 /api/ 로 시작하는 경로를 통과시키므로 여기서 토큰만 확인하면 된다.

    @app.route("/api/ping")
    @dashboard_auth.api_token_required
    def api_ping():
        """프로그램이 '주소와 토큰이 맞는지'만 확인할 때 쓴다. 결과를 보내기 전에 부른다."""
        return {"ok": True, "app": APP_MARKER}

    @app.route("/api/results", methods=["POST"])
    @dashboard_auth.api_token_required
    def api_results():
        """결과를 1건 또는 여러 건 받는다.

        본문은 JSON. 한 건이면 그대로, 여러 건이면 {"rows": [ ... ]}.
        같은 건을 다시 받아도 줄이 겹치지 않는다(run_id + tc_no + title 기준으로 덮어씀).
        네트워크가 끊겼다 재전송하는 경우가 정상 동작이라 중복 방어가 꼭 필요하다."""
        body = request.get_json(silent=True)
        if body is None:
            return {"ok": False, "error": "JSON 본문이 필요합니다"}, 400
        rows = body.get("rows") if isinstance(body, dict) else None
        if rows is None:
            rows = [body] if isinstance(body, dict) else body
        if not isinstance(rows, list):
            return {"ok": False, "error": "rows 는 목록이어야 합니다"}, 400
        if len(rows) > 200:
            return {"ok": False, "error": "한 번에 200건까지만 보낼 수 있습니다"}, 413

        dbp = app.config.get("DB_PATH")
        inserted = updated = 0
        errors = []
        for i, row in enumerate(rows):
            if not isinstance(row, dict):
                errors.append({"index": i, "error": "각 항목은 객체여야 합니다"})
                continue
            try:
                if results_store.upsert_result_row(row, db_path=dbp) == "insert":
                    inserted += 1
                else:
                    updated += 1
            except Exception as e:
                # 한 건이 잘못돼도 나머지는 받는다. 어느 건이 왜 실패했는지는 돌려준다.
                errors.append({"index": i, "error": str(e)[:200]})
        _purge_if_due()      # 하루에 한 번만 실제로 돈다
        return {"ok": not errors, "inserted": inserted, "updated": updated, "errors": errors}

    @app.route("/api/screenshot", methods=["POST"])
    @dashboard_auth.api_token_required
    def api_screenshot():
        """스크린샷 PNG 1장을 받는다. 본문은 파일 내용 그대로(Content-Type: image/png).

        multipart 대신 원시 본문을 쓰는 이유는 프로그램 쪽에 추가 라이브러리가 필요 없어서다.
        run_id 와 name 은 쿼리로 받되, 경로 조작은 results_store 쪽에서 깎아낸다."""
        data = request.get_data(cache=False)
        if not data:
            return {"ok": False, "error": "본문이 비어 있습니다"}, 400
        # PNG 시그니처 8바이트. 이 파일은 옮길 때 깨지지 않도록 이스케이프 문자를 피하는
        # 규칙이라, 문자열 리터럴 대신 바이트 값을 그대로 적는다.
        if data[:8] != bytes([0x89, 0x50, 0x4E, 0x47, 0x0D, 0x0A, 0x1A, 0x0A]):
            return {"ok": False, "error": "PNG 파일이 아닙니다"}, 415
        try:
            rel = results_store.save_uploaded_screenshot(
                request.args.get("run_id", ""), request.args.get("name", ""), data)
        except Exception as e:
            return {"ok": False, "error": str(e)[:200]}, 400
        return {"ok": True, "path": rel}

    # ---- TC 관리 ----                                            [NEW v0.4.0]
    @app.route("/tcs")
    def tcs():
        # [v0.14.0] sheet 파라미터가 있으면 그 시트(화면)의 TC만 보여준다.
        sheet = request.args.get("sheet")
        tc_list = results_store.list_custom_tcs(sheet=sheet, db_path=app.config["DB_PATH"])
        sheets = results_store.list_custom_tc_sheets(db_path=app.config["DB_PATH"])
        edit_id = request.args.get("edit")
        editing = None
        if edit_id:
            try:
                editing = results_store.get_custom_tc(edit_id, db_path=app.config["DB_PATH"])
            except Exception:
                editing = None
        return _render_tcs(tc_list, editing, request.args.get("msg", ""),
                           request.args.get("err", ""), sheets, sheet)

    @app.route("/tcs/sheet_enable", methods=["POST"])
    def tcs_sheet_enable():
        """한 시트의 TC를 통째로 실행 포함/제외. 화면 단위로 돌릴 때 쓴다. [NEW v0.14.0]"""
        _reject_cross_site()
        sheet = request.form.get("sheet") or ""
        on = request.form.get("enabled") == "1"
        n = results_store.set_sheet_enabled(sheet, on, db_path=app.config["DB_PATH"])
        label = sheet or "(시트 없음)"
        state = "실행 포함" if on else "실행 제외"
        return redirect(url_for("tcs", sheet=sheet, msg=f"{label} TC {n}건을 {state}로 바꿨습니다"))

    @app.route("/tcs/save", methods=["POST"])
    def tcs_save():
        _reject_cross_site()
        f = request.form
        row_id = (f.get("id") or "").strip()
        try:
            if row_id:
                results_store.update_custom_tc(
                    row_id, f.get("title"), f.get("steps"), f.get("expected"),
                    precondition=f.get("precondition"), priority=f.get("priority"),
                    tc_no=f.get("tc_no"), note=f.get("note"), sheet=f.get("sheet"),
                    db_path=app.config["DB_PATH"],
                )
                msg = f"TC를 수정했습니다"
            else:
                results_store.insert_custom_tc(
                    f.get("title"), f.get("steps"), f.get("expected"),
                    precondition=f.get("precondition"), priority=f.get("priority"),
                    tc_no=f.get("tc_no"), note=f.get("note"), sheet=f.get("sheet"),
                    db_path=app.config["DB_PATH"],
                )
                msg = "TC를 추가했습니다. 프로그램에서 [TC 불러오기]를 누르면 목록에 나옵니다"
            return redirect(url_for("tcs", msg=msg))
        except ValueError as e:
            return redirect(url_for("tcs", err=str(e)))
        except Exception as e:
            return redirect(url_for("tcs", err=f"저장 실패: {e}"))

    @app.route("/tcs/import", methods=["POST"])
    def tcs_import():
        """TC 엑셀을 올리면 그대로 TC 목록에 추가한다. [NEW v0.5.0]

        파싱은 프로그램과 같은 tc_excel.parse_tc_excel 을 쓰므로, 여기서 들어간 TC는
        프로그램이 엑셀을 직접 읽었을 때와 완전히 동일하게 해석된다."""
        _reject_cross_site()
        f = request.files.get("file")
        if not f or not f.filename:
            return redirect(url_for("tcs", err="엑셀 파일을 선택해주세요"))
        if not f.filename.lower().endswith((".xlsx", ".xlsm")):
            return redirect(url_for("tcs", err="xlsx 파일만 올릴 수 있습니다 (현재: "
                                               + os.path.basename(f.filename) + ")"))

        try:
            tcs, warnings = tc_excel.parse_tc_excel(io.BytesIO(f.read()))
        except tc_excel.TCExcelError as e:
            return redirect(url_for("tcs", err=str(e)))
        except Exception as e:
            return redirect(url_for("tcs", err=f"엑셀을 읽지 못했습니다: {str(e)[:150]}"))

        msg, ok = _bulk_add_tcs(app.config["DB_PATH"], tcs, warnings,
                                os.path.basename(f.filename), "엑셀에서")
        return redirect(url_for("tcs", msg=msg) if ok else url_for("tcs", err=msg))

    @app.route("/tcs/import_url", methods=["POST"])
    def tcs_import_url():
        """구글 스프레드시트 주소를 붙여넣으면 TC를 가져온다. [NEW v0.13.0]

        구글이 주는 xlsx 내보내기를 받아서 엑셀 업로드와 똑같은 파서를 태우므로,
        해석 결과는 파일을 올렸을 때와 완전히 같다."""
        _reject_cross_site()
        url = (request.form.get("url") or "").strip()
        if not url:
            return redirect(url_for("tcs", err="구글 시트 주소를 입력해주세요"))
        try:
            tcs, warnings = tc_excel.parse_gsheet(url)
        except tc_excel.TCExcelError as e:
            return redirect(url_for("tcs", err=str(e)))
        except Exception as e:
            return redirect(url_for("tcs", err=f"시트를 읽지 못했습니다: {str(e)[:150]}"))

        msg, ok = _bulk_add_tcs(app.config["DB_PATH"], tcs, warnings, "구글 시트", "구글 시트에서")
        return redirect(url_for("tcs", msg=msg) if ok else url_for("tcs", err=msg))

    @app.route("/tcs/toggle/<int:row_id>", methods=["POST"])
    def tcs_toggle(row_id):
        _reject_cross_site()
        cur = results_store.get_custom_tc(row_id, db_path=app.config["DB_PATH"])
        if not cur:
            abort(404)
        results_store.set_custom_tc_enabled(row_id, not cur.get("enabled"),
                                            db_path=app.config["DB_PATH"])
        state = "제외" if cur.get("enabled") else "포함"
        return redirect(url_for("tcs", msg=f"TC를 실행 대상에서 {state}했습니다"))

    @app.route("/tcs/delete/<int:row_id>", methods=["POST"])
    def tcs_delete(row_id):
        _reject_cross_site()
        results_store.delete_custom_tc(row_id, db_path=app.config["DB_PATH"])
        return redirect(url_for("tcs", msg="TC를 삭제했습니다"))

    return app


# ============================================================
# 렌더링
# ============================================================
def _esc(s):
    return (str(s if s is not None else "")
            .replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            .replace('"', "&quot;"))


def _badge(result):
    label, color, bg = RESULT_STYLE.get(result, (result, "#555", "#eee"))
    return f'<span class="badge" style="color:{color};background:{bg}">{_esc(label)}</span>'


STYLE = """
  :root { color-scheme: light; }
  body { font-family: -apple-system, "Segoe UI", "Malgun Gothic", sans-serif; margin: 0;
         background: #fafafa; color: #222; }
  .wrap { max-width: 1500px; margin: 0 auto; padding: 20px 16px 48px; }
  .tablewrap { overflow-x: auto; }
  nav { background: #22262e; padding: 0 16px; }
  nav .inner { max-width: 1500px; margin: 0 auto; display: flex; gap: 4px; align-items: center; }
  nav a { color: #c9cdd6; text-decoration: none; padding: 14px 14px; font-size: 14px; font-weight: 600; }
  nav a.on { color: #fff; box-shadow: inset 0 -3px 0 #4c9aff; }
  nav .brand { color: #fff; font-weight: 700; margin-right: 12px; font-size: 14px; }
  nav .who { color: #9aa1ad; font-size: 13px; margin-left: auto; }
  h2 { margin: 20px 0 4px; font-size: 20px; }
  .sub { color: #666; font-size: 13px; margin-bottom: 16px; }
  .summary { margin: 8px 0 16px; }
  .summary-item { margin-right: 14px; font-size: 14px; }
  table { border-collapse: collapse; width: 100%; background: #fff; }
  th, td { border: 1px solid #e4e4e4; padding: 8px 10px; font-size: 13px; text-align: left;
           vertical-align: top; }
  th { background: #f4f5f7; font-weight: 600; white-space: nowrap; }
  td.reason { max-width: 380px; min-width: 200px; }
  td.pre { white-space: pre-wrap; max-width: 300px; }
  .badge { padding: 2px 10px; border-radius: 12px; font-weight: 600; font-size: 12px;
           display: inline-block; white-space: nowrap; }
  select, input[type=text], textarea { padding: 7px 8px; font-size: 13px; border: 1px solid #ccd0d6;
           border-radius: 6px; font-family: inherit; background: #fff; }
  input[type=text], textarea { width: 100%; box-sizing: border-box; }
  textarea { min-height: 78px; resize: vertical; line-height: 1.5; }
  label { display: block; font-size: 12px; font-weight: 600; color: #444; margin: 0 0 4px; }
  .req::after { content: " *"; color: #c0392b; }
  .card { background: #fff; border: 1px solid #e4e4e4; border-radius: 8px; padding: 16px;
          margin-bottom: 20px; }
  .grid { display: grid; grid-template-columns: 1fr 1fr; gap: 12px 16px; }
  .grid .full { grid-column: 1 / -1; }
  button { font-family: inherit; font-size: 13px; padding: 8px 14px; border-radius: 6px;
           border: 1px solid #ccd0d6; background: #fff; cursor: pointer; }
  button.primary { background: #2d6cdf; border-color: #2d6cdf; color: #fff; font-weight: 600; }
  button.link { border: none; background: none; color: #2d6cdf; padding: 2px 4px; }
  button.danger { border: none; background: none; color: #c0392b; padding: 2px 4px; }
  .guide { background: #f4f7ff; border: 1px solid #d6e0f7; border-radius: 8px; padding: 12px 14px;
           font-size: 13px; line-height: 1.7; color: #2a3444; margin-bottom: 16px; }
  .guide code { background: #fff; border: 1px solid #d6e0f7; border-radius: 4px; padding: 1px 5px; }
  .msg { padding: 10px 14px; border-radius: 8px; font-size: 13px; margin-bottom: 16px; }
  .msg.ok { background: #e7f8ee; border: 1px solid #b9e6cc; color: #1c6b41; }
  .msg.err { background: #fdecec; border: 1px solid #f3c7c7; color: #a3271c; }
  .card.upload { background: #fbfcff; border-color: #d6e0f7; }
  .card.upload label { font-size: 14px; }
  input[type=file] { font-size: 13px; }
  td.shots { width: 1%; white-space: nowrap; }
  a.shot { display: inline-block; text-decoration: none; margin: 0 6px 0 0; vertical-align: top; }
  a.shot img { display: block; width: 180px; height: 130px; object-fit: cover; object-position: top;
               border: 1px solid #d8dbe0; border-radius: 6px; background: #fff; }
  a.shot span { display: block; text-align: center; font-size: 11px; color: #666; padding-top: 3px; }
  a.shot:hover img { border-color: #2d6cdf; box-shadow: 0 0 0 2px rgba(45,108,223,.18); }
  a.shot:hover span { color: #2d6cdf; }
  .noshot { color: #999; font-size: 12px; }
  /* [v0.23.0] 5건 단위 구간 요약 */
  .ckwrap { border: 1px solid #e2e6ec; border-radius: 10px; background: #fbfcfe;
            margin: 0 0 16px; padding: 10px 14px; }
  .ckwrap > summary { cursor: pointer; font-size: 14px; font-weight: 600; color: #2a3444; }
  .cklist { display: grid; grid-template-columns: repeat(auto-fill, minmax(300px, 1fr));
            gap: 10px; margin-top: 12px; }
  .ck { border: 1px solid #e2e6ec; border-radius: 8px; background: #fff; padding: 10px 12px; }
  .ckhead { font-weight: 600; font-size: 13px; color: #1b2330; }
  .cksub { font-weight: 400; color: #888; font-size: 12px; }
  .ckcnt { margin: 6px 0 4px; font-size: 12px; }
  .ckissues { margin: 6px 0 0; padding-left: 18px; font-size: 12px; color: #55606f; line-height: 1.6; }
  .ckissues li { margin-bottom: 3px; }
  .ckok { font-size: 12px; color: #1c6b41; margin-top: 6px; }
  /* [v0.20.0] 스크린샷 팝업(라이트박스). 새 탭 대신 화면 위에 겹쳐 띄운다. */
  .lb { display: none; position: fixed; top: 0; right: 0; bottom: 0; left: 0; z-index: 900;
        background: rgba(14,18,26,.94); }
  .lb.on { display: flex; flex-direction: column; }
  .lb-bar { display: flex; align-items: center; justify-content: space-between; gap: 12px;
            padding: 10px 14px; color: #fff; font-size: 13px; background: #11151d;
            border-bottom: 1px solid rgba(255,255,255,.12); }
  .lb-cap { font-weight: 600; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .lb-tools { display: flex; gap: 6px; align-items: center; flex: none; }
  .lb-btn { background: rgba(255,255,255,.14); border: 1px solid rgba(255,255,255,.3); color: #fff;
            border-radius: 6px; padding: 4px 10px; font-size: 13px; line-height: 1.5;
            cursor: pointer; text-decoration: none; font-family: inherit; }
  .lb-btn:hover { background: rgba(255,255,255,.3); }
  .lb-scroll { flex: 1; overflow: auto; padding: 14px; text-align: center; }
  .lb-scroll img { max-width: 100%; border-radius: 6px; background: #fff;
                   box-shadow: 0 8px 30px rgba(0,0,0,.45); }
  .sub2small { color: #888; font-size: 12px; margin-top: 2px; }
  form.rename { display: flex; flex-wrap: wrap; gap: 6px; align-items: center; }
  form.rename input[type=text] { width: 260px; }
  form.rename .sub2small { flex-basis: 100%; }
  .chips { display: flex; flex-wrap: wrap; gap: 6px; align-items: center; margin: 10px 0 12px; }
  .chips-label { font-size: 12px; font-weight: 600; color: #444; margin-right: 4px; }
  a.chip { font-size: 13px; text-decoration: none; color: #3f3f4d; background: #fff;
           border: 1px solid #ccd0d6; border-radius: 14px; padding: 4px 12px; }
  a.chip:hover { border-color: #2d6cdf; color: #2d6cdf; }
  a.chip.on { background: #2d6cdf; border-color: #2d6cdf; color: #fff; font-weight: 600; }
  .bulk { margin-left: 8px; }
  a.runlink { color: #1b2330; text-decoration: none; font-weight: 600; }
  a.runlink.sub2 { color: #555; font-weight: 400; }
  a.runlink:hover { color: #2d6cdf; text-decoration: underline; }
  tbody tr:hover { background: #f7f9fd; }
  td.right, th.right { text-align: right; white-space: nowrap; }
  a.btnlike { font-size: 13px; color: #2d6cdf; text-decoration: none; padding: 2px 6px; }
  a.btnlike:hover { text-decoration: underline; }
  @media (max-width: 900px) { a.shot img { width: 150px; height: 110px; } }
  .off { opacity: 0.45; }
  .actions { display: flex; gap: 8px; align-items: center; margin-top: 4px; flex-wrap: nowrap; }
  td .actions button { white-space: nowrap; }
  @media (max-width: 720px) { .grid { grid-template-columns: 1fr; } }
"""

# [NEW v0.20.0] 스크린샷을 새 탭이 아니라 팝업으로 연다.
# 외부 라이브러리 없이 이 페이지 안에서만 동작한다(대시보드는 사내 PC/서버에서 돌고
# 외부 CDN을 못 부르는 환경도 있어서 의존성을 만들지 않는다).
# 주의: 이 파일은 백틱/역슬래시/달러중괄호를 쓰지 않는 규칙을 지킨다(파일 전송 절차 때문).
LIGHTBOX = """
<div id="lb" class="lb" role="dialog" aria-modal="true" aria-hidden="true">
  <div class="lb-bar">
    <span id="lb-cap" class="lb-cap"></span>
    <span class="lb-tools">
      <a id="lb-open" class="lb-btn" href="#" target="_blank" rel="noopener">새 탭으로</a>
      <button id="lb-prev" class="lb-btn" type="button" title="이전 (왼쪽 화살표)">&#8249;</button>
      <button id="lb-next" class="lb-btn" type="button" title="다음 (오른쪽 화살표)">&#8250;</button>
      <button id="lb-close" class="lb-btn" type="button" title="닫기 (Esc)">&#10005;</button>
    </span>
  </div>
  <div id="lb-scroll" class="lb-scroll"><img id="lb-img" alt=""></div>
</div>
<script>
(function () {
  var links = [].slice.call(document.querySelectorAll('a.shot'));
  if (!links.length) { return; }
  var box = document.getElementById('lb');
  var img = document.getElementById('lb-img');
  var cap = document.getElementById('lb-cap');
  var openLink = document.getElementById('lb-open');
  var scroll = document.getElementById('lb-scroll');
  var idx = -1;

  function show(i) {
    if (i < 0 || i >= links.length) { return; }
    idx = i;
    var a = links[i];
    var href = a.getAttribute('href');
    img.setAttribute('src', href);
    openLink.setAttribute('href', href);
    cap.textContent = a.getAttribute('data-cap') || '';
    scroll.scrollTop = 0;
    box.classList.add('on');
    box.setAttribute('aria-hidden', 'false');
    document.body.style.overflow = 'hidden';
  }
  function hide() {
    box.classList.remove('on');
    box.setAttribute('aria-hidden', 'true');
    document.body.style.overflow = '';
    img.removeAttribute('src');
    idx = -1;
  }

  links.forEach(function (a, i) {
    a.addEventListener('click', function (e) {
      // 사용자가 일부러 새 탭으로 열려는 조작(Ctrl/Cmd/Shift 클릭)은 그대로 둔다
      if (e.metaKey || e.ctrlKey || e.shiftKey) { return; }
      e.preventDefault();
      show(i);
    });
  });
  document.getElementById('lb-close').addEventListener('click', hide);
  document.getElementById('lb-prev').addEventListener('click', function () { show(idx - 1); });
  document.getElementById('lb-next').addEventListener('click', function () { show(idx + 1); });
  // 배경(이미지 바깥)을 누르면 닫는다
  box.addEventListener('click', function (e) {
    if (e.target === box || e.target === scroll) { hide(); }
  });
  document.addEventListener('keydown', function (e) {
    if (!box.classList.contains('on')) { return; }
    if (e.key === 'Escape') { hide(); }
    else if (e.key === 'ArrowLeft') { show(idx - 1); }
    else if (e.key === 'ArrowRight') { show(idx + 1); }
  });
})();
</script>
"""


def _page(title, active, body):
    def cls(name):
        return ' class="on"' if name == active else ""
    user = dashboard_auth.current_user()
    account = (f'<span class="who">{_esc(user)}</span><a href="{_u("/logout")}">로그아웃</a>'
               if user else "")
    return f"""<!doctype html>
<html lang="ko"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{_esc(title)}</title>
<style>{STYLE}</style></head>
<body>
  <nav><div class="inner">
    <span class="brand">QA_runner_K</span>
    <a href="{_u('/')}"{cls('results')}>실행 내역</a>
    <a href="{_u('/tcs')}"{cls('tcs')}>TC 관리</a>
    {account}
  </div></nav>
  <div class="wrap">{body}</div>
{LIGHTBOX}
</body></html>"""


class PrefixMiddleware:
    """[NEW v0.24.0] nginx가 하위 경로(/qa-k)에 얹어 넘겨줄 때 앱이 자기 주소를 바르게 알게 한다.

    nginx의 proxy_pass 가 /qa-k 를 떼고 넘기므로 앱이 보는 경로는 /tcs 지만,
    브라우저에게 돌려줄 링크는 /qa-k/tcs 여야 한다. WSGI의 SCRIPT_NAME 을 세워두면
    Flask의 url_for/redirect 와 request.script_root 가 전부 알아서 맞춰진다.

    X-Forwarded-Proto/Host 도 함께 반영한다. 이게 없으면
    - 세션 쿠키의 Secure 판단이 틀어지고
    - CSRF 검사(request.host_url 비교)가 nginx 뒤에서 항상 불일치가 된다."""

    def __init__(self, wsgi_app, prefix=""):
        self.wsgi_app = wsgi_app
        self.prefix = "/" + str(prefix or "").strip("/") if str(prefix or "").strip("/") else ""

    def __call__(self, environ, start_response):
        prefix = environ.get("HTTP_X_FORWARDED_PREFIX") or self.prefix
        prefix = "/" + str(prefix).strip("/") if str(prefix).strip("/") else ""
        if prefix:
            environ["SCRIPT_NAME"] = prefix
            path = environ.get("PATH_INFO", "")
            # nginx가 접두어를 떼지 않고 넘기는 설정이어도 중복되지 않게 맞춘다
            if path.startswith(prefix):
                environ["PATH_INFO"] = path[len(prefix):] or "/"
        proto = environ.get("HTTP_X_FORWARDED_PROTO")
        if proto:
            environ["wsgi.url_scheme"] = proto.split(",")[0].strip()
        host = environ.get("HTTP_X_FORWARDED_HOST")
        if host:
            environ["HTTP_HOST"] = host.split(",")[0].strip()
        return self.wsgi_app(environ, start_response)


def _u(path=""):
    """[NEW v0.24.0] 하위 경로 배포(/qa-k) 대응. 화면에 박아 넣는 절대 주소 앞에 접두어를 붙인다.

    Flask의 url_for 는 알아서 붙지만, 이 파일은 HTML을 f-string으로 직접 만들기 때문에
    href="/tcs" 같이 손으로 적은 주소가 많다. 그 자리를 이 함수로 감싼다.
    로컬(접두어 없음)에서는 받은 값을 그대로 돌려주므로 동작이 달라지지 않는다."""
    try:
        root = request.script_root or ""
    except Exception:
        root = ""
    return root + path


def _screenshot_file(stored):
    """저장된 경로로 실제 스크린샷 파일을 찾는다. [NEW v0.24.0]

    DB에는 그 파일을 만든 PC 기준의 절대 경로가 들어간다(윈도우면 C:\\클로드\\... 형태).
    이 DB를 서버로 옮기면 그 경로는 존재하지 않으므로, 경로를 그대로 믿지 않고
    **마지막 두 조각(<실행ID>/<파일명>)** 만 떼어 지금 환경의 스크린샷 루트 아래에서 찾는다.
    덕분에 PC에서 만든 DB를 서버에 그대로 올려도 스크린샷이 그대로 보인다.

    보안은 그대로다 - 어느 후보를 쓰든 realpath 가 스크린샷 루트 안에 있을 때만 돌려준다."""
    root = os.path.realpath(results_store.get_screenshot_root())
    raw = str(stored or "")
    if not raw:
        return None
    parts = [x for x in raw.replace("\\", "/").split("/") if x not in ("", ".", "..")]
    candidates = []
    if len(parts) >= 2:
        candidates.append(os.path.join(root, parts[-2], parts[-1]))   # <실행ID>/<파일명>
    if parts:
        candidates.append(os.path.join(root, parts[-1]))              # <파일명>
    candidates.append(raw)                                            # 만든 PC에서 그대로 볼 때
    for c in candidates:
        try:
            real = os.path.realpath(c)
        except Exception:
            continue
        if real.startswith(root + os.sep) and os.path.isfile(real):
            return real
    return None


def _tc_key(sheet, tc_no, title):
    """다시 가져왔을 때 '같은 TC'로 볼 기준. [NEW v0.18.0]

    시트 이름 + No 가 1순위. No 가 비어 있는 TC는 시트 이름 + 테스트 항목으로 본다.
    내용(절차/예상 결과)은 기준에 넣지 않는다 - 내용이 바뀌는 게 바로 '수정'이기 때문."""
    sheet = str(sheet or "").strip()
    no = str(tc_no or "").strip()
    if no:
        return ("no", sheet, no)
    return ("title", sheet, str(title or "").strip())


def _tc_changed(row, t):
    """DB에 있는 줄과 새로 읽은 TC의 내용이 다른지. 화면 표시용 카운트에만 쓴다."""
    def norm(v):
        return str(v or "").strip()
    return any((
        norm(row.get("title")) != norm(t.get("title")),
        norm(row.get("steps")) != norm(t.get("steps")),
        norm(row.get("expected")) != norm(t.get("expected")),
        norm(row.get("precondition")) != norm(t.get("precondition")),
        norm(row.get("priority")) != norm(t.get("priority")),
        norm(row.get("sheet")) != norm(t.get("sheet")),
    ))


def _bulk_add_tcs(db_path, tcs, warnings, source_name, source_phrase):
    """파싱된 TC들을 custom_tcs에 반영하고 안내 문구를 만든다. 엑셀 업로드와 구글 시트가 공유한다.

    [v0.18.0] 같은 시트의 같은 No 인 TC가 이미 있으면 새 줄을 만들지 않고 그 줄을 덮어쓴다.
    v0.17.0까지는 내용이 조금이라도 다르면 새 줄로 쌓여서, 시트에서 고친 TC를 다시 가져와도
    고치기 전 줄이 '실행 포함' 상태로 남아 같이 실행되는 문제가 있었다.
    같은 키로 이미 여러 줄이 쌓여 있으면 첫 줄만 남기고 나머지는 지워서 예전 중복도 정리한다.
    실행 포함/제외 상태(enabled)는 덮어써도 그대로 유지된다."""
    index = {}
    for row in results_store.list_custom_tcs(db_path=db_path):
        index.setdefault(
            _tc_key(row.get("sheet"), row.get("tc_no"), row.get("title")), []).append(row)

    added = updated = same = removed = failed = 0
    seen = set()
    for t in tcs:
        key = _tc_key(t.get("sheet"), t.get("no"), t.get("title"))
        seen.add(key)
        note = t["note"] or f"[{source_name}]"
        old = index.get(key) or []
        try:
            if old:
                head = old[0]
                for dup in old[1:]:          # 예전 버전에서 쌓인 중복 줄 정리
                    try:
                        results_store.delete_custom_tc(dup["id"], db_path=db_path)
                        removed += 1
                    except Exception:
                        pass
                changed = _tc_changed(head, t)
                results_store.update_custom_tc(
                    head["id"], t["title"], t["steps"], t["expected"],
                    precondition=t["precondition"], priority=t["priority"],
                    tc_no=t["no"], note=note, sheet=t.get("sheet", ""), db_path=db_path,
                )
                if changed:
                    updated += 1
                else:
                    same += 1
                index[key] = [head]
            else:
                new_id = results_store.insert_custom_tc(
                    t["title"], t["steps"], t["expected"],
                    precondition=t["precondition"], priority=t["priority"],
                    tc_no=t["no"], note=note,
                    sheet=t.get("sheet", ""), db_path=db_path,
                )
                index[key] = [{"id": new_id, "title": t["title"], "steps": t["steps"],
                               "expected": t["expected"], "precondition": t["precondition"],
                               "priority": t["priority"], "sheet": t.get("sheet", ""),
                               "tc_no": t["no"]}]
                added += 1
        except Exception:
            failed += 1

    # 이번 시트에는 없는데 DB에는 남아 있는 TC - 지우지는 않고 알려만 준다
    sheets = {str(t.get("sheet") or "").strip() for t in tcs}
    stale = sum(len(rows) for key, rows in index.items()
                if key not in seen and key[1] in sheets)

    parts = [f"{source_phrase} TC {added}건 추가"]
    if updated:
        parts.append(f"{updated}건 갱신")
    if same:
        parts.append(f"{same}건 변경 없음")
    if removed:
        parts.append(f"중복 {removed}건 정리")
    if failed:
        parts.append(f"저장 실패 {failed}건")
    if stale:
        parts.append(f"시트에 없는 기존 TC {stale}건은 그대로 남아 있습니다")
    if warnings:
        parts.append(" / ".join(warnings[:3]))
    if added or updated:
        parts.append("프로그램에서 [TC 불러오기] 후 [시작]하면 실행됩니다")
    # 전부 '변경 없음'이라 추가/갱신이 없는 건 오류가 아니므로 경고색으로 띄우지 않는다
    ok = not failed and bool(added or updated or same)
    return " · ".join(parts), ok


def _when(ts):
    try:
        return time.strftime("%Y-%m-%d %H:%M", time.localtime(float(ts)))
    except Exception:
        return "-"


def _source_label(source, source_ref):
    """TC가 어디서 왔는지 한 줄로. 엑셀은 파일명만, 대시보드/EC2는 그대로."""
    ref = str(source_ref or "")
    if source == "local":
        return os.path.basename(ref) or "로컬 엑셀"
    if source == "custom":
        return ref or "대시보드 추가 TC"
    return f"EC2 · {ref}" if ref else "EC2"


def _runs_url(sheet=None, rename=None):
    """실행 내역 목록 주소. 시트 필터를 보고 있었으면 그대로 유지한다. [NEW v0.17.0]"""
    q = []
    if sheet is not None:
        q.append("sheet=" + urllib.parse.quote(sheet))
    if rename is not None:
        q.append("rename=" + urllib.parse.quote(str(rename)))
    return _u("/?" + "&".join(q)) if q else _u("/")


def _sheets_label(sheets):
    """한 배치에 여러 시트가 섞여 있을 수 있어 요약해서 보여준다. [NEW v0.15.0]"""
    names = [s for s in (sheets or []) if s]
    if not names:
        return "-"
    if len(names) == 1:
        return names[0]
    return names[0] + f" 외 {len(names) - 1}"


def _render_result_sheet_filter(sheets, current):
    """[NEW v0.15.0] 실행 내역의 시트(화면)별 필터. 구분 기준은 엑셀/구글 시트의 시트 이름."""
    if not sheets or (len(sheets) == 1 and not sheets[0]["sheet"]):
        return ""
    chips = [f'<a class="chip{"" if current is not None else " on"}" href="{_u("/")}">전체</a>']
    for s in sheets:
        name = s["sheet"]
        label = name or "(시트 없음)"
        on = " on" if current is not None and current == name else ""
        chips.append(f'<a class="chip{on}" href="{_u("/?sheet=")}{urllib.parse.quote(name)}">'
                     f'{_esc(label)} ({s["runs"]}회 · {s["total"]}건)</a>')
    return f"""
  <div class="chips">
    <span class="chips-label">시트 구분</span>
    {''.join(chips)}
  </div>
  <div class="sub" style="margin:-6px 0 14px">TC 엑셀·구글 시트의 시트 이름으로 나뉩니다. 괄호 안은 (실행 횟수 · 결과 건수)입니다.</div>"""


def _render_runs(runs, msg, sheets=None, current_sheet=None, rename_id=None):
    """[NEW v0.12.0] 실행 배치 목록. TC를 돌릴 때마다 한 줄씩 쌓이고,
    줄을 누르면 그 배치의 결과 화면으로 간다. 줄마다 [삭제]가 붙는다."""
    rows = []
    for r in runs:
        detail = _u("/?run_id=") + urllib.parse.quote(str(r["run_id"]))
        badges = []
        if r["passed"]:
            badges.append(f'{_badge("PASS")} {r["passed"]}')
        if r["failed"]:
            badges.append(f'{_badge("FAIL")} {r["failed"]}')
        if r["unsure"]:
            badges.append(f'{_badge("확인 필요")} {r["unsure"]}')
        rid = urllib.parse.quote(str(r["run_id"]))
        keep = f'<input type="hidden" name="sheet" value="{_esc(current_sheet)}">' if current_sheet is not None else ""
        if rename_id is not None and rename_id == r["run_id"]:
            # 이름 바꾸는 중인 줄: 첫 칸을 입력 폼으로 바꿔 보여준다 (별도 화면 없이 그 자리에서)
            name_cell = f"""<form method="post" action="{_u('/runs/rename/')}{rid}" class="rename">
      {keep}<input type="text" name="label" value="{_esc(r.get('label'))}" maxlength="120"
             placeholder="예) 9월 정기 회귀 - 환자관리" autofocus>
      <button type="submit" class="primary">저장</button>
      <a class="btnlike" href="{_runs_url(current_sheet)}">취소</a>
      <div class="sub2small">{_esc(_when(r['started_at']))}</div>
    </form>"""
            actions = ""
        else:
            title = r.get("label") or _when(r["started_at"])
            sub = f'<div class="sub2small">{_esc(_when(r["started_at"]))}</div>' if r.get("label") else ""
            name_cell = f'<a class="runlink" href="{detail}">{_esc(title)}</a>{sub}'
            actions = f"""
    <a class="btnlike" href="{detail}">결과 보기</a>
    <form method="post" action="{_u('/runs/delete/')}{rid}"
          style="display:inline" onsubmit="return confirm('{_esc(r.get('label') or _when(r['started_at']))} 실행 내역(결과 {r['total']}건)을 삭제할까요? 스크린샷도 함께 지워지며 되돌릴 수 없습니다.');">
      <button type="submit" class="danger">삭제</button>
    </form>
    <a class="btnlike" href="{_runs_url(current_sheet, rename=r['run_id'])}">프로젝트명 수정</a>"""
        rows.append(f"""<tr>
  <td>{name_cell}</td>
  <td><a class="runlink sub2" href="{detail}">{_esc(_source_label(r['source'], r['source_ref']))}</a></td>
  <td>{_esc(_sheets_label(r.get('sheets')))}</td>
  <td>{r['total']}건</td>
  <td>{' &nbsp; '.join(badges) or '-'}</td>
  <td class="right">{actions}</td>
</tr>""")

    msg_html = f'<div class="msg ok">{_esc(msg)}</div>' if msg else ""
    empty = ('<tr><td colspan="6">아직 실행 내역이 없습니다. 프로그램에서 TC를 실행하면 '
             '여기에 한 줄씩 쌓입니다.</td></tr>')
    body = f"""
  <h2>실행 내역{" - " + _esc(current_sheet or "(시트 없음)") if current_sheet is not None else ""}</h2>
  <div class="sub">TC를 실행할 때마다 한 줄씩 쌓입니다. 줄을 누르면 그 실행의 결과와 스크린샷을 봅니다.</div>
  {msg_html}
  {_render_result_sheet_filter(sheets, current_sheet)}
  <table>
    <thead><tr><th>프로젝트명 / 실행 시각</th><th>TC 소스</th><th>시트 구분</th><th>건수</th><th>판정</th><th class="right">&nbsp;</th></tr></thead>
    <tbody>{''.join(rows) or empty}</tbody>
  </table>
  <p class="sub" style="margin-top:14px"><a href="{_u('/?all=1')}">전체 결과 한 번에 보기 (최근 300건)</a></p>"""
    return _page("QA_runner_K 실행 내역", "results", body)


PROGRESS_REPORT_EVERY = 5   # [v0.23.0] 프로그램 로그의 중간 보고와 같은 단위


def _render_checkpoints(results):
    """[NEW v0.23.0] 저장된 결과를 실행 순서대로 5건씩 묶어 구간 요약을 만든다.

    프로그램 로그의 '중간 보고'와 같은 내용을 나중에 대시보드에서도 볼 수 있게 한 것.
    별도 테이블을 만들지 않고 결과에서 다시 계산하므로, 예전에 돌린 실행 내역에도 바로 보인다."""
    if len(results) <= PROGRESS_REPORT_EVERY:
        return ""
    blocks = []
    for start in range(0, len(results), PROGRESS_REPORT_EVERY):
        group = results[start:start + PROGRESS_REPORT_EVERY]
        counts = {"PASS": 0, "FAIL": 0, "확인 필요": 0}
        for r in group:
            counts[r["result"]] = counts.get(r["result"], 0) + 1
        nums = [str(r["tc_no"]) for r in group]
        span = f"{nums[0]}~{nums[-1]}번" if len(nums) > 1 else f"{nums[0]}번"
        chips = " ".join(f'{_badge(k)} {v}' for k, v in counts.items() if v)
        issues = [r for r in group if r["result"] != "PASS"]
        if issues:
            items = "".join(
                f'<li><b>{_esc(r["tc_no"])}번</b> {_esc(r["title"])} — '
                f'{_esc(_short_reason(r["reason"]))}</li>' for r in issues)
            issue_html = f'<ul class="ckissues">{items}</ul>'
        else:
            issue_html = '<div class="ckok">이슈 없음</div>'
        blocks.append(f'<div class="ck"><div class="ckhead">{_esc(span)} '
                      f'<span class="cksub">({len(group)}건)</span></div>'
                      f'<div class="ckcnt">{chips}</div>{issue_html}</div>')
    return f"""
  <details class="ckwrap" open>
    <summary>구간 요약 — {PROGRESS_REPORT_EVERY}건 단위</summary>
    <div class="cklist">{''.join(blocks)}</div>
  </details>"""


def _short_reason(reason):
    """구간 요약에 들어갈 길이로 사유를 줄인다. 말머리([코드 판정] 등)는 뗀다. [v0.23.0]

    이 파일은 백슬래시를 넣지 않는 규칙이 있어 정규식 대신 문자열 처리로 쓴다(파일 전송 절차)."""
    text = str(reason or "").strip()
    if text.startswith("[") and "]" in text[:22]:
        text = text[text.index("]") + 1:].strip()
    text = " ".join(text.split())
    return (text[:110] + "…") if len(text) > 110 else (text or "사유 없음")


def _render_results(results, current_run, current_sheet=None, run_label=""):
    summary = {"PASS": 0, "FAIL": 0, "확인 필요": 0}
    rows_html = []
    for r in results:
        summary[r["result"]] = summary.get(r["result"], 0) + 1
        # [v0.10.0] 버튼을 눌러 새 탭으로 보던 것을 표 안에 바로 보이는 썸네일로 바꿨다.
        # 스크린샷은 full_page라 세로로 아주 길다. 위쪽(첫 화면)만 잘라 보여주고,
        # 누르면 [v0.20.0] 새 탭이 아니라 화면 위 팝업으로 전체를 띄운다.
        # href는 그대로 남겨둬서 Ctrl+클릭으로 새 탭을 여는 것도 계속 된다.
        # loading=lazy로 화면에 들어올 때만 받는다.
        shots = []
        for key, label in (("before_screenshot", "실행 전"), ("after_screenshot", "실행 후")):
            if r.get(key):
                url = _u('/img?path=') + _esc(r[key])
                caption = _esc(f"{r['tc_no']}. {r['title']} - {label}")
                shots.append(f'<a class="shot" href="{url}" target="_blank" data-cap="{caption}" '
                             f'title="{label} - 클릭하면 크게 보기">'
                             f'<img src="{url}" loading="lazy" alt="{label}">'
                             f'<span>{label}</span></a>')
        rows_html.append(f"""<tr>
  <td>{_esc(r['tc_no'])}</td>
  <td>{_esc(r.get('sheet') or '-')}</td>
  <td>{_esc(r['title'])}</td>
  <td>{_esc(r['priority'])}</td>
  <td>{_badge(r['result'])}</td>
  <td class="pre">{_esc(r.get('steps'))}</td>
  <td class="pre">{_esc(r.get('expected'))}</td>
  <td class="reason">{_esc((r['reason'] or '')[:300])}</td>
  <td class="shots">{''.join(shots) or '<span class="noshot">스크린샷 없음</span>'}</td>
</tr>""")

    summary_html = "".join(
        f'<span class="summary-item">{_badge(k)} {v}건</span>' for k, v in summary.items()
    )
    if results and current_run:
        # 프로젝트명을 붙여둔 실행이면 그 이름을 제목으로 쓴다 [v0.17.0]
        when = _when(results[0]["created_at"])
        title = f"{run_label} ({when})" if run_label else f"{when} 실행"
    else:
        title = "전체 결과 (최근 300건)"
    body = f"""
  <p class="sub"><a href="{_u('/')}">← 실행 내역 목록</a>{" · 시트: " + _esc(current_sheet or "(시트 없음)") if current_sheet is not None else ""}</p>
  <h2>{_esc(title)}</h2>
  <div class="sub">"확인 필요"는 실패가 아니라 <b>근거가 부족해 사람이 확인해야 하는 항목</b>입니다. 오른쪽 스크린샷을 누르면 팝업으로 크게 볼 수 있습니다 (화살표 키로 이동, Esc로 닫기).</div>
  <div class="summary">{summary_html}</div>
{_render_checkpoints(results)}
  <div class="tablewrap">
  <table>
    <thead><tr><th>No</th><th>시트 구분</th><th>테스트 항목</th><th>우선순위</th><th>결과</th><th>테스트 절차</th><th>예상 결과</th><th>사유</th><th>스크린샷</th></tr></thead>
    <tbody>{''.join(rows_html) or '<tr><td colspan="9">이 실행에는 결과가 없습니다</td></tr>'}</tbody>
  </table>
  </div>"""
    return _page("QA_runner_K 실행 결과", "results", body)


def _render_sheet_filter(sheets, current):
    """[NEW v0.14.0] 시트(화면)별 필터 줄. 시트가 하나뿐이면 굳이 보여주지 않는다."""
    if not sheets or (len(sheets) == 1 and not sheets[0]["sheet"]):
        return ""
    total = sum(s["total"] for s in sheets)
    chips = [f'<a class="chip{"" if current is not None else " on"}" href="{_u("/tcs")}">전체 ({total})</a>']
    for s in sheets:
        name = s["sheet"]
        label = name or "(시트 없음)"
        on = " on" if current is not None and current == name else ""
        chips.append(f'<a class="chip{on}" href="{_u("/tcs?sheet=")}{urllib.parse.quote(name)}">'
                     f'{_esc(label)} ({s["enabled"]}/{s["total"]})</a>')

    bulk = ""
    if current is not None:
        bulk = f"""
    <span class="bulk">
      <form method="post" action="{_u('/tcs/sheet_enable')}" style="display:inline">
        <input type="hidden" name="sheet" value="{_esc(current)}">
        <input type="hidden" name="enabled" value="1">
        <button type="submit" class="link">이 시트 전체 실행 포함</button>
      </form>
      <form method="post" action="{_u('/tcs/sheet_enable')}" style="display:inline">
        <input type="hidden" name="sheet" value="{_esc(current)}">
        <input type="hidden" name="enabled" value="0">
        <button type="submit" class="link">전체 제외</button>
      </form>
    </span>"""
    return f"""
  <div class="chips">
    <span class="chips-label">시트</span>
    {''.join(chips)}{bulk}
  </div>
  <div class="sub" style="margin:-6px 0 14px">괄호 안은 (실행 포함 / 전체) 건수입니다. 프로그램은 '실행 포함'인 TC만 돌립니다.</div>"""


def _render_tcs(tc_list, editing, msg, err, sheets=None, current_sheet=None):
    editing = editing or {}
    is_edit = bool(editing.get("id"))

    prio_options = ['<option value="">미지정</option>']
    for p in PRIORITIES:
        sel = " selected" if editing.get("priority") == p else ""
        prio_options.append(f'<option value="{p}"{sel}>{p}</option>')

    rows = []
    for tc in tc_list:
        off = "" if tc.get("enabled") else ' class="off"'
        no = _esc(tc.get("tc_no") or f"c{tc['id']}")
        toggle_label = "실행 제외" if tc.get("enabled") else "실행 포함"
        rows.append(f"""<tr{off}>
  <td>{no}</td>
  <td>{_esc(tc.get('sheet') or '-')}</td>
  <td>{_esc(tc.get('title'))}</td>
  <td>{_esc(tc.get('priority'))}</td>
  <td class="pre">{_esc(tc.get('steps'))}</td>
  <td class="pre">{_esc(tc.get('expected'))}</td>
  <td>{'포함' if tc.get('enabled') else '제외'}</td>
  <td>
    <div class="actions">
      <a href="{_u('/tcs?edit=')}{tc['id']}"><button type="button" class="link">수정</button></a>
      <form method="post" action="{_u('/tcs/toggle/')}{tc['id']}" style="display:inline">
        <button type="submit" class="link">{toggle_label}</button>
      </form>
      <form method="post" action="{_u('/tcs/delete/')}{tc['id']}" style="display:inline"
            onsubmit="return confirm('이 TC를 삭제할까요?')">
        <button type="submit" class="danger">삭제</button>
      </form>
    </div>
  </td>
</tr>""")

    msg_html = f'<div class="msg ok">{_esc(msg)}</div>' if msg else ""
    err_html = f'<div class="msg err">{_esc(err)}</div>' if err else ""
    enabled_count = sum(1 for t in tc_list if t.get("enabled"))
    title_suffix = f" - {_esc(current_sheet or '(시트 없음)')}" if current_sheet is not None else ""

    body = f"""
  <h2>TC 관리</h2>
  <div class="sub">엑셀 없이 여기서 TC를 작성하고, 프로그램에서 TC 소스를 <b>"대시보드 추가 TC"</b>로 선택해 그대로 실행할 수 있습니다.</div>
  {msg_html}{err_html}

  <div class="guide">
    <b>작성 규칙</b> — 프로그램이 이 표기를 보고 동작을 만듭니다.<br>
    · 클릭할 대상은 대괄호: <code>화면의 [환자 관리] 버튼 클릭</code><br>
    · 입력할 값은 따옴표: <code>[검색] 입력창에 "강의성" 입력</code><br>
    · 엔터는 그대로: <code>엔터 키 입력</code><br>
    · 절차는 <b>번호를 매겨 한 줄에 한 단계씩</b> 적어주세요. 대괄호로 적지 않은 버튼은 클릭하지 않습니다.<br>
    <br>
    <b>예상 결과 표기</b> — 무엇을 확인할지 이 표기로 알려주세요.<br>
    · 확인할 <b>항목명</b>이 여러 개면 쉼표로 나열: <code>목록에 No, 환자명, 성별, 병동 항목이 노출된다</code><br>
    · 확인할 <b>문구</b>는 따옴표: <code>"검색 조건에 맞는 환자가 없습니다" 문구가 노출된다</code><br>
    · 확인할 <b>버튼명</b>은 대괄호: <code>[환자 등록] 버튼이 노출된다</code><br>
    · "목록 / 항목 / 컬럼 / 화면" 같은 <b>자리를 가리키는 말은 확인 대상에서 빠집니다</b> — 쉼표로 나열한 항목명만 봅니다.<br>
    · "팝업이 노출된다" / "~화면으로 이동한다" 처럼 쓰면 팝업 등장·화면 이동을 직접 확인합니다.
  </div>

  <div class="card upload">
    <form method="post" action="{_u('/tcs/import')}" enctype="multipart/form-data">
      <label for="file">TC 엑셀 파일로 한 번에 추가</label>
      <div class="sub" style="margin-bottom:10px">
        확정된 포맷(No / 테스트 항목 / 사전조건 / 테스트 절차 / 예상 결과 / 우선순위 / 결과 / 비고)
        그대로 올리면 됩니다. <b>시트 이름에 "TC" 또는 "테스트케이스"가 들어간 시트는 모두</b> 읽고,
        시트 이름이 화면 구분값으로 붙어 아래에서 시트별로 걸러볼 수 있습니다.
        추가된 TC는 <b>실행 포함</b> 상태로 들어갑니다.
        <b>다시 가져오면 같은 시트·같은 No 의 TC는 새로 쌓이지 않고 최신 내용으로 덮어씁니다</b>
        (실행 포함/제외 상태는 그대로 유지됩니다).
      </div>
      <div class="actions">
        <input type="file" id="file" name="file" accept=".xlsx,.xlsm" required>
        <button type="submit" class="primary">엑셀에서 TC 가져오기</button>
      </div>
    </form>
  </div>

  <div class="card upload">
    <form method="post" action="{_u('/tcs/import_url')}">
      <label for="gurl">구글 스프레드시트 주소로 추가</label>
      <div class="sub" style="margin-bottom:10px">
        구글 시트 주소를 그대로 붙여넣으면 내려받지 않고 바로 가져옵니다. 시트 탭 이름에
        <b>TC</b>(또는 테스트케이스)가 들어가면 되고, 컬럼은 위와 동일해야 합니다. 시트가 여러 개면 전부 가져옵니다.
        시트가 <b>[공유] → '링크가 있는 모든 사용자'(뷰어)</b> 로 열려 있어야 읽을 수 있습니다.
        시트에서 TC를 고친 뒤 <b>같은 주소로 다시 가져오면 기존 TC가 최신 내용으로 갱신</b>됩니다.
      </div>
      <div class="actions">
        <input type="text" id="gurl" name="url" style="max-width:520px"
               placeholder="https://docs.google.com/spreadsheets/d/..../edit" required>
        <button type="submit" class="primary">구글 시트에서 가져오기</button>
      </div>
    </form>
  </div>

  <div class="card">
    <form method="post" action="{_u('/tcs/save')}">
      <input type="hidden" name="id" value="{_esc(editing.get('id', ''))}">
      <div class="grid">
        <div>
          <label class="req" for="title">테스트 항목</label>
          <input type="text" id="title" name="title" required
                 placeholder="예) 환자 등록 버튼 클릭 시 등록 팝업 노출 확인"
                 value="{_esc(editing.get('title', ''))}">
        </div>
        <div>
          <label for="priority">우선순위</label>
          <select id="priority" name="priority">{''.join(prio_options)}</select>
          &nbsp;<label style="display:inline" for="tc_no">No</label>
          <input type="text" id="tc_no" name="tc_no" style="width:90px" placeholder="자동"
                 value="{_esc(editing.get('tc_no', ''))}">
        </div>
        <div class="full">
          <label for="precondition">사전조건</label>
          <input type="text" id="precondition" name="precondition"
                 placeholder="예) 환자 관리 화면 진입 상태"
                 value="{_esc(editing.get('precondition', ''))}">
        </div>
        <div class="full">
          <label class="req" for="steps">테스트 절차</label>
          <textarea id="steps" name="steps" required
                    placeholder="1. 화면의 [환자 관리] 버튼 클릭&#10;2. [환자 등록] 버튼 클릭&#10;3. 팝업 노출 확인">{_esc(editing.get('steps', ''))}</textarea>
        </div>
        <div class="full">
          <label class="req" for="expected">예상 결과</label>
          <input type="text" id="expected" name="expected"
                 placeholder="예) 환자 등록 팝업이 노출된다"
                 value="{_esc(editing.get('expected', ''))}">
        </div>
        <div>
          <label for="sheet">시트(화면 구분)</label>
          <input type="text" id="sheet" name="sheet" placeholder="예) TC_환자관리"
                 value="{_esc(editing.get('sheet', '') or current_sheet or '')}">
        </div>
        <div>
          <label for="note">비고</label>
          <input type="text" id="note" name="note" value="{_esc(editing.get('note', ''))}">
        </div>
      </div>
      <div class="actions" style="margin-top:14px">
        <button type="submit" class="primary">{'TC 수정' if is_edit else 'TC 추가'}</button>
        {f'<a href="{_u("/tcs")}"><button type="button">취소</button></a>' if is_edit else ''}
      </div>
    </form>
  </div>

  <h2>추가된 TC{title_suffix} ({len(tc_list)}건 · 실행 대상 {enabled_count}건)</h2>
  <div class="sub">프로그램에서 <b>TC 소스 → "대시보드 추가 TC" → [TC 불러오기] → [시작]</b> 순서로 실행하세요.</div>
  {_render_sheet_filter(sheets, current_sheet)}
  <table>
    <thead><tr><th>No</th><th>시트</th><th>테스트 항목</th><th>우선순위</th><th>테스트 절차</th><th>예상 결과</th><th>실행</th><th></th></tr></thead>
    <tbody>{''.join(rows) or '<tr><td colspan="8">아직 추가된 TC가 없습니다. 위 폼에서 추가해보세요.</td></tr>'}</tbody>
  </table>"""
    return _page("QA_runner_K TC 관리", "tcs", body)


# ============================================================
# 서버 기동
# ============================================================
def _port_available(host, port):
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.bind((host, port))
        return True
    except OSError:
        return False
    finally:
        s.close()


def _pick_port(host="127.0.0.1"):
    """고정 포트를 우선 사용하고, 이미 쓰이는 중이면 빈 포트를 받아온다."""
    if _port_available(host, DEFAULT_PORT):
        return DEFAULT_PORT
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind((host, 0))
    port = s.getsockname()[1]
    s.close()
    return port


def find_running_dashboard(host="127.0.0.1", port=DEFAULT_PORT, timeout=1.0):
    """이미 떠 있는 QA_runner_K 대시보드가 있으면 (host, port)를, 없으면 None을 반환. [NEW v0.6.0]

    대시보드를 별도 프로그램(QA_Runner_K_Dashboard.exe)으로 먼저 띄워둔 경우,
    본 프로그램이 또 하나를 띄우지 않고 그걸 그대로 쓰도록 하기 위한 확인용.
    """
    import json
    import urllib.request
    try:
        with urllib.request.urlopen(f"http://{host}:{port}/healthz", timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        if data.get("app") == APP_MARKER:
            return host, port
    except Exception:
        pass
    return None


def run_in_background(db_path=None, host=None, port=None):
    """대시보드를 백그라운드 스레드로 띄우고 (host, port)를 반환.
    이미 실행 중인 서버가 있으면 새로 띄우지 않고 그 (host, port)를 재사용하는 건
    호출하는 쪽(qa_runner_k_gui.py)의 책임으로 둔다.

    기본은 127.0.0.1(내 PC에서만 보임). 같은 사무실 다른 PC에서도 보이게 하려면
    QA_RUNNER_K_BIND=0.0.0.0 으로 띄운다. 이때 접속자는 로컬이 아니므로 로그인 화면이 뜬다."""
    app = create_app(db_path)
    host = host or os.environ.get("QA_RUNNER_K_BIND", "").strip() or "127.0.0.1"
    port = port or _pick_port(host)
    thread = threading.Thread(
        target=lambda: app.run(host=host, port=port, debug=False, use_reloader=False),
        daemon=True,
    )
    thread.start()
    return host, port
