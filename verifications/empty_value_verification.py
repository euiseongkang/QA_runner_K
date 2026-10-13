"""환자 목록의 결측 표시를 열 단위로 확인한다. 환자 값은 증거에 저장하지 않는다."""
import re

FIELDS = ('휴대전화번호', '병동', '병실')


def applies(tc):
    text = str(tc.get('title') or '') + str(tc.get('expected') or '')
    return bool(re.search(r'값이?\s*없는|빈\s*항목|결측', text)
                and re.search(r"['\"‘’“”]\s*-\s*['\"‘’“”]|하이픈", str(tc.get('expected') or '')))


def fields(tc):
    text = ' '.join(str(tc.get(key) or '') for key in ('precondition', 'steps', 'expected'))
    return [field for field in FIELDS if field in text]


def capture(page, tc):
    targets = fields(tc)
    if not targets:
        return None
    try:
        return page.evaluate(r'''targets => {
            const visible = e => e.getClientRects().length && getComputedStyle(e).visibility !== 'hidden';
            const norm = s => s.replace(/\s/g, '');
            const tables = [...document.querySelectorAll('table')].filter(visible).filter(t =>
                [...t.querySelectorAll('thead th')].some(h => norm(h.innerText) === '환자명'));
            if (tables.length !== 1) return null;
            const table = tables[0], headers = [...table.querySelectorAll('thead th')].map(h => norm(h.innerText));
            const rows = [...table.querySelectorAll('tbody tr')].filter(visible)
                .map(r => [...r.querySelectorAll(':scope > td')]).filter(c => c.length === headers.length);
            const result = {};
            for (const target of targets) {
                const aliases = target === '휴대전화번호' ? ['휴대전화번호', '휴대폰번호'] : [target];
                const indices = headers.map((h,i) => aliases.includes(h) ? i : -1).filter(i => i >= 0);
                if (indices.length !== 1) { result[target] = null; continue; }
                const cells = rows.map(c => c[indices[0]]).filter(visible);
                result[target] = {total: cells.length,
                    blank: cells.filter(c => !c.innerText.trim()).length,
                    dash: cells.filter(c => c.innerText.trim() === '-').length};
            }
            return result;
        }''', targets)
    except Exception:
        return None


def verify(evidence, tc):
    targets = fields(tc)
    if not targets or not evidence:
        return '확인 필요', '검증할 항목 또는 환자 목록을 하나로 식별하지 못함'
    blanks = [field for field in targets if evidence.get(field) and evidence[field]['blank']]
    if blanks:
        return 'FAIL', '값이 없는 셀이 하이픈 대신 빈칸으로 표시됨: ' + ', '.join(blanks)
    missing = [field for field in targets if not evidence.get(field) or not evidence[field]['dash']]
    if missing:
        return '확인 필요', '열 또는 하이픈 표시를 검증할 결측 항목이 없음: ' + ', '.join(missing)
    counts = ', '.join(f"{field} {evidence[field]['dash']}건" for field in targets)
    return 'PASS', f'현재 환자 목록의 결측 표시가 하이픈(-)이며 지정 열에 빈 셀이 없음 ({counts})'
