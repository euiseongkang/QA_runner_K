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

    def _reject_cross_site():
        """로컬 전용 서버이지만, 다른 사이트가 브라우저를 통해 POST를 보내는 것(CSRF)은 막는다.
        Origin 헤더가 있고 이 서버가 아니면 거부한다."""
        origin = request.headers.get("Origin")
        if origin and origin.rstrip("/") != request.host_url.rstrip("/"):
            abort(403)

    @app.route("/")
    def index():
        run_id = request.args.get("run_id") or None
        runs = results_store.list_runs(app.config["DB_PATH"])
        results = results_store.list_results(run_id=run_id, db_path=app.config["DB_PATH"])
        return _render_results(runs, results, run_id)

    @app.route("/healthz")
    def healthz():
        """이미 떠 있는 대시보드가 우리 것인지 확인하는 용도. [NEW v0.6.0]
        8765 포트를 다른 프로그램이 쓰고 있을 수도 있어서, 단순 포트 점유 여부로 판단하지 않는다."""
        return {"app": APP_MARKER, "db": results_store.get_db_path()}

    @app.route("/img")
    def img():
        # 스크린샷 저장 기준 디렉터리(qa_runner_k_screenshots) 하위 파일만 서빙.
        # 이게 없으면 ?path=/etc/passwd 같은 임의 경로를 그대로 읽어줄 수 있어서 필수 체크.
        path = request.args.get("path", "")
        base = os.path.realpath(os.path.join(results_store._base_dir(), results_store.SCREENSHOT_DIR_NAME))
        real = os.path.realpath(path) if path else ""
        if not path or not real.startswith(base + os.sep) or not os.path.isfile(real):
            abort(404)
        return send_file(real)

    # ---- TC 관리 ----                                            [NEW v0.4.0]
    @app.route("/tcs")
    def tcs():
        tc_list = results_store.list_custom_tcs(db_path=app.config["DB_PATH"])
        edit_id = request.args.get("edit")
        editing = None
        if edit_id:
            try:
                editing = results_store.get_custom_tc(edit_id, db_path=app.config["DB_PATH"])
            except Exception:
                editing = None
        return _render_tcs(tc_list, editing, request.args.get("msg", ""), request.args.get("err", ""))

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
                    tc_no=f.get("tc_no"), note=f.get("note"), db_path=app.config["DB_PATH"],
                )
                msg = f"TC를 수정했습니다"
            else:
                results_store.insert_custom_tc(
                    f.get("title"), f.get("steps"), f.get("expected"),
                    precondition=f.get("precondition"), priority=f.get("priority"),
                    tc_no=f.get("tc_no"), note=f.get("note"), db_path=app.config["DB_PATH"],
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

        # 같은 파일을 두 번 올려도 목록이 중복으로 불어나지 않게, 내용이 같은 TC는 건너뛴다
        existing = {
            (t.get("title"), (t.get("steps") or "").strip(), t.get("expected"))
            for t in results_store.list_custom_tcs(db_path=app.config["DB_PATH"])
        }
        added = skipped = failed = 0
        for t in tcs:
            key = (t["title"], t["steps"].strip(), t["expected"])
            if key in existing:
                skipped += 1
                continue
            try:
                results_store.insert_custom_tc(
                    t["title"], t["steps"], t["expected"],
                    precondition=t["precondition"], priority=t["priority"],
                    tc_no=t["no"], note=t["note"] or f"[{os.path.basename(f.filename)}]",
                    db_path=app.config["DB_PATH"],
                )
                existing.add(key)
                added += 1
            except Exception:
                failed += 1

        parts = [f"엑셀에서 TC {added}건 추가"]
        if skipped:
            parts.append(f"중복 {skipped}건 건너뜀")
        if failed:
            parts.append(f"저장 실패 {failed}건")
        if warnings:
            parts.append(" / ".join(warnings[:3]))
        if added:
            parts.append("프로그램에서 [TC 불러오기] 후 [시작]하면 실행됩니다")
        msg = " · ".join(parts)
        # 전부 중복이라 추가된 게 없는 건 오류가 아니므로 경고색으로 띄우지 않는다
        ok = bool(added) or (skipped and not failed)
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
  .wrap { max-width: 1120px; margin: 0 auto; padding: 20px 16px 48px; }
  nav { background: #22262e; padding: 0 16px; }
  nav .inner { max-width: 1120px; margin: 0 auto; display: flex; gap: 4px; align-items: center; }
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
  @media (max-width: 900px) { a.shot img { width: 150px; height: 110px; } }
  .off { opacity: 0.45; }
  .actions { display: flex; gap: 8px; align-items: center; margin-top: 4px; flex-wrap: nowrap; }
  td .actions button { white-space: nowrap; }
  @media (max-width: 720px) { .grid { grid-template-columns: 1fr; } }
"""


def _page(title, active, body):
    def cls(name):
        return ' class="on"' if name == active else ""
    user = dashboard_auth.current_user()
    account = (f'<span class="who">{_esc(user)}</span><a href="/logout">로그아웃</a>'
               if user else "")
    return f"""<!doctype html>
<html lang="ko"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{_esc(title)}</title>
<style>{STYLE}</style></head>
<body>
  <nav><div class="inner">
    <span class="brand">QA_runner_K</span>
    <a href="/"{cls('results')}>실행 결과</a>
    <a href="/tcs"{cls('tcs')}>TC 관리</a>
    {account}
  </div></nav>
  <div class="wrap">{body}</div>
</body></html>"""


def _render_results(runs, results, current_run):
    run_options = ['<option value="">전체 (최근 300건)</option>']
    for run_id, source, source_ref, started_at, count in runs:
        label = f"{run_id} · {source} · {os.path.basename(str(source_ref or ''))} ({count}건)"
        selected = " selected" if run_id == current_run else ""
        run_options.append(f'<option value="{_esc(run_id)}"{selected}>{_esc(label)}</option>')

    summary = {"PASS": 0, "FAIL": 0, "확인 필요": 0}
    rows_html = []
    for r in results:
        summary[r["result"]] = summary.get(r["result"], 0) + 1
        # [v0.10.0] 버튼을 눌러 새 탭으로 보던 것을 표 안에 바로 보이는 썸네일로 바꿨다.
        # 스크린샷은 full_page라 세로로 아주 길다. 위쪽(첫 화면)만 잘라 보여주고,
        # 눌러서 전체를 새 탭으로 여는 건 그대로 둔다. loading=lazy로 화면에 들어올 때만 받는다.
        shots = []
        for key, label in (("before_screenshot", "실행 전"), ("after_screenshot", "실행 후")):
            if r.get(key):
                url = f'/img?path={_esc(r[key])}'
                shots.append(f'<a class="shot" href="{url}" target="_blank" title="{label} - 클릭하면 전체 화면">'
                             f'<img src="{url}" loading="lazy" alt="{label}">'
                             f'<span>{label}</span></a>')
        rows_html.append(f"""<tr>
  <td>{_esc(r['tc_no'])}</td>
  <td>{_esc(r['title'])}</td>
  <td>{_esc(r['priority'])}</td>
  <td>{_badge(r['result'])}</td>
  <td class="reason">{_esc((r['reason'] or '')[:300])}</td>
  <td class="shots">{''.join(shots) or '<span class="noshot">스크린샷 없음</span>'}</td>
</tr>""")

    summary_html = "".join(
        f'<span class="summary-item">{_badge(k)} {v}건</span>' for k, v in summary.items()
    )
    body = f"""
  <h2>실행 결과</h2>
  <div class="sub">"확인 필요"는 실패가 아니라 <b>근거가 부족해 사람이 확인해야 하는 항목</b>입니다. 오른쪽 스크린샷을 눌러 전체 화면으로 확인하세요.</div>
  <div class="summary">{summary_html}</div>
  <form method="get">
    <label for="run_id">실행 배치</label>
    <select id="run_id" name="run_id" onchange="this.form.submit()">{''.join(run_options)}</select>
  </form>
  <br>
  <table>
    <thead><tr><th>No</th><th>테스트 항목</th><th>우선순위</th><th>결과</th><th>사유</th><th>스크린샷</th></tr></thead>
    <tbody>{''.join(rows_html) or '<tr><td colspan="6">아직 결과가 없습니다</td></tr>'}</tbody>
  </table>"""
    return _page("QA_runner_K 실행 결과", "results", body)


def _render_tcs(tc_list, editing, msg, err):
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
  <td>{_esc(tc.get('title'))}</td>
  <td>{_esc(tc.get('priority'))}</td>
  <td class="pre">{_esc(tc.get('steps'))}</td>
  <td class="pre">{_esc(tc.get('expected'))}</td>
  <td>{'포함' if tc.get('enabled') else '제외'}</td>
  <td>
    <div class="actions">
      <a href="/tcs?edit={tc['id']}"><button type="button" class="link">수정</button></a>
      <form method="post" action="/tcs/toggle/{tc['id']}" style="display:inline">
        <button type="submit" class="link">{toggle_label}</button>
      </form>
      <form method="post" action="/tcs/delete/{tc['id']}" style="display:inline"
            onsubmit="return confirm('이 TC를 삭제할까요?')">
        <button type="submit" class="danger">삭제</button>
      </form>
    </div>
  </td>
</tr>""")

    msg_html = f'<div class="msg ok">{_esc(msg)}</div>' if msg else ""
    err_html = f'<div class="msg err">{_esc(err)}</div>' if err else ""
    enabled_count = sum(1 for t in tc_list if t.get("enabled"))

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
    · 예상 결과에 "팝업이 노출된다" / "~화면으로 이동한다" 처럼 쓰면 팝업 등장·화면 이동을 직접 확인합니다.
  </div>

  <div class="card upload">
    <form method="post" action="/tcs/import" enctype="multipart/form-data">
      <label for="file">TC 엑셀 파일로 한 번에 추가</label>
      <div class="sub" style="margin-bottom:10px">
        확정된 포맷("테스트케이스" 시트 · No / 테스트 항목 / 사전조건 / 테스트 절차 / 예상 결과 / 우선순위 / 결과 / 비고)
        그대로 올리면 됩니다. 프로그램이 엑셀을 직접 읽을 때와 <b>같은 방식으로 해석</b>되고,
        추가된 TC는 <b>실행 포함</b> 상태로 들어갑니다. 같은 내용의 TC는 중복 추가하지 않습니다.
      </div>
      <div class="actions">
        <input type="file" id="file" name="file" accept=".xlsx,.xlsm" required>
        <button type="submit" class="primary">엑셀에서 TC 가져오기</button>
      </div>
    </form>
  </div>

  <div class="card">
    <form method="post" action="/tcs/save">
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
        <div class="full">
          <label for="note">비고</label>
          <input type="text" id="note" name="note" value="{_esc(editing.get('note', ''))}">
        </div>
      </div>
      <div class="actions" style="margin-top:14px">
        <button type="submit" class="primary">{'TC 수정' if is_edit else 'TC 추가'}</button>
        {'<a href="/tcs"><button type="button">취소</button></a>' if is_edit else ''}
      </div>
    </form>
  </div>

  <h2>추가된 TC ({len(tc_list)}건 · 실행 대상 {enabled_count}건)</h2>
  <div class="sub">프로그램에서 <b>TC 소스 → "대시보드 추가 TC" → [TC 불러오기] → [시작]</b> 순서로 실행하세요.</div>
  <table>
    <thead><tr><th>No</th><th>테스트 항목</th><th>우선순위</th><th>테스트 절차</th><th>예상 결과</th><th>실행</th><th></th></tr></thead>
    <tbody>{''.join(rows) or '<tr><td colspan="7">아직 추가된 TC가 없습니다. 위 폼에서 추가해보세요.</td></tr>'}</tbody>
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
