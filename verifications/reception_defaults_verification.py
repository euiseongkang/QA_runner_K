"""검사 접수 목록의 기본 필터를 읽기 전용 DOM 근거로 판정한다."""
import re
import time

STATUSES = ('대기', '진행', '종료', '취소')


def applies(tc):
    text = re.sub(r'\s+', '', str(tc.get('title') or ''))
    return '검사접수' in text and ('기본' in text or '조회조건' in text)


def requirements(tc):
    expected = str(tc.get('expected') or '')
    states = {}
    for clause in re.split(r'[\n\r]|(?<=다)\.|\d+\.\s*', expected):
        for status in STATUSES:
            if status not in clause:
                continue
            if status == '취소' and re.search(r'취소\s*\]?\s*(?:제외|미선택)', clause):
                states[status] = False
            else:
                cleaned = re.sub(r'\(?취소\s*제외\)?', '', clause)
                states[status] = not bool(re.search(r'미선택|선택되어?\s*있지\s*않|선택되지\s*않', cleaned))
    size = re.search(r'(\d+)\s*개씩\s*보기', expected)
    current = re.search(r'(?:현재\s*페이지가?\s*|)(\d+)\s*페이지', expected)
    return {'states': states, 'size': int(size[1]) if size else None,
            'page': current[1] if current else None}


def _screen(page):
    return page.evaluate(r'''() => {
      const visible=e=>!!e.getClientRects().length && getComputedStyle(e).visibility!=='hidden';
      const norm=s=>(s||'').replace(/\s/g,'');
      const tables=[...document.querySelectorAll('table,[role="table"],[role="grid"]')].filter(visible)
        .filter(t=>{const headers=[...t.querySelectorAll('th,[role="columnheader"]')].map(e=>norm(e.innerText));
          return headers.includes('환자명') && headers.includes('검사명');});
      const sizes=[...document.querySelectorAll('select,button,[role="combobox"]')].filter(visible)
        .map(e=>e.tagName==='SELECT'?e.selectedOptions[0]?.textContent:e.innerText)
        .map(norm).filter(s=>/^\d+개씩보기$/.test(s));
      const active=[...document.querySelectorAll('a,button,[role="link"]')].filter(visible)
        .filter(e=>/^\d+$/.test(e.innerText.trim()))
        .filter(e=>(e.hasAttribute('aria-current')&&e.getAttribute('aria-current')!=='false')||
          e.getAttribute('aria-selected')==='true'||e.getAttribute('data-state')==='active'||e.classList.contains('active'));
      const triggers=[...document.querySelectorAll('button')].filter(visible)
        .filter(e=>e.id.startsWith('multi-select-')||e.hasAttribute('aria-haspopup'))
        .filter(e=>/검사\s*상태|대기|진행|종료|취소/.test(e.innerText+' '+(e.getAttribute('aria-label')||'')));
      return {list_visible:tables.length===1,
        busy:tables.length===1 && (tables[0].matches('[aria-busy="true"]')||!!tables[0].querySelector('[role="progressbar"]')),
        size:sizes.length===1?Number(sizes[0].match(/^\d+/)[0]):null,
        page:active.length===1?active[0].innerText.trim():null,
        trigger_id:triggers.length===1?triggers[0].id:null};
    }''')


def capture(page, tc):
    evidence = {'states': {}, 'errors': {}}
    trigger = None
    opened = False
    try:
        evidence.update(_screen(page))
        # 다중 선택 UI는 열어서 체크 상태만 읽고 원래 닫힌 상태로 복원한다.
        if evidence.get('trigger_id'):
            trigger = page.locator(
                '[id=' + '"' + evidence['trigger_id'].replace('"', '\\"') + '"]')
            if trigger.get_attribute('aria-expanded') != 'true':
                trigger.click(timeout=3000)
                opened = True
                controls = trigger.get_attribute('aria-controls')
                if controls:
                    page.locator('[id="' + controls.replace('"', '\"') + '"]').wait_for(state='visible', timeout=3000)
        controls = trigger.get_attribute('aria-controls') if trigger is not None else None
        scope_id = controls or (evidence['trigger_id'] + '-options' if trigger is not None else None)
        requested = list(requirements(tc)['states'])
        deadline = time.monotonic() + 3
        while True:
            reading = read_states(page, scope_id, requested)
            evidence['states'], evidence['errors'] = reading['states'], reading['errors']
            if all(value is not None for value in reading['states'].values()) or time.monotonic() >= deadline:
                break
            page.wait_for_timeout(100)
    except Exception as exc:
        evidence['error'] = str(exc)
    finally:
        if opened and trigger is not None:
            try:
                trigger.click(timeout=3000)
            except Exception:
                evidence['error'] = '검사 상태 드롭다운을 원래 상태로 복원하지 못함'
    return evidence


def read_states(page, scope_id, statuses):
    # 체크 아이콘의 alt="check"가 접근성 이름에 포함될 수 있으므로 라벨 DOM을 사용한다.
    # 환자 행의 '대기/진행/종료' 배지는 검사 상태 드롭다운 안에서만 찾도록 분리한다.
    return page.evaluate(r'''({scope_id,statuses}) => {
      const scope=scope_id?document.getElementById(scope_id):document;
      const norm=s=>(s||'').replace(/\s/g,'');
      const visible=e=>!!e.getClientRects().length && getComputedStyle(e).visibility!=='hidden';
      const states={}, errors={};
      for(const status of statuses) {
        const roles=scope?[...scope.querySelectorAll('[role="checkbox"]')].filter(visible)
          .filter(e=>!e.closest('table,[role="table"],[role="grid"]'))
          .filter(e=>norm(e.querySelector('[data-checkbox-label]')?.textContent || e.textContent)===norm(status)):[];
        const natives=scope?[...scope.querySelectorAll('input[type="checkbox"]')]
          .filter(e=>!e.closest('table,[role="table"],[role="grid"]'))
          .filter(e=>[...(e.labels||[]),...e.parentElement.querySelectorAll('label')]
            .some(label=>visible(label)&&norm(label.textContent)===norm(status))):[];
        if(roles.length===1) {
          const value=roles[0].getAttribute('aria-checked');
          states[status]=value==='true'?true:value==='false'?false:null;
          if(natives.length===1 && states[status]!==null && natives[0].checked!==states[status])
            states[status]=null;
        } else if(roles.length===0 && natives.length===1) {
          states[status]=natives[0].checked;
        } else states[status]=null;
        if(states[status]===null)errors[status]=!scope?'검사 상태 드롭다운이 표시되지 않음':
          `체크 상태 식별 불가 (ARIA ${roles.length}개, input ${natives.length}개)`;
      }
      return {states,errors};
    }''', {'scope_id': scope_id, 'statuses': statuses})


def verify(evidence, tc):
    if not evidence or evidence.get('error'):
        return '확인 필요', '검사 접수 기본 조건 수집 실패: ' + str((evidence or {}).get('error') or '근거 없음')
    if not evidence.get('list_visible'):
        return '확인 필요', '검사 접수 목록 영역을 하나로 식별하지 못함'
    if evidence.get('busy'):
        return '확인 필요', '검사 접수 목록 조회가 아직 진행 중임'
    req = requirements(tc)
    missing, wrong, confirmed = [], [], []
    for status, checked in req['states'].items():
        actual = evidence.get('states', {}).get(status)
        label = status + (' 선택' if checked else ' 미선택')
        if actual is None:
            missing.append(label + ' (' + evidence.get('errors', {}).get(status, '체크 상태 근거 없음') + ')')
        elif actual != checked:
            wrong.append(label)
        else:
            confirmed.append(label)
    for key, label in (('size', '페이지당 표시 개수'), ('page', '현재 페이지')):
        if req[key] is None:
            continue
        if evidence.get(key) is None:
            missing.append(label)
        elif evidence[key] != req[key]:
            wrong.append(f'{label}: 예상 {req[key]}, 실제 {evidence[key]}')
        else:
            confirmed.append(f'{label} {req[key]}')
    if wrong:
        return 'FAIL', '검사 접수 기본 조회 조건 불일치: ' + ', '.join(wrong)
    if missing:
        return '확인 필요', '검사 접수 기본 조회 조건 근거 부족: ' + ', '.join(missing)
    return 'PASS', '검사 접수 목록 표시 및 기본 조회 조건 확인: ' + ', '.join(confirmed)
