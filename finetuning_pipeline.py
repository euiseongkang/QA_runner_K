"""학습 후 평가·병합·파일 검증. 학습이나 Ollama 모델 교체는 실행하지 않는다."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import sys
import uuid


def read_json(path):
    return json.loads(path.read_text(encoding='utf-8'))


def test_count(path):
    count = 0
    for number, line in enumerate(path.read_text(encoding='utf-8').splitlines(), 1):
        if not line.strip():
            continue
        try:
            value = json.loads(line)
            if not isinstance(value, dict) or not isinstance(value.get('messages'), list) or not value['messages']:
                raise ValueError('messages 예제가 아님')
        except (ValueError, TypeError) as error:
            raise ValueError(f'{path.name} {number}행의 JSONL 형식이 잘못되었습니다.') from error
        count += 1
    if not count:
        raise ValueError('test.jsonl에 평가 자료가 없습니다. 별도 시험 자료를 준비하세요.')
    return count


def verify_model(folder):
    """가중치·설정·토크나이저 파일의 완전성을 검사한다. 답변 품질 검증은 별도다."""
    folder = Path(folder).resolve()
    config = read_json(folder / 'config.json')
    tokenizer_config = read_json(folder / 'tokenizer_config.json')
    if not isinstance(config, dict) or not config.get('model_type'):
        raise ValueError('config.json에 model_type이 없습니다.')
    if not isinstance(tokenizer_config, dict):
        raise ValueError('tokenizer_config.json 형식이 잘못되었습니다.')
    if (folder / 'tokenizer.json').exists():
        if not isinstance(read_json(folder / 'tokenizer.json'), dict):
            raise ValueError('tokenizer.json 형식이 잘못되었습니다.')
    elif not ((folder / 'vocab.json').is_file() and (folder / 'merges.txt').is_file()):
        raise ValueError('tokenizer.json 또는 vocab.json·merges.txt가 필요합니다.')
    index = folder / 'model.safetensors.index.json'
    if index.exists():
        mapping = read_json(index).get('weight_map')
        if not isinstance(mapping, dict) or not mapping:
            raise ValueError('가중치 인덱스가 비어 있습니다.')
        names = sorted(set(mapping.values()))
    else:
        names = ['model.safetensors']
    files = []
    for name in names:
        if not isinstance(name, str):
            raise ValueError('가중치 파일명이 잘못되었습니다.')
        path = (folder / name).resolve()
        if not path.is_relative_to(folder) or not path.is_file() or path.stat().st_size == 0:
            raise ValueError(f'가중치 파일이 없거나 잘못되었습니다: {name}')
        files.append({'name': name, 'bytes': path.stat().st_size})
    warnings = []
    if not (folder / 'chat_template.jinja').is_file() and not tokenizer_config.get('chat_template'):
        warnings.append('대화 템플릿이 없습니다. Ollama 등록 전에 원본 모델의 템플릿을 확인하세요.')
    if isinstance(tokenizer_config.get('extra_special_tokens'), list):
        warnings.append('extra_special_tokens가 리스트입니다. GGUF 변환 시 Transformers 호환성을 확인하세요.')
    return {'folder': str(folder), 'model_type': config['model_type'],
            'weights': files, 'warnings': warnings,
            'note': '파일 완전성 검사이며 추론 성공이나 최적화 품질 향상을 보증하지 않습니다.'}


def commands(args, dataset, adapter, output, count, config):
    model = config.get('model')
    if not isinstance(model, str) or not model.strip():
        raise ValueError('adapter_config.json에 원본 model이 없습니다.')
    length = args.max_seq_length or config.get('max_seq_length', 4096)
    if not isinstance(length, int) or length < 1:
        raise ValueError('학습 입력 길이가 올바르지 않습니다.')
    evaluate = [sys.executable, '-m', 'mlx_lm.lora', '--model', model,
                '--adapter-path', str(adapter), '--data', str(dataset), '--test',
                '--batch-size', '1', '--test-batches', str(count), '--max-seq-length', str(length)]
    if config.get('mask_prompt'):
        evaluate.append('--mask-prompt')
    fuse = [sys.executable, '-m', 'mlx_lm.fuse', '--model', model,
            '--adapter-path', str(adapter), '--save-path', str(output)]
    return evaluate, fuse


def run_command(command, cwd, log):
    print('실행:', subprocess.list2cmdline(command), flush=True)
    with log.open('w', encoding='utf-8') as stream:
        process = subprocess.Popen(command, cwd=cwd, stdout=subprocess.PIPE,
                                   stderr=subprocess.STDOUT, text=True, errors='replace')
        try:
            for line in process.stdout:
                print(line, end='', flush=True)
                stream.write(line)
                stream.flush()
            code = process.wait()
        except BaseException:
            process.terminate()
            process.wait()
            raise
    if code:
        raise ValueError(f'명령이 실패했습니다(종료 코드 {code}). 로그: {log}')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dataset', default='.', help='JSONL 데이터 폴더 (기본: 현재 폴더)')
    parser.add_argument('--adapter', default='adapters_trial_v33', help='데이터 폴더 기준 어댑터 경로')
    parser.add_argument('--output', help='데이터 폴더 기준 병합 모델 경로 (기본: 새 고유 폴더)')
    parser.add_argument('--max-seq-length', type=int, help='평가 입력 길이 (기본: 학습 설정과 동일)')
    parser.add_argument('--dry-run', action='store_true', help='사전 확인·명령 출력만 수행')
    parser.add_argument('--verify-only', metavar='MODEL_FOLDER', help='기존 병합 모델 파일만 검사')
    args = parser.parse_args(argv)
    dataset = Path(args.dataset).expanduser().resolve()
    def relative(value):
        path = Path(value).expanduser()
        return (path if path.is_absolute() else dataset / path).resolve()
    report = None
    try:
        if args.verify_only:
            result = verify_model(relative(args.verify_only))
            print(json.dumps(result, ensure_ascii=False, indent=2))
            print('파일 검사 완료. 재학습·재병합은 실행하지 않았습니다.')
            return 0
        adapter = relative(args.adapter)
        config = read_json(adapter / 'adapter_config.json')
        if not (adapter / 'adapters.safetensors').is_file() or (adapter / 'adapters.safetensors').stat().st_size == 0:
            raise ValueError('학습된 adapters.safetensors가 없습니다.')
        count = test_count(dataset / 'test.jsonl')
        stamp = datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S') + '_' + uuid.uuid4().hex[:8]
        output = relative(args.output or ('fused_model_' + stamp))
        if output.exists():
            raise ValueError('출력 폴더가 이미 있습니다. --output에 새 이름을 지정하거나 --verify-only로 검사하세요.')
        evaluate, fuse = commands(args, dataset, adapter, output, count, config)
        print(f'평가 자료 {count}건 · 배치 1 · 출력 {output}', flush=True)
        if args.dry_run:
            print(subprocess.list2cmdline(evaluate))
            print(subprocess.list2cmdline(fuse))
            return 0
        logs = dataset / 'post_training_runs' / stamp
        logs.mkdir(parents=True)
        report = logs / 'report.json'
        info = {'status': 'running', 'dataset': str(dataset), 'adapter': str(adapter),
                'output': str(output), 'test_examples': count, 'commands': [evaluate, fuse], 'completed': []}
        def save_report():
            report.write_text(json.dumps(info, ensure_ascii=False, indent=2), encoding='utf-8')
        save_report()
        try:
            print('[1/3] 학습 모델 평가', flush=True)
            run_command(evaluate, dataset, logs / 'evaluation.log')
            info['completed'].append('evaluation')
            save_report()
            print('[2/3] 원본 모델과 어댑터 병합', flush=True)
            run_command(fuse, dataset, logs / 'fusion.log')
            info['completed'].append('fusion')
            save_report()
            print('[3/3] 생성 파일 검사', flush=True)
            info['verification'] = verify_model(output)
            info['completed'].append('verification')
            info['status'] = 'complete'
            save_report()
        except (Exception, KeyboardInterrupt) as error:
            info.update(status='failed', error=str(error) or '사용자가 중단했습니다.')
            save_report()
            raise
        print(f'완료 · 모델: {output}\n평가·병합 로그와 결과: {logs}')
        for warning in info['verification']['warnings']:
            print('주의:', warning)
        print('다음 단계는 GGUF 변환 및 후보 모델 비교 평가입니다. Ollama·Open WebUI 모델은 변경하지 않았습니다.')
        return 0
    except (OSError, ValueError, TypeError, KeyboardInterrupt) as error:
        print('중단: ' + (str(error) or '사용자가 중단했습니다.'), file=sys.stderr)
        if report:
            print('실행 기록: ' + str(report), file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
