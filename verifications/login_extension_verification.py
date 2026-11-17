"""로그인 연장은 화면 단어가 아니라 타이머와 갱신 응답으로 검증한다."""
import re
import time
from urllib.parse import urlsplit


def requests_click(steps):
    """같은 절의 로그인 연장 대상에 명시된 긍정 클릭만 판별한다."""
    for line in str(steps or '').splitlines():
        target=re.search(r'로그인\s*연장\]?(.*)',line)
        if not target:
            continue
        clause=re.split(r'[.;。]|\[[^\]]+\]',target.group(1),maxsplit=1)[0]
        if re.search(r'클릭하지|클릭\s*(?:없이|금지)|누르지',clause):
            continue
        if re.search(r'클릭(?:한다|합니다|하고|하여|해서|해주세요|한\s*(?:후|뒤)|[ \t]*(?:후|뒤)|[!?]?[ \t]*$)|누른다|누릅니다|눌러|누르고|누른\s*(?:후|뒤)',clause):
            return True
    return False


def applies(tc):
    """버튼 스타일 관찰과 구분해 실제 클릭·시간 갱신을 요구할 때만 적용한다."""
    expected=str(tc.get('expected') or '')
    return (requests_click(tc.get('steps')) and bool(re.search(r'시간|타이머',expected))
            and bool(re.search(r'초기|증가|늘|갱신|복원|(?:시간|타이머)[^\n.]{0,30}연장',expected)))


def parse_display_time(value):
    """화면 hh:mm:ss를 검증해 초로 변환한다. 잘못된 값은 None이다."""
    match = re.fullmatch(r'(\d{2}):(\d{2}):(\d{2})', str(value or ''))
    if not match:
        return None
    h, m, s = map(int, match.groups())
    return h*3600+m*60+s if m < 60 and s < 60 else None


def snapshot(page):
    text = page.evaluate(r'''() => {
        const visible = e => e.getClientRects().length && getComputedStyle(e).visibility !== 'hidden';
        const labels = [...document.querySelectorAll('p, span, label')].filter(e =>
            visible(e) && e.innerText.trim() === '로그아웃 남은 시간');
        if (labels.length !== 1) return null;
        const group = labels[0].parentElement;
        const times = group.innerText.match(/\b\d{2}:\d{2}:\d{2}\b/g) || [];
        if (times.length !== 1) return null;
        return times[0];
    }''')
    return parse_display_time(text)


def verify(evidence):
    if not evidence or evidence.get('before') is None or evidence.get('after') is None:
        return '확인 필요', '로그인 연장 전후 타이머를 하나로 식별하지 못함'
    before, after = evidence['before'], evidence['after']
    reset = evidence.get('server_remaining')
    if reset is None:
        return '확인 필요', '로그인 연장 응답의 만료 시각 근거를 수집하지 못함'
    if abs(after - reset) > 3:
        return '확인 필요', '갱신 응답의 만료 시각과 화면 타이머가 일치하지 않음'
    if after <= before:
        return '확인 필요', '남은 시간 증가를 확인하지 못함. 초기 시간보다 줄어든 상태에서 다시 검증 필요'
    return 'PASS', f'로그인 연장 응답의 만료 시각과 타이머 일치 + 남은 시간 증가 확인 ({before}초 → {after}초)'


def click_and_collect(page):
    evidence = {'before': snapshot(page)}
    def response_handler(response):
        if (response.status != 200 or not urlsplit(response.url).path.endswith('/auth/refresh-token')):
            return
        try:
            # 인증 토큰은 보관하거나 출력하지 않고 만료 시각만 사용한다.
            expires = response.json().get('data', {}).get('expiresAt')
            if isinstance(expires, (int, float)) and not isinstance(expires, bool):
                evidence['expires_at'] = expires
        except Exception:
            pass
    page.on('response', response_handler)
    try:
        buttons = page.get_by_role('button', name='로그인 연장', exact=True)
        visible = [button for button in buttons.all() if button.is_visible()]
        if len(visible) != 1:
            raise ValueError('로그인 연장 버튼을 하나로 식별하지 못함')
        visible[0].click(timeout=5000)
        deadline = time.monotonic() + 5
        while True:
            page.wait_for_timeout(100)
            evidence['after'] = snapshot(page)
            if 'expires_at' in evidence:
                evidence['server_remaining'] = max(0, int(evidence['expires_at'] - time.time()))
            if verify(evidence)[0] == 'PASS' or time.monotonic() >= deadline:
                return evidence
    finally:
        page.remove_listener('response', response_handler)
