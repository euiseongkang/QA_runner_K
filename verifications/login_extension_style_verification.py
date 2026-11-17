"""상단바 로그인 연장 버튼을 누르지 않고 기본 스타일만 측정한다."""
import re
import time
from urllib.parse import urlsplit
from verifications.sidebar_menu_verification import ROUTES
from verifications.sidebar_cgm_verification import SAMPLE as COLOR_SAMPLE, screens
from verifications.login_extension_verification import requests_click

LABEL='로그인 연장'


def applies(tc):
    title=str(tc.get('title') or '')
    return bool(re.search(r'상단\s*바',title) and '로그인 연장' in title and re.search(r'배경|문구|글자색|색상|테두리|모양|둥글기|크기|굵기',title))


def requirements(tc):
    text=str(tc.get('expected') or '')
    result={}
    def one(pattern,label):
        values=set(re.findall(pattern,text,re.I))
        if len(values)!=1:raise ValueError('로그인 연장 버튼 '+label+' 기준을 하나만 명시해야 함')
        return next(iter(values))
    if '배경' in text:
        result['background']=one(r'배경(?:색)?[^#\n.]{0,25}(#[0-9a-fA-F]{6})(?![0-9a-fA-F])','배경색').upper()
    if '글자색' in text or re.search(r'문구[^#\n.]{0,30}(?:색|#[0-9a-fA-F])',text):
        result['text']=one(r'(?:문구|글자색)[^#\n.]{0,30}(#[0-9a-fA-F]{6})(?![0-9a-fA-F])','문구 색상').upper()
    if '테두리' in text:
        result['border_color']=one(r'테두리[^#\n.]{0,30}(#[0-9a-fA-F]{6})(?![0-9a-fA-F])','테두리 색상').upper()
        result['border_width']=float(one(r'테두리[^\d\n.]{0,15}(\d+(?:\.\d+)?)\s*px','테두리 두께(px)'))
    size_pattern=r'(?:문구(?:의)?\s*(?:글자\s*)?크기(?:는|가)?|글자\s*크기(?:는|가)?|문구(?:는|가)?)\s*(\d+(?:\.\d+)?)\s*px'
    if re.search(size_pattern,text) or re.search(r'글자\s*크기|문구(?:의)?\s*(?:글자\s*)?크기',text):
        result['font_size']=float(one(size_pattern,'문구 글자 크기(px)'))
    if re.search(r'Regular|Medium|SemiBold|굵기',text,re.I):
        weights={int(v) for v in re.findall(r'(?<![\dA-Za-z#])(\d{3})(?![\dA-Za-z])',text)}
        for word,value in (('Regular',400),('Medium',500),('SemiBold',600)):
            if re.search(r'\b'+word+r'\b',text,re.I):weights.add(value)
        if len(weights)!=1 or not 100<=next(iter(weights))<=900:raise ValueError('문구 글자 굵기를 하나만 명시해야 함')
        result['font_weight']=next(iter(weights))
    if re.search(r'모서리|둥글기',text):
        result['radius']=float(one(r'(?:모서리|둥글기)[^\d\n.]{0,20}(\d+(?:\.\d+)?)\s*px','모서리 둥글기(px)'))
    if any(result[key]<=0 for key in ('border_width','font_size') if key in result) or result.get('radius',0)<0:
        raise ValueError('버튼 두께/글자 크기는 양수, 모서리 둥글기는 0 이상이어야 함')
    sequence=screens(tc)
    if not sequence:raise ValueError('버튼 스타일을 확인할 메뉴 클릭 절차 없음')
    if requests_click(tc.get('steps')):
        raise ValueError('버튼 스타일 관찰과 로그인 연장 클릭 동작을 별도 TC로 구분해야 함')
    return dict(screens=sequence,**result)


def detail_draft(tc):
    if not applies(tc):return None
    try:wanted=requirements(tc)
    except ValueError:return None
    conditions=[re.sub(r'^\s*\d+[.)]\s*','',line).strip() for line in re.split(r'\n|,(?=\s*(?:시작\s*URL|브라우저))',str(tc.get('precondition') or '')) if line.strip()]
    steps=[]
    for screen in wanted['screens']:
        steps.extend([f'왼쪽 사이드바의 [{screen}] 메뉴를 클릭하고 화면 로딩 완료를 기다린다.',
                      '상단바 오른쪽의 [로그인 연장] 버튼을 확인한다. 버튼은 클릭하지 않는다.',
                      '마우스를 [로그인 연장] 버튼 밖으로 이동하고 기본 스타일 반영을 기다린다.',
                      '버튼 문구를 확인한다.'])
        for key,line in (('background','버튼 클릭 영역의 배경색을 확인한다.'),('text','버튼 문구의 글자색을 확인한다.'),
                         ('border_width','버튼의 위·오른쪽·아래·왼쪽 테두리 두께와 색상을 확인한다.'),
                         ('font_size','버튼 문구의 글자 크기를 확인한다.'),('font_weight','버튼 문구의 글자 굵기를 확인한다.'),
                         ('radius','버튼 네 모서리의 둥글기를 각각 확인한다.')):
            if key in wanted:steps.append(line)
    expected=['상단바 오른쪽에 [로그인 연장] 버튼이 표시된다.',
              '버튼 문구는 ‘로그인 연장’과 정확히 일치하며, 두 단어 사이의 공백은 한 칸이고 다른 불필요한 공백이나 오탈자가 없다.']
    for key,line in (('background','버튼 배경색은 {value}이다.'),('text','버튼 문구의 글자색은 {value}이다.'),
                     ('border_width','버튼의 네 방향 테두리 두께는 각각 {value:g}px이다.'),('border_color','버튼의 네 방향 테두리 색상은 각각 {value}이다.'),
                     ('font_size','버튼 문구의 글자 크기는 {value:g}px이다.'),('font_weight','버튼 문구의 글자 굵기는 {value}이다.'),
                     ('radius','버튼 네 모서리의 둥글기는 각각 {value:g}px이다.')):
        if key in wanted:expected.append(line.format(value=wanted[key]))
    numbered=lambda rows:'\n'.join(f'{i}. {line}' for i,line in enumerate(rows,1))
    return dict(precondition=numbered(conditions),steps=numbered(steps),expected=numbered(expected))


def actions(tc,parsed):
    result=[];sequence=iter(screens(tc));pending=next(sequence,None)
    for command in parsed:
        if command.get('type')=='click' and command.get('description')==pending:
            result.extend([dict(command,sidebar_menu=pending),dict(type='verify_login_extension_style',target=pending,description=pending+' 로그인 연장 버튼 기본 스타일 수집')])
            pending=next(sequence,None)
    return result or [dict(type='verify_login_extension_style',target=None,description='로그인 연장 버튼 스타일 수집')]


SNAPSHOT='''checks => {
 checks=checks||{colors:true};
 const rect=e=>{const r=e.getBoundingClientRect();return {x:r.x,y:r.y,right:r.right,bottom:r.bottom,width:r.width,height:r.height};};
 const shown=e=>{const r=rect(e);if(r.width<=0||r.height<=0)return false;for(let p=e;p;p=p.parentElement){const s=getComputedStyle(p);if(s.display==='none'||s.visibility==='hidden'||Number(s.opacity)===0)return false;}return true;};
 const full=e=>{if(!shown(e))return false;const r=rect(e);if(r.x<0||r.y<0||r.right>innerWidth||r.bottom>innerHeight)return false;
  for(let p=e.parentElement;p;p=p.parentElement){const s=getComputedStyle(p),q=rect(p);if(/hidden|clip|auto|scroll/.test(s.overflowX)&&(r.x<q.x-.5||r.right>q.right+.5))return false;if(/hidden|clip|auto|scroll/.test(s.overflowY)&&(r.y<q.y-.5||r.bottom>q.bottom+.5))return false;}
  const hit=document.elementFromPoint(r.x+r.width/2,r.y+r.height/2);return !!hit&&(e.contains(hit)||hit.contains(e));};
 const norm=s=>(s||'').replace(/\\s/g,'');
 let roots=[...document.querySelectorAll('.dashboard-app-bar,.wco-app-bar')].filter(shown);
 if(!roots.length)roots=[...document.querySelectorAll('header,[role="banner"]')].filter(shown);
 if(roots.length!==1)return {error:'상단바를 하나로 식별하지 못함'};
 const top=roots[0],buttons=[...top.querySelectorAll('button,[role="button"]')].filter(e=>shown(e)&&norm(e.innerText)==='로그인연장');
 if(buttons.length!==1)return {error:'상단바 로그인 연장 버튼을 하나로 식별하지 못함'};
 const button=buttons[0],style=getComputedStyle(button),r=rect(button),tr=rect(top);
 const labels=[button,...button.querySelectorAll('*')].filter(e=>shown(e)&&norm(e.innerText)==='로그인연장');
 const label=labels.find(e=>!labels.some(other=>other!==e&&e.contains(other)))||button;
 const labelStyle=getComputedStyle(label),range=document.createRange();range.selectNodeContents(label);
 let sample={visible:full(button)&&full(label)&&label.scrollWidth<=label.clientWidth+1&&range.getBoundingClientRect().width<=rect(label).width+1,hovered:button.matches(':hover')};
 if(checks.colors){
  if(style.borderImageSource!=='none')return {error:'border-image 테두리는 단색 판정 불가'};
  sample=(''' + COLOR_SAMPLE + ''')(button,'로그인 연장');
  if(sample.error)return {error:sample.error.replace('CGM View','로그인 연장 버튼')};
 }
 const state={...sample,label:button.innerText.replace(/\\s+/g,' ').trim(),label_exact:label.textContent,
 right:r.x+r.width/2>=tr.x+tr.width/2&&r.right<=tr.right,
 font_size:parseFloat(labelStyle.fontSize),font_weight:Number(labelStyle.fontWeight),
 radii:[style.borderTopLeftRadius,style.borderTopRightRadius,style.borderBottomRightRadius,style.borderBottomLeftRadius]};
 if(checks.colors){
  const canvas=document.createElement('canvas');canvas.width=canvas.height=1;const ctx=canvas.getContext('2d',{willReadFrequently:true});
  const color=value=>{ctx.clearRect(0,0,1,1);ctx.fillStyle=sample.background;ctx.fillRect(0,0,1,1);ctx.fillStyle=value;ctx.fillRect(0,0,1,1);return '#'+[...ctx.getImageData(0,0,1,1).data].slice(0,3).map(v=>v.toString(16).padStart(2,'0')).join('').toUpperCase();};
  state.borders=['Top','Right','Bottom','Left'].map(side=>({side,width:parseFloat(style['border'+side+'Width']),style:style['border'+side+'Style'],color:color(style['border'+side+'Color']),css:style['border'+side+'Color']}));
 }
 return state;
}'''


def collect(page,tc,target):
    state=dict(screen=target)
    try:
        state['expected']=requirements(tc)
        if target not in state['expected']['screens']:raise ValueError('버튼 스타일 확인 화면 불명확')
        page.mouse.move(page.evaluate('innerWidth-1'),page.evaluate('innerHeight-1'))
        previous,since=None,time.monotonic();deadline=since+5
        while True:
            path=urlsplit(page.url).path.rstrip('/')
            snapshot=page.evaluate(SNAPSHOT,dict(colors=any(key in state['expected'] for key in ('background','text','border_color')))) if path==ROUTES[target] else dict(error='버튼 스타일 대상 화면 진입 근거 없음')
            now=time.monotonic()
            if snapshot!=previous:previous,since=snapshot,now
            if not snapshot.get('error') and now-since>=.5:
                state.update(snapshot,path=path);break
            if now>=deadline:raise ValueError(snapshot.get('error') or '로그인 연장 버튼 스타일이 안정화되지 않음')
            page.wait_for_timeout(100)
    except Exception as exc:state['error']=str(exc)
    return state


def verify(tc,evidence):
    try:wanted=requirements(tc)
    except ValueError as exc:return 'FAIL','검증 불가: '+str(exc)
    if not evidence or len(evidence)!=len(wanted['screens']):return 'FAIL','검증 불가: 화면별 로그인 연장 버튼 스타일 근거 부족'
    for screen,state in zip(wanted['screens'],evidence):
        if state.get('error'):return 'FAIL','검증 불가: '+screen+' '+state['error']
        if state.get('screen')!=screen or state.get('path')!=ROUTES[screen]:return 'FAIL','검증 불가: 버튼 스타일 수집 화면·순서 불일치'
        if state.get('label')!=LABEL or not state.get('visible') or not state.get('right') or state.get('hovered'):return 'FAIL','상단바 오른쪽 로그인 연장 버튼의 기본 문구/표시/위치 근거 부족'
        if state.get('label_exact')!=LABEL:
            return 'FAIL','로그인 연장 버튼 문구의 오탈자·불필요한 공백 또는 띄어쓰기 불일치'
        for key,label in (('background','배경색'),('text','글자색')):
            if key in wanted and state.get(key)!=wanted[key]:return 'FAIL',f"{screen} 로그인 연장 버튼 {label} 불일치: 기대 {wanted[key]}, 실제 {state.get(key)}"
        if 'font_size' in wanted and abs(state.get('font_size',-1)-wanted['font_size'])>.5:
            return 'FAIL',f"버튼 문구 글자 크기 불일치: 기대 {wanted['font_size']:g}px, 실제 {state.get('font_size')}px"
        if 'font_weight' in wanted and state.get('font_weight')!=wanted['font_weight']:
            return 'FAIL',f"버튼 문구 글자 굵기 불일치: 기대 {wanted['font_weight']}, 실제 {state.get('font_weight')}"
        if 'radius' in wanted:
            radii=state.get('radii') or []
            if len(radii)!=4 or any(not re.fullmatch(r'\d+(?:\.\d+)?px',r) or abs(float(r[:-2])-wanted['radius'])>.1 for r in radii):
                return 'FAIL',f"버튼 모서리 둥글기 불일치: 기대 각각 {wanted['radius']:g}px, 실제 {radii}"
        if 'border_width' not in wanted:
            continue
        borders=state.get('borders') or []
        if [b.get('side') for b in borders]!=['Top','Right','Bottom','Left']:return 'FAIL','검증 불가: 네 방향 테두리 근거 부족'
        for border in borders:
            if border.get('style') in (None,'none','hidden') or abs(border.get('width',-1)-wanted['border_width'])>.1:
                return 'FAIL',f"로그인 연장 버튼 {border['side']} 테두리 두께/표시 불일치: 기대 {wanted['border_width']:g}px, 실제 {border.get('width')}px/{border.get('style')}"
            if border.get('color')!=wanted['border_color']:return 'FAIL',f"로그인 연장 버튼 {border['side']} 테두리 색 불일치: 기대 {wanted['border_color']}, 실제 {border.get('color')}"
    return 'PASS',' → '.join(wanted['screens'])+' 로그인 연장 버튼 문구 및 TC에 명시된 스타일 기준 일치: '+', '.join(f'{key}={value}' for key,value in wanted.items() if key!='screens')
