"""검사명·환자 구분·모니터링 조합의 실제 선택 및 AND 조회를 검증한다."""
import re
import time
from urllib.parse import parse_qs, urlsplit
from verifications import exam_filter_verification as exam
from verifications import reception_filter_panel_verification as panel
from verifications import reception_my_patient_verification as checks
from verifications.prescription_period_verification import baseline_filters
from verifications import table_collection, table_pagination

MONITOR = '모니터링 대상만 보기'
TARGET_KEYS = ('deviceNo', 'encounterClassNo', 'monitoringYn')


def applies(tc):
    title = re.sub(r'\s+', '', str(tc.get('title') or ''))
    context = re.sub(r'\s+', '', ' '.join(str(tc.get(k) or '') for k in ('sheet_name', 'precondition', 'steps')))
    return '필터' in title and '조합' in title and '검사접수' in context


def action(tc):
    steps = str(tc.get('steps') or '')
    names = set()
    for line in steps.splitlines():
        if '드롭다운' in line and '선택' in line:
            names.update(re.findall(r'''["'“‘]([^"'”’\n]+)["'”’]''', line))
    types = set(re.findall(r'\[(외래|입원|응급)\]', steps))
    return dict(type='verify_reception_combined_filters', description='검사명·환자 구분·모니터링 AND 조회 검증',
                exam=next(iter(names)) if len(names) == 1 else None,
                encounter=next(iter(types)) if len(types) == 1 else None,
                monitoring=MONITOR in steps)


def remaining(query):
    return {k: v for k, v in query.items() if k not in (*TARGET_KEYS, 'page') and v != ['']}


def close_panel(page):
    info = panel.read(page)
    if info.get('panel_visible') and info.get('trigger_id'):
        page.locator('[id="' + info['trigger_id'].replace('"', '\\"') + '"]').click(timeout=3000)


def rows(page):
    data = table_collection.read_columns(page, ['검사명', '환자 구분', '모니터링 여부'])
    if data.get('error'): return data
    return dict(busy=data['busy'], values=[[cell.split('\n')[0].strip() for cell in row] for row in data['rows']],
                fingerprint=data['fingerprint'])


def collect(page, command):
    state = dict(exam=command.get('exam'), encounter=command.get('encounter'), stages=[], pages=[], complete=False,
                 responses=[], request_failed=0)
    handlers = []
    try:
        if not state['exam'] or not state['encounter'] or not command.get('monitoring'):
            return dict(state, error='검사명 드롭다운 선택값·환자 구분 탭·모니터링 선택 절차를 각각 명시해야 함')
        if not re.search(r'(?:^|/)receptions?/?$', urlsplit(page.url).path):
            return dict(state, error='검사 접수 목록 경로 진입 근거 없음')
        page.wait_for_load_state('networkidle', timeout=5000)
        initial = baseline_filters(page)['query']
        state['before_filters'] = remaining(initial)
        info = panel.read(page)
        if info.get('error') or not info.get('exam_id'):
            return dict(state, error='검사명 선택 컨트롤 식별 실패')
        trigger = page.locator('[id="' + info['exam_id'].replace('"', '\\"') + '"]')
        tabs = page.get_by_role('tablist').filter(has=page.get_by_role('tab', name='외래', exact=True)).filter(visible=True)
        if tabs.count() != 1:
            return dict(state, error='환자 구분 탭 그룹 식별 실패')
        if trigger.inner_text().strip() != '전체 검사' or tabs.get_by_role('tab', name='전체', exact=True).get_attribute('aria-selected') != 'true':
            return dict(state, error='전체 검사·전체 환자 구분 초기 조건 불충족')
        if any(initial.get(k, [''])[0] for k in ('keyword', 'startDate', 'endDate')):
            return dict(state, error='검색어·처방일이 비어 있어야 하는 초기 조건 불충족')
        if checks.control(page, MONITOR).is_checked():
            return dict(state, error='모니터링 필터가 처음부터 선택되어 있음')
        state['before_my_patient'] = checks.control(page).is_checked()
        close_panel(page)
        def related(request):
            return request.resource_type in ('xhr', 'fetch') and bool(re.search(
                r'(?:^|/)receptions?(?:/(?:list|search))?/?$', urlsplit(request.url).path))
        def response(value):
            if related(value.request):
                state['responses'].append(dict(status=value.status, query=parse_qs(urlsplit(value.request.url).query, keep_blank_values=True)))
        def failed(request):
            if related(request): state['request_failed'] += 1
        for event, handler in (('response', response), ('requestfailed', failed)):
            page.on(event, handler); handlers.append((event, handler))
        def wait_query(wanted, offset):
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline:
                query = parse_qs(urlsplit(page.url).query, keep_blank_values=True)
                responses = [r for r in state['responses'][offset:] if all(r['query'].get(k) == v for k, v in wanted.items())]
                if responses and all(query.get(k) == v for k, v in wanted.items()): break
                page.wait_for_timeout(100)
            page.wait_for_load_state('networkidle', timeout=5000)
            query = parse_qs(urlsplit(page.url).query, keep_blank_values=True)
            responses = [r for r in state['responses'][offset:] if all(r['query'].get(k) == v for k, v in wanted.items())]
            if not responses or any(not 200 <= r['status'] < 300 for r in responses):
                raise ValueError('선택 조건의 조회 성공 응답 없음: ' + ', '.join(wanted))
            if not all(query.get(k) == v for k, v in wanted.items()):
                raise ValueError('선택 조건 URL 반영 불일치')
            if remaining(query) != state['before_filters'] or any(remaining(r['query']) != state['before_filters'] for r in responses):
                raise ValueError('조합 대상 외 기존 조회 조건 변경')
            state['stages'].append(dict(wanted=wanted, query=query, statuses=[r['status'] for r in responses]))
        trigger.click(timeout=3000)
        opts = exam.options(page)
        deadline = time.monotonic() + 3
        while opts is None and time.monotonic() < deadline:
            page.wait_for_timeout(100)
            opts = exam.options(page)
        if opts is None:
            return dict(state, error='검사명 옵션 목록 식별 실패')
        matches = [item for item in opts['items'] if item['label'] == state['exam']]
        if len(matches) != 1 or not matches[0]['value']:
            return dict(state, error='검사명 옵션을 하나로 식별하지 못함')
        state['device_no'] = matches[0]['value']
        wanted = dict(deviceNo=[state['device_no']])
        offset = len(state['responses'])
        page.locator('ul.select-dropdown').nth(opts['index']).locator('li').filter(
            has_text=re.compile(r'^\s*' + re.escape(state['exam']) + r'\s*$')).click(timeout=3000)
        wait_query(wanted, offset)
        offset = len(state['responses'])
        tab = tabs.get_by_role('tab', name=state['encounter'], exact=True)
        tab.click(timeout=3000)
        deadline = time.monotonic() + 5
        while not parse_qs(urlsplit(page.url).query).get('encounterClassNo') and time.monotonic() < deadline:
            page.wait_for_timeout(100)
        encounter = parse_qs(urlsplit(page.url).query).get('encounterClassNo')
        if not encounter or encounter == ['0'] or tab.get_attribute('aria-selected') != 'true':
            return dict(state, error='환자 구분 탭 선택 또는 조건 반영 실패')
        wanted = dict(wanted, encounterClassNo=encounter)
        wait_query(wanted, offset)
        offset = len(state['responses'])
        checks.control(page, MONITOR).set_checked(True, timeout=3000)
        wanted = dict(wanted, monitoringYn=['Y'])
        wait_query(wanted, offset)
        state['selected'] = dict(exam=trigger.inner_text().strip(), encounter=tab.get_attribute('aria-selected') == 'true',
                                  monitoring=checks.control(page, MONITOR).is_checked(), my_patient=checks.control(page).is_checked())
        close_panel(page)
        if parse_qs(urlsplit(page.url).query).get('page', ['0']) != ['0']:
            return dict(state, error='조합 적용 후 첫 페이지 초기화 근거 없음')
        def visit(snapshot, info):
            query = parse_qs(urlsplit(page.url).query, keep_blank_values=True)
            if not all(query.get(k) == v for k, v in wanted.items()) or remaining(query) != state['before_filters']:
                raise ValueError('페이지 이동 후 조합 필터 또는 기존 조건 변경')
            return dict(page=str(info['index']), rows=snapshot)
        state['walk'] = table_pagination.walk(page, read=rows, visit=visit, max_pages=50, start='current')
        state['pages'], state['complete'] = state['walk']['pages'], state['walk']['complete']
        if state['walk'].get('error'): state['error'] = state['walk']['error']
        elif not state['complete']: state['error'] = '50페이지 한도 초과로 전체 목록 확인 불가'
    except Exception as exc:
        state['error'] = '필터 조합 근거 수집 실패: ' + str(exc)
    finally:
        for event, handler in handlers: page.remove_listener(event, handler)
        try: close_panel(page)
        except Exception: pass
    return state


def verify(state):
    if not state or state.get('error'):
        return 'FAIL', '검증 불가: ' + ((state or {}).get('error') or '필터 조합 실행 근거 없음')
    selected = state.get('selected', {})
    if selected.get('exam') != state['exam'] or not selected.get('encounter') or not selected.get('monitoring'):
        return 'FAIL', '세 필터의 최종 선택 상태 불일치'
    if selected.get('my_patient') != state.get('before_my_patient'):
        return 'FAIL', '내 환자 체크 상태가 변경됨'
    if state.get('request_failed') or len(state.get('stages', [])) < 3 or not state.get('complete'):
        return 'FAIL', '검증 불가: 단계별 조회 성공 또는 전체 페이지 완료 근거 부족'
    count = 0
    for item in state.get('pages', []):
        result = item.get('rows')
        if not result or result['busy']:
            return 'FAIL', '검증 불가: 조합 비교 열 또는 로딩 완료 근거 없음'
        for values in result['values']:
            if values != [state['exam'], state['encounter'], '대상']:
                return 'FAIL', 'AND 조건 불일치: 페이지 ' + item['page'] + ' 검사명·환자 구분·모니터링=' + repr(values)
            count += 1
    if not count: return 'FAIL', '검증 불가: 세 조건을 만족하는 비교 데이터가 0건임'
    return 'PASS', f"검사명·환자 구분·모니터링 동시 조건 조회 성공 + 전체 {len(state['pages'])}페이지 {count}건 AND 일치 + 기존 필터 유지 확인"
