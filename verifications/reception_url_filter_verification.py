"""필터 UI·URL·조회 응답과 새로고침 전후 행 내용을 비교한다."""
from datetime import date
import hashlib
import json
import re
import time
from urllib.parse import parse_qs, urlsplit
import checkbox_controls
from verifications import prescription_period_verification as period
from verifications import reception_defaults_verification as defaults
from verifications import reception_my_patient_verification as checks
from verifications import reception_combined_filter_verification as combined
from verifications.search_no_enter_verification import find_field

CHANGED = {'keyword', 'startDate', 'endDate', 'myPatientYn', 'receptionProgressStatusNo', 'page'}


def applies(tc):
    title = str(tc.get('title') or '')
    context = re.sub(r'\s+', '', ' '.join(str(tc.get(k) or '') for k in ('sheet_name', 'precondition', 'steps')))
    return 'URL' in title.upper() and '파라미터' in title and '검사접수' in context


def action(tc):
    steps = str(tc.get('steps') or '')
    keywords = set()
    statuses = None
    for line in steps.splitlines():
        if '검색창' in line and '입력' in line:
            keywords.update(re.findall(r'''["'“‘]([^"'”’\n]+)["'”’]''', line))
        if '검사 상태' in line and '만 선택' in line:
            statuses = [s for s in defaults.STATUSES if s in line.split('만 선택')[0]]
    dates = period.action(tc)
    return dict(type='verify_reception_url_filters', description='조회 조건 URL 반영 및 새로고침 복원 검증',
                keyword=next(iter(keywords)) if len(keywords) == 1 else None,
                start=dates['start'], end=dates['end'], statuses=statuses,
                mine=checks.LABEL in steps and '선택' in steps, reload='새로고침' in steps)


def canonical(query):
    result = {key: list(values) for key, values in query.items() if values != ['']}
    if result.get('page') == ['0']: result.pop('page')
    if 'receptionProgressStatusNo' in result:
        result['receptionProgressStatusNo'] = sorted(set(x.strip() for v in result['receptionProgressStatusNo'] for x in v.split(',') if x.strip()))
    return result


def remaining(query):
    return {k: v for k, v in canonical(query).items() if k not in CHANGED}


def status_controls(page):
    combined.close_panel(page)
    trigger = page.locator('button[id^="multi-select-"]').filter(visible=True)
    if trigger.count() != 1: raise ValueError('검사 상태 선택 컨트롤 식별 실패')
    scope_id = trigger.get_attribute('aria-controls') or trigger.get_attribute('id') + '-options'
    if trigger.get_attribute('aria-expanded') != 'true': trigger.click(timeout=3000)
    scope = page.locator('[id="' + scope_id.replace('"', '\\"') + '"]')
    scope.wait_for(state='visible', timeout=3000)
    return trigger, scope_id, scope


def snapshot(page):
    query = parse_qs(urlsplit(page.url).query, keep_blank_values=True)
    mine = checks.control(page).is_checked()
    monitor = checks.control(page, combined.MONITOR).is_checked()
    trigger, scope_id, _ = status_controls(page)
    states = defaults.read_states(page, scope_id, defaults.STATUSES)['states']
    trigger.click(timeout=3000)
    dates = page.locator('input[placeholder="YYYY-MM-DD"]').filter(visible=True)
    if dates.count() != 2: raise ValueError('처방일 입력란 식별 실패')
    info = checks.panel.read(page)
    if not info.get('exam_id'): raise ValueError('검사명 선택값 식별 실패')
    exam = page.locator('[id="' + info['exam_id'].replace('"', '\\"') + '"]').inner_text().strip()
    tabs = page.get_by_role('tablist').filter(has=page.get_by_role('tab', name='외래', exact=True)).filter(visible=True)
    selected = tabs.locator('[role="tab"][aria-selected="true"]')
    if selected.count() != 1: raise ValueError('환자 구분 선택값 식별 실패')
    table = page.evaluate(r'''() => {
      const visible=e=>!!e.getClientRects().length&&getComputedStyle(e).visibility!=='hidden';
      const ts=[...document.querySelectorAll('table')].filter(visible).filter(t=>{
        const hs=[...t.querySelectorAll('th')].map(h=>h.innerText.replace(/\s/g,''));
        return ['환자명','처방일','검사상태'].every(h=>hs.includes(h));});
      if(ts.length!==1)return null;
      const t=ts[0],hs=[...t.querySelectorAll('th')].map(h=>h.innerText.replace(/\s/g,''));
      return {busy:t.matches('[aria-busy="true"]')||!!t.parentElement.querySelector('[role="progressbar"]'),headers:hs,
        rows:[...t.querySelectorAll('tbody tr')].filter(visible).map(r=>[...r.querySelectorAll('td')])
          .filter(cs=>cs.length===hs.length&&cs.every(c=>c.colSpan===1)).map(cs=>cs.map(c=>c.innerText.trim()))};
    }''')
    signatures = []
    valid_rows = True
    raw_rows = table.pop('rows') if table else []
    if table and not table['busy']:
        for row in raw_rows:
            signatures.append(hashlib.sha256(json.dumps(row, ensure_ascii=False).encode()).hexdigest())
            name = row[table['headers'].index('환자명')]
            prescription = row[table['headers'].index('처방일')]
            status = row[table['headers'].index('검사상태')]
            try:
                valid_rows = valid_rows and query.get('keyword', [''])[0] in name and '내 환자' in name
                valid_rows = valid_rows and date.fromisoformat(query['startDate'][0]) <= date.fromisoformat(prescription) <= date.fromisoformat(query['endDate'][0])
                valid_rows = valid_rows and states.get(status) is True
            except (ValueError, KeyError): valid_rows = False
    return dict(query=canonical(query), keyword=find_field(page).input_value(), dates=[dates.nth(i).input_value() for i in range(2)],
                mine=mine, monitor=monitor, states=states, exam=exam, encounter=selected.inner_text().strip(),
                table=table, row_signatures=signatures, valid_rows=valid_rows)


def collect(page, command):
    state = dict(command=command, transitions=[], responses=[])
    handlers = []
    try:
        keyword, start, end, wanted = (command.get(k) for k in ('keyword', 'start', 'end', 'statuses'))
        if not keyword or not start or not end or not wanted or not command.get('mine') or not command.get('reload'):
            return dict(state, error='검색어·기간·선택 상태·내 환자 선택·새로고침 절차를 명시해야 함')
        if date.fromisoformat(start) > date.fromisoformat(end): return dict(state, error='역전된 처방일 기간')
        if not re.search(r'(?:^|/)receptions?/?$', urlsplit(page.url).path): return dict(state, error='검사 접수 경로 진입 근거 없음')
        page.wait_for_load_state('networkidle', timeout=5000)
        state['initial_query'] = canonical(period.baseline_filters(page)['query'])
        state['initial_monitor'] = checks.control(page, combined.MONITOR).is_checked()
        combined.close_panel(page)
        def response(value):
            request = value.request
            if request.resource_type in ('xhr', 'fetch') and re.search(r'(?:^|/)receptions?(?:/(?:list|search))?/?$', urlsplit(request.url).path):
                state['responses'].append(dict(status=value.status, query=canonical(parse_qs(urlsplit(request.url).query, keep_blank_values=True))))
        page.on('response', response); handlers.append(('response', response))
        def wait_value(key, value):
            deadline = time.monotonic() + 5
            while parse_qs(urlsplit(page.url).query).get(key, ['']) != [value] and time.monotonic() < deadline: page.wait_for_timeout(100)
            if parse_qs(urlsplit(page.url).query).get(key, ['']) != [value]: raise ValueError(key + ' URL 반영 실패')
            page.wait_for_load_state('networkidle', timeout=5000)
        field = find_field(page)
        field.fill(keyword, timeout=3000); field.press('Enter', timeout=3000); wait_value('keyword', keyword)
        dates = page.locator('input[placeholder="YYYY-MM-DD"]').filter(visible=True)
        if dates.count() != 2: raise ValueError('처방일 입력란 식별 실패')
        old_end = dates.nth(1).input_value()
        order = [(1, end, 'endDate'), (0, start, 'startDate')] if old_end and old_end < start else [(0, start, 'startDate'), (1, end, 'endDate')]
        for index, value, key in order:
            dates.nth(index).click(timeout=3000); dates.nth(index).fill(value, timeout=3000)
            dates.nth(index).press('Tab', timeout=3000); dates.nth(index).press('Escape', timeout=3000); wait_value(key, value)
        checks.control(page).set_checked(True, timeout=3000); wait_value('myPatientYn', 'Y')
        # 최소 한 상태 유지 제약을 지키기 위해 필요한 상태부터 선택하고 나머지를 해제한다.
        for label in list(wanted) + [s for s in defaults.STATUSES if s not in wanted]:
            trigger, scope_id, scope = status_controls(page)
            control = scope.locator('[role="checkbox"]').filter(has=page.locator('[data-checkbox-label]').filter(has_text=re.compile(r'^\s*' + re.escape(label) + r'\s*$')))
            if control.count() != 1: raise ValueError('검사 상태 라벨 식별 실패: ' + label)
            before = canonical(parse_qs(urlsplit(page.url).query))
            checkbox_controls.CheckboxControl(page, control).set_checked(label in wanted, timeout=3000)
            page.wait_for_load_state('networkidle', timeout=5000)
            state['transitions'].append(dict(label=label, checked=label in wanted, before=before, after=canonical(parse_qs(urlsplit(page.url).query))))
            if trigger.get_attribute('aria-expanded') == 'true': trigger.click(timeout=3000)
        state['before'] = snapshot(page)
        offset = len(state['responses'])
        page.reload(wait_until='domcontentloaded', timeout=15000)
        deadline = time.monotonic() + 5
        while len(state['responses']) == offset and time.monotonic() < deadline: page.wait_for_timeout(100)
        page.wait_for_load_state('networkidle', timeout=5000)
        state['after'] = snapshot(page)
        state['reload_responses'] = state['responses'][offset:]
    except Exception as exc:
        state['error'] = 'URL 필터 복원 근거 수집 실패: ' + str(exc)
    finally:
        for event, handler in handlers: page.remove_listener(event, handler)
        try:
            trigger = page.locator('button[id^="multi-select-"]').filter(visible=True)
            if trigger.count() == 1 and trigger.get_attribute('aria-expanded') == 'true':
                trigger.click(timeout=1000)
        except Exception: pass
        try: combined.close_panel(page)
        except Exception: pass
    return state


def verify(state):
    if not state or state.get('error'): return 'FAIL', '검증 불가: ' + ((state or {}).get('error') or 'URL 필터 실행 근거 없음')
    command = state['command']
    before, after = state.get('before', {}), state.get('after', {})
    expected_states = {s: s in command['statuses'] for s in defaults.STATUSES}
    for label, shot in (('새로고침 전', before), ('새로고침 후', after)):
        if shot.get('keyword') != command['keyword'] or shot.get('dates') != [command['start'], command['end']] or shot.get('mine') is not True or shot.get('states') != expected_states:
            return 'FAIL', label + ' 입력값·내 환자·검사 상태 선택 불일치'
        query = shot.get('query', {})
        expected = dict(keyword=[command['keyword']], startDate=[command['start']], endDate=[command['end']], myPatientYn=['Y'])
        if any(query.get(k) != v for k, v in expected.items()) or len(query.get('receptionProgressStatusNo', [])) != len(command['statuses']):
            return 'FAIL', label + ' URL 조건과 필터 선택 불일치'
        if remaining(query) != remaining(state['initial_query']) or shot.get('monitor') != state['initial_monitor']:
            return 'FAIL', label + ' 변경 대상 외 조회 조건 변경'
        if not shot.get('table') or shot['table']['busy'] or not shot.get('row_signatures') or not shot.get('valid_rows'):
            return 'FAIL', label + ' 목록 로딩·비교 데이터 또는 필터 일치 근거 부족'
    responses = state.get('reload_responses', [])
    if not responses or any(not 200 <= r['status'] < 300 for r in responses): return 'FAIL', '새로고침 후 목록 조회 성공 근거 없음'
    if not any(r['query'] == after['query'] for r in responses): return 'FAIL', '새로고침 후 URL과 조회 요청 조건 불일치'
    for key in ('query', 'keyword', 'dates', 'mine', 'monitor', 'states', 'exam', 'encounter', 'row_signatures'):
        if before.get(key) != after.get(key): return 'FAIL', '새로고침 전후 불일치: ' + key
    return 'PASS', '필터 UI·URL·조회 조건 일치 + 새로고침 후 조건·현재 페이지 접수 내용·순서 유지 확인'
