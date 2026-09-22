#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""QA_runner_K 실행 결과 로컬 저장소 (SQLite, 표준 라이브러리만 사용).

로컬 엑셀 파일을 TC 소스로 쓰는 경우 EC2 백엔드가 없으므로, 실행 결과(PASS/FAIL/확인 필요)와
전/후 스크린샷 경로를 로컬 DB에 남기고 `dashboard_server.py`가 이를 읽어 브라우저 페이지로 보여준다.
EC2를 TC 소스로 쓰는 경우에도 동일하게 로컬에 남겨서, 로컬/EC2 어느 쪽이든 같은 결과 화면으로 볼 수
있게 한다 (EC2 자체 제출은 qa_runner_k_gui.py의 _submit_result_ec2에서 별도로 처리).
"""

import os
import sqlite3
import time

DB_FILENAME = "qa_runner_k_results.db"
SCREENSHOT_DIR_NAME = "qa_runner_k_screenshots"

SCHEMA = """
CREATE TABLE IF NOT EXISTS results (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL,
    source TEXT NOT NULL,          -- 'local' | 'ec2'
    source_ref TEXT,               -- 로컬: 엑셀 파일 경로 / EC2: session_id
    tc_no TEXT,
    title TEXT,
    priority TEXT,
    precondition TEXT,
    steps TEXT,
    expected TEXT,
    result TEXT NOT NULL,          -- 'PASS' | 'FAIL' | '확인 필요'
    reason TEXT,
    sheet TEXT,                    -- TC가 나온 시트 이름 = 화면별 구분값 [v0.15.0]
    before_screenshot TEXT,        -- 로컬 파일 경로 (없으면 NULL)
    after_screenshot TEXT,
    created_at REAL NOT NULL
);
"""


# [NEW v0.4.0] 대시보드에서 직접 추가하는 TC. 엑셀을 만들지 않고도 화면에서 TC를 작성해
# 바로 실행할 수 있게 하기 위한 테이블. 컬럼 구성은 TC 엑셀 포맷(8컬럼)과 일부러 맞춰둔다.
# [NEW v0.17.0] 실행 배치에 사람이 알아볼 이름을 붙인다. 목록에 "20260915_115050" 같은
# 식별자만 늘어놓으면 어느 회차가 뭐였는지 알 수 없어서, 프로젝트명을 따로 둔다.
# results 행마다 같은 값을 적지 않고 별도 테이블로 두어, 이름만 바꿀 때 결과를 건드리지 않는다.
RUN_LABEL_SCHEMA = """
CREATE TABLE IF NOT EXISTS run_labels (
    run_id TEXT PRIMARY KEY,
    label TEXT NOT NULL,
    updated_at REAL NOT NULL
);
"""


CUSTOM_TC_SCHEMA = """
CREATE TABLE IF NOT EXISTS custom_tcs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tc_no TEXT,                    -- 비어 있으면 화면에서 c<id>로 표시
    title TEXT NOT NULL,           -- 테스트 항목
    precondition TEXT,             -- 사전조건
    steps TEXT NOT NULL,           -- 테스트 절차 (번호 매긴 줄)
    expected TEXT NOT NULL,        -- 예상 결과
    priority TEXT,                 -- P1~P4
    note TEXT,                     -- 비고
    sheet TEXT,                    -- 출처 시트 이름 = 화면별 구분값 [v0.14.0]
    enabled INTEGER NOT NULL DEFAULT 1,
    created_at REAL NOT NULL
);
"""


def _base_dir():
    """exe로 빌드됐을 때도 실행 파일 옆에 DB/스크린샷을 두기 위한 기준 경로."""
    import sys
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


def get_db_path():
    return os.environ.get("QA_RUNNER_K_DB_PATH") or os.path.join(_base_dir(), DB_FILENAME)


def get_screenshot_root():
    """스크린샷 보관 기준 폴더. [NEW v0.24.0]

    내 PC에서는 예전처럼 exe(또는 소스) 옆의 qa_runner_k_screenshots 폴더를 쓴다.
    서버(도커)에서는 데이터 볼륨을 가리켜야 하므로 환경변수로 바꿀 수 있게 했다.
    /img 서빙과 삭제도 전부 이 함수 하나를 기준으로 삼는다 - 기준이 갈리면
    '화면에는 보이는데 파일은 못 찾는' 상태가 생긴다."""
    return (os.environ.get("QA_RUNNER_K_SCREENSHOT_DIR")
            or os.path.join(_base_dir(), SCREENSHOT_DIR_NAME))


def get_screenshot_dir(run_id: str):
    d = os.path.join(get_screenshot_root(), run_id)
    os.makedirs(d, exist_ok=True)
    return d


def _connect(db_path=None):
    # [v0.6.0] 대시보드를 별도 프로그램으로도 띄울 수 있게 되면서, 같은 DB 파일을 두 프로세스가
    # 함께 열 수 있다. 잠깐 겹칠 때 "database is locked"로 죽지 않도록 대기 시간을 준다.
    conn = sqlite3.connect(db_path or get_db_path(), timeout=10)
    conn.execute(SCHEMA)
    conn.execute(CUSTOM_TC_SCHEMA)
    conn.execute(RUN_LABEL_SCHEMA)
    _migrate(conn)
    return conn


def _migrate(conn):
    """예전 버전에서 만든 DB에 새 컬럼을 채워 넣는다. [NEW v0.14.0]

    이미 쓰던 DB가 강의성님 PC에 있으므로, 컬럼을 추가할 때 파일을 지우게 하면 안 된다.
    CREATE TABLE IF NOT EXISTS 는 기존 테이블을 건드리지 않으니 ALTER로 따로 채운다."""
    for table in ("custom_tcs", "results"):
        try:
            cols = {r[1] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()}
            if "sheet" not in cols:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN sheet TEXT")
                conn.commit()
        except Exception:
            pass      # 마이그레이션 실패로 프로그램이 안 뜨는 일은 없게 한다

    # [v0.16.0] 이미 들어간 "1.0" 같은 TC 번호를 "1"로 정리한다.
    # 구글 시트를 거치면 숫자가 실수로 와서 생긴 흔적이라, 다시 올리지 않아도 고쳐지게 한다.
    import re as _re
    for table in ("custom_tcs", "results"):
        try:
            rows = conn.execute(
                f"SELECT id, tc_no FROM {table} WHERE tc_no LIKE '%.0'").fetchall()
            fixed = [(r[1][:-2], r[0]) for r in rows if _re.fullmatch(r"\d+\.0", r[1] or "")]
            if fixed:
                conn.executemany(f"UPDATE {table} SET tc_no=? WHERE id=?", fixed)
                conn.commit()
        except Exception:
            pass


def insert_result(tc: dict, result: str, reason: str, source: str, source_ref: str,
                   run_id: str, before_screenshot=None, after_screenshot=None, db_path=None):
    conn = _connect(db_path)
    try:
        conn.execute(
            """INSERT INTO results
               (run_id, source, source_ref, tc_no, title, priority, precondition, steps, expected,
                result, reason, sheet, before_screenshot, after_screenshot, created_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                run_id, source, source_ref,
                str(tc.get("tc_id", "")), tc.get("title", ""), tc.get("priority", ""),
                tc.get("precondition", ""), tc.get("steps", ""), tc.get("expected", ""),
                result, reason or "", tc.get("sheet_name", ""),
                before_screenshot, after_screenshot, time.time(),
            ),
        )
        conn.commit()
    finally:
        conn.close()


_SAFE_NAME_MAX = 80


def _safe_segment(name, fallback):
    """경로 한 조각만 남긴다 - '../', 절대경로, 드라이브 문자를 전부 떨어낸다. [NEW v0.26.0]

    서버가 PC에서 올라온 이름을 그대로 파일 경로에 쓰면 스크린샷 폴더 밖에 파일을 쓸 수 있다.
    받은 값은 믿지 않고 여기서 한 번 깎아낸 뒤에만 쓴다."""
    name = os.path.basename(str(name or "").replace("\\", "/").strip())
    out = "".join(c for c in name if c.isalnum() or c in "-_.").lstrip(".")[:_SAFE_NAME_MAX]
    return out or fallback


def upsert_result_row(row: dict, db_path=None):
    """[NEW v0.26.0] 프로그램(PC)이 보낸 결과 한 건을 기록한다. 이미 있으면 덮어쓴다.

    PC는 로컬에 먼저 저장한 뒤 서버로 보내고, 실패하면 나중에 다시 보낸다.
    그래서 같은 건이 두 번 올 수 있고, 두 번 와도 줄이 겹치면 안 된다.
    기준은 run_id + tc_no + title - tc_no가 비어 있는 대시보드 TC까지 구분하기 위해
    title을 같이 본다 (v0.18.0에서 TC 가져오기를 '추가'에서 '갱신'으로 바꿀 때와 같은 기준).

    반환: "insert" 또는 "update"
    """
    fields = ("run_id", "source", "source_ref", "tc_no", "title", "priority",
              "precondition", "steps", "expected", "result", "reason", "sheet",
              "before_screenshot", "after_screenshot")
    v = {k: _clip(str(row.get(k) or "")) for k in fields}
    if not v["run_id"] or not v["result"]:
        raise ValueError("run_id 와 result 는 필수입니다")
    for k in ("before_screenshot", "after_screenshot"):
        v[k] = v[k] or None
    try:
        created = float(row.get("created_at"))
    except (TypeError, ValueError):
        created = time.time()

    conn = _connect(db_path)
    try:
        found = conn.execute(
            "SELECT id FROM results WHERE run_id=? AND IFNULL(tc_no,'')=? AND IFNULL(title,'')=?",
            (v["run_id"], v["tc_no"], v["title"]),
        ).fetchone()
        if found:
            conn.execute(
                """UPDATE results SET source=?, source_ref=?, priority=?, precondition=?,
                       steps=?, expected=?, result=?, reason=?, sheet=?,
                       before_screenshot=?, after_screenshot=?, created_at=?
                   WHERE id=?""",
                (v["source"], v["source_ref"], v["priority"], v["precondition"], v["steps"],
                 v["expected"], v["result"], v["reason"], v["sheet"],
                 v["before_screenshot"], v["after_screenshot"], created, found[0]),
            )
            action = "update"
        else:
            conn.execute(
                """INSERT INTO results
                   (run_id, source, source_ref, tc_no, title, priority, precondition, steps,
                    expected, result, reason, sheet, before_screenshot, after_screenshot, created_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (v["run_id"], v["source"], v["source_ref"], v["tc_no"], v["title"], v["priority"],
                 v["precondition"], v["steps"], v["expected"], v["result"], v["reason"], v["sheet"],
                 v["before_screenshot"], v["after_screenshot"], created),
            )
            action = "insert"
        conn.commit()
        return action
    finally:
        conn.close()


def save_uploaded_screenshot(run_id, filename, data):
    """[NEW v0.26.0] PC가 올린 스크린샷을 저장하고, DB에 넣을 상대 경로를 돌려준다.

    DB에는 '<run_id>/<파일명>'만 넣는다. v0.24.0에서 겪은 그대로, 절대 경로를 넣으면
    다른 컴퓨터로 옮기는 순간 전부 깨진다. 이름은 받은 값을 믿지 않고 깎아서 쓴다."""
    rid = _safe_segment(run_id, "unknown_run")
    fn = _safe_segment(filename, "shot.png")
    if not fn.lower().endswith(".png"):
        fn += ".png"
    path = os.path.join(get_screenshot_dir(rid), fn)
    real = os.path.realpath(path)
    root = os.path.realpath(get_screenshot_root())
    if not real.startswith(root + os.sep):
        raise ValueError("스크린샷 경로가 기준 폴더를 벗어납니다")
    with open(real, "wb") as f:
        f.write(data)
    return rid + "/" + fn


def purge_old_runs(days=30, db_path=None):
    """[NEW v0.26.0] 오래된 실행 내역과 스크린샷을 지운다. 반환: (지운 배치 수, 지운 줄 수)

    스크린샷이 계속 쌓이면 서버 디스크가 언젠가 찬다(현재 20G 중 11G 여유).
    days가 0 이하이면 아무 것도 지우지 않는다 - 정리를 끄는 방법."""
    if not days or days <= 0:
        return (0, 0)
    cutoff = time.time() - days * 86400
    conn = _connect(db_path)
    try:
        rows = conn.execute(
            "SELECT run_id FROM results GROUP BY run_id HAVING MAX(created_at) < ?",
            (cutoff,),
        ).fetchall()
    finally:
        conn.close()
    runs = lines = 0
    for (run_id,) in rows:
        try:
            lines += delete_run(run_id, db_path=db_path, remove_screenshots=True)
            runs += 1
        except Exception:
            pass          # 한 배치가 안 지워져도 나머지 정리는 계속한다
    return (runs, lines)


def list_runs(db_path=None):
    """실행 배치(run_id) 목록을 최신순으로. [(run_id, source, source_ref, started_at, count), ...]"""
    conn = _connect(db_path)
    try:
        rows = conn.execute(
            """SELECT run_id, source, source_ref, MIN(created_at), COUNT(*)
               FROM results GROUP BY run_id ORDER BY MIN(created_at) DESC"""
        ).fetchall()
        return rows
    finally:
        conn.close()


def list_runs_summary(sheet=None, db_path=None):
    """실행 배치 목록 + 배치별 판정 집계. 대시보드 첫 화면(목록)에서 쓴다. [NEW v0.12.0]
    [{run_id, source, source_ref, started_at, total, passed, failed, unsure, sheets}, ...] 최신순.
    sheet를 주면 그 시트의 TC가 포함된 배치만 남긴다. [v0.15.0]"""
    conn = _connect(db_path)
    try:
        sql = """SELECT run_id, source, source_ref, MIN(created_at), COUNT(*),
                        SUM(CASE WHEN result='PASS' THEN 1 ELSE 0 END),
                        SUM(CASE WHEN result='FAIL' THEN 1 ELSE 0 END),
                        SUM(CASE WHEN result NOT IN ('PASS','FAIL') THEN 1 ELSE 0 END),
                        GROUP_CONCAT(DISTINCT IFNULL(sheet,''))
                 FROM results"""
        args = []
        if sheet is not None:
            sql += " WHERE run_id IN (SELECT run_id FROM results WHERE IFNULL(sheet,'')=?)"
            args.append(str(sheet))
        sql += " GROUP BY run_id ORDER BY MIN(created_at) DESC"
        rows = conn.execute(sql, args).fetchall()
        labels = dict(conn.execute("SELECT run_id, label FROM run_labels").fetchall())
        return [
            {"run_id": r[0], "source": r[1], "source_ref": r[2], "started_at": r[3],
             "total": r[4], "passed": r[5] or 0, "failed": r[6] or 0, "unsure": r[7] or 0,
             "sheets": [s for s in sorted((r[8] or "").split(",")) if s],
             "label": labels.get(r[0], "")}
            for r in rows
        ]
    finally:
        conn.close()


def set_run_label(run_id, label, db_path=None):
    """실행 배치의 프로젝트명을 지정/변경. 빈 값이면 이름을 지운다. [NEW v0.17.0]"""
    run_id = str(run_id or "").strip()
    if not run_id:
        raise ValueError("run_id가 필요합니다")
    label = _clip(label, 120)
    conn = _connect(db_path)
    try:
        if label:
            conn.execute(
                "INSERT INTO run_labels (run_id, label, updated_at) VALUES (?,?,?) "
                "ON CONFLICT(run_id) DO UPDATE SET label=excluded.label, "
                "updated_at=excluded.updated_at",
                (run_id, label, time.time()))
        else:
            conn.execute("DELETE FROM run_labels WHERE run_id=?", (run_id,))
        conn.commit()
        return label
    finally:
        conn.close()


def get_run_label(run_id, db_path=None):
    conn = _connect(db_path)
    try:
        row = conn.execute("SELECT label FROM run_labels WHERE run_id=?",
                           (str(run_id or ""),)).fetchone()
        return row[0] if row else ""
    finally:
        conn.close()


def list_result_sheets(db_path=None):
    """실행 결과에 들어 있는 시트(화면)별 건수. 실행 내역 필터용. [NEW v0.15.0]"""
    conn = _connect(db_path)
    try:
        rows = conn.execute(
            """SELECT IFNULL(sheet,''), COUNT(*), COUNT(DISTINCT run_id)
               FROM results GROUP BY IFNULL(sheet,'') ORDER BY IFNULL(sheet,'')"""
        ).fetchall()
        return [{"sheet": r[0], "total": r[1], "runs": r[2]} for r in rows]
    finally:
        conn.close()


def _remove_screenshot_dir(run_id):
    """해당 배치의 스크린샷 폴더를 지운다.
    run_id에 경로 조작 문자가 섞여 있어도 스크린샷 루트 밖을 건드리지 못하게 확인한다."""
    import shutil
    root = os.path.realpath(get_screenshot_root())
    target = os.path.realpath(os.path.join(root, str(run_id)))
    if target.startswith(root + os.sep) and os.path.isdir(target):
        shutil.rmtree(target, ignore_errors=True)
        return True
    return False


def delete_run(run_id, db_path=None, remove_screenshots=True):
    """실행 배치 하나를 통째로 삭제(결과 행 + 스크린샷 파일). 지운 행 수를 반환. [NEW v0.12.0]

    스크린샷은 용량을 많이 차지하므로 결과와 함께 지운다. 되돌릴 수 없으니
    화면에서 한 번 더 확인을 받은 뒤 호출한다."""
    run_id = str(run_id or "").strip()
    if not run_id:
        raise ValueError("run_id가 필요합니다")
    conn = _connect(db_path)
    try:
        cur = conn.execute("DELETE FROM results WHERE run_id=?", (run_id,))
        conn.execute("DELETE FROM run_labels WHERE run_id=?", (run_id,))   # [v0.17.0]
        conn.commit()
        deleted = cur.rowcount
    finally:
        conn.close()
    if remove_screenshots:
        _remove_screenshot_dir(run_id)
    return deleted


def list_results(run_id=None, db_path=None, limit=300, sheet=None):
    """실행 결과 행. sheet를 주면 그 시트(화면)의 결과만. [sheet: v0.15.0]"""
    conn = _connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        where, args = [], []
        if run_id:
            where.append("run_id=?")
            args.append(run_id)
        if sheet is not None:
            where.append("IFNULL(sheet,'')=?")
            args.append(str(sheet))
        sql = "SELECT * FROM results"
        if where:
            sql += " WHERE " + " AND ".join(where)
        if run_id:
            sql += " ORDER BY id"
        else:
            sql += " ORDER BY id DESC LIMIT ?"
            args.append(limit)
        return [dict(r) for r in conn.execute(sql, args).fetchall()]
    finally:
        conn.close()


# ============================================================
# 대시보드에서 추가한 TC (custom_tcs)                          [NEW v0.4.0]
# ============================================================
MAX_FIELD_LEN = 4000


def _clip(value, limit=MAX_FIELD_LEN):
    """입력이 비정상적으로 길 때 DB/화면이 깨지지 않게 자른다 (로컬 전용이라 검증은 최소한만)."""
    return (str(value or "").strip())[:limit]


def insert_custom_tc(title, steps, expected, precondition="", priority="", tc_no="", note="",
                     sheet="", db_path=None):
    """대시보드 입력 폼에서 TC 1건 추가. 추가된 row id 반환.
    필수는 테스트 항목/테스트 절차/예상 결과 3개 (엑셀 로더의 필수 컬럼과 동일 기준).
    sheet는 엑셀/구글 시트의 시트 이름 = 화면별 구분값. [v0.14.0]"""
    title, steps, expected = _clip(title), _clip(steps), _clip(expected)
    if not title or not steps or not expected:
        raise ValueError("테스트 항목 / 테스트 절차 / 예상 결과는 필수입니다")
    conn = _connect(db_path)
    try:
        cur = conn.execute(
            """INSERT INTO custom_tcs
               (tc_no, title, precondition, steps, expected, priority, note, sheet,
                enabled, created_at)
               VALUES (?,?,?,?,?,?,?,?,1,?)""",
            (_clip(tc_no, 40), title, _clip(precondition), steps, expected,
             _clip(priority, 20), _clip(note, 500), _clip(sheet, 100), time.time()),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def update_custom_tc(row_id, title, steps, expected, precondition="", priority="", tc_no="",
                     note="", sheet="", db_path=None):
    """기존 TC 수정. 화면에서 문구를 고쳐 다시 돌릴 수 있게 하기 위한 것."""
    title, steps, expected = _clip(title), _clip(steps), _clip(expected)
    if not title or not steps or not expected:
        raise ValueError("테스트 항목 / 테스트 절차 / 예상 결과는 필수입니다")
    conn = _connect(db_path)
    try:
        conn.execute(
            """UPDATE custom_tcs SET tc_no=?, title=?, precondition=?, steps=?, expected=?,
                                     priority=?, note=?, sheet=? WHERE id=?""",
            (_clip(tc_no, 40), title, _clip(precondition), steps, expected,
             _clip(priority, 20), _clip(note, 500), _clip(sheet, 100), int(row_id)),
        )
        conn.commit()
    finally:
        conn.close()


def set_custom_tc_enabled(row_id, enabled, db_path=None):
    """실행 대상 포함/제외 토글. 지우지 않고 잠시 빼둘 수 있게."""
    conn = _connect(db_path)
    try:
        conn.execute("UPDATE custom_tcs SET enabled=? WHERE id=?",
                     (1 if enabled else 0, int(row_id)))
        conn.commit()
    finally:
        conn.close()


def delete_custom_tc(row_id, db_path=None):
    conn = _connect(db_path)
    try:
        conn.execute("DELETE FROM custom_tcs WHERE id=?", (int(row_id),))
        conn.commit()
    finally:
        conn.close()


def list_custom_tcs(only_enabled=False, sheet=None, db_path=None):
    """대시보드에서 추가한 TC 목록. 프로그램 실행 시에는 only_enabled=True로 쓴다.
    sheet를 주면 그 시트(화면)의 TC만. [v0.14.0]"""
    conn = _connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        sql, args = "SELECT * FROM custom_tcs", []
        where = []
        if only_enabled:
            where.append("enabled=1")
        if sheet is not None:
            where.append("IFNULL(sheet,'')=?")
            args.append(str(sheet))
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY id"
        return [dict(r) for r in conn.execute(sql, args).fetchall()]
    finally:
        conn.close()


def list_custom_tc_sheets(db_path=None):
    """시트(화면)별 TC 건수. 대시보드 필터를 만들기 위한 것. [NEW v0.14.0]
    [{sheet, total, enabled}, ...] - 시트 이름이 없는 TC는 sheet=''로 묶인다."""
    conn = _connect(db_path)
    try:
        rows = conn.execute(
            """SELECT IFNULL(sheet,''), COUNT(*), SUM(CASE WHEN enabled=1 THEN 1 ELSE 0 END)
               FROM custom_tcs GROUP BY IFNULL(sheet,'') ORDER BY IFNULL(sheet,'')"""
        ).fetchall()
        return [{"sheet": r[0], "total": r[1], "enabled": r[2] or 0} for r in rows]
    finally:
        conn.close()


def set_sheet_enabled(sheet, enabled, db_path=None):
    """한 시트의 TC를 통째로 실행 포함/제외. 화면 단위로 돌릴 때 쓴다. [NEW v0.14.0]"""
    conn = _connect(db_path)
    try:
        cur = conn.execute("UPDATE custom_tcs SET enabled=? WHERE IFNULL(sheet,'')=?",
                           (1 if enabled else 0, str(sheet or "")))
        conn.commit()
        return cur.rowcount
    finally:
        conn.close()


def get_custom_tc(row_id, db_path=None):
    conn = _connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute("SELECT * FROM custom_tcs WHERE id=?", (int(row_id),)).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()
