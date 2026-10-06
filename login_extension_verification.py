"""로그인 연장은 화면 단어가 아니라 타이머와 갱신 응답으로 검증한다."""
import re
import time
from urllib.parse import urlsplit


def applies(tc):
    return ('로그인 연장' in str(tc.get('steps') or '')
            and bool(re.search(r'시간|타이머|연장', str(tc.get('expected') or ''))))


def snapshot(page):
    return page.evaluate(r'''() => {
        const visible = e => e.getClientRects().length && getComputedStyle(e).visibility !== 'hidden';
        const labels = [...document.querySelectorAll('p, span, label')].filter(e =>
            visible(e) && e.innerText.trim() === '로그아웃 남은 시간');
        if (labels.length !== 1) return null;
        const group = labels[0].parentElement;
        const times = group.innerText.match(/\b\d{2}:\d{2}:\d{2}\b/g) || [];
        if (times.length !== 1) return null;
        const [h, m, s] = times[0].split(':').map(Number);
        return m < 60 && s < 60 ? h*3600 + m*60 + s : null;
    }''')


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
