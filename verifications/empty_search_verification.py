"""검색 결과 0건 안내를 목록·조회 응답·관찰한 오류로 검증한다."""
import re
import time
from urllib.parse import parse_qs, urlsplit
from verifications.search_no_enter_verification import find_field


def applies(tc):
    text = str(tc.get('title') or '') + '\n' + str(tc.get('expected') or '')
    return bool(re.search(r'(?:검색|조회)\s*결과(?:가|는|\s)*없|결과가\s*없음|조회\s*결과가\s*없', text))


def expected_notices(text):
    """따옴표에 바로 연결된 안내 문맥만 사용한다. 줄바꿈/번호 유무에 의존하지 않는다."""
    result = []
    quotes = list(re.finditer(r'''["'“‘]([^"'”’\n]+)["'”’]''', str(text or '')))
    for index, match in enumerate(quotes):
        # 다른 따옴표 항목의 문맥까지 연결하지 않는다.
        before = text[quotes[index-1].end() if index else 0:match.start()]
        after = text[match.end():quotes[index+1].start() if index+1<len(quotes) else len(text)]
        label_before = re.search(r'(?:안내(?:\s*문구)?|문구|메시지)\s*(?:는|가|:|로|를|을)?\s*$', before)
        label_after = re.match(r'\s*(?:라는|이라는|의)?\s*(?:안내|문구|메시지)', after)
        list_display = (re.search(r'(?:목록|테이블|영역)[^.!?\n]{0,60}$', before)
                        and re.match(r'\s*(?:이|가)?\s*(?:표시|노출)', after))
        if (label_before or label_after or list_display) and match[1] not in result:
            result.append(match[1])
    return result


def action(tc):
    values = []
    steps = str(tc.get('steps') or '')
    for line in steps.splitlines():
        if '입력' in line:
            values.extend(re.findall(r'''["'“‘]([^"'”’\n]+)["'”’]''', line))
    notices = expected_notices(str(tc.get('expected') or ''))
    wait = re.search(r'(\d+(?:\.\d+)?)\s*초(?:\s*동안)?(?:\s*추가로)?\s*(?:기다|대기)',steps)
    return dict(type='search_empty_results',description='검색 결과 0건 안내 및 관찰 오류 확인',
                value=values[0] if len(values)==1 else None,
                enter=bool(re.search(r'Enter|엔터',steps,re.I)),
                receptions='검사접수' in re.sub(r'\s+','',' '.join(str(tc.get(k) or '') for k in ('sheet_name','precondition','steps'))),
                notices=notices, settle_seconds=float(wait[1]) if wait else 0)


def screen(page):
    return page.evaluate(r'''() => {
      const visible=e=>!!e.getClientRects().length&&getComputedStyle(e).visibility!=='hidden';
      const tables=[...document.querySelectorAll('table,[role="table"],[role="grid"]')].filter(visible)
        .filter(t=>/환자명/.test(t.innerText));
      if(tables.length!==1)return null;
      const t=tables[0],headers=t.querySelectorAll('th,[role="columnheader"]');
      if(headers.length<2)return null;
      const data=[...t.querySelectorAll('tbody tr,[role="row"]')].filter(visible)
        .filter(r=>{const cells=[...r.querySelectorAll('td,[role="cell"],[role="gridcell"]')];
          return cells.length===headers.length&&cells.every(c=>!(c.colSpan>1));});
      const scope=t.parentElement||t;
      const notices=[scope,...scope.querySelectorAll('*')].filter(visible).map(e=>(e.innerText||'').trim())
        .filter(s=>s.length>0&&s.length<=160&&/(?:검색|조회).*결과.*없|데이터가 없습니다/.test(s))
        .sort((a,b)=>a.length-b.length);
      const alerts=[...document.querySelectorAll('[role="alert"]')].filter(visible)
        .map(e=>e.innerText.trim()).filter(s=>/오류|실패|에러|error/i.test(s));
      return {rows:data.length,notices:[...new Set(notices)],alerts,
        busy:t.matches('[aria-busy="true"]')||!!scope.querySelector('[role="progressbar"]')};
    }''')


def collect(page, action):
    state = dict(query=action.get('value'),statuses=[],page_errors=0,console_errors=0,
                 request_failed=0,observed=False,required_notices=action.get('notices',[]))
    if not isinstance(state['query'],str) or not state['query'].strip():
        return dict(state,error="테스트 절차에 실제 검색어를 따옴표로 명시해야 함 (예: 검색창에 '이오아우에'를 입력하고 Enter를 누른다)")
    if not action.get('enter'):
        return dict(state,error='검색 조회를 실행할 Enter 절차가 없음')
    settle = action.get('settle_seconds',0)
    if not 0 <= settle <= 60:
        return dict(state,error='조회 후 추가 대기는 0~60초 이내로 명시해야 함')
    def related(request):
        try:
            if request.resource_type not in ('xhr','fetch'):return False
            url=urlsplit(request.url)
            if not re.search(r'(?:^|/)(?:receptions?|patients?)(?:/(?:list|search))?/?$',url.path,re.I):return False
            values=parse_qs(url.query,keep_blank_values=True).get('keyword',[])
            if not values:
                body=request.post_data_json
                values=[body.get('keyword')] if isinstance(body,dict) else []
            return values==[state['query']]
        except Exception:return False
    def response(value):
        if related(value.request):state['statuses'].append(value.status)
    def page_error(_):state['page_errors']+=1
    def console(value):
        if value.type=='error':state['console_errors']+=1
    def failed(request):
        if related(request):state['request_failed']+=1
    handlers = [('response',response),('pageerror',page_error),('console',console),('requestfailed',failed)]
    attached=[]
    try:
        page.wait_for_load_state('networkidle',timeout=5000)
        if action.get('receptions') and not re.search(r'(?:^|/)receptions?(?:/|$)',urlsplit(page.url).path):
            return dict(state,error='검사 접수 목록 경로 진입을 확인하지 못함')
        field=find_field(page)
        for event,handler in handlers:
            page.on(event,handler);attached.append((event,handler))
        field.fill(state['query'])
        field.press('Enter')
        deadline=time.monotonic()+5
        while True:
            state['screen']=screen(page)
            state['final_value']=field.input_value()
            current=state['screen']
            if (state['statuses'] or state['request_failed']) and current and not current['busy']:
                if current['rows']==0 and current['notices']:break
                if state['request_failed'] or any(s>=400 for s in state['statuses']):break
            if time.monotonic()>=deadline:break
            page.wait_for_timeout(100)
        # 렌더링 직후 발생하는 페이지/콘솔 오류도 같은 관찰 구간에 포함한다.
        state['settle_ms'] = max(200,settle*1000)
        page.wait_for_timeout(state['settle_ms'])
        state['screen']=screen(page)
        state['final_value']=field.input_value()
        state['observed']=True
    except Exception as exc:state['error']='검색 결과 관찰 실패: '+str(exc)
    finally:
        for event,handler in attached:page.remove_listener(event,handler)
    return state


def verify(state):
    if not state or state.get('error'):
        return 'FAIL','검증 불가: '+((state or {}).get('error') or '검색 실행 및 결과 근거가 없음')
    if state.get('request_failed') or any(not 200<=s<300 for s in state.get('statuses',[])):
        return 'FAIL','검색 조회 요청 실패 또는 비정상 HTTP 응답 확인'
    if state.get('page_errors') or state.get('console_errors'):
        return 'FAIL',f"검색 관찰 중 페이지 오류 {state['page_errors']}건·콘솔 오류 {state['console_errors']}건 수집"
    current=state.get('screen')
    if not state.get('observed') or not state.get('statuses') or not current or current.get('busy'):
        return 'FAIL','검증 불가: 검색 조회 성공 및 목록 렌더링 완료 근거가 부족함'
    if current.get('alerts'):
        return 'FAIL','검색 결과 화면에서 오류 안내가 표시됨'
    if state.get('final_value')!=state.get('query'):
        return 'FAIL','검색창에 실행한 검색어가 유지되지 않음'
    if current['rows']!=0:return 'FAIL','검색 결과가 없어야 하지만 목록 데이터 행이 표시됨'
    if not current.get('notices'):return 'FAIL','검색 결과 0건이나 목록 영역에 빈 결과 안내가 표시되지 않음'
    missing = [required for required in state.get('required_notices',[])
               if not any(required in text for text in current['notices'])]
    if missing:
        return 'FAIL',f"빈 결과 안내 불일치 (기대: {missing[0][:120]} / 수집: {current['notices'][0][:120]})"
    return 'PASS','검색 조회 성공 + 데이터 행 0건 + 빈 결과 안내 확인; 관찰 구간 내 조회 실패·페이지/콘솔 오류·오류 안내 없음'
