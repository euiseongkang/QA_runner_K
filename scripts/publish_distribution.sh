#!/bin/bash
set -euo pipefail
script_dir="$(cd "$(dirname "$0")" && pwd)"
repo_dir="$(cd "$script_dir/.." && pwd)"
python_path="${QA_DISTRIBUTION_PYTHON:-python3}"
if [ "${QA_DRIVE_PUBLISH_ENABLED:-1}" != "1" ]; then
  echo "Drive 게시 비활성: QA_DRIVE_PUBLISH_ENABLED=1과 인증·모델 경로를 설정하세요."
  if [ "${1:-}" = "--model" ]; then exit 1; fi
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
    # 실행 태그 검증은 Runner에서 한 번 수행한다. 수동 재실행에서 태그
    # 환경변수가 없으면 현재 커밋의 실제 모델 태그를 확인해 복원한다.
    exec "$python_path" runner_model_pipeline.py --commit "${BITBUCKET_COMMIT:-HEAD}"
    ;;
  *) echo "사용법: publish_distribution.sh [--knowledge|--model]" >&2; exit 1 ;;
esac
