"""기록된 최신 병합 모델을 기준으로 추가 학습·검사·GGUF·Ollama 배포를 실행한다."""
import argparse
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import sys
from datetime import datetime, timezone

from finetuning_pipeline import verify_model
from gguf_pipeline import verify_gguf

ROOT = Path(__file__).resolve().parent
REGISTRY = ROOT / 'finetuning/model_registry.json'


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def save(path, value):
    path = Path(path)
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    os.replace(temporary, path)


def resolve(value):
    path = Path(value).expanduser()
    return (path if path.is_absolute() else ROOT / path).resolve()


def execute(command, dry_run):
    print(shlex.join(command), flush=True)
    if not dry_run:
        subprocess.run(command, check=True)


def create_plan(dataset, name, latest):
    if not re.fullmatch(r'[a-z0-9][a-z0-9._-]*', name):
        raise ValueError('모델 이름은 영문 소문자·숫자·점·밑줄·하이픈만 사용할 수 있습니다.')
    for filename in ('train.jsonl', 'valid.jsonl', 'test.jsonl'):
        path = dataset / filename
        if not path.is_file() or not path.read_text().strip():
            raise ValueError('학습·평가 JSONL이 필요합니다: ' + str(path))
    base = resolve(latest['fused_model'])
    verify_model(base)
    return {'name': name, 'base_model': str(base), 'dataset': str(dataset),
            'adapter': str(dataset / ('adapters_' + name)),
            'fused_model': str(dataset / ('fused_' + name)),
            'gguf': str(dataset / (name + '-f16.gguf')),
            'modelfile': str(dataset / ('Modelfile.' + name)),
            'template_source': str(resolve(latest['modelfile'])), 'stage': 'prepared'}


def command_for(stage, plan, iterations=20, llama_cpp='~/Projects/llama.cpp'):
    if stage == 'train':
        return [sys.executable, '-m', 'mlx_lm.lora', '--model', plan['base_model'], '--train',
                '--data', plan['dataset'], '--adapter-path', plan['adapter'], '--iters', str(iterations),
                '--batch-size', '1', '--num-layers', '4', '--learning-rate', '1e-5',
                '--max-seq-length', '4096', '--mask-prompt', '--grad-checkpoint',
                '--steps-per-report', '10', '--steps-per-eval', '10', '--save-every', '10']
    if stage == 'post':
        return [sys.executable, str(ROOT / 'finetuning_pipeline.py'), '--dataset', plan['dataset'],
                '--adapter', plan['adapter'], '--output', plan['fused_model']]
    if stage == 'gguf':
        return [sys.executable, str(ROOT / 'gguf_pipeline.py'), '--model', plan['fused_model'],
                '--outfile', plan['gguf'], '--llama-cpp', str(Path(llama_cpp).expanduser())]
    if stage == 'deploy':
        return ['ollama', 'create', plan['name'], '-f', plan['modelfile']]
    raise ValueError('지원하지 않는 단계')


def modelfile(plan):
    template = Path(plan['template_source']).read_text(encoding='utf-8')
    if len(re.findall(r'^FROM\s+.*$', template, flags=re.M)) != 1:
        raise ValueError('원본 Modelfile의 FROM을 하나로 식별하지 못했습니다.')
    return re.sub(r'^FROM\s+.*$', lambda _: 'FROM ' + json.dumps(plan['gguf']), template, flags=re.M)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('stage', choices=('show', 'train', 'post', 'gguf', 'deploy', 'promote'))
    parser.add_argument('--dataset', help='새 학습 JSONL 폴더')
    parser.add_argument('--name', help='train 단계에서 생성할 새 모델 이름')
    parser.add_argument('--iters', type=int, default=20, help='시험 학습 기본 20회; 품질에 맞춰 조정')
    parser.add_argument('--llama-cpp', default='~/Projects/llama.cpp')
    parser.add_argument('--dry-run', action='store_true')
    parser.add_argument('--registry', default=str(REGISTRY), help='Runner 등에서 사용할 모델 레지스트리 경로')
    parser.add_argument('--retry-prepared', action='store_true', help='산출물 없이 준비 상태에서 실패한 동일 학습만 재시도')
    args = parser.parse_args(argv)
    try:
        registry_path = Path(args.registry).expanduser().resolve()
        registry = read(registry_path)
        if args.stage == 'show':
            print(json.dumps(registry, ensure_ascii=False, indent=2))
            return 0
        if not args.dataset:
            raise ValueError('--dataset을 지정하세요.')
        dataset = resolve(args.dataset)
        state = dataset / 'model_release.json'
        if args.stage == 'train':
            if not args.name or args.iters < 1:
                raise ValueError('--name과 양수 --iters가 필요합니다.')
            plan = create_plan(dataset, args.name, registry['latest'])
            if state.exists():
                if not args.retry_prepared or read(state) != plan:
                    raise ValueError('기존 실행과 준비 상태·데이터·시작 모델이 일치하지 않아 재학습하지 않습니다.')
            if any(Path(plan[k]).exists() for k in ('adapter', 'fused_model', 'gguf', 'modelfile')):
                raise ValueError('기존 모델 산출물은 덮어쓰지 않습니다. 새 모델 이름을 지정하세요.')
            if not args.dry_run:
                save(state, plan)
        else:
            plan = read(state)
            required = {'post': 'train', 'gguf': 'post', 'deploy': 'gguf', 'promote': 'deploy'}[args.stage]
            if plan['stage'] != required:
                raise ValueError(f"{args.stage} 전에 {required} 단계를 완료해야 합니다. 현재: {plan['stage']}")
        if args.stage == 'promote':
            verify_model(plan['fused_model'])
            verify_gguf(plan['gguf'], Path(args.llama_cpp).expanduser())
            print('최신 모델 변경: ' + plan['name'])
            if not args.dry_run:
                registry.setdefault('history', []).append(registry['latest'])
                record = dict(plan)
                for key in ('base_model', 'dataset', 'adapter', 'fused_model', 'gguf', 'modelfile', 'template_source'):
                    try:
                        record[key] = str(Path(record[key]).relative_to(ROOT))
                    except ValueError:
                        pass
                registry['latest'] = {**record, 'updated_at': datetime.now(timezone.utc).isoformat(),
                                      'verification': '학습 후 평가·파일 검사·GGUF 검사·Ollama 등록 완료; 답변 품질 비교는 별도'}
                save(registry_path, registry)
                plan['stage'] = 'promote'
                save(state, plan)
            return 0
        if args.stage == 'deploy':
            verify_model(plan['fused_model'])
            verify_gguf(plan['gguf'], Path(args.llama_cpp).expanduser())
            text = modelfile(plan)
            if Path(plan['modelfile']).exists() and Path(plan['modelfile']).read_text() != text:
                raise ValueError('기존 Modelfile 내용이 다릅니다. 덮어쓰지 않습니다.')
            if not args.dry_run:
                Path(plan['modelfile']).write_text(text, encoding='utf-8')
        command = command_for(args.stage, plan, args.iters, args.llama_cpp)
        if args.dry_run and args.stage in ('post', 'gguf'):
            command.append('--dry-run')
        execute(command, args.dry_run)
        if not args.dry_run:
            if args.stage == 'train':
                weights = Path(plan['adapter']) / 'adapters.safetensors'
                config = read(Path(plan['adapter']) / 'adapter_config.json')
                if not weights.is_file() or weights.stat().st_size == 0 or config.get('model') != plan['base_model']:
                    raise ValueError('학습 어댑터가 없거나 시작 모델이 실행 기록과 다릅니다.')
            elif args.stage == 'post':
                verify_model(plan['fused_model'])
            elif args.stage == 'gguf':
                verify_gguf(plan['gguf'], Path(args.llama_cpp).expanduser())
            if args.stage == 'deploy':
                execute(['ollama', 'show', plan['name']], False)
            plan['stage'] = args.stage
            save(state, plan)
        return 0
    except (OSError, ValueError, KeyError, subprocess.CalledProcessError) as error:
        print('중단: ' + str(error), file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
