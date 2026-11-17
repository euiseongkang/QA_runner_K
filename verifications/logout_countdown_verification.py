"""상단바 로그아웃 타이머 스타일·형식·배치와 실제 초 단위 감소를 검증한다."""
import re
import time
from urllib.parse import urlsplit
from verifications.sidebar_menu_verification import ROUTES
from verifications.sidebar_cgm_verification import screens
from verifications.login_extension_verification import parse_display_time

LABEL='로그아웃 남은 시간'
TICK_TOLERANCE_MS=250


def applies(tc):
    title=str(tc.get('title') or '')
    return bool(re.search(r'상단\s*바',title) and re.search(r'로그아웃\s*남은\s*시간',title))


def requirements(tc):
    text=str(tc.get('expected') or '')
    parts=re.split(r'\n|,\s*그\s*아래',text)
    groups={'label':[],'time':[]}
    for part in parts:
        if re.search(r'로그아웃\s*남은\s*시간|안내\s*문구',part):groups['label'].append(part)
        elif re.search(r'시간\s*표시|hh:mm:ss|타이머',part,re.I):groups['time'].append(part)
    result={}
    for key,parts in groups.items():
        chunk='\n'.join(parts)
        sizes={float(v) for v in re.findall(r'(\d+(?:\.\d+)?)\s*px',chunk)}
        colors={v.upper() for v in re.findall(r'#[0-9a-fA-F]{6}(?![0-9a-fA-F])',chunk)}
        weights={int(v) for v in re.findall(r'(?<![\dA-Za-z#])(\d{3})(?![\dA-Za-z])',chunk)}
        if re.search(r'\bMedium\b',chunk,re.I):weights.add(500)
        if len(sizes)!=1 or len(colors)!=1 or len(weights)!=1 or min(sizes)<=0 or not 100<=next(iter(weights))<=900:
            raise ValueError(('안내 문구' if key=='label' else '시간 표시')+'의 글자 크기(px)·굵기(Medium/500 등)·색상을 하나씩 명시해야 함')
        result[key]=dict(font_size=next(iter(sizes)),font_weight=next(iter(weights)),color=next(iter(colors)))
    if not re.search(r'hh:mm:ss',text,re.I) or not re.search(r'1초\s*(?:단위|간격|주기)',text):
        raise ValueError('hh:mm:ss 형식과 1초 단위 감소 기준을 명시해야 함')
    steps=str(tc.get('steps') or '')
    durations={float(v) for v in re.findall(r'(\d+(?:\.\d+)?)초\s*(?:동안|간)',steps)}
    if len(durations)>1:raise ValueError('카운트다운 관찰 시간을 하나만 명시해야 함')
    duration=next(iter(durations)) if durations else 5
    if not 4<=duration<=30:raise ValueError('카운트다운 관찰 시간은 4~30초로 지정해야 함')
    sequence=screens(tc)
    if not sequence:raise ValueError('타이머를 확인할 메뉴 클릭 절차 없음')
    return dict(**result,duration=duration,screens=sequence)


def detail_draft(tc):
    if not applies(tc):return None
    try:wanted=requirements(tc)
    except ValueError:return None
    conditions=[re.sub(r'^\s*\d+[.)]\s*','',line).strip() for line in re.split(r'\n|,(?=\s*(?:시작\s*URL|브라우저))',str(tc.get('precondition') or '')) if line.strip()]
    if not any(re.search(r'로그아웃\s*남은\s*시간이\s*\d+초\s*이상', line) for line in conditions):
        conditions.append(f"로그아웃 남은 시간이 {int(wanted['duration'])+2}초 이상이며, 테스트 중 로그인 연장을 수행하지 않는다.")
    steps=[]
    for screen in wanted['screens']:
        steps.extend([f'왼쪽 사이드바의 [{screen}] 메뉴를 클릭하고 화면 로딩 완료를 기다린다.',
                      '상단바 오른쪽의 [로그아웃 남은 시간] 안내 문구를 확인한다.',
                      '안내 문구의 글자 크기·굵기·색상을 확인한다.',
                      '안내 문구 아래 시간 표시의 형식과 글자 크기·굵기·색상을 확인한다.',
                      f"시간 표시를 {wanted['duration']:g}초 동안 연속 관찰하고 값이 바뀐 시각과 표시값을 기록한다."])
    expected=['상단바 오른쪽에 ‘로그아웃 남은 시간’ 안내 문구가 표시된다.',
              f"안내 문구의 글자 크기는 {wanted['label']['font_size']:g}px이다.",
              f"안내 문구의 글자 굵기는 {wanted['label']['font_weight']}이다.",
              f"안내 문구의 글자색은 {wanted['label']['color']}이다.",
              '안내 문구 아래 시간 표시가 hh:mm:ss 형식이며 분·초는 각각 00~59이다.',
              f"시간 표시의 글자 크기는 {wanted['time']['font_size']:g}px이다.",
              f"시간 표시의 글자 굵기는 {wanted['time']['font_weight']}이다.",
              f"시간 표시의 글자색은 {wanted['time']['color']}이다.",
              '시간 표시가 1초 간격으로 1초씩 감소한다.']
    numbered=lambda rows:'\n'.join(f'{i}. {line}' for i,line in enumerate(rows,1))
    return dict(precondition=numbered(conditions),steps=numbered(steps),expected=numbered(expected))


def actions(tc,parsed):
    result=[];sequence=iter(screens(tc));pending=next(sequence,None)
    for command in parsed:
        if command.get('type')=='click' and command.get('description')==pending:
            result.extend([dict(command,sidebar_menu=pending),dict(type='verify_logout_countdown',target=pending,description=pending+' 로그아웃 타이머 스타일·감소 관찰')])
            pending=next(sequence,None)
    return result or [dict(type='verify_logout_countdown',target=None,description='로그아웃 타이머 관찰')]


SNAPSHOT=r'''() => {
 const rect=e=>{const r=e.getBoundingClientRect();return {x:r.x,y:r.y,width:r.width,height:r.height,right:r.right,bottom:r.bottom};};
 const shown=e=>{const r=rect(e);if(r.width<=0||r.height<=0)return false;for(let p=e;p;p=p.parentElement){const s=getComputedStyle(p);if(s.display==='none'||s.visibility==='hidden'||Number(s.opacity)===0)return false;}return true;};
 const full=e=>{if(!shown(e))return false;const r=rect(e);if(r.x<0||r.y<0||r.right>innerWidth||r.bottom>innerHeight)return false;
  for(let p=e.parentElement;p;p=p.parentElement){const s=getComputedStyle(p),q=rect(p);
   if(/hidden|clip|auto|scroll/.test(s.overflowX)&&(r.x<q.x-.5||r.right>q.right+.5))return false;
   if(/hidden|clip|auto|scroll/.test(s.overflowY)&&(r.y<q.y-.5||r.bottom>q.bottom+.5))return false;}
  const hit=document.elementFromPoint(r.x+r.width/2,r.y+r.height/2);return !!hit&&(e.contains(hit)||hit.contains(e));};
 let roots=[...document.querySelectorAll('.dashboard-app-bar,.wco-app-bar')].filter(shown);
 if(!roots.length)roots=[...document.querySelectorAll('header,[role="banner"]')].filter(shown);
 if(roots.length!==1)return {error:'상단바를 하나로 식별하지 못함'};
 const top=roots[0],tr=rect(top);
 const all=[...top.querySelectorAll('p,span,label,div')].filter(e=>shown(e)&&e.innerText.trim()==='로그아웃 남은 시간');
 const labels=all.filter(e=>!all.some(other=>other!==e&&e.contains(other)));
 if(labels.length!==1)return {error:'상단바 안내 문구를 하나로 식별하지 못함'};
 const label=labels[0];let times=[];
 for(let group=label.parentElement;group&&group!==top;group=group.parentElement){
  const candidates=[...group.querySelectorAll('*')].filter(e=>shown(e)&&/^\d{2}:\d{2}:\d{2}$/.test(e.innerText.trim()));
  times=candidates.filter(e=>!candidates.some(other=>other!==e&&e.contains(other)));
  if(times.length)break;
 }
 if(times.length!==1)return {error:'안내 문구 아래 hh:mm:ss 시간을 하나로 식별하지 못함'};
 const timer=times[0],lr=rect(label),r=rect(timer),canvas=document.createElement('canvas');canvas.width=canvas.height=1;const ctx=canvas.getContext('2d',{willReadFrequently:true});
 const sample=e=>{const s=getComputedStyle(e);
  for(let p=e;p;p=p.parentElement){const ps=getComputedStyle(p);if(Number(ps.opacity)!==1||ps.filter!=='none'||ps.mixBlendMode!=='normal')return {error:'글자 표시 효과로 단색 판정 불가'};}
  ctx.clearRect(0,0,1,1);ctx.fillStyle=s.color;ctx.fillRect(0,0,1,1);const rgb=[...ctx.getImageData(0,0,1,1).data];
  if(rgb[3]!==255||s.webkitTextFillColor!==s.color)return {error:'투명/별도 채움 글자색 판정 불가'};
  const range=document.createRange();range.selectNodeContents(e);
  return {font_size:parseFloat(s.fontSize),font_weight:Number(s.fontWeight),color:'#'+rgb.slice(0,3).map(v=>v.toString(16).padStart(2,'0')).join('').toUpperCase(),visible:full(e)&&e.scrollWidth<=e.clientWidth+1&&range.getBoundingClientRect().width<=rect(e).width+1};};
 return {label:sample(label),time:sample(timer),display:timer.innerText.trim(),
 right:lr.x+lr.width/2>=tr.x+tr.width/2&&lr.right<=tr.right,
 below:r.y>=lr.bottom-.5&&r.x<lr.right&&r.right>lr.x};
}'''

# MutationObserver는 실제 텍스트 변경 시각을 기록한다. 폴링은 스타일/요소 변경 누락을 보완한다.
OBSERVE='''async duration=>{
 const sample=('''+SNAPSHOT+''');const samples=[];const start=performance.now();let signature='';
 const record=()=>{const value=sample(),key=JSON.stringify(value);if(key!==signature){signature=key;samples.push({...value,at_ms:performance.now()-start});}};
 record();const observer=new MutationObserver(record);observer.observe(document.documentElement,{subtree:true,childList:true,characterData:true,attributes:true});
 const poll=setInterval(record,100);
 try{await new Promise(resolve=>setTimeout(resolve,duration*1000));record();return {samples,observed_ms:performance.now()-start};}
 finally{observer.disconnect();clearInterval(poll);}
}'''


def collect(page,tc,target):
    state=dict(screen=target)
    try:
        wanted=requirements(tc);state['expected']=wanted
        if target not in wanted['screens'] or urlsplit(page.url).path.rstrip('/')!=ROUTES[target]:raise ValueError('타이머 대상 화면 진입 근거 없음')
        deadline=time.monotonic()+5
        while True:
            baseline=page.evaluate(SNAPSHOT)
            if not baseline.get('error'):break
            if time.monotonic()>=deadline:raise ValueError(baseline['error'])
            page.wait_for_timeout(100)
        remaining=parse_display_time(baseline.get('display'))
        if remaining is None or remaining<=wanted['duration']+1:raise ValueError('형식이 유효하고 관찰 시간보다 충분히 남은 타이머가 필요함')
        state.update(page.evaluate(OBSERVE,wanted['duration']))
        state['path']=urlsplit(page.url).path.rstrip('/')
    except Exception as exc:state['error']=str(exc)
    return state


def verify(tc,evidence):
    try:wanted=requirements(tc)
    except ValueError as exc:return 'FAIL','검증 불가: '+str(exc)
    if not evidence or len(evidence)!=len(wanted['screens']):return 'FAIL','검증 불가: 화면별 카운트다운 근거 부족'
    for screen,state in zip(wanted['screens'],evidence):
        if state.get('error'):return 'FAIL','검증 불가: '+screen+' '+state['error']
        if state.get('screen')!=screen or state.get('path')!=ROUTES[screen]:return 'FAIL','검증 불가: 타이머 수집 화면·순서 불일치'
        if state.get('observed_ms',0)<wanted['duration']*1000-20:return 'FAIL','검증 불가: 타이머 관찰 시간 부족'
        samples=state.get('samples') or [];changes=[];previous=None
        for sample in samples:
            if sample.get('error'):return 'FAIL','검증 불가: '+sample['error']
            if not sample.get('right') or not sample.get('below'):return 'FAIL','타이머가 상단바 오른쪽 또는 안내 문구 아래에 표시되지 않음'
            for key,label in (('label','안내 문구'),('time','시간 표시')):
                actual=sample.get(key) or {};expected=wanted[key]
                if actual.get('error') or not actual.get('visible'):return 'FAIL','검증 불가: '+label+' 표시/색상 근거 부족'
                for name in ('color','font_weight'):
                    if actual.get(name)!=expected[name]:return 'FAIL',f"{label} {name} 불일치: 기대 {expected[name]}, 실제 {actual.get(name)}"
                if abs(actual.get('font_size',-1)-expected['font_size'])>.5:return 'FAIL',f"{label} 글자 크기 불일치: 기대 {expected['font_size']:g}px, 실제 {actual.get('font_size')}px"
            seconds=parse_display_time(sample.get('display'))
            if seconds is None:return 'FAIL','시간 표시가 유효한 hh:mm:ss 형식이 아님'
            if previous is not None and seconds!=previous:
                if previous-seconds!=1:return 'FAIL',f'타이머가 1초씩 감소하지 않음: {previous}초 → {seconds}초'
                changes.append(sample.get('at_ms',0))
            previous=seconds
        if len(changes)<3:return 'FAIL','관찰 구간에서 타이머 감소 3회 이상을 확인하지 못함'
        if changes[0]>1000+TICK_TOLERANCE_MS or state['observed_ms']-changes[-1]>1000+TICK_TOLERANCE_MS:
            return 'FAIL','관찰 구간 시작 또는 끝에서 1초 기준을 넘는 타이머 정체가 발생함'
        intervals=[b-a for a,b in zip(changes,changes[1:])]
        if any(abs(ms-1000)>TICK_TOLERANCE_MS for ms in intervals):return 'FAIL','타이머 갱신 간격이 1초 기준과 다름: '+', '.join(f'{ms:.0f}ms' for ms in intervals)
    return 'PASS',f"상단바 타이머 안내/시간 스타일·hh:mm:ss·오른쪽/아래 배치와 {wanted['duration']:g}초 관찰 중 1초씩 감소·갱신 간격 확인"
