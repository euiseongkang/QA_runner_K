"""환자 구분 탭 복귀를 실제 선택 상태와 환자 테이블 변화로 검증한다."""
import re
import time

CONTROLS = 'button, [role="tab"], [role="button"]'


def applies(tc):
    steps = str(tc.get('steps') or '')
    expected = str(tc.get('expected') or '')
    return (bool(re.search(r'\[외래\]', steps)) and bool(re.search(r'\[전체\]', steps))
            and bool(re.search(r'환자\s*구분', expected + str(tc.get('title') or '')))
            and bool(re.search(r'필터.*해제|전체.*(?:선택|복귀)|모든.*환자', expected)))


def snapshot(page):
    return page.evaluate(r'''() => {
        const visible = e => e.getClientRects().length && getComputedStyle(e).visibility !== 'hidden';
        const norm = s => s.replace(/\s/g, '');
        const controls = [...document.querySelectorAll('button, [role="tab"], [role="button"]')];
        const labels = ['전체', '외래', '입원', '응급'];
        const groups = new Set();
        for (const el of controls.filter(e => visible(e) && norm(e.innerText) === '외래')) {
            for (let p = el.parentElement; p && p !== document.body; p = p.parentElement) {
                const buttons = [...p.querySelectorAll('button, [role="tab"], [role="button"]')].filter(visible);
                if (buttons.length === 4 && labels.every(s => buttons.filter(b => norm(b.innerText) === s).length === 1)) {
                    groups.add(p); break;
                }
                if (buttons.length > 4) break;
            }
        }
        if (groups.size !== 1) return {selected: null, targets: {}, rows: [], types: []};
        const buttons = [...[...groups][0].querySelectorAll('button, [role="tab"], [role="button"]')].filter(visible);
        const active = buttons.filter(b => b.getAttribute('aria-selected') === 'true' ||
            b.getAttribute('aria-pressed') === 'true' || b.getAttribute('data-state') === 'active' ||
            [...b.classList].some(c => /^(active|selected|is-active|is-selected)$/.test(c)));
        // 배경색으로 선택을 표시하면 그룹 내 하나만 다른 배경을 갖는 경우에 한한다.
        const backgrounds = buttons.map(b => getComputedStyle(b).backgroundColor);
        const highlighted = buttons.filter((b, i) => backgrounds[i] !== 'rgba(0, 0, 0, 0)' &&
            backgrounds[i] !== 'transparent' && backgrounds.filter(c => c === backgrounds[i]).length === 1 &&
            backgrounds.some(c => backgrounds.filter(x => x === c).length === 3));
        const chosen = active.length === 1 ? active : active.length === 0 ? highlighted : [];
        const tables = [...document.querySelectorAll('table, [role="table"], [role="grid"]')]
            .filter(visible).filter(t => /환자명/.test(t.innerText) && /환자\s*구분/.test(t.innerText));
        let rows = [], types = [];
        if (tables.length === 1) {
            const table = tables[0];
            const headers = [...table.querySelectorAll('thead th, [role="columnheader"]')];
            const col = headers.findIndex(h => norm(h.innerText) === '환자구분');
            if (col >= 0) for (const row of table.querySelectorAll('tbody tr, [role="row"]')) {
                const cells = [...row.querySelectorAll('td, [role="cell"], [role="gridcell"]')];
                if (visible(row) && cells.length > col) {
                    rows.push(row.innerText.trim()); types.push(norm(cells[col].innerText));
                }
            }
        }
        return {selected: chosen.length === 1 ? norm(chosen[0].innerText) : null,
            targets: Object.fromEntries(buttons.map(b => [norm(b.innerText), controls.indexOf(b)])), rows, types};
    }''')


def verify(evidence):
    if not evidence:
        return '확인 필요', '환자 구분 탭의 선택 상태와 목록 변화 근거를 수집하지 못함'
    before, after = evidence.get('before', {}), evidence.get('after', {})
    if before.get('selected') != '외래' or after.get('selected') != '전체':
        return '확인 필요', '외래 선택 후 전체 탭으로 복귀한 상태를 확인하지 못함'
    if not before.get('rows') or not after.get('rows') or before['rows'] == after['rows']:
        return '확인 필요', '전체 탭 복귀 후 환자 목록 갱신 근거가 부족함'
    before_types, after_types = before.get('types', []), after.get('types', [])
    if (before_types and all(t == '외래' for t in before_types)
            and '외래' in after_types and any(t in ('입원', '응급') for t in after_types)):
        return 'PASS', '외래→전체 탭 선택 변경 + 목록 갱신 + 외래와 다른 환자 구분 행의 동시 노출 확인'
    return '확인 필요', '전체 탭은 선택됐으나 외래 외 환자 구분의 조회 근거가 부족함'


def click_and_collect(page, target, evidence=None):
    state = snapshot(page)
    index = state.get('targets', {}).get(target)
    if index is None:
        raise ValueError('환자 구분 탭 그룹의 클릭 대상을 하나로 식별하지 못함')
    page.locator(CONTROLS).nth(index).click(timeout=5000)
    deadline = time.monotonic() + 5
    while True:
        page.wait_for_timeout(100)
        after = snapshot(page)
        if target == '외래':
            if after.get('selected') == '외래' and after.get('types') and all(t == '외래' for t in after['types']):
                return {'before': after}
        else:
            result = {**(evidence or {}), 'after': after}
            if verify(result)[0] == 'PASS':
                return result
        if time.monotonic() >= deadline:
            return {'before': after} if target == '외래' else result
