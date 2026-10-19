"""검사 접수의 추가 필터 패널에서 내 환자 선택·해제를 단계별 검증한다."""
import re
import time
from urllib.parse import parse_qs, urlsplit
import checkbox_controls
from verifications import reception_filter_panel_verification as panel

LABEL = '내 환자만 보기'


def applies(tc):
    title = re.sub(r'\s+', '', str(tc.get('title') or ''))
    context = re.sub(r'\s+', '', ' '.join(str(tc.get(k) or '') for k in ('sheet_name', 'precondition', 'steps')))
    return '내환자만보기' in title and '검사접수' in context


def ensure_panel(page):
    info = panel.read(page)
    if info.get('error'):
        raise ValueError(info['error'])
    if not info.get('panel_visible'):
        page.locator('[id="' + info['trigger_id'].replace('"', '\\"') + '"]').click(timeout=3000)
    scopes = page.locator('[data-filter-tooltip-panel],.filter-tooltip-panel').filter(visible=True)
    scopes.wait_for(state='visible', timeout=3000)
    if scopes.count() != 1:
        raise ValueError('추가 필터 패널을 하나로 식별하지 못함')
    return scopes


def control(page, label=LABEL):
    scope = ensure_panel(page)
    # 체크 아이콘의 alt 텍스트와 무관하게 패널 안의 실제 라벨로 찾는다.
    roles = scope.locator('[role="checkbox"]').filter(
        has=page.locator('[data-checkbox-label]').filter(has_text=re.compile(r'^\s*' + re.escape(label) + r'\s*$')))
    if roles.count() == 1:
        return checkbox_controls.CheckboxControl(page, roles)
    native = scope.get_by_label(label, exact=True)
    if native.count() == 1:
        return checkbox_controls.CheckboxControl(page, native, scope.get_by_text(label, exact=True))
    raise ValueError('패널 내 체크박스를 하나로 식별하지 못함: ' + label)


def rows(page):
    return page.evaluate(r'''() => {
      const visible=e=>!!e.getClientRects().length&&getComputedStyle(e).visibility!=='hidden';
      const tables=[...document.querySelectorAll('table')].filter(visible).filter(t=>{
        const labels=[...t.querySelectorAll('th')].map(h=>h.innerText.replace(/\s/g,''));
        return labels.includes('환자명')&&labels.includes('처방일');});
      if(tables.length!==1)return null;
      const t=tables[0],headers=[...t.querySelectorAll('th')];
      const index=headers.findIndex(h=>h.innerText.replace(/\s/g,'')==='환자명');
      const cs=[...t.querySelectorAll('tbody tr')].filter(visible).map(r=>[...r.querySelectorAll('td')])
        .filter(c=>c.length===headers.length&&c.every(e=>e.colSpan===1));
      return {count:cs.length,mine:cs.filter(c=>/내\s*환자/.test(c[index].innerText)).length,
        busy:t.matches('[aria-busy="true"]')||!!t.parentElement.querySelector('[role="progressbar"]')};
    }''')


def other_filters(query):
    return {k: v for k, v in query.items() if k not in ('myPatientYn', 'page') and v != ['']}


def collect(page):
    evidence = dict(stages=[], responses=[], request_failed=0)
    handlers = []
    try:
        if not re.search(r'(?:^|/)receptions?/?$', urlsplit(page.url).path):
            return dict(evidence, error='검사 접수 목록 경로 진입 근거 없음')
        page.wait_for_load_state('networkidle', timeout=5000)
        evidence['initial_checked'] = control(page).is_checked()
        # 처음부터 선택된 계정도 실제 선택 동작을 검증하도록 준비 해제를 기록한다.
        if evidence['initial_checked']:
            control(page).set_checked(False, timeout=3000)
            deadline = time.monotonic() + 5
            while parse_qs(urlsplit(page.url).query).get('myPatientYn') != ['N'] and time.monotonic() < deadline:
                page.wait_for_timeout(100)
            if control(page).is_checked() or parse_qs(urlsplit(page.url).query).get('myPatientYn') != ['N']:
                return dict(evidence, error='초기 내 환자 선택의 준비 해제 실패')
            page.wait_for_load_state('networkidle', timeout=5000)
            evidence['prepared_unchecked'] = True
        baseline = parse_qs(urlsplit(page.url).query, keep_blank_values=True)
        evidence['before_filters'] = other_filters(baseline)
        def response(value):
            request = value.request
            parsed = urlsplit(request.url)
            if request.resource_type in ('xhr', 'fetch') and re.search(r'(?:^|/)receptions?(?:/(?:list|search))?/?$', parsed.path):
                query = parse_qs(parsed.query)
                if query.get('myPatientYn') in (['Y'], ['N']):
                    evidence['responses'].append(dict(value=query['myPatientYn'][0], status=value.status,
                                                      filters=other_filters(query)))
        def failed(request):
            if request.resource_type in ('xhr', 'fetch') and re.search(r'(?:^|/)receptions?(?:/(?:list|search))?/?$', urlsplit(request.url).path):
                evidence['request_failed'] += 1
        for event, handler in (('response', response), ('requestfailed', failed)):
            page.on(event, handler)
            handlers.append((event, handler))
        for checked, value in ((True, 'Y'), (False, 'N')):
            offset = len(evidence['responses'])
            control(page).set_checked(checked, timeout=3000)
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline:
                responses = [r for r in evidence['responses'][offset:] if r['value'] == value]
                if responses and parse_qs(urlsplit(page.url).query).get('myPatientYn') == [value]:
                    break
                page.wait_for_timeout(100)
            page.wait_for_load_state('networkidle', timeout=5000)
            query = parse_qs(urlsplit(page.url).query, keep_blank_values=True)
            evidence['stages'].append(dict(checked=control(page).is_checked(), value=value,
                url_value=query.get('myPatientYn'), filters=other_filters(query), rows=rows(page),
                responses=[r for r in evidence['responses'][offset:] if r['value'] == value]))
    except Exception as exc:
        evidence['error'] = '검사 접수 내 환자 필터 근거 수집 실패: ' + str(exc)
    finally:
        for event, handler in handlers:
            page.remove_listener(event, handler)
        try:
            info = panel.read(page)
            if info.get('panel_visible') and info.get('trigger_id'):
                page.locator('[id="' + info['trigger_id'].replace('"', '\\"') + '"]').click(timeout=3000)
        except Exception:
            pass
    return evidence


def verify(evidence):
    if not evidence or evidence.get('error'):
        return 'FAIL', '검증 불가: ' + ((evidence or {}).get('error') or '검사 접수 내 환자 필터 실행 근거 없음')
    if evidence.get('request_failed'):
        return 'FAIL', '내 환자 선택·해제 조회 요청 실패'
    if len(evidence.get('stages', [])) != 2:
        return 'FAIL', '검증 불가: 내 환자 선택·해제 단계별 근거 없음'
    for stage, checked, value in zip(evidence['stages'], (True, False), ('Y', 'N')):
        label = '선택' if checked else '해제'
        if stage.get('checked') is not checked or stage.get('url_value') != [value]:
            return 'FAIL', '내 환자 ' + label + ' 체크값 또는 URL 조건 불일치'
        if stage.get('filters') != evidence['before_filters']:
            return 'FAIL', '내 환자 ' + label + ' 시 다른 조회 조건이 변경됨'
        responses = stage.get('responses', [])
        if not responses:
            return 'FAIL', '검증 불가: 내 환자 ' + label + ' 조건의 조회 응답 없음'
        if any(not 200 <= r['status'] < 300 for r in responses):
            return 'FAIL', '내 환자 ' + label + ' 목록 조회 실패'
        if any(r['filters'] != evidence['before_filters'] for r in responses):
            return 'FAIL', '내 환자 ' + label + ' 조회 요청의 나머지 필터 불일치'
        result = stage.get('rows')
        if not result or result['busy'] or not result['count']:
            return 'FAIL', '검증 불가: 내 환자 ' + label + ' 목록의 비교 데이터 또는 로딩 완료 근거 없음'
        if checked and result['mine'] != result['count']:
            return 'FAIL', '내 환자 선택 목록에 내 환자 표시가 없는 접수 건이 노출됨'
        if not checked and result['mine'] == result['count']:
            return 'FAIL', '검증 불가: 해제 후 현재 페이지에 내 환자가 아닌 접수 건이 없어 범위 확대 확인 불가'
    return 'PASS', '필터 패널 내 내 환자 선택·해제 + Y/N 조회 성공 + 선택 시 내 환자만 표시 + 해제 시 다른 환자 표시 확인 (현재 페이지 기준)'
