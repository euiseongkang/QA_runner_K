"""병합 모델을 F16 GGUF로 변환하고 검증한다. Ollama 등록은 별도다."""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shlex
import sys
import uuid

from finetuning_pipeline import read_json, run_command, verify_model


def reader_type(repo):
    library = repo / 'gguf-py'
    if not (library / 'gguf' / 'gguf_reader.py').is_file():
        raise ValueError('llama.cpp의 gguf-py를 찾지 못했습니다. --llama-cpp 경로를 확인하세요.')
    sys.path.insert(0, str(library))
    try:
        from gguf import GGUFReader
        return GGUFReader
    except ImportError:
        raise ValueError('GGUF 검증 의존성이 없습니다. 학습 가상환경에 llama.cpp/requirements.txt를 설치하세요.') from None
    finally:
        sys.path.pop(0)


def verify_gguf(path, repo, architecture=None):
    path = Path(path).resolve()
    reader = reader_type(repo)(str(path))
    def value(key):
        return reader.fields[key].contents() if key in reader.fields else None
    actual = value('general.architecture')
    if not actual or (architecture and actual != architecture):
        raise ValueError('GGUF 모델 구조가 원본과 일치하지 않습니다.')
    if value('general.file_type') != 1:
        raise ValueError('F16 GGUF 파일이 아닙니다.')
    if not reader.tensors:
        raise ValueError('GGUF에 모델 텐서가 없습니다.')
    size = path.stat().st_size
    if any(t.data_offset + t.n_bytes > size for t in reader.tensors):
        raise ValueError('GGUF 가중치 데이터가 잘렸습니다.')
    if not value('tokenizer.chat_template'):
        raise ValueError('GGUF에 대화 템플릿이 없습니다. 원본 토크나이저의 대화 템플릿을 확인하세요.')
    return {'file': str(path), 'bytes': size, 'architecture': actual,
            'file_type': 'F16', 'tensors': len(reader.tensors),
            'context_length': value(actual + '.context_length'),
            'chat_template_present': True,
            'note': 'GGUF 구조 검사이며 실제 추론·TC 개선 품질은 별도로 평가해야 합니다.'}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--model', help='병합 모델 폴더')
    group.add_argument('--verify-only', metavar='GGUF_FILE', help='기존 GGUF 검사만 수행')
    parser.add_argument('--outfile', help='출력 GGUF 파일 (기본: 모델 폴더 옆의 <폴더명>-f16.gguf)')
    parser.add_argument('--llama-cpp', default='~/Projects/llama.cpp', help='llama.cpp 소스 경로')
    parser.add_argument('--dry-run', action='store_true', help='사전 확인과 명령 출력만 수행')
    args = parser.parse_args(argv)
    repo = Path(args.llama_cpp).expanduser().resolve()
    report, temporary = None, None
    try:
        if args.verify_only:
            result = verify_gguf(Path(args.verify_only).expanduser(), repo)
            print(json.dumps(result, ensure_ascii=False, indent=2))
            print('기존 GGUF 검사 완료. 변환은 실행하지 않았습니다.')
            return 0
        model = Path(args.model).expanduser().resolve()
        original = verify_model(model)
        if original['warnings']:
            raise ValueError('변환 전 확인이 필요합니다: ' + ' / '.join(original['warnings']))
        output = Path(args.outfile).expanduser().resolve() if args.outfile else model.parent / (model.name + '-f16.gguf')
        if output.exists():
            raise ValueError('출력 파일이 이미 있습니다. 새 --outfile을 지정하거나 --verify-only를 사용하세요.')
        if not output.parent.is_dir():
            raise ValueError('출력 파일의 상위 폴더가 없습니다.')
        converter = repo / 'convert_hf_to_gguf.py'
        if not converter.is_file():
            raise ValueError('GGUF 변환 도구를 찾지 못했습니다. --llama-cpp 경로를 확인하세요.')
        reader_type(repo)  # 긴 변환 전에 검증 의존성부터 확인한다.
        stamp = datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S') + '_' + uuid.uuid4().hex[:8]
        temporary = output.parent / ('.' + output.stem + '-' + stamp + '.partial.gguf')
        command = [sys.executable, str(converter), str(model), '--outfile', str(temporary), '--outtype', 'f16']
        if args.dry_run:
            print('변환 명령:', shlex.join(command))
            print('검증 통과 후 저장:', output)
            return 0
        logs = model.parent / 'gguf_runs' / stamp
        logs.mkdir(parents=True)
        report = logs / 'report.json'
        info = {'status': 'running', 'source': str(model), 'output': str(output),
                'command': command, 'completed': []}
        def save():
            report.write_text(json.dumps(info, ensure_ascii=False, indent=2), encoding='utf-8')
        save()
        try:
            print('[1/2] F16 GGUF 변환', flush=True)
            run_command(command, model.parent, logs / 'conversion.log')
            info['completed'].append('conversion')
            save()
            print('[2/2] GGUF 구조·텐서·대화 템플릿 확인', flush=True)
            expected = 'qwen2' if original['model_type'] == 'qwen2' else None
            result = verify_gguf(temporary, repo, expected)
            # 다른 실행이 같은 파일을 만든 경우에도 덮어쓰지 않는다.
            os.link(temporary, output)
            result['file'] = str(output)
            info.update(status='complete', verification=result)
            info['completed'].append('verification')
            save()
        except (Exception, KeyboardInterrupt) as error:
            info.update(status='failed', error=str(error) or '사용자가 중단했습니다.')
            save()
            raise
        print(f'완료 · GGUF: {output}\n로그와 검사 결과: {logs}')
        print('다음은 Ollama 후보 모델 등록입니다. 사용 중인 모델은 변경하지 않았습니다.')
        return 0
    except (OSError, ValueError, TypeError, ImportError, KeyboardInterrupt) as error:
        print('중단: ' + (str(error) or '사용자가 중단했습니다.'), file=sys.stderr)
        if report:
            print('실행 기록: ' + str(report), file=sys.stderr)
        return 1
    finally:
        if temporary and temporary.exists():
            temporary.unlink()


if __name__ == '__main__':
    raise SystemExit(main())
