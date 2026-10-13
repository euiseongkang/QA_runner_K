"""화면에 표시되는 테이블 헤더 구성과 좌우 순서를 검증한다."""
import re


def applies(tc):
    title = str(tc.get('title') or '')
    expected = str(tc.get('expected') or '')
    return bool(re.search(r'컬럼|칼럼|열\s*(?:구성|순서)', title)
                and '순서' in expected and ',' in expected)


def expected_columns(tc):
    text = str(tc.get('expected') or '')
    # 단일 헤더 목록만 지원한다. 여러 기대 문장이 섞이면 추측하지 않는다.
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if len(lines) != 1:
        return []
    text = re.sub(r'^\s*\d+\.\s*', '', lines[0])
    text = re.split(r'\s*순서(?:대로|로|이다|입니다)', text, maxsplit=1)[0]
    items = [item.strip().strip('[]\"\'“”‘’') for item in text.split(',')]
    return items if len(items) > 1 and all(items) else []


def capture(page, tc):
    columns = expected_columns(tc)
    if not columns:
        return {'error': '예상 결과의 컬럼 목록을 하나로 해석하지 못함'}
    try:
        return page.evaluate(r'''expected => {
          const visible=e=>!!e.getClientRects().length && getComputedStyle(e).visibility!=='hidden';
          const norm=s=>(s||'').replace(/\s/g,'').toLowerCase();
          const candidates=[...document.querySelectorAll('table,[role="table"],[role="grid"]')]
            .filter(visible).map(table=>{
              const heads=[...table.querySelectorAll('thead th,thead td,[role="columnheader"]')]
                .filter(visible).map(e=>({text:e.innerText.trim(),left:e.getBoundingClientRect().left,
                  top:e.getBoundingClientRect().top,span:Number(e.getAttribute('colspan')||1)}));
              return {table,heads};
            }).filter(({heads})=>expected.filter(name=>heads.some(h=>norm(h.text)===norm(name))).length>=2);
          if(candidates.length!==1)return {error:'대상 테이블 헤더를 하나로 식별하지 못함',table_count:candidates.length};
          const {table,heads}=candidates[0];
          if(heads.some(h=>h.span>1)||heads.some(h=>Math.abs(h.top-heads[0].top)>2))
            return {error:'병합 또는 여러 줄의 헤더 구조는 별도 검증이 필요함'};
          return {headers:heads.sort((a,b)=>a.left-b.left).map(h=>h.text),
            busy:table.matches('[aria-busy="true"]')||!!table.querySelector('[role="progressbar"]')};
        }''', columns)
    except Exception as exc:
        return {'error': str(exc)}


def verify(evidence, tc):
    expected = expected_columns(tc)
    if not expected or not evidence or evidence.get('error'):
        return '확인 필요', '컬럼 구성·순서 근거 부족: ' + str((evidence or {}).get('error') or '헤더 수집 근거 없음')
    if evidence.get('busy'):
        return '확인 필요', '목록 조회가 아직 진행 중임'
    actual = evidence.get('headers')
    if not actual or any(not item.strip() for item in actual):
        return '확인 필요', '빈 헤더 또는 헤더 목록을 식별하지 못함'
    norm = lambda s: re.sub(r'\s+', '', s).casefold()
    wanted, found = list(map(norm, expected)), list(map(norm, actual))
    if wanted == found:
        return 'PASS', f'표시된 테이블 컬럼 {len(actual)}개의 구성과 순서 일치'
    missing = [name for name in expected if norm(name) not in found]
    extra = [name for name in actual if norm(name) not in wanted]
    details = []
    if missing:
        details.append('화면에 없는 컬럼: ' + ', '.join(missing))
    if extra:
        details.append('예상 결과에 없는 컬럼: ' + ', '.join(extra))
    if not missing and not extra:
        details.append('컬럼 순서 또는 중복 개수 불일치')
    details.append('실제 순서: ' + ' → '.join(actual))
    return 'FAIL', '컬럼 구성·순서 불일치 (' + ' / '.join(details) + ')'
