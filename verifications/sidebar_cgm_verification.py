"""화면 이동별 CGM View 메뉴의 기본 배경색·메뉴명 글자색을 검증한다."""
import re
import time
from urllib.parse import urlsplit
from verifications.sidebar_menu_verification import ROUTES
from verifications.sidebar_hover_verification import FIND


def applies(tc):
    title = str(tc.get('title') or '')
    return bool(re.search(r'사이드\s*바', title) and re.search(r'CGM\s*View', title, re.I)
                and re.search(r'강조|배경|글자색', title))


def screens(tc):
    return [next(name for name in ROUTES if name.replace(' ', '') == re.sub(r'\s+', '', value))
            for value in re.findall(r'\[(검사\s*접수|검사\s*결과|환자\s*관리)\][^\n]*?클릭(?:한다|하고|합니다|[ \t]*(?:후|뒤)|[.!。]?[ \t]*$)', str(tc.get('steps') or ''), re.M)]


def requirements(tc):
    expected = str(tc.get('expected') or '')
    colors = {}
    for key, label in (('background', '배경색'), ('text', '글자색')):
        values = {value.upper() for value in re.findall(label+r'[^#\n.]{0,25}(#[0-9a-fA-F]{6})(?![0-9a-fA-F])', expected)}
        if len(values) != 1: raise ValueError('CGM View '+label+'을 #RRGGBB로 하나만 명시해야 함')
        colors[key] = next(iter(values))
    sequence = screens(tc)
    if not sequence: raise ValueError('CGM View를 확인할 화면의 메뉴 클릭 절차가 없음')
    multiple = bool(re.search(r'다른\s*화면|각\s*화면|모든\s*화면|두\s*화면', expected))
    return dict(colors=colors, screens=sequence, multiple=multiple,
                intent_unconfirmed=bool(re.search(r'의도[^\n.]*확인', expected)))


def detail_draft(tc):
    if not applies(tc): return None
    try: wanted = requirements(tc)
    except ValueError: return None
    sequence = list(wanted['screens'])
    if wanted['multiple'] and len(set(sequence)) < 2:
        sequence.append(next(name for name in ('검사 접수', '검사 결과') if name not in sequence))
    conditions = [re.sub(r'^\s*\d+[.)]\s*', '', line).strip() for line in re.split(r'\n|,(?=\s*(?:시작\s*URL|브라우저))', str(tc.get('precondition') or '')) if line.strip()]
    if not any('펼쳐' in line for line in conditions): conditions.append('왼쪽 사이드바가 펼쳐져 [CGM View] 메뉴가 표시된다.')
    steps = []
    for screen in sequence:
        steps.extend([f'왼쪽 사이드바의 [{screen}] 메뉴를 클릭하고 화면 로딩 완료를 기다린다.',
                      '마우스를 [CGM View] 메뉴 밖으로 이동하고 기본 스타일 반영을 기다린다.',
                      '[CGM View] 메뉴 클릭 영역의 배경색을 확인한다.',
                      '[CGM View] 메뉴명의 글자색을 확인한다.'])
    scope = '·'.join(f'[{name}]' for name in dict.fromkeys(sequence))
    screen_phrase = scope + (' 각 화면에서' if len(set(sequence)) > 1 else ' 화면에서')
    expected = [f"{screen_phrase} [CGM View] 메뉴의 배경색은 {wanted['colors']['background']}이다.",
                f"{screen_phrase} [CGM View] 메뉴명의 글자색은 {wanted['colors']['text']}이다.",
                '화면 이동 후에도 [CGM View] 메뉴가 숨김이나 잘림 없이 표시된다.']
    numbered = lambda rows: '\n'.join(f'{i}. {line}' for i, line in enumerate(rows, 1))
    return dict(precondition=numbered(conditions), steps=numbered(steps), expected=numbered(expected))


def actions(tc, parsed):
    result = []
    # 관찰 문장에 등장하는 [CGM View]는 클릭하지 않는다.
    sequence = iter(screens(tc))
    pending = next(sequence, None)
    for command in parsed:
        if command.get('type') == 'click' and command.get('description') == pending:
            result.extend([command, dict(type='verify_sidebar_cgm', target=pending,
                                        description=pending+' CGM View 배경색·글자색 수집')])
            pending = next(sequence, None)
    return result or [dict(type='verify_sidebar_cgm', target=None, description='CGM View 색상 수집')]


SAMPLE = r'''(e, name) => {
 name = name || 'CGM View';
 const rect=n=>{const r=n.getBoundingClientRect();return {x:r.x,y:r.y,right:r.right,bottom:r.bottom,width:r.width,height:r.height};};
 const full=n=>{const r=rect(n);if(r.width<=0||r.height<=0||r.x<0||r.y<0||r.right>innerWidth||r.bottom>innerHeight)return false;
  for(let p=n;p;p=p.parentElement){const s=getComputedStyle(p),q=rect(p);
   if(s.display==='none'||s.visibility==='hidden'||Number(s.opacity)===0)return false;
   if(/hidden|clip|auto|scroll/.test(s.overflowX)&&(r.x<q.x-.5||r.right>q.right+.5))return false;
   if(/hidden|clip|auto|scroll/.test(s.overflowY)&&(r.y<q.y-.5||r.bottom>q.bottom+.5))return false;}
  const hit=document.elementFromPoint(r.x+r.width/2,r.y+r.height/2);return !!hit&&(n.contains(hit)||hit.contains(n));};
 const norm=s=>(s||'').replace(/\s/g,'').toLowerCase();
 const labels=[e,...e.querySelectorAll('span,p,div')].filter(n=>norm(n.innerText)===norm(name));
 const label=labels.find(n=>!labels.some(other=>other!==n&&n.contains(other)))||e;
 const canvas=document.createElement('canvas');canvas.width=canvas.height=1;const ctx=canvas.getContext('2d',{willReadFrequently:true});
 const rgba=color=>{ctx.clearRect(0,0,1,1);ctx.fillStyle=color;ctx.fillRect(0,0,1,1);return [...ctx.getImageData(0,0,1,1).data];};
 const hex=rgb=>'#'+rgb.slice(0,3).map(v=>Math.round(v).toString(16).padStart(2,'0')).join('').toUpperCase();
 const layers=[];let opaque=false;
 for(let n=e;n;n=n.parentElement){const s=getComputedStyle(n);
  if(Number(s.opacity)!==1||s.mixBlendMode!=='normal'||s.filter!=='none')return {error:'CGM View의 투명도·혼합·필터 효과로 단색 판정 불가'};
  if(opaque)continue;
  if(s.backgroundImage!=='none')return {error:'CGM View 배경 이미지·그라데이션으로 단색 판정 불가'};
  const value=rgba(s.backgroundColor);layers.push(value);if(value[3]===255)opaque=true;}
 let rgb=[255,255,255];for(const value of layers.reverse()){const a=value[3]/255;rgb=rgb.map((v,i)=>value[i]*a+v*(1-a));}
 // 메뉴명 자식에만 적용된 투명도·그라데이션 텍스트 효과도 추측하지 않는다.
 for(let n=label;n!==e;n=n.parentElement){const s=getComputedStyle(n);if(Number(s.opacity)!==1||s.filter!=='none'||s.mixBlendMode!=='normal')return {error:'CGM View 메뉴명 표시 효과로 글자색 판정 불가'};}
 const textStyle=getComputedStyle(label),text=rgba(textStyle.color);
 if(text[3]!==255||textStyle.webkitTextFillColor!==textStyle.color)return {error:'CGM View 메뉴명의 투명/별도 채움 글자색 판정 불가'};
 const range=document.createRange();range.selectNodeContents(label);
 return {background:hex(rgb),text:hex(text),background_css:getComputedStyle(e).backgroundColor,text_css:textStyle.color,
  visible:full(e)&&full(label)&&label.scrollWidth<=label.clientWidth+1&&range.getBoundingClientRect().width<=label.getBoundingClientRect().width+1,
  hovered:e.matches(':hover')};
}'''


def collect(page, tc, target):
    state = dict(screen=target)
    try:
        state['expected'] = requirements(tc)['colors']
        if target not in ROUTES: raise ValueError('CGM View 수집 대상 화면이 명시되지 않음')
        page.mouse.move(page.evaluate('innerWidth-1'), page.evaluate('innerHeight-1'))
        deadline = time.monotonic() + 5
        previous, since = None, time.monotonic()
        while True:
            path = urlsplit(page.url).path.rstrip('/')
            snapshot = dict(error='대상 화면 진입 근거 없음')
            if path == ROUTES[target]:
                try:
                    handle = page.evaluate_handle(FIND, 'CGM View')
                    try: snapshot = handle.as_element().evaluate(SAMPLE)
                    finally: handle.dispose()
                except Exception as exc: snapshot = dict(error=str(exc).replace('마우스 오버 대상 메뉴', 'CGM View 메뉴'))
            now = time.monotonic()
            if snapshot != previous: previous, since = snapshot, now
            if not snapshot.get('error') and now-since >= .5:
                state.update(snapshot, path=path);break
            if now >= deadline: raise ValueError(snapshot.get('error') or 'CGM View 스타일이 안정화되지 않음')
            page.wait_for_timeout(100)
    except Exception as exc: state['error'] = str(exc)
    return state


def verify(tc, evidence):
    try: wanted = requirements(tc)
    except ValueError as exc: return 'FAIL', '검증 불가: '+str(exc)
    sequence = wanted['screens']
    if wanted['intent_unconfirmed']:
        return 'FAIL', '검증 불가: 의도된 강조 버튼인지는 기획 확인이 필요함. 색상 검증과 분리해야 함'
    if wanted['multiple'] and len(set(sequence)) < 2:
        return 'FAIL', '검증 불가: 다른 화면에서도 유지되는지 확인할 두 번째 화면 절차 없음'
    if not evidence or len(evidence) != len(sequence):
        return 'FAIL', '검증 불가: 화면 이동별 CGM View 수집 근거 부족'
    for screen, state in zip(sequence, evidence):
        if state.get('error'): return 'FAIL', '검증 불가: '+screen+' '+state['error']
        if state.get('screen') != screen or state.get('path') != ROUTES[screen]:
            return 'FAIL', '검증 불가: CGM View 수집 화면·순서 불일치'
        if not state.get('visible') or state.get('hovered'):
            return 'FAIL', screen+' CGM View가 숨김·잘림·가림 상태이거나 기본 스타일이 아닌 hover 상태임'
        for key, label in (('background', '배경색'), ('text', '글자색')):
            if state.get(key) != wanted['colors'][key]:
                return 'FAIL', f"{screen} CGM View {label} 불일치: 기대 {wanted['colors'][key]}, 실제 {state.get(key)}"
    return 'PASS', ' → '.join(sequence)+f" CGM View 배경색 {wanted['colors']['background']}·글자색 {wanted['colors']['text']} 일치"
