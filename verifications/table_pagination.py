"""목록 페이지 이동·로딩 확인·조건 보존·반복 수집을 위한 공통 실행기."""
import json
import re
import time
from urllib.parse import parse_qs, urlsplit

CONTROLS = 'a,button,[role="link"],[role="button"]'


def query(page):
    return parse_qs(urlsplit(page.url).query, keep_blank_values=True)


def page_index(page):
    values = query(page).get('page', ['0'])
    if len(values) != 1 or not re.fullmatch(r'\d+', values[0]):
        raise ValueError('목록 URL의 페이지 번호를 식별하지 못함')
    return int(values[0])


def filters(values):
    result = {k: v for k, v in values.items() if k != 'page' and v != ['']}
    if 'receptionProgressStatusNo' in result:
        result['receptionProgressStatusNo'] = sorted(set(x for v in result['receptionProgressStatusNo'] for x in v.split(',') if x))
    return result


def controls(page):
    return page.evaluate(r'''selector => {
      const visible=e=>!!e.getClientRects().length&&getComputedStyle(e).visibility!=='hidden';
      const all=[...document.querySelectorAll(selector)];
      const candidates=all.filter(visible).filter(e=>!e.closest('table,[role="table"],[role="grid"]'));
      const find=labels=>candidates.filter(e=>{
        const names=[e.getAttribute('aria-label'),e.getAttribute('title'),e.innerText,...[...e.querySelectorAll('img')].map(i=>i.alt)];
        return names.some(n=>labels.includes((n||'').trim()));});
      const result={};
      for(const [key,labels] of Object.entries({first:['처음','첫 페이지','First Page'],next:['다음','다음 페이지','Next Page']})){
        let matches=find(labels);
        if(key==='first'&&!matches.length)matches=candidates.filter(e=>e.innerText.trim()==='1');
        result[key]=matches.length===1?{index:all.indexOf(matches[0]),
          disabled:matches[0].matches(':disabled,[aria-disabled="true"]')||getComputedStyle(matches[0]).pointerEvents==='none'}:
          {error:key+' 페이지 컨트롤 '+matches.length+'개'};
      }
      return result;
    }''', CONTROLS)


class PageNavigator:
    """프로젝트의 page=0 기반 patients/receptions 목록을 UI로만 이동한다."""
    def __init__(self, page):
        self.page = page
        path = urlsplit(page.url).path.rstrip('/')
        if path not in ('/patients', '/receptions'):
            raise ValueError('지원하는 목록 경로가 아님: ' + path)
        self.route = path.rsplit('/', 1)[-1]
        self.baseline = None
        self.requests = {}
        self.handlers = []

    def __enter__(self):
        def related(request):
            try:
                path = urlsplit(request.url).path.rstrip('/')
                return request.resource_type in ('xhr', 'fetch') and bool(re.search(
                    r'(?:^|/)' + re.escape(self.route) + r'(?:/(?:list|search))?$', path))
            except Exception:
                return False
        def requested(request):
            if related(request):
                q = parse_qs(urlsplit(request.url).query, keep_blank_values=True)
                self.requests[request] = dict(page=q.get('page', ['0']), query=q, status=None, done=False, failed=False)
        def responded(response):
            if response.request in self.requests:
                self.requests[response.request]['status'] = response.status
        def finished(request):
            if request in self.requests: self.requests[request]['done'] = True
        def failed(request):
            if request in self.requests: self.requests[request].update(done=True, failed=True)
        for event, handler in (('request', requested), ('response', responded), ('requestfinished', finished), ('requestfailed', failed)):
            self.page.on(event, handler); self.handlers.append((event, handler))
        return self

    def __exit__(self, *args):
        for event, handler in self.handlers: self.page.remove_listener(event, handler)

    def check_filters(self):
        if urlsplit(self.page.url).path.rstrip('/') != '/' + self.route:
            raise ValueError('목록 페이지 이동 중 경로가 변경됨')
        if self.baseline is not None and filters(query(self.page)) != self.baseline:
            actual = filters(query(self.page))
            changed = sorted(k for k in self.baseline.keys() | actual.keys() if self.baseline.get(k) != actual.get(k))
            raise ValueError('페이지 이동 중 조회 조건이 변경됨: ' + ', '.join(changed))

    def ready(self, read, *, expected=None, previous=None, offset=0, timeout=5):
        deadline = time.monotonic() + timeout
        last, stable_since, last_error = None, time.monotonic(), ''
        while True:
            self.check_filters()
            actual = page_index(self.page)
            snapshot = read(self.page)
            last_error = (snapshot or {}).get('error', '')
            stamp = json.dumps([snapshot, filters(query(self.page))], ensure_ascii=False, sort_keys=True)
            now = time.monotonic()
            if stamp != last or not snapshot or snapshot.get('busy') or last_error:
                last, stable_since = stamp, now
            observed = list(self.requests.values())[offset:]
            matching = [r for r in observed if r['page'] == [str(actual)]]
            if any(r['failed'] or (r['status'] is not None and not 200 <= r['status'] < 300) for r in matching):
                raise ValueError('대상 페이지 목록 조회 실패')
            pending = any(not r['done'] for r in observed)
            successful = any(r['done'] and r['status'] is not None and 200 <= r['status'] < 300
                             and all(filters(r['query']).get(k) == v for k, v in (self.baseline or {}).items()) for r in matching)
            changed = previous is not None and snapshot and snapshot != previous
            proof = 'initial_list_stable' if expected is None else ('response_finished' if successful else 'render_changed' if changed and not observed else None)
            if (expected is None or actual == expected) and snapshot and not last_error and not snapshot.get('busy') and not pending and now - stable_since >= 0.5 and proof:
                if self.baseline is None: self.baseline = filters(query(self.page))
                return snapshot, dict(page=actual + 1, index=actual, proof=proof)
            if now >= deadline:
                target = str(expected + 1) if expected is not None else '현재 페이지'
                raise ValueError(last_error or '페이지 이동·조회 완료 근거 부족 (예상 ' + target + ', 실제 ' + str(actual + 1) + '페이지)')
            self.page.wait_for_timeout(100)

    def move(self, direction, read, previous):
        before = page_index(self.page)
        expected = 0 if direction == 'first' else before + 1
        target = controls(self.page)[direction]
        if target.get('error'): raise ValueError(target['error'])
        if target['disabled']: raise ValueError(direction + ' 페이지 이동 컨트롤 비활성')
        offset = len(self.requests)
        self.page.locator(CONTROLS).nth(target['index']).click(timeout=3000)
        return self.ready(read, expected=expected, previous=previous, offset=offset)


def walk(page, *, read, visit, max_pages, start='first', stop=None):
    """visit가 선택 열을 해석하고 stop이 종료 여부를 결정한다. 판정 내용은 알지 못한다."""
    result = dict(pages=[], navigation=[], termination=None, complete=False)
    try:
        if not isinstance(max_pages, int) or isinstance(max_pages, bool) or not 1 <= max_pages <= 50:
            raise ValueError('최대 페이지 수는 1~50의 정수여야 함')
        if start not in ('first', 'current'): raise ValueError('지원하지 않는 시작 페이지 정책')
        with PageNavigator(page) as pager:
            current, info = pager.ready(read)
            if start == 'first' and page_index(page) != 0:
                current, info = pager.move('first', read, current)
            for index in range(max_pages):
                result['navigation'].append(info)
                result['pages'].append(visit(current, info))
                decision = stop(result['pages']) if stop else None
                if decision:
                    result['termination'] = decision if isinstance(decision, str) else 'goal_reached'
                    break
                # 한도에 도달한 뒤 4페이지 등의 컨트롤을 클릭하지 않는다.
                if index + 1 == max_pages:
                    target = controls(page)['next']
                    last = not target.get('error') and target['disabled']
                    result.update(termination='last_page' if last else 'page_limit', complete=last)
                    break
                target = controls(page)['next']
                if target.get('error'): raise ValueError(target['error'])
                if target['disabled']:
                    result.update(termination='last_page', complete=True)
                    break
                current, info = pager.move('next', read, current)
    except Exception as exc:
        result.update(error=str(exc), termination='error')
    return result
