#!/bin/bash
set -euo pipefail
script_dir="$(cd "$(dirname "$0")" && pwd)"
repo_dir="$(cd "$script_dir/.." && pwd)"
python_path="${QA_DISTRIBUTION_PYTHON:-python3}"
if [ "${QA_DRIVE_PUBLISH_ENABLED:-1}" != "1" ]; then
  echo "Drive 게시 비활성: QA_DRIVE_PUBLISH_ENABLED=1과 인증·모델 경로를 설정하세요."
  exit 0
fi
cd "$repo_dir"
export QA_MODEL_ARTIFACT_ROOT="${QA_MODEL_ARTIFACT_ROOT:-$HOME/Projects/QA_runner_K}"
exec "$python_path" runner_model_pipeline.py --commit "${BITBUCKET_COMMIT:-HEAD}"
