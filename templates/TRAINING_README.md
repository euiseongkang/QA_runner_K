# {{MODEL_NAME}} 추가 학습 가이드

이 패키지는 기존 QA 모델에서 새로운 학습을 이어가기 위한 자료입니다.

- 배포 모델: `{{MODEL_NAME}}`
- QA 프로그램 버전: `{{APP_VERSION}}`
- 배포 기준 QA 커밋: `{{COMMIT}}`
- 시작 모델: 이 패키지의 `fused_model/`
- 환경: `environment.json` 참고

배포 커밋은 패키지를 만든 QA 소스 커밋입니다. 모델의 학습 원문이나 학습 시점이 이 커밋과 동일하다는 뜻은 아닙니다. 모델에 기존 학습이 반영되어 있지만 기존 JSONL은 포함되지 않습니다.

## 1. 압축 해제와 파일 확인

`training.zip`을 내려받아 원하는 작업 폴더에 압축을 풉니다. 파일은 다음과 같습니다.

```text
training/
├── README.md
├── manifest.json
├── environment.json
├── requirements-training.txt
├── fused_model/                 # 기존 학습이 병합된 모델 전체
├── Modelfile.template           # 응답 설정·대화 템플릿, 새 GGUF로 갱신하여 사용
├── finetuning_pipeline.py
├── gguf_pipeline.py
├── verify_package.py
└── scripts/
    ├── run_train.sh
    ├── run_post_training.sh
    └── run_gguf_conversion.sh
```

터미널에서 README.md가 있는 폴더로 이동합니다. 아래 모든 명령은 **이 폴더에서 실행**합니다.

```bash
cd "/압축을_푼_폴더/training"
python3 verify_package.py --verify-only
```

`배포 파일 체크섬 확인 완료`가 표시되어야 합니다. 실패하면 다시 다운로드하세요. 가중치가 여러 파일로 나뉜 경우 인덱스에 지정된 모든 파일이 있어야 합니다.

## 2. MLX-LM 환경 설치

이 안내는 **Apple Silicon Mac(M 계열)과 MLX-LM** 기준입니다. Intel Mac이나 Windows에서 같은 명령을 그대로 실행할 수 없습니다. 그 환경은 별도의 학습 프레임워크와 GPU 설정이 필요합니다. Ollama·Open WebUI는 모델 사용용이고 학습은 MLX-LM으로 진행합니다.

먼저 환경을 확인합니다.

```bash
uname -m
python3 --version
```

Apple Silicon은 `arm64`입니다. Python은 배포 패키지의 environment.json에 기록된 버전을 우선 참고하세요. 해당 버전의 Python이 설치되어 있다면 `python3` 대신 그 실행 파일을 사용합니다.

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements-training.txt
python -m mlx_lm.lora --help
```

requirements-training.txt는 확인 가능한 학습 환경의 주요 패키지 버전을 기록합니다. 전체 운영체제·의존성 잠금 파일은 아닙니다. 환경 버전 확인이 불가능했던 배포는 environment.json에 표시됩니다.

수 GB 모델을 불러오므로 여유 메모리와 디스크가 필요합니다. 원본 모델, 새 어댑터, 새 병합 모델, GGUF, 로그가 함께 저장됩니다. 메모리 부족 시 batch-size 1을 유지하고 학습 길이·레이어 수를 낮춰 시험합니다.

## 3. 자신의 QA 자료를 준비하고 내보내기

1. runtime.zip의 모델을 Ollama에 등록하고 Open WebUI/QA 프로그램에서 선택합니다.
2. 자신의 환경에서 TC를 실행합니다. 실행 기록과 스크린샷은 자신의 PC에 적재됩니다.
3. QA 프로그램 → 실행 패키지·학습 승인 관리에서 기록을 확인합니다.
4. **학습 정답 편집**에서 사전조건·절차·예상 결과를 검토합니다. 예상 결과에 입력·Enter 절차가 복사됐거나 검증 기준이 빠진 사례는 교정하거나 미승인합니다.
5. 정답 및 사유를 저장한 뒤 승인하고 학습 데이터를 내보냅니다.
6. QA 프로젝트 또는 배포 실행 파일 옆 finetuning/qa_tc_dataset_... 폴더의 JSONL을 사용합니다.

```bash
# 반드시 자신의 실제 내보내기 폴더로 변경하세요.
QA_TRAIN_DATASET="/Users/사용자/QA_runner_K/finetuning/qa_tc_dataset_실제폴더명"
wc -l "$QA_TRAIN_DATASET/train.jsonl" "$QA_TRAIN_DATASET/valid.jsonl" "$QA_TRAIN_DATASET/test.jsonl"
```

파일 이름은 train.jsonl·valid.jsonl·test.jsonl입니다. 학습·검증·시험 자료를 그대로 복제하여 세 파일을 만들지 마세요. 별도 TC 그룹의 평가 자료가 필요합니다. 3개 미만의 TC 그룹만 내보내면 valid/test가 비어 있을 수 있으며 학습 후 평가 스크립트는 시험 자료가 없으면 중단합니다.

이 JSONL은 **TC 문구 편집 모델**의 학습 자료입니다. 스크린샷 이미지 학습 자료가 아니며 실행 PASS만으로 정답 정확성이 보장되지 않습니다. 정답을 편집하지 않은 기본 승인 기록은 원문 유지 사례입니다. 실제 개인정보·인증 정보가 입력이나 원문에 포함됐다면 학습 전에 테스트 값으로 일관되게 치환하세요.

## 4. 기존 병합 모델에서 추가 학습

시작 모델은 반드시 이 패키지의 fused_model/입니다. 원본 Qwen 모델을 지정하면 이번 배포 모델에서 이어가는 학습이 아닙니다. **이미 병합된 기존 어댑터를 다시 적용하지 마세요.**

아래는 20회 시험 학습 예시입니다. 품질 개선을 보장하는 학습 횟수가 아닙니다. 평가 결과를 보며 횟수와 학습률을 조정하세요.

```bash
bash scripts/run_train.sh \
  --train \
  --data "$QA_TRAIN_DATASET" \
  --adapter-path "$PWD/adapters_next" \
  --iters 20 \
  --batch-size 1 \
  --num-layers 4 \
  --learning-rate 1e-5 \
  --max-seq-length 4096 \
  --mask-prompt \
  --grad-checkpoint \
  --steps-per-report 10 \
  --steps-per-eval 10 \
  --save-every 10
```

학습 종료 후 다음 파일을 확인하세요.

```bash
ls -lh adapters_next/adapter_config.json adapters_next/adapters.safetensors
```

adapter_config.json의 model은 이 패키지의 fused_model을 가리켜야 합니다.

학습 중단 후 재개하려면 같은 시작 모델과 기존 어댑터 설정을 사용하고 `--resume-adapter-file "$PWD/adapters_next/adapters.safetensors"`를 학습 명령에 추가합니다. 다른 시작 모델의 어댑터를 섞지 마세요.

## 5. 평가 → 병합 → 생성 파일 검사

다음 스크립트는 학습 어댑터의 설정에 기록된 시작 모델을 기준으로 평가·병합합니다. 시험 배치는 1로 설정하여 시험 자료가 적을 때 기본 배치 크기 문제를 피합니다.

```bash
bash scripts/run_post_training.sh \
  --dataset "$QA_TRAIN_DATASET" \
  --adapter "$PWD/adapters_next" \
  --output "$PWD/fused_model_next"
```

출력 폴더는 기존 폴더와 다른 새 이름이어야 합니다. 기존 산출물은 덮어쓰지 않습니다. 평가 로그와 report.json은 JSONL 폴더의 post_training_runs/ 아래에 저장됩니다. 결과 파일에는 모델 설정·가중치·토크나이저가 있어야 합니다.

```bash
bash scripts/run_post_training.sh \
  --dataset "$QA_TRAIN_DATASET" \
  --verify-only "$PWD/fused_model_next"
```

loss나 파일 검사만으로 QA 응답이 개선됐다고 판단하지 마세요. 예전 모델과 새 모델에 같은 독립 TC를 입력해 다음을 비교합니다.

- 원문의 입력값·대상 화면·검증 기준 보존
- 절차와 예상 결과 구분
- 시트명·비고 맥락 반영
- 불필요한 동작·기능을 추가하지 않음
- JSON 형식과 변경 판단·사유의 적절성

## 6. GGUF 변환

Qwen 계열은 포함된 스크립트가 외부 llama.cpp의 변환기를 사용합니다. 학습 작업 폴더와 별도로 설치합니다. 이미 설치했다면 기존 경로를 사용하세요.

```bash
mkdir -p "$HOME/Projects"
git clone https://github.com/ggml-org/llama.cpp.git "$HOME/Projects/llama.cpp"
python -m pip install -r "$HOME/Projects/llama.cpp/requirements.txt"

bash scripts/run_gguf_conversion.sh \
  --model "$PWD/fused_model_next" \
  --outfile "$PWD/model-next-f16.gguf" \
  --llama-cpp "$HOME/Projects/llama.cpp"
```

같은 이름의 GGUF가 이미 있으면 새 이름을 사용합니다. 형식·가중치 범위·대화 템플릿 검사에 성공해야 배포할 수 있습니다. 로그는 병합 모델 폴더 옆 gguf_runs/에 저장됩니다. llama.cpp는 외부 도구이므로 사용한 커밋도 기록하세요.

```bash
git -C "$HOME/Projects/llama.cpp" rev-parse HEAD
```

## 7. 새 모델을 Ollama에 등록

Ollama 설치와 서버 실행이 먼저 되어 있어야 합니다. 기존 모델을 유지하고 자신의 새 모델 이름으로 등록하세요.

아래 명령은 배포 템플릿을 복사하면서 FROM만 새 GGUF로 바꿉니다. **템플릿·응답 설정은 유지합니다.**

```bash
python - <<'PYCODE'
from pathlib import Path
import re
text = Path('Modelfile.template').read_text()
if len(re.findall(r'^FROM\s+.*$', text, re.M)) != 1:
    raise SystemExit('FROM을 하나로 식별하지 못했습니다.')
text = re.sub(r'^FROM\s+.*$', 'FROM ./model-next-f16.gguf', text, flags=re.M)
Path('Modelfile.next').write_text(text)
PYCODE

ollama create qa-tc-optimizer-my-next -f ./Modelfile.next
ollama show qa-tc-optimizer-my-next
```

Open WebUI → Ollama 연결의 모델 목록을 갱신하고 새 모델을 선택합니다. QA 프로그램의 대화 모델도 새 이름으로 변경합니다. 지식 기반은 모델과 별개이므로 자신의 Open WebUI에 QA 지식 패키지를 가져와 재색인하고 새 ID를 선택하세요.

## 8. 이후에도 학습을 이어가는 방법

다음 회차에는 이번에 생성한 fused_model_next를 시작 모델로 사용합니다. 본 패키지의 원래 fused_model로 매번 돌아가면 개인의 직전 추가 학습이 누적되지 않습니다. 시작 모델·어댑터·데이터·평가 결과를 회차별로 기록하세요. 새 데이터만으로 반복 학습하면 기존 능력이 약해질 수 있으므로 기존 TC에 대한 평가도 유지합니다.

기존 모델은 기존 학습 원문을 보관하는 데이터베이스가 아닙니다. 기존 JSONL이 필요하면 별도 제공을 받아야 합니다. 상대방의 새 데이터나 모델은 원 배포자의 PC/Drive에 자동 합쳐지지 않습니다.

## 문제 해결

- Dataset must have at least batch_size: 평가 명령의 batch-size를 1로 지정하고 test.jsonl의 유효 자료 수를 확인합니다.
- 최초 학습 모델과 어댑터의 시작 모델이 다름: adapter_config.json의 model과 병합 명령의 모델을 일치시킵니다.
- 토크나이저 변환 오류: fused_model의 토크나이저 파일 전체와 배포 환경 버전을 확인합니다. tokenizer.model을 임의로 만들어 해결하지 않습니다.
- supplied file was not in GGUF format: Modelfile의 FROM이 폴더나 safetensors가 아닌 실제 .gguf 파일인지 확인합니다.
- 실행 패키지에 PASS가 있음: 실행 판정과 TC 편집 정답의 정확성은 별개입니다. 학습 정답을 검토합니다.
- 메모리 부족: batch-size 1, 낮은 num-layers와 max-seq-length로 시험합니다. 값 변경 시 새로운 설정·어댑터 경로를 기록합니다.
