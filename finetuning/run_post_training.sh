#!/bin/bash
# 현재 위치 또는 --dataset으로 지정한 데이터 폴더에서 학습 후 단계를 진행한다.
set -euo pipefail
script_dir="$(cd "$(dirname "$0")" && pwd)"
python_path="$script_dir/.venv/bin/python"
if [ ! -x "$python_path" ]; then
  echo "학습 환경이 없습니다: $python_path (finetuning/.venv에 MLX-LM을 설치하세요.)" >&2
  exit 1
fi
exec "$python_path" "$script_dir/../finetuning_pipeline.py" "$@"
