"""검사 상태 '전체' 선택과 해제 직후의 체크 상태를 각각 기록한다."""
import re
import time
from urllib.parse import urlsplit

from verifications.reception_defaults_verification import read_states, STATUSES

LABELS = ('전체',) + STATUSES


def applies(tc):
    title = re.sub(r'\s+', '', str(tc.get('title') or ''))
    context = re.sub(r'\s+', '', ' '.join(str(tc.get(k) or '') for k in
                                        ('sheet_name', 'precondition', 'steps')))
    return '검사상태' in title and '전체' in title and '검사접수' in context


def collect(page):
    evidence = {}
    trigger = None
    try:
        if not re.search(r'(?:^|/)receptions?/?$', urlsplit(page.url).path):
            return {'error': '검사 접수 목록 경로 진입 근거 없음'}
        trigger = page.locator('button[id^="multi-select-"]').filter(visible=True)
        if trigger.count() != 1:
            return {'error': '검사 상태 드롭다운을 하나로 식별하지 못함'}
        scope_id = trigger.get_attribute('aria-controls') or trigger.get_attribute('id') + '-options'
        scope = page.locator('[id="' + scope_id.replace('"', '\\"') + '"]')

        def opened():
            if trigger.get_attribute('aria-expanded') != 'true':
                trigger.click(timeout=3000)
            scope.wait_for(state='visible', timeout=3000)

        def snapshot(target=None):
            deadline = time.monotonic() + 3
            while True:
                opened()
                reading = read_states(page, scope_id, LABELS)
                states = reading['states']
                if target is None or all(states.get(label) is target for label in LABELS):
                    return reading
                if time.monotonic() >= deadline:
                    return reading
                page.wait_for_timeout(100)

        def change(checked):
            opened()
            control = scope.locator('[role="checkbox"]').filter(
                has=page.locator('[data-checkbox-label]').filter(has_text=re.compile(r'^\s*전체\s*$')))
            if control.count() == 0:
                control = scope.get_by_role('checkbox', name='전체', exact=True)
            if control.count() != 1:
                raise ValueError('[전체] 체크박스를 하나로 식별하지 못함')
            control.set_checked(checked, timeout=3000)

        evidence['before'] = snapshot()
        before = evidence['before']['states']
        if any(before.get(label) is None for label in LABELS):
            return dict(evidence, error='초기 검사 상태 체크값 식별 실패')
        selected = sum(before[s] for s in STATUSES)
        if before['전체'] or not 0 < selected < len(STATUSES):
            return dict(evidence, error='일부 상태만 선택된 초기 조건이 충족되지 않음')
        change(True)
        evidence['selected'] = snapshot(True)
        # 선택 단계가 실패하면 해제로 덮어쓰지 않고 그 시점의 근거로 판정한다.
        if not all(evidence['selected']['states'].get(s) is True for s in LABELS):
            return evidence
        change(False)
        evidence['cleared'] = snapshot(False)
    except Exception as exc:
        evidence['error'] = '전체 선택·해제 근거 수집 실패: ' + str(exc)
    finally:
        if trigger is not None:
            try:
                if trigger.count() == 1 and trigger.get_attribute('aria-expanded') == 'true':
                    trigger.click(timeout=3000)
            except Exception:
                evidence['error'] = '검사 상태 드롭다운을 닫지 못함'
    return evidence


def verify(evidence):
    if not evidence or evidence.get('error'):
        return 'FAIL', '검증 불가: ' + ((evidence or {}).get('error') or '전체 선택·해제 실행 근거 없음')
    for stage, target, label in (('selected', True, '전체 선택 직후'),
                                 ('cleared', False, '전체 해제 직후')):
        states = evidence.get(stage, {}).get('states', {})
        missing = [s for s in LABELS if states.get(s) is None]
        if missing:
            return 'FAIL', '검증 불가: ' + label + ' 체크 상태 근거 없음: ' + ', '.join(missing)
        wrong = [s for s in LABELS if states[s] is not target]
        if wrong:
            return 'FAIL', label + (' 미선택 항목: ' if target else '선택이 유지된 항목: ') + ', '.join(wrong)
    return 'PASS', '전체 선택 직후 모든 상태 선택 + 전체 해제 직후 모든 상태 해제 확인 (조회 결과는 검증 범위 제외)'
