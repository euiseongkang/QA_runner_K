"""실제 포인터 이동으로 사이드바 메뉴의 hover 글자색과 커서를 검증한다."""
import re
import time
from urllib.parse import urlsplit
from verifications.sidebar_menu_verification import LABELS, ROUTES


def applies(tc):
    title = str(tc.get('title') or '')
    return bool(re.search(r'사이드\s*바', title) and re.search(r'hover|마우스\s*오버', title, re.I))


def requirements(tc):
    steps = str(tc.get('steps') or '')
    expected = str(tc.get('expected') or '')
    hover_lines = [line for line in steps.splitlines() if re.search(r'hover|마우스.*(?:올|오버)', line, re.I)]
    targets = {name for line in hover_lines for name in LABELS if name.replace(' ', '') in re.sub(r'\s+', '', line)}
    entries = {name for name in ROUTES if re.search(r'\[' + re.escape(name).replace(r'\ ', r'\s*') + r'\][^\n]*?클릭(?:한다|하고|한다면|\s|$)', steps)}
    colors = {value.upper() for value in re.findall(r'#[0-9a-fA-F]{6}(?![0-9a-fA-F])', expected)}
    if len(targets) != 1 or len(entries) != 1 or len(colors) != 1:
        raise ValueError('진입 메뉴·마우스를 올릴 메뉴·기대 글자색(#RRGGBB)을 하나씩 명시해야 함')
    if not re.search(r'손가락|pointer', expected, re.I):
        raise ValueError('기대 마우스 커서(pointer/손가락)를 명시해야 함')
    target, entry = next(iter(targets)), next(iter(entries))
    if target == entry:
        raise ValueError('hover 검증 대상은 현재 선택된 진입 메뉴와 달라야 함')
    return dict(target=target, entry=entry, path=ROUTES[entry], color=next(iter(colors)), cursor='pointer',
                color_change=bool(re.search(r'진해|바뀌|변경|변한다', expected)))


def detail_draft(tc):
    if not applies(tc): return None
    try: wanted = requirements(tc)
    except ValueError: return None
    conditions = [re.sub(r'^\s*\d+[.)]\s*', '', line).strip() for line in re.split(r'\n|,(?=\s*(?:시작\s*URL|브라우저))', str(tc.get('precondition') or '')) if line.strip()]
    if not any('펼쳐' in line for line in conditions): conditions.append('왼쪽 사이드바가 펼쳐져 전체 메뉴를 확인할 수 있다.')
    target = wanted['target']
    steps = [f"왼쪽 사이드바의 [{wanted['entry']}] 메뉴를 클릭하고 화면 로딩 완료를 기다린다.",
             f'마우스를 사이드바 밖으로 이동하고 [{target}] 메뉴의 기본 글자색을 확인한다.',
             f'사이드바의 [{target}] 메뉴 위에 마우스를 올린다(마우스 오버). 메뉴를 클릭하지 않는다.',
             '마우스를 메뉴 위에 유지하고 hover 스타일 반영이 완료될 때까지 기다린다.',
             '마우스를 올린 메뉴명의 실제 글자색을 기본 상태와 비교한다.',
             '마우스를 올린 메뉴의 마우스 커서 모양을 확인한다.']
    color = f"마우스를 올린 메뉴명의 글자색은 {wanted['color']}이다."
    if wanted['color_change']: color = f"마우스를 올린 메뉴명의 글자색이 기본 상태에서 {wanted['color']}로 변경된다."
    expected = [color, '마우스를 올린 메뉴의 커서는 손가락 모양(pointer)이다.',
                '메뉴 클릭이나 다른 화면으로의 이동 없이 마우스 오버 상태를 확인한다.']
    numbered = lambda rows: '\n'.join(f'{i}. {line}' for i, line in enumerate(rows, 1))
    return dict(precondition=numbered(conditions), steps=numbered(steps), expected=numbered(expected))


def action(tc):
    return dict(type='verify_sidebar_hover', description='사이드바 메뉴 실제 마우스 오버·글자색·커서 검증')


FIND = r'''name => {
 const norm=s=>(s||'').replace(/\s/g,'');
 const visible=e=>{if(!e.getClientRects().length)return false;for(let p=e;p;p=p.parentElement){const s=getComputedStyle(p);if(s.display==='none'||s.visibility==='hidden'||Number(s.opacity)===0)return false;}return true;};
 let sides=[...document.querySelectorAll('.sidebar,.wco-sidebar')].filter(visible);
 if(!sides.length)sides=[...document.querySelectorAll('aside,[role="complementary"]')].filter(visible);
 if(sides.length!==1)throw Error('사이드바를 하나로 식별하지 못함');
 const items=[...sides[0].querySelectorAll('a[href],button,[role="link"],[role="menuitem"],[role="button"]')]
 .filter(e=>visible(e)&&norm(e.innerText)===norm(name)&&!e.closest('.wco-sidebar-brand,.sidebar-brand,[data-sidebar-brand]'));
 if(items.length!==1)throw Error('마우스 오버 대상 메뉴를 하나로 식별하지 못함');
 return items[0];
}'''
SAMPLE = r'''(e, name) => {
 const norm=s=>(s||'').replace(/\s/g,'');
 const labels=[e,...e.querySelectorAll('span,p,div')].filter(n=>norm(n.innerText)===norm(name));
 const label=labels.find(n=>!labels.some(other=>other!==n&&n.contains(other)))||e;
 const style=getComputedStyle(label),canvas=document.createElement('canvas'),ctx=canvas.getContext('2d');
 ctx.fillStyle=style.color;const color=ctx.fillStyle.toUpperCase();
 const r=label.getBoundingClientRect(),hit=document.elementFromPoint(r.x+r.width/2,r.y+r.height/2);
 return {color,cursor:style.cursor,hovered:e.matches(':hover'),label_hovered:label.matches(':hover'),
 visible:r.width>0&&r.height>0&&r.x>=0&&r.y>=0&&r.right<=innerWidth&&r.bottom<=innerHeight&&!!hit&&(e.contains(hit)||hit===e),
 position:{x:r.x+r.width/2-e.getBoundingClientRect().x,y:r.y+r.height/2-e.getBoundingClientRect().y},
 active:e.getAttribute('aria-current')==='page'||e.getAttribute('aria-selected')==='true'};
}'''


def collect(page, tc):
    state = {}
    handle = None
    try:
        wanted = state['expected'] = requirements(tc)
        if urlsplit(page.url).path.rstrip('/') != wanted['path']:
            raise ValueError('대상 화면 진입 근거 없음')
        initial_url = page.url
        handle = page.evaluate_handle(FIND, wanted['target'])
        element = handle.as_element()
        # 목표 메뉴 바깥 좌표로 이동한 뒤 실제 :hover 해제까지 확인한다.
        box = element.bounding_box()
        viewport = page.evaluate('({width:innerWidth,height:innerHeight})')
        outside = (viewport['width'] - 1, viewport['height'] - 1)
        if box and box['x'] <= outside[0] <= box['x'] + box['width'] and box['y'] <= outside[1] <= box['y'] + box['height']:
            outside = (0, 0)
        page.mouse.move(*outside)
        before = _stable(page, element, wanted['target'], False)
        if before['active']: raise ValueError('hover 대상 메뉴가 이미 선택된 상태임')
        state['before'] = before
        element.hover(position=before['position'], timeout=5000)
        state['after'] = _stable(page, element, wanted['target'], True)
        state['url_unchanged'] = page.url == initial_url
        state['path'] = urlsplit(page.url).path.rstrip('/')
    except Exception as exc:
        state['error'] = str(exc)
    finally:
        if handle is not None: handle.dispose()
    return state


def _stable(page, element, target, hovered):
    deadline = time.monotonic() + 5
    previous, since = None, time.monotonic()
    while True:
        value = element.evaluate(SAMPLE, target)
        now = time.monotonic()
        if value != previous: previous, since = value, now
        if value['hovered'] == hovered and value['visible'] and now - since >= .5: return value
        if now >= deadline: raise ValueError('메뉴 표시·마우스 오버 상태가 안정화되지 않음')
        page.wait_for_timeout(100)


def verify(state):
    if not state or state.get('error'):
        return 'FAIL', '검증 불가: ' + ((state or {}).get('error') or '마우스 오버 수집 근거 없음')
    wanted, before, after = state['expected'], state['before'], state['after']
    if not state.get('url_unchanged') or state.get('path') != wanted['path']:
        return 'FAIL', '마우스 오버 중 대상 화면이 변경됨'
    if before['hovered'] or not after['hovered'] or not after['visible']:
        return 'FAIL', '메뉴의 실제 마우스 오버 전후 근거 부족'
    if after['color'] != wanted['color']:
        return 'FAIL', f"hover 글자색 불일치: 기대 {wanted['color']}, 실제 {after['color']}"
    if wanted['color_change'] and before['color'] == after['color']:
        return 'FAIL', '마우스 오버 전후 메뉴명 글자색이 변경되지 않음'
    if after['cursor'] != wanted['cursor']:
        return 'FAIL', f"hover 커서 불일치: 기대 pointer, 실제 {after['cursor']}"
    return 'PASS', f"{wanted['target']} 실제 마우스 오버 후 글자색 {after['color']}·커서 pointer 확인, 화면 이동 없음"
