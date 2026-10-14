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
case "${1:---knowledge}" in
  --knowledge)
    if [ "$#" -gt 1 ]; then echo "인자가 너무 많습니다." >&2; exit 1; fi
    exec "$python_path" distribution_package.py --commit "${BITBUCKET_COMMIT:-HEAD}" --upload
    ;;
  --model)
    if [ "$#" -gt 1 ]; then echo "인자가 너무 많습니다." >&2; exit 1; fi
    case "${BITBUCKET_TAG:-}" in
      model-v*) ;;
      *) echo "모델 학습 중단: model-v* 태그 파이프라인에서만 실행합니다." >&2; exit 1 ;;
    esac
    exec "$python_path" runner_model_pipeline.py --commit "${BITBUCKET_COMMIT:-HEAD}"
    ;;
  *) echo "사용법: publish_distribution.sh [--knowledge|--model]" >&2; exit 1 ;;
esac
