"""검사 상태 다중 선택에서 취소 포함 및 현재 목록 표시를 확인한다."""
import re
import time
from urllib.parse import parse_qs, urlsplit
from verifications.reception_defaults_verification import read_states, STATUSES


def applies(tc):
    title=re.sub(r'\s+','',str(tc.get('title') or ''))
    context=re.sub(r'\s+','',' '.join(str(tc.get(k) or '') for k in ('sheet_name','steps','precondition')))
    return '검사상태' in title and '취소' in title and '포함' in title and '검사접수' in context


def status_ids(query):
    return sorted(set(item for value in query.get('receptionProgressStatusNo',[]) for item in value.split(',') if item))


def list_statuses(page):
    return page.evaluate(r'''() => {
      const visible=e=>!!e.getClientRects().length&&getComputedStyle(e).visibility!=='hidden';
      const tables=[...document.querySelectorAll('table,[role="table"],[role="grid"]')].filter(visible)
        .filter(t=>/환자명/.test(t.innerText)&&/검사 상태/.test(t.innerText));
      if(tables.length!==1)return null;
      const t=tables[0],headers=[...t.querySelectorAll('th,[role="columnheader"]')];
      const col=headers.findIndex(h=>h.innerText.replace(/\s/g,'')==='검사상태');
      if(col<0)return null;
      return {busy:t.matches('[aria-busy="true"]')||!!t.parentElement.querySelector('[role="progressbar"]'),
        statuses:[...t.querySelectorAll('tbody tr,[role="row"]')].filter(visible)
          .map(r=>[...r.querySelectorAll('td,[role="cell"],[role="gridcell"]')])
          .filter(c=>c.length===headers.length&&c.every(e=>!(e.colSpan>1))).map(c=>c[col].innerText.trim())};
    }''')


def collect(page):
    state=dict(responses=[],request_failed=0)
    handlers=[]
    trigger=None
    opened=False
    try:
        if not re.search(r'(?:^|/)receptions?/?$',urlsplit(page.url).path):
            return dict(state,error='검사 접수 목록 경로 진입 근거 없음')
        page.wait_for_load_state('networkidle',timeout=5000)
        triggers=page.locator('button[id^="multi-select-"]').filter(visible=True)
        if triggers.count()!=1:return dict(state,error='검사 상태 다중 선택을 하나로 식별하지 못함')
        trigger=triggers
        scope=trigger.get_attribute('aria-controls') or trigger.get_attribute('id')+'-options'
        if trigger.get_attribute('aria-expanded')!='true':trigger.click(timeout=3000)
        opened=True
        reading=read_states(page,scope,STATUSES)
        state['before']=reading['states']
        if any(v is None for v in state['before'].values()):return dict(state,error='검사 상태 초기 체크 상태 식별 실패')
        if state['before']['취소']:return dict(state,error='초기 취소가 이미 선택되어 있어 추가 포함 동작 검증 불가')
        baseline=parse_qs(urlsplit(page.url).query,keep_blank_values=True)
        state['before_ids']=status_ids(baseline)
        state['before_filters']={k:v for k,v in baseline.items() if k not in ('receptionProgressStatusNo','page')}
        def related(request):
            try:return request.resource_type in ('xhr','fetch') and bool(re.search(r'(?:^|/)receptions?(?:/(?:list|search))?/?$',urlsplit(request.url).path,re.I))
            except Exception:return False
        def response(value):
            if related(value.request):state['responses'].append(dict(status=value.status,ids=status_ids(parse_qs(urlsplit(value.url).query))))
        def failed(value):
            if related(value):state['request_failed']+=1
        for event,handler in [('response',response),('requestfailed',failed)]:
            page.on(event,handler);handlers.append((event,handler))
        page.locator('[id="'+scope.replace('"','\\"')+'"]').get_by_role('checkbox',name='취소',exact=True).set_checked(True,timeout=3000)
        if trigger.get_attribute('aria-expanded')!='true':trigger.click(timeout=3000)
        state['after']=read_states(page,scope,STATUSES)['states']
        deadline=time.monotonic()+5
        while True:
            state['rows']=list_statuses(page)
            if (state['responses'] and state['rows'] and not state['rows']['busy']
                    and '취소' in state['rows']['statuses']):break
            if state['request_failed'] or any(r['status']>=400 for r in state['responses']) or time.monotonic()>=deadline:break
            page.wait_for_timeout(100)
        if state['responses'] and all(200<=r['status']<300 for r in state['responses']):
            page.wait_for_load_state('networkidle',timeout=5000)
            state['rows']=list_statuses(page)
        query=parse_qs(urlsplit(page.url).query,keep_blank_values=True)
        state['after_ids']=status_ids(query)
        state['after_filters']={k:v for k,v in query.items() if k not in ('receptionProgressStatusNo','page')}
    except Exception as exc:state['error']='취소 상태 포함 근거 수집 실패: '+str(exc)
    finally:
        for event,handler in handlers:page.remove_listener(event,handler)
        if opened and trigger is not None:
            try:
                if trigger.get_attribute('aria-expanded')=='true':trigger.click(timeout=3000)
            except Exception:state['error']='검사 상태 드롭다운을 닫지 못함'
    return state


def verify(state):
    if not state or state.get('error'):return 'FAIL','검증 불가: '+((state or {}).get('error') or '취소 포함 실행 근거 없음')
    before,after=state.get('before',{}),state.get('after',{})
    if before.get('취소') is not False or after.get('취소') is not True:return 'FAIL','취소 미선택에서 선택으로 변경된 근거 없음'
    if any(before.get(s) is None or after.get(s)!=before[s] for s in ('대기','진행','종료')):
        return 'FAIL','취소 외 기존 검사 상태의 체크 선택이 변경됨'
    all_selected=all(after.get(s) is True for s in STATUSES)
    ids=state.get('after_ids',[])
    if all_selected:
        if ids not in ([],['0']):return 'FAIL','전체 상태 선택과 URL 상태 필터가 일치하지 않음'
    else:
        old=set(state.get('before_ids',[]));new=set(ids)
        if not old.issubset(new) or len(new-old)!=1:return 'FAIL','취소 추가 선택과 URL 상태 필터 변경이 일치하지 않음'
    if state.get('before_filters')!=state.get('after_filters'):return 'FAIL','검사 상태 외 기존 조회 조건이 변경됨'
    if state.get('request_failed'):return 'FAIL','검사 상태 포함 조회 요청 실패'
    matches=[r for r in state.get('responses',[]) if (r['ids'] in ([],['0']) if all_selected else r['ids']==ids)]
    if not matches:return 'FAIL','검증 불가: 변경한 상태 조건의 조회 응답 근거 없음'
    if any(not 200<=r['status']<300 for r in matches):return 'FAIL','취소 포함 조회가 비정상 HTTP 응답을 반환함'
    rows=state.get('rows')
    if not rows or rows['busy']:return 'FAIL','검증 불가: 검사 상태 컬럼 및 목록 로딩 완료 근거 없음'
    allowed={s for s in STATUSES if after.get(s)}
    if any(s not in allowed for s in rows['statuses']):return 'FAIL','선택하지 않은 검사 상태의 접수 건이 목록에 표시됨'
    if '취소' not in rows['statuses']:return 'FAIL','검증 불가: 현재 페이지에 취소 접수 건이 없어 포함 노출 확인 불가 (데이터·필터·페이지 확인 필요)'
    return 'PASS','기존 검사 상태 유지 + 취소 추가 선택 + 상태 조건 조회 성공 + 현재 목록 취소 접수 건 표시 확인 (행 수 증가는 요구하지 않음)'
