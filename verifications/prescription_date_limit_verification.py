"""종료일 이후 시작일의 달력 선택 제한을 확인한다. 비활성 날짜는 클릭하지 않는다."""
from datetime import date
import re
import time
from urllib.parse import parse_qs, urlsplit


def applies(tc):
    title = re.sub(r'\s+', '', str(tc.get('title') or ''))
    context = re.sub(r'\s+', '', ' '.join(str(tc.get(k) or '') for k in ('sheet_name', 'precondition', 'steps')))
    return all(s in title for s in ('처방일', '시작일', '종료일', '제한')) and '검사접수' in context


def action(tc):
    text = str(tc.get('steps') or '') + '\n' + str(tc.get('expected') or '')
    def value(label):
        matches = set(re.findall(label + r'[^\d\n]{0,35}(\d{4}-\d{2}-\d{2})', text))
        return next(iter(matches)) if len(matches) == 1 else None
    return dict(type='verify_prescription_date_limit', description='종료일 이후 시작일 달력 비활성 상태 검증',
                end=value('종료일'), target=value('시작일'))


def collect(page, command):
    evidence = dict(end=command.get('end'), target=command.get('target'), responses=[], invalid_requests=[])
    handlers = []
    fields = None
    try:
        end, target = evidence['end'], evidence['target']
        if not end or not target:
            return dict(evidence, error='종료일과 선택 제한 대상 시작일을 YYYY-MM-DD로 명시해야 함')
        if date.fromisoformat(target) <= date.fromisoformat(end):
            return dict(evidence, error='제한 대상 시작일은 종료일보다 늦어야 함')
        if not re.search(r'(?:^|/)receptions?/?$', urlsplit(page.url).path):
            return dict(evidence, error='검사 접수 목록 경로 진입 근거 없음')
        page.wait_for_load_state('networkidle', timeout=5000)
        fields = page.locator('input[placeholder="YYYY-MM-DD"]').filter(visible=True)
        if fields.count() != 2:
            return dict(evidence, error='처방일 입력란 두 개를 식별하지 못함')
        evidence['before_inputs'] = [fields.nth(i).input_value() for i in range(2)]
        initial = parse_qs(urlsplit(page.url).query)
        if any(evidence['before_inputs']) or initial.get('startDate') or initial.get('endDate'):
            return dict(evidence, error='시작일·종료일이 모두 비어 있어야 하는 초기 조건 불충족')

        def related(request):
            parsed = urlsplit(request.url)
            if request.resource_type in ('xhr', 'fetch') and re.search(r'(?:^|/)receptions?(?:/(?:list|search))?/?$', parsed.path):
                return parse_qs(parsed.query)
            return None
        def requested(request):
            query = related(request)
            if query and query.get('startDate') and query.get('endDate'):
                try:
                    if date.fromisoformat(query['startDate'][0]) > date.fromisoformat(query['endDate'][0]):
                        evidence['invalid_requests'].append({k: query[k] for k in ('startDate', 'endDate')})
                except ValueError:
                    evidence['invalid_requests'].append({'error': '조회 기간 날짜 해석 실패'})
        def response(value):
            query = related(value.request)
            if query is not None and query.get('endDate') == [end]:
                evidence['responses'].append(value.status)
        for event, handler in (('request', requested), ('response', response)):
            page.on(event, handler)
            handlers.append((event, handler))
        field = fields.nth(1)
        field.click(timeout=3000)
        field.fill(end, timeout=3000)
        field.press('Tab', timeout=3000)
        field.press('Escape', timeout=3000)
        deadline = time.monotonic() + 5
        while parse_qs(urlsplit(page.url).query).get('endDate') != [end] and time.monotonic() < deadline:
            page.wait_for_timeout(100)
        if field.input_value() != end or parse_qs(urlsplit(page.url).query).get('endDate') != [end]:
            return dict(evidence, error='종료일 입력값 또는 URL 반영 실패')
        page.wait_for_load_state('networkidle', timeout=5000)
        fields.nth(0).click(timeout=3000)
        calendar = page.locator('.react-datepicker').filter(visible=True)
        calendar.wait_for(state='visible', timeout=3000)
        year, month, day = map(int, target.split('-'))
        for _ in range(120):
            match = re.search(r'(\d{4})년\s*(\d{1,2})월', calendar.inner_text())
            if not match:
                return dict(evidence, error='달력에 표시된 연·월을 식별하지 못함')
            current = tuple(map(int, match.groups()))
            if current == (year, month):
                break
            direction = 'Previous Month' if current > (year, month) else 'Next Month'
            arrow = calendar.locator('[aria-label="' + direction + '"]').filter(visible=True)
            if arrow.count() != 1:
                return dict(evidence, error='대상 월 이동이 제한되어 날짜 셀 직접 검증 불가')
            arrow.click(timeout=3000)
            previous = current
            deadline = time.monotonic() + 2
            while time.monotonic() < deadline:
                match = re.search(r'(\d{4})년\s*(\d{1,2})월', calendar.inner_text())
                if match and tuple(map(int, match.groups())) != previous:
                    break
                page.wait_for_timeout(100)
            else:
                return dict(evidence, error='달력 월 이동 반영 실패')
        else:
            return dict(evidence, error='달력 월 이동 120회 한도 초과')
        cell = calendar.locator('.react-datepicker__day:not(.react-datepicker__day--outside-month)').filter(
            has_text=re.compile(r'^\s*' + str(day) + r'\s*$'))
        if cell.count() != 1:
            return dict(evidence, error='대상 날짜 셀을 하나로 식별하지 못함')
        evidence['cell'] = dict(date=target, month=f'{year:04d}-{month:02d}', text=cell.inner_text(),
                                aria_disabled=cell.get_attribute('aria-disabled'),
                                disabled_class='react-datepicker__day--disabled' in (cell.get_attribute('class') or '').split())
        fields.nth(0).press('Escape', timeout=3000)
        page.wait_for_timeout(300)
        evidence['after_inputs'] = [fields.nth(i).input_value() for i in range(2)]
        query = parse_qs(urlsplit(page.url).query)
        evidence['applied_period'] = {k: query.get(k, [''])[0] for k in ('startDate', 'endDate')}
    except Exception as exc:
        evidence['error'] = '처방일 달력 제한 근거 수집 실패: ' + str(exc)
    finally:
        for event, handler in handlers:
            page.remove_listener(event, handler)
        if fields is not None:
            try:
                if fields.count() == 2:
                    fields.nth(0).press('Escape', timeout=1000)
            except Exception:
                pass
    return evidence


def verify(evidence):
    if not evidence or evidence.get('error'):
        return 'FAIL', '검증 불가: ' + ((evidence or {}).get('error') or '처방일 달력 제한 실행 근거 없음')
    cell = evidence.get('cell', {})
    if cell.get('aria_disabled') != 'true' or not cell.get('disabled_class'):
        return 'FAIL', '종료일 이후 시작일이 달력에서 비활성화되지 않음: ' + evidence['target']
    if evidence.get('after_inputs') != ['', evidence['end']]:
        return 'FAIL', '시작일 빈 값 또는 종료일 설정값이 유지되지 않음'
    if evidence.get('applied_period') != dict(startDate='', endDate=evidence['end']):
        return 'FAIL', '시작일 미적용 또는 종료일 조회 조건 유지 실패'
    if evidence.get('invalid_requests'):
        return 'FAIL', '시작일이 종료일보다 늦은 조회 요청 발생'
    if not evidence.get('responses'):
        return 'FAIL', '검증 불가: 종료일 설정 조회 응답 근거 없음'
    if any(not 200 <= status < 300 for status in evidence['responses']):
        return 'FAIL', '종료일 설정 조회 실패'
    return 'PASS', f"종료일 {evidence['end']} 유지 + 시작일 달력 {evidence['target']} 비활성 + 역전 기간 미적용 확인"
