"""TC 실행 원본·동작·판정·스크린샷을 실행별 독립 폴더로 보관한다."""
import base64
import json
import os
import platform
import re
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import training_history

TC_KEYS = ('id', 'tc_id', 'tc_no', 'title', 'priority', 'sheet', 'sheet_name',
           'precondition', 'steps', 'expected', 'note')
ACTION_KEYS = ('type', 'description', 'selector', 'text', 'value', 'key',
               'checked', 'ms', 'label', 'source', 'target', 'patient_row', 'page_number', 'wait', 'from', 'to', 'plan')


def now():
    return datetime.now(timezone.utc).isoformat()


def safe_url(url):
    """URL 자격증명·쿼리·프래그먼트는 실행 환경 기록에 넣지 않는다."""
    try:
        parsed = urlsplit(str(url))
        if parsed.scheme not in ('http', 'https') or not parsed.hostname:
            return ''
        host = parsed.hostname
        if ':' in host:
            host = '[' + host + ']'
        if parsed.port:
            host += ':' + str(parsed.port)
        return urlunsplit((parsed.scheme, host, parsed.path, '', ''))
    except ValueError:
        return ''


def begin(tc, *, version, provider, rule_only, target_url):
    return {'started_at': now(), 'tc': {key: tc[key] for key in TC_KEYS if key in tc},
            'environment': {'app_version': version, 'provider': provider,
                            'judgment_mode': 'rule' if rule_only else 'ai',
                            'target_url': safe_url(target_url),
                            'platform': platform.system(), 'architecture': platform.machine(),
                            'python': platform.python_version()},
            'errors': []}


def action_record(action, index):
    return {'index': index, 'action': {key: action[key] for key in ACTION_KEYS if key in action},
            'started_at': now(), 'status': 'pending', 'observations': [], 'error': None}


def write(root, *, tc, result, reason, run_id, source, source_ref, context=None,
          before_b64=None, after_b64=None):
    context = context or {}
    token = uuid.uuid4().hex
    component = lambda value: re.sub(r'[^\w.-]', '_', str(value))[:80].strip('.') or 'unknown'
    parent = Path(root) / component(run_id)
    parent.mkdir(parents=True, exist_ok=True)
    destination = parent / ('tc_' + component(tc.get('tc_id', tc.get('tc_no', '?'))) + '_' + token)
    # 임시 폴더에 모두 쓴 뒤 이름을 바꿔 저장 중인 기록과 완성 기록을 구분한다.
    with tempfile.TemporaryDirectory(prefix='.partial_', dir=parent) as temp:
        directory = Path(temp)
        errors = list(context.get('errors', []))
        shots = {}
        for name, content in (('before', before_b64), ('after', after_b64)):
            shots[name] = None
            if not content:
                continue
            try:
                image = base64.b64decode(content, validate=True)
                if not image.startswith(b'\x89PNG\r\n\x1a\n'):
                    raise ValueError('PNG 형식이 아님')
                (directory / 'screenshots').mkdir(exist_ok=True)
                relative = f'screenshots/{name}.png'
                (directory / relative).write_bytes(image)
                shots[name] = relative
            except (ValueError, TypeError) as error:
                errors.append(f'{name} 스크린샷 저장 실패: {error}')
        snapshot = context.get('tc') or {key: tc[key] for key in TC_KEYS if key in tc}
        manifest = {'schema_version': 1, 'execution_id': token, 'run_id': str(run_id),
                    'started_at': context.get('started_at'), 'finished_at': context.get('finished_at', now()),
                    'source': source, 'source_ref': source_ref,
                    'environment': context.get('environment', {}),
                    'action_generation': context.get('action_generation'),
                    'preparation': context.get('preparation', []),
                    'last_phase': context.get('phase'),
                    'result': result, 'reason': reason, 'errors': errors,
                    'screenshots': shots,
                    'precondition_execution': 'TC 사전조건 원문을 보관하며 자동 충족 여부는 별도로 확인해야 함'}
        manifest['training_identity'] = training_history.identity(tc, source, source_ref)
        review = {'status': 'approved', 'approved_for_training': True,
                  'review_reason': '실행 당시 TC를 기본 승인했습니다.',
                  'corrected_tc': {**{key: str(snapshot.get(key) or '') for key in ('precondition', 'steps', 'expected')},
                                   'change_required': False, 'review_reason': '실행 당시 TC 원문을 유지합니다.'},
                  'approval_source': 'automatic', 'human_reviewed': False,
                  'updated_at': now(),
                  'note': '기본 승인은 실행 판정의 정확성이나 사람의 검토 완료를 의미하지 않음'}
        actions = {'planned': context.get('planned_actions', []),
                   'trace': context.get('action_trace', []),
                   'completed': context.get('actions_done', []),
                   'failures': context.get('failed_actions', [])}
        for filename, data in (('execution.json', manifest), ('tc.json', snapshot),
                               ('actions.json', actions), ('review.json', review)):
            (directory / filename).write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        summary = [f"TC {snapshot.get('tc_id', snapshot.get('tc_no', '?'))}: {snapshot.get('title', '')}",
                   f'결과: {result}', f'판정 사유: {reason}',
                   f"시작(UTC): {manifest['started_at']}", f"완료(UTC): {manifest['finished_at']}",
                   '', '사전조건 원문 (자동 충족 확인과 구분)', str(snapshot.get('precondition', '')),
                   '', '테스트 절차 원문', str(snapshot.get('steps', '')),
                   '', '예상 결과 원문', str(snapshot.get('expected', '')),
                   '', '실제 동작별 결과']
        summary += [f"{item['index']}. {item['status']} | {item['action'].get('description', item['action'].get('type', ''))}"
                    + (f" | {item['error']}" if item.get('error') else '') for item in actions['trace']]
        summary += ['', '기록 오류', *(errors or ['없음']), '', '학습 정답 승인: review.json의 최신 상태 참고']
        (directory / 'summary.txt').write_text('\n'.join(summary) + '\n', encoding='utf-8')
        directory.rename(destination)
    return str(destination)


def read(root, path):
    directory = Path(path).resolve()
    relative = directory.relative_to(Path(root).resolve())
    if len(relative.parts) != 2 or any(part.startswith('.') for part in relative.parts):
        raise ValueError('실행 패키지 경로가 아닙니다.')
    data = {'path': str(directory)}
    for name in ('execution', 'tc', 'actions', 'review'):
        file = directory / f'{name}.json'
        if file.is_symlink():
            raise ValueError('외부 파일 참조는 지원하지 않습니다.')
        data[name] = json.loads(file.read_text(encoding='utf-8'))
        if not isinstance(data[name], dict):
            raise ValueError(f'{name}.json 객체 형식이 아닙니다.')
    if data['execution'].get('result') not in ('PASS', 'FAIL', '확인 필요'):
        raise ValueError('실행 결과 형식이 올바르지 않습니다.')
    if data['review'].get('corrected_tc') is not None and not isinstance(data['review']['corrected_tc'], dict):
        raise ValueError('학습 정답 형식이 올바르지 않습니다.')
    return data


def list_packages(root):
    rows, errors = [], []
    for file in Path(root).glob('*/tc_*/execution.json'):
        try:
            rows.append(read(root, file.parent))
        except (ValueError, OSError) as error:
            errors.append(f'{file.parent.name}: {error}')
    rows.sort(key=lambda row: row['execution'].get('finished_at') or '', reverse=True)
    return rows, errors


def update_review(root, path, approved, reason='', corrected_tc=None):
    if not isinstance(reason, str) or len(reason) > 300:
        raise ValueError('검토 사유는 300자 이하로 입력하세요.')
    record = read(root, path)
    review = dict(record['review'])
    if corrected_tc is not None:
        keys = ('precondition', 'steps', 'expected')
        if not all(isinstance(corrected_tc.get(key), str) for key in keys):
            raise ValueError('사전조건·테스트 절차·예상 결과가 필요합니다.')
        if not corrected_tc['steps'].strip() or not corrected_tc['expected'].strip():
            raise ValueError('테스트 절차와 예상 결과를 입력하세요.')
        if any(len(corrected_tc[key]) > 4000 for key in keys):
            raise ValueError('각 항목은 4000자 이하로 입력하세요.')
        changed = any(corrected_tc[key] != str(record['tc'].get(key) or '') for key in keys)
        review['corrected_tc'] = {**{key: corrected_tc[key] for key in keys},
                                  'change_required': changed,
                                  'review_reason': reason or ('검토하여 TC 문구를 수정했습니다.' if changed else '검토 후 원문을 유지합니다.')}
    if approved and not review.get('corrected_tc'):
        review['corrected_tc'] = {**{key: str(record['tc'].get(key) or '') for key in ('precondition', 'steps', 'expected')},
                                  'change_required': False, 'review_reason': '검토 후 원문을 유지합니다.'}
    review.update(status='approved' if approved else 'rejected', approved_for_training=bool(approved),
                  review_reason=reason, approval_source='manual', human_reviewed=True, updated_at=now())
    directory = Path(record['path'])
    # 원문·실행 판정은 변경하지 않고 검토 파일만 원자적으로 교체한다.
    handle, temp = tempfile.mkstemp(prefix='.review_', dir=directory)
    try:
        with os.fdopen(handle, 'w', encoding='utf-8') as stream:
            json.dump(review, stream, ensure_ascii=False, indent=2)
            stream.write('\n')
        os.replace(temp, directory / 'review.json')
    finally:
        if os.path.exists(temp):
            os.unlink(temp)
    return review
