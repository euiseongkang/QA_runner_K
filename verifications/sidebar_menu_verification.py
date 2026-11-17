"""사이드바 최상위 메뉴의 구성·순서·아이콘·치수·CSS를 검증한다."""
import re
import time
from urllib.parse import urlsplit

LABELS = ('CGM View', '환자 관리', '검사 접수', '검사 결과', '공지사항')
ROUTES = {'검사 접수':'/receptions', '검사 결과':'/results', '환자 관리':'/patients'}
TOLERANCE = 0.5


def applies(tc):
    title = str(tc.get('title') or '')
    return bool(re.search(r'사이드\s*바', title) and '메뉴' in title and re.search(r'구성|순서', title))


def requirements(tc):
    text = str(tc.get('expected') or '')
    compact = re.sub(r'\s+', '', text).casefold()
    names = sorted((name for name in LABELS if name.replace(' ','').casefold() in compact),
                   key=lambda name:compact.index(name.replace(' ','').casefold()))
    if len(names) != len(LABELS): raise ValueError('예상 결과에 검증할 다섯 메뉴 이름과 순서를 명시해야 함')
    sizes = {(float(w),float(h)) for w,h in re.findall(r'(\d+(?:\.\d+)?)\s*[xX×]\s*(\d+(?:\.\d+)?)\s*px',text)}
    radii = {float(n) for n in re.findall(r'모서리(?:\s*반경)?[^,;\d\n]{0,12}(\d+(?:\.\d+)?)\s*px',text)}
    fonts = {float(n) for n in re.findall(r'(\d+(?:\.\d+)?)\s*px\s*(?:글자|글씨|폰트)',text)}
    fonts.update(float(n) for n in re.findall(r'(?:글자|글씨|폰트)\s*크기[^,;\d\n]{0,12}(\d+(?:\.\d+)?)\s*px',text))
    if any(len(values)!=1 for values in (sizes,radii,fonts)) or '아이콘' not in text:
        raise ValueError('메뉴 크기(가로×세로px)·모서리(px)·글자 크기(px)·아이콘을 하나의 기준으로 명시해야 함')
    menu = re.findall(r'\[(검사\s*접수|검사\s*결과|환자\s*관리)\]',str(tc.get('steps') or ''))
    paths={ROUTES[name] for name in ROUTES if name.replace(' ','') in [re.sub(r'\s+','',m) for m in menu]}
    if len(paths)!=1:raise ValueError('메뉴 구성을 확인할 진입 메뉴를 하나만 명시해야 함')
    width,height=next(iter(sizes))
    if min(width,height,*radii,*fonts)<=0:raise ValueError('메뉴 스타일 수치는 양수여야 함')
    return dict(names=names,width=width,height=height,radius=next(iter(radii)),font_size=next(iter(fonts)),path=next(iter(paths)))


def detail_draft(tc):
    """명시된 값만 실행기에서 수집 가능한 관찰 항목으로 풀어 쓴다."""
    if not applies(tc):return None
    try:wanted=requirements(tc)
    except ValueError:return None
    menu=next(name for name,path in ROUTES.items() if path==wanted['path'])
    conditions=[re.sub(r'^\s*\d+[.)]\s*','',line).strip() for line in re.split(r'\n|,(?=\s*(?:시작\s*URL|브라우저))',str(tc.get('precondition') or '')) if line.strip()]
    if not any('펼쳐' in c for c in conditions):conditions.append('왼쪽 사이드바가 펼쳐져 전체 메뉴를 확인할 수 있다.')
    sequence=' → '.join(wanted['names'])
    steps=[f'왼쪽 사이드바의 [{menu}] 메뉴를 클릭하고 화면 로딩 완료를 기다린다.',
           '왼쪽 사이드바의 최상위 메뉴를 위에서 아래 순서로 확인한다.',
           '각 메뉴의 메뉴명과 아이콘이 숨김이나 잘림 없이 표시되는지 확인한다.',
           '각 메뉴 클릭 영역의 실제 가로·세로 크기를 확인한다.',
           '각 메뉴 클릭 영역의 네 모서리 반경과 메뉴명 글자 크기를 확인한다.']
    expected=[f'사이드바 메뉴가 위에서부터 {sequence} 순서로 표시된다.',
              '각 메뉴에 해당 아이콘과 메뉴명이 표시된다.',
              f"각 메뉴 클릭 영역의 크기는 {wanted['width']:g}x{wanted['height']:g}px이다.",
              f"각 메뉴 클릭 영역의 네 모서리 반경은 각각 {wanted['radius']:g}px이다.",
              f"각 메뉴명 글자 크기는 {wanted['font_size']:g}px이다."]
    numbered=lambda rows:'\n'.join(f'{i}. {line}' for i,line in enumerate(rows,1))
    return dict(precondition=numbered(conditions),steps=numbered(steps),expected=numbered(expected))


def action(tc):return dict(type='verify_sidebar_menus',description='사이드바 메뉴 순서·아이콘·크기·모서리·글자 크기 검증')


SNAPSHOT = r'''names => {
 const norm=s=>(s||'').replace(/\s/g,'').toLowerCase();
 const rect=e=>{const r=e.getBoundingClientRect();return {x:r.x,y:r.y,width:r.width,height:r.height,right:r.right,bottom:r.bottom};};
 const rendered=e=>{if(!e||!e.getClientRects().length)return false;for(let p=e;p;p=p.parentElement){const s=getComputedStyle(p);if(s.display==='none'||s.visibility==='hidden'||Number(s.opacity)===0)return false;}return true;};
 const full=e=>{if(!rendered(e))return false;const r=rect(e);if(r.width<=0||r.height<=0||r.x<-.5||r.y<-.5||r.right>innerWidth+.5||r.bottom>innerHeight+.5)return false;
   for(let p=e.parentElement;p;p=p.parentElement){const s=getComputedStyle(p),q=rect(p);
    if(/hidden|clip|auto|scroll/.test(s.overflowX)&&(r.x<q.x-.5||r.right>q.right+.5))return false;
    if(/hidden|clip|auto|scroll/.test(s.overflowY)&&(r.y<q.y-.5||r.bottom>q.bottom+.5))return false;}
   const hit=document.elementFromPoint(r.x+r.width/2,r.y+r.height/2);return !!hit&&(e.contains(hit)||hit.contains(e));};
 let sides=[...document.querySelectorAll('.sidebar,.wco-sidebar')].filter(rendered);
 if(!sides.length)sides=[...document.querySelectorAll('aside,[role="complementary"]')].filter(rendered);
 if(sides.length!==1)return {error:'사이드바를 하나로 식별하지 못함'};
 const side=sides[0];
 const controls=[...side.querySelectorAll('a[href],button,[role="link"],[role="menuitem"],[role="button"]')]
  .filter(e=>rendered(e)&&!e.closest('.wco-sidebar-brand,.sidebar-brand,[data-sidebar-brand],.sidebar-menu-children'))
  .filter(e=>!e.parentElement?.closest('a[href],button,[role="link"],[role="menuitem"]'));
 const items=[];
 for(const name of names){
   const candidates=controls.filter(e=>norm(e.innerText)===norm(name));
   if(candidates.length!==1)return {error:name+' 메뉴를 하나로 식별하지 못함',matches:candidates.length};
   const control=candidates[0],r=rect(control),s=getComputedStyle(control);
   const labels=[control,...control.querySelectorAll('span,p,div')].filter(e=>rendered(e)&&norm(e.innerText)===norm(name));
   const label=labels.find(e=>!labels.some(other=>other!==e&&e.contains(other)))||control;
   const icons=[...control.querySelectorAll('svg,img')].filter(e=>rendered(e)&&!e.closest('.sidebar-menu-arrow'));
   const icon_ok=icons.some(e=>full(e)&&(e.tagName.toLowerCase()!=='img'||(e.complete&&e.naturalWidth>0)));
   const text_width=(()=>{const range=document.createRange();range.selectNodeContents(label);return range.getBoundingClientRect().width})();
   items.push({name,...r,visible:full(control)&&full(label)&&label.scrollWidth<=label.clientWidth+1&&text_width<=label.getBoundingClientRect().width+1,
     icon:icon_ok,font_size:parseFloat(getComputedStyle(label).fontSize),
     radii:[s.borderTopLeftRadius,s.borderTopRightRadius,s.borderBottomRightRadius,s.borderBottomLeftRadius]});
 }
 const extras=controls.filter(e=>!names.some(n=>norm(n)===norm(e.innerText)));
 return {items,extra_menu_count:extras.length,order:items.slice().sort((a,b)=>a.y-b.y||a.x-b.x).map(e=>e.name)};
}'''


def collect(page,tc):
    state={}
    try:
        state['expected']=requirements(tc)
        deadline=time.monotonic()+5
        previous,since=None,time.monotonic()
        while True:
            path=urlsplit(page.url).path.rstrip('/')
            snapshot=page.evaluate(SNAPSHOT,state['expected']['names']) if path==state['expected']['path'] else dict(error='대상 화면 진입 근거 없음')
            now=time.monotonic()
            if snapshot!=previous:previous,since=snapshot,now
            if not snapshot.get('error') and now-since>=.5:
                state.update(snapshot,path=path);break
            if now>=deadline:raise ValueError(snapshot.get('error') or '메뉴 표시 상태가 안정화되지 않음')
            page.wait_for_timeout(100)
    except Exception as exc:state['error']=str(exc)
    return state


def verify(state):
    if not state or state.get('error'):return 'FAIL','검증 불가: '+((state or {}).get('error') or '사이드바 메뉴 수집 근거 없음')
    expected=state['expected']
    if state.get('path')!=expected['path']:return 'FAIL','검증 불가: 메뉴 수집 화면 불일치'
    if state.get('order')!=expected['names'] or state.get('extra_menu_count'):
        return 'FAIL','사이드바 메뉴 구성·순서 불일치: 기대 '+' → '.join(expected['names'])+', 실제 '+' → '.join(state.get('order',[]))+f", 추가 메뉴 {state.get('extra_menu_count',0)}개"
    items=state.get('items',[])
    if len(items)!=len(expected['names']):return 'FAIL','검증 불가: 메뉴별 측정 근거 부족'
    for item in items:
        name=item['name']
        if not item.get('visible'):return 'FAIL',name+' 메뉴명/클릭 영역이 숨겨지거나 잘림·가림 상태임'
        if not item.get('icon'):return 'FAIL',name+' 메뉴 아이콘 노출 또는 이미지 로딩 근거 없음'
        for key,label in (('width','가로'),('height','세로'),('font_size','글자 크기')):
            if abs(item.get(key,-1)-expected[key])>TOLERANCE:
                return 'FAIL',f"{name} {label} 불일치: 기대 {expected[key]:g}px, 실제 {item.get(key)}px"
        radii=item.get('radii',[])
        if len(radii)!=4 or any(not re.fullmatch(r'\d+(?:\.\d+)?px',r) or abs(float(r[:-2])-expected['radius'])>TOLERANCE for r in radii):
            return 'FAIL',f"{name} 모서리 반경 불일치: 기대 {expected['radius']:g}px, 실제 {radii}"
    return 'PASS',f"사이드바 {len(items)}개 메뉴 순서·아이콘·{expected['width']:g}×{expected['height']:g}px·모서리 {expected['radius']:g}px·글자 {expected['font_size']:g}px 일치"
