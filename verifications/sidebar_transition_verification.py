"""메뉴 이동 전후 두 메뉴의 선택 배경과 이전 메뉴 글자색을 비교한다."""
import re
import time
from urllib.parse import urlsplit
from verifications.sidebar_menu_verification import ROUTES
from verifications.sidebar_cgm_verification import SAMPLE, screens
from verifications.sidebar_hover_verification import FIND


def applies(tc):
    title = str(tc.get('title') or '')
    return bool(re.search(r'사이드\s*바',title) and '메뉴' in title and '선택' in title and re.search(r'전환|이동',title))


def requirements(tc):
    sequence = screens(tc)
    if len(sequence)!=2 or sequence[0]==sequence[1]:
        raise ValueError('선택 전환을 비교할 서로 다른 두 메뉴 클릭 절차를 순서대로 명시해야 함')
    text = str(tc.get('expected') or '')
    normalized = text.replace('[','').replace(']','')
    for pattern, expected in ((r'새로\s*누른\s*(검사\s*접수|검사\s*결과|환자\s*관리)',sequence[1]),
                              (r'이전\s*(검사\s*접수|검사\s*결과|환자\s*관리)',sequence[0])):
        names=re.findall(pattern,normalized)
        if any(re.sub(r'\s+','',name)!=expected.replace(' ','') for name in names):
            raise ValueError('예상 결과의 이전/새 메뉴와 클릭 순서가 일치하지 않음')
    colors={v.upper() for v in re.findall(r'#[0-9a-fA-F]{6}(?![0-9a-fA-F])',text)}
    backgrounds={v.upper() for v in re.findall(r'배경(?:색)?[^#\n.]{0,25}(#[0-9a-fA-F]{6})(?![0-9a-fA-F])',text)}
    if len(backgrounds)!=1 or len(colors)!=2 or not re.search(r'글자',text):
        raise ValueError('선택 배경색과 이전 메뉴의 비선택 글자색을 #RRGGBB로 각각 하나씩 명시해야 함')
    background=next(iter(backgrounds))
    inactive=next(iter(colors-backgrounds))
    return dict(screens=sequence,background=background,inactive_text=inactive)


def detail_draft(tc):
    if not applies(tc): return None
    try: wanted=requirements(tc)
    except ValueError:return None
    first,second=wanted['screens']
    conditions=[re.sub(r'^\s*\d+[.)]\s*','',line).strip() for line in re.split(r'\n|,(?=\s*(?:시작\s*URL|브라우저))',str(tc.get('precondition') or '')) if line.strip()]
    if not any('펼쳐' in line for line in conditions):conditions.append('왼쪽 사이드바가 펼쳐져 두 메뉴가 표시된다.')
    steps=[f'왼쪽 사이드바의 [{first}] 메뉴를 클릭하고 화면 로딩 완료를 기다린다.',
           '마우스를 사이드바 밖으로 이동하고 기본 스타일 반영을 기다린다.',
           f'[{first}]와 [{second}] 메뉴의 배경색을 각각 확인한다.',
           f'왼쪽 사이드바의 [{second}] 메뉴를 클릭하고 화면 로딩 완료를 기다린다.',
           '마우스를 사이드바 밖으로 이동하고 기본 스타일 반영을 기다린다.',
           f'[{second}]와 [{first}] 메뉴의 배경색을 각각 확인한다.',
           f'이전 [{first}] 메뉴명의 글자색을 확인한다.']
    expected=[f"[{first}] 화면에서 선택된 [{first}] 메뉴의 배경색은 {wanted['background']}이다.",
              f"[{first}] 화면에서 [{second}] 메뉴에는 선택 배경색 {wanted['background']}가 적용되지 않는다.",
              f"[{second}] 화면으로 이동하면 선택된 [{second}] 메뉴의 배경색은 {wanted['background']}이다.",
              f"이전 [{first}] 메뉴의 배경색은 선택 배경색 {wanted['background']}와 다르다.",
              f"이전 [{first}] 메뉴명의 글자색은 {wanted['inactive_text']}이다."]
    numbered=lambda rows:'\n'.join(f'{i}. {line}' for i,line in enumerate(rows,1))
    return dict(precondition=numbered(conditions),steps=numbered(steps),expected=numbered(expected))


def actions(tc,parsed):
    result=[];sequence=iter(screens(tc));pending=next(sequence,None)
    for command in parsed:
        if command.get('type')=='click' and command.get('description')==pending:
            result.extend([dict(command,sidebar_menu=pending),dict(type='verify_sidebar_transition',target=pending,description=pending+' 선택 전환 비교 근거 수집')])
            pending=next(sequence,None)
    return result or [dict(type='verify_sidebar_transition',target=None,description='메뉴 선택 전환 근거 수집')]


SNAPSHOT='''names=>{const find=('''+FIND+'''),sample=('''+SAMPLE+''');const menus={};
 for(const name of names){const e=find(name);menus[name]={...sample(e,name),href:e.getAttribute('href'),aria_current:e.getAttribute('aria-current'),aria_selected:e.getAttribute('aria-selected')};}
 return {menus};}'''


def collect(page,tc,target):
    state=dict(screen=target)
    try:
        wanted=requirements(tc)
        if target not in wanted['screens']:raise ValueError('선택 전환 확인 화면 불명확')
        page.mouse.move(page.evaluate('innerWidth-1'),page.evaluate('innerHeight-1'))
        previous,since=None,time.monotonic();deadline=since+5
        while True:
            path=urlsplit(page.url).path.rstrip('/')
            snapshot=dict(error='선택 전환 대상 화면 진입 근거 없음')
            if path==ROUTES[target]:
                try:snapshot=page.evaluate(SNAPSHOT,wanted['screens'])
                except Exception as exc:snapshot=dict(error=str(exc).replace('마우스 오버 대상 메뉴','선택 전환 대상 메뉴'))
            now=time.monotonic()
            if snapshot!=previous:previous,since=snapshot,now
            if not snapshot.get('error') and now-since>=.5:
                state.update(snapshot,path=path);break
            if now>=deadline:raise ValueError(snapshot.get('error') or '메뉴 선택 스타일이 안정화되지 않음')
            page.wait_for_timeout(100)
    except Exception as exc:state['error']=str(exc)
    return state


def verify(tc,evidence):
    try:wanted=requirements(tc)
    except ValueError as exc:return 'FAIL','검증 불가: '+str(exc)
    if not evidence or len(evidence)!=2:return 'FAIL','검증 불가: 메뉴 이동 전후 두 단계의 근거 부족'
    first,second=wanted['screens'];background=wanted['background']
    for index,(screen,state) in enumerate(zip(wanted['screens'],evidence)):
        if state.get('error'):return 'FAIL','검증 불가: '+screen+' '+state['error']
        if state.get('screen')!=screen or state.get('path')!=ROUTES[screen]:return 'FAIL','검증 불가: 메뉴 전환 수집 화면·순서 불일치'
        for name in wanted['screens']:
            menu=state.get('menus',{}).get(name)
            if not menu or menu.get('error'):return 'FAIL','검증 불가: '+screen+' 화면의 '+name+' 스타일 근거 없음: '+str((menu or {}).get('error',''))
            if not menu.get('visible') or menu.get('hovered'):return 'FAIL',screen+' 화면의 '+name+' 메뉴가 숨김·잘림·가림 또는 hover 상태임'
            if menu.get('href') and urlsplit(menu['href']).path.rstrip('/')!=ROUTES[name]:return 'FAIL','검증 불가: '+name+' 메뉴 링크 불일치'
            selected=name==screen
            if selected:
                if menu.get('background')!=background:return 'FAIL',f"{screen} 화면 선택 메뉴 배경색 불일치: 기대 {background}, 실제 {menu.get('background')}"
                if menu.get('aria_current')=='false' or menu.get('aria_selected')=='false':return 'FAIL',name+' 메뉴의 명시적 선택 속성이 해제 상태임'
            else:
                if menu.get('background')==background:return 'FAIL',screen+' 화면에서 비선택 '+name+' 메뉴에 선택 배경이 남아 있음'
                if menu.get('aria_current') in ('page','true') or menu.get('aria_selected')=='true':return 'FAIL',name+' 메뉴의 선택 속성이 해제되지 않음'
        if index==1:
            actual=state['menus'][first].get('text')
            if actual!=wanted['inactive_text']:return 'FAIL',f"이전 {first} 메뉴 글자색 복원 불일치: 기대 {wanted['inactive_text']}, 실제 {actual}"
    return 'PASS',f"{first} → {second} 선택 배경 {background} 전환·이전 메뉴 배경 해제·글자색 {wanted['inactive_text']} 복원 확인"
