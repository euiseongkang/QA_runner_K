"""QA 실행용 모델과 MLX 학습용 원본 모델의 설치 안내."""
TRAINING_MODEL = 'Qwen/Qwen2.5-1.5B-Instruct'
RUNTIME_MODEL = 'qwen2.5:1.5b'
MODEL_GUIDANCE = f'''이 프로젝트의 첫 시험 학습 권장 모델: {TRAINING_MODEL}

QA 실행·최적화용 Ollama 모델: {RUNTIME_MODEL}
Ollama 설정의 [설치] 버튼으로 설치합니다.

MLX 학습용 원본 모델: {TRAINING_MODEL}
Ollama에 설치한 모델과 파일 형식·저장 위치가 다릅니다.
MLX-LM 설치 후 첫 학습 시 원본 모델이 자동 다운로드됩니다.
원본 모델을 먼저 다운로드하려면 아래 순서로 터미널에서 실행하세요.

cd /Users/ik-lpc-084/Projects/QA_runner_K/finetuning
python3 -m venv .venv
source .venv/bin/activate
python -m pip install 'mlx-lm[train]'
python -c "from huggingface_hub import snapshot_download; print(snapshot_download('{TRAINING_MODEL}'))"

마지막 명령이 캐시 경로를 출력하면 다운로드가 완료된 것입니다.
학습 명령에는 --model {TRAINING_MODEL}을 지정합니다.
이 안내 버튼은 설치·다운로드·학습을 실행하지 않습니다.
1.5B는 경량 시험 학습 출발점이며, 품질은 학습 후 비교 평가합니다.'''


def show_model_guidance(parent):
    from tkinter import messagebox
    messagebox.showinfo('권장 학습 모델 · 설치 안내', MODEL_GUIDANCE, parent=parent)
