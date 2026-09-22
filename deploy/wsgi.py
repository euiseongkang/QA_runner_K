#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""gunicorn 진입점. 서버(EC2)에서만 쓴다.

내 PC에서 쓰던 방식(qa_runner_k_gui.py 가 스레드로 띄우는 것)은 그대로 두고,
서버에서는 이 파일을 gunicorn 이 불러 앱 객체만 가져간다."""
import os

import dashboard_server

app = dashboard_server.create_app(db_path=os.environ.get("QA_RUNNER_K_DB_PATH"))
