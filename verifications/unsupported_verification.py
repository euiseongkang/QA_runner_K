"""현재 실행기에 검증 근거 연동이 없는 요구사항을 명시적으로 실패 처리한다."""
import re


def failure(tc):
    text = re.sub(r'\s+', '', ' '.join(str(tc.get(key) or '') for key in
                                    ('title', 'sheet_name', 'steps', 'expected')))
    if ('검사접수' not in text
            or not re.search(r'최초등록(?:일시|시각|시간)', text)
            or not re.search(r'정렬|최신순|내림차순', text)):
        return None
    reason = ('[검증 불가] 최초 등록일시 기준 정렬을 검증할 수 없음: '
              '현재 QA 실행기에 접수별 최초 등록일시와 화면 행을 연결하는 근거 수집이 구현되지 않음. '
              '화면의 No·처방일·설명 텍스트로 최초 등록일시 최신순을 판정할 수 없음.')
    if re.search(r'수정', str(tc.get('expected') or '')):
        reason += ' 수정 후 정렬 순서 유지도 수정 전후 비교 기록의 수집·연동이 없어 검증할 수 없음.'
    return 'FAIL', reason
