"""처방일 입력·조회 조건과 페이지별 처방일 범위를 확인한다."""
from datetime import date
import re
import time
from urllib.parse import parse_qs, urlsplit
from verifications import reception_defaults_verification as defaults
from verifications import table_collection, table_pagination


def other_filters(query):
    """기간·페이지를 제외한 조회 조건. 비어 있는 선택 필터는 생략과 동일하다."""
    optional = {'keyword', 'deviceNo', 'encounterClassNo', 'monitoringYn', 'myPatientYn'}
    return {k: v for k, v in query.items() if k not in ('startDate', 'endDate', 'page')
            and not (k in optional and v == [''])}


def baseline_filters(page):
    # 상태 옵션은 목록 응답과 별도로 도착한다. 부분 선택 상태인데 URL 상태 조건이
    # 아직 없다면 기본 상태 ID가 URL에 반영될 때까지 기다린 뒤 기준을 기록한다.
    evidence = defaults.capture(page, {'expected': '대기 진행 종료 취소'})
    states = evidence.get('states', {})
    if evidence.get('error') or any(states.get(s) is None for s in defaults.STATUSES):
        raise ValueError('초기 검사 상태 체크값 수집 실패')
    partial = 0 < sum(states[s] for s in defaults.STATUSES) < len(defaults.STATUSES)
    deadline = time.monotonic() + 5
    previous = None
    stable_since = time.monotonic()
    while True:
        query = parse_qs(urlsplit(page.url).query, keep_blank_values=True)
        current = other_filters(query)
        now = time.monotonic()
        if current != previous:
            previous, stable_since = current, now
        pending = partial and not query.get('receptionProgressStatusNo')
        if not pending and now - stable_since >= 0.5:
            return dict(query=query, states=states)
        if now >= deadline:
            raise ValueError('초기 검사 상태 URL 반영 또는 조회 조건 안정화 확인 실패')
        page.wait_for_timeout(100)


def applies(tc):
    title = re.sub(r'\s+', '', str(tc.get('title') or ''))
    context = re.sub(r'\s+', '', ' '.join(str(tc.get(k) or '') for k in ('sheet_name', 'precondition', 'steps')))
    return '처방일' in title and '기간' in title and '검사접수' in context


def action(tc):
    steps = str(tc.get('steps') or '')
    values = {}
    for key, label in (('start', '시작일'), ('end', '종료일')):
        matches = re.findall(label + r'[^\d\n]{0,35}(\d{4}-\d{2}-\d{2})', steps)
        values[key] = matches[0] if len(set(matches)) == 1 else None
    return dict(type='verify_prescription_period', description='처방일 기간 입력 및 전체 페이지 범위 검증',
                boundaries=bool(re.search(r'같은 날짜|경계|시작일.*종료일.*포함', str(tc.get('expected') or ''))), **values)


def rows(page):
    data = table_collection.read_columns(page, ['처방일'])
    if data.get('error'): return data
    return dict(busy=data['busy'], dates=[row[0] for row in data['rows']], fingerprint=data['fingerprint'])


def collect(page, command):
    state = dict(start=command.get('start'), end=command.get('end'), boundaries=command.get('boundaries', False),
                 responses=[], pages=[], complete=False, request_failed=0)
    handlers = []
    try:
        start, end = state['start'], state['end']
        if not start or not end:
            return dict(state, error='절차에 시작일·종료일을 각각 YYYY-MM-DD로 명시해야 함')
        if date.fromisoformat(start) > date.fromisoformat(end):
            return dict(state, error='시작일이 종료일보다 늦음')
        if not re.search(r'(?:^|/)receptions?/?$', urlsplit(page.url).path):
            return dict(state, error='검사 접수 목록 경로 진입 근거 없음')
        page.wait_for_load_state('networkidle', timeout=5000)
        fields = page.locator('input[placeholder="YYYY-MM-DD"]').filter(visible=True)
        if fields.count() != 2:
            return dict(state, error='표시된 처방일 시작·종료 입력란 두 개를 식별하지 못함')
        initial = baseline_filters(page)
        state['before_states'] = initial['states']
        state['before_filters'] = other_filters(initial['query'])
        def query_of(request):
            parsed = urlsplit(request.url)
            if request.resource_type not in ('xhr', 'fetch') or not re.search(r'(?:^|/)receptions?(?:/(?:list|search))?/?$', parsed.path):
                return None
            query = parse_qs(parsed.query, keep_blank_values=True)
            return query if query.get('startDate') == [start] and query.get('endDate') == [end] else None
        def response(value):
            query = query_of(value.request)
            if query is not None:
                state['responses'].append(dict(status=value.status, page=query.get('page', ['0'])[0]))
        def failed(request):
            if query_of(request) is not None:
                state['request_failed'] += 1
        for event, callback in (('response', response), ('requestfailed', failed)):
            page.on(event, callback)
            handlers.append((event, callback))

        # 기존 종료일보다 새 시작일이 늦으면 종료일부터 바꿔 달력의 min/max 제약을 피한다.
        old_end = fields.nth(1).input_value()
        order = [(1, end, 'endDate'), (0, start, 'startDate')] if old_end and old_end < start else [(0, start, 'startDate'), (1, end, 'endDate')]
        for index, value, key in order:
            field = fields.nth(index)
            field.click(timeout=3000)
            field.fill(value, timeout=3000)
            field.press('Tab', timeout=3000)
            field.press('Escape', timeout=3000)
            deadline = time.monotonic() + 5
            while parse_qs(urlsplit(page.url).query).get(key) != [value] and time.monotonic() < deadline:
                page.wait_for_timeout(100)
            if field.input_value() != value or parse_qs(urlsplit(page.url).query).get(key) != [value]:
                return dict(state, error=key + ' 입력값 또는 URL 반영 실패 (날짜 컴포넌트 확인 필요)')
        state['inputs'] = [fields.nth(i).input_value() for i in range(2)]
        query = parse_qs(urlsplit(page.url).query, keep_blank_values=True)
        if query.get('page', ['0']) != ['0']:
            return dict(state, error='기간 설정 후 첫 페이지로 초기화되지 않아 전체 목록 검증 불가')
        def visit(snapshot, info):
            query = parse_qs(urlsplit(page.url).query, keep_blank_values=True)
            state['after_filters'] = other_filters(query)
            if state['after_filters'] != state['before_filters']:
                changed = [k for k in sorted(state['before_filters'].keys() | state['after_filters'].keys())
                           if state['before_filters'].get(k) != state['after_filters'].get(k)]
                detail = '; '.join(f"{k}: {state['before_filters'].get(k)!r} → {state['after_filters'].get(k)!r}" for k in changed)
                raise ValueError('처방일 외 조회 조건이 변경됨 (' + detail + ')')
            return dict(page=str(info['index']), rows=snapshot)
        state['walk'] = table_pagination.walk(page, read=rows, visit=visit, max_pages=50, start='current')
        state['pages'], state['complete'] = state['walk']['pages'], state['walk']['complete']
        state['after_filters'] = other_filters(parse_qs(urlsplit(page.url).query, keep_blank_values=True))
        if state['walk'].get('error'):
            state['error'] = state['walk']['error']
        elif not state['complete']:
            state['error'] = '50페이지 검증 한도 초과로 전체 목록 확인 불가'
    except Exception as exc:
        state['error'] = '처방일 기간 근거 수집 실패: ' + str(exc)
    finally:
        for event, callback in handlers:
            page.remove_listener(event, callback)
    return state


def verify(state):
    if not state or state.get('error'):
        return 'FAIL', '검증 불가: ' + ((state or {}).get('error') or '처방일 기간 실행 근거 없음')
    if state.get('inputs') != [state['start'], state['end']]:
        return 'FAIL', '처방일 시작일·종료일 입력값 불일치'
    if state.get('request_failed') or any(not 200 <= r['status'] < 300 for r in state['responses']):
        return 'FAIL', '선택 기간의 접수 조회 요청 실패'
    dates = []
    for item in state['pages']:
        if not any(r['page'] == item['page'] for r in state['responses']):
            return 'FAIL', '검증 불가: 기간 조건의 페이지별 조회 응답 없음'
        result = item['rows']
        if not result or result['busy']:
            return 'FAIL', '검증 불가: 처방일 컬럼 또는 로딩 완료 근거 없음'
        for value in result['dates']:
            try:
                actual = date.fromisoformat(value)
            except ValueError:
                return 'FAIL', '검증 불가: 처방일 날짜 해석 실패: ' + value
            if not date.fromisoformat(state['start']) <= actual <= date.fromisoformat(state['end']):
                return 'FAIL', '선택 기간 밖 처방일 노출: ' + value + ' (페이지 ' + item['page'] + ')'
            dates.append(value)
    if not state.get('complete') or not dates:
        return 'FAIL', '검증 불가: 전체 페이지 완료 또는 비교할 접수 데이터 근거 없음'
    if state.get('boundaries') and not {state['start'], state['end']}.issubset(dates):
        return 'FAIL', '검증 불가: 시작일·종료일 경계 날짜의 접수 건 포함 근거 없음'
    return 'PASS', f'처방일 입력·기간 조건 조회 성공 + 전체 {len(state["pages"])}페이지 {len(dates)}건 범위 일치 확인'
