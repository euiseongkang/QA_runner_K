"""검사 접수 상단 컨트롤과 추가 필터 패널을 구분해 검증한다."""
import re
import time

LABELS = ('모니터링 대상만 보기', '내 환자만 보기')


def applies(tc):
    title = re.sub(r'\s+', '', str(tc.get('title') or ''))
    context = re.sub(r'\s+', '', ' '.join(str(tc.get(k) or '') for k in ('sheet_name','steps','precondition')))
    return '필터' in title and '구성' in title and '검사접수' in context


def read(page):
    return page.evaluate(r'''() => {
      const visible=e=>!!e.getClientRects().length&&getComputedStyle(e).visibility!=='hidden';
      const norm=s=>(s||'').replace(/\s+/g,' ').trim();
      const triggers=[...document.querySelectorAll('[id^="filter-funnel-"]:not([id$="-label"])')].filter(visible);
      if(triggers.length!==1)return {error:'필터 아이콘을 하나로 식별하지 못함'};
      const trigger=triggers[0];
      let toolbar=null,p=trigger.parentElement;
      for(let i=0;p&&p!==document.body&&i<8;i++,p=p.parentElement){
        if(p.querySelector('table,[role="table"],[role="grid"]'))break;
        if(p.querySelector('[role="tablist"]')||
           (p.querySelector('[id^="multi-select-"]')&&p.querySelector('input[placeholder="YYYY-MM-DD"]'))){toolbar=p;break;}
      }
      const panels=[...document.querySelectorAll('[data-filter-tooltip-panel],.filter-tooltip-panel')].filter(visible);
      // 마커가 중첩되어 있으면 안쪽 패널만 센다.
      const unique=panels.filter(e=>!panels.some(other=>other!==e&&e.contains(other)));
      const panel=unique.length===1?unique[0]:null;
      const labels=['모니터링 대상만 보기','내 환자만 보기'];
      const checks={};
      for(const name of labels){
        const controls=panel?[...panel.querySelectorAll('[role="checkbox"],input[type="checkbox"]')].filter(visible):[];
        checks[name]=controls.filter(c=>{
          const label=c.getAttribute('aria-label')||(c.labels&&[...c.labels].map(l=>l.innerText).join(' '))||c.innerText;
          return norm(label).replace(/^check\s*/,'')===name;
        }).length===1;
      }
      const tabs=toolbar?[...toolbar.querySelectorAll('[role="tab"]')].filter(visible).map(e=>norm(e.innerText)):[];
      const statuses=toolbar?[...toolbar.querySelectorAll('[id^="multi-select-"]')].filter(visible):[];
      const dates=toolbar?[...toolbar.querySelectorAll('input[placeholder="YYYY-MM-DD"]')].filter(visible):[];
      const exams=toolbar?[...toolbar.querySelectorAll('button,[role="combobox"],select')].filter(visible)
        .filter(e=>!e.id.startsWith('multi-select-')&&e.getAttribute('aria-label')!=='입력 지우기')
        .filter(e=>/검사/.test((e.getAttribute('aria-label')||'')+' '+norm(e.innerText))||!!e.querySelector('img[alt="arrow"]')):[];
      return {trigger_id:trigger.id,toolbar_found:!!toolbar,exam:exams.length===1,
        exam_id:exams.length===1?exams[0].id:null,
        tabs,status:statuses.length===1,dates:dates.length,panel_count:unique.length,
        panel_visible:!!panel,checks};
    }''')


def click_and_collect(page):
    before=read(page)
    if before.get('error'):return before
    state=dict(before,clicked=False)
    try:
        # 이미 열려 있으면 닫았다 다시 열어 클릭 동작까지 검증한다. 필터 값은 바꾸지 않는다.
        target=page.locator('[id="'+before['trigger_id'].replace('"','\\"')+'"]')
        if before.get('panel_visible'):
            target.click(timeout=3000)
            deadline=time.monotonic()+2
            while read(page).get('panel_visible'):
                if time.monotonic()>=deadline:raise ValueError('기존 필터 패널을 닫지 못함')
                page.wait_for_timeout(100)
        target.click(timeout=3000)
        state['clicked']=True
        deadline=time.monotonic()+3
        while True:
            state.update(read(page))
            if state.get('panel_visible') or time.monotonic()>=deadline:break
            page.wait_for_timeout(100)
    except Exception as exc:state['error']='필터 아이콘 클릭/패널 확인 실패: '+str(exc)
    return state


def verify(state):
    if not state or state.get('error'):
        return 'FAIL','검증 불가: '+((state or {}).get('error') or '필터 아이콘 클릭 및 패널 근거가 없음')
    if not state.get('clicked'):return 'FAIL','필터 아이콘을 클릭한 근거가 없음'
    missing=[]
    if not state.get('toolbar_found'):missing.append('목록 상단 필터 영역')
    if not state.get('exam'):missing.append('검사 선택')
    for tab in ('전체','외래','입원','응급'):
        if tab not in state.get('tabs',[]):missing.append(tab+' 유형 탭')
    if not state.get('status'):missing.append('검사 상태 선택')
    if state.get('dates')!=2:missing.append('처방일 시작·종료 입력란')
    if not state.get('panel_visible'):missing.append('추가 필터 패널 열림')
    for label in LABELS:
        if not state.get('checks',{}).get(label):missing.append('패널 내 '+label+' 체크박스')
    if missing:return 'FAIL','필터 구성 미확인/미노출: '+', '.join(missing)
    return 'PASS','상단 검사 선택·유형 4종·검사 상태·시작/종료일 및 필터 클릭 후 추가 패널의 체크박스 2종 표시 확인'
