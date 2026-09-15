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
    before_screenshot TEXT,        -- 로컬 파일 경로 (없으면 NULL)
    after_screenshot TEXT,
    created_at REAL NOT NULL
);
"""


# [NEW v0.4.0] 대시보드에서 직접 추가하는 TC. 엑셀을 만들지 않고도 화면에서 TC를 작성해
# 바로 실행할 수 있게 하기 위한 테이블. 컬럼 구성은 TC 엑셀 포맷(8컬럼)과 일부러 맞춰둔다.
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


def get_screenshot_dir(run_id: str):
    d = os.path.join(_base_dir(), SCREENSHOT_DIR_NAME, run_id)
    os.makedirs(d, exist_ok=True)
    return d


def _connect(db_path=None):
    # [v0.6.0] 대시보드를 별도 프로그램으로도 띄울 수 있게 되면서, 같은 DB 파일을 두 프로세스가
    # 함께 열 수 있다. 잠깐 겹칠 때 "database is locked"로 죽지 않도록 대기 시간을 준다.
    conn = sqlite3.connect(db_path or get_db_path(), timeout=10)
    conn.execute(SCHEMA)
    conn.execute(CUSTOM_TC_SCHEMA)
    return conn


def insert_result(tc: dict, result: str, reason: str, source: str, source_ref: str,
                   run_id: str, before_screenshot=None, after_screenshot=None, db_path=None):
    conn = _connect(db_path)
    try:
        conn.execute(
            """INSERT INTO results
               (run_id, source, source_ref, tc_no, title, priority, precondition, steps, expected,
                result, reason, before_screenshot, after_screenshot, created_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                run_id, source, source_ref,
                str(tc.get("tc_id", "")), tc.get("title", ""), tc.get("priority", ""),
                tc.get("precondition", ""), tc.get("steps", ""), tc.get("expected", ""),
                result, reason or "", before_screenshot, after_screenshot, time.time(),
            ),
        )
        conn.commit()
    finally:
        conn.close()


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


def list_runs_summary(db_path=None):
    """실행 배치 목록 + 배치별 판정 집계. 대시보드 첫 화면(목록)에서 쓴다. [NEW v0.12.0]
    [{run_id, source, source_ref, started_at, total, passed, failed, unsure}, ...] 최신순."""
    conn = _connect(db_path)
    try:
        rows = conn.execute(
            """SELECT run_id, source, source_ref, MIN(created_at), COUNT(*),
                      SUM(CASE WHEN result='PASS' THEN 1 ELSE 0 END),
                      SUM(CASE WHEN result='FAIL' THEN 1 ELSE 0 END),
                      SUM(CASE WHEN result NOT IN ('PASS','FAIL') THEN 1 ELSE 0 END)
               FROM results GROUP BY run_id ORDER BY MIN(created_at) DESC"""
        ).fetchall()
        return [
            {"run_id": r[0], "source": r[1], "source_ref": r[2], "started_at": r[3],
             "total": r[4], "passed": r[5] or 0, "failed": r[6] or 0, "unsure": r[7] or 0}
            for r in rows
        ]
    finally:
        conn.close()


def _remove_screenshot_dir(run_id):
    """해당 배치의 스크린샷 폴더를 지운다.
    run_id에 경로 조작 문자가 섞여 있어도 스크린샷 루트 밖을 건드리지 못하게 확인한다."""
    import shutil
    root = os.path.realpath(os.path.join(_base_dir(), SCREENSHOT_DIR_NAME))
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
        conn.commit()
        deleted = cur.rowcount
    finally:
        conn.close()
    if remove_screenshots:
        _remove_screenshot_dir(run_id)
    return deleted


def list_results(run_id=None, db_path=None, limit=300):
    conn = _connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        if run_id:
            rows = conn.execute(
                "SELECT * FROM results WHERE run_id=? ORDER BY id", (run_id,)
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM results ORDER BY id DESC LIMIT ?", (limit,)
            ).fetchall()
        return [dict(r) for r in rows]
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
                     db_path=None):
    """대시보드 입력 폼에서 TC 1건 추가. 추가된 row id 반환.
    필수는 테스트 항목/테스트 절차/예상 결과 3개 (엑셀 로더의 필수 컬럼과 동일 기준)."""
    title, steps, expected = _clip(title), _clip(steps), _clip(expected)
    if not title or not steps or not expected:
        raise ValueError("테스트 항목 / 테스트 절차 / 예상 결과는 필수입니다")
    conn = _connect(db_path)
    try:
        cur = conn.execute(
            """INSERT INTO custom_tcs
               (tc_no, title, precondition, steps, expected, priority, note, enabled, created_at)
               VALUES (?,?,?,?,?,?,?,1,?)""",
            (_clip(tc_no, 40), title, _clip(precondition), steps, expected,
             _clip(priority, 20), _clip(note, 500), time.time()),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def update_custom_tc(row_id, title, steps, expected, precondition="", priority="", tc_no="",
                     note="", db_path=None):
    """기존 TC 수정. 화면에서 문구를 고쳐 다시 돌릴 수 있게 하기 위한 것."""
    title, steps, expected = _clip(title), _clip(steps), _clip(expected)
    if not title or not steps or not expected:
        raise ValueError("테스트 항목 / 테스트 절차 / 예상 결과는 필수입니다")
    conn = _connect(db_path)
    try:
        conn.execute(
            """UPDATE custom_tcs SET tc_no=?, title=?, precondition=?, steps=?, expected=?,
                                     priority=?, note=? WHERE id=?""",
            (_clip(tc_no, 40), title, _clip(precondition), steps, expected,
             _clip(priority, 20), _clip(note, 500), int(row_id)),
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


def list_custom_tcs(only_enabled=False, db_path=None):
    """대시보드에서 추가한 TC 목록. 프로그램 실행 시에는 only_enabled=True로 쓴다."""
    conn = _connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        sql = "SELECT * FROM custom_tcs"
        if only_enabled:
            sql += " WHERE enabled=1"
        sql += " ORDER BY id"
        return [dict(r) for r in conn.execute(sql).fetchall()]
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
