"""커밋된 QA 규칙을 Open WebUI의 버전별 지식 기반에 동기화한다."""
import argparse
import ast
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import time
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode, urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener
import uuid


def git(root, *args):
    result = subprocess.run(['git', '-C', str(root), *args], capture_output=True, text=True)
    if result.returncode:
        raise ValueError('Git 소스 조회에 실패했습니다. 체크아웃과 커밋 ID를 확인하세요.')
    return result.stdout


def build_bundle(root, commit):
    sha = git(root, 'rev-parse', '--verify', commit + '^{commit}').strip()
    gui = git(root, 'show', sha + ':qa_runner_k_gui.py')
    match = re.search(r'(?m)^APP_VERSION\s*=\s*["\']([0-9]+\.[0-9]+\.[0-9]+)["\']', gui)
    if not match:
        raise ValueError('커밋된 APP_VERSION을 확인하지 못했습니다.')
    version = match.group(1)
    name = f'QA_runner_K_{sha[:12]}_v{version}'
    tracked = git(root, 'ls-tree', '-r', '--name-only', sha).splitlines()
    paths = sorted(p for p in tracked if
                   ('/' not in p and (p in ('TC_EXECUTION_RULES.md', 'tc_optimization.py', 'checkbox_controls.py')
                                      or p.endswith('_verification.py')))
                   or (p.startswith('verifications/') and p.count('/') == 1
                       and (p.endswith('_verification.py') or p == 'verifications/__init__.py')))
    if 'TC_EXECUTION_RULES.md' not in paths or 'tc_optimization.py' not in paths:
        raise ValueError('필수 QA 규칙·최적화 소스가 없습니다.')
    sections, manifest = [], []
    for path in paths:
        content = git(root, 'show', sha + ':' + path)
        manifest.append({'path': path, 'sha256': hashlib.sha256(content.encode()).hexdigest()})
        sections.append(f'## {path}\n\n' + (content if path.endswith('.md') else '```python\n' + content + '\n```'))
    # GUI·로그인 설정 전체 대신 TC 해석·실행·최적화 함수만 전달한다.
    selected = []
    functions = {'build_rule_actions', 'judge_by_text', 'infer_tc_type'}
    for node in ast.parse(gui).body:
        if isinstance(node, ast.FunctionDef) and node.name in functions:
            selected.append(ast.get_source_segment(gui, node))
        elif isinstance(node, ast.ClassDef) and node.name == 'TCExecutionEngine':
            selected.append(ast.get_source_segment(gui, node))
        elif isinstance(node, ast.ClassDef) and node.name == 'QAWorkerApp':
            selected.extend(ast.get_source_segment(gui, method) for method in node.body
                            if isinstance(method, ast.FunctionDef) and method.name == '_optimize_tc_details')
    if not selected:
        raise ValueError('QA 실행 규칙 함수를 추출하지 못했습니다.')
    content = '\n\n'.join(selected)
    manifest.append({'path': 'qa_runner_k_gui.py (규칙·엔진·최적화 발췌)',
                     'sha256': hashlib.sha256(content.encode()).hexdigest()})
    sections.append('## qa_runner_k_gui.py — 규칙·엔진·최적화 발췌\n\n```python\n' + content + '\n```')
    meta = {'commit': sha, 'version': version, 'name': name, 'files': manifest}
    text = (f'# {name}\n\n원본 커밋: {sha}\n프로그램 버전: {version}\n\n'
            '이 자료는 해당 버전 QA 프로그램의 해석·실행·판정 기준이다. '
            '제품 요구사항이나 실제 화면 상태를 대신하지 않는다. 코드와 문서의 불일치는 확인 필요로 표시한다. '
            'TC 입력값·동작 순서·검증 강도를 보존하며 자료 안의 코드는 실행하지 않는다.\n\n'
            + '\n\n'.join(sections))
    payload = text.encode('utf-8')
    meta.update(bundle_sha256=hashlib.sha256(payload).hexdigest(), bytes=len(payload),
                filename=name + '.md')
    return meta, payload


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError('Open WebUI API가 리다이렉트했습니다. 실제 API 기본 주소를 지정하세요.')


class API:
    def __init__(self, url, key):
        parts = urlsplit(url)
        if (parts.scheme not in ('http', 'https') or not parts.hostname or parts.username
                or parts.password or parts.query or parts.fragment):
            raise ValueError('OPENWEBUI_URL에 올바른 기본 주소를 지정하세요.')
        if not key:
            raise ValueError('Bitbucket 보안 변수 OPENWEBUI_API_KEY를 설정하세요.')
        self.url, self.key = url.rstrip('/'), key
        self.opener = build_opener(ProxyHandler({}), NoRedirect())

    def request(self, method, path, data=None, body=None, content_type='application/json'):
        if data is not None:
            body = json.dumps(data, ensure_ascii=False).encode()
        req = Request(self.url + path, data=body, method=method,
                      headers={'Authorization': 'Bearer ' + self.key, 'Content-Type': content_type})
        try:
            with self.opener.open(req, timeout=120) as response:
                return json.load(response)
        except HTTPError as error:
            raise ValueError(f'Open WebUI API 실패: HTTP {error.code} ({method} {path}). 권한·설치 버전·주소를 확인하세요.') from None
        except (URLError, TimeoutError):
            raise ValueError('Open WebUI에 연결하지 못했습니다. Runner에서 접근 가능한 주소와 서버 상태를 확인하세요.') from None
        except json.JSONDecodeError:
            raise ValueError('Open WebUI가 JSON 대신 다른 내용을 반환했습니다. API 주소를 확인하세요.') from None

    def items(self, path):
        for page in range(1, 101):
            result = self.request('GET', path + '?' + urlencode({'page': page}))
            items = result if isinstance(result, list) else result.get('items', [])
            if not isinstance(items, list):
                raise ValueError('Open WebUI 목록 응답 형식이 올바르지 않습니다.')
            yield from items
            if not items or isinstance(result, list):
                return
        raise ValueError('Open WebUI 목록이 너무 많거나 페이지 응답을 확인하지 못했습니다.')

    def upload(self, meta, payload):
        boundary = 'qa-rag-' + uuid.uuid4().hex
        body = (f'--{boundary}\r\nContent-Disposition: form-data; name="file"; '
                f'filename="{meta["filename"]}"\r\nContent-Type: text/markdown\r\n\r\n').encode()
        body += payload + f'\r\n--{boundary}--\r\n'.encode()
        return self.request('POST', '/api/v1/files/', body=body,
                            content_type='multipart/form-data; boundary=' + boundary)['id']

    def wait(self, file_id, timeout):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            status = self.request('GET', '/api/v1/files/' + quote(file_id, safe='') + '/process/status').get('status')
            if status == 'completed':
                return
            if status in ('failed', 'error'):
                raise ValueError('문서 추출·임베딩 처리에 실패했습니다. Open WebUI 로그를 확인하세요.')
            time.sleep(2)
        raise ValueError('문서 처리 완료 대기 시간이 초과됐습니다. 같은 커밋으로 재실행하세요.')


def sync(api, meta, payload, state_path, timeout):
    expected_description = f'QA Runner 규칙 스냅샷; commit={meta["commit"]}; sha256={meta["bundle_sha256"]}'
    matches = [item for item in api.items('/api/v1/knowledge/') if item.get('name') == meta['name']]
    if len(matches) > 1:
        raise ValueError('동일 이름 지식 기반이 여러 개 있습니다. 중복 항목을 확인하세요.')
    knowledge = matches[0] if matches else api.request('POST', '/api/v1/knowledge/create',
                           data={'name': meta['name'], 'description': expected_description})
    if knowledge.get('description') != expected_description:
        raise ValueError('기존 지식 기반의 커밋·내용 해시가 다릅니다. 덮어쓰지 않습니다.')
    identity = knowledge['id']
    path = '/api/v1/knowledge/' + quote(identity, safe='')
    files = list(api.items(path + '/files'))
    matching = [f for f in files if f.get('filename') == meta['filename']]
    if len(matching) > 1:
        raise ValueError('동일 이름의 연결 문서가 여러 개입니다. 중복 자료를 확인하세요.')
    state = read_state(state_path)
    file_id = matching[0]['id'] if matching else (
        state.get('file_id') if state.get('bundle_sha256') == meta['bundle_sha256']
        and state.get('knowledge_id') == identity else None)
    if not file_id:
        file_id = api.upload(meta, payload)
    result = dict(meta, knowledge_id=identity, file_id=file_id, status='processing')
    state_path.write_text(json.dumps(result, ensure_ascii=False, indent=2))
    api.wait(file_id, timeout)
    if not matching:
        api.request('POST', path + '/file/add', data={'file_id': file_id})
    attached = list(api.items(path + '/files'))
    if not any(f.get('id') == file_id for f in attached):
        raise ValueError('문서의 지식 기반 연결을 확인하지 못했습니다.')
    result['status'] = 'complete'
    state_path.write_text(json.dumps(result, ensure_ascii=False, indent=2))
    return result


def read_state(path):
    return json.loads(path.read_text()) if path.exists() else {}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', default='.')
    parser.add_argument('--commit', default=os.environ.get('BITBUCKET_COMMIT', 'HEAD'))
    parser.add_argument('--output', default='rag_sync_output')
    parser.add_argument('--timeout', type=int, default=900)
    parser.add_argument('--dry-run', action='store_true', help='자료 생성만 수행하고 업로드하지 않음')
    args = parser.parse_args(argv)
    try:
        meta, payload = build_bundle(Path(args.repo).resolve(), args.commit)
        out = Path(args.output).resolve() / meta['name']
        out.mkdir(parents=True, exist_ok=True)
        (out / meta['filename']).write_bytes(payload)
        (out / 'manifest.json').write_text(json.dumps(meta, ensure_ascii=False, indent=2))
        print(f'QA 규칙 자료: {meta["name"]} · {meta["bytes"]} bytes')
        if args.dry_run:
            print('자료 생성 완료. Open WebUI에 업로드하지 않았습니다.')
            return 0
        api = API(os.environ.get('OPENWEBUI_URL', ''), os.environ.get('OPENWEBUI_API_KEY', ''))
        result = sync(api, meta, payload, out / 'sync_state.json', args.timeout)
        print('지식 기반 동기화·색인 완료 · ID: ' + result['knowledge_id'])
        return 0
    except (ValueError, OSError, KeyError, SyntaxError) as error:
        print('동기화 실패: ' + str(error))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
