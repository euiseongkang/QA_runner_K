"""검색창의 실제 지우기 버튼과 검색 조건 해제를 검증한다."""
import re
from urllib.parse import parse_qs, urlsplit


def applies(tc):
    steps = str(tc.get('steps') or '')
    expected = str(tc.get('expected') or '')
    return (bool(re.search(r'검색|환자명', steps)) and bool(re.search(r'지우|\[X\]|\(X\)', steps, re.I))
            and bool(re.search(r'검색어|검색\s*조건', expected))
            and bool(re.search(r'해제|전체\s*목록|조건\s*없는', expected)))


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


def empty_query(response):
    try:
        if not 200 <= response.status < 300 or response.request.resource_type not in ('xhr', 'fetch'):
            return False
        url=urlsplit(response.url)
        if not re.search(r'(?:^|/)patients?(?:/(?:list|search))?/?$', url.path, re.I):
            return False
        params=parse_qs(url.query, keep_blank_values=True)
        if 'keyword' in params:
            return params['keyword']==['']
        # 검색어 생략을 사용하는 GET 목록 조회도 검색 조건 해제로 취급한다.
        if response.request.method=='GET':
            return True
        payload=response.request.post_data_json
        return isinstance(payload, dict) and payload.get('keyword') == ''
    except Exception:
        return False


def capture_submit(page, field, evidence, submit):
    state = dict(evidence or {}, loaded=False)
    def on_response(response):
        if empty_query(response):
            state['loaded'] = True
    page.on('response', on_response)
    try:
        submit()
        state['final_value'] = field.input_value()
        state['after_rows'] = rows(page)
        return state
    finally:
        page.remove_listener('response', on_response)


def verify(evidence):
    if not evidence or not evidence.get('before_value'):
        return '확인 필요', '지우기 버튼 클릭 전 검색어 입력 근거가 없음'
    if evidence.get('after_value') != '' or evidence.get('final_value') != '':
        return '확인 필요', '검색 입력창의 값이 비워진 상태를 확인하지 못함'
    if not evidence.get('loaded') or evidence.get('after_rows') is None:
        return '확인 필요', '검색 조건 없는 환자 목록 조회 완료 근거가 부족함'
    baseline = evidence.get('baseline_rows')
    if baseline is None or evidence['after_rows'] != baseline:
        return '확인 필요', '검색 조건 해제는 확인했으나 검색 전 목록으로 복귀한 근거가 부족함'
    return 'PASS', '지우기 버튼으로 입력값 비움 + 검색어 없는 조회 성공 + 검색 전 환자 목록 복귀 확인'
