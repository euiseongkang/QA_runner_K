"""커밋별 QA Open WebUI 지식 원문 패키지 생성 및 Drive 게시. 모델은 선택 기능."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import shutil
import zipfile
from urllib.parse import quote

from rag_sync import API, build_bundle, git

ROOT = Path(__file__).resolve().parent
FOLDERS = {'model': '11U7VeTxdThwpBTOvfDbAmR9z4O9L92tH',
           'qa': '1X9vbsAVd14Jr8m1mAOVLQO5KQGcNCTvR'}


def digest(path):
    result = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            result.update(block)
    return result.hexdigest()


def export_knowledge(api, identity):
    details = api.request('GET', '/api/v1/knowledge/' + quote(identity, safe=''))
    documents = []
    for item in api.items('/api/v1/knowledge/' + quote(identity, safe='') + '/files'):
        file_id = item['id']
        api.wait(file_id, 900)
        content = api.request('GET', '/api/v1/files/' + quote(file_id, safe='') + '/data/content').get('content')
        if not isinstance(content, str) or not content.strip():
            raise ValueError('지식 파일의 추출된 원문이 비어 있습니다: ' + file_id)
        documents.append({'filename': f'documents/{len(documents)+1:04d}.txt', 'source_name': item.get('filename', ''),
                          'payload': content.encode('utf-8')})
    if not documents:
        raise ValueError('내보낼 지식 파일이 없습니다.')
    return {'name': details['name'], 'source_knowledge_id': identity}, documents


def package(path, manifest, files):
    """허용한 파일만 압축하고 수신 측에서 확인할 체크섬을 기록한다."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    checksums = {}
    for name, value in files.items():
        if Path(name).is_absolute() or '..' in Path(name).parts:
            raise ValueError('패키지 내부 경로가 잘못되었습니다.')
        checksums[name] = digest(value) if isinstance(value, Path) else hashlib.sha256(value).hexdigest()
    record = dict(manifest, schema_version=1, checksums=checksums)
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False, suffix='.zip') as temp:
        temporary = Path(temp.name)
    try:
        with zipfile.ZipFile(temporary, 'w', compression=zipfile.ZIP_STORED, allowZip64=True) as archive:
            for name, value in files.items():
                if isinstance(value, Path):
                    info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
                    with value.open('rb') as source, archive.open(info, 'w', force_zip64=True) as target:
                        shutil.copyfileobj(source, target, 1024*1024)
                else:
                    archive.writestr(zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0)), value)
            archive.writestr(zipfile.ZipInfo('manifest.json', date_time=(1980, 1, 1, 0, 0, 0)), json.dumps(record, ensure_ascii=False, indent=2))
        if path.exists():
            if digest(path) != digest(temporary):
                raise ValueError('같은 이름의 다른 배포 패키지가 있습니다. 덮어쓰지 않습니다.')
        else:
            os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
    return path


def model_package(out, meta, latest, artifact_root):
    def local(key):
        path = Path(latest[key]).expanduser()
        return path if path.is_absolute() else artifact_root / path
    gguf = local('gguf')
    with gguf.open('rb') as stream:
        if stream.read(4) != b'GGUF':
            raise ValueError('최신 모델이 GGUF 파일이 아닙니다.')
    template = local('modelfile').read_text()
    if len(re.findall(r'^FROM\s+.*$', template, re.M)) != 1:
        raise ValueError('Modelfile FROM을 하나로 식별하지 못했습니다.')
    template = re.sub(r'^FROM\s+.*$', 'FROM ./model.gguf', template, flags=re.M)
    name = latest['name'] + '_' + meta['commit'][:12]
    files = {'model.gguf': gguf, 'Modelfile': template.encode(),
             'install_package.py': (ROOT / 'install_distribution.py').read_bytes(),
             'README.txt': 'Ollama 설치 후 python3 install_package.py --model 을 실행하세요.\nOpen WebUI의 Ollama 연결에서 모델 목록을 갱신하세요.\n'.encode()}
    return package(out / name / 'runtime.zip', {'kind': 'model', 'commit': meta['commit'], 'app_version': meta['version'],
                   'model_name': latest['name'], 'model_origin': latest.get('base_model', ''),
                   'model_verification': latest.get('verification', ''),
                   'note': '앱 커밋 버전과 모델 버전은 별도다. 이 게시 작업은 재학습하지 않는다.'}, files)


def training_environment(artifact_root):
    python = artifact_root / 'finetuning/.venv/bin/python'
    if not python.is_file():
        python = Path(sys.executable)
    code = '''import json,platform
from importlib import metadata
versions={}
for name in ('mlx-lm','mlx','transformers','tokenizers','safetensors','numpy','sentencepiece','protobuf','torch'):
 try: versions[name]=metadata.version(name)
 except metadata.PackageNotFoundError: pass
print(json.dumps({'python':platform.python_version(),'packages':versions}))'''
    info = json.loads(subprocess.check_output([str(python), '-c', code], text=True))
    info['training_versions_available'] = 'mlx-lm' in info['packages']
    requirements = []
    for name in ('mlx-lm', 'mlx', 'transformers', 'tokenizers', 'safetensors', 'numpy', 'sentencepiece', 'protobuf'):
        version = info['packages'].get(name)
        package_name = 'mlx-lm[train]' if name == 'mlx-lm' else name
        requirements.append(package_name + ('==' + version if version else ''))
    return info, '\n'.join(requirements) + '\n'


def training_package(out, meta, latest, artifact_root):
    from finetuning_pipeline import verify_model
    model = Path(latest['fused_model']).expanduser()
    if not model.is_absolute():
        model = artifact_root / model
    verify_model(model)
    allowed = {'config.json', 'generation_config.json', 'tokenizer.json', 'tokenizer_config.json',
               'special_tokens_map.json', 'added_tokens.json', 'vocab.json', 'merges.txt',
               'tokenizer.model', 'chat_template.jinja', 'model.safetensors.index.json', 'LICENSE', 'LICENSE.txt'}
    index = model / 'model.safetensors.index.json'
    weights = set(json.loads(index.read_text())['weight_map'].values()) if index.exists() else {'model.safetensors'}
    if any(Path(name).name != name for name in weights):
        raise ValueError('가중치 인덱스에 폴더 밖의 경로가 있습니다.')
    files = {'fused_model/' + p.name: p for p in model.iterdir() if p.is_file() and p.name in allowed | weights}
    env, requirements = training_environment(artifact_root)
    files['environment.json'] = json.dumps(env, ensure_ascii=False, indent=2).encode()
    files['requirements-training.txt'] = requirements.encode()
    text = (ROOT / 'templates/TRAINING_README.md').read_text()
    for token, value in {'MODEL_NAME': latest['name'], 'APP_VERSION': meta['version'], 'COMMIT': meta['commit']}.items():
        text = text.replace('{{' + token + '}}', value)
    files['README.md'] = text.encode()
    for name in ('finetuning_pipeline.py', 'gguf_pipeline.py'):
        files[name] = (ROOT / name).read_bytes()
    files['verify_package.py'] = (ROOT / 'install_distribution.py').read_bytes()
    modelfile = Path(latest['modelfile']).expanduser()
    if not modelfile.is_absolute():
        modelfile = artifact_root / modelfile
    template = modelfile.read_text()
    if len(re.findall(r'^FROM\s+.*$', template, re.M)) != 1:
        raise ValueError('학습용 Modelfile 템플릿의 FROM이 모호합니다.')
    files['Modelfile.template'] = re.sub(r'^FROM\s+.*$', 'FROM ./model-next-f16.gguf', template, flags=re.M).encode()
    prefix = '''#!/bin/bash
set -euo pipefail
script_dir="$(cd "$(dirname "$0")" && pwd)"
package_dir="$(cd "$script_dir/.." && pwd)"
python_path="$package_dir/.venv/bin/python"
if [ ! -x "$python_path" ]; then echo "README.md에 따라 .venv를 설치하세요." >&2; exit 1; fi
'''
    files['scripts/run_train.sh'] = (prefix + 'exec "$python_path" -m mlx_lm.lora --model "$package_dir/fused_model" "$@"\n').encode()
    files['scripts/run_post_training.sh'] = (prefix + 'exec "$python_path" "$package_dir/finetuning_pipeline.py" "$@"\n').encode()
    files['scripts/run_gguf_conversion.sh'] = (prefix + 'exec "$python_path" "$package_dir/gguf_pipeline.py" "$@"\n').encode()
    return package(out / (latest['name'] + '_' + meta['commit'][:12]) / 'training.zip',
                   {'kind': 'training', 'commit': meta['commit'], 'app_version': meta['version'],
                    'model_name': latest['name'], 'starting_model': 'fused_model',
                    'note': '병합 모델에서 추가 학습. 기존 어댑터·원본 JSONL·인증 파일은 포함하지 않음.'}, files)


def knowledge_package(out, meta, source, docs, kind):
    files = {d['filename']: d['payload'] for d in docs}
    files['install_package.py'] = (ROOT / 'install_distribution.py').read_bytes()
    files['README.txt'] = ('Open WebUI의 임베딩 엔진·모델 설정 후 실행하세요. API Key는 패키지에 포함되지 않습니다.\n'
                          'OPENWEBUI_URL, OPENWEBUI_API_KEY를 환경변수로 설정하고 python3 install_package.py --knowledge 실행.\n'
                          '원문을 가져와 수신 서버에서 재색인합니다. 서버 UUID·벡터 DB를 복사하지 않습니다.\n').encode()
    name = meta['name'] + '_KNOWLEDGE_' + kind
    return package(out / (name + '.zip'), {'kind': 'knowledge', 'commit': meta['commit'], 'app_version': meta['version'],
                   'knowledge_name': name, 'source': source,
                   'documents': [{'filename': d['filename'], 'source_name': d['source_name']} for d in docs],
                   'embedding': '수신 Open WebUI의 임베딩 설정으로 재색인'}, files)


class Drive:
    def __init__(self):
        import google.auth
        from googleapiclient.discovery import build
        credentials, _ = google.auth.default(scopes=['https://www.googleapis.com/auth/drive'])
        self.service = build('drive', 'v3', credentials=credentials, cache_discovery=False)

    def folder(self, parent, name):
        if not re.fullmatch(r'[a-zA-Z0-9_.-]+', name):
            raise ValueError('배포 모델 폴더 이름이 잘못되었습니다.')
        files = self.service.files()
        result = files.list(q=f"'{parent}' in parents and trashed=false and name='{name}' and mimeType='application/vnd.google-apps.folder'",
                            supportsAllDrives=True, includeItemsFromAllDrives=True, fields='files(id),nextPageToken').execute()
        found = result.get('files', [])
        if len(found) > 1 or result.get('nextPageToken'):
            raise ValueError('모델 배포 폴더가 중복되었습니다.')
        if found:
            return found[0]['id']
        return files.create(body={'name': name, 'parents': [parent], 'mimeType': 'application/vnd.google-apps.folder'},
                            supportsAllDrives=True, fields='id').execute()['id']

    def upload(self, path, folder):
        from googleapiclient.http import MediaFileUpload
        files = self.service.files()
        folder_info = files.get(fileId=folder, supportsAllDrives=True,
                                fields='id,mimeType,capabilities(canAddChildren)').execute()
        if folder_info['mimeType'] != 'application/vnd.google-apps.folder' or not folder_info.get('capabilities', {}).get('canAddChildren'):
            raise ValueError('배포 폴더의 업로드 권한이 없습니다.')
        result = files.list(q=f"'{folder}' in parents and trashed=false and name='{path.name}'",
                            supportsAllDrives=True, includeItemsFromAllDrives=True,
                            fields='files(id,size,md5Checksum),nextPageToken').execute()
        existing = result.get('files', [])
        if len(existing) > 1 or result.get('nextPageToken'):
            raise ValueError('동일 이름의 배포 파일이 중복되어 있습니다.')
        md5 = hashlib.md5()
        with path.open('rb') as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b''):
                md5.update(block)
        if existing:
            if existing[0].get('md5Checksum') != md5.hexdigest() or int(existing[0].get('size', -1)) != path.stat().st_size:
                raise ValueError('Drive에 같은 이름의 다른 파일이 있어 덮어쓰지 않습니다.')
            identity = existing[0]['id']
        else:
            request = files.create(body={'name': path.name, 'parents': [folder]}, supportsAllDrives=True,
                                   media_body=MediaFileUpload(str(path), mimetype='application/zip', chunksize=8*1024*1024, resumable=True), fields='id')
            response = None
            while response is None:
                _, response = request.next_chunk(num_retries=3)
            identity = response['id']
        info = files.get(fileId=identity, supportsAllDrives=True, fields='id,size,md5Checksum,webViewLink').execute()
        if int(info.get('size', -1)) != path.stat().st_size or info.get('md5Checksum') != md5.hexdigest():
            raise ValueError('Drive 업로드 파일 검사에 실패했습니다.')
        return info


def register_local_model(latest, artifact_root):
    def local(key):
        path = Path(latest[key]).expanduser()
        return (path if path.is_absolute() else artifact_root / path).resolve()
    gguf = local('gguf')
    with gguf.open('rb') as stream:
        if stream.read(4) != b'GGUF':
            raise ValueError('Ollama 등록 대상이 GGUF 파일이 아닙니다.')
    template = local('modelfile').read_text()
    if len(re.findall(r'^FROM\s+.*$', template, re.M)) != 1:
        raise ValueError('Ollama Modelfile FROM이 모호합니다.')
    template = re.sub(r'^FROM\s+.*$', lambda _: 'FROM ' + json.dumps(str(gguf), ensure_ascii=False), template, flags=re.M)
    with tempfile.TemporaryDirectory(prefix='qa-ollama-register-') as directory:
        modelfile = Path(directory) / 'Modelfile'
        modelfile.write_text(template)
        subprocess.run(['ollama', 'create', latest['name'], '-f', str(modelfile)], check=True)
        subprocess.run(['ollama', 'show', latest['name']], check=True)
    return {'status': 'registered', 'model_name': latest['name'], 'gguf_sha256': digest(gguf)}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--commit', default=os.environ.get('BITBUCKET_COMMIT', 'HEAD'))
    parser.add_argument('--output', default='distribution_output')
    parser.add_argument('--artifact-root', default=os.environ.get('QA_MODEL_ARTIFACT_ROOT', str(ROOT)))
    parser.add_argument('--include-model', action='store_true', help='명시한 경우에만 최신 모델도 게시')
    parser.add_argument('--model-registry', help='현재 커밋의 Runner가 생성한 후보 모델 레지스트리')
    parser.add_argument('--upload', action='store_true')
    parser.add_argument('--register-local-model', action='store_true', help='모든 Drive 업로드 성공 후 Runner의 Ollama에 등록')
    parser.add_argument('--dry-run', action='store_true', help='게시 대상 계획만 출력; 패키지·서버 변경 없음')
    args = parser.parse_args(argv)
    try:
        if args.register_local_model and not (args.include_model and args.upload):
            raise ValueError('--register-local-model에는 --include-model과 --upload가 필요합니다.')
        meta, _ = build_bundle(ROOT, args.commit)
        latest = None
        if args.include_model:
            if args.model_registry:
                registry = json.loads(Path(args.model_registry).read_text())
                if registry.get('distribution_commit') != meta['commit']:
                    raise ValueError('Runner 후보 모델 레지스트리의 배포 커밋이 다릅니다.')
                latest = registry['latest']
            else:
                latest = json.loads(git(ROOT, 'show', meta['commit'] + ':finetuning/model_registry.json'))['latest']
        if args.dry_run:
            print(json.dumps({'snapshot': meta['name'], 'model': latest['name'] if latest else None,
                              'folders': {k: v for k, v in FOLDERS.items() if k == 'qa' or latest},
                              'knowledge_id_source': '동일 커밋 rag_sync_output/.../sync_state.json'}, ensure_ascii=False, indent=2))
            return 0
        state = json.loads((ROOT / 'rag_sync_output' / meta['name'] / 'sync_state.json').read_text())
        if (state.get('status') != 'complete' or state.get('bundle_sha256') != meta['bundle_sha256']
                or state.get('commit') != meta['commit']):
            raise ValueError('동일 커밋의 QA 지식 기반 동기화가 먼저 완료되어야 합니다.')
        api = API(os.environ.get('OPENWEBUI_URL', ''), os.environ.get('OPENWEBUI_API_KEY', ''))
        qa_source, qa_docs = export_knowledge(api, state['knowledge_id'])
        # QA 스냅샷은 한 문서다. 서버 내용 변경 시 다른 커밋 자료로 게시하지 않는다.
        if len(qa_docs) != 1 or hashlib.sha256(qa_docs[0]['payload']).hexdigest() != meta['bundle_sha256']:
            raise ValueError('Open WebUI의 QA 원문이 커밋 스냅샷과 다릅니다.')
        out = Path(args.output).resolve() / meta['name']
        out.mkdir(parents=True, exist_ok=True)
        packages = {'qa': knowledge_package(out, meta, qa_source, qa_docs, 'QA_runner_K')}
        if latest:
            packages['model'] = model_package(out, meta, latest, Path(args.artifact_root).expanduser().resolve())
            packages['training'] = training_package(out, meta, latest, Path(args.artifact_root).expanduser().resolve())
        report = {'commit': meta['commit'], 'app_version': meta['version'], 'status': 'packaged', 'packages': {}}
        for kind, path in packages.items():
            report['packages'][kind] = {'path': str(path), 'sha256': digest(path), 'bytes': path.stat().st_size}
        (out / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2))
        if args.upload:
            drive = Drive()
            model_folder = drive.folder(FOLDERS['model'], latest['name'] + '_' + meta['commit'][:12]) if latest else None
            for kind, path in packages.items():
                report['packages'][kind]['drive'] = drive.upload(path, model_folder if kind in ('model', 'training') else FOLDERS[kind])
                (out / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2))
            report['status'] = 'uploaded'
            (out / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2))
        if args.register_local_model:
            report['ollama'] = register_local_model(latest, Path(args.artifact_root).expanduser().resolve())
            report['status'] = 'uploaded_and_registered'
            (out / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2))
        print('배포 패키지 처리 완료: ' + str(out / 'report.json'))
        return 0
    except Exception as error:
        # 인증·HTTP 오류 본문에는 민감 정보가 포함될 수 있어 원문을 출력하지 않는다.
        message = str(error) if isinstance(error, (ValueError, FileNotFoundError)) else type(error).__name__
        print('게시 중단: ' + message)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
