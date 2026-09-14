#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""TC 엑셀 파서 - 프로그램(qa_runner_k_gui.py)과 대시보드(dashboard_server.py)가 함께 쓴다.

두 곳에서 같은 엑셀을 읽는데 파싱 규칙이 따로 놀면 "프로그램에서는 되는데 대시보드에서는
안 되는" 상황이 생기므로, 규칙을 이 한 곳에만 둔다. [NEW v0.5.0]

지원 포맷 (강의성님이 확정한 표준):
  시트 "개요"        - 문서 정보 (파싱하지 않음)
  시트 "테스트케이스" - No / 테스트 항목 / 사전조건 / 테스트 절차 / 예상 결과 / 우선순위 /
                       결과(Pass/Fail) / 비고

실제 파일에 맞춰 들어간 규칙:
  - 헤더는 공백을 무시하고 비교 ("테스트 항목" = "테스트항목")
  - 실행에 꼭 필요한 건 테스트 항목 / 테스트 절차 / 예상 결과 3개. 나머지는 비어도 통과
  - No가 비어 있는 행이 실제로 많아서, 비면 엑셀 행 번호(r<번호>)로 대체
  - 완전히 빈 행은 조용히 건너뜀 (작성용 빈 줄이 대부분인 파일이 있음)
"""

import re

SHEET_NAME = "테스트케이스"
REQUIRED_COLUMNS = ["테스트 항목", "테스트 절차", "예상 결과"]


def norm_header(name) -> str:
    """헤더/컬럼명 비교용 정규화 (공백 제거)."""
    return re.sub(r"\s+", "", str(name or ""))


def clean_cell(value) -> str:
    """셀 값의 앞뒤 공백/중복 공백 정리. 줄바꿈은 살려야 하는 컬럼이 있어 여기서는 쓰지 않음."""
    if value is None:
        return ""
    return re.sub(r"[ \t]+", " ", str(value)).strip()


class TCExcelError(ValueError):
    """포맷이 달라서 읽을 수 없을 때. 메시지를 그대로 사용자에게 보여준다."""


def parse_tc_excel(source):
    """TC 엑셀을 읽어 (tcs, warnings) 반환.

    source: 파일 경로(str) 또는 file-like 객체 (Flask 업로드 스트림도 그대로 사용 가능)
    tcs   : [{"no","title","precondition","steps","expected","priority","note","row"}, ...]
            - steps는 줄바꿈을 그대로 보존한다 (번호 매긴 절차가 줄 단위로 해석되므로)
    warnings: 건너뛴 행 등 사람에게 알려줄 메모 리스트
    """
    try:
        from openpyxl import load_workbook
    except ImportError:  # pragma: no cover - 빌드 환경에서는 항상 포함됨
        raise TCExcelError("엑셀을 읽는 데 필요한 openpyxl이 설치되어 있지 않습니다")

    try:
        wb = load_workbook(source, data_only=True, read_only=True)
    except Exception as e:
        raise TCExcelError(f"엑셀 파일을 열 수 없습니다: {str(e)[:120]}")

    try:
        if SHEET_NAME not in wb.sheetnames:
            raise TCExcelError(
                f'시트 "{SHEET_NAME}"를 찾을 수 없습니다. '
                f'(이 파일의 시트: {", ".join(wb.sheetnames) or "없음"})'
            )
        ws = wb[SHEET_NAME]

        rows = ws.iter_rows(values_only=True)
        try:
            header_row = next(rows)
        except StopIteration:
            raise TCExcelError(f'"{SHEET_NAME}" 시트가 비어 있습니다')

        col = {}
        for idx, name in enumerate(header_row):
            key = norm_header(name)
            if key and key not in col:
                col[key] = idx

        missing = [c for c in REQUIRED_COLUMNS if norm_header(c) not in col]
        if missing:
            raise TCExcelError(
                "필수 컬럼이 없습니다: " + ", ".join(missing)
                + " / 1행 헤더가 'No · 테스트 항목 · 사전조건 · 테스트 절차 · 예상 결과 · 우선순위' "
                  "형태인지 확인해주세요"
            )

        def cell(row, name, keep_newlines=False):
            idx = col.get(norm_header(name))
            if idx is None or idx >= len(row) or row[idx] is None:
                return ""
            return str(row[idx]) if keep_newlines else clean_cell(row[idx])

        tcs, warnings = [], []
        for row_idx, row in enumerate(rows, start=2):
            title = cell(row, "테스트 항목")
            steps = cell(row, "테스트 절차", keep_newlines=True)
            expected = cell(row, "예상 결과")

            if not title and not steps.strip() and not expected:
                continue  # 완전히 빈 행

            if not title or not steps.strip() or not expected:
                missing_here = [
                    n for n, v in (("테스트 항목", title), ("테스트 절차", steps.strip()),
                                   ("예상 결과", expected)) if not v
                ]
                warnings.append(f"{row_idx}행 건너뜀 - 빈 칸: {', '.join(missing_here)}")
                continue

            no = cell(row, "No")
            tcs.append({
                "no": no or f"r{row_idx}",
                "title": title,
                "precondition": cell(row, "사전조건"),
                "steps": steps,
                "expected": expected,
                "priority": cell(row, "우선순위"),
                "note": cell(row, "비고"),
                "row": row_idx,
            })

        if not tcs:
            warnings.append("읽을 수 있는 TC가 없습니다 (데이터 행이 비어 있는지 확인해주세요)")
        return tcs, warnings
    finally:
        try:
            wb.close()
        except Exception:
            pass
