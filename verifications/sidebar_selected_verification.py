"""현재 경로의 선택 메뉴 배경·글자·SVG 페인트·글자 크기/굵기 검증."""
import re
import time
from urllib.parse import urlsplit
from verifications.sidebar_menu_verification import ROUTES
from verifications.sidebar_hover_verification import FIND
from verifications.sidebar_cgm_verification import SAMPLE as COLOR_SAMPLE, screens


def applies(tc):
    title = str(tc.get('title') or '')
    return bool(re.search(r'사이드\s*바', title) and re.search(r'선택(?:된)?\s*메뉴', title) and '색상' in title)


def subject_error(tc):
    if applies(tc) and re.search(r'CGM\s*View', str(tc.get('expected') or ''), re.I) and not re.search(r'선택(?:된)?\s*메뉴', str(tc.get('expected') or '')):
        return '제목은 선택된 메뉴 색상인데 본문은 CGM View 강조를 검증합니다. 선택 메뉴의 원래 배경색·글자/아이콘 색·글자 크기·굵기 기준을 복원해야 합니다.'
    return None


def requirements(tc):
    if subject_error(tc): raise ValueError(subject_error(tc))
    text = str(tc.get('expected') or '')
    result = {}
    for key, pattern in (('background', r'배경(?:색)?'), ('text', r'글자(?:색)?(?:[·ㆍ/\s]*아이콘(?:색)?)?'), ('icon', r'아이콘(?:색)?')):
        colors = {v.upper() for v in re.findall(pattern+r'[^#\n.]{0,25}(#[0-9a-fA-F]{6})(?![0-9a-fA-F])', text)}
        if len(colors) != 1: raise ValueError('선택 메뉴의 '+key+' 색상을 #RRGGBB로 하나만 명시해야 함')
        result[key] = next(iter(colors))
    sizes = {float(v) for v in re.findall(r'(\d+(?:\.\d+)?)\s*px', text)}
    weights = {int(v) for v in re.findall(r'(?<![\dA-Za-z#])(\d{3})(?![\dA-Za-z])', text)}
    if len(sizes) != 1 or len(weights) != 1 or min(sizes)<=0 or not 100<=next(iter(weights))<=900:
        raise ValueError('선택 메뉴 글자 크기(px)와 굵기(100~900)를 하나씩 명시해야 함')
    sequence = screens(tc)
    if not sequence: raise ValueError('선택할 메뉴 클릭 절차 없음')
    return dict(**result, font_size=next(iter(sizes)), font_weight=next(iter(weights)), screens=sequence)


def detail_draft(tc):
    if not applies(tc): return None
    try: wanted = requirements(tc)
    except ValueError: return None
    conditions = [re.sub(r'^\s*\d+[.)]\s*', '', line).strip() for line in re.split(r'\n|,(?=\s*(?:시작\s*URL|브라우저))', str(tc.get('precondition') or '')) if line.strip()]
    if not any('펼쳐' in line for line in conditions): conditions.append('왼쪽 사이드바가 펼쳐져 메뉴명과 아이콘이 표시된다.')
    steps = []
    for screen in wanted['screens']:
        steps.extend([f'왼쪽 사이드바의 [{screen}] 메뉴를 클릭하고 화면 로딩 완료를 기다린다.',
                      f'마우스를 [{screen}] 메뉴 밖으로 이동하고 선택 상태의 기본 스타일 반영을 기다린다.',
                      f'현재 화면의 선택된 [{screen}] 메뉴 클릭 영역의 배경색을 확인한다.',
                      f'선택된 [{screen}] 메뉴명의 글자색을 확인한다.',
                      f'선택된 [{screen}] 메뉴 아이콘의 색을 확인한다.',
                      f'선택된 [{screen}] 메뉴명의 글자 크기를 확인한다.',
                      f'선택된 [{screen}] 메뉴명의 글자 굵기를 확인한다.'])
    expected = [f"현재 화면의 선택된 메뉴 배경색은 {wanted['background']}이다.",
                f"선택된 메뉴의 글자색은 {wanted['text']}이다.",f"선택된 메뉴의 아이콘 색은 {wanted['icon']}이다.",
                f"선택된 메뉴명의 글자 크기는 {wanted['font_size']:g}px이다.",
                f"선택된 메뉴명의 글자 굵기는 {wanted['font_weight']}이다."]
    numbered = lambda rows: '\n'.join(f'{i}. {line}' for i, line in enumerate(rows, 1))
    return dict(precondition=numbered(conditions), steps=numbered(steps), expected=numbered(expected))


def actions(tc, parsed):
    result = []
    sequence = iter(screens(tc))
    pending = next(sequence, None)
    for command in parsed:
        if command.get('type') == 'click' and command.get('description') == pending:
            result.extend([command, dict(type='verify_sidebar_selected', target=command['description'],
                                        description=command['description']+' 선택 메뉴 스타일 수집')])
            pending = next(sequence, None)
    return result or [dict(type='verify_sidebar_selected',target=None,description='선택 메뉴 스타일 수집')]


SAMPLE = '(e,name)=>{const state=('+COLOR_SAMPLE+''')(e,name);
 if(state.error)return state;
 const norm=s=>(s||'').replace(/\s/g,'');
 const labels=[e,...e.querySelectorAll('span,p,div')].filter(n=>norm(n.innerText)===norm(name));
 const label=labels.find(n=>!labels.some(other=>other!==n&&n.contains(other)))||e;
 const style=getComputedStyle(label);
 const canvas=document.createElement('canvas');canvas.width=canvas.height=1;const ctx=canvas.getContext('2d',{willReadFrequently:true});
 const paint=color=>{ctx.clearRect(0,0,1,1);ctx.fillStyle=color;ctx.fillRect(0,0,1,1);const v=[...ctx.getImageData(0,0,1,1).data];return v[3]===255?'#'+v.slice(0,3).map(n=>n.toString(16).padStart(2,'0')).join('').toUpperCase():null;};
 const visible=n=>{if(!n.getClientRects().length)return false;for(let p=n;p&&p!==e;p=p.parentElement){const s=getComputedStyle(p);if(s.display==='none'||s.visibility==='hidden'||Number(s.opacity)!==1||s.filter!=='none'||s.mixBlendMode!=='normal')return false;}return true;};
 const icons=[...e.querySelectorAll('svg')].filter(n=>visible(n)&&!n.closest('.sidebar-menu-arrow'));
 const paints=[];
 for(const icon of icons){
  const shapes=[...icon.querySelectorAll('path,rect,circle,ellipse,line,polyline,polygon,use')].filter(n=>visible(n)&&!n.closest('defs,clipPath,mask,symbol'));
  for(const shape of shapes){const s=getComputedStyle(shape);let box;try{box=shape.getBBox()}catch{return {...state,error:'아이콘 도형 측정 불가'}}
   if(box.width===0&&box.height===0)continue;
   if(s.fill!=='none'){if(Number(s.fillOpacity)!==1)return {...state,error:'아이콘 fill 투명도 판정 불가'};paints.push(paint(s.fill));}
   if(s.stroke!=='none'&&parseFloat(s.strokeWidth)>0){if(Number(s.strokeOpacity)!==1)return {...state,error:'아이콘 stroke 투명도 판정 불가'};paints.push(paint(s.stroke));}
  }
 }
 return {...state,font_size:parseFloat(style.fontSize),font_weight:Number(style.fontWeight),icon_count:icons.length,icon_paints:paints,
 href:e.getAttribute('href'),aria_current:e.getAttribute('aria-current'),aria_selected:e.getAttribute('aria-selected')};
}'''


def collect(page, tc, target):
    state = dict(screen=target)
    try:
        state['expected'] = requirements(tc)
        if target not in ROUTES: raise ValueError('선택 메뉴 수집 대상 없음')
        page.mouse.move(page.evaluate('innerWidth-1'), page.evaluate('innerHeight-1'))
        deadline = time.monotonic()+5
        previous, since = None, time.monotonic()
        while True:
            path = urlsplit(page.url).path.rstrip('/')
            snapshot = dict(error='선택 메뉴 화면 진입 근거 없음')
            if path == ROUTES[target]:
                try:
                    handle = page.evaluate_handle(FIND,target)
                    try: snapshot = handle.as_element().evaluate(SAMPLE,target)
                    finally: handle.dispose()
                except Exception as exc: snapshot = dict(error=str(exc).replace('마우스 오버 대상 메뉴','선택 메뉴'))
            if snapshot.get('error'):
                snapshot['error'] = snapshot['error'].replace('CGM View', target+' 선택 메뉴')
            now=time.monotonic()
            if snapshot!=previous: previous,since=snapshot,now
            if not snapshot.get('error') and now-since>=.5:
                state.update(snapshot,path=path);break
            if now>=deadline: raise ValueError(snapshot.get('error') or '선택 메뉴 스타일이 안정화되지 않음')
            page.wait_for_timeout(100)
    except Exception as exc: state['error']=str(exc)
    return state


def verify(tc, evidence):
    try: wanted=requirements(tc)
    except ValueError as exc: return 'FAIL','검증 불가: '+str(exc)
    if not evidence or len(evidence)!=len(wanted['screens']):return 'FAIL','검증 불가: 화면별 선택 메뉴 스타일 수집 근거 부족'
    for screen,state in zip(wanted['screens'],evidence):
        if state.get('error'):return 'FAIL','검증 불가: '+screen+' '+state['error']
        if state.get('screen')!=screen or state.get('path')!=ROUTES[screen]:return 'FAIL','검증 불가: 선택 메뉴 수집 화면·순서 불일치'
        if not state.get('visible') or state.get('hovered'):return 'FAIL',screen+' 선택 메뉴가 숨김·잘림·가림 상태이거나 hover 상태임'
        href=state.get('href')
        if (href and urlsplit(href).path.rstrip('/')!=ROUTES[screen]) or state.get('aria_current')=='false' or state.get('aria_selected')=='false':
            return 'FAIL','검증 불가: '+screen+' 메뉴의 현재 화면 선택 근거 불일치'
        for key,label in (('background','배경색'),('text','글자색'),('font_weight','글자 굵기')):
            if state.get(key)!=wanted[key]:return 'FAIL',f"{screen} 선택 메뉴 {label} 불일치: 기대 {wanted[key]}, 실제 {state.get(key)}"
        if abs(state.get('font_size',-1)-wanted['font_size'])>.5:return 'FAIL',f"{screen} 글자 크기 불일치: 기대 {wanted['font_size']:g}px, 실제 {state.get('font_size')}px"
        paints=state.get('icon_paints') or []
        if not state.get('icon_count') or not paints:return 'FAIL','검증 불가: '+screen+' 아이콘의 실제 SVG 색상 근거 없음'
        if any(color!=wanted['icon'] for color in paints):return 'FAIL',f"{screen} 아이콘 색 불일치: 기대 {wanted['icon']}, 실제 {paints}"
    return 'PASS',' → '.join(wanted['screens'])+f" 선택 메뉴 배경 {wanted['background']}·글자/아이콘 {wanted['text']}/{wanted['icon']}·{wanted['font_size']:g}px·굵기 {wanted['font_weight']} 일치"
