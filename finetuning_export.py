"""승인된 실행 패키지를 텍스트 TC 편집 학습용 messages JSONL로 내보낸다."""
import hashlib
import json
import tempfile
import uuid
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import execution_package

FIELDS = ('precondition', 'steps', 'expected')
SYSTEM_PROMPT = ('당신은 QA 테스트케이스 편집자다. 원본 TC와 제공된 실행 근거만 사용하여 '
                 '사전조건·테스트 절차·예상 결과를 검토한다. 입력값, 대괄호 대상, 따옴표 안의 문자, '
                 '동작 순서와 검증 강도를 보존한다. 근거 없는 조건이나 기능을 추가하지 않는다. '
                 '필요하면 공백·번호·명확한 서술 오타만 교정한다. 변경이 필요 없으면 원문을 유지한다. '
                 '실행 실패가 TC 오류라는 가정을 하지 않으며 성공을 꾸며내지 않는다. '
                 '응답은 precondition, steps, expected, change_required(boolean), review_reason의 '
                 '다섯 키를 갖는 JSON 객체 하나다. 검토 이유는 300자 이내이며 반복하지 않는다. '
                 '바뀐 필드가 있으면 change_required=true, 전부 같으면 false다.')


def encode(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def digest(value):
    return hashlib.sha256(encode(value).encode('utf-8')).hexdigest()


def example(record):
    tc, review, run, actions = (record[k] for k in ('tc', 'review', 'execution', 'actions'))
    corrected = review.get('corrected_tc')
    if not isinstance(corrected, dict):
        raise ValueError('저장된 학습 정답이 없음')
    for obj in (tc, corrected):
        for key in FIELDS:
            value = obj.get(key)
            if not isinstance(value, str) or len(value) > 4000 or (key != 'precondition' and not value.strip()):
                raise ValueError(f'{key}가 비어 있거나 형식/길이가 올바르지 않음')
    target = {key: corrected[key] for key in FIELDS}
    changed = any(tc[key] != target[key] for key in FIELDS)
    if type(corrected.get('change_required')) is not bool or corrected['change_required'] != changed:
        raise ValueError('change_required와 변경 내용이 일치하지 않음')
    reason = corrected.get('review_reason')
    if not isinstance(reason, str) or not reason.strip() or len(reason) > 300:
        raise ValueError('학습 정답의 검토 사유가 없거나 300자를 초과함')
    target.update(change_required=changed, review_reason=reason)
    # 실행 ID·시간·스크린샷·환경 설정은 제외한다. 입력에 수정 정답을 넣지 않는다.
    trace = [{key: item[key] for key in ('index', 'action', 'status', 'observations', 'error') if key in item}
             for item in actions.get('trace', [])]
    context = {'original_tc': {key: tc[key] for key in FIELDS}, 'title': tc.get('title', ''),
               'execution': {'result': run['result'], 'reason': run.get('reason', ''),
                             'preparation': run.get('preparation', []),
                             'precondition_execution': run.get('precondition_execution', ''),
                             'record_errors': run.get('errors', [])},
               'actions': {'trace': trace, 'completed': actions.get('completed', []),
                           'failures': actions.get('failures', [])}}
    return {'messages': [{'role': 'system', 'content': SYSTEM_PROMPT},
                         {'role': 'user', 'content': encode(context)},
                         {'role': 'assistant', 'content': encode(target)}]}, context


def export_packages(root, destination_parent):
    """全 승인 기록을 읽고 원본은 유지하며 고유 폴더를 반환한다. 필터/선택과 무관하다."""
    records, read_errors = execution_package.list_packages(root)
    report = {'schema_version': 1, 'created_at': execution_package.now(), 'total': len(records),
              'unapproved': 0, 'approved': 0, 'duplicates': 0, 'invalid': [],
              'read_errors': read_errors, 'splits': {}, 'notes': [
                  '기본 승인 자료도 포함합니다. 승인은 실행 판정의 정확성을 보증하지 않습니다.',
                  '텍스트 TC 편집 학습 자료이며 스크린샷은 원본 패키지에만 남습니다.',
                  '정답 편집을 하지 않은 자료는 원문 유지 학습 사례입니다.']}
    samples, seen = [], set()
    for record in records:  # 최신 실행부터 읽는다.
        if record['review'].get('approved_for_training') is not True:
            report['unapproved'] += 1
            continue
        report['approved'] += 1
        relative = str(Path(record['path']).relative_to(Path(root).resolve()))
        try:
            line, context = example(record)
        except (ValueError, TypeError, KeyError, AttributeError) as error:
            report['invalid'].append({'package': relative, 'reason': str(error)})
            continue
        fingerprint = digest(line)
        if fingerprint in seen:
            report['duplicates'] += 1
            continue
        seen.add(fingerprint)
        tc, run = record['tc'], record['execution']
        tc_id = tc.get('tc_id', tc.get('tc_no'))
        identity = digest([run.get('source'), run.get('source_ref'), tc.get('sheet', tc.get('sheet_name')), tc_id]) if tc_id is not None else None
        samples.append({'line': line, 'original': digest(context['original_tc']), 'identity': identity,
                        'package': relative, 'execution_id': run.get('execution_id'),
                        'result': run['result'], 'human_reviewed': record['review'].get('human_reviewed') is True})
    if not samples:
        raise ValueError(f'내보낼 승인 자료가 없습니다. 미승인 {report["unapproved"]}건, '
                         f'정답 형식 오류 {len(report["invalid"])}건, 읽기 실패 {len(read_errors)}건')
    # TC 식별자 또는 동일 원문으로 연결된 자료는 같은 분할에 둔다.
    parents = list(range(len(samples)))
    def find(i):
        while parents[i] != i:
            parents[i] = parents[parents[i]]
            i = parents[i]
        return i
    owners = {}
    for i, sample in enumerate(samples):
        for key in (('original', sample['original']), ('tc', sample['identity'])):
            if key[1] is None:
                continue
            if key in owners:
                parents[find(i)] = find(owners[key])
            else:
                owners[key] = i
    groups = {}
    for i, sample in enumerate(samples):
        groups.setdefault(find(i), []).append(sample)
    ordered = sorted(groups.values(), key=lambda group: min(s['original'] for s in group))
    count = len(ordered)
    holdout = max(1, round(count * .1)) if count >= 3 else 0
    assignment = ['valid'] * holdout + ['test'] * holdout + ['train'] * (count - 2 * holdout)
    report['groups'] = count
    if not holdout:
        report['notes'].append('독립 TC 그룹이 3개 미만이므로 모두 train에 저장했습니다. valid/test는 비어 있어 별도 평가 자료가 필요합니다.')
    splits = {name: [] for name in ('train', 'valid', 'test')}
    lineage = []
    for group_index, (group, split) in enumerate(zip(ordered, assignment)):
        for sample in group:
            splits[split].append(sample['line'])
            lineage.append({key: sample[key] for key in ('package', 'execution_id', 'result', 'human_reviewed')}
                           | {'split': split, 'line': len(splits[split]), 'group': group_index})
    report['exported'] = len(samples)
    report['human_reviewed'] = sum(s['human_reviewed'] for s in samples)
    report['results'] = dict(Counter(s['result'] for s in samples))
    report['splits'] = {name: len(lines) for name, lines in splits.items()}
    parent = Path(destination_parent)
    parent.mkdir(parents=True, exist_ok=True)
    name = 'qa_tc_dataset_' + datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S') + '_' + uuid.uuid4().hex[:8]
    destination = parent / name
    with tempfile.TemporaryDirectory(prefix='.export_', dir=parent) as temporary:
        directory = Path(temporary)
        for split, lines in splits.items():
            (directory / f'{split}.jsonl').write_text(''.join(encode(line) + '\n' for line in lines), encoding='utf-8')
        for filename, value in (('export_summary.json', report), ('lineage.json', lineage)):
            (directory / filename).write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        (directory / 'system_prompt.txt').write_text(SYSTEM_PROMPT + '\n', encoding='utf-8')
        directory.rename(destination)
    return destination, report
