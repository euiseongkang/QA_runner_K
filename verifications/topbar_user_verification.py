"""로그인 세션과 사용자 이름/직군을 대조하고 이름 스타일·펼침 아이콘을 검증한다."""
import re
import time
from urllib.parse import urlsplit
from verifications.sidebar_menu_verification import ROUTES
from verifications.sidebar_cgm_verification import screens


def applies(tc):
    title=str(tc.get('title') or '')
    return bool(re.search(r'상단\s*바',title) and re.search(r'사용자\s*이름',title))


def requirements(tc):
    text=str(tc.get('expected') or '')
    sizes={float(v) for v in re.findall(r'(\d+(?:\.\d+)?)\s*px',text)}
    colors={v.upper() for v in re.findall(r'#[0-9a-fA-F]{6}(?![0-9a-fA-F])',text)}
    if len(sizes)!=1 or min(sizes)<=0 or len(colors)!=1:raise ValueError('사용자 이름의 글자 크기(px)와 색상(#RRGGBB)을 하나씩 명시해야 함')
    if not re.search(r'직군',text) or not re.search(r'펼침|화살표|arrow|chevron',text,re.I):raise ValueError('계정 이름·직군 형식과 오른쪽 펼침 아이콘을 명시해야 함')
    sequence=screens(tc)
    if not sequence:raise ValueError('사용자 이름을 확인할 메뉴 클릭 절차 없음')
    scope='both' if re.search(r'이름과\s*직군(?:의)?\s*(?:글자|모두|각각)|이름·직군(?:의)?\s*글자',text) else 'name'
    return dict(screens=sequence,font_size=next(iter(sizes)),color=next(iter(colors)),scope=scope)


def detail_draft(tc):
    if not applies(tc):return None
    try:wanted=requirements(tc)
    except ValueError:return None
    conditions=[re.sub(r'^\s*\d+[.)]\s*','',line).strip() for line in re.split(r'\n|,(?=\s*(?:시작\s*URL|브라우저))',str(tc.get('precondition') or '')) if line.strip()]
    if not any('계정의 이름과 직군' in line for line in conditions):conditions.append('로그인한 계정의 이름과 직군을 확인할 수 있다.')
    steps=[]
    target='이름과 직군' if wanted['scope']=='both' else '이름'
    for screen in wanted['screens']:
        steps.extend([f'왼쪽 사이드바의 [{screen}] 메뉴를 클릭하고 화면 로딩 완료를 기다린다.',
                      '상단바 오른쪽 사용자 영역의 이름과 직군을 로그인한 계정 정보와 비교한다.',
                      '이름 다음에 공백을 두고 직군이 표시되는지 확인한다.',
                      f'{target} 부분의 실제 글자 크기와 글자색을 확인한다.',
                      '직군 오른쪽의 펼침 아이콘이 표시되는지 확인한다. 사용자 메뉴는 클릭하지 않는다.'])
    expected=['상단바 오른쪽 사용자 영역의 이름과 직군이 로그인한 계정 정보와 각각 일치한다.',
              '사용자 문구가 ‘이름 직군’ 순서로 표시되며 두 항목 사이에 공백이 있다.',
              f"{target}의 글자 크기는 {wanted['font_size']:g}px이다.",
              f"{target}의 글자색은 {wanted['color']}이다.",
              '직군 오른쪽에 펼침 아이콘이 숨김이나 잘림 없이 표시된다.']
    numbered=lambda rows:'\n'.join(f'{i}. {line}' for i,line in enumerate(rows,1))
    return dict(precondition=numbered(conditions),steps=numbered(steps),expected=numbered(expected))


def actions(tc,parsed):
    result=[];sequence=iter(screens(tc));pending=next(sequence,None)
    for command in parsed:
        if command.get('type')=='click' and command.get('description')==pending:
            result.extend([dict(command,sidebar_menu=pending),dict(type='verify_topbar_user',target=pending,description=pending+' 사용자 계정 대조·이름 스타일·펼침 아이콘 수집')])
            pending=next(sequence,None)
    return result or [dict(type='verify_topbar_user',target=None,description='상단바 사용자 이름 검증')]


REFERENCE=r'''() => {
 // 인증 저장소 전체나 토큰을 반환하지 않고 비교에 필요한 두 필드만 읽는다.
 let data;try{data=JSON.parse(localStorage.getItem('auth-store')||'null')}catch{return {error:'로그인 계정 저장 정보 형식 오류'}};
 const me=data?.state?.me;
 if(!me||typeof me.userName!=='string'||typeof me.userTypeName!=='string'||!me.userName.trim()||!me.userTypeName.trim())return {error:'로그인 계정의 이름·직군 기준 정보 없음'};
 return {source:'login_session.auth-store.state.me',name:me.userName.trim(),role:me.userTypeName.trim()};
}'''
SNAPSHOT=r'''() => {
 const norm=s=>(s||'').replace(/ /g,' ').replace(/\s+/g,' ').trim();
 const rect=e=>{const r=e.getBoundingClientRect();return {x:r.x,y:r.y,width:r.width,height:r.height,right:r.right,bottom:r.bottom};};
 const shown=e=>{if(!e||!e.getClientRects().length)return false;for(let p=e;p;p=p.parentElement){const s=getComputedStyle(p);if(s.display==='none'||s.visibility==='hidden'||Number(s.opacity)===0)return false;}return true;};
 const full=e=>{if(!shown(e))return false;const r=rect(e);if(r.width<=0||r.height<=0||r.x<0||r.y<0||r.right>innerWidth||r.bottom>innerHeight)return false;
 for(let p=e.parentElement;p;p=p.parentElement){const s=getComputedStyle(p),q=rect(p);if(/hidden|clip|auto|scroll/.test(s.overflowX)&&(r.x<q.x-.5||r.right>q.right+.5))return false;if(/hidden|clip|auto|scroll/.test(s.overflowY)&&(r.y<q.y-.5||r.bottom>q.bottom+.5))return false;}
 const hit=document.elementFromPoint(r.x+r.width/2,r.y+r.height/2);return !!hit&&(e.contains(hit)||hit.contains(e));};
 let roots=[...document.querySelectorAll('.dashboard-app-bar,.wco-app-bar')].filter(shown);
 if(!roots.length)roots=[...document.querySelectorAll('header,[role="banner"]')].filter(shown);
 if(roots.length!==1)return {error:'상단바를 하나로 식별하지 못함'};
 const top=roots[0],tr=rect(top),controls=[...top.querySelectorAll('button,[role="button"]')].filter(shown);
 const candidates=controls.filter(e=>/사용자|프로필|계정|profile|user menu/i.test(e.getAttribute('aria-label')||'')||
   [...e.querySelectorAll('img,svg')].some(n=>/arrow|chevron|펼침|expand/i.test((n.getAttribute('alt')||'')+' '+(n.getAttribute('aria-label')||'')))||
   [...e.querySelectorAll('p')].some(p=>[...p.querySelectorAll('span')].filter(n=>shown(n)&&norm(n.innerText)).length>=2));
 if(candidates.length!==1)return {error:'상단바 사용자 메뉴를 하나로 식별하지 못함',matches:candidates.length};
 const control=candidates[0],containers=[...control.querySelectorAll('p')].filter(shown);
 if(containers.length>1)return {error:'사용자 이름·직군 영역이 여러 개임'};
 const container=containers[0]||control;
 const spans=[...container.querySelectorAll('span')].filter(e=>shown(e)&&norm(e.innerText));
 const leaves=spans.filter(e=>!spans.some(other=>other!==e&&e.contains(other)));
 if(leaves.length<2)return {error:'이름과 직군의 표시 요소를 각각 식별하지 못함'};
 const name=leaves[0],role=leaves[leaves.length-1];
 const canvas=document.createElement('canvas');canvas.width=canvas.height=1;const ctx=canvas.getContext('2d',{willReadFrequently:true});
 const sample=e=>{const r=rect(e),s=getComputedStyle(e),range=document.createRange();range.selectNodeContents(e);
  for(let p=e;p;p=p.parentElement){const ps=getComputedStyle(p);if(ps.opacity!=='1'||ps.filter!=='none'||ps.mixBlendMode!=='normal')return {error:'문구 표시 효과로 단색 판정 불가'};}
  ctx.clearRect(0,0,1,1);ctx.fillStyle=s.color;ctx.fillRect(0,0,1,1);const rgba=[...ctx.getImageData(0,0,1,1).data];
  if(rgba[3]!==255||s.webkitTextFillColor!==s.color)return {error:'투명/별도 채움 글자색 판정 불가'};
  return {text:norm(e.innerText),font_size:parseFloat(s.fontSize),color:'#'+rgba.slice(0,3).map(v=>v.toString(16).padStart(2,'0')).join('').toUpperCase(),visible:full(e)&&e.scrollWidth<=e.clientWidth+1&&range.getBoundingClientRect().width<=r.width+1};};
 let icons=[...control.querySelectorAll('img,svg')].filter(e=>/arrow|chevron|펼침|expand/i.test((e.getAttribute('alt')||'')+' '+(e.getAttribute('aria-label')||'')));
 if(!icons.length)icons=[...control.querySelectorAll('svg')].filter(e=>shown(e)&&rect(e).x>=rect(role).right-.5);
 const icon=icons.length===1?icons[0]:null;
 return {display:norm(container.innerText),name:sample(name),role:sample(role),visible:full(control),
 right:rect(control).x+rect(control).width/2>=tr.x+tr.width/2,
 arrow:{count:icons.length,visible:!!icon&&full(icon),right:!!icon&&rect(icon).x>=rect(role).right-.5,
 aligned:!!icon&&(rect(icon).y+rect(icon).height/2)>=Math.min(rect(name).y,rect(role).y)&&
 (rect(icon).y+rect(icon).height/2)<=Math.max(rect(name).bottom,rect(role).bottom),
 within:!!icon&&rect(icon).x>=rect(control).x&&rect(icon).right<=rect(control).right&&rect(icon).y>=rect(control).y&&rect(icon).bottom<=rect(control).bottom,
 loaded:!!icon&&(icon.tagName.toLowerCase()!=='img'||(icon.complete&&icon.naturalWidth>0&&icon.naturalHeight>0))}};
}'''


def collect(page,tc,target):
    state=dict(screen=target)
    try:
        state['expected']=requirements(tc)
        if target not in state['expected']['screens']:raise ValueError('사용자 이름 확인 화면 불명확')
        page.mouse.move(page.evaluate('innerWidth-1'),page.evaluate('innerHeight-1'))
        previous,since=None,time.monotonic();deadline=since+5
        while True:
            path=urlsplit(page.url).path.rstrip('/')
            snapshot=dict(error='사용자 이름 대상 화면 진입 근거 없음')
            if path==ROUTES[target]:
                reference=page.evaluate(REFERENCE)
                snapshot=dict(error=reference['error']) if reference.get('error') else dict(page.evaluate(SNAPSHOT),reference=reference)
            now=time.monotonic()
            if snapshot!=previous:previous,since=snapshot,now
            if not snapshot.get('error') and now-since>=.5:
                state.update(snapshot,path=path);break
            if now>=deadline:raise ValueError(snapshot.get('error') or '사용자 이름 표시가 안정화되지 않음')
            page.wait_for_timeout(100)
    except Exception as exc:state['error']=str(exc)
    return state


def verify(tc,evidence):
    try:wanted=requirements(tc)
    except ValueError as exc:return 'FAIL','검증 불가: '+str(exc)
    if not evidence or len(evidence)!=len(wanted['screens']):return 'FAIL','검증 불가: 화면별 사용자 이름 근거 부족'
    norm=lambda s:re.sub(r'\s+',' ',str(s or '').replace('\u00a0',' ')).strip()
    for screen,state in zip(wanted['screens'],evidence):
        if state.get('error'):return 'FAIL','검증 불가: '+state['error']
        if state.get('screen')!=screen or state.get('path')!=ROUTES[screen]:return 'FAIL','검증 불가: 사용자 이름 수집 화면·순서 불일치'
        reference=state.get('reference') or {}
        if reference.get('source')!='login_session.auth-store.state.me' or not norm(reference.get('name')) or not norm(reference.get('role')):return 'FAIL','검증 불가: 로그인 계정의 이름·직군 기준 정보 없음'
        if not state.get('visible') or not state.get('right'):return 'FAIL','상단바 오른쪽 사용자 영역이 숨김·잘림·가림 상태이거나 위치가 다름'
        for key,label in (('name','이름'),('role','직군')):
            actual=state.get(key) or {}
            if actual.get('error') or not actual.get('visible'):return 'FAIL','검증 불가: 사용자 '+label+' 표시/스타일 근거 부족'
            if norm(actual.get('text'))!=norm(reference[key]):return 'FAIL',f"로그인 계정 {label}과 표시 문구 불일치: 기대 {reference[key]}, 실제 {actual.get('text')}"
        expected_display=norm(reference['name'])+' '+norm(reference['role'])
        if state.get('display')!=expected_display:return 'FAIL',f"사용자 문구 형식 불일치: 기대 {expected_display}, 실제 {state.get('display')}"
        for key in (('name','role') if wanted['scope']=='both' else ('name',)):
            actual=state[key];label='이름' if key=='name' else '직군'
            if abs(actual.get('font_size',-1)-wanted['font_size'])>.5:return 'FAIL',f"사용자 {label} 글자 크기 불일치: 기대 {wanted['font_size']:g}px, 실제 {actual.get('font_size')}px"
            if actual.get('color')!=wanted['color']:return 'FAIL',f"사용자 {label} 글자색 불일치: 기대 {wanted['color']}, 실제 {actual.get('color')}"
        arrow=state.get('arrow') or {}
        if arrow.get('count')!=1 or not arrow.get('visible') or not arrow.get('right') or not arrow.get('aligned') or not arrow.get('within') or not arrow.get('loaded'):return 'FAIL','사용자 직군 오른쪽 펼침 아이콘의 표시·위치·로딩 근거 없음'
    return 'PASS',' → '.join(wanted['screens'])+f" 로그인 계정 이름·직군 문구/순서 일치, {'이름과 직군' if wanted['scope']=='both' else '이름'} {wanted['font_size']:g}px/{wanted['color']} 및 오른쪽 펼침 아이콘 확인"
