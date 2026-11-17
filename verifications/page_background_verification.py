"""페이지별 사이드바·상단바·본문 CSS 배경색을 단계별 수집한다."""
import re
import time
from urllib.parse import urlsplit

REGIONS = ('사이드바', '상단바', '본문')
ROUTES = {'검사 접수':'/receptions', '검사 결과':'/results'}


def applies(tc):
    return bool(re.search(r'페이지\s*배경색', str(tc.get('title') or '')))


def screens(tc):
    return [re.sub(r'\s+', '', value).replace('검사접수','검사 접수').replace('검사결과','검사 결과')
            for value in re.findall(r'\[(검사\s*접수|검사\s*결과)\]', str(tc.get('steps') or ''))]


def expected_colors(tc):
    text = re.sub(r'상단\s+바', '상단바', str(tc.get('expected') or ''))
    result = {}
    common = {value.upper() for value in re.findall(r'#[0-9a-fA-F]{6}\b', text)}
    for region in REGIONS:
        values = set()
        for line in text.splitlines():
            if region in line:
                values.update(value.upper() for value in re.findall(r'#[0-9a-fA-F]{6}\b', line))
        if len(values) != 1 and len(common) == 1 and region in text:
            values = set(common)
        if len(values) != 1: raise ValueError(region+'의 기대 배경색을 #RRGGBB로 하나만 지정해야 함')
        result[region] = next(iter(values))
    return result


def actions(tc, parsed):
    result = []
    for command in parsed:
        if command.get('type') == 'click' and command.get('description') in ROUTES:
            result.extend([command, dict(type='verify_page_background', description=command['description']+' 배경색 수집',
                                        target=command['description'])])
    return result or [dict(type='verify_page_background',description='페이지 배경색 수집',target=None)]


SNAPSHOT = r'''() => {
 const visible=e=>{const r=e.getBoundingClientRect(),s=getComputedStyle(e);return r.width>0&&r.height>0&&s.visibility!=='hidden'&&s.display!=='none'&&r.bottom>0&&r.right>0&&r.top<innerHeight&&r.left<innerWidth;};
 const pick=selectors=>{for(const selector of selectors){let es=[...document.querySelectorAll(selector)].filter(visible);if(es.length)return es;}return [];};
 const side=pick(['.sidebar,.wco-sidebar','aside,[role="complementary"]']);
 const top=pick(['.dashboard-app-bar,.wco-app-bar','header,[role="banner"]']);
 let main=pick(['main,[role="main"],[data-qa-main]']);
 if(!main.length&&top.length===1){let next=top[0].nextElementSibling;while(next){
   if(visible(next)&&!next.matches('[aria-hidden="true"],.wco-app-bar-spacer')){main=[next];break;}next=next.nextElementSibling;}}
 if(!main.length)main=pick(['.dashboard-content']);
 if(side.length!==1||top.length!==1||main.length!==1)return {error:'사이드바·상단바·본문을 각각 하나로 식별하지 못함'};
 const canvas=document.createElement('canvas');canvas.width=canvas.height=1;const ctx=canvas.getContext('2d',{willReadFrequently:true});
 const rgba=color=>{ctx.clearRect(0,0,1,1);ctx.fillStyle=color;ctx.fillRect(0,0,1,1);return [...ctx.getImageData(0,0,1,1).data];};
 const colors={};
 for(const [region,node] of Object.entries({'사이드바':side[0],'상단바':top[0],'본문':main[0]})){
   const layers=[];let opaque=false;
   for(let e=node;e;e=e.parentElement){const s=getComputedStyle(e);
     if(Number(s.opacity)!==1||s.mixBlendMode!=='normal'||s.filter!=='none')return {error:region+'의 투명도·혼합·필터 효과로 단색 배경 판정 불가'};
     if(opaque)continue;
     if(s.backgroundImage!=='none')return {error:region+'에 배경 이미지/그라데이션이 있어 단색 CSS 판정 불가'};
     const value=rgba(s.backgroundColor);layers.push(value);if(value[3]===255)opaque=true;
   }
   let rgb=[255,255,255];
   for(const value of layers.reverse()){let a=value[3]/255;rgb=rgb.map((v,i)=>value[i]*a+v*(1-a));}
   colors[region]={css:getComputedStyle(node).backgroundColor,effective:'#'+rgb.map(v=>Math.round(v).toString(16).padStart(2,'0')).join('').toUpperCase()};
 }
 return {colors};
}'''


def collect(page, tc, target):
    state = dict(screen=target)
    try:
        state['expected'] = expected_colors(tc)
        if target not in ROUTES: raise ValueError('검증 대상 메뉴 이동 절차 없음')
        deadline = time.monotonic()+5
        previous, since = None, time.monotonic()
        while True:
            path = urlsplit(page.url).path.rstrip('/')
            if path == ROUTES[target]:
                snapshot=page.evaluate(SNAPSHOT)
            else: snapshot=dict(error=target+' 화면 경로 진입 근거 없음')
            now=time.monotonic()
            if snapshot!=previous: previous,since=snapshot,now
            if not snapshot.get('error') and now-since>=0.5:
                state.update(snapshot,path=path);break
            if now>=deadline: raise ValueError(snapshot.get('error') or '배경색 표시 상태가 안정화되지 않음')
            page.wait_for_timeout(100)
    except Exception as exc:state['error']=str(exc)
    return state


def verify(tc, evidence):
    try: wanted=expected_colors(tc)
    except ValueError as exc:return 'FAIL','검증 불가: '+str(exc)
    sequence=screens(tc)
    if not sequence or not evidence or len(evidence)!=len(sequence):
        return 'FAIL','검증 불가: 메뉴 이동별 배경색 수집 근거 부족'
    for target,state in zip(sequence,evidence):
        if state.get('error'): return 'FAIL','검증 불가: '+target+' '+state['error']
        if state.get('screen')!=target or state.get('path')!=ROUTES[target]:
            return 'FAIL','검증 불가: 배경색 수집 화면·순서 불일치'
        for region,color in wanted.items():
            actual=state.get('colors',{}).get(region,{}).get('effective')
            if actual is None:return 'FAIL','검증 불가: '+target+' '+region+' 배경색 근거 없음'
            if actual!=color:return 'FAIL',f'{target} {region} 배경색 불일치: 기대 {color}, 실제 {actual}'
    return 'PASS',' → '.join(sequence)+' 각각 사이드바·상단바·본문 배경색 일치: '+', '.join(f'{r} {v}' for r,v in wanted.items())
