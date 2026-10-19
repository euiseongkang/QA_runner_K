"""최초 최적화 전 원문과 출처별 TC 고유 식별자를 보존한다."""
import hashlib
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

FIELDS = ('precondition', 'steps', 'expected')


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def identity(tc, source, source_ref, server_url=None):
    context = tc.get('_edit_context') or {}
    server_url = server_url or context.get('server_url')
    if server_url:
        parsed = urlsplit(server_url)
        host = (parsed.hostname or '').lower()
        if parsed.port: host += ':' + str(parsed.port)
        namespace = urlunsplit((parsed.scheme.lower(), host, parsed.path.rstrip('/'), '', ''))
    else:
        namespace = str(source_ref or '')
        if source == 'local': namespace = str(Path(namespace).expanduser().resolve())
    pk = tc.get('id')
    if pk is not None and str(pk) and source != 'local':
        key = ['pk', str(pk)]
    else:
        number = tc.get('tc_id', tc.get('tc_no'))
        if number is None or str(number) == '': raise ValueError('TC 고유 식별자가 없습니다.')
        key = ['number', str(tc.get('sheet', tc.get('sheet_name')) or ''), str(number)]
    return dict(version=1, source=str(source), namespace=namespace, key=key)


def record_identity(record):
    stored = record['execution'].get('training_identity')
    return stored if stored is not None else identity(record['tc'], record['execution'].get('source'), record['execution'].get('source_ref'))


def capture(root, tc, *, source, source_ref, server_url=None):
    """배타적 파일 게시로 최초 내용만 보존한다. 재요청·재시작에도 덮어쓰지 않는다."""
    ident = identity(tc, source, source_ref, server_url)
    snapshot = {key: str(tc.get(key) or '') for key in ('title', *FIELDS)}
    if any(len(snapshot[key]) > 4000 for key in snapshot) or any(not snapshot[key].strip() for key in ('steps', 'expected')):
        raise ValueError('최초 TC의 절차·예상 결과와 항목별 4000자 제한을 확인하세요.')
    parent = Path(root) / '.training_originals'
    parent.mkdir(parents=True, exist_ok=True)
    target = parent / (digest(ident) + '.json')
    document = dict(schema_version=1, identity=ident, captured_at=datetime.now(timezone.utc).isoformat(),
                    origin='before_first_optimization', tc=snapshot)
    handle, temporary = tempfile.mkstemp(prefix='.partial_', dir=parent)
    try:
        with os.fdopen(handle, 'w', encoding='utf-8') as stream:
            json.dump(document, stream, ensure_ascii=False, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        try:
            os.link(temporary, target)
        except FileExistsError:
            pass
    finally:
        os.unlink(temporary)
    return load(root, ident)


def load(root, ident):
    target = Path(root) / '.training_originals' / (digest(ident) + '.json')
    if target.is_symlink(): raise ValueError('최초 원문 외부 파일 참조는 지원하지 않습니다.')
    if not target.exists(): return None
    document = json.loads(target.read_text(encoding='utf-8'))
    if document.get('identity') != ident or not isinstance(document.get('tc'), dict):
        raise ValueError('최초 TC 원문 식별자가 일치하지 않습니다.')
    return document
