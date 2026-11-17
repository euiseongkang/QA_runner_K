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
import training_partition
import training_quality

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


def target_review_reason(original_tc, target_tc, corrections=()):
    """학습 정답에는 선택 정책(PASS 등)이 아닌 실제 변경 항목을 설명한다."""
    labels = dict(precondition='사전조건', steps='테스트 절차', expected='예상 결과')
    changes = []
    for key, label in labels.items():
        if original_tc[key] != target_tc[key]:
            count = sum(bool(line.strip()) for line in target_tc[key].splitlines())
            changes.append(f'{label}를 {count}개 항목으로 수정했습니다.' if key != 'precondition'
                           else f'사전조건을 {count}개 항목으로 수정했습니다.')
    explanation = ' '.join(changes) if changes else '사전조건·테스트 절차·예상 결과가 원문과 같아 유지합니다.'
    if corrections:
        explanation = '검토로 확인된 원문 오류를 교정했습니다. ' + explanation
    return explanation[:300]


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
    target.update(change_required=changed, review_reason=target_review_reason(
        original_tc, target_tc, record['review'].get('requirement_corrections', [])))
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


def group_records(records):
    """과거 번호 기반 이력은 유일한 새 식별자로만 연결한다."""
    groups, invalid, known = {}, [], {}
    for record in records:
        if record['execution'].get('training_identity') is not None:
            known.setdefault(legacy_key(record), set()).add(encode(training_history.record_identity(record)))
    for record in records:
        try:
            execution_order(record)
            key = encode(training_history.record_identity(record))
            if record['execution'].get('training_identity') is None:
                candidates = known.get(legacy_key(record), set())
                if len(candidates) > 1:
                    raise ValueError('기존 TC 번호가 여러 PK와 겹쳐 원문 연결 불가')
                if candidates:
                    key = next(iter(candidates))
            groups.setdefault(key, []).append(record)
        except (ValueError, TypeError, KeyError) as error:
            invalid.append((record, str(error)))
    for history in groups.values():
        history.sort(key=execution_order)
    return groups, invalid


def original_for_history(root, key, history):
    origin = training_history.load(root, json.loads(key))
    earliest = history[0]
    if origin and datetime.fromisoformat(origin['captured_at']).timestamp() <= execution_order(earliest)[0]:
        return origin['tc'], dict(kind='before_first_optimization', captured_at=origin['captured_at'])
    return earliest['tc'], dict(kind='earliest_available_execution',
        package=str(Path(earliest['path']).relative_to(Path(root).resolve())),
        result=earliest['execution']['result'])


def original_for_record(root, record):
    """승인 화면에도 내보내기와 같은 최초 원문을 제공한다."""
    records, errors = execution_package.list_packages(root)
    if errors:
        raise ValueError('일부 실행 패키지를 읽을 수 없어 최초 원문을 확인하지 못했습니다.')
    groups, _ = group_records(records)
    for key, history in groups.items():
        if any(item['path'] == record['path'] for item in history):
            return original_for_history(root, key, history)
    raise ValueError('TC의 최초 원문 연결을 확인하지 못했습니다.')


def export_packages(root, destination_parent):
    """TC별 최초 원문 → 최신 PASS 실행 문구 한 쌍. 화면 필터/선택과 무관하다."""
    records, read_errors = execution_package.list_packages(root)
    if read_errors:
        raise ValueError('읽기 실패한 실행 패키지가 있어 최신 PASS를 확인하지 못했습니다. 패키지를 복구한 뒤 다시 내보내세요.')
    report = {'schema_version': 3, 'policy': 'reviewed_first_original_to_latest_pass',
              'created_at': execution_package.now(), 'total': len(records),
              'unapproved': 0, 'approved': 0, 'duplicates': 0, 'invalid': [],
              'no_pass': 0, 'legacy_originals': 0, 'read_errors': read_errors, 'splits': {},
              'review_required': 0, 'quality_rejected': [], 'quality_warnings': [], 'confirmed_corrections': 0, 'notes': [
                  '최초 최적화 전 원문을 입력, 같은 TC의 최신 PASS 실행 문구를 정답으로 사용합니다.',
                  '최신 PASS가 미승인이면 해당 TC를 제외하며 이전 PASS로 되돌아가지 않습니다.',
                  'FAIL·확인 필요 및 실행하지 않은 학습 정답 편집 문구는 정답으로 사용하지 않습니다.',
                  '최초 최적화 전 원문이 없는 기존 자료는 가장 오래된 실행 문구를 대체 원문으로 사용합니다.',
                  '기존 실행 패키지와 이전 내보내기는 보존됩니다. 새 내보내기는 TC별 한 쌍입니다.',
                  '사람이 검토·승인한 실제 실행 문구만 사용하며 요구사항 교정은 변경 전후와 사유를 별도 기록합니다.',
                  'TC별 분할을 보존하고 이전 학습 자료는 검증·시험 자료로 재사용하지 않습니다.',
                  'PASS 선택 정책은 메타데이터에 보관하며 학습 정답의 검토 이유에는 실제 변경 항목을 기록합니다.']}
    groups, invalid = group_records(records)
    report['invalid'] = [{'package': str(Path(record['path']).relative_to(Path(root).resolve())), 'reason': reason}
                         for record, reason in invalid]
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
        if record['review'].get('human_reviewed') is not True or record['review'].get('approval_source') != 'manual':
            report['review_required'] += 1
            continue
        report['approved'] += 1
        report['duplicates'] += len(history) - 1
        relative = str(Path(record['path']).relative_to(Path(root).resolve()))
        try:
            original, provenance = original_for_history(root, key, history)
            if provenance['kind'] == 'earliest_available_execution':
                report['legacy_originals'] += 1
            line, context = example(record, original)
            assessment = training_quality.assess_pair(original, record)
            if record['execution'].get('errors') or record['actions'].get('failures'):
                assessment['errors'].append('실행 오류 또는 동작 실패가 있는 PASS입니다. 재실행해 근거를 확인하세요.')
            if assessment['errors']:
                report['quality_rejected'].append({'package': relative, 'errors': assessment['errors']})
                continue
            warnings = list(assessment['warnings'])
            if not record['actions'].get('trace'):
                warnings.append('동작 추적 기록이 없습니다. 화면 관찰만 하는 TC인지 확인하세요.')
            if warnings:
                report['quality_warnings'].append({'package': relative, 'warnings': warnings})
            report['confirmed_corrections'] += len(assessment['corrections'])
        except (ValueError, OSError, TypeError, KeyError, AttributeError) as error:
            report['invalid'].append({'package': relative, 'reason': str(error)})
            continue
        samples.append({'line': line, 'original': digest(context['original_tc']), 'identity': digest(json.loads(key)),
                        'package': relative, 'execution_id': record['execution'].get('execution_id'),
                        'original_source': provenance, 'result': 'PASS',
                        'human_reviewed': True, 'requirement_corrections': assessment['corrections']})
    if not samples:
        raise ValueError(f'내보낼 최신 PASS 학습 쌍이 없습니다. PASS 없음 {report["no_pass"]}개 TC, '
                         f'최신 PASS 미승인 {report["unapproved"]}개 TC, '
                         f'사람 검토 필요 {report["review_required"]}개 TC, 품질 재검토 {len(report["quality_rejected"])}개 TC, '
                         f'형식 오류 {len(report["invalid"])}건, 읽기 실패 {len(read_errors)}건')
    assignments, partition_report = training_partition.split_samples(samples, Path(destination_parent))
    report['partition'] = partition_report
    report['groups'] = partition_report['groups']
    report['notes'].extend(partition_report['notes'])
    splits = {name: [] for name in ('train', 'valid', 'test')}
    lineage = []
    for sample, split in zip(samples, assignments):
        splits[split].append(sample['line'])
        lineage.append({key: sample[key] for key in ('package', 'execution_id', 'result', 'human_reviewed', 'identity', 'original_source', 'requirement_corrections')}
                       | {'split': split, 'line': len(splits[split]), 'original': sample['original'],
                          'sample_sha256': digest(sample['line'])})
    report['exported'] = len(samples)
    report['human_reviewed'] = sum(s['human_reviewed'] for s in samples)
    report['results'] = dict(Counter(s['result'] for s in samples))
    report['splits'] = {name: len(lines) for name, lines in splits.items()}
    report['training_ready'] = all(report['splits'].values())
    if not report['training_ready']:
        report['notes'].append('독립 TC 그룹이 3개 미만이거나 기존 학습 이력과 겹쳐 검증/시험 자료가 부족합니다. 새 TC를 검토해 별도 평가 자료를 확보한 뒤 학습하세요.')
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


def validate_training_export(dataset, registry=None):
    try:
        return _validate_training_export(dataset, registry)
    except (KeyError, TypeError, AttributeError, IndexError) as error:
        raise ValueError('학습 자료·검토 출처 형식이 잘못되었습니다. 검토 후 새로 내보내세요.') from error


def _validate_training_export(dataset, registry=None):
    """오래된 무검증 내보내기나 수정된 JSONL로 학습을 우회하지 못하게 한다."""
    dataset = Path(dataset).resolve()
    report = json.loads((dataset / 'export_summary.json').read_text(encoding='utf-8'))
    lineage = json.loads((dataset / 'lineage.json').read_text(encoding='utf-8'))
    if report.get('schema_version', 0) < 3 or not isinstance(lineage, list):
        raise ValueError('이전 형식의 학습 자료입니다. 검토·품질 검사를 적용해 새로 내보내세요.')
    indexed = {}
    for item in lineage:
        key = (item.get('split'), item.get('line'))
        if key in indexed or item.get('result') != 'PASS' or item.get('human_reviewed') is not True:
            raise ValueError('학습 출처의 중복 또는 사람 검토·PASS 근거 누락을 확인하세요.')
        indexed[key] = item
    counts = {}
    for split in ('train', 'valid', 'test'):
        rows = (dataset / (split + '.jsonl')).read_text(encoding='utf-8').splitlines()
        if not rows or any(not row.strip() for row in rows):
            raise ValueError('독립적인 학습·검증·시험 자료가 모두 필요합니다. 새 TC를 검토한 뒤 다시 내보내세요.')
        counts[split] = len(rows)
        for number, raw in enumerate(rows, 1):
            item = indexed.pop((split, number), None)
            if item is None:
                raise ValueError(f'{split} {number}행의 검토·출처 기록이 없습니다.')
            row = json.loads(raw)
            if item.get('sample_sha256') != digest(row):
                raise ValueError(f'{split} {number}행이 검토 후 내보낸 내용과 다릅니다. 새 문구를 검토·실행한 뒤 다시 내보내세요.')
            messages = row.get('messages', [])
            if [message.get('role') for message in messages] != ['system', 'user', 'assistant']:
                raise ValueError(f'{split} {number}행의 학습 대화 형식을 확인하세요.')
            context, target = [json.loads(message['content']) for message in messages[1:]]
            original = context['original_tc'] | {'title': context.get('title', '')}
            if (set(target) != {*FIELDS, 'change_required', 'review_reason'}
                    or type(target['change_required']) is not bool
                    or target['change_required'] != any(original[key] != target[key] for key in FIELDS)
                    or not isinstance(target['review_reason'], str) or not target['review_reason'].strip()
                    or len(target['review_reason']) > 300):
                raise ValueError(f'{split} {number}행의 정답 형식·변경 여부·검토 사유를 확인하세요.')
            assessment = training_quality.assess_pair(original, {'tc': target, 'review': {
                'requirement_corrections': item.get('requirement_corrections', [])}})
            if assessment['errors']:
                raise ValueError(f'{split} {number}행의 정답을 다시 검토하세요: ' + '; '.join(assessment['errors']))
    if (indexed or counts != report.get('splits')
            or sum(counts.values()) != report.get('exported')
            or report.get('human_reviewed') != report.get('exported')):
        raise ValueError('JSONL·출처·내보내기 요약의 행 수 또는 검토 건수가 다릅니다.')
    portable = Path(__file__).with_name('training_split_registry.json')
    return training_partition.validate_training_dataset(
        dataset, registry=registry, history_registry=portable if portable.exists() else None)
