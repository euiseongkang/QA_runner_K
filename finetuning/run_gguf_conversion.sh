#!/bin/bash
set -euo pipefail
script_dir="$(cd "$(dirname "$0")" && pwd)"
python_path="$script_dir/.venv/bin/python"
if [ ! -x "$python_path" ]; then
  echo "학습 환경이 없습니다: $python_path" >&2
  exit 1
fi
exec "$python_path" "$script_dir/../gguf_pipeline.py" "$@"
