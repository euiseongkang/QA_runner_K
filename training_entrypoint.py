"""검토·분할 검사를 통과한 자료만 MLX-LM 추가 학습으로 전달한다."""
import argparse
from pathlib import Path
import subprocess
import sys

from finetuning_export import validate_training_export


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument('--model', required=True, help='추가 학습을 시작할 병합 모델')
    parser.add_argument('--data', required=True, help='검토·승인 후 내보낸 JSONL 폴더')
    args, training_args = parser.parse_known_args(argv)
    try:
        dataset = Path(args.data).expanduser().resolve()
        validate_training_export(dataset)
        subprocess.run([sys.executable, '-m', 'mlx_lm.lora', '--model', args.model,
                        '--data', str(dataset), *training_args], check=True)
        return 0
    except (OSError, ValueError, subprocess.CalledProcessError) as error:
        print('학습 중단: ' + str(error), file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
