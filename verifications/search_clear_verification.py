"""검색창의 실제 지우기 버튼과 검색 조건 해제를 검증한다."""
import re
from urllib.parse import parse_qs, urlsplit


def applies(tc):
    steps = str(tc.get('steps') or '')
    expected = str(tc.get('expected') or '')
    return (bool(re.search(r'검색|환자명', steps)) and bool(re.search(r'지우|지워|\[X\]|\(X\)', steps, re.I))
            and bool(re.search(r'검색어|검색\s*조건', expected))
            and bool(re.search(r'해제|전체\s*목록|조건\s*없는', expected)))


def input_only(tc):
    """입력 지우기 버튼의 값 삭제만 요구하는 TC. 비고의 미확정 조회는 제외한다."""
    steps = str(tc.get('steps') or '')
    title = str(tc.get('title') or '')
    expected = str(tc.get('expected') or '')
    return (not applies(tc) and bool(re.search(r'검색창|검색\s*입력', steps + title))
            and bool(re.search(r'입력\s*지우기|\[X\]|\(X\)', steps + title, re.I))
            and bool(re.search(r'입력|내용|검색어', expected))
            and bool(re.search(r'삭제|비어|빈\s*(?:값|문자열)|지워|지우', expected))
            and not re.search(r'재조회|목록|필터|조회', expected))


def verify_input_only(evidence):
    if not evidence or not evidence.get('before_value'):
        return '확인 필요', '입력 지우기 버튼 클릭 전 검색어와 버튼 클릭 근거가 없음'
    if not isinstance(evidence.get('after_value'), str):
        return '확인 필요', '입력 지우기 버튼 클릭 후 검색창 값을 수집하지 못함'
    if evidence['after_value'] != '' or evidence.get('final_value', '') != '':
        return 'FAIL', '입력 지우기 버튼 클릭 후 검색창에 입력값이 남아 있음'
    return 'PASS', '검색창에 연결된 입력 지우기 버튼 클릭 전 값 존재 및 클릭 후 빈 문자열 확인 (재조회 여부는 검증 대상 아님)'


def filters(page):
    """검색어 외 URL 조건 및 표시된 선택 컨트롤을 읽는다."""
    url = urlsplit(page.url)
    query = parse_qs(url.query, keep_blank_values=True)
    query.pop('keyword', None)
    controls = page.evaluate(r'''() => [...document.querySelectorAll(
      'input[type="checkbox"],input[type="radio"],select,[role="checkbox"],[role="combobox"]')]
      .filter(e=>e.getClientRects().length&&getComputedStyle(e).visibility!=='hidden')
      .map(e=>({id:e.id,name:e.getAttribute('name'),role:e.getAttribute('role'),
        checked:e.matches('input')?e.checked:e.getAttribute('aria-checked'),
        value:e.tagName==='SELECT'?e.value:(e.getAttribute('role')==='combobox'?e.innerText.trim():null)}))''')
    return {'path': url.path, 'query': query, 'controls': controls}


def rows(page):
    return page.evaluate(r'''() => {
      const visible = e => e.getClientRects().length && getComputedStyle(e).visibility !== 'hidden';
      const tables = [...document.querySelectorAll('table, [role="table"], [role="grid"]')]
        .filter(visible).filter(t => /환자명/.test(t.innerText));
      if(tables.length!==1) return null;
      return [...tables[0].querySelectorAll('tbody tr, [role="row"]')].filter(visible)
        .filter(r => r.querySelectorAll('td, [role="cell"], [role="gridcell"]').length>=2)
        .map(r => r.innerText.trim());
    }''')


def click_clear(page, field):
    index = field.evaluate(r'''input => {
      const visible = e => e.getClientRects().length && getComputedStyle(e).visibility !== 'hidden';
      const all = [...document.querySelectorAll('button, [role="button"]')];
      let p=input.parentElement;
      for(let level=0; p && level<4; level++, p=p.parentElement) {
        if([...p.querySelectorAll('input,textarea')].filter(visible).length!==1) break;
        const matches = [...p.querySelectorAll('button, [role="button"]')].filter(visible).filter(b => {
          const text=b.innerText.trim();
          const name=[b.getAttribute('aria-label'),b.getAttribute('title'),b.getAttribute('data-testid')].filter(Boolean).join(' ');
          return /^(x|×|✕|✖)$/i.test(text) || /지우|초기화|삭제|clear|reset/i.test(name) ||
            !!b.querySelector('svg.lucide-x, svg[data-icon="x"], svg[class*="close"], svg[class*="clear"]');
        });
        if(matches.length===1) return all.indexOf(matches[0]);
        if(matches.length>1) break;
      }
      return -1;
    }''')
    if index < 0:
        raise ValueError('검색 입력창에 연결된 지우기(X) 버튼을 하나로 식별하지 못함')
    before = field.input_value()
    page.locator('button, [role="button"]').nth(index).click(timeout=5000)
    return {'before_value': before, 'after_value': field.input_value()}


def empty_query(response, keyword=''):
    try:
        if not 200 <= response.status < 300 or response.request.resource_type not in ('xhr', 'fetch'):
            return False
        url=urlsplit(response.url)
        if not re.search(r'(?:^|/)(?:patients?|receptions?)(?:/(?:list|search))?/?$', url.path, re.I):
            return False
        params=parse_qs(url.query, keep_blank_values=True)
        if 'keyword' in params:
            return params['keyword']==[keyword]
        # 검색어 생략을 사용하는 GET 목록 조회도 검색 조건 해제로 취급한다.
        if response.request.method=='GET':
            return keyword == ''
        payload=response.request.post_data_json
        return isinstance(payload, dict) and payload.get('keyword') == keyword
    except Exception:
        return False


def capture_submit(page, field, evidence, submit, keyword=''):
    state = dict(evidence or {}, loaded=False)
    def on_response(response):
        if empty_query(response, keyword):
            state['loaded'] = True
    page.on('response', on_response)
    try:
        submit()
        state['final_value'] = field.input_value()
        state['after_rows'] = rows(page)
        state['after_filters'] = filters(page)
        return state
    finally:
        page.remove_listener('response', on_response)


def verify(evidence):
    if not evidence or not evidence.get('before_value'):
        return '확인 필요', '검색어 지우기 전 입력 근거가 없음'
    if evidence.get('baseline_error'):
        return '확인 필요', evidence['baseline_error']
    if evidence.get('manual_clear') and not evidence.get('searched_loaded'):
        return '확인 필요', '검색어가 입력된 상태의 목록 조회 성공 근거가 없음'
    if evidence.get('after_value') != '' or evidence.get('final_value') != '':
        return '확인 필요', '검색 입력창의 값이 비워진 상태를 확인하지 못함'
    if not evidence.get('loaded') or evidence.get('after_rows') is None:
        return '확인 필요', '검색 조건 없는 환자 목록 조회 완료 근거가 부족함'
    baseline = evidence.get('baseline_rows')
    if baseline is None or evidence['after_rows'] != baseline:
        return '확인 필요', '검색 조건 해제는 확인했으나 검색 전 목록으로 복귀한 근거가 부족함'
    if 'baseline_filters' in evidence and evidence.get('after_filters') != evidence['baseline_filters']:
        return 'FAIL', '검색어 외 필터 조건이 초기 상태와 달라짐'
    return 'PASS', '검색 입력값 비움 + 검색어 없는 조회 성공 + 검색 전 목록 복귀 및 수집한 필터 조건 유지 확인'
