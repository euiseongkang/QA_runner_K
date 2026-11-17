"""상단바 배경·하단 테두리와 현재 페이지명 CSS를 화면별로 검증한다."""
import re
import time
from urllib.parse import urlsplit
from verifications.sidebar_menu_verification import ROUTES
from verifications.sidebar_cgm_verification import SAMPLE as COLOR_SAMPLE, screens


def applies(tc):
    title=str(tc.get('title') or '')
    return bool(re.search(r'상단\s*바',title) and re.search(r'스타일|페이지\s*(?:타이틀|제목)',title))


def requirements(tc):
    text=str(tc.get('expected') or '')
    def one(pattern,label):
        values=set(re.findall(pattern,text,re.I))
        if len(values)!=1:raise ValueError('상단바 '+label+' 기준을 하나만 명시해야 함')
        return next(iter(values))
    background=one(r'배경(?:색)?[^#\n.]{0,25}(#[0-9a-fA-F]{6})(?![0-9a-fA-F])','배경색').upper()
    title_color=one(r'(?:페이지명|타이틀)[^#\n.]{0,100}(#[0-9a-fA-F]{6})(?![0-9a-fA-F])','페이지명 글자색').upper()
    colors={v.upper() for v in re.findall(r'#[0-9a-fA-F]{6}(?![0-9a-fA-F])',text)}
    border_colors=colors-{background,title_color}
    if len(border_colors)!=1 or '구분선' not in text:raise ValueError('상단바 구분선 색상을 #RRGGBB로 하나만 명시해야 함')
    border_width=float(one(r'(?:아래쪽|하단|구분선)[^\d\n.]{0,20}(\d+(?:\.\d+)?)\s*px','하단 구분선 두께(px)'))
    font_size=float(one(r'(?:페이지명|타이틀)[^\d\n.]{0,40}(\d+(?:\.\d+)?)\s*px','페이지명 글자 크기(px)'))
    weight=int(one(r'(?<![\dA-Za-z#])(\d{3})(?![\dA-Za-z])','페이지명 글자 굵기'))
    if border_width<=0 or font_size<=0 or not 100<=weight<=900:raise ValueError('상단바 두께·글자 크기·굵기 범위 오류')
    sequence=screens(tc)
    if not sequence:raise ValueError('상단바를 확인할 메뉴 클릭 절차 없음')
    return dict(screens=sequence,background=background,border_color=next(iter(border_colors)),border_width=border_width,
                title_color=title_color,font_size=font_size,font_weight=weight)


def detail_draft(tc):
    if not applies(tc):return None
    try:wanted=requirements(tc)
    except ValueError:return None
    conditions=[re.sub(r'^\s*\d+[.)]\s*','',line).strip() for line in re.split(r'\n|,(?=\s*(?:시작\s*URL|브라우저))',str(tc.get('precondition') or '')) if line.strip()]
    steps=[]
    for screen in wanted['screens']:
        steps.extend([f'왼쪽 사이드바의 [{screen}] 메뉴를 클릭하고 화면 로딩 완료를 기다린다.',
                      '마우스를 상단바 밖으로 이동하고 기본 스타일 반영을 기다린다.',
                      '상단바 영역의 배경색을 확인한다.',
                      '상단바 자체의 아래쪽 구분선 두께와 색상을 확인한다.',
                      '상단바 왼쪽 페이지명이 현재 화면의 메뉴명과 일치하는지 확인한다.',
                      '페이지명의 글자 크기를 확인한다.',
                      '페이지명의 글자 굵기를 확인한다.',
                      '페이지명의 글자색을 확인한다.'])
    names='·'.join(f'[{name}]' for name in dict.fromkeys(wanted['screens']))
    expected=[f"상단바 배경색은 {wanted['background']}이다.",
              f"상단바 아래쪽 구분선 두께는 {wanted['border_width']:g}px이다.",
              f"상단바 아래쪽 구분선 색상은 {wanted['border_color']}이다.",
              f'상단바 왼쪽 페이지명은 현재 진입한 메뉴명({names})과 일치한다.',
              f"페이지명의 글자 크기는 {wanted['font_size']:g}px이다.",
              f"페이지명의 글자 굵기는 {wanted['font_weight']}이다.",
              f"페이지명의 글자색은 {wanted['title_color']}이다."]
    numbered=lambda rows:'\n'.join(f'{i}. {line}' for i,line in enumerate(rows,1))
    return dict(precondition=numbered(conditions),steps=numbered(steps),expected=numbered(expected))


def actions(tc,parsed):
    result=[];sequence=iter(screens(tc));pending=next(sequence,None)
    for command in parsed:
        if command.get('type')=='click' and command.get('description')==pending:
            result.extend([dict(command,sidebar_menu=pending),dict(type='verify_topbar_style',target=pending,description=pending+' 상단바·페이지명 스타일 수집')])
            pending=next(sequence,None)
    return result or [dict(type='verify_topbar_style',target=None,description='상단바 스타일 수집')]


TITLE_COLOR_SAMPLE=COLOR_SAMPLE.replace("querySelectorAll('span,p,div')","querySelectorAll('span,p,div,a,h1,h2,h3,[role=heading],[data-page-title]')")

SNAPSHOT='''name=>{
 const norm=s=>(s||'').replace(/\\s/g,'');
 const shown=e=>{const r=e.getBoundingClientRect();if(r.width<=0||r.height<=0)return false;for(let p=e;p;p=p.parentElement){const s=getComputedStyle(p);if(s.display==='none'||s.visibility==='hidden'||Number(s.opacity)===0)return false;}return true;};
 let roots=[...document.querySelectorAll('.dashboard-app-bar,.wco-app-bar')].filter(shown);
 if(!roots.length)roots=[...document.querySelectorAll('header,[role="banner"]')].filter(shown);
 if(roots.length!==1)return {error:'상단바를 하나로 식별하지 못함'};
 const top=roots[0],tr=top.getBoundingClientRect();
 const candidates=[...top.querySelectorAll('*')].filter(e=>shown(e)&&norm(e.innerText)===norm(name));
 const leaves=candidates.filter(e=>!candidates.some(other=>other!==e&&e.contains(other)));
 if(leaves.length!==1)return {error:'상단바 현재 페이지명을 하나로 식별하지 못함',matches:leaves.length};
 const title=leaves[0],r=title.getBoundingClientRect(),style=getComputedStyle(title),ts=getComputedStyle(top);
 if(ts.borderImageSource!=='none')return {error:'상단바 border-image 구분선은 단색 판정 불가'};
 const sample=('''+TITLE_COLOR_SAMPLE+''')(top,name);
 if(sample.error)return {error:sample.error.replace('CGM View','상단바')};
 const canvas=document.createElement('canvas');canvas.width=canvas.height=1;const ctx=canvas.getContext('2d',{willReadFrequently:true});
 ctx.fillStyle=sample.background;ctx.fillRect(0,0,1,1);ctx.fillStyle=ts.borderBottomColor;ctx.fillRect(0,0,1,1);
 const border='#'+[...ctx.getImageData(0,0,1,1).data].slice(0,3).map(v=>v.toString(16).padStart(2,'0')).join('').toUpperCase();
 const range=document.createRange();range.selectNodeContents(title);
 return {...sample,title:name,title_left:r.x>=tr.x&&r.x+r.width/2<tr.x+tr.width/2,
 title_unclipped:title.scrollWidth<=title.clientWidth+1&&range.getBoundingClientRect().width<=r.width+1,
 font_size:parseFloat(style.fontSize),font_weight:Number(style.fontWeight),
 border_width:parseFloat(ts.borderBottomWidth),border_style:ts.borderBottomStyle,border_color:border,border_css:ts.borderBottomColor};
}'''


def collect(page,tc,target):
    state=dict(screen=target)
    try:
        state['expected']=requirements(tc)
        if target not in state['expected']['screens']:raise ValueError('상단바 수집 대상 화면 불명확')
        page.mouse.move(page.evaluate('innerWidth-1'),page.evaluate('innerHeight-1'))
        previous,since=None,time.monotonic();deadline=since+5
        while True:
            path=urlsplit(page.url).path.rstrip('/')
            snapshot=dict(error='상단바 대상 화면 진입 근거 없음')
            if path==ROUTES[target]:snapshot=page.evaluate(SNAPSHOT,target)
            now=time.monotonic()
            if snapshot!=previous:previous,since=snapshot,now
            if not snapshot.get('error') and now-since>=.5:
                state.update(snapshot,path=path);break
            if now>=deadline:raise ValueError(snapshot.get('error') or '상단바 스타일이 안정화되지 않음')
            page.wait_for_timeout(100)
    except Exception as exc:state['error']=str(exc)
    return state


def verify(tc,evidence):
    try:wanted=requirements(tc)
    except ValueError as exc:return 'FAIL','검증 불가: '+str(exc)
    if not evidence or len(evidence)!=len(wanted['screens']):return 'FAIL','검증 불가: 화면별 상단바 스타일 근거 부족'
    for screen,state in zip(wanted['screens'],evidence):
        if state.get('error'):return 'FAIL','검증 불가: '+screen+' '+state['error']
        if state.get('screen')!=screen or state.get('path')!=ROUTES[screen] or state.get('title')!=screen:return 'FAIL','검증 불가: 상단바 수집 화면·페이지명 불일치'
        if not state.get('visible') or not state.get('title_unclipped') or not state.get('title_left'):return 'FAIL',screen+' 상단바/왼쪽 페이지명 표시·잘림·가림·위치 불일치'
        for key,actual,label in (('background','background','배경색'),('border_color','border_color','하단 구분선 색'),('title_color','text','페이지명 글자색'),('font_weight','font_weight','페이지명 굵기')):
            if state.get(actual)!=wanted[key]:return 'FAIL',f"{screen} {label} 불일치: 기대 {wanted[key]}, 실제 {state.get(actual)}"
        if state.get('border_style') in (None,'none','hidden') or abs(state.get('border_width',-1)-wanted['border_width'])>.1:return 'FAIL',f"{screen} 하단 구분선 두께/표시 불일치: 기대 {wanted['border_width']:g}px, 실제 {state.get('border_width')}px/{state.get('border_style')}"
        if abs(state.get('font_size',-1)-wanted['font_size'])>.5:return 'FAIL',f"{screen} 페이지명 글자 크기 불일치: 기대 {wanted['font_size']:g}px, 실제 {state.get('font_size')}px"
    return 'PASS',' → '.join(wanted['screens'])+f" 상단바 배경 {wanted['background']}·구분선 {wanted['border_width']:g}px/{wanted['border_color']}·왼쪽 페이지명 {wanted['font_size']:g}px/{wanted['font_weight']}/{wanted['title_color']} 일치"
