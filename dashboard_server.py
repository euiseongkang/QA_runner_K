#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""QA_runner_K 결과 대시보드 - 로컬에서만 뜨는 조회용 웹 페이지.

프로그램(qa_runner_k_gui.py)의 "결과 보기" 버튼을 누르면 이 Flask 앱이 백그라운드 스레드로
127.0.0.1의 임의 포트에서 뜨고, 기본 브라우저가 자동으로 열린다. 외부에 노출되는 서버가 아니라
로컬 전용 조회 화면이라는 점에 유의 (TODO: 필요해지면 EC2 쪽에 결과 API를 붙여 원격 조회로 확장).
"""

import os
import socket
import threading

from flask import Flask, request, send_file, abort

import results_store

RESULT_STYLE = {
    "PASS": ("PASS", "#1f9d55", "#e7f8ee"),
    "FAIL": ("FAIL", "#c0392b", "#fdecec"),
    "확인 필요": ("확인 필요", "#b7791f", "#fff6e0"),
}


def create_app(db_path=None):
    app = Flask(__name__)
    app.config["DB_PATH"] = db_path

    @app.route("/")
    def index():
        run_id = request.args.get("run_id") or None
        runs = results_store.list_runs(app.config["DB_PATH"])
        results = results_store.list_results(run_id=run_id, db_path=app.config["DB_PATH"])
        return _render(runs, results, run_id)

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

    return app


def _badge(result):
    label, color, bg = RESULT_STYLE.get(result, (result, "#555", "#eee"))
    return f'<span class="badge" style="color:{color};background:{bg}">{label}</span>'


def _esc(s):
    return (str(s or "")
            .replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def _render(runs, results, current_run):
    run_options = ['<option value="">전체 (최근 300건)</option>']
    for run_id, source, source_ref, started_at, count in runs:
        label = f"{run_id} · {source} · {source_ref or ''} ({count}건)"
        selected = "selected" if run_id == current_run else ""
        run_options.append(f'<option value="{_esc(run_id)}" {selected}>{_esc(label)}</option>')

    summary = {"PASS": 0, "FAIL": 0, "확인 필요": 0}
    rows_html = []
    for r in results:
        summary[r["result"]] = summary.get(r["result"], 0) + 1
        shots = []
        if r.get("before_screenshot"):
            shots.append(f'<a href="/img?path={_esc(r["before_screenshot"])}" target="_blank">전</a>')
        if r.get("after_screenshot"):
            shots.append(f'<a href="/img?path={_esc(r["after_screenshot"])}" target="_blank">후</a>')
        rows_html.append(f"""<tr>
  <td>{_esc(r['tc_no'])}</td>
  <td>{_esc(r['title'])}</td>
  <td>{_esc(r['priority'])}</td>
  <td>{_badge(r['result'])}</td>
  <td class="reason">{_esc((r['reason'] or '')[:200])}</td>
  <td>{' / '.join(shots) or '-'}</td>
</tr>""")

    summary_html = "".join(
        f'<span class="summary-item">{_badge(k)} {v}건</span>' for k, v in summary.items()
    )

    return f"""<!doctype html>
<html lang="ko"><head><meta charset="utf-8">
<title>QA_runner_K 결과</title>
<style>
  body {{ font-family: -apple-system, "Segoe UI", sans-serif; margin: 24px; background: #fafafa; color:#222; }}
  h2 {{ margin-bottom: 4px; }}
  .summary {{ margin: 8px 0 16px; }}
  .summary-item {{ margin-right: 14px; font-size: 14px; }}
  table {{ border-collapse: collapse; width: 100%; background: #fff; }}
  th, td {{ border: 1px solid #e4e4e4; padding: 8px 10px; font-size: 13px; text-align: left; vertical-align: top; }}
  th {{ background: #f4f5f7; }}
  td.reason {{ max-width: 420px; }}
  .badge {{ padding: 2px 10px; border-radius: 12px; font-weight: 600; font-size: 12px; }}
  select {{ padding: 6px; font-size: 14px; }}
</style></head>
<body>
  <h2>QA_runner_K 실행 결과</h2>
  <div class="summary">{summary_html}</div>
  <form method="get">
    <label>실행 배치: </label>
    <select name="run_id" onchange="this.form.submit()">{''.join(run_options)}</select>
  </form>
  <br>
  <table>
    <thead><tr><th>No</th><th>테스트 항목</th><th>우선순위</th><th>결과</th><th>사유</th><th>스크린샷</th></tr></thead>
    <tbody>{''.join(rows_html) or '<tr><td colspan="6">아직 결과가 없습니다</td></tr>'}</tbody>
  </table>
</body></html>"""


def _pick_free_port(host="127.0.0.1"):
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind((host, 0))
    port = s.getsockname()[1]
    s.close()
    return port


def run_in_background(db_path=None, host="127.0.0.1"):
    """대시보드를 백그라운드 스레드로 띄우고 (host, port)를 반환.
    이미 실행 중인 서버가 있으면 새로 띄우지 않고 그 (host, port)를 재사용하는 건
    호출하는 쪽(qa_runner_k_gui.py)의 책임으로 둔다."""
    app = create_app(db_path)
    port = _pick_free_port(host)
    thread = threading.Thread(
        target=lambda: app.run(host=host, port=port, debug=False, use_reloader=False),
        daemon=True,
    )
    thread.start()
    return host, port
