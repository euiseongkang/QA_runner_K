"""선택 열의 값 분류·사례 수집 규칙. UI나 페이지 이동을 직접 수행하지 않는다."""
import re

MOBILE = re.compile(r'(?:010(?:-\d{4}-\d{4}|\d{8})|01[16789](?:-\d{3,4}-\d{4}|\d{7,8}))', re.ASCII)
CASES = ('mobile', 'hyphen')
LABELS = dict(mobile='휴대전화번호 표시', hyphen="하이픈 '-' 표시")


def classify_mobile(value):
    if value == '-': return 'hyphen'
    if MOBILE.fullmatch(value): return 'mobile'
    return 'invalid'


def mobile_examples(snapshot, info):
    result = dict(page=info['page'], index=info['index'], rows=len(snapshot['rows']),
                  counts=dict.fromkeys(CASES, 0), examples={}, invalid=[])
    for row_number, row in enumerate(snapshot['rows'], 1):
        value = row[0]
        kind = classify_mobile(value)
        if kind == 'invalid':
            # 번호/환자명을 실행 사유에 그대로 노출하지 않는다.
            cause = '빈칸' if not value else value.lower() if value.lower() in ('null', 'undefined') else '지원 전화번호 형식 아님'
            result['invalid'].append(dict(row=row_number, cause=cause))
        else:
            result['counts'][kind] += 1
            result['examples'].setdefault(kind, dict(page=info['page'], row=row_number,
                display='-' if kind == 'hyphen' else '01*-****-****', digits=sum(c.isdigit() for c in value)))
    return result


def required_found(pages, cases=CASES):
    return all(any(page['counts'][case] for page in pages) for case in cases)


def should_stop(pages):
    # 현재 페이지 전체를 검사한 뒤 종료한다. 두 사례 뒤에 있는 잘못된 셀도 FAIL 대상이다.
    if any(p['invalid'] for p in pages): return 'invalid_value'
    return 'goal_reached' if required_found(pages) else None


PATIENT_TYPES = ('외래', '입원', '응급')


def patient_type_examples(snapshot, info):
    result = dict(page=info['page'], index=info['index'], rows=len(snapshot['rows']),
                  counts=dict.fromkeys(PATIENT_TYPES, 0), examples={}, invalid=[])
    for row_number, row in enumerate(snapshot['rows'], 1):
        value = row[0].strip()
        if value not in PATIENT_TYPES:
            cause = '빈칸' if not value else value.lower() if value.lower() in ('null', 'undefined') else '허용하지 않은 환자 구분'
            result['invalid'].append(dict(row=row_number, cause=cause))
        else:
            result['counts'][value] += 1
            result['examples'].setdefault(value, dict(page=info['page'], row=row_number, display=value))
    return result


def patient_type_stop(pages):
    if any(p['invalid'] for p in pages): return 'invalid_value'
    return 'goal_reached' if required_found(pages, PATIENT_TYPES) else None


PROFILES = {
    'mobile_or_hyphen': dict(visit=mobile_examples, stop=should_stop, cases=CASES, labels=LABELS,
                           columns=['휴대전화번호'], aliases={'휴대전화번호': ['휴대폰번호']},
                           success="휴대전화번호 표시·하이픈 '-' 표시 각각 수집"),
    'patient_type': dict(visit=patient_type_examples, stop=patient_type_stop, cases=PATIENT_TYPES,
                         labels={value: value for value in PATIENT_TYPES}, columns=['환자 구분'], aliases={},
                         success='환자 구분 외래·입원·응급 각각 수집'),
}
