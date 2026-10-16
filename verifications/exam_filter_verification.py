"""검사 접수 검사명 옵션 순서와 선택 조회를 DOM·응답으로 판정한다."""
import re
import time
from urllib.parse import parse_qs, urlsplit
from verifications import reception_filter_panel_verification as panel


def applies(tc):
    title = re.sub(r'\s+','',' '.join(str(tc.get(k) or '') for k in ('title','expected')))
    context = re.sub(r'\s+','',' '.join(str(tc.get(k) or '') for k in ('sheet_name','steps','precondition')))
    return '검사명' in title and ('정렬' in title or '가나다' in title) and '검사접수' in context


def action(tc):
    values=[]
    for line in str(tc.get('steps') or '').splitlines():
        if '선택' in line:
            values.extend(re.findall(r'''["'“‘]([^"'”’\n]+)["'”’]''',line))
    return dict(type='verify_exam_filter',description='검사명 옵션 정렬 및 선택 조회 근거 수집',
                value=values[0] if len(values)==1 else None)


def options(page):
    return page.evaluate(r'''() => {
      const visible=e=>!!e.getClientRects().length&&getComputedStyle(e).visibility!=='hidden';
      const all=[...document.querySelectorAll('ul.select-dropdown')];
      const lists=all.filter(visible).map(el=>({el,items:[...el.querySelectorAll('li')]
        .map(li=>({label:(li.querySelector('span[title]')?.getAttribute('title')||li.innerText).trim(),value:li.getAttribute('value')}))}))
        .filter(x=>x.items.some(item=>item.label==='전체 검사'));
      if(lists.length!==1)return null;
      const {el,items}=lists[0],labels=items.slice(1).map(x=>x.label),collator=new Intl.Collator('ko');
      return {index:all.indexOf(el),items,ordered:labels.every((label,i)=>i===0||collator.compare(labels[i-1],label)<=0)};
    }''')


def rows(page):
    return page.evaluate(r'''() => {
      const visible=e=>!!e.getClientRects().length&&getComputedStyle(e).visibility!=='hidden';
      const tables=[...document.querySelectorAll('table,[role="table"],[role="grid"]')].filter(visible)
        .filter(t=>/환자명/.test(t.innerText)&&/검사명/.test(t.innerText));
      if(tables.length!==1)return null;
      const t=tables[0],headers=[...t.querySelectorAll('th,[role="columnheader"]')];
      const col=headers.findIndex(h=>h.innerText.replace(/\s/g,'')==='검사명');
      if(col<0)return null;
      return {busy:t.matches('[aria-busy="true"]')||!!t.parentElement.querySelector('[role="progressbar"]'),
        names:[...t.querySelectorAll('tbody tr,[role="row"]')].filter(visible)
          .map(r=>[...r.querySelectorAll('td,[role="cell"],[role="gridcell"]')])
          .filter(c=>c.length===headers.length&&c.every(e=>!(e.colSpan>1)))
          .map(c=>c[col].innerText.trim())};
    }''')


def collect(page, action):
    state=dict(target=action.get('value'),statuses=[],request_failed=0)
    target=state['target']
    if not isinstance(target,str) or not target.strip():
        return dict(state,error="절차에 선택할 검사명을 따옴표로 명시해야 함 (예: '리브레'를 선택한다)")
    attached=[]
    try:
        if not re.search(r'(?:^|/)receptions?/?$',urlsplit(page.url).path):
            return dict(state,error='검사 접수 목록 경로 진입을 확인하지 못함')
        page.wait_for_load_state('networkidle',timeout=5000)
        info=panel.read(page)
        if info.get('error') or not info.get('exam_id'):
            return dict(state,error='상단 검사명 드롭다운을 하나로 식별하지 못함')
        trigger=page.locator('[id="'+info['exam_id'].replace('"','\\"')+'"]')
        opts=options(page)
        if opts is None:
            trigger.click(timeout=3000)
            deadline=time.monotonic()+3
            while opts is None and time.monotonic()<deadline:
                opts=options(page)
                if opts is None:page.wait_for_timeout(100)
        if opts is None:return dict(state,error='검사명 옵션 목록을 식별하지 못함')
        state['options']=opts['items'];state['ordered']=opts['ordered']
        matches=[item for item in opts['items'] if item['label']==target]
        if len(matches)!=1 or not matches[0]['value']:
            return dict(state,error='선택할 검사명 옵션을 하나로 식별하지 못함: '+target)
        state['device_no']=matches[0]['value']
        baseline=parse_qs(urlsplit(page.url).query,keep_blank_values=True)
        state['before_filters']={k:v for k,v in baseline.items() if k not in ('deviceNo','page')}
        def related(request):
            try:
                url=urlsplit(request.url)
                if request.resource_type not in ('xhr','fetch') or not re.search(r'(?:^|/)receptions?(?:/(?:list|search))?/?$',url.path,re.I):return False
                return parse_qs(url.query).get('deviceNo')==[state['device_no']]
            except Exception:return False
        def response(value):
            if related(value.request):state['statuses'].append(value.status)
        def failed(value):
            if related(value):state['request_failed']+=1
        for event,handler in [('response',response),('requestfailed',failed)]:
            page.on(event,handler);attached.append((event,handler))
        page.locator('ul.select-dropdown').nth(opts['index']).locator('li').filter(
            has_text=re.compile(r'^\s*'+re.escape(target)+r'\s*$')).click(timeout=3000)
        deadline=time.monotonic()+5
        while True:
            state['rows']=rows(page)
            query=parse_qs(urlsplit(page.url).query)
            if (state['statuses'] and state['rows'] and not state['rows']['busy'] and state['rows']['names']
                    and query.get('deviceNo')==[state['device_no']] and trigger.inner_text().strip()==target):break
            if state['request_failed'] or any(s>=400 for s in state['statuses']) or time.monotonic()>=deadline:break
            page.wait_for_timeout(100)
        if state['statuses'] and not state['request_failed'] and all(200<=s<300 for s in state['statuses']):
            page.wait_for_load_state('networkidle',timeout=5000)
            state['rows']=rows(page)
        state['selected']=trigger.inner_text().strip()
        query=parse_qs(urlsplit(page.url).query,keep_blank_values=True)
        state['url_device']=query.get('deviceNo')
        state['after_filters']={k:v for k,v in query.items() if k not in ('deviceNo','page')}
    except Exception as exc:state['error']='검사명 선택 조회 근거 수집 실패: '+str(exc)
    finally:
        for event,handler in attached:page.remove_listener(event,handler)
    return state


def verify(state):
    if not state or state.get('error'):return 'FAIL','검증 불가: '+((state or {}).get('error') or '검사명 필터 실행 근거 없음')
    names=[item['label'] for item in state.get('options',[])]
    if len(names)<2 or names[0]!='전체 검사':return 'FAIL','검사명 옵션 첫 항목이 전체 검사가 아니거나 비교할 검사명 옵션이 없음'
    if not state.get('ordered'):return 'FAIL','전체 검사 다음 검사명 옵션이 한국어 가나다 정렬 순서와 다름'
    if state.get('request_failed') or any(not 200<=s<300 for s in state.get('statuses',[])):return 'FAIL','선택한 검사명의 목록 조회 요청 실패'
    if not state.get('statuses'):return 'FAIL','검증 불가: 선택한 deviceNo의 목록 조회 성공 근거 없음'
    if state.get('selected')!=state['target'] or state.get('url_device')!=[state.get('device_no')]:return 'FAIL','선택한 검사명 표시 또는 URL 조회 조건 불일치'
    if state.get('before_filters')!=state.get('after_filters'):return 'FAIL','검사명 외 기존 조회 조건이 변경됨'
    result=state.get('rows')
    if not result or result['busy']:return 'FAIL','검증 불가: 검사명 컬럼 및 목록 조회 완료 근거 없음'
    if not result['names']:return 'FAIL','검증 불가: 조회 결과 0건으로 선택 검사만 노출되는지 비교할 데이터가 없음'
    if any(name!=state['target'] for name in result['names']):return 'FAIL','선택한 검사명과 다른 접수 건이 현재 목록에 표시됨'
    return 'PASS','전체 검사 첫 항목 + 검사명 가나다 정렬 + 선택 검사 조회 성공 + 현재 목록 모든 행의 검사명 일치 확인'
