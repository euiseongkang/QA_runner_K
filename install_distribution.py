"""배포 ZIP을 풀어 놓은 폴더에서 모델 또는 지식 원문을 설치한다."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time
from urllib.parse import quote, urlsplit
from urllib.request import Request, build_opener, ProxyHandler, HTTPRedirectHandler
import uuid


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


class WebUI:
    def __init__(self):
        self.url = os.environ.get('OPENWEBUI_URL', '').rstrip('/')
        self.key = os.environ.get('OPENWEBUI_API_KEY', '')
        parts = urlsplit(self.url)
        if parts.scheme not in ('http', 'https') or not parts.hostname or parts.username or parts.query or parts.fragment or not self.key:
            raise ValueError('OPENWEBUI_URL과 OPENWEBUI_API_KEY를 설정하세요.')
        self.opener = build_opener(ProxyHandler({}), NoRedirect())

    def request(self, method, path, data=None, body=None, content_type='application/json'):
        if data is not None:
            body = json.dumps(data).encode()
        request = Request(self.url + path, method=method, data=body,
                          headers={'Authorization': 'Bearer ' + self.key, 'Content-Type': content_type})
        try:
            with self.opener.open(request, timeout=120) as response:
                return json.load(response)
        except Exception:
            raise ValueError('Open WebUI API 요청 실패: ' + method + ' ' + path) from None

    def items(self, path):
        for page in range(1, 101):
            result = self.request('GET', path + '?page=' + str(page))
            items = result if isinstance(result, list) else result.get('items', [])
            yield from items
            if not items or isinstance(result, list):
                return
        raise ValueError('Open WebUI 목록이 너무 많습니다.')

    def upload(self, name, payload):
        boundary = 'qa-install-' + uuid.uuid4().hex
        body = (f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{name}"\r\n'
                'Content-Type: text/plain\r\n\r\n').encode() + payload + f'\r\n--{boundary}--\r\n'.encode()
        return self.request('POST', '/api/v1/files/', body=body, content_type='multipart/form-data; boundary=' + boundary)['id']

    def wait(self, identity):
        deadline = time.monotonic() + 900
        while time.monotonic() < deadline:
            status = self.request('GET', '/api/v1/files/' + quote(identity, safe='') + '/process/status')['status']
            if status == 'completed':
                return
            if status in ('failed', 'error'):
                raise ValueError('원문 재색인 실패. 수신 Open WebUI 임베딩 설정을 확인하세요.')
            time.sleep(2)
        raise ValueError('재색인 완료 대기 시간 초과')


def digest(path):
    value = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024*1024), b''):
            value.update(block)
    return value.hexdigest()


def verify(folder, manifest):
    for name, expected in manifest['checksums'].items():
        path = (folder / name).resolve()
        if not path.is_relative_to(folder.resolve()) or not path.is_file() or digest(path) != expected:
            raise ValueError('배포 파일 체크섬·경로 오류: ' + name)


def install_knowledge(folder, manifest):
    api = WebUI()
    description = 'QA 배포 원문; commit=' + manifest['commit'] + '; package=' + digest(folder / 'manifest.json')
    matches = [item for item in api.items('/api/v1/knowledge/') if item['name'] == manifest['knowledge_name']]
    if len(matches) > 1 or (matches and matches[0].get('description') != description):
        raise ValueError('같은 이름의 다른 지식 기반이 존재합니다. 덮어쓰지 않습니다.')
    identity = matches[0]['id'] if matches else api.request('POST', '/api/v1/knowledge/create',
                        data={'name': manifest['knowledge_name'], 'description': description})['id']
    path = '/api/v1/knowledge/' + quote(identity, safe='')
    linked = list(api.items(path + '/files'))
    state_file = folder / '.import_state.json'
    state = json.loads(state_file.read_text()) if state_file.exists() else {}
    binding = {'url': api.url, 'knowledge_id': identity, 'description': description}
    if any(state.get(key) != value for key, value in binding.items()):
        state = dict(binding, files={})
    for document in manifest['documents']:
        name = Path(document['filename']).name
        matches = [item for item in linked if item.get('filename') == name]
        if len(matches) > 1:
            raise ValueError('지식 문서가 중복되었습니다.')
        file_id = matches[0]['id'] if matches else state['files'].get(name)
        if not file_id:
            file_id = api.upload(name, (folder / document['filename']).read_bytes())
            state['files'][name] = file_id
            state_file.write_text(json.dumps(state, ensure_ascii=False, indent=2))
        api.wait(file_id)
        if not matches:
            api.request('POST', path + '/file/add', data={'file_id': file_id})
        if not any(item['id'] == file_id for item in api.items(path + '/files')):
            raise ValueError('지식 문서 연결 확인 실패')
    print('지식 기반 설치·재색인 완료. QA 프로그램에서 선택할 ID: ' + identity)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--model', action='store_true')
    group.add_argument('--knowledge', action='store_true')
    group.add_argument('--verify-only', action='store_true')
    parser.add_argument('--folder', default=str(Path(__file__).resolve().parent))
    args = parser.parse_args(argv)
    try:
        folder = Path(args.folder).resolve()
        manifest = json.loads((folder / 'manifest.json').read_text())
        verify(folder, manifest)
        if args.verify_only:
            print('배포 파일 체크섬 확인 완료')
            return 0
        if args.model:
            if manifest['kind'] != 'model':
                raise ValueError('모델 패키지가 아닙니다.')
            subprocess.run(['ollama', 'create', manifest['model_name'], '-f', str(folder / 'Modelfile')], cwd=folder, check=True)
            subprocess.run(['ollama', 'show', manifest['model_name']], check=True)
            print('모델 등록 완료. Open WebUI의 모델 목록을 갱신하세요.')
        else:
            if manifest['kind'] != 'knowledge':
                raise ValueError('지식 패키지가 아닙니다.')
            install_knowledge(folder, manifest)
        return 0
    except Exception as error:
        print('설치 중단: ' + (str(error) if isinstance(error, ValueError) else type(error).__name__))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
