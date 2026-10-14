"""Mac Runner: 최신 내보내기 → 추가 학습 → 평가·병합 → GGUF → Drive → Ollama."""
import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

import model_release as release
from finetuning_pipeline import test_count, verify_model
from rag_sync import build_bundle, git

ROOT = Path(__file__).resolve().parent
DATA_FILES = ('train.jsonl', 'valid.jsonl', 'test.jsonl')


def dataset_hash(folder):
    digest = hashlib.sha256()
    for filename in DATA_FILES:
        test_count(folder / filename)
        digest.update(filename.encode())
        digest.update((folder / filename).read_bytes())
    return digest.hexdigest()


def select_dataset(artifact_root):
    # 내보내기는 임시 폴더에서 완성된 뒤 이름이 변경되므로 완료 폴더만 선택한다.
    choices = sorted((artifact_root / 'finetuning').glob('qa_tc_dataset_*/export_summary.json'))
    if not choices:
        raise ValueError('finetuning에 완료된 내보내기가 없습니다. QA 프로그램에서 학습 데이터를 내보내세요.')
    folder = choices[-1].parent
    dataset_hash(folder)
    return folder


def absolute_registry(registry, artifact_root):
    value = json.loads(json.dumps(registry))
    for key in ('fused_model', 'adapter', 'gguf', 'modelfile', 'dataset', 'base_model', 'template_source'):
        if value['latest'].get(key):
            path = Path(value['latest'][key]).expanduser()
            value['latest'][key] = str((path if path.is_absolute() else artifact_root / path).resolve())
    return value


def run(command):
    subprocess.run([str(item) for item in command], check=True)


def training_interpreter(value):
    # venv/bin/python의 심볼릭 링크를 풀면 시스템 Python으로 실행되어 venv를 잃는다.
    return Path(os.path.abspath(Path(value).expanduser()))


def check_training_environment(python):
    subprocess.run([str(python), '-c',
                    'import importlib.util,sys; print("학습 Python:",sys.executable,flush=True); '
                    'sys.exit(0 if importlib.util.find_spec("mlx_lm") else '
                    '"학습 가상환경에 mlx_lm이 없습니다. QA_TRAINING_PYTHON을 확인하세요.")'], check=True)


def check_model_trigger():
    tag = os.environ.get('BITBUCKET_TAG', '')
    in_pipeline = bool(os.environ.get('BITBUCKET_BUILD_NUMBER') or os.environ.get('BITBUCKET_PIPELINE_UUID'))
    if in_pipeline or tag:
        if not re.fullmatch(r'model-v[0-9]+(?:\.[0-9]+){0,2}-[0-9]{8}-[0-9]{2}', tag):
            raise ValueError('모델 학습은 model-v35-20261014-01 형식의 태그에서만 실행합니다.')
        allowed = os.environ.get('QA_MODEL_BUILD_ALLOWED_ACTOR_UUID', '').strip().strip('{}')
        actor = os.environ.get('BITBUCKET_STEP_TRIGGERER_UUID', '').strip().strip('{}')
        if allowed and actor != allowed:
            raise ValueError('허용된 계정이 실행한 모델 학습 요청이 아닙니다.')
    return tag


def pipeline(args):
    tag = check_model_trigger()
    artifact_root = Path(args.artifact_root).expanduser().resolve()
    meta, _ = build_bundle(ROOT, args.commit)
    dataset = select_dataset(artifact_root)
    fingerprint = dataset_hash(dataset)
    cache = artifact_root / 'finetuning/.runner'
    registry_path = cache / 'model_registry.json'
    registry = (release.read(registry_path) if registry_path.exists() else
                absolute_registry(json.loads(git(ROOT, 'show', meta['commit'] + ':finetuning/model_registry.json')), artifact_root))
    verify_model(registry['latest']['fused_model'])
    python = training_interpreter(args.training_python or artifact_root / 'finetuning/.venv/bin/python')
    llama_cpp = Path(args.llama_cpp).expanduser().resolve()
    if not python.is_file():
        raise ValueError('MLX 학습 Python이 없습니다: ' + str(python))
    check_training_environment(python)
    if not (llama_cpp / 'convert_hf_to_gguf.py').is_file():
        raise ValueError('llama.cpp 변환 도구가 없습니다: ' + str(llama_cpp))
    needs_training = registry['latest'].get('dataset_sha256') != fingerprint
    version = meta['version'].split('.')
    name = 'qa-tc-optimizer-v' + (version[1] if len(version) >= 2 and version[0] == '0' else meta['version'])
    print(json.dumps({'commit':meta['commit'], 'tag':tag, 'dataset':str(dataset), 'dataset_sha256':fingerprint,
                      'base_model':registry['latest']['fused_model'], 'new_training':needs_training,
                      'model_name':name if needs_training else registry['latest']['name'],
                      'steps':['train','evaluate_and_fuse','gguf','drive_upload','ollama_register']}, ensure_ascii=False, indent=2), flush=True)
    if args.dry_run:
        return
    cache.mkdir(parents=True, exist_ok=True)
    with (cache / 'pipeline.lock').open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ValueError('다른 모델 파이프라인이 실행 중입니다. 완료 후 재실행하세요.')
        # 계획 확인 이후 다른 실행이 최신 모델을 변경했으면 최신 상태부터 다시 시작한다.
        if registry_path.exists() and release.read(registry_path) != registry:
            raise ValueError('실행 준비 중 최신 모델이 변경되었습니다. 파이프라인을 재실행하세요.')
        if not registry_path.exists():
            release.save(registry_path, registry)
        work = cache / 'runs' / meta['commit']
        work.mkdir(parents=True, exist_ok=True)
        candidate_path = work / 'candidate_registry.json'
        if candidate_path.exists():
            candidate = release.read(candidate_path)
            if candidate.get('export_sha256') != fingerprint:
                raise ValueError('같은 커밋의 내보내기 데이터가 변경되었습니다. 새 커밋으로 실행하세요.')
        elif needs_training:
            snapshot = work / 'dataset'
            snapshot.mkdir(exist_ok=True)
            state = snapshot / 'model_release.json'
            if not state.exists():
                for filename in (*DATA_FILES, 'export_summary.json', 'lineage.json'):
                    source = dataset / filename
                    if source.is_file():
                        shutil.copyfile(source, snapshot / filename)
            if dataset_hash(snapshot) != fingerprint:
                raise ValueError('내보내기 데이터가 복사 중 변경되었거나 기존 실행 데이터와 다릅니다.')
            common = ['--dataset',str(snapshot),'--registry',str(registry_path)]
            if not state.exists():
                run([python,ROOT/'model_release.py','train',*common,'--name',name,'--iters',args.iters])
            plan = release.read(state)
            if plan['stage'] == 'prepared':
                # 시작 전 환경 오류처럼 산출물이 없는 실패만 재시도한다.
                run([python,ROOT/'model_release.py','train',*common,'--name',name,
                     '--iters',args.iters,'--retry-prepared'])
                plan = release.read(state)
            if plan['stage'] == 'train':
                run([python,ROOT/'model_release.py','post',*common])
                plan = release.read(state)
            if plan['stage'] == 'post':
                run([python,ROOT/'model_release.py','gguf',*common,'--llama-cpp',str(llama_cpp)])
                plan = release.read(state)
            if plan['stage'] != 'gguf':
                raise ValueError('모델 생성 단계가 완료되지 않았습니다.')
            verify_model(plan['fused_model'])
            # GGUF 구조 검사는 직전 gguf 단계에서 MLX 가상환경으로 완료했다.
            Path(plan['modelfile']).write_text(release.modelfile(plan))
            candidate = {'schema_version':1, 'distribution_commit':meta['commit'], 'export_sha256':fingerprint,
                         'build_tag':tag,
                         'latest':{**plan,'dataset_sha256':fingerprint,'training_commit':meta['commit'],
                                   'verification':'MLX 평가·병합 파일·GGUF 검사 완료; 실제 TC 답변 품질은 별도 평가'},
                         'history':registry.get('history',[]) + [registry['latest']]}
            release.save(candidate_path,candidate)
        else:
            candidate = {**registry,'distribution_commit':meta['commit'],'export_sha256':fingerprint,'build_tag':tag}
            release.save(candidate_path,candidate)
        run([args.distribution_python, ROOT/'distribution_package.py','--commit',meta['commit'],
             '--artifact-root',str(artifact_root),'--model-registry',str(candidate_path),
             '--include-model','--upload','--register-local-model'])
        # Drive 업로드와 Ollama 등록이 모두 성공해야 다음 학습의 시작 모델을 갱신한다.
        candidate['latest']['stage'] = 'published'
        release.save(registry_path,candidate)
        print('Runner 학습·Drive 게시·Ollama 등록 완료: ' + candidate['latest']['name'], flush=True)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--commit',default=os.environ.get('BITBUCKET_COMMIT','HEAD'))
    parser.add_argument('--artifact-root',default=os.environ.get('QA_MODEL_ARTIFACT_ROOT',str(Path.home()/'Projects/QA_runner_K')))
    parser.add_argument('--training-python',default=os.environ.get('QA_TRAINING_PYTHON'))
    parser.add_argument('--distribution-python',default=os.environ.get('QA_DISTRIBUTION_PYTHON',sys.executable))
    parser.add_argument('--llama-cpp',default=os.environ.get('QA_LLAMA_CPP',str(Path.home()/'Projects/llama.cpp')))
    parser.add_argument('--iters',type=int,default=int(os.environ.get('QA_TRAIN_ITERS','20')))
    parser.add_argument('--dry-run',action='store_true')
    args = parser.parse_args(argv)
    try:
        if args.iters < 1:
            raise ValueError('학습 반복 횟수는 양수여야 합니다.')
        pipeline(args)
        return 0
    except (OSError,ValueError,KeyError,subprocess.CalledProcessError) as error:
        print('Runner 중단: ' + str(error),file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
