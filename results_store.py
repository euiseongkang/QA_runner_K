#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""QA_runner_K 실행 결과 로컬 저장소 (SQLite, 표준 라이브러리만 사용).

로컬 엑셀 파일을 TC 소스로 쓰는 경우 EC2 백엔드가 없으므로, 실행 결과(PASS/FAIL/확인 필요)와
전/후 스크린샷 경로를 로컬 DB에 남기고 `dashboard_server.py`가 이를 읽어 브라우저 페이지로 보여준다.
EC2를 TC 소스로 쓰는 경우에도 동일하게 로컬에 남겨서, 로컬/EC2 어느 쪽이든 같은 결과 화면으로 볼 수
있게 한다 (EC2 자체 제출은 qa_runner_k_gui.py의 _submit_result_ec2에서 별도로 처리).
"""

import os
import secrets
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


# [NEW v0.28.0] TC 불러오기 한 번 = 세션 하나.
# 전에는 묶음 구분이 '시트 이름'뿐이라, 같은 시트를 고쳐서 다시 불러오면 덮어쓰는 수밖에 없었다
# (v0.18.0). 이제는 불러올 때마다 세션이 쌓이고, **실행할 세션을 고르는** 방식으로 바꾼다.
# 고른 세션의 TC만 실행되므로 옛 세션이 섞여 실행되던 문제가 구조적으로 사라진다.
#
# 중요한 설계: 프로그램(exe)은 예전처럼 enabled=1 인 TC를 읽는다. 그래서 enabled 를
# **파생 값**으로 둔다 -> enabled = (세션이 선택됨) AND (TC가 포함됨).
# 사람이 끄고 켜는 값은 custom_tcs.included 에 따로 저장하므로, 세션 선택을 바꿔도
# 개별 TC의 포함/제외 상태가 보존된다. 덕분에 **exe를 다시 빌드하지 않아도 동작한다.**
TC_SESSION_SCHEMA = """
CREATE TABLE IF NOT EXISTS tc_sessions (
    session_id TEXT PRIMARY KEY,
    label TEXT NOT NULL,           -- 사람이 알아볼 이름. 기본값은 출처 + 시각
    source TEXT,                   -- 엑셀 파일명 / 구글 시트 / 직접 작성
    sheets TEXT,                   -- 이 세션에 들어온 시트 이름들 (쉼표로 이어붙임)
    selected INTEGER NOT NULL DEFAULT 0,   -- 실행 대상 세션인가
    created_at REAL NOT NULL
);
"""

LEGACY_SESSION_ID = "legacy"       # 세션 개념이 생기기 전에 있던 TC들을 담을 자리


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
    conn.execute(TC_SESSION_SCHEMA)          # [v0.28.0]
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

    # [v0.28.0] 세션 컬럼 추가. 이미 쓰고 있는 DB가 있으므로 지우고 다시 만들면 안 된다.
    try:
        cols = {r[1] for r in conn.execute("PRAGMA table_info(custom_tcs)").fetchall()}
        for name, decl in (("session_id", "TEXT"),
                           ("seq", "INTEGER"),
                           ("included", "INTEGER NOT NULL DEFAULT 1")):
            if name not in cols:
                conn.execute(f"ALTER TABLE custom_tcs ADD COLUMN {name} {decl}")
        conn.commit()
    except Exception:
        return          # 컬럼을 못 만들었으면 아래 백필도 의미가 없다

    # 세션이 없던 시절의 TC를 '기존 TC' 세션으로 옮긴다. 사라지는 TC가 있으면 안 된다.
    try:
        orphan = conn.execute(
            "SELECT COUNT(*) FROM custom_tcs WHERE IFNULL(session_id,'')=''").fetchone()[0]
        if orphan:
            conn.execute(
                "INSERT OR IGNORE INTO tc_sessions"
                " (session_id, label, source, sheets, selected, created_at)"
                " VALUES (?,?,?,?,?,?)",
                (LEGACY_SESSION_ID, "기존 TC (세션 구분 전)", "", "", 1, time.time()),
            )
            # included 는 지금까지의 enabled 를 그대로 물려받는다 - 꺼둔 TC가 되살아나지 않게.
            conn.execute(
                "UPDATE custom_tcs SET session_id=?, included=enabled"
                " WHERE IFNULL(session_id,'')=''", (LEGACY_SESSION_ID,))
            conn.commit()
        # seq 가 비어 있으면 id 순서를 등록 순으로 본다(그때까지의 실제 입력 순서).
        missing = conn.execute(
            "SELECT id FROM custom_tcs WHERE seq IS NULL ORDER BY id").fetchall()
        if missing:
            conn.executemany("UPDATE custom_tcs SET seq=? WHERE id=?",
                             [(i, r[0]) for i, r in enumerate(missing)])
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


def tc_result_key(tc):
    """같은 번호의 다른 시트나 내용이 바뀐 TC에 이전 결과를 붙이지 않는다."""
    sheet = str(tc.get('sheet_name', tc.get('sheet')) or '').strip()
    if sheet in ('대시보드', '서버'):
        sheet = ''
    return tuple(' '.join(str(value or '').split()) for value in (
        tc.get('tc_id', tc.get('tc_no')), tc.get('title'), sheet,
        tc.get('steps'), tc.get('expected')))


def latest_tc_details(source=None, source_ref=None, db_path=None):
    """TC별 최신 실행 결과. 300건 표시 제한과 무관하게 전체 이력을 조회한다."""
    conn = _connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        where, args = [], []
        for field, value in [('source', source), ('source_ref', source_ref)]:
            if value is not None:
                where.append(field + '=?')
                args.append(value)
        sql = 'SELECT tc_no, title, sheet, steps, expected, result, reason, created_at FROM results'
        if where:
            sql += ' WHERE ' + ' AND '.join(where)
        sql += ' ORDER BY created_at DESC, id DESC'
        latest = {}
        for row in conn.execute(sql, args):
            if row['result'] in ('PASS', 'FAIL', '확인 필요'):
                latest.setdefault(tc_result_key(dict(row)), dict(row))
        return latest
    finally:
        conn.close()


def latest_tc_results(source=None, source_ref=None, db_path=None):
    return {key: row['result'] for key, row in
            latest_tc_details(source, source_ref, db_path).items()}


class TCEditConflict(ValueError):
    pass


def update_custom_tc_text(row_id, steps, expected, previous_steps, previous_expected, db_path=None):
    """절차·예상 결과만 갱신한다. 다른 사용자의 편집을 덮어쓰지 않는다."""
    if not isinstance(steps, str) or not isinstance(expected, str) or not steps.strip() or not expected.strip():
        raise ValueError('테스트 절차와 예상 결과를 모두 입력하세요')
    if len(steps) > MAX_FIELD_LEN or len(expected) > MAX_FIELD_LEN:
        raise ValueError(f'각 문구는 {MAX_FIELD_LEN}자 이내로 입력하세요')
    conn = _connect(db_path)
    try:
        conn.execute('BEGIN IMMEDIATE')
        row = conn.execute('SELECT steps, expected FROM custom_tcs WHERE id=?', (int(row_id),)).fetchone()
        if row is None:
            raise KeyError('TC가 삭제되었거나 존재하지 않습니다')
        normalize = lambda text: ' '.join(str(text or '').split())
        if (normalize(row[0]), normalize(row[1])) != (normalize(previous_steps), normalize(previous_expected)):
            raise TCEditConflict('다른 곳에서 TC가 수정되었습니다. 목록을 다시 불러와 주세요')
        conn.execute('UPDATE custom_tcs SET steps=?, expected=? WHERE id=?',
                     (steps.strip(), expected.strip(), int(row_id)))
        conn.commit()
    finally:
        conn.close()


def update_custom_tc_details(row_id, changes, previous, db_path=None):
    fields = ('title', 'priority', 'sheet', 'precondition', 'steps', 'expected')
    if not isinstance(changes, dict) or not isinstance(previous, dict) or any(
            not isinstance(changes.get(key), str) or not isinstance(previous.get(key), str) for key in fields):
        raise ValueError('TC 항목과 변경 전 정보가 필요합니다')
    limits = dict(title=4000, priority=20, sheet=100, precondition=4000, steps=4000, expected=4000)
    values = {key: changes[key].strip() for key in fields}
    if any(not values[key] for key in ('title', 'steps', 'expected')):
        raise ValueError('TC 제목·테스트 절차·예상 결과는 필수입니다')
    if any(len(values[key]) > limits[key] for key in fields):
        raise ValueError('TC 항목의 최대 길이를 초과했습니다')
    if values['priority'] not in ('', 'P1', 'P2', 'P3', 'P4') and values['priority'] != previous['priority']:
        raise ValueError('우선순위는 P1~P4 또는 미지정이어야 합니다')
    conn = _connect(db_path)
    try:
        conn.execute('BEGIN IMMEDIATE')
        row = conn.execute('SELECT title, priority, sheet, precondition, steps, expected FROM custom_tcs WHERE id=?', (int(row_id),)).fetchone()
        if row is None:
            raise KeyError('TC가 삭제되었거나 존재하지 않습니다')
        normalize = lambda value: ' '.join(str(value or '').split())
        if any(normalize(row[index]) != normalize(previous[key]) for index, key in enumerate(fields)):
            raise TCEditConflict('다른 곳에서 TC가 수정되었습니다. 목록을 다시 불러와 주세요')
        conn.execute('UPDATE custom_tcs SET title=?, priority=?, sheet=?, precondition=?, steps=?, expected=? WHERE id=?',
                     (*[values[key] for key in fields], int(row_id)))
        conn.commit()
    finally:
        conn.close()


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
                     sheet="", session_id=None, seq=None, db_path=None):
    """대시보드 입력 폼에서 TC 1건 추가. 추가된 row id 반환.
    필수는 테스트 항목/테스트 절차/예상 결과 3개 (엑셀 로더의 필수 컬럼과 동일 기준).
    sheet는 엑셀/구글 시트의 시트 이름 = 화면별 구분값. [v0.14.0]
    session_id/seq 는 [v0.28.0] - seq 가 시트에서의 행 순서라 목록 정렬 기준이 된다."""
    title, steps, expected = _clip(title), _clip(steps), _clip(expected)
    if not title or not steps or not expected:
        raise ValueError("테스트 항목 / 테스트 절차 / 예상 결과는 필수입니다")
    conn = _connect(db_path)
    try:
        cur = conn.execute(
            """INSERT INTO custom_tcs
               (tc_no, title, precondition, steps, expected, priority, note, sheet,
                session_id, seq, included, enabled, created_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,1,1,?)""",
            (_clip(tc_no, 40), title, _clip(precondition), steps, expected,
             _clip(priority, 20), _clip(note, 500), _clip(sheet, 100),
             (str(session_id) if session_id else None), seq, time.time()),
        )
        conn.commit()
        row_id = cur.lastrowid
    finally:
        conn.close()
    _recompute_enabled(db_path)      # 선택되지 않은 세션에 넣었으면 enabled 는 0이 된다
    return row_id


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


def list_custom_tcs(only_enabled=False, sheet=None, session_id=None, db_path=None):
    """대시보드에서 추가한 TC 목록. 프로그램 실행 시에는 only_enabled=True로 쓴다.
    sheet를 주면 그 시트(화면)의 TC만. [v0.14.0]  session_id 필터는 [v0.28.0]

    [v0.28.0] 정렬을 id 에서 **시트 등록 순(seq)** 으로 바꿨다.
    id 순이면 나중에 시트 중간에 끼워 넣은 TC가 목록 맨 끝에 붙어서, 시트와 순서가 달라진다."""
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
        if session_id is not None:
            where.append("IFNULL(session_id,'')=?")
            args.append(str(session_id))
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY IFNULL(seq, id), id"
        return [dict(r) for r in conn.execute(sql, args).fetchall()]
    finally:
        conn.close()


# ============================================================
# TC 세션                                                      [NEW v0.28.0]
# ============================================================

def create_tc_session(label, source="", sheets="", select=True, db_path=None):
    """불러오기 한 번에 해당하는 세션을 만든다. 반환: session_id

    select=True 면 이 세션만 실행 대상이 된다 - 방금 불러온 것이 실행되는 게 자연스럽고,
    예전 세션이 같이 실행돼 옛 TC가 섞이는 사고(v0.18.0)를 막는다.
    예전 세션의 TC 자체는 건드리지 않는다(지우지도, 내용을 바꾸지도 않는다)."""
    session_id = time.strftime("%Y%m%d_%H%M%S") + "_" + secrets.token_hex(2)
    conn = _connect(db_path)
    try:
        conn.execute(
            "INSERT INTO tc_sessions (session_id, label, source, sheets, selected, created_at)"
            " VALUES (?,?,?,?,?,?)",
            (session_id, _clip(str(label or session_id)), _clip(str(source or "")),
             _clip(str(sheets or "")), 0, time.time()),
        )
        conn.commit()
    finally:
        conn.close()
    if select:
        set_tc_session_selected(session_id, True, exclusive=True, db_path=db_path)
    return session_id


def list_tc_sessions(db_path=None):
    """세션 목록을 최신순으로. 각 세션의 TC 건수와 실행 포함 건수를 같이 준다."""
    conn = _connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        rows = [dict(r) for r in conn.execute(
            "SELECT * FROM tc_sessions ORDER BY created_at DESC").fetchall()]
        counts = {}
        for sid, total, on in conn.execute(
                "SELECT IFNULL(session_id,''), COUNT(*), SUM(CASE WHEN included=1 THEN 1 ELSE 0 END)"
                " FROM custom_tcs GROUP BY IFNULL(session_id,'')").fetchall():
            counts[sid] = (total, on or 0)
        for r in rows:
            r["tc_count"], r["included_count"] = counts.get(r["session_id"], (0, 0))
        return rows
    finally:
        conn.close()


def get_tc_session(session_id, db_path=None):
    conn = _connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        r = conn.execute("SELECT * FROM tc_sessions WHERE session_id=?",
                         (str(session_id),)).fetchone()
        return dict(r) if r else None
    finally:
        conn.close()


def rename_tc_session(session_id, label, db_path=None):
    label = _clip(str(label or "").strip())
    if not label:
        raise ValueError("세션 이름이 비어 있습니다")
    conn = _connect(db_path)
    try:
        conn.execute("UPDATE tc_sessions SET label=? WHERE session_id=?",
                     (label, str(session_id)))
        conn.commit()
    finally:
        conn.close()


def delete_tc_session(session_id, db_path=None):
    """세션과 그 안의 TC를 함께 지운다. 다른 세션은 건드리지 않는다. 반환: 지운 TC 수"""
    session_id = str(session_id or "").strip()
    if not session_id:
        raise ValueError("session_id가 필요합니다")
    conn = _connect(db_path)
    try:
        cur = conn.execute("DELETE FROM custom_tcs WHERE IFNULL(session_id,'')=?", (session_id,))
        conn.execute("DELETE FROM tc_sessions WHERE session_id=?", (session_id,))
        conn.commit()
        return cur.rowcount
    finally:
        conn.close()


def set_tc_session_selected(session_id, selected, exclusive=False, db_path=None):
    """세션을 실행 대상으로 켜거나 끈다. exclusive=True면 이 세션만 남기고 나머지는 끈다."""
    conn = _connect(db_path)
    try:
        if exclusive:
            conn.execute("UPDATE tc_sessions SET selected=0")
        conn.execute("UPDATE tc_sessions SET selected=? WHERE session_id=?",
                     (1 if selected else 0, str(session_id)))
        conn.commit()
    finally:
        conn.close()
    _recompute_enabled(db_path)


def set_custom_tc_included(row_id, included, db_path=None):
    """TC 하나의 실행 포함/제외. 세션 선택과 곱해져 enabled 가 정해진다. [v0.28.0]"""
    conn = _connect(db_path)
    try:
        conn.execute("UPDATE custom_tcs SET included=? WHERE id=?",
                     (1 if included else 0, int(row_id)))
        conn.commit()
    finally:
        conn.close()
    _recompute_enabled(db_path)


def _recompute_enabled(db_path=None):
    """enabled = (세션이 선택됨) AND (TC가 포함됨).

    프로그램(exe)은 예전 그대로 enabled=1 을 읽으므로, 이 한 줄이 두 세계를 이어준다.
    세션 개념을 몰라도 exe가 올바른 TC만 실행하게 되는 지점이다."""
    conn = _connect(db_path)
    try:
        conn.execute(
            "UPDATE custom_tcs SET enabled = CASE WHEN included=1 AND IFNULL(session_id,'') IN"
            " (SELECT session_id FROM tc_sessions WHERE selected=1) THEN 1 ELSE 0 END")
        conn.commit()
    finally:
        conn.close()


def list_custom_tc_sheets(session_id=None, db_path=None):
    """시트(화면)별 TC 건수. 대시보드 필터를 만들기 위한 것. [NEW v0.14.0]
    [{sheet, total, enabled}, ...] - 시트 이름이 없는 TC는 sheet=''로 묶인다.
    session_id 를 주면 그 세션 안에서만 센다. [v0.28.0]"""
    conn = _connect(db_path)
    try:
        where, args = "", []
        if session_id is not None:
            where = " WHERE IFNULL(session_id,'')=?"
            args.append(str(session_id))
        rows = conn.execute(
            "SELECT IFNULL(sheet,''), COUNT(*), SUM(CASE WHEN included=1 THEN 1 ELSE 0 END)"
            " FROM custom_tcs" + where + " GROUP BY IFNULL(sheet,'') ORDER BY IFNULL(sheet,'')",
            args).fetchall()
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
