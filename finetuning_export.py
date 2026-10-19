"""TC별 최초 원문과 최신 PASS 실행 문구를 학습용 messages JSONL로 내보낸다."""
import hashlib
import json
import tempfile
import uuid
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import execution_package
import training_history

FIELDS = ('precondition', 'steps', 'expected')
SYSTEM_PROMPT = ('당신은 QA 테스트케이스 편집자다. 원본 TC의 목적을 보존하면서 '
                 '사전조건·테스트 절차·예상 결과를 명확하고 실행 가능한 문구로 개선한다. '
                 '입력값과 제품 요구사항을 근거 없이 변경하지 않는다. 각 항목은 번호가 있는 목록으로 작성한다. '
                 '응답은 precondition, steps, expected, change_required(boolean), review_reason의 '
                 '다섯 키를 갖는 JSON 객체 하나다. 검토 이유는 300자 이내이며 반복하지 않는다. '
                 '바뀐 필드가 있으면 change_required=true, 전부 같으면 false다.')


def encode(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def digest(value):
    return hashlib.sha256(encode(value).encode('utf-8')).hexdigest()


def example(record, original_tc=None):
    # 정답은 실제 PASS 실행 당시 TC다. 실행하지 않은 수동 정답 편집본은 사용하지 않는다.
    target_tc = record['tc']
    original_tc = target_tc if original_tc is None else original_tc
    for obj in (original_tc, target_tc):
        for key in FIELDS:
            value = obj.get(key)
            if not isinstance(value, str) or len(value) > 4000 or (key != 'precondition' and not value.strip()):
                raise ValueError(f'{key}가 비어 있거나 형식/길이가 올바르지 않음')
    target = {key: target_tc[key] for key in FIELDS}
    changed = any(original_tc[key] != target[key] for key in FIELDS)
    target.update(change_required=changed, review_reason=(
        '동일 TC의 최신 PASS 실행 문구로 개선합니다.' if changed else '최신 PASS 실행 문구와 같아 원문을 유지합니다.'))
    # 최종 PASS의 동작·실행 사유에는 정답이 포함될 수 있으므로 입력에 넣지 않는다.
    context = {'original_tc': {key: original_tc[key] for key in FIELDS}, 'title': original_tc.get('title', '')}
    return {'messages': [{'role': 'system', 'content': SYSTEM_PROMPT},
                         {'role': 'user', 'content': encode(context)},
                         {'role': 'assistant', 'content': encode(target)}]}, context


def execution_order(record):
    value = record['execution'].get('finished_at')
    if not isinstance(value, str): raise ValueError('실행 완료 시각이 없습니다.')
    stamp = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if stamp.tzinfo is None: raise ValueError('실행 완료 시각의 시간대가 없습니다.')
    return stamp.timestamp(), str(record['execution'].get('execution_id') or record['path'])


def legacy_key(record):
    tc, run = record['tc'], record['execution']
    return encode([run.get('source'), run.get('source_ref'), tc.get('sheet', tc.get('sheet_name')) or '',
                   str(tc.get('tc_id', tc.get('tc_no')))])


def export_packages(root, destination_parent):
    """TC별 최초 원문 → 최신 PASS 실행 문구 한 쌍. 화면 필터/선택과 무관하다."""
    records, read_errors = execution_package.list_packages(root)
    report = {'schema_version': 2, 'policy': 'first_original_to_latest_pass',
              'created_at': execution_package.now(), 'total': len(records),
              'unapproved': 0, 'approved': 0, 'duplicates': 0, 'invalid': [],
              'no_pass': 0, 'legacy_originals': 0, 'read_errors': read_errors, 'splits': {}, 'notes': [
                  '최초 최적화 전 원문을 입력, 같은 TC의 최신 PASS 실행 문구를 정답으로 사용합니다.',
                  '최신 PASS가 미승인이면 해당 TC를 제외하며 이전 PASS로 되돌아가지 않습니다.',
                  'FAIL·확인 필요 및 실행하지 않은 학습 정답 편집 문구는 정답으로 사용하지 않습니다.',
                  '최초 최적화 전 원문이 없는 기존 자료는 가장 오래된 실행 문구를 대체 원문으로 사용합니다.',
                  '기존 실행 패키지와 이전 내보내기는 보존됩니다. 새 내보내기는 TC별 한 쌍입니다.']}
    groups = {}
    # PK가 추가되기 전 패키지는 출처·시트·TC 번호가 단 하나의 새 PK와 연결될 때만 합친다.
    known = {}
    for record in records:
        if record['execution'].get('training_identity') is not None:
            known.setdefault(legacy_key(record), set()).add(encode(training_history.record_identity(record)))
    for record in records:
        try:
            execution_order(record)
            key = encode(training_history.record_identity(record))
            if record['execution'].get('training_identity') is None:
                candidates = known.get(legacy_key(record), set())
                if len(candidates) > 1: raise ValueError('기존 TC 번호가 여러 PK와 겹쳐 원문 연결 불가')
                if candidates: key = next(iter(candidates))
            groups.setdefault(key, []).append(record)
        except (ValueError, TypeError, KeyError) as error:
            report['invalid'].append({'package': str(Path(record['path']).relative_to(Path(root).resolve())), 'reason': str(error)})
    samples = []
    for key, history in groups.items():
        history.sort(key=execution_order)
        passes = [record for record in history if record['execution']['result'] == 'PASS']
        if not passes:
            report['no_pass'] += 1
            continue
        record = passes[-1]
        if record['review'].get('approved_for_training') is not True:
            report['unapproved'] += 1
            continue
        report['approved'] += 1
        report['duplicates'] += len(history) - 1
        relative = str(Path(record['path']).relative_to(Path(root).resolve()))
        try:
            origin = training_history.load(root, json.loads(key))
            earliest = history[0]
            # 캡처보다 먼저 실행된 기록은 이미 존재하던 원문의 가장 오래된 근거다.
            if origin and datetime.fromisoformat(origin['captured_at']).timestamp() <= execution_order(earliest)[0]:
                original = origin['tc']
                provenance = dict(kind='before_first_optimization', captured_at=origin['captured_at'])
            else:
                original = earliest['tc']
                provenance = dict(kind='earliest_available_execution',
                                  package=str(Path(earliest['path']).relative_to(Path(root).resolve())))
                report['legacy_originals'] += 1
            line, context = example(record, original)
        except (ValueError, OSError, TypeError, KeyError, AttributeError) as error:
            report['invalid'].append({'package': relative, 'reason': str(error)})
            continue
        samples.append({'line': line, 'original': digest(context['original_tc']), 'identity': digest(json.loads(key)),
                        'package': relative, 'execution_id': record['execution'].get('execution_id'),
                        'original_source': provenance, 'result': 'PASS',
                        'human_reviewed': record['review'].get('human_reviewed') is True})
    if not samples:
        raise ValueError(f'내보낼 최신 PASS 학습 쌍이 없습니다. PASS 없음 {report["no_pass"]}개 TC, '
                         f'최신 PASS 미승인 {report["unapproved"]}개 TC, '
                         f'형식 오류 {len(report["invalid"])}건, 읽기 실패 {len(read_errors)}건')
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
            lineage.append({key: sample[key] for key in ('package', 'execution_id', 'result', 'human_reviewed', 'identity', 'original_source')}
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
