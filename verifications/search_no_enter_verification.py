"""Enter 없는 검색의 관찰 구간을 입력 직전부터 수집한다."""
import re
import time
from urllib.parse import parse_qs, urlsplit


NEGATIVE_ENTER = (r'(?:Enter|엔터)(?:\s*키)?(?:를|을)?\s*(?:없이|누르지|입력하지|전송하지)'
                  r'|(?:Enter|엔터)\s*키(?:나|또는)[^\n]{0,40}수행하지')


def applies(tc):
    text = '\n'.join(str(tc.get(k) or '') for k in ('title', 'steps', 'expected'))
    return '검색' in text and bool(re.search(NEGATIVE_ENTER, text, re.I))


def action(tc):
    steps = str(tc.get('steps') or '')
    values = []
    for line in steps.splitlines():
        if '입력' in line and re.search(r'검색창|검색어|검색\s*입력', line):
            values.extend(re.findall(r'''["'“‘]([^"'”’\n]+)["'”’]''', line))
    duration = re.search(r'(\d+(?:\.\d+)?)\s*초\s*(?:동안\s*)?(?:기다|대기)', steps)
    seconds = float(duration[1]) if duration else None
    context = re.sub(r'\s+', '', '\n'.join(str(tc.get(k) or '') for k in
                                           ('sheet_name', 'precondition', 'steps')))
    return {'type': 'observe_search_no_enter', 'description': 'Enter 없이 검색 입력 및 목록·조회 요청 관찰',
            'value': values[0] if len(values) == 1 else None, 'seconds': seconds,
            'receptions': '검사접수' in context}


def snapshot(page):
    return page.evaluate(r'''() => {
      const visible=e=>!!e.getClientRects().length&&getComputedStyle(e).visibility!=='hidden';
      const norm=s=>(s||'').replace(/\s+/g,' ').trim();
      const tables=[...document.querySelectorAll('table,[role="table"],[role="grid"]')]
        .filter(visible).filter(t=>/환자명/.test(t.innerText));
      if(tables.length!==1) return null;
      const t=tables[0];
      if(t.matches('[aria-busy="true"]')||t.querySelector('[role="progressbar"]')) return null;
      const headers=[...t.querySelectorAll('th,[role="columnheader"]')].map(e=>norm(e.innerText));
      const rows=[...t.querySelectorAll('tbody tr,[role="row"]')].filter(visible)
        .map(r=>[...r.querySelectorAll('td,[role="cell"],[role="gridcell"]')].map(c=>norm(c.innerText)))
        .filter(c=>c.length>=2&&!c.some(s=>/^(조회|검색) 결과가 없습니다\.?$|^데이터가 없습니다\.?$/.test(s)));
      return {headers,rows};
    }''')


def find_field(page):
    fields = page.locator('input:not([readonly]):not([disabled])').all()
    matches = []
    for field in fields:
        if not field.is_visible():
            continue
        label = ' '.join(field.get_attribute(k) or '' for k in ('placeholder', 'aria-label', 'type'))
        if re.search(r'검색|환자명|환자등록번호|search', label, re.I):
            matches.append(field)
    if len(matches) != 1:
        raise ValueError('검색 입력창을 하나로 식별하지 못함')
    return matches[0]


def collect(page, action):
    state = {'keyword': action.get('value'), 'seconds': action.get('seconds'),
             'requests': 0, 'observed': False, 'changed': False}
    keyword, seconds = state['keyword'], state['seconds']
    if not isinstance(keyword, str) or not keyword.strip():
        return dict(state, error='테스트 절차에 실제 검색어를 따옴표로 명시해야 함 (예: 검색창에 \'강의\'를 입력한다)')
    if not isinstance(seconds, (int, float)) or not 1 <= seconds <= 60:
        return dict(state, error='Enter 없이 기다릴 관찰 시간을 1~60초 이내로 명시해야 함')
    handler = None
    try:
        page.wait_for_load_state('networkidle', timeout=5000)
        if action.get('receptions') and not re.search(r'(?:^|/)receptions?(?:/|$)', urlsplit(page.url).path):
            return dict(state, error='검사 접수 목록 경로 진입을 확인하지 못함')
        field = find_field(page)
        state['before_value'] = field.input_value()
        state['before'] = snapshot(page)
        if state['before_value'] != '' or not state['before'] or not state['before']['rows']:
            return dict(state, error='빈 검색창 및 조회 완료된 초기 목록 1건 이상을 확인하지 못함')
        headers = state['before']['headers']
        indices = [i for i, label in enumerate(headers)
                   if re.search(r'환자명|환자등록번호|휴대전화번호', label.replace(' ', ''))]
        if not indices or not any(all(i < len(row) and keyword not in row[i] for i in indices)
                                  for row in state['before']['rows']):
            return dict(state, error='검색어와 일치하지 않는 초기 접수 건의 근거가 부족함')
        def on_request(request):
            if request.resource_type not in ('xhr', 'fetch'):
                return
            url = urlsplit(request.url)
            query = parse_qs(url.query, keep_blank_values=True)
            # 목록 API 또는 명시적인 검색어가 전송된 요청만 센다. heartbeat 등은 제외한다.
            related = bool(re.search(r'(?:^|/)(?:receptions?|patients?)(?:/|$)', url.path, re.I))
            sent = keyword in query.get('keyword', [])
            try:
                payload = request.post_data_json
            except Exception:
                payload = None
            sent = sent or (isinstance(payload, dict) and payload.get('keyword') == keyword)
            if related or sent:
                state['requests'] += 1
        handler = on_request
        page.on('request', handler)
        started = time.monotonic()
        field.fill(keyword)
        state['after_value'] = field.input_value()
        deadline = time.monotonic() + seconds
        while True:
            current = snapshot(page)
            state['after'] = current
            state['changed'] = state['changed'] or current != state['before']
            state['after_value'] = field.input_value()
            if state['after_value'] != keyword:
                state['input_changed'] = True
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            page.wait_for_timeout(min(100, remaining * 1000))
        state.update(observed=True, elapsed=time.monotonic()-started)
    except Exception as exc:
        state['error'] = '관찰 실패: ' + str(exc)
    finally:
        if handler is not None:
            page.remove_listener('request', handler)
    return state


def verify(state):
    if not state or state.get('error'):
        return 'FAIL', '검증 불가: ' + ((state or {}).get('error') or 'Enter 없는 검색 관찰 근거가 없음')
    if not state.get('observed'):
        return 'FAIL', '검증 불가: 지정한 관찰 시간을 완료하지 못함'
    if state.get('requests'):
        return 'FAIL', f"Enter 없이 관찰 중 목록/검색 조회 요청 {state['requests']}건 발생"
    if state.get('input_changed') or state.get('after_value') != state.get('keyword'):
        return 'FAIL', '입력한 검색어가 검색창에 유지되지 않음'
    if state.get('changed'):
        return 'FAIL', 'Enter 없이 관찰 중 목록 데이터·표시 순서 또는 목록 상태가 변경됨'
    return 'PASS', f"{state['seconds']:g}초 동안 검색어 유지 + 목록 데이터·순서 유지 + 관찰한 목록/검색 조회 요청 0건 (Enter 미입력)"
