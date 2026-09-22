# QA_runner_K 대시보드 (조회/TC 관리 전용)
# TC 실행은 강의성님 PC의 exe가 하고, 서버는 화면만 담당한다 -> Playwright/Chromium 불필요.
FROM python:3.11-slim

WORKDIR /app

# 대시보드에 필요한 것만. playwright/anthropic/openai 는 서버에서 쓰지 않는다.
RUN pip install --no-cache-dir flask==3.0.3 openpyxl==3.1.5 requests==2.32.3 gunicorn==22.0.0

COPY dashboard_server.py dashboard_auth.py results_store.py tc_excel.py ./
COPY deploy/wsgi.py ./

# 데이터(SQLite + 스크린샷)는 볼륨으로 붙인다
ENV QA_RUNNER_K_DB_PATH=/data/qa_runner_k.db \
    QA_RUNNER_K_SCREENSHOT_DIR=/data/qa_runner_k_screenshots \
    PYTHONUNBUFFERED=1

RUN useradd -m -u 10001 qa && mkdir -p /data && chown -R qa:qa /data /app
USER qa

EXPOSE 8765

# 워커 2개 - 이 서버는 메모리 2GB에 스왑이 없어서 넉넉히 잡으면 원본 서비스가 위험해진다.
# 스크린샷이 큰 편이라 타임아웃은 60초.
CMD ["gunicorn", "--bind", "0.0.0.0:8765", "--workers", "2", "--threads", "4", \
     "--timeout", "60", "--max-requests", "500", "--max-requests-jitter", "50", \
     "--access-logfile", "-", "--error-logfile", "-", "wsgi:app"]
