"""환자 목록 페이지 버튼의 선택 상태와 조회 결과를 수집한다."""
import re
import time
from urllib.parse import urlsplit, parse_qs

CONTROLS = 'button, a, [role="button"], [role="link"]'


def target(tc):
    text = str(tc.get('title') or '') + str(tc.get('steps') or '') + str(tc.get('expected') or '')
    if not re.search(r'페이지네이션|페이지\s*이동', text):
        return None
    numbers = []
    for line in str(tc.get('steps') or '').splitlines():
        if re.search(r'클릭|누르|눌러', line):
            numbers += re.findall(r'\[(\d+)\]', line)
    return numbers[-1] if numbers else None


def snapshot(page):
    return page.evaluate(r'''() => {
      const visible=e=>e.getClientRects().length && getComputedStyle(e).visibility!=='hidden';
      const all=[...document.querySelectorAll('button,a,[role="button"],[role="link"]')];
      const groups=new Set();
      for(const el of all.filter(e=>visible(e)&&e.innerText.trim()==='1')) {
        for(let p=el.parentElement;p && p!==document.body;p=p.parentElement) {
          const cs=[...p.querySelectorAll('button,a,[role="button"],[role="link"]')].filter(visible);
          const nums=cs.filter(e=>/^\d+$/.test(e.innerText.trim()));
          if(nums.length>=2 && cs.length<=20 && cs.every(e=>!e.closest('table,[role="table"],[role="grid"]'))) {
            groups.add(p);break;
          }
          if(cs.length>20)break;
        }
      }
      if(groups.size!==1)return {selected:null,targets:{},rows:null};
      const cs=[...[...groups][0].querySelectorAll('button,a,[role="button"],[role="link"]')]
        .filter(visible).filter(e=>/^\d+$/.test(e.innerText.trim()));
      const active=cs.filter(e=>(e.hasAttribute('aria-current') && e.getAttribute('aria-current')!=='false') ||
        e.getAttribute('aria-selected')==='true' || e.getAttribute('aria-pressed')==='true' ||
        e.getAttribute('data-state')==='active' ||
        [...e.classList].some(c=>/^(active|selected|is-active|is-selected)$/.test(c)));
      const colors=cs.map(e=>getComputedStyle(e).backgroundColor);
      const highlighted=cs.filter((e,i)=>colors[i]!=='transparent' && colors[i]!=='rgba(0, 0, 0, 0)' &&
        colors.filter(c=>c===colors[i]).length===1 && colors.some(c=>colors.filter(x=>x===c).length===cs.length-1));
      const chosen=active.length===1?active:active.length===0?highlighted:[];
      const tables=[...document.querySelectorAll('table,[role="table"],[role="grid"]')].filter(visible).filter(t=>/환자명/.test(t.innerText));
      const rows=tables.length===1?[...tables[0].querySelectorAll('tbody tr,[role="row"]')].filter(visible)
        .filter(r=>r.querySelectorAll('td,[role="cell"],[role="gridcell"]').length>=2).map(r=>r.innerText.trim()):null;
      const labels=cs.map(e=>e.innerText.trim());
      const linkPages={};
      for(const el of cs) {
        const href=el.getAttribute('href');
        if(!href)continue;
        const url=new URL(href,location.href);
        const value=url.searchParams.get('page');
        if(url.origin===location.origin && /(?:^|\/)patients\/?$/.test(url.pathname) && /^\d+$/.test(value||''))
          linkPages[el.innerText.trim()]=Number(value);
      }
      return {selected:chosen.length===1?chosen[0].innerText.trim():null,rows,
        link_pages:linkPages,
        targets:Object.fromEntries(labels.filter(s=>labels.filter(x=>x===s).length===1).map(s=>[s,all.indexOf(cs.find(e=>e.innerText.trim()===s))]))};
    }''')


def click_and_collect(page, number):
    before = snapshot(page)
    if number not in before['targets']:
        raise ValueError('페이지네이션의 [' + number + '] 버튼을 하나로 식별하지 못함')
    # 시작 URL의 page 값과 선택 페이지를 비교해 0/1 기반 인덱스를 구분한다.
    params = parse_qs(urlsplit(page.url).query)
    try:
        base = int(before['selected']) - int(params['page'][0])
        if base not in (0, 1):
            base = None
    except (KeyError, ValueError, TypeError):
        base = None
    # 실제 환자 화면의 <a href="/patients?page=0..."> 링크를 우선 사용한다.
    # 활성 페이지는 href가 없어도 다른 숫자 링크로 기준을 확인할 수 있다.
    link_pages = before.get('link_pages', {})
    offsets = {int(label) - value for label, value in link_pages.items()}
    if len(offsets) == 1 and next(iter(offsets)) in (0, 1):
        base = next(iter(offsets))
    evidence = {'before': before, 'target': number, 'loaded': False}
    def on_response(response):
        try:
            url = urlsplit(response.url)
            query = parse_qs(url.query)
            if (base is not None and 200 <= response.status < 300
                    and response.request.resource_type in ('xhr', 'fetch')
                    and re.search(r'(?:^|/)patients?/?$', url.path, re.I)
                    and query.get('page') == [str(int(number) - base)]):
                evidence['loaded'] = True
        except Exception:
            pass
    page.on('response', on_response)
    try:
        page.locator(CONTROLS).nth(before['targets'][number]).click(timeout=5000)
        deadline = time.monotonic() + 5
        while True:
            evidence['after'] = snapshot(page)
            if verify(evidence)[0] == 'PASS' or time.monotonic() >= deadline:
                return evidence
            page.wait_for_timeout(100)
    finally:
        page.remove_listener('response', on_response)


def verify(evidence):
    if not evidence:
        return '확인 필요', '페이지 선택과 환자 목록 조회 근거를 수집하지 못함'
    before, after = evidence.get('before', {}), evidence.get('after', {})
    if after.get('selected') != evidence.get('target'):
        return '확인 필요', '대상 페이지 버튼의 선택 상태를 확인하지 못함'
    if (not evidence.get('loaded') or not before.get('rows') or not after.get('rows')
            or before['rows'] == after['rows']):
        return '확인 필요', '페이지 선택은 확인했으나 해당 페이지 조회 성공·목록 갱신 근거가 부족함'
    return 'PASS', '대상 페이지 선택 + 해당 페이지 조회 성공 + 환자 목록 갱신 확인'
