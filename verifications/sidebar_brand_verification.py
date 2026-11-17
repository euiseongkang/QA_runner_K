"""사이드바의 실제 폭과 상단 아이콘·로고의 표시 상태를 수집·판정한다."""
import re
import time
from urllib.parse import urlsplit

TOLERANCE = 0.5  # CSS 서브픽셀 반올림 허용치
MENUS = {'검사 접수': '/receptions', '검사 결과': '/results', '환자 관리': '/patients'}


def applies(tc):
    title = str(tc.get('title') or '')
    return bool(re.search(r'사이드\s*바', title) and re.search(r'폭|너비', title) and '로고' in title)


def requirements(tc):
    text = str(tc.get('expected') or '')
    widths = {float(n) for n in re.findall(r'사이드\s*바(?:의)?\s*(?:가로\s*)?(?:폭|너비)[^\d\n]{0,15}(\d+(?:\.\d+)?)\s*px', text, re.I)}
    if len(widths) != 1 or not all(word in text for word in ('아이콘', '로고')):
        raise ValueError('사이드바 폭(px)과 상단 아이콘·로고 노출을 예상 결과에 명시해야 함')
    sizes = {}
    for name in ('아이콘', '로고'):
        values = {(float(w), float(h)) for w, h in re.findall(name+r'\s*\(?\s*(\d+(?:\.\d+)?)\s*[xX×]\s*(\d+(?:\.\d+)?)\s*px', text)}
        if len(values) > 1: raise ValueError(name+'의 기대 크기가 여러 개임')
        if values: sizes[name] = list(next(iter(values)))
    menus = [re.sub(r'\s+', '', name) for name in re.findall(r'\[(검사\s*접수|검사\s*결과|환자\s*관리)\]', str(tc.get('steps') or ''))]
    paths = {MENUS[name] for name in MENUS if name.replace(' ', '') in menus}
    if len(paths) != 1: raise ValueError('사이드바를 확인할 대상 메뉴를 하나만 명시해야 함')
    return dict(width=next(iter(widths)), sizes=sizes, path=next(iter(paths)), inline=bool(re.search(r'나란히|같은\s*줄', text)))


def action(tc):
    return dict(type='verify_sidebar_brand', description='사이드바 폭·상단 아이콘·로고 표시 검증')


SNAPSHOT = r'''() => {
 const rect=e=>{const r=e.getBoundingClientRect();return {x:r.x,y:r.y,width:r.width,height:r.height,right:r.right,bottom:r.bottom};};
 const shown=e=>{const r=rect(e);if(r.width<=0||r.height<=0||r.right<=0||r.bottom<=0||r.x>=innerWidth||r.y>=innerHeight)return false;
   for(let p=e;p;p=p.parentElement){const s=getComputedStyle(p);if(s.display==='none'||s.visibility==='hidden'||Number(s.opacity)===0)return false;}return true;};
 const within=(a,b)=>a.x>=b.x-0.5&&a.y>=b.y-0.5&&a.right<=b.right+0.5&&a.bottom<=b.bottom+0.5;
 const full=e=>{const r=rect(e);if(!shown(e)||!within(r,{x:0,y:0,right:innerWidth,bottom:innerHeight}))return false;
   for(let p=e.parentElement;p;p=p.parentElement){const s=getComputedStyle(p),q=rect(p);
     if(/hidden|clip|scroll|auto/.test(s.overflowX)&&!(r.x>=q.x-0.5&&r.right<=q.right+0.5))return false;
     if(/hidden|clip|scroll|auto/.test(s.overflowY)&&!(r.y>=q.y-0.5&&r.bottom<=q.bottom+0.5))return false;}
   const hit=document.elementFromPoint(r.x+r.width/2,r.y+r.height/2);
   return !!hit&&(e.contains(hit)||hit.contains(e));};
 let sides=[...document.querySelectorAll('.sidebar,.wco-sidebar')].filter(shown);
 if(!sides.length)sides=[...document.querySelectorAll('aside,[role="complementary"]')].filter(shown);
 if(sides.length!==1)return {error:'사이드바를 하나로 식별하지 못함'};
 const side=sides[0],brands=[...side.querySelectorAll('.wco-sidebar-brand,.sidebar-brand,[data-sidebar-brand]')].filter(shown);
 if(brands.length!==1)return {error:'상단 브랜드 영역을 하나로 식별하지 못함'};
 const brand=brands[0],logos=[...brand.querySelectorAll('img,svg[aria-label]')].filter(e=>
   /logo|로고|labconnect|랩커넥트/i.test((e.getAttribute('alt')||'')+' '+(e.getAttribute('aria-label')||'')+' '+(e.getAttribute('src')||'')));
 const icons=[...brand.querySelectorAll('svg,img')].filter(e=>!logos.some(logo=>logo===e||logo.contains(e)))
   .filter(e=>e.tagName.toLowerCase()==='svg'||/menu|메뉴|아이콘|햄버거/i.test((e.getAttribute('alt')||'')+' '+(e.getAttribute('aria-label')||'')));
 if(logos.length!==1||icons.length!==1)return {error:'상단 메뉴 아이콘·로고를 각각 하나로 식별하지 못함'};
 const sb=rect(side),br=rect(brand),icon=icons[0],logo=logos[0];
 const image=logo.tagName.toLowerCase()==='img';
 return {sidebar:sb,css_width:getComputedStyle(side).width,brand:br,
   top:within(br,sb)&&br.y>=sb.y-0.5&&br.y<=sb.y+br.height,
   icon:{...rect(icon),visible:full(icon)&&within(rect(icon),br)},
   logo:{...rect(logo),visible:full(logo)&&within(rect(logo),br),complete:!image||logo.complete,
     loaded:!image||(logo.complete&&logo.naturalWidth>0&&logo.naturalHeight>0)}};
}'''


def collect(page, tc):
    state = {}
    try:
        state['expected'] = requirements(tc)
        deadline = time.monotonic()+5
        previous, since = None, time.monotonic()
        while True:
            path = urlsplit(page.url).path.rstrip('/')
            snapshot = page.evaluate(SNAPSHOT) if path == state['expected']['path'] else dict(error='대상 메뉴 화면 진입 근거 없음')
            now = time.monotonic()
            if snapshot != previous: previous, since = snapshot, now
            stable = not snapshot.get('error') and now-since >= 0.5
            if stable and (snapshot.get('logo', {}).get('complete') or now >= deadline):
                state.update(snapshot, path=path); break
            if now >= deadline: raise ValueError(snapshot.get('error') or '사이드바 표시 상태가 안정화되지 않음')
            page.wait_for_timeout(100)
    except Exception as exc: state['error'] = str(exc)
    return state


def verify(state):
    if not state or state.get('error'):
        return 'FAIL', '검증 불가: '+((state or {}).get('error') or '사이드바 폭·아이콘·로고 근거 없음')
    expected = state.get('expected', {})
    if state.get('path') != expected.get('path'): return 'FAIL', '검증 불가: 수집 화면 불일치'
    width = state.get('sidebar', {}).get('width')
    if width is None or not isinstance(expected.get('width'), (float, int)):
        return 'FAIL', '검증 불가: 사이드바 폭 측정 근거 없음'
    if abs(width-expected['width']) > TOLERANCE:
        return 'FAIL', f"사이드바 폭 불일치: 기대 {expected['width']:g}px, 실제 {width:g}px"
    if not state.get('top'): return 'FAIL', '아이콘·로고 영역이 사이드바 상단에 표시되지 않음'
    for key, name in (('icon', '아이콘'), ('logo', '로고')):
        item = state.get(key, {})
        if not item.get('visible'): return 'FAIL', name+'가 완전히 표시되지 않음: 숨김·잘림·화면 밖·가림 확인'
        if key == 'logo' and not item.get('loaded'): return 'FAIL', '로고 이미지 로딩 실패'
        if name in expected.get('sizes', {}):
            w, h = expected['sizes'][name]
            if abs(item.get('width', -1)-w) > TOLERANCE or abs(item.get('height', -1)-h) > TOLERANCE:
                return 'FAIL', f'{name} 크기 불일치: 기대 {w:g}×{h:g}px, 실제 {item.get("width")}×{item.get("height")}px'
    if expected.get('inline'):
        a, b = state['icon'], state['logo']
        if min(a['bottom'], b['bottom']) <= max(a['y'], b['y']) or not (a['right'] <= b['x']+TOLERANCE or b['right'] <= a['x']+TOLERANCE):
            return 'FAIL', '상단 아이콘과 로고가 같은 줄에 나란히 표시되지 않음'
    return 'PASS', f'사이드바 실제 폭 {width:g}px 일치 + 상단 메뉴 아이콘·로고 노출 및 숨김·잘림 없음 확인'
