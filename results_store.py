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
    conn = sqlite3.connect(db_path or get_db_path())
    conn.execute(SCHEMA)
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
