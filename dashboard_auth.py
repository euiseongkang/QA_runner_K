#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""QA_runner_K 대시보드 로그인 (ID/PW). [NEW v0.9.0]

대시보드를 사내 서버에 올려 링크로 공유하기로 하면서, 인증이 필요해졌다.
지금까지는 127.0.0.1 전용이라 인증이 아예 없었다.

설계 원칙
  - **로컬에서는 로그인을 요구하지 않는다.** 내 PC에서만 뜨는 대시보드에 매번 로그인하는 건
    불편하기만 하고 얻는 게 없다. 서버 배포 시 QA_RUNNER_K_REQUIRE_LOGIN=1 로 켠다.
  - 표준 라이브러리만 사용 (exe 용량과 의존성을 늘리지 않기 위해). 해시는 PBKDF2-HMAC-SHA256.
  - 비밀번호 평문은 어디에도 저장하지 않는다. DB에는 salt + 해시만 남는다.
  - 프로그램(exe)이 서버와 통신할 때는 쿠키가 아니라 API 토큰을 쓴다 (require_api_token).

계정 만들기 (서버에서)
    python3 dashboard_auth.py adduser <아이디>
    python3 dashboard_auth.py passwd <아이디>
    python3 dashboard_auth.py list
"""

import functools
import hashlib
import hmac
import os
import secrets
import sqlite3
import time

from flask import request, session, redirect, url_for, abort

import results_store

USER_SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL UNIQUE,
    salt TEXT NOT NULL,
    pw_hash TEXT NOT NULL,
    created_at REAL NOT NULL,
    last_login_at REAL
);
"""

PBKDF2_ROUNDS = 200000
SESSION_HOURS = 12

# 비밀번호 최소 길이. 짧으면 막지는 않되 경고한다(사내 도구라 운용 편의를 우선).
MIN_PASSWORD_LEN = 6
WEAK_PASSWORD_LEN = 10

# 로그인 없이 열어두는 경로. /healthz 는 대시보드 탐지용이라 인증을 걸면 안 된다.
PUBLIC_PATHS = ("/login", "/healthz", "/favicon.ico")

LOOPBACK = ("127.0.0.1", "::1", "localhost")

# 무차별 대입 방어. 같은 IP에서 연속 실패가 쌓이면 잠깐 막는다 (메모리 보관, 재시작 시 초기화).
MAX_FAILS = 8
LOCK_SECONDS = 300
_fails = {}


# ============================================================
# 비밀번호 / 사용자
# ============================================================
def _connect(db_path=None):
    conn = sqlite3.connect(db_path or results_store.get_db_path(), timeout=10)
    conn.execute(USER_SCHEMA)
    return conn


def hash_password(password, salt=None):
    salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"),
                                 salt.encode("utf-8"), PBKDF2_ROUNDS)
    return salt, digest.hex()


def add_user(username, password, db_path=None):
    username = (username or "").strip().lower()
    if not username:
        raise ValueError("아이디를 입력하세요")
    if len(password or "") < MIN_PASSWORD_LEN:
        raise ValueError("비밀번호는 " + str(MIN_PASSWORD_LEN) + "자 이상이어야 합니다")
    salt, pw_hash = hash_password(password)
    conn = _connect(db_path)
    try:
        conn.execute("INSERT INTO users (username, salt, pw_hash, created_at) VALUES (?,?,?,?)",
                     (username, salt, pw_hash, time.time()))
        conn.commit()
    except sqlite3.IntegrityError:
        raise ValueError("이미 있는 아이디입니다: " + username)
    finally:
        conn.close()


def set_password(username, password, db_path=None):
    if len(password or "") < MIN_PASSWORD_LEN:
        raise ValueError("비밀번호는 " + str(MIN_PASSWORD_LEN) + "자 이상이어야 합니다")
    salt, pw_hash = hash_password(password)
    conn = _connect(db_path)
    try:
        cur = conn.execute("UPDATE users SET salt=?, pw_hash=? WHERE username=?",
                           (salt, pw_hash, (username or "").strip().lower()))
        conn.commit()
        if cur.rowcount == 0:
            raise ValueError("없는 아이디입니다: " + str(username))
    finally:
        conn.close()


def list_users(db_path=None):
    conn = _connect(db_path)
    try:
        return conn.execute(
            "SELECT username, created_at, last_login_at FROM users ORDER BY username").fetchall()
    finally:
        conn.close()


def delete_user(username, db_path=None):
    conn = _connect(db_path)
    try:
        conn.execute("DELETE FROM users WHERE username=?", ((username or "").strip().lower(),))
        conn.commit()
    finally:
        conn.close()


def verify(username, password, db_path=None):
    """아이디/비밀번호가 맞으면 True. 없는 아이디여도 해시 계산을 한 번 돌려서
    응답 시간 차이로 아이디 존재 여부가 새어나가지 않게 한다."""
    username = (username or "").strip().lower()
    conn = _connect(db_path)
    try:
        row = conn.execute("SELECT salt, pw_hash FROM users WHERE username=?",
                           (username,)).fetchone()
    finally:
        conn.close()
    if not row:
        hash_password(password or "", "dummy")
        return False
    salt, expected = row
    _, actual = hash_password(password or "", salt)
    if not hmac.compare_digest(actual, expected):
        return False
    conn = _connect(db_path)
    try:
        conn.execute("UPDATE users SET last_login_at=? WHERE username=?", (time.time(), username))
        conn.commit()
    finally:
        conn.close()
    return True


def user_count(db_path=None):
    conn = _connect(db_path)
    try:
        return conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    finally:
        conn.close()


# ============================================================
# 잠금
# ============================================================
def _client_ip():
    # nginx 뒤에 있을 때 실제 접속자 IP. 신뢰 가능한 프록시 뒤라는 전제.
    fwd = request.headers.get("X-Forwarded-For", "")
    return (fwd.split(",")[0].strip() if fwd else request.remote_addr) or "?"


def is_local_request():
    """이 요청이 '이 컴퓨터에서 직접 온 것'인지.

    프록시를 거치면 remote_addr이 127.0.0.1로 보이므로, X-Forwarded-For가 붙어 있으면
    무조건 원격으로 본다. 서버(nginx 뒤)에서 이 함수가 True가 되면 인증이 통째로
    무력화되기 때문에, 판단은 보수적으로 한다."""
    if request.headers.get("X-Forwarded-For") or request.headers.get("X-Real-IP"):
        return False
    return (request.remote_addr or "") in LOOPBACK


def _locked_for(ip):
    count, until = _fails.get(ip, (0, 0))
    remain = int(until - time.time())
    return remain if remain > 0 else 0


def _note_fail(ip):
    count, until = _fails.get(ip, (0, 0))
    count += 1
    if count >= MAX_FAILS:
        _fails[ip] = (0, time.time() + LOCK_SECONDS)
    else:
        _fails[ip] = (count, until)


def _clear_fail(ip):
    _fails.pop(ip, None)


# ============================================================
# Flask 연결
# ============================================================
def login_required_enabled(app):
    return bool(app.config.get("REQUIRE_LOGIN"))


def install(app, db_path=None, require_login=None):
    """대시보드 앱에 로그인 기능을 붙인다. require_login=False면 화면만 열어두고 통과시킨다."""
    if require_login is None:
        require_login = os.environ.get("QA_RUNNER_K_REQUIRE_LOGIN", "").strip() in ("1", "true", "yes")

    app.config["REQUIRE_LOGIN"] = require_login
    app.config["AUTH_DB_PATH"] = db_path

    # 세션 서명 키. 서버에서는 반드시 환경변수로 고정해야 재시작 때 로그인이 풀리지 않는다.
    secret = os.environ.get("QA_RUNNER_K_SECRET_KEY", "").strip()
    app.secret_key = secret or secrets.token_urlsafe(48)
    app.config["SESSION_COOKIE_HTTPONLY"] = True
    app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
    if os.environ.get("QA_RUNNER_K_BASE_URL", "").lower().startswith("https://"):
        app.config["SESSION_COOKIE_SECURE"] = True
    app.permanent_session_lifetime = SESSION_HOURS * 3600

    @app.before_request
    def _guard():
        path = request.path or "/"
        if path in PUBLIC_PATHS or path.startswith("/static/"):
            return None
        if path.startswith("/api/"):
            return None          # API는 토큰 인증 (require_api_token)

        # 내 PC에서 직접 보는 건 로그인 없이 통과. 다른 컴퓨터에서 들어오거나
        # 서버 배포 모드(REQUIRE_LOGIN)면 로그인을 요구한다.
        if not app.config.get("REQUIRE_LOGIN") and is_local_request():
            return None

        if session.get("user"):
            return None
        if path == "/setup":
            return None          # /setup은 자기 라우트에서 직접 로컬 여부를 막는다
        if request.method == "POST":
            abort(401)
        return redirect(url_for("login", next=request.full_path or "/"))

    @app.route("/login", methods=["GET", "POST"])
    def login():
        dbp = app.config.get("AUTH_DB_PATH")
        nxt = request.values.get("next") or "/"
        if not nxt.startswith("/") or nxt.startswith("//"):
            nxt = "/"          # 외부 주소로 튕기는 open redirect 방지

        if request.method == "GET":
            if session.get("user") or (not app.config.get("REQUIRE_LOGIN") and is_local_request()):
                return redirect(nxt)
            if user_count(dbp) == 0:
                return _no_account_page(is_local_request())
            return _login_page(nxt, "")

        ip = _client_ip()
        remain = _locked_for(ip)
        if remain:
            return _login_page(nxt, "실패가 많아 잠시 막혔습니다. " + str(remain) + "초 후에 다시 시도하세요."), 429

        username = request.form.get("username", "")
        password = request.form.get("password", "")
        if verify(username, password, dbp):
            _clear_fail(ip)
            session.clear()
            session.permanent = True
            session["user"] = username.strip().lower()
            return redirect(nxt)
        _note_fail(ip)
        return _login_page(nxt, "아이디 또는 비밀번호가 맞지 않습니다."), 401

    @app.route("/logout", methods=["GET", "POST"])
    def logout():
        session.clear()
        return redirect("/login")

    @app.route("/setup", methods=["GET", "POST"])
    def setup():
        """대시보드 계정 만들기. **이 컴퓨터에서 직접 열었을 때만** 동작한다.

        다른 컴퓨터에서 이 주소로 계정을 만들 수 있으면 인증이 있으나 마나이므로,
        원격 요청은 무조건 404로 막는다(존재 자체를 알리지 않는다).
        서버(REQUIRE_LOGIN=1)에서는 아예 닫고 CLI로만 만든다 — 서버에서는 nginx를 거쳐
        remote_addr이 127.0.0.1로 보일 수 있기 때문."""
        dbp = app.config.get("AUTH_DB_PATH")
        if app.config.get("REQUIRE_LOGIN") or not is_local_request():
            abort(404)

        if request.method == "GET":
            return _setup_page("")

        username = (request.form.get("username") or "").strip().lower()
        pw1 = request.form.get("password") or ""
        pw2 = request.form.get("password2") or ""
        if pw1 != pw2:
            return _setup_page("비밀번호가 서로 다릅니다."), 400
        try:
            if any(u[0] == username for u in list_users(dbp)):
                set_password(username, pw1, dbp)
            else:
                add_user(username, pw1, dbp)
        except ValueError as e:
            return _setup_page(str(e)), 400
        return _setup_done_page(username, len(pw1) < WEAK_PASSWORD_LEN)

    return app


def require_api_token():
    """프로그램(exe)이 서버 API를 부를 때 쓰는 인증. Authorization: Bearer <토큰>.
    QA_RUNNER_K_API_TOKEN 이 비어 있으면 API를 아예 막는다(설정 누락 상태로 열리는 것 방지)."""
    expected = os.environ.get("QA_RUNNER_K_API_TOKEN", "").strip()
    if not expected:
        abort(503)
    got = request.headers.get("Authorization", "")
    if not got.startswith("Bearer "):
        abort(401)
    if not hmac.compare_digest(got[7:].strip(), expected):
        abort(401)


def api_token_required(fn):
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        require_api_token()
        return fn(*args, **kwargs)
    return wrapper


def current_user():
    try:
        return session.get("user")
    except Exception:
        return None


# ============================================================
# 로그인 화면
# ============================================================
def _esc(s):
    # 작은따옴표까지 escape 한다 (value='...' 속성에 그대로 들어가는 자리가 있어서).
    return (str(s if s is not None else "")
            .replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            .replace('"', "&quot;").replace("'", "&#39;"))


LOGIN_STYLE = """
  :root { color-scheme: light; }
  body { font-family: -apple-system, "Segoe UI", "Malgun Gothic", sans-serif; margin: 0;
         background: #f3f4f6; color: #222; display: flex; min-height: 100vh;
         align-items: center; justify-content: center; }
  .box { background: #fff; border: 1px solid #e4e4e4; border-radius: 10px; padding: 28px 26px;
         width: 320px; box-shadow: 0 1px 3px rgba(0,0,0,.06); }
  h1 { font-size: 17px; margin: 0 0 4px; }
  .sub { color: #666; font-size: 13px; margin: 0 0 18px; }
  label { display: block; font-size: 12px; font-weight: 600; color: #444; margin: 12px 0 4px; }
  input { width: 100%; box-sizing: border-box; padding: 9px 10px; font-size: 14px;
          border: 1px solid #ccd0d6; border-radius: 6px; font-family: inherit; }
  button { width: 100%; margin-top: 18px; padding: 10px; font-size: 14px; font-weight: 600;
           border-radius: 6px; border: 1px solid #2d6cdf; background: #2d6cdf; color: #fff;
           cursor: pointer; font-family: inherit; }
  .err { background: #fdecec; border: 1px solid #f3c7c7; color: #a3271c; font-size: 13px;
         padding: 9px 12px; border-radius: 6px; margin-bottom: 4px; line-height: 1.6; }
  .warn { background: #fff6e0; border: 1px solid #f0dcae; color: #7a5a12; font-size: 13px;
          padding: 9px 12px; border-radius: 6px; margin: 12px 0 4px; line-height: 1.6; }
  .note { color: #777; font-size: 12px; line-height: 1.6; margin: 14px 0 0; }
  .btnlink { display: block; text-align: center; margin-top: 18px; padding: 10px;
             font-size: 14px; font-weight: 600; border-radius: 6px; background: #2d6cdf;
             color: #fff; text-decoration: none; }
  .box.wide { width: 360px; }
"""


def _login_page(next_url, error):
    err_html = ('<div class="err">' + _esc(error) + "</div>") if error else ""
    return """<!doctype html>
<html lang="ko"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>QA_runner_K 로그인</title>
<style>""" + LOGIN_STYLE + """</style></head>
<body>
  <form class="box" method="post" action="/login">
    <h1>QA_runner_K</h1>
    <p class="sub">대시보드에 로그인하세요.</p>
    """ + err_html + """
    <input type="hidden" name="next" value='""" + _esc(next_url) + """'>
    <label for="u">아이디</label>
    <input id="u" name="username" autocomplete="username" autofocus required>
    <label for="p">비밀번호</label>
    <input id="p" name="password" type="password" autocomplete="current-password" required>
    <button type="submit">로그인</button>
  </form>
</body></html>"""


def _shell(title, body):
    return """<!doctype html>
<html lang="ko"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>""" + _esc(title) + """</title>
<style>""" + LOGIN_STYLE + """</style></head>
<body>
""" + body + """
</body></html>"""


def _no_account_page(local):
    if local:
        body = """  <div class="box">
    <h1>대시보드 계정이 없습니다</h1>
    <p class="sub">다른 컴퓨터에서 이 대시보드를 보려면 계정이 필요합니다.
       지금 이 컴퓨터에서 하나 만들어 두세요.</p>
    <a class="btnlink" href="/setup">계정 만들기</a>
    <p class="note">이 페이지는 이 컴퓨터에서만 열립니다.</p>
  </div>"""
    else:
        body = """  <div class="box">
    <h1>대시보드 계정이 없습니다</h1>
    <p class="sub">아직 계정이 만들어지지 않았습니다. 관리자에게 계정 생성을 요청하세요.</p>
    <p class="note">서버: python3 dashboard_auth.py adduser &lt;아이디&gt;</p>
  </div>"""
    return _shell("QA_runner_K", body)


def _setup_page(error):
    err_html = ('<div class="err">' + _esc(error) + "</div>") if error else ""
    return _shell("대시보드 계정 만들기", """  <form class="box" method="post" action="/setup">
    <h1>대시보드 계정 만들기</h1>
    <p class="sub">다른 컴퓨터나 서버에서 접속할 때 쓸 아이디/비밀번호입니다.
       이 컴퓨터에서 볼 때는 로그인을 묻지 않습니다.</p>
    """ + err_html + """
    <label for="u">아이디</label>
    <input id="u" name="username" value="qa" autocomplete="off" autofocus required>
    <label for="p">비밀번호</label>
    <input id="p" name="password" type="password" autocomplete="new-password" required>
    <label for="p2">비밀번호 확인</label>
    <input id="p2" name="password2" type="password" autocomplete="new-password" required>
    <button type="submit">저장</button>
    <p class="note">같은 아이디가 이미 있으면 비밀번호가 바뀝니다.
       비밀번호는 해시로만 저장되어 원문은 남지 않습니다.</p>
  </form>""")


def _setup_done_page(username, weak):
    warn = ("""<div class="warn">비밀번호가 짧습니다. 지금은 이대로 쓰셔도 되지만,
       사내 서버에 올려 링크로 공유하기 전에는 더 긴 것으로 바꾸세요.</div>""" if weak else "")
    return _shell("완료", """  <div class="box">
    <h1>계정을 저장했습니다</h1>
    <p class="sub">아이디: <b>""" + _esc(username) + """</b></p>
    """ + warn + """
    <a class="btnlink" href="/tcs">대시보드로 이동</a>
    <p class="note">다른 컴퓨터에서 들어오면 이 계정으로 로그인해야 합니다.</p>
  </div>""")


# ============================================================
# 계정 관리 CLI (서버에서 실행)
# ============================================================
def _cli():
    import getpass
    import sys

    args = sys.argv[1:]
    cmd = args[0] if args else ""

    if cmd == "adduser" and len(args) >= 2:
        pw = getpass.getpass("새 비밀번호(8자 이상): ")
        if pw != getpass.getpass("한 번 더: "):
            print("비밀번호가 서로 다릅니다.")
            return 1
        add_user(args[1], pw)
        print("계정을 만들었습니다: " + args[1])
        return 0

    if cmd == "passwd" and len(args) >= 2:
        pw = getpass.getpass("새 비밀번호(8자 이상): ")
        if pw != getpass.getpass("한 번 더: "):
            print("비밀번호가 서로 다릅니다.")
            return 1
        set_password(args[1], pw)
        print("비밀번호를 바꿨습니다: " + args[1])
        return 0

    if cmd == "deluser" and len(args) >= 2:
        delete_user(args[1])
        print("계정을 지웠습니다: " + args[1])
        return 0

    if cmd == "list":
        rows = list_users()
        if not rows:
            print("계정이 없습니다.")
        for username, created, last in rows:
            when = time.strftime("%Y-%m-%d %H:%M", time.localtime(last)) if last else "-"
            print(username + "   마지막 로그인: " + when)
        return 0

    print("사용법:")
    print("  python3 dashboard_auth.py adduser <아이디>")
    print("  python3 dashboard_auth.py passwd  <아이디>")
    print("  python3 dashboard_auth.py deluser <아이디>")
    print("  python3 dashboard_auth.py list")
    return 1


if __name__ == "__main__":
    import sys
    try:
        sys.exit(_cli())
    except ValueError as e:
        print("오류: " + str(e))
        sys.exit(1)
