"""TC 문구 → 명시적 수집 계획 → 공통 실행기 → 규칙 판정 연결."""
import re
from verifications import column_rules, table_collection, table_pagination


def profile_name(tc):
    text = str(tc.get('title') or '') + '\n' + str(tc.get('expected') or '')
    if re.search(r'환자\s*구분', text) and '표시' in text and all(value in text for value in column_rules.PATIENT_TYPES):
        return 'patient_type'
    return 'mobile_or_hyphen'


def applies(tc):
    title = str(tc.get('title') or '')
    expected = str(tc.get('expected') or '')
    text = title + '\n' + expected
    # 검색값 비교 TC와 구분한다. TC 번호에는 의존하지 않는다.
    return bool(re.search(r'수집|사례', str(tc.get('steps') or '')) and (profile_name(tc) == 'patient_type' or
                (re.search(r'휴대전화번호|휴대폰번호', text) and '표시' in text
                and re.search(r'하이픈|[\'"‘’“”]-[\'"‘’“”]', text)
                )))


def compile_plan(tc):
    name = profile_name(tc)
    profile = column_rules.PROFILES[name]
    steps = str(tc.get('steps') or '')
    expected = str(tc.get('expected') or '')
    text = '\n'.join(str(tc.get(k) or '') for k in ('precondition', 'steps', 'expected'))
    context = re.sub(r'\s+', '', str(tc.get('sheet_name') or tc.get('sheet') or '') + text)
    maxima = {int(n) for n in re.findall(r'최대\s*(\d+)\s*페이지', text)}
    errors = []
    if len(maxima) != 1: errors.append('최대 확인 페이지 수를 하나로 명시해야 함')
    maximum = next(iter(maxima)) if len(maxima) == 1 else None
    if maximum is not None and not 1 <= maximum <= 50: errors.append('지원하는 최대 확인 범위는 1~50페이지임')
    if not re.search(r'첫\s*페이지|1\s*페이지(?:부터|로)', steps): errors.append('첫 페이지부터 확인하는 절차가 필요함')
    if not re.search(r'(?:두\s*사례|세\s*사례|모두\s*수집)[^.\n]*종료', steps): errors.append('필요 사례 수집 후 종료 조건을 명시해야 함')
    if not re.search(r'(?:빈칸|null|undefined)[^.\n]*FAIL', expected, re.I):
        errors.append('허용하지 않은 표시값과 미수집 시 FAIL 기준을 명시해야 함')
    if (not re.search(r'(?:수집되지|미수집|수집[^.\n]*못)[^.\n]*FAIL', expected, re.I)
            or re.search(r'(?:수집되지|미수집|수집[^.\n]*못)[^.\n]*PASS', expected, re.I)):
        errors.append('범위 안에서 사례를 수집하지 못한 경우의 판정 기준을 명시해야 함')
    screen = 'receptions' if '검사접수' in context else 'patients' if '환자관리' in context else None
    if screen is None: errors.append('검증 대상 목록 화면을 명시해야 함')
    if name == 'patient_type' and not re.search(r'환자\s*구분[^.\n]*\[전체\][^.\n]*선택', steps):
        errors.append('환자 구분 [전체] 탭 선택 절차가 필요함')
    return dict(version=1, strategy='collect_column_examples', screen=screen,
                columns=list(profile['columns']), aliases={key: list(values) for key, values in profile['aliases'].items()},
                traversal=dict(start='first', max_pages=maximum, stop_when='required_cases_or_invalid'),
                rule=dict(profile=name, required_cases=list(profile['cases']), invalid='fail', missing='fail'),
                errors=errors)


def action(tc):
    return dict(type='execute_collection_plan', description='문구에서 추출한 목록 열·페이지 범위·사례 수집 계획 실행', plan=compile_plan(tc))


def collect(page, plan):
    state = dict(plan=plan)
    try:
        if plan.get('errors'): raise ValueError('; '.join(plan['errors']))
        profile = column_rules.PROFILES.get(plan.get('rule', {}).get('profile'))
        if (not profile or plan.get('version') != 1 or plan.get('strategy') != 'collect_column_examples'
                or plan.get('columns') != profile['columns'] or plan.get('rule', {}).get('profile') not in column_rules.PROFILES
                or plan.get('aliases') != profile['aliases']
                or plan.get('rule', {}).get('required_cases') != list(profile['cases'])
                or plan.get('rule', {}).get('invalid') != 'fail' or plan.get('rule', {}).get('missing') != 'fail'
                or plan.get('traversal', {}).get('start') != 'first'
                or plan.get('traversal', {}).get('stop_when') != 'required_cases_or_invalid'):
            raise ValueError('지원하지 않는 수집 계획 또는 판정 규칙')
        from urllib.parse import urlsplit
        if plan.get('screen') not in ('receptions', 'patients') or urlsplit(page.url).path.rstrip('/') != '/' + plan['screen']:
            raise ValueError('수집 계획의 목록 화면과 실제 경로 불일치')
        profile = column_rules.PROFILES[plan['rule']['profile']]
        if plan['rule']['profile'] == 'patient_type':
            state['preparation'] = select_all_patient_types(page, plan)
        state['walk'] = table_pagination.walk(page,
            read=lambda current: table_collection.read_columns(current, plan['columns'], aliases=plan.get('aliases')),
            visit=profile['visit'], stop=profile['stop'], start=plan['traversal']['start'], max_pages=plan['traversal']['max_pages'])
        if plan['rule']['profile'] == 'patient_type':
            final_filters = table_pagination.filters(table_pagination.query(page))
            if final_filters != state['preparation']['filters']:
                raise ValueError('수집 전후 조회 조건이 변경됨')
            if patient_type_all_tab(page).get_attribute('aria-selected') != 'true':
                raise ValueError('수집 후 환자 구분 전체 탭 선택 상태 불일치')
    except Exception as exc:
        state['error'] = str(exc)
    return state


def verify(state):
    if not state or state.get('error'):
        return 'FAIL', '검증 불가: ' + ((state or {}).get('error') or '목록 수집 계획 실행 근거 없음')
    walk = state.get('walk') or {}
    pages = walk.get('pages', [])
    scope = ', '.join(str(p['page']) for p in pages) or '없음'
    if walk.get('error'): return 'FAIL', f"검증 불가: {walk['error']} (확인 페이지: {scope})"
    maximum = state.get('plan', {}).get('traversal', {}).get('max_pages')
    navigation = walk.get('navigation', [])
    if (not isinstance(maximum, int) or not pages or len(pages) > maximum or len(navigation) != len(pages)
            or any(p['page'] != i + 1 or navigation[i].get('index') != i
                   or navigation[i].get('proof') not in ('initial_list_stable', 'response_finished', 'render_changed')
                   for i, p in enumerate(pages))):
        return 'FAIL', '검증 불가: 수집 범위 또는 페이지 이동·조회 완료 근거 불일치'
    profile = column_rules.PROFILES.get(state.get('plan', {}).get('rule', {}).get('profile'))
    if not profile: return 'FAIL', '검증 불가: 지원하지 않는 열 규칙'
    if state['plan']['rule']['profile'] == 'patient_type' and not state.get('preparation', {}).get('selected'):
        return 'FAIL', '검증 불가: 환자 구분 전체 탭 선택 근거 없음'
    for page in pages:
        if page['invalid']:
            cell = page['invalid'][0]
            return 'FAIL', f"{profile['columns'][0]} 표시 불일치: {page['page']}페이지 {cell['row']}행 {cell['cause']} (확인 페이지: {scope})"
    missing = [profile['labels'][case] for case in profile['cases'] if not any(p['counts'][case] for p in pages)]
    if missing:
        return 'FAIL', '검증 불가: 미수집 사례: ' + ', '.join(missing) + f' (확인 페이지: {scope}, 종료: {walk.get("termination")})'
    return 'PASS', f"{profile['success']} + 확인한 셀의 허용 형식 일치 (확인 페이지: {scope})"


def select_all_patient_types(page, plan):
    """수집 전에 실제 환자 구분 탭만 선택하고 다른 조회 조건을 보존한다."""
    def read(current):
        return table_collection.read_columns(current, plan['columns'], aliases=plan['aliases'])
    def remaining(query):
        return {key: value for key, value in table_pagination.filters(query).items() if key != 'encounterClassNo'}
    with table_pagination.PageNavigator(page) as pager:
        before, _ = pager.ready(read)
        original = remaining(table_pagination.query(page))
        target = patient_type_all_tab(page)
        changed = target.get_attribute('aria-selected') != 'true'
        if changed:
            offset = len(pager.requests)
            pager.baseline = None
            target.click(timeout=3000)
            _, proof = pager.ready(read, expected=0, previous=before, offset=offset)
            actual = table_pagination.filters(table_pagination.query(page))
            if remaining(table_pagination.query(page)) != original:
                raise ValueError('환자 구분 외 기존 조회 조건이 변경됨')
            observed = list(pager.requests.values())[offset:]
            if observed and not any(
                    item['done'] and item['status'] is not None and 200 <= item['status'] < 300
                    and item['page'] == ['0']
                    and item['query'].get('encounterClassNo', ['']) in ([''], ['0'])
                    and all(table_pagination.filters(item['query']).get(key) == value for key, value in actual.items())
                    for item in observed):
                raise ValueError('환자 구분 전체 조건의 조회 성공 응답 없음')
        else:
            proof = dict(proof='already_selected')
        query = table_pagination.query(page)
        if target.get_attribute('aria-selected') != 'true' or query.get('encounterClassNo', ['']) not in ([''], ['0']):
            raise ValueError('환자 구분 전체 선택 또는 URL 조건 반영 불일치')
        if remaining(query) != original: raise ValueError('환자 구분 외 기존 조회 조건이 변경됨')
        return dict(selected=True, changed=changed, proof=proof['proof'], filters_preserved=True, filters=table_pagination.filters(query))


def patient_type_all_tab(page):
    tabs = page.get_by_role('tablist').filter(has=page.get_by_role('tab', name='외래', exact=True)).filter(visible=True)
    if tabs.count() != 1: raise ValueError('환자 구분 탭 그룹 식별 실패')
    target = tabs.get_by_role('tab', name='전체', exact=True)
    if target.count() != 1: raise ValueError('환자 구분 전체 탭 식별 실패')
    return target
