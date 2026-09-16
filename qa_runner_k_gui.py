#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
QA_runner_K - iKooB QA 자동화 프로그램 (코드 뼈대)

`ikoob_clinic/qa-tc-runner`(qa_runner_gui.py)를 모티브로 하되, TC 엑셀 포맷을
"기능경로 키워드 매칭" 방식에서 "번호 매긴 테스트 절차 문장을 AI가 그대로 읽고
액션을 생성" 하는 방식으로 바꾼 버전.

대상 서비스 / 판정 방식 / 백엔드 / GUI-배포 방식은 원본과 동일하게 유지한다.
(Claude Project "QA 자동화" > `QA_runner_K 설계 결정사항.md` 참고)

이 파일은 "뼈대" 단계입니다. 아래 표시를 기준으로 완성도가 다릅니다.
    [REUSED]  원본에서 검증된 로직을 그대로/거의 그대로 가져온 부분 (바로 동작 가능)
    [NEW]     새 TC 포맷에 맞춰 이번에 새로 설계한 부분
    [TODO]    EC2 백엔드 실제 응답 필드 확정, UI 세부 배치, 셀렉터 튜닝 등
              실제 서비스 화면을 보면서 채워야 하는 부분
"""

import base64
import json
import os
import re
import sys
import tempfile
import threading
import time
import tkinter as tk
import webbrowser
from tkinter import ttk, messagebox, filedialog
import urllib.parse

import requests

import results_store          # [NEW] 로컬 결과 저장(SQLite) - 결과 대시보드용
import dashboard_server        # [NEW] 결과를 보여주는 로컬 전용 웹 페이지 (Flask)
import tc_excel                # [NEW v0.5.0] TC 엑셀 파서 (대시보드 업로드와 공용)

# ============================================================
# 설정 상수                                                    [TODO]
# ============================================================
APP_VERSION = "0.18.0"

# TODO: QA_runner_K가 원본과 동일한 EC2 백엔드(qa.healthkoob.com)를 그대로 쓸지,
#       아니면 새 TC 포맷 전용 엔드포인트/네임스페이스가 필요한지 백엔드 쪽과 확인 필요.
#       (신규 컬럼: 테스트 항목/사전조건/테스트 절차/예상 결과/우선순위/비고)
DEFAULT_EC2_API = "https://qa.healthkoob.com"

GITHUB_RELEASE_API = "https://api.github.com/repos/euiseongkang/QA_runner_K/releases/latest"
APP_EXE_NAME = "QA_Runner_K.exe"

CONFIG_FILENAME = "qa_runner_k_config.json"  # 시작 URL/로그인 정보 등 로컬 설정 저장 [NEW]

# [NEW] 결과값 3단계. 원본은 PASS/FAIL 2단계였고 판정이 애매하면 그냥 FAIL로 밀어넣었는데,
# 그러면 "진짜 실패"와 "AI가 판단을 못 내린 것/실행 중 오류"가 섞여버려 사람이 다시 걸러야 했음.
# 새 프로그램은 이 둘을 분리해서 NEEDS_REVIEW(확인 필요)로 명확히 구분해 노출한다.
RESULT_PASS = "PASS"
RESULT_FAIL = "FAIL"
RESULT_NEEDS_REVIEW = "확인 필요"

# 모달/팝업 판별 셀렉터. 실제 LabConnect staging의 환자 등록 팝업이 role="dialog"를 갖고 있는 걸
# 브라우저로 직접 확인함(2026-09-11). 여러 곳에서 쓰므로 상수로 둔다.
MODAL_SELECTOR = 'div[role="dialog"], .modal, [class*="modal"], [class*="popup"]'


# ============================================================
# 공통 유틸                                                    [REUSED 원본 기반]
# ============================================================
def clean_text(s: str) -> str:
    """공백/개행 정리. 원본과 동일한 목적."""
    if not s:
        return ""
    return re.sub(r"\s+", " ", str(s)).strip()


def get_scoped_locator(page, selector: str):
    """모달/팝업이 열려 있으면 그 안에서 우선 탐색하고, 없으면 page 전체에서 탐색.
    원본의 '엉뚱한 배경 요소를 잘못 클릭하는 문제' 방지 로직을 그대로 가져옴."""
    try:
        modal = page.locator(MODAL_SELECTOR).last
        if modal.is_visible(timeout=500):
            scoped = modal.locator(selector)
            if scoped.count() > 0:
                return scoped.first
    except Exception:
        pass
    return page.locator(selector).first


def b64_to_photoimage(b64_str: str):
    """스크린샷 base64 -> Tkinter PhotoImage (로그 뷰어 미리보기용)."""
    import io
    from PIL import Image, ImageTk  # TODO: requirements.txt에 Pillow 추가 필요

    data = base64.b64decode(b64_str)
    img = Image.open(io.BytesIO(data))
    img.thumbnail((480, 480))
    return ImageTk.PhotoImage(img)


# ============================================================
# 자동 업데이트                                                 [REUSED 원본 그대로]
# ============================================================
def get_latest_release_info():
    """GitHub Releases API에서 최신 버전 정보 조회."""
    try:
        resp = requests.get(GITHUB_RELEASE_API, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        tag = data.get("tag_name", "").lstrip("v")
        asset_url = None
        for asset in data.get("assets", []):
            if asset.get("name", "").endswith(".exe"):
                asset_url = asset.get("browser_download_url")
                break
        return {"version": tag, "download_url": asset_url, "notes": data.get("body", "")}
    except Exception:
        return None


def do_update(download_url: str, log_fn=print):
    """새 exe를 내려받고, 현재 프로세스 종료 후 교체하는 배치 스크립트를 실행.
    원본과 동일하게 '자동 재실행'은 보안 소프트웨어 오탐 문제로 넣지 않는다."""
    try:
        exe_path = sys.executable if getattr(sys, "frozen", False) else None
        if not exe_path:
            log_fn("⚠ 개발 모드(exe 아님)에서는 자동 업데이트를 건너뜁니다.")
            return False

        tmp_new = os.path.join(tempfile.gettempdir(), APP_EXE_NAME)
        with requests.get(download_url, stream=True, timeout=60) as r:
            r.raise_for_status()
            with open(tmp_new, "wb") as f:
                for chunk in r.iter_content(chunk_size=1 << 20):
                    f.write(chunk)

        pid = os.getpid()
        bat_path = os.path.join(tempfile.gettempdir(), "qa_runner_k_update.bat")
        # PID가 종료될 때까지 대기 후 교체 - 원본과 동일 패턴
        bat_content = f"""@echo off
:loop
tasklist /FI "PID eq {pid}" | find "{pid}" >nul
if not errorlevel 1 (
    timeout /t 1 /nobreak >nul
    goto loop
)
move /Y "{tmp_new}" "{exe_path}"
start "" "{exe_path}"
del "%~f0"
"""
        with open(bat_path, "w", encoding="utf-8") as f:
            f.write(bat_content)

        os.startfile(bat_path)  # noqa: Windows 전용
        return True
    except Exception as e:
        log_fn(f"⚠ 업데이트 실패: {e}")
        return False


# ============================================================
# AI 프롬프트 빌더                                              [NEW - 테스트 절차 기반]
# ============================================================
def build_action_prompt(tc: dict, html_snippet: str) -> str:
    """원본은 '기능경로' 한 문장 + KEYWORD_URL_MAP으로 메뉴부터 찾아갔지만,
    새 포맷은 '테스트 절차'에 번호 매긴 단계가 이미 다 적혀 있으므로
    AI가 절차 전체를 순서대로 읽고 액션 리스트 하나를 통째로 생성하게 한다.
    (menu keyword mapping 유지보수 자체를 없애는 것이 이번 포맷 변경의 핵심 목적)
    """
    title = tc.get("title", "")  # 테스트 항목
    precondition = tc.get("precondition", "")  # 사전조건
    steps = tc.get("steps", "")  # 테스트 절차 (번호 매긴 여러 줄)
    expected = tc.get("expected", "")  # 예상 결과

    return f"""아래 테스트 절차를 순서대로 수행하기 위한 Playwright 액션을 JSON으로만 반환하세요.
절차는 번호 순서대로 하나씩 실행되어야 하며, 절차에 없는 임의의 추가 동작은 만들지 마세요.

[테스트 항목] {title}
[사전조건] {precondition[:200]}
[테스트 절차]
{steps[:1200]}
[예상 결과] {expected[:300]}
[현재 화면 HTML] {html_snippet[:4000]}

규칙:
1. 텍스트 기반 셀렉터 우선: button:has-text(), label:has-text()
2. rgba/복잡한 클래스 기반 셀렉터 절대 금지
3. 드래그가 필요하면 type:drag, 입력이 필요하면 type:fill 사용
4. 절차 문장에 "엔터"/"Enter" 언급이 있으면 반드시 type:press, key:Enter 액션 추가
5. 절차 문장에 "hover"/"마우스 오버"/"마우스오버" 표현이 있으면 절대 click을 만들지 말고 type:hover 사용
6. 검색 입력 후 별도 조회/Enter 버튼이 화면에 없다면 type:wait(1500)으로 자동 검색 대기
7. 절차에 명시적으로 언급되지 않은 버튼(수정/삭제/등록 등)은 화면에 보여도 클릭 금지
8. 절차가 "~노출 확인", "~확인" 처럼 조회성 문장으로 끝나면 그 이상 화면을 진행시키는
   추가 클릭을 만들지 말 것. 단, 문장 중간에 "클릭"이 있으면 "확인"으로 끝나도 그 클릭은 생성할 것
9. 텍스트 없는 아이콘 버튼은 aria-label/title 속성 또는 클래스 기반 셀렉터 사용
10. 절차 각 단계는 actions 배열 순서와 1:1로 대응되도록 생성 (한 단계가 여러 액션이 필요하면 순서대로 여러 개)

JSON: {{"actions":[
  {{"type":"click","selector":"button:has-text('조회')","description":"조회"}},
  {{"type":"fill","selector":"input[placeholder*='검색']","value":"테스트","description":"검색어 입력"}},
  {{"type":"hover","selector":"셀렉터","description":"마우스 호버"}},
  {{"type":"wait","ms":500}}
]}}
액션 없으면: {{"actions":[]}}"""


def build_judge_prompt(tc: dict, actions_done: list, body_text: str, compare_before_after: bool) -> str:
    """PASS/FAIL/확인 필요 3단계 판정 프롬프트. [NEW] 원본은 PASS/FAIL 2단계였음.

    "확인 필요"는 AI가 화면 정보만으로 확신을 갖고 PASS/FAIL을 단정하기 어려운 경우
    (예: 액션이 의도대로 실행됐는지 화면상 근거가 불충분함, 예상 결과 문장이 모호함,
    스크린샷에 판단에 필요한 요소가 안 보임) 사용하도록 명시적으로 지시한다.
    억지로 PASS/FAIL 중 하나를 고르게 하면 원본처럼 애매한 케이스가 FAIL로 뭉개져서
    사람이 다시 하나하나 확인해야 하는 문제가 있었음."""
    title = tc.get("title", "")
    precondition = tc.get("precondition", "")
    expected = tc.get("expected", "")
    actions_str = " -> ".join(actions_done) if actions_done else "(없음)"

    prompt = f"""아래 정보를 보고 테스트가 PASS/FAIL/확인 필요 중 무엇인지 판정하세요.
[테스트 항목] {title}
[사전조건] {precondition[:200]}
[수행한 액션] {actions_str}
[예상 결과] {expected[:300]}
[화면 텍스트 일부] {body_text[:3000]}

판정 기준:
- PASS: 예상 결과대로 화면/동작이 확인됨
- FAIL: 예상 결과와 다르게 동작하거나 오류가 명확히 확인됨
- 확인 필요: 화면 정보만으로 PASS/FAIL을 확신할 수 없음 (판단 근거 불충분, 예상 결과 문장이 모호함,
  액션이 의도대로 실행됐는지 화면에서 확인이 안 됨 등) - 억지로 PASS/FAIL 중 하나를 고르지 말 것
"""
    if compare_before_after:
        prompt += "\n액션 전/후 스크린샷을 비교해서 예상 결과대로 화면이 바뀌었는지 반드시 확인하세요."
    prompt += ('\n\n반드시 아래 JSON 형식으로만 답하세요: '
               '{"judgment":"PASS 또는 FAIL 또는 확인 필요","reason":"판정 이유 한글로 간단히"}')
    return prompt


# ============================================================
# 규칙 기반 액션 생성 / 검증유형 추론                            [NEW]
# ============================================================
# 원본 인수인계 문서(정확도개선)의 핵심 권고: "GPT가 결정하는 범위를 줄이고, 코드가 결정하는
# 범위를 늘린다". 원본은 TC 엑셀의 `검증방식` 컬럼으로 이걸 구현했지만, 우리 TC 포맷(8컬럼)에는
# 그 컬럼이 없다(강의성님이 작성 부담 때문에 컬럼 추가는 안 하기로 결정).
# 그래서 컬럼 대신 **"테스트 절차"/"예상 결과" 문장에서 코드가 검증유형과 액션을 직접 추론**한다.
#   - `[대괄호]` = 클릭 대상, `"따옴표"` = 입력값, "엔터/Enter" = 키 입력  (기존 TC 작성 관례 그대로)
# 이 경로로 액션이 만들어지면 AI 액션 생성을 건너뛰므로, 같은 TC를 돌릴 때마다 결과가 달라지는
# 비결정성이 줄고 AI API 키 없이도 실행/검증이 가능해진다.

VERIFY_SCREEN = "화면노출"
VERIFY_CLICK = "클릭동작"
VERIFY_INPUT = "입력검증"
VERIFY_POPUP = "팝업확인"
VERIFY_NAVIGATE = "화면이동"
VERIFY_UNKNOWN = "기타"

# 클릭 대상 셀렉터 후보. div는 의도적으로 제외 - 텍스트를 품은 거대한 래퍼 div가 먼저 잡혀서
# 엉뚱한 영역을 클릭하는 사고가 원본에서 있었음(인수인계 문서 v4.26 사례와 같은 유형).
_CLICK_TAGS = ["button", "a", '[role="button"]', "label", "li", "td", "span"]

# 예상 결과에서 "화면에 실제로 있는지 확인할 단어"를 뽑을 때 걸러낼 일반 동작/서술 어휘.
# 이게 없으면 "버튼/클릭/노출/화면" 같은 단어가 항상 매칭돼서 판정이 무의미해진다.
_JUDGE_STOPWORDS = {
    "버튼", "클릭", "노출", "노출된다", "표시", "표시된다", "이동", "이동한다", "진입", "진입한다",
    "화면", "확인", "확인된다", "정상", "정상적으로", "해당", "각각", "모두", "관련", "경우", "시",
    "으로", "되며", "된다", "한다", "있다", "있는", "함께", "그리고", "또는", "선택", "입력",
    # 팝업/모달은 화면에 그 단어가 글자로 쓰여 있지 않으므로(팝업이 스스로 "팝업"이라 적지 않음)
    # 텍스트 판정에서 제외하고, 대신 모달 요소 존재 여부로 판정한다.
    "팝업", "모달", "레이어", "다이얼로그",
}

# 조사 때문에 매칭이 깨지는 걸 막는다 ("테이블이"는 화면에 "테이블"로 적혀 있음)
_PARTICLES = ("으로", "에서", "이나", "이가", "은", "는", "이", "가", "을", "를", "의", "에", "로", "와", "과", "도")


def _strip_step_number(line: str) -> str:
    """"1. ", "2) ", "- " 같은 앞머리 번호/불릿 제거."""
    return re.sub(r"^\s*(?:\d+\s*[.)]|[-*•])\s*", "", line).strip()


def infer_verify_type(tc: dict) -> str:
    """TC 문장에서 검증유형을 추론. 액션 실행 후 '무엇을 기다릴지'를 결정하는 데 쓴다."""
    steps = str(tc.get("steps") or "")
    expected = str(tc.get("expected") or "")
    both = steps + " " + expected

    if re.search(r"팝업|모달|dialog|레이어", both, re.IGNORECASE):
        return VERIFY_POPUP
    if re.search(r"이동|전환|진입|페이지로|화면으로", expected):
        return VERIFY_NAVIGATE
    if re.search(r"입력|검색|엔터|enter", both, re.IGNORECASE):
        return VERIFY_INPUT
    if re.search(r"\[[^\]]+\].*(클릭|선택|누르)", steps, re.DOTALL):
        return VERIFY_CLICK
    if re.search(r"노출|표시|확인", expected):
        return VERIFY_SCREEN
    return VERIFY_UNKNOWN


def _click_selector(text: str) -> str:
    """텍스트 기반 클릭 셀렉터(CSS 리스트) 생성."""
    safe = text.replace('"', '\\"')
    return ", ".join(f'{tag}:has-text("{safe}")' for tag in _CLICK_TAGS)


def build_rule_actions(tc: dict) -> list:
    """"테스트 절차" 문장을 코드가 직접 파싱해 액션 리스트를 만든다. 해석 불가하면 빈 리스트.

    반환 액션은 AI가 만드는 것과 같은 스키마라서 TCExecutionEngine이 그대로 실행할 수 있다.
    click 액션에는 verify 유형에 따라 "wait"(dialog/url) 힌트를 넣어 고정 대기가 아니라
    조건 대기를 하도록 한다(인수인계 문서 4-B).
    """
    steps = str(tc.get("steps") or "")
    if not steps.strip():
        return []

    verify_type = infer_verify_type(tc)
    wait_hint = {VERIFY_POPUP: "dialog", VERIFY_NAVIGATE: "url"}.get(verify_type)

    actions = []
    for raw_line in re.split(r"[\n\r]+", steps):
        line = _strip_step_number(raw_line)
        if not line:
            continue

        brackets = re.findall(r"\[([^\]]+)\]", line)
        quoted = re.findall(r"[\"'“”‘’]([^\"'“”‘’]{1,60})[\"'“”‘’]", line)
        has_click = bool(re.search(r"클릭|선택|누르|눌러|탭", line))
        has_input = bool(re.search(r"입력|기입|검색어", line))
        has_enter = bool(re.search(r"엔터|enter", line, re.IGNORECASE))

        # 1) 입력: "따옴표" 안의 값을 입력. 따옴표 값이 있어도 '입력' 문맥이 아니면 건드리지 않는다
        #    (예: "'랩커넥트' 진입"의 따옴표는 서비스 이름이라 입력값이 아님)
        if has_input and quoted:
            value = quoted[0]
            if brackets:
                field = brackets[0].replace('"', '\\"')
                selector = (f'input[placeholder*="{field}"], textarea[placeholder*="{field}"], '
                            f'input[name*="{field}"], input[aria-label*="{field}"]')
            else:
                selector = ('input[placeholder*="검색"], input[type="search"], '
                            'input[type="text"]:not([readonly])')
            # description은 대상 이름만 담는다 (엔진이 "입력: {desc} = {value}" 형태로 로그를 찍으므로)
            actions.append({"type": "fill", "selector": selector, "value": value,
                            "description": brackets[0] if brackets else "검색 입력창"})

        # 2) 클릭: [대괄호]로 명시된 대상만 클릭한다. 대괄호가 없으면 클릭 액션을 만들지 않음
        #    (원본 사고: 대상이 불명확할 때 AI가 '환자 등록' 같은 엉뚱한 버튼을 눌렀음)
        if has_click and brackets:
            for target in brackets:
                action = {"type": "click", "selector": _click_selector(target),
                          "description": target}  # 엔진이 "클릭: {desc}"로 찍으므로 대상만 담는다
                if wait_hint:
                    action["wait"] = wait_hint
                actions.append(action)

        # 3) 엔터
        if has_enter:
            actions.append({"type": "press", "key": "Enter", "description": "Enter 키 입력"})

    return actions


def _strip_particle(token: str) -> str:
    """3자 이상 토큰의 뒤에 붙은 조사를 떼어낸다 ("테이블이" -> "테이블")."""
    for p in _PARTICLES:
        if len(token) > len(p) + 1 and token.endswith(p):
            return token[: -len(p)]
    return token


def extract_expected_keywords(expected: str) -> list:
    """예상 결과 문장에서 "화면에 실제로 있는지 확인할 단어"를 뽑는다.
    따옴표/대괄호로 명시된 값이 있으면 그것만 쓰고, 없으면 서술 어휘를 걸러낸 명사들을 쓴다."""
    explicit = re.findall(r"[\"'“”‘’\[]([^\"'“”‘’\]]{2,40})[\"'“”‘’\]]", expected)
    if explicit:
        return [k.strip() for k in explicit if k.strip()]
    keywords = []
    for token in re.findall(r"[가-힣A-Za-z0-9]{2,}", expected):
        if token in _JUDGE_STOPWORDS:
            continue
        stripped = _strip_particle(token)
        if stripped and stripped not in _JUDGE_STOPWORDS and stripped not in keywords:
            keywords.append(stripped)
    return keywords


def judge_by_text(tc: dict, body_text: str, modal_visible=None, url_changed=None):
    """AI 없이 코드로만 하는 보수적 판정. (judgment, reason) 반환.

    확실한 근거가 있을 때만 PASS를 주고, 근거를 못 찾으면 FAIL이 아니라 "확인 필요"로 둔다.
    텍스트에 안 보인다고 실패라고 단정할 수 없기 때문(이미지/아이콘/색상만 바뀌는 TC도 있음).
    FAIL은 사람이 확인할 필요가 없을 만큼 확실할 때만 써야 하므로 여기서는 아예 내지 않는다.

    검증유형별로 가장 확실한 근거를 먼저 본다(인수인계 문서 4-A의 템플릿 판정과 같은 취지):
      - 팝업확인 -> 모달 요소가 실제로 떠 있는지 (modal_visible)
      - 화면이동 -> URL이 바뀌었는지 (url_changed) + 화면 키워드
      - 그 외    -> 예상 결과 키워드가 화면 텍스트에 있는지
    """
    expected = str(tc.get("expected") or "")
    if not expected.strip():
        return RESULT_NEEDS_REVIEW, "예상 결과가 비어 있어 코드 판정 불가"

    verify_type = infer_verify_type(tc)
    keywords = extract_expected_keywords(expected)
    body = body_text or ""
    found = [k for k in keywords if k in body]
    missing = [k for k in keywords if k not in body]

    if verify_type == VERIFY_POPUP:
        if modal_visible:
            extra = f" / 내용 확인: {', '.join(found[:4])}" if found else ""
            return RESULT_PASS, f"팝업(모달) 요소가 화면에 떠 있음{extra}"
        if modal_visible is False:
            return (RESULT_NEEDS_REVIEW,
                    "팝업으로 보이는 요소를 찾지 못함 - 커스텀 구조일 수 있어 스크린샷 확인 필요")

    if verify_type == VERIFY_NAVIGATE:
        if url_changed and not missing and keywords:
            return RESULT_PASS, f"URL 변경 + 화면에서 확인됨: {', '.join(found[:5])}"
        if url_changed is False and not found:
            return RESULT_NEEDS_REVIEW, "URL이 바뀌지 않고 화면 텍스트에서도 근거를 찾지 못함"

    if not keywords:
        return RESULT_NEEDS_REVIEW, f"예상 결과에서 확인할 키워드를 뽑지 못함: {expected[:60]}"
    if not missing:
        return RESULT_PASS, f"화면에서 확인됨: {', '.join(found[:5])}"
    if found:
        return (RESULT_NEEDS_REVIEW,
                f"일부만 확인됨 (확인: {', '.join(found[:4])} / 미확인: {', '.join(missing[:4])})")
    return RESULT_NEEDS_REVIEW, f"화면 텍스트에서 근거를 찾지 못함 (미확인: {', '.join(missing[:5])})"


# ============================================================
# TC 실행 엔진                                                  [REUSED 원본 안전장치 그대로]
# ============================================================
class DangerousActionError(Exception):
    """위험 액션이 차단되어 실행을 건너뛰었음을 나타내는 표시용 예외 (실제로 raise하진 않고 로그만)."""


class TCExecutionEngine:
    """생성된 액션 리스트를 Playwright page에 실제로 실행하는 엔진.

    원본에서 실전 버그로 검증된 안전장치를 그대로 가져온다:
      - 위험 셀렉터(rgba/style 등 불안정 셀렉터) 차단
      - 위험 단어(로그아웃/탈퇴/삭제확인/계정삭제) 차단 - TC가 해당 버튼을
        '명시적으로' 검증 대상으로 삼을 때만 허용 (그 외엔 오조작 방지를 위해 항상 차단)
      - 비활성화된 버튼은 클릭 실패로 보지 않고 "비활성 상태 확인"으로 기록
      - 클릭 후 모달 등장/URL 변경을 기다리고, 둘 다 아니면 800ms 폴백 대기
    """

    DANGEROUS_SELECTOR_PATTERNS = ["rgba(", "rgb(", "style=", "!important"]
    DANGER_WORDS_BASE = ["탈퇴", "삭제확인", "계정삭제"]

    def __init__(self, page, log_fn=print):
        self.page = page
        self.log_fn = log_fn

    def _is_dangerous(self, action: dict, tc_steps_text: str) -> bool:
        sel = (action.get("selector") or "").lower()
        desc = (action.get("description") or "").lower()

        if any(d in sel for d in self.DANGEROUS_SELECTOR_PATTERNS):
            return True

        danger_words = list(self.DANGER_WORDS_BASE)
        logout_is_intended_target = "[로그아웃]" in tc_steps_text or "로그아웃] 버튼" in tc_steps_text
        if not logout_is_intended_target:
            danger_words += ["로그아웃", "logout"]
        if ("로그아웃" in tc_steps_text or "경고" in tc_steps_text) and "나가기" in desc:
            danger_words += ["나가기"]

        return any(w in desc or w in sel for w in danger_words)

    def execute(self, actions: list, tc: dict) -> list:
        """액션 리스트를 순서대로 실행하고, 실제 실행된 액션 설명 리스트를 반환."""
        actions_done = []
        tc_steps_text = tc.get("steps", "")

        for action in actions:
            atype = action.get("type")
            desc = action.get("description", atype)

            if self._is_dangerous(action, tc_steps_text):
                self.log_fn(f"  ⚠ 위험 액션 차단: {desc}")
                continue

            try:
                if atype == "click":
                    self._click(action, actions_done)
                elif atype == "fill":
                    self._fill(action, actions_done)
                elif atype == "drag":
                    self._drag(action, actions_done)
                elif atype == "hover":
                    self._hover(action, actions_done)
                elif atype == "press":
                    self._press(action, actions_done)
                elif atype == "wait":
                    self.page.wait_for_timeout(int(action.get("ms", 500)))
                else:
                    self.log_fn(f"  ⚠ 알 수 없는 액션 타입: {atype}")
            except Exception as e:
                self.log_fn(f"  ⚠ 액션 실행 실패 ({desc}): {str(e)[:80]}")

        return actions_done

    # ---- 개별 액션 실행 (원본 로직 이식) ----
    def _click(self, action, actions_done):
        sel = action.get("selector", "")
        desc = action.get("description", "클릭")
        el = get_scoped_locator(self.page, sel)
        if not el.is_visible(timeout=3000):
            return

        is_disabled = False
        try:
            is_disabled = el.is_disabled(timeout=500)
        except Exception:
            pass
        if is_disabled:
            self.log_fn(f"  ⓘ 버튼 비활성화 상태 확인: {desc}")
            actions_done.append(f"비활성화 확인: {desc}")
            return

        url_before = self.page.url
        el.click()
        self._wait_after_click(url_before, action.get("wait"))
        self.log_fn(f"  ✓ 클릭: {desc}")
        actions_done.append(f"클릭: {desc}")

    def _wait_after_click(self, url_before, wait_hint=None):
        """클릭 후 화면 반영 대기. 고정 대기(wait_for_timeout)를 최대한 쓰지 않는다.

        원본 인수인계 문서가 지목한 핵심 비결정성 원인 중 하나가 "클릭 후 화면 반영을
        고정된 ms만큼만 기다린다"는 것이었음(TC14: 팝업이 800ms 안에 안 떠서 FAIL 오판정).

        wait_hint가 있으면(규칙 기반 액션이 검증유형에서 추론해 넣어줌) 무엇을 기다릴지
        확정적으로 알고 있으므로 그 조건만 넉넉히(5초) 기다린다. 힌트가 없으면
        ① 모달 등장 ② URL 변경 ③ 네트워크 유휴 순으로 시도하고, 마지막에만 짧게 고정 대기.
        """
        if wait_hint == "dialog":
            try:
                self.page.wait_for_selector(MODAL_SELECTOR, timeout=5000, state="visible")
                return
            except Exception:
                self.log_fn("  ⚠ 팝업이 5초 안에 나타나지 않음 (판정에서 확인 필요로 남을 수 있음)")
                return
        if wait_hint == "url":
            try:
                self.page.wait_for_function(
                    "prevUrl => window.location.href !== prevUrl", arg=url_before, timeout=5000
                )
                self.page.wait_for_load_state("networkidle", timeout=3000)
                return
            except Exception:
                self.log_fn("  ⚠ 화면 이동(URL 변경)이 5초 안에 감지되지 않음")
                return

        try:
            self.page.wait_for_selector(MODAL_SELECTOR, timeout=1200, state="visible")
        except Exception:
            try:
                self.page.wait_for_function(
                    "prevUrl => window.location.href !== prevUrl", arg=url_before, timeout=1500
                )
            except Exception:
                try:
                    self.page.wait_for_load_state("networkidle", timeout=1500)
                except Exception:
                    self.page.wait_for_timeout(400)

    def _fill(self, action, actions_done):
        sel = action.get("selector", "")
        value = action.get("value", "")
        desc = action.get("description", "입력")
        el = get_scoped_locator(self.page, sel)
        el.fill(value)
        self.log_fn(f"  ✓ 입력: {desc} = {value}")
        actions_done.append(f"입력: {desc}")

    def _drag(self, action, actions_done):
        desc = action.get("description", "드래그")
        src = get_scoped_locator(self.page, action.get("source", ""))
        tgt = get_scoped_locator(self.page, action.get("target", ""))
        src.drag_to(tgt)
        self.log_fn(f"  ✓ 드래그: {desc}")
        actions_done.append(f"드래그: {desc}")

    def _hover(self, action, actions_done):
        desc = action.get("description", "호버")
        el = get_scoped_locator(self.page, action.get("selector", ""))
        el.hover()
        self.log_fn(f"  ✓ 호버: {desc}")
        actions_done.append(f"호버: {desc}")

    def _press(self, action, actions_done):
        key = action.get("key", "Enter")
        self.page.keyboard.press(key)
        self.log_fn(f"  ✓ 키 입력: {key}")
        actions_done.append(f"키 입력: {key}")


# ============================================================
# GUI 애플리케이션
# ============================================================
class QAWorkerApp:
    def __init__(self, root):
        self.root = root
        self.root.title(f"QA_runner_K v{APP_VERSION}")
        self.running = False
        self.tc_data = []
        self.session_map = {}

        self.ec2_var = tk.StringVar(value=DEFAULT_EC2_API)
        self.key_var = tk.StringVar()
        self.provider_var = tk.StringVar(value="Claude")
        self.action_model_var = tk.StringVar(value="claude-sonnet-4-20250514")  # TODO: 실제 사용할 모델로 확정
        self.judge_model_var = tk.StringVar(value="claude-sonnet-4-20250514")
        self.session_var = tk.StringVar()
        self.sheet_var = tk.StringVar()
        self.priority_var = tk.StringVar(value="전체")
        self.limit_var = tk.StringVar(value="0")
        self.status_var = tk.StringVar(value="대기 중")

        # [NEW] AI 없이 규칙 기반으로만 실행. API 키가 없어도 로그인/이동/클릭/팝업 대기/
        # 스크린샷/대시보드까지 전부 검증할 수 있게 기본값을 켜둔다 (키 확보 후 체크 해제).
        self.rule_only_var = tk.BooleanVar(value=True)

        # [NEW] TC 소스: 로컬 엑셀 파일을 바로 읽거나(local), 기존처럼 EC2 세션에서 불러오거나(ec2)
        self.tc_source_var = tk.StringVar(value="local")
        self.local_xlsx_path_var = tk.StringVar(value="")
        self._dashboard_addr = None  # (host, port) - "결과 보기"로 이미 띄운 서버가 있으면 재사용
        # [NEW v0.11.0] 대시보드 주소를 화면에 띄워서 복사/북마크할 수 있게 한다.
        # 주소를 매번 물어보시는 일이 있어서, 버튼과 함께 눈에 보이는 자리에 둔다.
        self.dashboard_url_var = tk.StringVar(value="대시보드 준비 중...")

        # [NEW] 시작 URL/로그인 - TC 엑셀과 분리해서 프로그램 설정으로 관리
        self.start_url_var = tk.StringVar()
        self.login_type_var = tk.StringVar(value="idpw")  # idpw / token / none
        self.login_id_var = tk.StringVar()
        self.login_pw_var = tk.StringVar()

        self._load_local_config()
        self._build_ui()
        # [NEW v0.4.0] 대시보드에서 TC를 작성할 수 있게 되었으니 시작 시 미리 띄운다
        self._ensure_dashboard()
        self.check_update_and_prompt()

    # ---- 로컬 설정 (시작 URL/로그인) ----                    [NEW][TODO: 저장 경로/암호화 방식 확정]
    def _config_path(self):
        base = os.path.dirname(sys.executable if getattr(sys, "frozen", False) else __file__)
        return os.path.join(base, CONFIG_FILENAME)

    def _load_local_config(self):
        try:
            with open(self._config_path(), "r", encoding="utf-8") as f:
                cfg = json.load(f)
            self.ec2_var.set(cfg.get("ec2_api", DEFAULT_EC2_API))
            self.start_url_var.set(cfg.get("start_url", ""))
            self.login_type_var.set(cfg.get("login_type", "idpw"))
            self.login_id_var.set(cfg.get("login_id", ""))
            # TODO: 비밀번호 평문 저장은 임시 조치. 배포 전 OS 자격 증명 저장소 등으로 교체 검토.
            self.login_pw_var.set(cfg.get("login_pw", ""))
        except Exception:
            pass

    def _save_local_config(self):
        cfg = {
            "ec2_api": self.ec2_var.get(),
            "start_url": self.start_url_var.get(),
            "login_type": self.login_type_var.get(),
            "login_id": self.login_id_var.get(),
            "login_pw": self.login_pw_var.get(),
        }
        try:
            with open(self._config_path(), "w", encoding="utf-8") as f:
                json.dump(cfg, f, ensure_ascii=False, indent=2)
        except Exception as e:
            self.log_msg(f"⚠ 설정 저장 실패: {e}")

    # ---- UI 구성 ----                                        [TODO: 실제 배치는 원본 GUI 참고해 다듬기]
    def _build_ui(self):
        top = ttk.Frame(self.root, padding=8)
        top.pack(fill="x")

        ttk.Label(top, text="EC2 API").grid(row=0, column=0, sticky="w")
        ttk.Entry(top, textvariable=self.ec2_var, width=40).grid(row=0, column=1, sticky="w")

        ttk.Label(top, text="AI Provider").grid(row=0, column=2, sticky="w")
        ttk.Combobox(top, textvariable=self.provider_var, values=["Claude", "OpenAI"], width=10,
                     state="readonly").grid(row=0, column=3, sticky="w")

        ttk.Label(top, text="API Key").grid(row=1, column=0, sticky="w")
        ttk.Entry(top, textvariable=self.key_var, width=40, show="*").grid(row=1, column=1, sticky="w")

        # [NEW] AI 없이 규칙 기반으로만 실행 (API 키 없이 동작 검증할 때)
        ttk.Checkbutton(
            top,
            text="AI 없이 규칙 기반으로만 실행 (API 키 불필요 · 절차의 [대괄호]/\"따옴표\"만 해석)",
            variable=self.rule_only_var,
        ).grid(row=2, column=0, columnspan=4, sticky="w", pady=(4, 0))

        # [NEW] 시작 지점 설정 영역 - TC 엑셀과 분리
        start_frame = ttk.LabelFrame(self.root, text="시작 지점 / 로그인 설정", padding=8)
        start_frame.pack(fill="x", padx=8, pady=4)
        ttk.Label(start_frame, text="시작 URL").grid(row=0, column=0, sticky="w")
        ttk.Entry(start_frame, textvariable=self.start_url_var, width=50).grid(row=0, column=1, sticky="w")
        ttk.Label(start_frame, text="로그인 방식").grid(row=1, column=0, sticky="w")
        ttk.Combobox(start_frame, textvariable=self.login_type_var, values=["idpw", "token", "none"],
                     width=10, state="readonly").grid(row=1, column=1, sticky="w")
        ttk.Label(start_frame, text="ID").grid(row=2, column=0, sticky="w")
        ttk.Entry(start_frame, textvariable=self.login_id_var, width=25).grid(row=2, column=1, sticky="w")
        ttk.Label(start_frame, text="PW").grid(row=3, column=0, sticky="w")
        ttk.Entry(start_frame, textvariable=self.login_pw_var, width=25, show="*").grid(row=3, column=1, sticky="w")
        ttk.Button(start_frame, text="저장", command=self._save_local_config).grid(row=3, column=2, padx=4)

        # [NEW] TC 소스 선택 영역 - 로컬 엑셀 파일을 바로 읽을지, EC2 세션에서 불러올지
        source_frame = ttk.LabelFrame(self.root, text="TC 소스", padding=8)
        source_frame.pack(fill="x", padx=8, pady=4)
        ttk.Radiobutton(source_frame, text="로컬 엑셀 파일", variable=self.tc_source_var,
                        value="local", command=self._on_tc_source_change).grid(row=0, column=0, sticky="w")
        # [NEW v0.4.0] 대시보드 화면에서 직접 추가한 TC로 실행
        ttk.Radiobutton(source_frame, text="대시보드 추가 TC", variable=self.tc_source_var,
                        value="custom", command=self._on_tc_source_change).grid(row=0, column=1, sticky="w")
        ttk.Radiobutton(source_frame, text="EC2 세션", variable=self.tc_source_var,
                        value="ec2", command=self._on_tc_source_change).grid(row=0, column=2, sticky="w")

        self.local_file_frame = ttk.Frame(source_frame)
        self.local_file_frame.grid(row=1, column=0, columnspan=4, sticky="w", pady=(4, 0))
        ttk.Button(self.local_file_frame, text="엑셀 파일 선택...",
                   command=self._choose_local_xlsx).pack(side="left")
        ttk.Label(self.local_file_frame, textvariable=self.local_xlsx_path_var,
                  foreground="#555").pack(side="left", padx=6)

        # [NEW v0.4.0] 대시보드 TC 안내 + 바로 열기
        self.custom_tc_frame = ttk.Frame(source_frame)
        self.custom_tc_frame.grid(row=1, column=0, columnspan=4, sticky="w", pady=(4, 0))
        ttk.Button(self.custom_tc_frame, text="대시보드에서 TC 추가/수정...",
                   command=self.open_tc_dashboard).pack(side="left")
        ttk.Label(self.custom_tc_frame,
                  text="대시보드 'TC 관리'에서 추가한 TC 중 '실행 포함' 상태인 것만 불러옵니다",
                  foreground="#555").pack(side="left", padx=6)

        self.ec2_session_frame = ttk.Frame(source_frame)
        self.ec2_session_frame.grid(row=1, column=0, columnspan=4, sticky="w", pady=(4, 0))
        ttk.Button(self.ec2_session_frame, text="세션 불러오기", command=self.load_sessions).grid(row=0, column=0)
        ttk.Combobox(self.ec2_session_frame, textvariable=self.session_var, width=30,
                     state="readonly").grid(row=0, column=1)
        ttk.Combobox(self.ec2_session_frame, textvariable=self.sheet_var, width=20,
                     state="readonly").grid(row=0, column=2)

        # 세션/시트/TC 선택 영역
        sel_frame = ttk.LabelFrame(self.root, text="TC 목록", padding=8)
        sel_frame.pack(fill="both", expand=True, padx=8, pady=4)

        ttk.Button(sel_frame, text="TC 불러오기", command=self.load_tc_list).grid(row=0, column=0)
        ttk.Combobox(sel_frame, textvariable=self.priority_var,
                     values=["전체", "P1", "P2", "P3", "P4", "P1+P2", "P1+P2+P3"],
                     width=10, state="readonly").grid(row=0, column=1)

        self.tc_listbox = tk.Listbox(sel_frame, selectmode="extended", width=100, height=15)
        self.tc_listbox.grid(row=1, column=0, columnspan=4, sticky="nsew", pady=4)
        ttk.Button(sel_frame, text="전체 선택", command=self.select_all_tc).grid(row=2, column=0)
        ttk.Button(sel_frame, text="선택 해제", command=self.deselect_all_tc).grid(row=2, column=1)

        # 실행 제어
        ctrl_frame = ttk.Frame(self.root, padding=8)
        ctrl_frame.pack(fill="x")
        ttk.Label(ctrl_frame, text="최대 실행 수(0=전체)").pack(side="left")
        ttk.Entry(ctrl_frame, textvariable=self.limit_var, width=6).pack(side="left")
        ttk.Button(ctrl_frame, text="시작", command=self.start_worker).pack(side="left", padx=4)
        ttk.Button(ctrl_frame, text="중지", command=self.stop_worker).pack(side="left")
        ttk.Label(ctrl_frame, textvariable=self.status_var).pack(side="left", padx=8)
        # [NEW] 실행 결과(PASS/FAIL/확인 필요 + 스크린샷)를 보여주는 로컬 웹 페이지를 브라우저로 염
        ttk.Button(ctrl_frame, text="결과 보기", command=self.open_results_dashboard).pack(side="left", padx=8)
        ttk.Button(ctrl_frame, text="업데이트 확인", command=self.manual_check_update).pack(side="right")

        # [NEW v0.11.0] 대시보드 바로가기 줄. 버튼 하나로 브라우저 새 창이 열리고,
        # 옆에 주소를 그대로 노출해서 복사하거나 북마크할 수 있게 한다.
        dash_frame = ttk.Frame(self.root, padding=(8, 0, 8, 6))
        dash_frame.pack(fill="x")
        ttk.Button(dash_frame, text="대시보드 바로가기",
                   command=self.open_dashboard).pack(side="left")
        ttk.Label(dash_frame, text="주소").pack(side="left", padx=(10, 4))
        url_entry = ttk.Entry(dash_frame, textvariable=self.dashboard_url_var,
                              state="readonly", width=32)
        url_entry.pack(side="left")
        ttk.Button(dash_frame, text="주소 복사",
                   command=self.copy_dashboard_url).pack(side="left", padx=4)

        # 로그
        log_frame = ttk.LabelFrame(self.root, text="로그", padding=4)
        log_frame.pack(fill="both", expand=True, padx=8, pady=4)
        self.log_text = tk.Text(log_frame, height=15, state="disabled")
        self.log_text.pack(fill="both", expand=True)

        self._on_tc_source_change()  # 초기 상태: local/ec2 프레임 중 하나만 보이도록 정리

    # ---- TC 소스: 로컬 엑셀 / 대시보드 추가 TC / EC2 세션 ----     [NEW]
    def _on_tc_source_change(self):
        frames = {
            "local": self.local_file_frame,
            "custom": self.custom_tc_frame,
            "ec2": self.ec2_session_frame,
        }
        for f in frames.values():
            f.grid_remove()
        frames.get(self.tc_source_var.get(), self.local_file_frame).grid()

    def _choose_local_xlsx(self):
        path = filedialog.askopenfilename(
            title="TC 엑셀 파일 선택 (개요 + 테스트케이스 시트 포맷)",
            filetypes=[("Excel files", "*.xlsx")],
        )
        if not path:
            return
        self.local_xlsx_path_var.set(path)
        self._load_tcs_from_local_xlsx(path)

    def _load_tcs_from_local_xlsx(self, path):
        """TC 엑셀("테스트케이스" 시트)을 읽어 TC 리스트를 구성.

        [v0.5.0] 파싱 규칙은 tc_excel.parse_tc_excel 로 옮겼다. 대시보드의 엑셀 업로드도
        같은 함수를 쓰기 때문에, 프로그램과 대시보드가 같은 파일을 다르게 읽는 일이 없다."""
        try:
            tcs_raw, warnings = tc_excel.parse_tc_excel(path)
        except Exception as e:
            self.log_msg(f"⚠ 로컬 엑셀 로드 실패: {e}")
            messagebox.showerror("TC 로드 실패", str(e))
            return

        self.tc_data = [{
            "id": f"local:{os.path.basename(path)}:{t['no']}",  # EC2 tc id가 없으므로 파일+식별자로 대체
            "tc_id": t["no"],
            "sheet_name": t.get("sheet") or tc_excel.SHEET_NAME,   # [v0.15.0] 시트별 구분
            "title": t["title"],
            "precondition": t["precondition"],
            "steps": t["steps"],
            "expected": t["expected"],
            "priority": t["priority"] or "미지정",
            "note": t["note"],
            "result": "",  # 엑셀에 적힌 기존 결과값은 참고만 하고 실행 대상 필터링에는 쓰지 않음
        } for t in tcs_raw]

        self.tc_listbox.delete(0, "end")
        for tc in self.tc_data:
            self.tc_listbox.insert("end", f"[{tc['priority']}] {tc['tc_id']} | {tc['title']}")
        self.log_msg(f"로컬 엑셀에서 TC {len(self.tc_data)}건 로드: {os.path.basename(path)}")
        for w in warnings[:5]:
            self.log_msg(f"  ⓘ {w}")

    # ---- 대시보드 ----                                            [NEW]
    def _ensure_dashboard(self):
        """대시보드 서버를 (한 번만) 띄우고 주소를 돌려준다.
        [NEW v0.4.0] TC를 대시보드에서 작성할 수 있게 되었으므로 프로그램을 켜는 시점에
        미리 띄운다. 포트는 8765를 우선 사용해서 주소를 북마크할 수 있게 한다."""
        if not self._dashboard_addr:
            # [NEW v0.6.0] 대시보드 단독 실행 프로그램(QA_Runner_K_Dashboard.exe)이 이미 떠 있으면
            # 하나 더 띄우지 않고 그걸 그대로 쓴다 (같은 DB를 보므로 데이터도 동일).
            existing = dashboard_server.find_running_dashboard()
            if existing:
                self._dashboard_addr = existing
                self.log_msg(f"📊 대시보드(이미 실행 중): http://{existing[0]}:{existing[1]}/")
                self._set_dashboard_url()
                return self._dashboard_addr
            try:
                host, port = dashboard_server.run_in_background(db_path=results_store.get_db_path())
                self._dashboard_addr = (host, port)
                self.log_msg(f"📊 대시보드: http://{host}:{port}/   (결과 조회 + TC 관리)")
                self._set_dashboard_url()
            except Exception as e:
                self.log_msg(f"⚠ 대시보드 실행 실패: {e}")
                self.dashboard_url_var.set("대시보드를 열지 못했습니다")
                return None
        return self._dashboard_addr

    def _dashboard_url(self, path=""):
        addr = self._dashboard_addr
        return f"http://{addr[0]}:{addr[1]}/{path}" if addr else ""

    def _set_dashboard_url(self):
        self.dashboard_url_var.set(self._dashboard_url())

    def _open_browser(self, url):
        """브라우저 새 창(또는 새 탭)으로 연다. new=2는 '가능하면 새 탭'이라
        이미 열려 있는 브라우저 창을 덮어쓰지 않는다."""
        if not url:
            messagebox.showwarning("대시보드", "대시보드가 아직 준비되지 않았습니다.\n로그 창의 메시지를 확인해 주세요.")
            return
        try:
            webbrowser.open(url, new=2)
        except Exception as e:
            self.log_msg(f"⚠ 브라우저 열기 실패: {e}  (주소를 복사해서 직접 여세요: {url})")

    def open_dashboard(self):
        """[대시보드 바로가기] - 대시보드 첫 화면(실행 결과)을 새 창으로. [NEW v0.11.0]"""
        self._ensure_dashboard()
        self._open_browser(self._dashboard_url())

    def copy_dashboard_url(self):
        """주소를 클립보드로. 다른 브라우저나 메신저에 붙여넣을 때 쓴다. [NEW v0.11.0]"""
        url = self._dashboard_url()
        if not url:
            return
        try:
            self.root.clipboard_clear()
            self.root.clipboard_append(url)
            self.log_msg(f"주소를 복사했습니다: {url}")
        except Exception as e:
            self.log_msg(f"⚠ 복사 실패: {e}")

    def open_results_dashboard(self):
        self._ensure_dashboard()
        self._open_browser(self._dashboard_url())

    def open_tc_dashboard(self):
        """대시보드의 'TC 관리' 화면을 바로 연다. [NEW v0.4.0]"""
        self._ensure_dashboard()
        self._open_browser(self._dashboard_url("tcs"))

    def log_msg(self, msg, tag="info"):
        def _append():
            self.log_text.configure(state="normal")
            self.log_text.insert("end", str(msg) + "\n")
            self.log_text.see("end")
            self.log_text.configure(state="disabled")
        try:
            self.root.after(0, _append)
        except Exception:
            print(msg)

    # ---- 자동 업데이트 ----                                   [REUSED 원본 그대로]
    def check_update_and_prompt(self):
        threading.Thread(target=self._check_update_worker, daemon=True).start()

    def manual_check_update(self):
        self.log_msg("업데이트 확인 중...")
        threading.Thread(target=self._check_update_worker, args=(True,), daemon=True).start()

    def _check_update_worker(self, manual=False):
        info = get_latest_release_info()
        if not info or not info.get("version"):
            if manual:
                self.log_msg("업데이트 정보를 가져오지 못했습니다.")
            return
        if info["version"] and info["version"] != APP_VERSION:
            self.root.after(0, lambda: self.prompt_update_ui(info))
        elif manual:
            self.log_msg("최신 버전입니다.")

    def prompt_update_ui(self, info):
        if messagebox.askyesno(
            "업데이트", f"새 버전 {info['version']}이 있습니다. 지금 업데이트할까요?\n\n{info.get('notes','')[:300]}"
        ):
            if info.get("download_url"):
                do_update(info["download_url"], log_fn=self.log_msg)
            else:
                self.log_msg("⚠ 다운로드 URL을 찾지 못했습니다.")

    # ---- EC2 연동 ----                                        [TODO: 실제 응답 필드명 확정 필요]
    def load_sessions(self):
        ec2 = self.ec2_var.get().rstrip("/")
        try:
            resp = requests.get(f"{ec2}/api/sessions", timeout=10)
            resp.raise_for_status()
            sessions = resp.json()
            self.session_map = {s.get("name", str(s.get("id"))): s for s in sessions}
            self.log_msg(f"세션 {len(sessions)}건 로드")
            # TODO: 세션 콤보박스 values 갱신, 선택 시 load_sheets 연쇄 호출 바인딩
        except Exception as e:
            self.log_msg(f"⚠ 세션 로드 실패: {e}")

    def load_sheets(self):
        # TODO: GET {ec2}/api/sessions/{id}/sheets - 원본과 동일 엔드포인트 가정
        pass

    def load_tc_list(self):
        """"TC 불러오기" 버튼 핸들러. TC 소스(로컬 엑셀 / 대시보드 / EC2)에 따라 분기. [NEW]"""
        source = self.tc_source_var.get()
        if source == "local":
            path = self.local_xlsx_path_var.get()
            if not path:
                self.log_msg("⚠ 먼저 엑셀 파일을 선택하세요")
                return
            self._load_tcs_from_local_xlsx(path)
        elif source == "custom":
            self._load_tcs_from_custom()
        else:
            self._load_tcs_from_ec2()

    def _load_tcs_from_custom(self):
        """대시보드 'TC 관리'에서 추가한 TC를 불러온다 ('실행 포함' 상태인 것만). [NEW v0.4.0]

        엑셀 로더(_load_tcs_from_local_xlsx)와 완전히 같은 모양의 dict를 만들어서,
        실행 루프/판정/결과 저장 쪽은 TC가 어디서 왔는지 몰라도 되게 한다."""
        try:
            rows = results_store.list_custom_tcs(only_enabled=True)
        except Exception as e:
            self.log_msg(f"⚠ 대시보드 TC 로드 실패: {e}")
            return

        tcs = []
        for r in rows:
            tc_id = clean_text(r.get("tc_no")) or f"c{r.get('id')}"
            tcs.append({
                "id": f"custom:{r.get('id')}",
                "tc_id": tc_id,
                "sheet_name": clean_text(r.get("sheet")) or "대시보드",   # [v0.15.0]
                "title": clean_text(r.get("title")),
                "precondition": clean_text(r.get("precondition")),
                "steps": r.get("steps") or "",
                "expected": clean_text(r.get("expected")),
                "priority": clean_text(r.get("priority")) or "미지정",
                "note": clean_text(r.get("note")),
                "result": "",
            })

        self.tc_data = tcs
        self.tc_listbox.delete(0, "end")
        for tc in self.tc_data:
            self.tc_listbox.insert("end", f"[{tc['priority']}] {tc['tc_id']} | {tc['title']}")
        if tcs:
            self.log_msg(f"대시보드에서 TC {len(tcs)}건 로드 (실행 포함 상태만)")
        else:
            self.log_msg("⚠ 대시보드에 '실행 포함' 상태인 TC가 없습니다 - "
                         "[대시보드에서 TC 추가/수정...] 버튼으로 추가하세요")

    def _load_tcs_from_ec2(self):
        """TC 목록 로드(EC2). 새 포맷 필드(테스트 항목/사전조건/테스트 절차/예상 결과/우선순위)로 매핑.

        TODO: 실제 EC2 응답 JSON의 키 이름을 백엔드와 확인해서 아래 매핑을 맞출 것.
        지금은 원본 API 계약(/api/sessions/{id}/tcs?sheet=...)을 그대로 가정하고,
        원본 필드명(depth_path 등) 대신 새 포맷 필드명을 우선 사용하되 원본 키가
        오면 폴백하도록 작성함 (백엔드 마이그레이션 전환기 대비).
        """
        ec2 = self.ec2_var.get().rstrip("/")
        info = self.session_map.get(self.session_var.get(), {})
        session_id = info.get("id") if isinstance(info, dict) else None
        if not session_id:
            self.log_msg("⚠ 세션을 먼저 선택하세요")
            return
        sheet = self.sheet_var.get()
        url = f"{ec2}/api/sessions/{session_id}/tcs"
        if sheet and sheet != "전체":
            url += f"?sheet={urllib.parse.quote(sheet)}"
        try:
            resp = requests.get(url, timeout=10)
            resp.raise_for_status()
            raw_tcs = resp.json()
        except Exception as e:
            self.log_msg(f"⚠ TC 로드 실패: {e}")
            return

        self.tc_data = [self._normalize_tc(t) for t in raw_tcs]
        self.tc_listbox.delete(0, "end")
        for tc in self.tc_data:
            self.tc_listbox.insert(
                "end", f"[{tc['priority']}] {tc['tc_id']} | {tc['title']}"
            )
        self.log_msg(f"TC {len(self.tc_data)}건 로드")

    @staticmethod
    def _normalize_tc(raw: dict) -> dict:
        """새/구 필드명 모두 대응하는 정규화. [TODO] 백엔드 확정되면 폴백 제거."""
        return {
            "id": raw.get("id"),
            "tc_id": raw.get("tc_id", str(raw.get("no", raw.get("id", "")))),
            "sheet_name": raw.get("sheet_name", raw.get("sheet", "")),
            "title": raw.get("title", raw.get("테스트 항목", raw.get("depth_path", ""))),
            "precondition": clean_text(raw.get("precondition", raw.get("사전조건", ""))),
            "steps": raw.get("steps", raw.get("테스트 절차", raw.get("procedure", ""))),
            "expected": clean_text(raw.get("expected", raw.get("예상 결과", ""))),
            "priority": raw.get("priority", raw.get("우선순위", "")),
            "note": raw.get("note", raw.get("비고", "")),
            "result": raw.get("result", ""),
        }

    def select_all_tc(self):
        self.tc_listbox.select_set(0, "end")

    def deselect_all_tc(self):
        self.tc_listbox.select_clear(0, "end")

    # ---- 실행 제어 ----
    def start_worker(self):
        if self.running:
            return
        self.running = True
        self._save_local_config()
        threading.Thread(target=self.run_worker, daemon=True).start()

    def stop_worker(self):
        self.running = False
        self.log_msg("중지 요청됨 (현재 TC 완료 후 종료)")

    # ---- AI 호출 ----                                         [REUSED 원본 그대로]
    def _to_claude_content(self, content):
        """OpenAI 스타일 content 블록 리스트 -> Claude 스타일로 변환."""
        blocks = []
        for item in content:
            if item.get("type") == "text":
                blocks.append({"type": "text", "text": item["text"]})
            elif item.get("type") == "image_url":
                url = item["image_url"]["url"]
                # data:image/png;base64,xxxx 형식 가정
                media_type, b64data = url.split(";base64,")
                media_type = media_type.replace("data:", "")
                blocks.append({
                    "type": "image",
                    "source": {"type": "base64", "media_type": media_type, "data": b64data},
                })
        return blocks

    def call_ai(self, client, provider, model, content, max_tokens, timeout=None):
        """provider(OpenAI/Claude)에 따라 API를 통일된 방식으로 호출하고 텍스트 응답만 반환."""
        if provider == "Claude":
            msg_content = content if isinstance(content, str) else self._to_claude_content(content)
            resp = client.messages.create(
                model=model, max_tokens=max_tokens,
                messages=[{"role": "user", "content": msg_content}],
            )
            return "".join(b.text for b in resp.content if getattr(b, "type", "") == "text")
        else:
            kwargs = {"model": model, "messages": [{"role": "user", "content": content}],
                      "max_completion_tokens": max_tokens}
            if timeout:
                kwargs["timeout"] = timeout
            resp = client.chat.completions.create(**kwargs)
            return resp.choices[0].message.content

    # ---- 핵심 실행 루프 ----                                   [NEW 구조 / REUSED 세부 로직]
    def run_worker(self):
        try:
            self._run_worker_impl()
        except Exception as e:
            self.log_msg(f"❌ 실행 중 오류: {e}")
        finally:
            self._done()

    def _run_worker_impl(self):
        ec2 = self.ec2_var.get().rstrip("/")
        api_key = self.key_var.get()
        provider = self.provider_var.get()
        limit = int(self.limit_var.get() or 0)
        tc_source = self.tc_source_var.get()  # 'local' | 'ec2' - 결과 저장/제출 분기에 사용 [NEW]

        # [NEW] 실행 배치 식별자. 결과 대시보드에서 "이번에 돌린 것"끼리 묶어보기 위함.
        run_id = time.strftime("%Y%m%d_%H%M%S")
        self.current_run_id = run_id
        if tc_source == "local":
            source_ref = self.local_xlsx_path_var.get()
        elif tc_source == "custom":
            source_ref = "대시보드 추가 TC"   # [NEW v0.4.0]
        else:
            source_ref = self.session_var.get()

        # [NEW] 규칙 기반 전용 모드: AI를 아예 호출하지 않는다.
        # "테스트 절차"의 [대괄호]/"따옴표"/엔터 표기만으로 실행하고, 판정은 화면 텍스트 기준.
        # API 키가 없어도 로그인 -> 이동/클릭 -> 팝업 대기 -> 스크린샷 -> 대시보드까지 검증 가능.
        rule_only = bool(self.rule_only_var.get())
        client = None
        if rule_only:
            self.log_msg("⚙ 규칙 기반 전용 모드 - AI 호출 없이 '테스트 절차' 문장만으로 실행합니다")
            if api_key:
                self.log_msg("  ⓘ API Key가 입력돼 있지만 이 모드에서는 사용하지 않습니다 (체크 해제 시 AI 사용)")
        else:
            if not api_key:
                self.log_msg("❌ API Key가 없습니다. 키를 입력하거나 '규칙 기반으로만 실행'을 체크하세요")
                return
            if provider == "Claude":
                import anthropic
                client = anthropic.Anthropic(api_key=api_key)
            else:
                import openai
                client = openai.OpenAI(api_key=api_key)

        # [NEW v0.5.0] 대시보드 소스인데 아직 목록을 안 불러왔으면 자동으로 불러온다.
        # (대시보드에서 엑셀을 올린 직후 [시작]만 눌러도 바로 돌게 하려는 것)
        if tc_source == "custom" and not self.tc_data:
            self._load_tcs_from_custom()

        selected = list(self.tc_listbox.curselection())
        tcs = [self.tc_data[i] for i in selected] if selected else list(self.tc_data)
        priority = self.priority_var.get()
        if priority != "전체":
            wanted = priority.split("+")
            tcs = [t for t in tcs if t["priority"] in wanted]
        tcs = [t for t in tcs if not t.get("result")]
        if limit:
            tcs = tcs[:limit]
        if not tcs:
            self.log_msg("검증할 TC가 없어요")
            return

        self.log_msg(f"🎯 대상 TC: {len(tcs)}건 (소스: {tc_source})")

        from playwright.sync_api import sync_playwright

        # PyInstaller 번들 시 Chromium 경로 자동 설정                [REUSED 원본 그대로]
        if getattr(sys, "frozen", False):
            base_path = sys._MEIPASS
            ms_playwright = os.path.join(base_path, "ms-playwright")
            if os.path.exists(ms_playwright):
                os.environ["PLAYWRIGHT_BROWSERS_PATH"] = ms_playwright
            else:
                user_playwright = os.path.join(os.environ.get("LOCALAPPDATA", ""), "ms-playwright")
                if os.path.exists(user_playwright):
                    os.environ["PLAYWRIGHT_BROWSERS_PATH"] = user_playwright

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=False)
            ctx = browser.new_context(viewport={"width": 1920, "height": 1080})
            page = ctx.new_page()
            page.on("dialog", lambda d: d.accept())

            if not self._login(page):
                browser.close()
                return

            results = {RESULT_PASS: 0, RESULT_FAIL: 0, RESULT_NEEDS_REVIEW: 0}
            engine = TCExecutionEngine(page, log_fn=self.log_msg)

            for i, tc in enumerate(tcs):
                if not self.running:
                    break
                self.log_msg(f"\n[{i+1}/{len(tcs)}] TC {tc['tc_id']} | {tc['priority']} | {tc['title']}")
                self.status_var.set(f"{i}/{len(tcs)} 완료")

                after_b64 = before_b64 = None
                try:
                    judgment, reason, after_b64, before_b64 = self._run_single_tc(
                        page, tc, client, provider, engine, rule_only=rule_only)
                except Exception as e:
                    # [NEW] 원본은 이런 경우를 그냥 "ERROR" 카운트로만 남겼는데, 그러면 사람이
                    # 화면을 안 보면 뭐가 왜 안 됐는지 알 수 없었음. "확인 필요"로 명확히 남기고
                    # 이유(예외 메시지)까지 기록해서 대시보드에서 바로 확인할 수 있게 한다.
                    judgment, reason = RESULT_NEEDS_REVIEW, f"실행 중 오류: {str(e)[:200]}"
                    self.log_msg(f"  ⚠ TC 처리 오류 → 확인 필요로 기록: {str(e)[:120]}")
                    try:
                        after_b64 = self._screenshot_b64(page)
                    except Exception:
                        pass

                results[judgment] = results.get(judgment, 0) + 1
                self._save_result(tc, judgment, reason, after_b64, before_b64,
                                   run_id=run_id, source=tc_source, source_ref=source_ref, ec2=ec2)

            self.log_msg(
                f"\n완료: PASS {results[RESULT_PASS]} / FAIL {results[RESULT_FAIL]} / "
                f"확인 필요 {results[RESULT_NEEDS_REVIEW]}"
            )
            self.open_results_dashboard()
            browser.close()

    def _login(self, page) -> bool:
        """시작 URL/로그인 - TC 엑셀과 분리된 프로그램 설정 기반. [REUSED 원본 3분기 로직]"""
        start_url = self.start_url_var.get().rstrip("/")
        if not start_url:
            self.log_msg("❌ 시작 URL이 설정되지 않았습니다 ('시작 지점 / 로그인 설정'에서 입력)")
            return False

        login_type = self.login_type_var.get()
        stg_id = self.login_id_var.get()
        stg_pw = self.login_pw_var.get()

        if login_type == "idpw" and stg_id:
            self.log_msg("🔐 ID/PW 로그인 중...")

            # [FIX v0.3.1] 로그인 페이지 탐색 기준을 "텍스트 입력란이 있는지"에서
            # "비밀번호 입력란이 있는지"로 바꿈. 랩커넥트는 /login이 404이고 /sign-in이
            # 로그인 페이지인데, 404 페이지나 다른 화면에도 텍스트 입력란(검색창 등)은
            # 있을 수 있어서 엉뚱한 화면을 로그인 페이지로 오인할 수 있었음.
            id_input = pw_input = None
            used_url = None
            for login_path in ["/sign-in", "/login", "/signin", ""]:
                target = f"{start_url}{login_path}" if login_path else f"{start_url}/"
                try:
                    page.goto(target, timeout=20000, wait_until="domcontentloaded")
                except Exception as e:
                    self.log_msg(f"  ⓘ {target} 접속 실패: {str(e)[:60]}")
                    continue
                try:
                    page.wait_for_load_state("networkidle", timeout=8000)
                except Exception:
                    pass
                try:
                    # SPA는 첫 렌더가 늦으므로 비밀번호 입력란이 보일 때까지 조건 대기
                    page.wait_for_selector('input[type="password"]', state="visible", timeout=5000)
                except Exception:
                    self.log_msg(f"  ⓘ {target} - 로그인 폼 없음 (건너뜀)")
                    continue

                pw_input = page.locator('input[type="password"]').first
                # 아이디 칸: 로그인 화면에서는 비밀번호 칸보다 앞에 오는 첫 번째 보이는 입력란
                cands = page.locator('input[type="text"], input[type="email"], input[type="tel"], input:not([type])')
                for i in range(min(cands.count(), 8)):
                    c = cands.nth(i)
                    try:
                        if c.is_visible(timeout=500):
                            id_input = c
                            break
                    except Exception:
                        continue
                if id_input:
                    used_url = target
                    break

            if not (id_input and pw_input):
                self.log_msg("❌ 로그인 폼을 찾지 못했습니다 (시작 URL이 맞는지 확인하세요)")
                return False
            self.log_msg(f"  ✓ 로그인 폼 발견: {used_url}")

            url_before = page.url
            try:
                id_input.fill(stg_id)
                pw_input.fill(stg_pw)
            except Exception as e:
                self.log_msg(f"❌ 로그인 정보 입력 실패: {str(e)[:100]}")
                return False

            # 로그인 버튼. "로그인 연장"/"비밀번호 찾기"/"회원가입" 같은 유사 버튼은 제외
            clicked = False
            for sel in ['button:has-text("로그인")', 'button:has-text("Login")',
                        'button:has-text("Sign in")', 'button[type="submit"]']:
                loc = page.locator(sel)
                try:
                    count = min(loc.count(), 5)
                except Exception:
                    count = 0
                for i in range(count):
                    btn = loc.nth(i)
                    try:
                        if not btn.is_visible(timeout=500):
                            continue
                        label = clean_text(btn.inner_text())
                        if any(w in label for w in ["연장", "찾기", "가입", "취소"]):
                            continue
                        btn.click()
                        clicked = True
                        self.log_msg(f"  ✓ 로그인 버튼 클릭: {label or sel}")
                        break
                    except Exception:
                        continue
                if clicked:
                    break
            if not clicked:
                try:
                    pw_input.press("Enter")
                    self.log_msg("  ⓘ 로그인 버튼을 못 찾아 Enter로 제출")
                except Exception as e:
                    self.log_msg(f"❌ 로그인 제출 실패: {str(e)[:100]}")
                    return False

            # [FIX v0.3.1] 성공 판정을 URL 문자열 검사에서 "로그인 폼이 사라졌는지"로 변경.
            # 이 서비스는 SPA라서 로그인 버튼을 눌러도 문서 로드가 새로 일어나지 않는다.
            # 그래서 wait_for_load_state("networkidle")이 즉시 끝나고, 그 시점엔 URL이
            # 아직 /sign-in 이어서 로그인이 성공했는데도 실패로 판정됐다(v0.3.0 버그).
            success = False
            try:
                page.wait_for_selector('input[type="password"]', state="hidden", timeout=15000)
                success = True
            except Exception:
                try:
                    page.wait_for_function(
                        "prev => window.location.href !== prev", arg=url_before, timeout=3000
                    )
                    success = True
                except Exception:
                    success = False
            try:
                page.wait_for_load_state("networkidle", timeout=8000)
            except Exception:
                pass

            if not success:
                # 진짜 계정 오류인지 구분할 수 있게 화면에 뜬 메시지를 같이 남긴다
                err = ""
                for sel in ['[role="alert"]', '[class*="error"]', '[class*="Error"]',
                            '[class*="invalid"]', 'p:has-text("비밀번호")', 'span:has-text("비밀번호")']:
                    try:
                        loc = page.locator(sel).first
                        if loc.is_visible(timeout=400):
                            err = clean_text(loc.inner_text())[:150]
                            if err:
                                break
                    except Exception:
                        continue
                self.log_msg(f"❌ 로그인 실패 - 로그인 폼이 그대로 남아있습니다 (현재 URL: {page.url})")
                if err:
                    self.log_msg(f"   화면 메시지: {err}")
                return False

            self.log_msg(f"✅ 로그인 성공 (이동한 화면: {page.url})")
            return True

        elif login_type == "token":
            # TODO: 원본의 "비일만사 토큰" 방식처럼 서비스별 토큰 로그인 흐름을
            # 여기에 채울 것 (도메인/의사ID 드롭다운 등 서비스 특화 로직 - 대상 서비스 확정 후 작성)
            self.log_msg("⚠ token 로그인 방식은 아직 구현되지 않았습니다")
            page.goto(start_url, timeout=20000)
            return True

        else:
            page.goto(start_url, timeout=20000)
            page.wait_for_load_state("networkidle", timeout=15000)
            self.log_msg(f"✅ {start_url} 접속 (로그인 없음)")
            return True

    def _run_single_tc(self, page, tc, client, provider, engine, rule_only=False):
        """TC 1건 처리: 홈 이동 → 절차 기반 액션 생성/실행 → 스크린샷 → 판정.

        원본은 이 로직이 run_worker 안에 12000자 넘게 한 함수로 들어있어 유지보수가
        어려웠음 - 새 버전은 처음부터 별도 메서드로 분리해서 가독성을 확보한다. [NEW]

        액션 생성은 2경로:
          ① 규칙 기반(build_rule_actions) - "테스트 절차"의 [대괄호]/"따옴표"/엔터 표기를
             코드가 직접 해석. 성공하면 AI 액션 생성을 아예 건너뛴다.
          ② AI - ①이 아무 액션도 못 만들었을 때만 (rule_only=True면 이 경로도 안 씀)
        판정도 rule_only=True면 AI 대신 화면 텍스트 기반 보수적 판정(judge_by_text)을 쓴다.
        """
        start_url = self.start_url_var.get().rstrip("/")

        # 홈으로 이동해 사이드바/상태 초기화 (원본과 동일 패턴)
        try:
            page.goto(start_url + "/", timeout=20000, wait_until="domcontentloaded")
        except Exception:
            page.evaluate("window.onbeforeunload = null")
            page.goto(start_url + "/", timeout=20000)
        page.wait_for_load_state("networkidle", timeout=15000)
        page.wait_for_timeout(1500)

        # 세션 만료 감지 -> 재로그인 (원본과 동일 안전장치)
        # [FIX v0.3.1] URL만 보면 SPA에서 세션이 끊겨 로그인 폼이 떠 있어도(URL은 그대로)
        # 감지하지 못한다. 비밀번호 입력란이 보이는지도 함께 확인한다.
        session_expired = "/login" in page.url or "/sign-in" in page.url
        if not session_expired:
            try:
                session_expired = page.locator('input[type="password"]').first.is_visible(timeout=800)
            except Exception:
                session_expired = False
        if session_expired and self.login_type_var.get() == "idpw":
            self.log_msg("  ⚠ 세션 만료 감지 → 재로그인 시도")
            if not self._login(page):
                raise RuntimeError("재로그인 실패")

        # [NEW] 메뉴 키워드 매칭(navigate_by_menu) 제거 - "테스트 절차" 문장 안에
        # 이미 이동 단계가 포함되어 있다고 가정하고, 액션 생성 AI가 전부 처리한다.
        before_b64 = None
        # TODO: needs_before_after 판단 로직(원본은 verify_type + 기능경로 키워드 기반) 이식 또는
        # 새 포맷 기준(예: '예상 결과'에 "변경"/"비교" 등의 단어가 있으면 전후 비교) 설계 필요
        do_before_after = any(k in tc.get("expected", "") for k in ["변경", "비교", "전환"])
        if do_before_after:
            page.reload()
            page.wait_for_load_state("networkidle", timeout=10000)
            page.wait_for_timeout(1000)
            before_b64 = self._screenshot_b64(page)

        # ① 규칙 기반 액션 우선 [NEW]
        verify_type = infer_verify_type(tc)
        actions = build_rule_actions(tc)
        if actions:
            self.log_msg(f"  📐 규칙 기반 액션 {len(actions)}건 (검증유형: {verify_type}) - AI 액션 생성 생략")

        # ② 규칙으로 액션을 못 만든 경우에만 AI에게 맡긴다
        if not actions and not rule_only:
            html = page.inner_html("body")
            html = re.sub(r"<script[^>]*>.*?</script>", "", html, flags=re.DOTALL)
            html = re.sub(r"<style[^>]*>.*?</style>", "", html, flags=re.DOTALL)
            html = re.sub(r'style="[^"]*"', "", html)
            html = re.sub(r"\s+", " ", html)[:5000]

            prompt_action = build_action_prompt(tc, html)
            for attempt in range(3):
                try:
                    content = self.call_ai(client, provider, self.action_model_var.get(), prompt_action, 1500, timeout=50)
                    if not content or not content.strip():
                        raise ValueError("빈 응답")
                    raw = re.sub(r"```json|```", "", content.strip()).strip()
                    actions = json.loads(raw).get("actions", [])
                    self.log_msg(f"  📋 AI 액션 {len(actions)}건 (검증유형: {verify_type})")
                    break
                except Exception as api_err:
                    if attempt < 2:
                        self.log_msg(f"  ⚠ 액션생성 재시도 ({attempt+1}/3)")
                        page.wait_for_timeout(1500)
                    else:
                        self.log_msg(f"  ⚠ 액션 생성 실패: {str(api_err)[:80]}")
        elif not actions:
            # 규칙 전용 모드에서 실행할 액션이 없는 경우 = "화면 노출 확인"류 TC.
            # 액션 없이 현재 화면 그대로 판정하는 게 정상 동작이다(인수인계 문서의 '화면노출' 템플릿).
            self.log_msg(f"  ⓘ 실행할 액션 없음 (검증유형: {verify_type}) - 현재 화면 상태로 판정")

        url_before_actions = page.url
        actions_done = engine.execute(actions, tc)

        # [NEW] 판정용 "액션 후" 스크린샷을 찍기 전 조건부 대기 한 번 더.
        # 원본에서 TC14가 FAIL로 오판정된 지점이 정확히 "마지막 액션 직후 대기 없이
        # 바로 스크린샷"이었음 - 개별 액션(_click)마다 대기는 있어도 마지막 액션과
        # 판정 스크린샷 사이엔 아무 대기가 없었던 구조적 빈틈을 메운다.
        try:
            page.wait_for_load_state("networkidle", timeout=2000)
        except Exception:
            pass

        after_b64 = self._screenshot_b64(page)
        body_text = page.inner_text("body")[:3000]

        if rule_only:
            # [NEW] AI 없이 코드로 판정. 근거를 못 찾으면 FAIL이 아니라 "확인 필요".
            # 팝업확인/화면이동 TC는 텍스트보다 확실한 근거(모달 존재, URL 변경)를 같이 넘긴다.
            try:
                modal_visible = page.locator(MODAL_SELECTOR).last.is_visible(timeout=500)
            except Exception:
                modal_visible = False
            judgment, reason = judge_by_text(
                tc, body_text, modal_visible=modal_visible,
                url_changed=(page.url != url_before_actions),
            )
            reason = f"[코드 판정] {reason}"
        else:
            content_msgs = [{"type": "text", "text": build_judge_prompt(tc, actions_done, body_text, bool(before_b64))}]
            if before_b64:
                content_msgs.append({"type": "image_url", "image_url": {"url": f"data:image/png;base64,{before_b64}"}})
            content_msgs.append({"type": "image_url", "image_url": {"url": f"data:image/png;base64,{after_b64}"}})

            # [NEW] 판정 실패/파싱 불가 시에도 무조건 FAIL로 밀어넣지 않고 "확인 필요"로 남김
            # (원본은 이런 케이스를 FAIL 취급해서 실제 실패와 구분이 안 됐음)
            judgment, reason = RESULT_NEEDS_REVIEW, "AI 판정 실패 - 응답을 받지 못함"
            for attempt in range(3):
                try:
                    raw = self.call_ai(client, provider, self.judge_model_var.get(), content_msgs, 400, timeout=60)
                    raw = re.sub(r"```json|```", "", raw.strip()).strip()
                    parsed = json.loads(raw)
                    judgment = parsed.get("judgment", RESULT_NEEDS_REVIEW)
                    if judgment not in (RESULT_PASS, RESULT_FAIL, RESULT_NEEDS_REVIEW):
                        judgment = RESULT_NEEDS_REVIEW
                    reason = parsed.get("reason", "")
                    break
                except Exception:
                    if attempt < 2:
                        page.wait_for_timeout(1000)

        icon = {"PASS": "✅", "FAIL": "❌"}.get(judgment, "⚠")
        self.log_msg(f"  {icon} {judgment} - {reason[:80]}")
        return judgment, reason, after_b64, before_b64

    @staticmethod
    def _screenshot_b64(page) -> str:
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
            path = f.name
        page.screenshot(path=path, full_page=True)
        with open(path, "rb") as f:
            b64 = base64.b64encode(f.read()).decode()
        try:
            os.unlink(path)
        except Exception:
            pass
        return b64

    def _save_result(self, tc, judgment, reason, after_b64, before_b64, run_id, source, source_ref, ec2):
        """실행 결과 저장. [NEW] 소스에 상관없이 항상 로컬 DB+스크린샷 파일로 남겨서
        "결과 보기" 대시보드에서 바로 볼 수 있게 하고, EC2가 소스인 TC는 추가로
        원본과 동일하게 EC2에도 PUT 제출한다 (로컬 파일 TC는 EC2 tc id가 없어 제출 대상이 아님)."""
        shot_dir = results_store.get_screenshot_dir(run_id)
        before_path = after_path = None
        try:
            if before_b64:
                before_path = os.path.join(shot_dir, f"{tc.get('tc_id','?')}_before.png")
                with open(before_path, "wb") as f:
                    f.write(base64.b64decode(before_b64))
            if after_b64:
                after_path = os.path.join(shot_dir, f"{tc.get('tc_id','?')}_after.png")
                with open(after_path, "wb") as f:
                    f.write(base64.b64decode(after_b64))
        except Exception as e:
            self.log_msg(f"  ⚠ 스크린샷 저장 실패: {e}")

        try:
            results_store.insert_result(
                tc, judgment, reason, source=source, source_ref=source_ref, run_id=run_id,
                before_screenshot=before_path, after_screenshot=after_path,
            )
        except Exception as e:
            self.log_msg(f"  ⚠ 로컬 결과 저장 실패: {e}")

        if source == "ec2":
            self._submit_result_ec2(ec2, tc, judgment, reason, after_b64, before_b64)

    def _submit_result_ec2(self, ec2, tc, judgment, reason, after_b64, before_b64):
        """PUT /api/results/{tc_id} - 원본과 동일 엔드포인트 가정. [TODO] 확정 필요"""
        payload = {
            "result": judgment,
            "result_type": "ai",
            "memo": "",
            "ai_judgment": judgment,
            "ai_reason": reason[:1000],
            "screenshot_b64": after_b64,
        }
        if before_b64:
            payload["screenshot_before_b64"] = before_b64
        try:
            requests.put(f"{ec2}/api/results/{tc['id']}", json=payload, timeout=30)
        except Exception as e:
            self.log_msg(f"  ⚠ EC2 결과 제출 실패: {e}")

    def _done(self):
        self.running = False
        self.status_var.set("대기 중")


def main():
    # [v0.7.0] "QA_Runner_K.exe --dashboard" 로 실행하면 GUI 대신 대시보드만 띄운다.
    #
    # 대시보드 전용 exe(QA_Runner_K_Dashboard.exe)를 따로 배포했더니, 서명 없는 작은
    # PyInstaller exe라서 Windows Defender가 다운로드 즉시 삭제해 버렸다. 반면 본 exe는
    # 이미 통과해서 잘 쓰고 있으므로, 새 파일을 받지 않아도 되게 여기에 모드를 넣었다.
    # (onefile 압축 해제 때문에 첫 실행이 20~40초 걸리는 건 감수한다)
    # --quiet(= --startup)는 부팅 시 자동 시작용. 브라우저를 열지 않고 창도 내려둔다.
    args = [a.lower().lstrip("-/") for a in sys.argv[1:]]
    if "dashboard" in args:
        import dashboard_app
        quiet = "quiet" in args or "startup" in args
        dashboard_app.main(open_browser=not quiet, minimized=quiet)
        return

    root = tk.Tk()
    QAWorkerApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
