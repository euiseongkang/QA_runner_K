"""긴 환자명의 실제 말줄임과 목록 행·열 배치를 측정한다."""
import re


def applies(tc):
    text = str(tc.get('title') or '') + str(tc.get('expected') or '')
    return bool(re.search(r'긴\s*환자명|환자명.*(?:말줄임|줄바꿈|정렬)', text))


def capture(page):
    try:
        return page.evaluate(r'''() => {
            const visible = e => e.getClientRects().length && getComputedStyle(e).visibility !== 'hidden';
            const norm = s => s.replace(/\s/g, '');
            const tables = [...document.querySelectorAll('table')].filter(visible).filter(t =>
                [...t.querySelectorAll('thead th')].some(h => norm(h.innerText) === '환자명'));
            if (tables.length !== 1) return null;
            const table = tables[0];
            const headers = [...table.querySelectorAll('thead th')];
            const index = headers.findIndex(h => norm(h.innerText) === '환자명');
            const canvas = document.createElement('canvas').getContext('2d');
            const rect = e => { const r = e.getBoundingClientRect();
                return {left:r.left, width:r.width, top:r.top, height:r.height}; };
            const rows = [];
            for (const row of table.querySelectorAll('tbody tr')) {
                const cells = [...row.querySelectorAll(':scope > td')];
                if (!visible(row) || cells.length !== headers.length) continue;
                const cell = cells[index];
                // 이름만 가진 말단 요소를 사용해 내 환자 배지를 이름에 섞지 않는다.
                const leaves = [...cell.querySelectorAll('span, a, p')].filter(e =>
                    visible(e) && e.innerText.trim() && !e.querySelector('span, a, p'));
                const names = leaves.filter(e => e.innerText.trim() !== '내 환자');
                const name = names[0] || cell;
                const text = name.innerText.trim();
                const cs = getComputedStyle(name), cr = cell.getBoundingClientRect(), nr = name.getBoundingClientRect();
                canvas.font = cs.font || `${cs.fontSize} ${cs.fontFamily}`;
                const natural = canvas.measureText(text).width + Math.max(0, text.length-1)*(parseFloat(cs.letterSpacing)||0);
                const available = Math.min(name.clientWidth || nr.width, cr.width);
                if (!text || available <= 0) continue;
                const long = natural > available + 1 || name.scrollWidth > available + 1;
                const ellipsis = cs.textOverflow === 'ellipsis' && cs.whiteSpace === 'nowrap'
                    && ['hidden','clip'].includes(cs.overflowX) && name.clientWidth > 0
                    && name.scrollWidth > name.clientWidth + 1;
                const contained = nr.left >= cr.left-1 && nr.right <= cr.right+1
                    && nr.top >= cr.top-1 && nr.bottom <= cr.bottom+1;
                rows.push({height:row.getBoundingClientRect().height, long, ellipsis, contained,
                    cells:cells.map(rect)});
            }
            return {rows, headers:headers.map(rect)};
        }''')
    except Exception:
        return None


def verify(evidence):
    if not evidence:
        return '확인 필요', '환자명 열이 있는 환자 목록을 하나로 식별하지 못함'
    rows = evidence.get('rows', [])
    long_rows = [row for row in rows if row['long']]
    references = [row for row in rows if not row['long']]
    if not long_rows:
        return '확인 필요', '현재 목록에 이름 표시 영역을 실제로 초과하는 긴 환자명이 없음'
    if any(not row['ellipsis'] or not row['contained'] for row in long_rows):
        return 'FAIL', '긴 환자명의 실제 말줄임 또는 이름 셀 내부 표시 조건을 충족하지 못함'
    if not references:
        return '확인 필요', '행 높이와 열 정렬을 비교할 일반 환자 행이 없음'
    heights = sorted(row['height'] for row in references)
    # 첫 행 경계·개별 배지 등 일부 일반 행의 차이를 전체 비교 실패로 만들지 않는다.
    # 1px 이내로 일치하는 과반수 기준 그룹을 요구하므로 임의의 높이를 선택하지 않는다.
    groups = [[h for h in heights if start <= h <= start + 1] for start in heights]
    group = max(groups, key=len)
    if len(group) <= len(heights) / 2:
        return '확인 필요', f'일반 환자 행의 과반수 높이 기준을 찾지 못함 ({min(heights):.1f}~{max(heights):.1f}px)'
    baseline = group[len(group)//2]
    if any(abs(row['height']-baseline) > 1 for row in long_rows):
        return 'FAIL', '긴 환자명의 행 높이가 일반 환자 행보다 달라짐 (허용 오차 1px)'
    headers = evidence['headers']
    for row in long_rows:
        for cell, header in zip(row['cells'], headers):
            if abs(cell['left']-header['left']) > 1 or abs(cell['width']-header['width']) > 1:
                return 'FAIL', '긴 환자명 행의 셀 위치 또는 너비가 열 헤더 정렬과 다름'
            if abs(cell['top']-row['cells'][0]['top']) > 1 or abs(cell['height']-row['height']) > 1:
                return 'FAIL', '긴 환자명 행 내부 셀의 높이 또는 수직 정렬이 다름'
    return 'PASS', f'긴 환자명 {len(long_rows)}건 말줄임·셀 내부 표시·높이·열 정렬 유지 확인 (기준 {baseline:.1f}px, 일반 행 {len(group)}/{len(heights)}건 일치, 허용 오차 1px)'
