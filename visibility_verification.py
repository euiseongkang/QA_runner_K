"""노출/미노출을 상태 조건으로 해석하고 검색 단계별 목록 근거를 보존한다."""
import re
from urllib.parse import parse_qs, urlsplit

NEGATIVE = r'미노출|노출되지|표시되지|보이지|숨겨|숨김|사라'


def clauses(tc):
    result = []
    for line in str(tc.get('expected') or '').splitlines():
        if not line.strip():
            continue
        if not re.search(r'노출|표시|보이|숨김|숨겨|사라', line):
            return []  # 다른 검증 기준을 무시하고 일부 조건만으로 PASS를 주지 않는다.
        targets = re.findall(r'''["'“”‘’]([^"'“”‘’]+)["'“”‘’]|\[([^\[\]]+)\]''', line)
        targets = [a or b for a, b in targets]
        if len(targets) != 1:
            return []
        result.append({'target': targets[0], 'visible': not bool(re.search(NEGATIVE, line)),
                       'conditional': '경우' in line})
    return result


def is_phone_search(tc):
    rules = clauses(tc)
    return (bool(rules) and bool(re.search(r'휴대전화|휴대폰|전화번호',
            str(tc.get('title') or '') + str(tc.get('steps') or '')))
            and all(re.fullmatch(r'0\d[\d\s\-–—−]{7,}', r['target']) for r in rules))


def query_key(value):
    # 검색값의 하이픈 유무는 별개 조건이다. 숫자로 정규화해서 합치지 않는다.
    return str(value).strip().translate(str.maketrans('–—−', '---'))


def response_matches(response, query):
    try:
        if response.request.resource_type not in ('xhr', 'fetch') or not 200 <= response.status < 300:
            return False
        url = urlsplit(response.url)
        if not re.search(r'(?:^|/)patients?(?:/(?:list|search))?/?$', url.path, re.I):
            return False
        values = parse_qs(url.query).get('keyword', [])
        if not values:
            data = response.request.post_data_json
            values = [data['keyword']] if isinstance(data, dict) and 'keyword' in data else []
        return len(values) == 1 and query_key(values[0]) == query_key(query)
    except Exception:
        return False


def phone_rows(page):
    return page.evaluate(r'''() => {
      const visible = e => e.getClientRects().length && getComputedStyle(e).visibility !== 'hidden';
      const tables = [...document.querySelectorAll('table, [role="table"], [role="grid"]')]
        .filter(visible).filter(t => /환자명/.test(t.innerText) && /휴대전화번호|휴대폰번호/.test(t.innerText));
      if (tables.length !== 1) return null;
      const table = tables[0];
      const headers = [...table.querySelectorAll('thead th, [role="columnheader"]')];
      const col = headers.findIndex(h => /^(휴대전화번호|휴대폰번호)$/.test(h.innerText.replace(/\s/g,'')));
      if (col < 0) return null;
      const rows = [...table.querySelectorAll('tbody tr, [role="row"]')].filter(visible)
        .map(r => [...r.querySelectorAll('td, [role="cell"], [role="gridcell"]')])
        .filter(c => c.length === headers.length);
      return rows.map(c => c[col].innerText);
    }''')


def capture_search(page, query, submit):
    state = {'query': query, 'loaded': False, 'phones': None}
    def on_response(response):
        if response_matches(response, query):
            state['loaded'] = True
    page.on('response', on_response)
    try:
        submit()
        state['phones'] = phone_rows(page)
        return state
    finally:
        page.remove_listener('response', on_response)


def judge_phone(tc, searches):
    for index, rule in enumerate(clauses(tc), 1):
        matches = [s for s in searches or [] if query_key(s['query']) == query_key(rule['target'])]
        if not matches or not matches[-1]['loaded'] or matches[-1]['phones'] is None:
            return '확인 필요', f'검색 조건 {index}의 조회 완료/환자 목록 근거가 부족함'
        phones = matches[-1]['phones']
        target = re.sub(r'\D', '', rule['target'])
        found = [re.sub(r'\D', '', p) == target for p in phones]
        valid = bool(found) and all(found) if rule['visible'] else not phones
        if not valid:
            # 잘못된 환자가 표시되는 것도 검색 성공으로 취급하지 않는다.
            return 'FAIL', f'검색 조건 {index}의 환자 목록이 예상 {"노출" if rule["visible"] else "미노출"} 상태와 다름'
    return 'PASS', '각 검색값의 조회 완료와 환자 목록 노출/미노출을 단계별로 확인함'


def capture_visibility(page, tc):
    rules = clauses(tc)
    if not rules or any(r['conditional'] for r in rules):
        return None
    values = []
    for rule in rules:
        targets = page.get_by_text(rule['target'], exact=True)
        values.append(any(targets.nth(i).is_visible() for i in range(targets.count())))
    return values


def judge_visibility(tc, evidence):
    rules = clauses(tc)
    if not rules or evidence is None or len(evidence) != len(rules):
        return '확인 필요', '노출/미노출 대상 또는 단계별 상태 근거를 확인하지 못함'
    for index, (rule, visible) in enumerate(zip(rules, evidence), 1):
        if visible != rule['visible']:
            return 'FAIL', f'조건 {index}의 대상이 예상 {"노출" if rule["visible"] else "미노출"} 상태와 다름'
    return 'PASS', '명시된 대상의 실제 노출/미노출 상태를 확인함'
