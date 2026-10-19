"""서비스 기준 내일 날짜를 종료일 달력에서 선택하고 실제 조회를 확인한다."""
from datetime import datetime, timedelta, timezone
import re
import time
from urllib.parse import parse_qs, urlsplit

SERVICE_TIMEZONE = 'Asia/Seoul'


def service_today():
    # 현재 서비스의 한국 표준시(UTC+9). Windows EXE의 별도 tzdata 설치에 의존하지 않는다.
    return datetime.now(timezone(timedelta(hours=9), SERVICE_TIMEZONE)).date()


def applies(tc):
    title = re.sub(r'\s+', '', str(tc.get('title') or ''))
    context = re.sub(r'\s+', '', ' '.join(str(tc.get(k) or '') for k in ('sheet_name', 'precondition', 'steps')))
    return '처방일' in title and '미래' in title and '선택' in title and '검사접수' in context


def action(tc):
    steps = str(tc.get('steps') or '')
    return dict(type='verify_prescription_future_date', description='종료일 달력에서 내일 날짜 선택 및 조회 검증',
                supported='내일' in steps and '종료일' in steps)


def calendar_cell(page, target):
    calendar = page.locator('.react-datepicker').filter(visible=True)
    calendar.wait_for(state='visible', timeout=3000)
    for _ in range(120):
        match = re.search(r'(\d{4})년\s*(\d{1,2})월', calendar.inner_text())
        if not match:
            raise ValueError('달력 표시 연·월을 식별하지 못함')
        current = tuple(map(int, match.groups()))
        if current == (target.year, target.month):
            break
        direction = 'Previous Month' if current > (target.year, target.month) else 'Next Month'
        arrow = calendar.locator('[aria-label="' + direction + '"]').filter(visible=True)
        if arrow.count() != 1:
            raise ValueError('대상 월로 이동할 달력 컨트롤을 식별하지 못함')
        arrow.click(timeout=3000)
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            match = re.search(r'(\d{4})년\s*(\d{1,2})월', calendar.inner_text())
            if match and tuple(map(int, match.groups())) != current:
                break
            page.wait_for_timeout(100)
        else:
            raise ValueError('달력 월 이동 반영 실패')
    else:
        raise ValueError('달력 월 이동 120회 한도 초과')
    cell = calendar.locator('.react-datepicker__day:not(.react-datepicker__day--outside-month)').filter(
        has_text=re.compile(r'^\s*' + str(target.day) + r'\s*$'))
    if cell.count() != 1:
        raise ValueError('내일 날짜 셀을 하나로 식별하지 못함')
    return cell


def collect(page, command):
    today = service_today()
    tomorrow = today + timedelta(days=1)
    target = tomorrow.isoformat()
    evidence = dict(today=today.isoformat(), target=target, timezone=SERVICE_TIMEZONE,
                    responses=[], request_failed=0)
    handlers = []
    fields = None
    try:
        if not command.get('supported'):
            return dict(evidence, error='절차에 종료일 달력에서 내일 날짜를 선택한다고 명시해야 함')
        if not re.search(r'(?:^|/)receptions?/?$', urlsplit(page.url).path):
            return dict(evidence, error='검사 접수 목록 경로 진입 근거 없음')
        page.wait_for_load_state('networkidle', timeout=5000)
        fields = page.locator('input[placeholder="YYYY-MM-DD"]').filter(visible=True)
        if fields.count() != 2:
            return dict(evidence, error='처방일 입력란 두 개를 식별하지 못함')
        evidence['before_inputs'] = [fields.nth(i).input_value() for i in range(2)]
        query = parse_qs(urlsplit(page.url).query)
        if any(evidence['before_inputs']) or query.get('startDate') or query.get('endDate'):
            return dict(evidence, error='시작일·종료일이 모두 비어 있어야 하는 초기 조건 불충족')

        def related(request):
            parsed = urlsplit(request.url)
            if request.resource_type not in ('xhr', 'fetch') or not re.search(r'(?:^|/)receptions?(?:/(?:list|search))?/?$', parsed.path):
                return False
            query = parse_qs(parsed.query)
            return not query.get('startDate') and query.get('endDate') == [target]
        def response(value):
            if related(value.request):
                evidence['responses'].append(value.status)
        def failed(request):
            if related(request):
                evidence['request_failed'] += 1
        for event, handler in (('response', response), ('requestfailed', failed)):
            page.on(event, handler)
            handlers.append((event, handler))
        fields.nth(1).click(timeout=3000)
        cell = calendar_cell(page, tomorrow)
        evidence['cell'] = dict(date=target, month=tomorrow.strftime('%Y-%m'),
                                aria_disabled=cell.get_attribute('aria-disabled'),
                                disabled_class='react-datepicker__day--disabled' in (cell.get_attribute('class') or '').split())
        if evidence['cell']['aria_disabled'] != 'false' or evidence['cell']['disabled_class']:
            return dict(evidence, error='내일 날짜 셀이 활성 상태가 아니거나 활성 근거가 없음: ' + target)
        # 실제 달력 선택으로 실행한다. 입력값 강제 주입이나 강제 클릭은 사용하지 않는다.
        cell.click(timeout=3000)
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            query = parse_qs(urlsplit(page.url).query)
            if evidence['request_failed'] or (evidence['responses'] and query.get('endDate') == [target]
                                              and fields.nth(1).input_value() == target):
                break
            page.wait_for_timeout(100)
        if evidence['responses']:
            page.wait_for_load_state('networkidle', timeout=5000)
        evidence['after_inputs'] = [fields.nth(i).input_value() for i in range(2)]
        query = parse_qs(urlsplit(page.url).query)
        evidence['applied_period'] = {key: query.get(key, [''])[0] for key in ('startDate', 'endDate')}
    except Exception as exc:
        evidence['error'] = '미래 처방일 선택 근거 수집 실패: ' + str(exc)
    finally:
        for event, handler in handlers:
            page.remove_listener(event, handler)
        if fields is not None:
            try:
                if fields.count() == 2:
                    fields.nth(1).press('Escape', timeout=1000)
            except Exception:
                pass
    return evidence


def verify(evidence):
    if not evidence or evidence.get('error'):
        return 'FAIL', '검증 불가: ' + ((evidence or {}).get('error') or '미래 처방일 실행 근거 없음')
    target = evidence['target']
    cell = evidence.get('cell', {})
    if cell.get('aria_disabled') != 'false' or cell.get('disabled_class') is not False:
        return 'FAIL', '내일 날짜 활성 상태 근거 없음'
    if evidence.get('after_inputs') != ['', target]:
        return 'FAIL', '선택한 내일 종료일 또는 시작일 빈 값이 유지되지 않음'
    if evidence.get('applied_period') != dict(startDate='', endDate=target):
        return 'FAIL', '선택한 내일 종료일이 조회 조건과 일치하지 않음'
    if evidence.get('request_failed') or any(not 200 <= status < 300 for status in evidence.get('responses', [])):
        return 'FAIL', '미래 종료일 조건의 접수 조회 실패'
    if not evidence.get('responses'):
        return 'FAIL', '검증 불가: 미래 종료일 조건의 조회 응답 없음'
    return 'PASS', f"{evidence['timezone']} 기준 내일 {target} 달력 선택 + 시작일 빈 값 유지 + 해당 종료일 조회 성공 확인 (0건 허용)"
