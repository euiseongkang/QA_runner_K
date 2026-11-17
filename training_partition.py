"""Keep TC partitions stable and reject evaluation material used by prior models."""
from collections import Counter, defaultdict
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
import unicodedata


SPLITS = ('train', 'valid', 'test')
FIELDS = ('precondition', 'steps', 'expected')
TRAINED_STAGES = {'train', 'post', 'gguf', 'deploy', 'promote', 'published'}


def _digest(value):
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))
    return hashlib.sha256(raw.encode('utf-8')).hexdigest()


def _normalize(value):
    if isinstance(value, str):
        return re.sub(r'\s+', ' ', unicodedata.normalize('NFC', value)).strip()
    if isinstance(value, dict):
        return {key: _normalize(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_normalize(item) for item in value]
    return value


def _json_content(content):
    try:
        return json.loads(content)
    except (ValueError, TypeError):
        return content


def sample_keys(sample):
    """Return hashes only; review_reason and prompt scaffolding are not TC content."""
    example = sample.get('line')
    if not isinstance(example, dict) or not isinstance(example.get('messages'), list):
        raise ValueError('학습 예제에 messages 배열이 없습니다.')
    keys = set()
    for name in ('identity', 'original', 'package', 'execution_id'):
        value = sample.get(name)
        if value is not None and value != '':
            keys.add(name + ':' + _digest(value))
    origin = sample.get('original_source')
    if isinstance(origin, dict) and origin.get('package'):
        keys.add('package:' + _digest(origin['package']))
    found = set()
    for message in example['messages']:
        if not isinstance(message, dict):
            raise ValueError('학습 예제의 message 형식이 잘못되었습니다.')
        role, content = message.get('role'), message.get('content')
        if role not in ('system', 'user', 'assistant') or not isinstance(content, str):
            raise ValueError('학습 예제의 role/content 형식이 잘못되었습니다.')
        if role == 'system':
            continue
        if not content.strip():
            raise ValueError('학습 예제의 입력 또는 정답이 비어 있습니다.')
        found.add(role)
        value = _json_content(content)
        if role == 'user' and isinstance(value, dict):
            value = value.get('original_tc', value)
        if isinstance(value, dict) and all(isinstance(value.get(key), str) for key in FIELDS):
            # A previous target may become a later input. Keep both on one side.
            keys.add('tc_content:' + _digest(_normalize({key: value[key] for key in FIELDS})))
        else:
            keys.add(role + '_content:' + _digest(_normalize(value)))
    if found != {'user', 'assistant'}:
        raise ValueError('학습 예제에 user 입력과 assistant 정답이 모두 필요합니다.')
    return sorted(keys)


def _read_json(path):
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError) as error:
        raise ValueError(f'학습 분할 이력을 읽지 못했습니다: {path}') from error


def _dataset_rows(folder):
    lineage_path = folder / 'lineage.json'
    lineage = {}
    if lineage_path.exists():
        value = _read_json(lineage_path)
        if not isinstance(value, list):
            raise ValueError(f'lineage.json은 배열이어야 합니다: {lineage_path}')
        for record in value:
            if (not isinstance(record, dict) or record.get('split') not in SPLITS
                    or not isinstance(record.get('line'), int) or record['line'] < 1):
                raise ValueError(f'출처의 분할/행 번호가 잘못되었습니다: {lineage_path}')
            index = (record['split'], record['line'])
            if index in lineage:
                raise ValueError(f'출처의 행 번호가 중복되었습니다: {lineage_path}')
            lineage[index] = record
    rows = []
    used = set()
    for split in SPLITS:
        path = folder / (split + '.jsonl')
        if not path.is_file():
            raise ValueError(f'학습 분할 파일이 없습니다: {path}')
        logical = 0
        for number, text in enumerate(path.read_text(encoding='utf-8').splitlines(), 1):
            if not text.strip():
                continue
            logical += 1
            try:
                example = json.loads(text)
                sample = dict(lineage.get((split, logical), {}), line=example)
                keys = sample_keys(sample)
            except (ValueError, TypeError) as error:
                raise ValueError(f'학습 자료를 확인하세요: {path} {number}행 ({error})') from error
            used.add((split, logical))
            rows.append({'keys': keys, 'split': split, 'row': number,
                         'source': str(folder), 'kind': 'export'})
    if set(lineage) - used:
        raise ValueError(f'출처가 존재하지 않는 JSONL 행을 참조합니다: {lineage_path}')
    return rows


def _parent_for_dataset(dataset):
    if (dataset.name == 'dataset' and dataset.parent.parent.name == 'runs'
            and dataset.parent.parent.parent.name == '.runner'):
        return dataset.parents[3]
    return dataset.parent


def _registry_entries(parent):
    path = parent / 'split_registry.json'
    if not path.exists():
        return []
    if path.is_symlink():
        raise ValueError(f'분할 이력 파일의 외부 참조는 지원하지 않습니다: {path}')
    return _validated_entries(_read_json(path), str(path))


def _validated_entries(data, description):
    if not isinstance(data, dict) or data.get('schema_version') != 1 or not isinstance(data.get('entries'), list):
        raise ValueError(f'분할 이력 파일 형식이 잘못되었습니다: {description}')
    for record in data['entries']:
        if (not isinstance(record, dict) or record.get('split') not in SPLITS
                or not isinstance(record.get('keys'), list) or not record['keys']
                or any(not isinstance(key, str) for key in record['keys'])
                or record.get('kind') not in ('export', 'trained', 'reservation')):
            raise ValueError(f'분할 이력 항목 형식이 잘못되었습니다: {description}')
    return data['entries']


def _portable_entries(registry):
    if registry is None:
        return []
    data = registry if isinstance(registry, dict) else _read_json(Path(registry).expanduser().resolve())
    records = _validated_entries(data, 'packaged_history')
    result = []
    for record in records:
        # Refuse accidental raw identifiers in an otherwise portable ledger.
        if any(not re.fullmatch(r'(identity|original|package|execution_id|tc_content|user_content|assistant_content):[0-9a-f]{64}', key)
               for key in record['keys']):
            raise ValueError('배포용 분할 이력에는 해시 식별자만 포함할 수 있습니다.')
        result.append({'keys': sorted(set(record['keys'])), 'split': record['split'],
                       'kind': record['kind'], 'source': 'packaged_history'})
    return result


def _trained_datasets(parent, registry=None):
    sources = [(parent / 'model_registry.json', None), (parent / '.runner/model_registry.json', None)]
    if registry is not None:
        if isinstance(registry, dict):
            sources.append((None, registry))
        else:
            sources.append((Path(registry).expanduser().resolve(), None))
    trained = set()
    for path, value in sources:
        if value is None:
            if not path.is_file():
                continue
            value = _read_json(path)
        if not isinstance(value, dict):
            raise ValueError('모델 등록 기록은 JSON 객체여야 합니다.')
        records = [value.get('latest', {})] + value.get('history', [])
        for record in records:
            if not isinstance(record, dict) or not record.get('dataset'):
                continue
            target = Path(record['dataset']).expanduser()
            if not target.is_absolute():
                choices = [parent.parent / target, parent / target]
                if path is not None:
                    choices.append(path.parent / target)
                target = next((item for item in choices if item.is_dir()), choices[0])
            trained.add(target.resolve())
    return trained


def _history(parent, registry=None, exclude=None):
    trained = _trained_datasets(parent, registry)
    missing = sorted(str(folder) for folder in trained if folder != exclude and not folder.is_dir())
    if missing:
        raise ValueError('이전 모델의 학습 데이터셋이 없습니다. 누수 확인을 위해 복원하세요: ' + ', '.join(missing[:3]))
    folders = set(parent.glob('qa_tc_dataset_*')) | set(parent.glob('.runner/runs/*/dataset')) | trained
    observations, scanned, trained_scanned = [], [], []
    for folder in sorted(folders):
        folder = folder.resolve()
        if folder == exclude or not folder.is_dir():
            continue
        if not any((folder / name).exists() for name in ('export_summary.json', 'train.jsonl', 'model_release.json')):
            continue
        state = folder / 'model_release.json'
        was_trained = folder in trained
        if state.is_file():
            value = _read_json(state)
            if not isinstance(value, dict):
                raise ValueError(f'학습 실행 기록 형식이 잘못되었습니다: {state}')
            was_trained = was_trained or value.get('stage') in TRAINED_STAGES
        rows = _dataset_rows(folder)
        for row in rows:
            row['kind'] = 'trained' if was_trained else 'export'
        observations.extend(rows)
        scanned.append(str(folder))
        if was_trained:
            trained_scanned.append(str(folder))
    return observations, scanned, trained_scanned


def portable_history(parent, registry=None):
    """Return a path-free ledger without modifying exports or local registries.

    It contains only hashed linkage keys, partition and evidence type. Successful
    model training remains distinct from an export or a reserved partition.
    """
    parent = Path(parent).expanduser().resolve()
    history, _, _ = _history(parent, registry)
    entries = _portable_entries({'schema_version': 1, 'entries': _registry_entries(parent) + history})
    unique = {_digest(record): record for record in entries}
    return {'schema_version': 1, 'entries': [unique[key] for key in sorted(unique)]}


def _components(records):
    parents = {}

    def find(key):
        parents.setdefault(key, key)
        while parents[key] != key:
            parents[key] = parents[parents[key]]
            key = parents[key]
        return key

    for record in records:
        first = record['keys'][0]
        for key in record['keys']:
            parents[find(key)] = find(first)
    groups = defaultdict(list)
    for index, record in enumerate(records):
        groups[find(record['keys'][0])].append(index)
    return groups


def _preferred_split(records):
    choices = {record['split'] for record in records}
    # Merged historical partitions cannot remain independent evaluation sets.
    return next(iter(choices)) if len(choices) == 1 else 'train'


@contextmanager
def _locked(parent):
    parent.mkdir(parents=True, exist_ok=True)
    with (parent / '.split_registry.lock').open('a+b') as stream:
        try:
            if os.name == 'nt':
                import msvcrt
                stream.seek(0)
                if not stream.read(1):
                    stream.write(b'0')
                    stream.flush()
                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as error:
            raise ValueError('다른 내보내기가 분할 이력을 갱신 중입니다. 완료 후 다시 시도하세요.') from error
        try:
            yield
        finally:
            if os.name == 'nt':
                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream, fcntl.LOCK_UN)


def _save_entries(parent, entries):
    handle, temporary = tempfile.mkstemp(prefix='.split_registry_', suffix='.tmp', dir=parent)
    try:
        with os.fdopen(handle, 'w', encoding='utf-8') as stream:
            json.dump({'schema_version': 1, 'entries': entries}, stream, ensure_ascii=False, indent=2)
            stream.write('\n')
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, parent / 'split_registry.json')
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def split_samples(samples, parent):
    """Return (splits aligned to samples, metadata); append assignments atomically.

    Historical exports reserve their partition. Actual training and conflicting
    historical partitions always resolve to train. New groups are assigned once;
    adding data never moves an existing training group into evaluation.
    """
    parent = Path(parent).expanduser().resolve()
    current = [{'keys': sample_keys(sample), 'kind': 'reservation'} for sample in samples]
    with _locked(parent):
        saved = _registry_entries(parent)
        history, scanned, trained = _history(parent)
        previous = saved + history
        records = previous + current
        assignments = [None] * len(current)
        group_ids = [None] * len(current)
        fresh = []
        conflicts = 0
        current_groups = 0
        for indices in _components(records).values():
            positions = [index - len(previous) for index in indices if index >= len(previous)]
            if not positions:
                continue
            current_groups += 1
            prior = [records[index] for index in indices if index < len(previous)]
            keys = sorted({key for index in indices for key in records[index]['keys']})
            group_id = _digest(keys)
            if prior:
                split = _preferred_split(prior)
                conflicts += len({entry['split'] for entry in prior}) > 1
                for position in positions:
                    assignments[position] = split
                    group_ids[position] = group_id
            else:
                fresh.append((group_id, positions))
        # Allocate only unseen groups. Existing assignments are never rebalanced.
        fresh.sort()
        holdout = max(1, round(len(fresh) * .1)) if len(fresh) >= 3 else 0
        for index, (group_id, positions) in enumerate(fresh):
            split = 'valid' if index < holdout else 'test' if index < 2 * holdout else 'train'
            for position in positions:
                assignments[position] = split
                group_ids[position] = group_id
        additions = history + [dict(record, split=split, source='current_export')
                               for record, split in zip(current, assignments)]
        known = {_digest({key: value for key, value in entry.items() if key != 'recorded_at'}) for entry in saved}
        merged = list(saved)
        for entry in additions:
            fingerprint = _digest(entry)
            if fingerprint not in known:
                merged.append(dict(entry, recorded_at=datetime.now(timezone.utc).isoformat()))
                known.add(fingerprint)
        if merged != saved:
            _save_entries(parent, merged)
    counts = {split: assignments.count(split) for split in SPLITS}
    notes = []
    if not counts['valid'] or not counts['test']:
        notes.append('독립 평가 자료가 부족합니다. 이전 학습 TC를 평가용으로 옮기지 말고 새 TC를 추가하세요.')
    if conflicts:
        notes.append(f'과거 분할이 충돌한 {conflicts}개 그룹은 학습 전용으로 고정했습니다.')
    return assignments, {'policy': 'persistent_history_aware', 'registry': str(parent / 'split_registry.json'),
                         'groups': current_groups, 'group_ids': group_ids, 'new_groups': len(fresh),
                         'historical_datasets': len(scanned), 'trained_datasets': len(trained),
                         'resolved_conflicts': conflicts, 'splits': counts, 'notes': notes}


def validate_training_dataset(dataset, registry=None, history_registry=None):
    """Read-only preflight; raise ValueError on leakage or empty partitions.

    registry optionally supplies an additional model registry dict or file path.
    history_registry optionally supplies a portable split ledger dict or path.
    Plain exports reserve splits but are never reported as trained models.
    """
    dataset = Path(dataset).expanduser().resolve()
    parent = _parent_for_dataset(dataset)
    current = _dataset_rows(dataset)
    counts = Counter(row['split'] for row in current)
    empty = [split for split in SPLITS if not counts[split]]
    if empty:
        raise ValueError('학습·평가 분할에 자료가 없습니다: ' + ', '.join(empty)
                         + '. 이전 학습 TC를 옮기지 말고 독립적인 새 TC를 추가해 내보내세요.')
    saved = _registry_entries(parent)
    history, scanned, trained = _history(parent, registry, exclude=dataset)
    packaged = _portable_entries(history_registry)
    previous = saved + history + packaged
    records = previous + current
    errors = []
    groups = 0
    for indices in _components(records).values():
        rows = [records[index] for index in indices if index >= len(previous)]
        if not rows:
            continue
        groups += 1
        prior = [records[index] for index in indices if index < len(previous)]
        places = ', '.join(f"{row['split']}.jsonl {row['row']}행" for row in rows[:4])
        if len({row['split'] for row in rows}) > 1:
            errors.append(f'같은 TC·입력·정답이 여러 분할에 있습니다: {places}')
        contaminated = [row for row in rows if row['split'] != 'train']
        learned = [row for row in prior if row['kind'] == 'trained' and row['split'] == 'train']
        if contaminated and learned:
            source = learned[0]
            errors.append(f"이전 모델이 학습한 TC가 평가 자료에 있습니다: {places}; "
                          f"이전 학습: {source['source']}/train.jsonl")
        elif prior:
            expected = _preferred_split(prior)
            if any(row['split'] != expected for row in rows):
                errors.append(f'영구 분할 이력과 다릅니다: {places}; 유지할 분할: {expected}')
    if errors:
        detail = '\n'.join(errors[:8])
        raise ValueError('학습 자료 누수로 중단했습니다. 새로 내보내고 독립 평가 TC를 추가하세요.\n' + detail)
    return {'status': 'valid', 'groups': groups, 'splits': dict(counts),
            'historical_datasets': len(scanned), 'trained_datasets': len(trained),
            'packaged_history_entries': len(packaged)}
