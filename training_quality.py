"""실행된 학습 쌍의 품질과 사람이 확인한 요구사항 보정을 검사한다.

최초 TC는 정답의 절대 기준이 아니다. 잘못된 요구사항을 고친 PASS 실행은
review.requirement_corrections에 보정 전·후 구절과 근거를 남겨 사용할 수 있다.
검사는 복사본에만 보정을 적용하며 실행 원문과 학습 입력은 변경하지 않는다.
"""
import re

import tc_optimization

FIELDS = ('precondition', 'steps', 'expected')
LABELS = dict(precondition='사전조건', steps='테스트 절차', expected='예상 결과')
CORRECTION_KEYS = ('field', 'before', 'after', 'reason')


def _unique(items):
    return list(dict.fromkeys(items))


def _safe_quality_message(message):
    # 기존 검사 중 시트명만 입력값을 오류 문장에 삽입한다. 원문/비밀값은
    # 내보내기 요약의 오류 사유로 복사하지 않는다.
    if message.startswith('시트 화면 맥락 누락:'):
        return '시트 화면 맥락 누락: 사전조건과 메뉴 진입·조회 완료 절차를 확인하세요.'
    return message


def _check_fields(value, description, errors):
    if not isinstance(value, dict):
        errors.append(description + '은 TC 객체여야 합니다.')
        return False
    valid = True
    for field in FIELDS:
        content = value.get(field)
        if (not isinstance(content, str) or len(content) > 4000
                or (field != 'precondition' and not content.strip())):
            errors.append(description + '의 ' + LABELS[field] + ' 문자열·필수 내용·4000자 제한을 확인하세요.')
            valid = False
    return valid


def _format_checks(target, errors, warnings):
    for field in FIELDS:
        content = target[field]
        label = LABELS[field]
        if tc_optimization.has_repetition(content):
            errors.append(label + '에 같은 문장이 과도하게 반복되어 학습에서 제외합니다.')
        lines = [line.strip() for line in content.splitlines() if line.strip()]
        if not lines:
            continue
        numbered = [re.match(r'^(\d+)[.)]\s*(.*)$', line) for line in lines]
        if any(re.fullmatch(r'PASS|FAIL', re.sub(r'^\d+[.)]\s*', '', line), re.I) for line in lines):
            errors.append(label + '의 독립 PASS/FAIL 항목은 구체적인 동작·기대 상태를 대신할 수 없습니다.')
        if any(match and not match.group(2).strip() for match in numbered):
            errors.append(label + '에 내용이 없는 번호 항목이 있습니다.')
        if all(numbered):
            if [int(match.group(1)) for match in numbered] != list(range(1, len(lines) + 1)):
                errors.append(label + '의 번호는 1부터 빠짐없이 순서대로 작성해야 합니다.')
        else:
            warnings.append(label + '이 일관된 번호 목록이 아니므로 서식을 검토하세요.')


def _apply_corrections(original, target, review, errors):
    adjusted = dict(original)
    accepted = []
    declared = review.get('requirement_corrections', [])
    if not isinstance(declared, list):
        errors.append('요구사항 보정 기록은 field, before, after, reason을 가진 목록이어야 합니다.')
        return adjusted, accepted
    occupied = {field: set() for field in FIELDS}
    replacements = {field: {} for field in FIELDS}
    for index, correction in enumerate(declared, 1):
        label = f'요구사항 보정 {index}번'
        if not isinstance(correction, dict):
            errors.append(label + '의 필드와 보정 전·후 구절, 근거를 확인하세요.')
            continue
        field = correction.get('field')
        if (field not in FIELDS or any(not isinstance(correction.get(key), str)
                                     or not correction[key].strip() for key in CORRECTION_KEYS)):
            errors.append(label + '의 필드와 보정 전·후 구절, 근거를 확인하세요.')
            continue
        before, after = correction['before'], correction['after']
        if before == after or before not in original[field] or after not in target[field]:
            errors.append(label + '은 원문의 보정 전 구절과 실행 정답의 보정 후 구절에 정확히 일치해야 합니다.')
            continue
        positions = set()
        offset = 0
        while True:
            start = original[field].find(before, offset)
            if start < 0:
                break
            positions.update(range(start, start + len(before)))
            offset = start + len(before)
        if occupied[field] & positions:
            errors.append(label + '이 다른 보정 범위와 겹칩니다. 겹치지 않는 구절로 검토하세요.')
            continue
        occupied[field].update(positions)
        replacements[field][before] = after
        accepted.append({key: correction[key] for key in CORRECTION_KEYS})
    # 한 보정의 결과가 다음 보정의 입력으로 다시 치환되지 않게 동시에 적용한다.
    for field, values in replacements.items():
        if values:
            pattern = '|'.join(re.escape(before) for before in sorted(values, key=len, reverse=True))
            adjusted[field] = re.sub(pattern, lambda match: values[match.group()], original[field])
    return adjusted, accepted


def assess_pair(original, record):
    """Return errors, warnings and valid explicit corrections without any writes.

    ``record['tc']`` is the TC actually executed, never ``corrected_tc`` edited
    after execution. The caller must independently require an approved PASS
    with a manual human review. Corrections authorize only their exact spans;
    they cannot bypass synthetic verdict, repetition or basic format checks.
    """
    errors, warnings = [], []
    result = dict(errors=errors, warnings=warnings, corrections=[])
    if not isinstance(record, dict):
        errors.append('실행 패키지는 객체여야 합니다.')
        return result
    target = record.get('tc')
    original_valid = _check_fields(original, '원문', errors)
    target_valid = _check_fields(target, '실행 정답', errors)
    if not original_valid or not target_valid:
        return result
    review = record.get('review', {})
    if not isinstance(review, dict):
        errors.append('검토 기록은 객체여야 합니다.')
        return result
    _format_checks(target, errors, warnings)

    # 명시적인 요구사항 보정도 새 PASS/FAIL 메타 문구를 정답에 넣는 허가가 아니다.
    raw_errors = tc_optimization.preserved_content_errors(original, target)
    errors.extend(message for message in raw_errors if 'PASS/FAIL' in message or 'PASS 실행' in message)
    adjusted, accepted = _apply_corrections(original, target, review, errors)
    result['corrections'] = accepted
    proposal = {field: target[field] for field in FIELDS}
    proposal.update(change_required=any(adjusted[field] != target[field] for field in FIELDS),
                    review_reason='검토한 실행 문구를 기준으로 내용과 검증 조건을 확인합니다.')
    quality_errors = []
    try:
        quality_errors = tc_optimization.validate_detail_quality(adjusted, proposal)
    except (ValueError, TypeError, KeyError, AttributeError, IndexError):
        # 예외 본문에는 원문 값이 포함될 수 있으므로 그대로 기록하지 않는다.
        errors.append('실행 정답의 품질 검사를 완료하지 못했습니다. TC 형식과 검증 조건을 검토하세요.')
    else:
        errors.extend(_safe_quality_message(message) for message in quality_errors)
    if quality_errors:
        warnings.append('요구사항 변경이 의도된 경우 보정 전·후 구절과 근거를 사람 검토 기록에 명시하세요.')
    result['errors'] = _unique(errors)
    result['warnings'] = _unique(warnings)
    return result
