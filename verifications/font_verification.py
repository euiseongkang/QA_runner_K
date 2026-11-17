"""공통 기본 글꼴: 영역별 CSS와 Chromium 실제 사용 폰트를 수집한다."""
import re
import time

REGIONS = ('사이드바', '상단바', '목록 헤더', '목록 데이터')
FAMILIES = {'pretendard', 'pretendard variable'}


def applies(tc):
    title = str(tc.get('title') or '')
    return bool(re.search(r'기본\s*(?:글꼴|폰트)', title) and re.search(r'Pretendard', str(tc.get('expected') or ''), re.I))


def action(tc):
    expected = str(tc.get('expected') or '')
    fallback = bool(re.search(r'fallback|(?:시스템|대체)\s*(?:기본\s*한글\s*)?(?:글꼴|폰트)|(?:글꼴|폰트)(?:이|가)?\s*(?:없는|미설치|미로딩)', expected, re.I))
    return dict(type='verify_default_font', description='기본 글꼴 CSS·실제 렌더링 폰트 확인', fallback_required=fallback)


SNAPSHOT = r'''() => {
 const rendered=e=>{const r=e.getBoundingClientRect(),s=getComputedStyle(e);
   return r.width>0&&r.height>0&&s.visibility!=='hidden'&&s.display!=='none'&&s.opacity!=='0';};
 const visible=e=>{const r=e.getBoundingClientRect();return rendered(e)&&r.bottom>0&&r.right>0&&r.top<innerHeight&&r.left<innerWidth;};
 const roots=(selectors)=>{for(const selector of selectors){const found=[...document.querySelectorAll(selector)].filter(visible);
   if(found.length)return found;}return [];};
 const side=roots(['.sidebar,.wco-sidebar','aside,[role="complementary"]']);
 const top=roots(['.dashboard-app-bar,.wco-app-bar','header,[role="banner"]']);
 const tables=[...document.querySelectorAll('table,[role="table"],[role="grid"]')].filter(visible)
   .filter(t=>[...t.querySelectorAll('th,[role="columnheader"]')].some(e=>e.innerText.replace(/\s/g,'')==='환자명'));
 if(side.length!==1||top.length!==1||tables.length!==1)return {error:'사이드바·상단바·목록 테이블을 각각 하나로 식별하지 못함'};
 const table=tables[0];
 if(table.matches('[aria-busy="true"]')||[...table.querySelectorAll('[role="progressbar"],[aria-busy="true"]')].some(visible))return {error:'목록 로딩 중'};
 // 행 구조는 수평 스크롤 밖의 열도 포함한다. 글꼴 대상은 아래에서 화면 안으로 제한한다.
 const heads=[...table.querySelectorAll('th,[role="columnheader"]')].filter(rendered);
 const data=[...table.querySelectorAll('tbody tr,[role="row"]')].filter(visible).filter(r=>!r.querySelector('th,[role="columnheader"]'))
   .flatMap(r=>{const cells=[...r.querySelectorAll('td,[role="cell"],[role="gridcell"]')].filter(rendered);
     return cells.length===heads.length&&cells.every(c=>!(c.colSpan>1)&&Number(c.getAttribute('aria-colspan')||1)<=1)?cells:[];});
 const path=e=>{const parts=[];for(let p=e;p;p=p.parentElement){let n=1;for(let s=p.previousElementSibling;s;s=s.previousElementSibling)if(s.tagName===p.tagName)n++;
   parts.unshift(p.tagName.toLowerCase()+':nth-of-type('+n+')');}return parts.join('>');};
 const groups={'사이드바':side,'상단바':top,'목록 헤더':heads,'목록 데이터':data};
 const samples=[];
 for(const [region,nodes] of Object.entries(groups)){
   const elements=new Set(nodes.flatMap(n=>[n,...n.querySelectorAll('*')]));
   let count=0;
   for(const e of elements){if(!visible(e)||e.namespaceURI!=='http://www.w3.org/1999/xhtml')continue;
     const text=[...e.childNodes].filter(n=>n.nodeType===Node.TEXT_NODE).map(n=>n.textContent).join('');
     if(!/[가-힣]/.test(text))continue;
     samples.push({region,selector:path(e),css:getComputedStyle(e).fontFamily,
       korean_chars:(text.match(/[가-힣]/g)||[]).length,replacement:/[\uFFFD\u25A1]/.test(text)});count++;
   }
   if(!count)return {error:region+'의 표시된 한글 텍스트 수집 근거 없음'};
 }
 if(samples.length>500)return {error:'글꼴 검증 대상 500개 초과: 범위를 명확하게 지정해야 함'};
 return {samples,font_status:document.fonts.status};
}'''


def collect(page, command):
    state = dict(samples=[], fallback_required=command.get('fallback_required', False))
    session = None
    try:
        page.evaluate('''async () => {
          let timer;try {await Promise.race([document.fonts.ready,new Promise((_,reject)=>{timer=setTimeout(()=>reject(new Error('웹폰트 로딩 대기 시간 초과')),10000)})]);}
          finally {clearTimeout(timer);} }''')
        deadline = time.monotonic() + 5
        while True:
            snapshot = page.evaluate(SNAPSHOT)
            if not snapshot.get('error') or time.monotonic() >= deadline: break
            page.wait_for_timeout(100)
        if snapshot.get('error'): raise ValueError(snapshot['error'])
        state['font_status'] = snapshot['font_status']
        session = page.context.new_cdp_session(page)
        session.send('DOM.enable')
        session.send('CSS.enable')
        document = session.send('DOM.getDocument', {'depth':0})['root']['nodeId']
        for sample in snapshot['samples']:
            node = session.send('DOM.querySelector', {'nodeId':document, 'selector':sample['selector']}).get('nodeId')
            if not node: raise ValueError('글꼴 수집 중 화면 요소가 변경됨')
            usage = session.send('CSS.getPlatformFontsForNode', {'nodeId':node}).get('fonts', [])
            # 환자명과 화면 문자열은 저장하지 않는다.
            state['samples'].append(dict(sample, fonts=[{key:font.get(key) for key in ('familyName','postScriptName','glyphCount','isCustomFont')} for font in usage]))
        state['scope'] = '현재 화면에 표시된 영역별 한글 텍스트'
        state['limitations'] = ['스크린샷의 모든 글자 모양·잘림에 대한 시각적 검증은 포함하지 않음', '웹폰트 미로딩 환경의 대체 글꼴 검증은 별도 TC 필요']
    except Exception as exc:
        state['error'] = '글꼴 근거 수집 실패: ' + str(exc)
    finally:
        if session is not None:
            try: session.detach()
            except Exception: pass
    return state


def verify(state):
    if not state or state.get('error'):
        return 'FAIL', '검증 불가: ' + ((state or {}).get('error') or '기본 글꼴 수집 근거 없음')
    samples = state.get('samples') or []
    if state.get('font_status') != 'loaded' or any(not any(s.get('region') == r for s in samples) for r in REGIONS):
        return 'FAIL', '검증 불가: 글꼴 로딩 완료 또는 영역별 텍스트 근거 부족'
    for sample in samples:
        region = sample['region']
        first = sample.get('css','').split(',')[0].strip().strip('"\'').casefold()
        if first not in FAMILIES:
            return 'FAIL', f'{region} 기본 CSS 글꼴 불일치: {sample.get("css")}'
        fonts = [f for f in sample.get('fonts',[]) if (f.get('glyphCount') or 0)>0]
        if not fonts: return 'FAIL', f'검증 불가: {region} 실제 사용 폰트 근거 없음'
        wrong = [f.get('familyName') or '이름 없음' for f in fonts if str(f.get('familyName') or '').casefold() not in FAMILIES]
        if wrong: return 'FAIL', f'{region} 실제 사용 폰트 불일치: ' + ', '.join(sorted(set(wrong)))
        if sample.get('replacement'): return 'FAIL', f'{region} 텍스트에 대체 문자 또는 빈 네모가 포함됨'
    if state.get('fallback_required'):
        return 'FAIL', '검증 불가: 기본 글꼴 적용은 확인했으나 미로딩 환경의 대체 글꼴 검증은 별도 TC로 분리해야 함'
    return 'PASS', f'사이드바·상단바·목록 헤더·데이터의 한글 텍스트 {len(samples)}개 CSS 및 실제 사용 폰트가 Pretendard 계열로 일치'
