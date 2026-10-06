"""‘내 환자만 보기’ 해제 TC를 화면 문자열 대신 필터/목록 상태로 검증한다."""

import re
import time
import checkbox_controls
from urllib.parse import parse_qs, urlsplit


LABEL = "내 환자만 보기"


def applies(tc):
    """해제 후 전체 환자 목록을 기대하는 TC에만 적용한다."""
    steps = str(tc.get("steps") or "")
    expected = str(tc.get("expected") or "")
    return (bool(re.search(r"내\s*환자만\s*보기", steps))
            and bool(re.search(r"해제|체크[^.!?\n]{0,15}(?:풀|없)|선택[^.!?\n]{0,15}취소", expected))
            and bool(re.search(r"전체|아닌\s*환자|다른\s*환자", expected)))


def checkbox(page):
    return checkbox_controls.find(page, LABEL)


def snapshot(page):
    checked = checkbox(page).is_checked()
    # 환자 헤더가 있는 실제 테이블의 데이터 행만 확인한다. 본문/메뉴는 근거가 아니다.
    tables = page.evaluate("""() => {
        const visible = e => !!(e.getClientRects().length) &&
            getComputedStyle(e).visibility !== 'hidden';
        return [...document.querySelectorAll('table, [role="table"], [role="grid"]')]
          .filter(visible).filter(t => /환자명/.test(t.innerText) && /환자\s*등록번호/.test(t.innerText))
          .map(t => {
              const rows = [...t.querySelectorAll('tbody tr, [role="row"]')]
                .filter(visible).filter(r => r.querySelectorAll('td, [role="cell"], [role="gridcell"]').length >= 3);
              return {rows: rows.map(r => r.innerText.trim()),
                      mine: rows.filter(r => /내\\s*환자/.test(r.innerText)).length};
          });
    }""")
    if len(tables) != 1:
        return {"checked": checked, "rows": [], "mine": 0}
    return {"checked": checked, **tables[0]}


def all_patient_response(response):
    """성공한 환자 목록 요청에 명시된 필터 해제 값만 근거로 쓴다."""
    try:
        if not 200 <= response.status < 300:
            return False
        request = response.request
        if request.resource_type not in ("xhr", "fetch"):
            return False
        url = urlsplit(response.url)
        if not re.search(r"(?:^|/)patients?(?:/(?:list|search))?/?$", url.path, re.IGNORECASE):
            return False
        params = parse_qs(url.query)
        values = params.get("myPatientYn", [])
        # JSON POST 조회 API도 같은 명시적 필터 필드를 사용할 때 지원한다.
        if not values:
            payload = request.post_data_json
            if isinstance(payload, dict) and "myPatientYn" in payload:
                values = [payload["myPatientYn"]]
        return len(values) == 1 and str(values[0]).lower() in ("n", "false", "0")
    except Exception:
        return False


def verify(evidence):
    if not evidence:
        return "확인 필요", "내 환자 필터와 목록 조회 근거를 수집하지 못함"
    before, after = evidence.get("before", {}), evidence.get("after", {})
    if after.get("checked") is not False:
        return "확인 필요", "‘내 환자만 보기’ 체크박스가 해제되지 않음"
    rows = after.get("rows", [])
    if not rows:
        return "확인 필요", "체크박스 해제는 확인했으나 환자 목록의 데이터 행을 확인하지 못함"
    refreshed = (before.get("checked") is True and before.get("rows") != rows)
    fetched_all = evidence.get("all_response") is True
    # ‘내 환자’ 표시가 있는 행과 없는 행이 함께 있어야 화면만으로 범위 확대를 판단한다.
    mixed = 0 < after.get("mine", 0) < len(rows)
    if refreshed and (fetched_all or mixed):
        proof = ("필터 해제 값(myPatientYn)을 사용한 환자 목록 API의 성공 응답"
                 if fetched_all else "목록 변경 및 ‘내 환자’ 표시가 있는/없는 행의 동시 노출")
        return "PASS", f"‘내 환자만 보기’ 해제 + {proof} + 데이터 행 노출 확인"
    return "확인 필요", "체크박스 해제는 확인했으나 전체 환자 조회/목록 갱신 근거가 부족함"


def uncheck_and_collect(page):
    """응답 리스너는 이 동작에만 연결하고, 개인정보를 사유/로그에 넣지 않는다."""
    before = snapshot(page)
    evidence = {"before": before, "all_response": False}

    def on_response(response):
        if all_patient_response(response):
            evidence["all_response"] = True

    page.on("response", on_response)
    try:
        checkbox(page).set_checked(False, timeout=5000)
        deadline = time.monotonic() + 5
        while True:
            page.wait_for_timeout(100)
            evidence["after"] = snapshot(page)
            if verify(evidence)[0] == "PASS" or time.monotonic() >= deadline:
                return evidence
    finally:
        page.remove_listener("response", on_response)
