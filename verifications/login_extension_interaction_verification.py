"""실제 hover/마우스 누름 유지 상태의 검정 inset overlay를 검증한다."""
import re
import time
from urllib.parse import urlsplit
from verifications.sidebar_menu_verification import ROUTES
from verifications.sidebar_cgm_verification import screens

ALPHA_TOLERANCE=.01  # '약' 표시에 대해 1 percentage point / 8bit 색상 반올림 허용


def applies(tc):
    title=str(tc.get('title') or '')
    return bool(re.search(r'상단\s*바',title) and '로그인 연장' in title and re.search(r'hover|눌림|누름|마우스\s*오버',title,re.I))


def requirements(tc):
    text=str(tc.get('expected') or '')
    def percent(pattern,label):
        values={float(v)/100 for v in re.findall(pattern,text,re.I)}
        if len(values)!=1 or not 0<next(iter(values))<1:raise ValueError(label+'의 검정 덧칠 비율(%)을 하나만 명시해야 함')
        return next(iter(values))
    hover=percent(r'(?:hover|마우스[^\n.]{0,12}올리|마우스\s*오버)[^,\d%\n.]{0,50}(\d+(?:\.\d+)?)\s*%','마우스 오버')
    pressed=percent(r'(?:누르는\s*동안|누름\s*유지|눌림|:active)[^,\d%\n.]{0,50}(\d+(?:\.\d+)?)\s*%','누름 유지')
    if '검정' not in text:raise ValueError('검정 덧칠 기준을 명시해야 함. 단순 밝기 변화와 구분해야 함')
    sequence=screens(tc)
    if not sequence:raise ValueError('버튼 상호작용을 확인할 메뉴 클릭 절차 없음')
    return dict(screens=sequence,hover=hover,pressed=pressed)


def detail_draft(tc):
    if not applies(tc):return None
    try:wanted=requirements(tc)
    except ValueError:return None
    conditions=[re.sub(r'^\s*\d+[.)]\s*','',line).strip() for line in re.split(r'\n|,(?=\s*(?:시작\s*URL|브라우저))',str(tc.get('precondition') or '')) if line.strip()]
    if not any('활성' in line for line in conditions):conditions.append('[로그인 연장] 버튼이 활성 상태이며 다른 팝업에 가려져 있지 않다.')
    steps=[]
    for screen in wanted['screens']:
        steps.extend([f'왼쪽 사이드바의 [{screen}] 메뉴를 클릭하고 화면 로딩 완료를 기다린다.',
                      '마우스를 상단바의 [로그인 연장] 버튼 밖으로 이동하고 버튼의 포커스를 해제해 기본 상태를 확인한다.',
                      '[로그인 연장] 버튼 위에 마우스를 올리고 색상 전환이 완료될 때까지 기다린다.',
                      '마우스 오버 상태의 검정 덧칠 비율을 확인한다.',
                      '버튼 위에서 마우스 왼쪽 버튼을 누른 채 유지하고 색상 전환 완료를 기다린다.',
                      '실제 누름 유지 상태의 검정 덧칠 비율을 확인한다.',
                      '누른 채 포인터를 버튼 밖으로 이동한 다음 마우스를 놓고 버튼 포커스를 해제한다. 버튼 클릭을 완료하지 않는다.'])
    expected=[f"마우스 오버(hover) 상태에서 기본 상태 위에 검정이 약 {wanted['hover']*100:g}% 덧칠된다.",
              f"마우스 왼쪽 버튼을 누르는 동안 검정이 약 {wanted['pressed']*100:g}% 덧칠된다."]
    numbered=lambda rows:'\n'.join(f'{i}. {line}' for i,line in enumerate(rows,1))
    return dict(precondition=numbered(conditions),steps=numbered(steps),expected=numbered(expected))


def actions(tc,parsed):
    result=[];sequence=iter(screens(tc));pending=next(sequence,None)
    for command in parsed:
        if command.get('type')=='click' and command.get('description')==pending:
            result.extend([dict(command,sidebar_menu=pending),dict(type='verify_login_extension_interaction',target=pending,description=pending+' 로그인 연장 버튼 hover·누름 유지 표시 수집')])
            pending=next(sequence,None)
    return result or [dict(type='verify_login_extension_interaction',target=None,description='로그인 연장 버튼 상호작용 수집')]


FIND=r'''() => {
 const shown=e=>{if(!e.getClientRects().length)return false;for(let p=e;p;p=p.parentElement){const s=getComputedStyle(p);if(s.display==='none'||s.visibility==='hidden'||Number(s.opacity)===0)return false;}return true;};
 let roots=[...document.querySelectorAll('.dashboard-app-bar,.wco-app-bar')].filter(shown);
 if(!roots.length)roots=[...document.querySelectorAll('header,[role="banner"]')].filter(shown);
 if(roots.length!==1)throw Error('상단바를 하나로 식별하지 못함');
 const buttons=[...roots[0].querySelectorAll('button,[role="button"]')].filter(e=>shown(e)&&e.innerText.replace(/\s+/g,' ').trim()==='로그인 연장');
 if(buttons.length!==1)throw Error('로그인 연장 버튼을 하나로 식별하지 못함');
 if(buttons[0].disabled||buttons[0].getAttribute('aria-disabled')==='true')throw Error('로그인 연장 버튼이 비활성 상태임');
 return buttons[0];
}'''
SAMPLE=r'''e=>{
 const r=e.getBoundingClientRect(),s=getComputedStyle(e);
 for(let p=e;p;p=p.parentElement){const ps=getComputedStyle(p);if(ps.opacity!=='1'||ps.filter!=='none'||ps.mixBlendMode!=='normal')return {error:'opacity/filter/혼합 효과로 덧칠 비율 분리 불가'};}
 const canvas=document.createElement('canvas');canvas.width=canvas.height=1;const ctx=canvas.getContext('2d',{willReadFrequently:true});
 const rgba=value=>{ctx.clearRect(0,0,1,1);ctx.fillStyle=value;ctx.fillRect(0,0,1,1);return [...ctx.getImageData(0,0,1,1).data];};
 const insets=[];
 for(const shadow of (s.boxShadow==='none'?[]:s.boxShadow.split(/,(?![^()]*\))/))){
  if(!/\binset\b/.test(shadow))continue;
  const color=shadow.match(/rgba?\([^)]*\)|color\([^)]*\)|#[0-9a-fA-F]{3,8}/);
  if(!color)return {error:'inset shadow 색상 파싱 불가'};
  const paint=rgba(color[0]);
  if(paint[3]===0)continue;
  const lengths=[...shadow.replace(color[0],'').matchAll(/(-?\d+(?:\.\d+)?)px/g)].map(m=>Number(m[1]));
  if(lengths.length!==4||lengths[0]!==0||lengths[1]!==0||lengths[2]!==0||lengths[3]<Math.max(r.width,r.height))return {error:'전체 면적을 덮는 단색 inset shadow 근거 없음'};
  if(paint.slice(0,3).some(v=>v!==0))return {error:'검정 이외의 inset 덧칠이 적용됨'};
  insets.push(paint[3]/255);
 }
 for(const pseudo of ['::before','::after']){const ps=getComputedStyle(e,pseudo);if(ps.content!=='none'&&ps.display!=='none'&&Number(ps.opacity)>0&&(rgba(ps.backgroundColor)[3]>0||ps.backgroundImage!=='none'||ps.boxShadow!=='none'))return {error:'가상 요소 덧칠이 있어 inset shadow만으로 판정 불가'};}
 const hit=document.elementFromPoint(r.x+r.width/2,r.y+r.height/2);
 const visible=r.width>0&&r.height>0&&r.x>=0&&r.y>=0&&r.right<=innerWidth&&r.bottom<=innerHeight&&!!hit&&(e.contains(hit)||hit.contains(e));
 return {visible,hover:e.matches(':hover'),active:e.matches(':active'),focus:e.matches(':focus'),
 alpha:1-insets.reduce((n,a)=>n*(1-a),1),box_shadow:s.boxShadow,background:s.backgroundColor,background_image:s.backgroundImage};
}'''


def _stable(page,button,phase):
    previous,since=None,time.monotonic();deadline=since+5
    while True:
        value=button.evaluate(SAMPLE);now=time.monotonic()
        if value.get('error'):raise ValueError(value['error'])
        if value!=previous:previous,since=value,now
        desired=(not value['hover'] and not value['active'] and not value['focus']) if phase=='normal' else (value['hover'] and value['active']==(phase=='pressed'))
        if value['visible'] and desired and now-since>=.35:return value
        if now>=deadline:raise ValueError(phase+' 실제 표시/입력 상태가 안정화되지 않음')
        page.wait_for_timeout(100)


def collect(page,tc,target):
    state=dict(screen=target,activation_count=None,released=False)
    handle=guard=None;holding=False
    try:
        state['expected']=requirements(tc)
        if target not in state['expected']['screens'] or urlsplit(page.url).path.rstrip('/')!=ROUTES[target]:raise ValueError('상호작용 대상 화면 진입 근거 없음')
        handle=page.evaluate_handle(FIND);button=handle.as_element()
        guard=button.evaluate_handle("e=>{const state={button:e,clicks:0};state.listener=()=>state.clicks++;e.addEventListener('click',state.listener,true);return state}")
        outside=(page.evaluate('innerWidth-1'),page.evaluate('innerHeight-1'))
        page.mouse.move(*outside);button.evaluate('e=>e.blur()')
        state['normal']=_stable(page,button,'normal')
        button.hover(timeout=5000);state['hover']=_stable(page,button,'hover')
        holding=True;page.mouse.down(button='left');state['pressed']=_stable(page,button,'pressed')
    except Exception as exc:state['error']=str(exc)
    finally:
        try:
            if holding:
                page.mouse.move(page.evaluate('innerWidth-1'),page.evaluate('innerHeight-1'))
                page.mouse.up(button='left')
            state['released']=True
        except Exception as exc:state['error']=str(exc)
        if handle is not None:
            try:
                state['after_release']=handle.as_element().evaluate(SAMPLE)
                handle.as_element().evaluate('e=>e.blur()')
            except Exception as exc:state['error']=str(exc)
        if guard is not None:
            try:state['activation_count']=guard.evaluate("s=>{s.button.removeEventListener('click',s.listener,true);return s.clicks}")
            except Exception as exc:state['error']=str(exc)
            finally:
                try:guard.dispose()
                except Exception:pass
        if handle is not None:
            try:handle.dispose()
            except Exception:pass
        try:state['path']=urlsplit(page.url).path.rstrip('/')
        except Exception:pass
    return state


def verify(tc,evidence):
    try:wanted=requirements(tc)
    except ValueError as exc:return 'FAIL','검증 불가: '+str(exc)
    if not evidence or len(evidence)!=len(wanted['screens']):return 'FAIL','검증 불가: 화면별 hover/누름 유지 근거 부족'
    for screen,state in zip(wanted['screens'],evidence):
        if state.get('error'):return 'FAIL','검증 불가: '+str(state['error'])
        if state.get('screen')!=screen or state.get('path')!=ROUTES[screen]:return 'FAIL','상호작용 중 화면 변경 또는 근거 순서 불일치'
        if not state.get('released') or state.get('activation_count')!=0:return 'FAIL','마우스 해제 근거가 없거나 로그인 연장 클릭이 발생함'
        normal=state.get('normal') or {}
        if not normal.get('visible') or any(normal.get(key) for key in ('hover','active','focus')) or abs(normal.get('alpha',-1))>1/255:return 'FAIL','기본 상태의 포인터/포커스 해제 또는 덧칠 없음 근거 부족'
        for phase in ('hover','pressed'):
            value=state.get(phase) or {}
            if not value.get('visible') or not value.get('hover') or value.get('active')!=(phase=='pressed'):return 'FAIL',phase+' 실제 포인터/누름 유지 상태 근거 없음'
            if value.get('background')!=normal.get('background') or value.get('background_image')!=normal.get('background_image'):return 'FAIL',phase+' 상태에서 덧칠 이외의 배경색/이미지 변경이 발생함'
            if abs(value.get('alpha',-1)-wanted[phase])>ALPHA_TOLERANCE+1e-9:return 'FAIL',f"{phase} 검정 덧칠 비율 불일치: 기대 약 {wanted[phase]*100:g}%, 실제 {value.get('alpha',-1)*100:.2f}%"
    return 'PASS',' → '.join(wanted['screens'])+f" 실제 hover {wanted['hover']*100:g}%·누름 유지 {wanted['pressed']*100:g}% 검정 inset 덧칠 확인, 클릭 없이 마우스 해제"
