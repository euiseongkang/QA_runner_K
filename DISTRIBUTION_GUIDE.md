# QA_runner_K 커밋별 지식 기반 Drive 배포

목표: QA 프로그램에서 검토·승인 후 내보내기 → main 푸시 → Open WebUI QA 지식 갱신 → 최신 내보내기로 추가 학습·평가·병합·GGUF 변환 → 지식·모델을 Drive에 게시 → Runner Mac Ollama 등록. 지식 ID와 최신 내보내기 폴더는 스크립트가 찾는다. 웹 프로젝트는 처리하지 않는다.

## 게시 폴더

- KNOWLEDGE/QA_runner_K: `1X9vbsAVd14Jr8m1mAOVLQO5KQGcNCTvR`
- MODEL: `11U7VeTxdThwpBTOvfDbAmR9z4O9L92tH`

MODEL 아래 `<레지스트리 모델명>_<커밋12자리>/runtime.zip`과 `training.zip`을 게시한다. training.zip에는 병합 가중치·설정·토크나이저·학습 스크립트·상세 README.md가 포함된다.

사용자가 지정한 공유 드라이브 폴더에서 확인한 ID이다. 기존 공유 설정은 스크립트가 변경하지 않는다. 다운로드 사용자는 뷰어 권한을, 게시 서비스 계정은 업로드 가능한 권한을 별도로 부여한다.

## Runner 최초 준비

1. Google Cloud 프로젝트에서 Google Drive API를 활성화한다.
2. IAM 및 관리자 → 서비스 계정 → 서비스 계정 만들기. 이름 예: `qa-artifact-publisher`. Drive 폴더 접근을 위해 프로젝트 Owner/Editor 역할을 부여할 필요는 없다.
3. 서비스 계정 → 키 → 키 추가 → 새 키 만들기 → JSON. 조직 정책으로 키 생성이 막히면 관리자에게 허용 가능한 인증 방식(예: OAuth 또는 연합 인증)을 확인한다.
4. 서비스 계정 이메일에 지정한 공유 드라이브 배포 폴더의 업로드 가능한 권한을 부여한다. 공유 드라이브 정책이 외부 서비스 계정을 제한하면 관리자 확인이 필요하다.
5. JSON 키는 Git 저장소 밖, Runner Mac의 전용 경로에 보관한다. 예: `~/atlassian-runners/credentials/qa-drive-publisher.json`. 소유자만 읽도록 설정하고 키 내용을 Git·로그·패키지·채팅에 넣지 않는다.
6. Runner에 전용 Python 가상환경을 만들고 `pip install -r distribution_requirements.txt`로 업로드 의존성을 설치한다.

Bitbucket 저장소 변수:

- `GOOGLE_APPLICATION_CREDENTIALS`: Runner Mac의 JSON 키 **절대 경로**. 파일 내용이 아니다.
- `QA_DISTRIBUTION_PYTHON`: 의존성이 설치된 전용 Python 실행 파일의 절대 경로.
- `OPENWEBUI_URL`: Runner에서 접근할 Open WebUI 주소.
- `OPENWEBUI_API_KEY`: Open WebUI 보안 변수. 지식·파일 조회/생성 및 추출 원문 API 접근이 필요하다.
- `QA_DRIVE_PUBLISH_ENABLED`: 기본값 `1`로 전체 자동화를 실행한다. 일시 중단하려면 `0`으로 설정한다. 기존 저장소 변수에 `0`이 남아 있으면 `1`로 변경한다.
- `QA_MODEL_ARTIFACT_ROOT`: 모델 레지스트리의 상대 경로를 찾을 Runner Mac의 프로젝트 절대 경로. 게시 스크립트 기본값은 `$HOME/Projects/QA_runner_K`이다. Pipeline의 임시 체크아웃 경로와 구분한다.
- `QA_TRAINING_PYTHON`: MLX-LM과 llama.cpp 변환 의존성이 설치된 Python 경로. 기본값은 `<QA_MODEL_ARTIFACT_ROOT>/finetuning/.venv/bin/python`이다.
- `QA_LLAMA_CPP`: llama.cpp 경로. 기본값은 `$HOME/Projects/llama.cpp`이다.
- `QA_TRAIN_ITERS`: 추가 학습 반복 횟수. 기본값은 시험 학습용 `20`이다. 학습 효과는 독립 TC로 비교하고 필요하면 조정한다.

해당 경로에 레지스트리가 지정한 병합 모델·GGUF·Modelfile이 있어야 한다. Runner 사용자의 PATH에 Ollama가 있고 서버가 실행 중이어야 한다. Drive 권한은 KNOWLEDGE와 MODEL 모두에 필요하다.

Cloud IAM 역할과 Drive 폴더 권한은 별개다. 키를 만든 것만으로 Drive 업로드 권한이 생기지 않는다.

## Pipeline 순서

main 푸시 시 GitHub 미러 → QA 지식 기반 동기화·색인 확인 → 추가 학습·평가·병합·GGUF 생성 → 지식·runtime.zip·training.zip Drive 게시 → Runner Mac Ollama 등록 순으로 진행한다. 첫 실전 검증은 Bitbucket의 custom `publish-distribution` 파이프라인으로 수행한다. Drive 단계 활성화 전에는 기존 미러·RAG 동기화가 유지된다.

게시 스크립트는 동일 커밋의 QA 동기화 완료 기록에서 지식 ID를 읽고 Open WebUI의 색인 완료 상태·원문을 확인한다. 다른 커밋의 기록이거나 원문 해시가 다르면 게시를 중단한다.

파일명은 `QA_runner_K_<커밋12자리>_v<앱버전>_KNOWLEDGE_QA_runner_K.zip`이다. ZIP에 추출 원문, manifest, 파일별 SHA-256, 설치 스크립트를 넣는다. API Key와 서비스 계정 JSON은 포함하지 않는다.

main/custom 게시 스크립트는 `runner_model_pipeline.py`를 실행한다. 이 스크립트가 생성한 후보 레지스트리를 배포 스크립트에 전달하고 `--include-model --upload --register-local-model`을 지정한다. 모든 업로드의 크기·체크섬 검사가 성공한 뒤 후보 이름으로 `ollama create`와 `ollama show`를 실행한다. 동일 이름이 이미 있으면 해당 모델을 갱신한다. Open WebUI가 이 Mac의 Ollama에 연결되어 있어야 모델을 사용할 수 있다.

Runner는 `<QA_MODEL_ARTIFACT_ROOT>/finetuning/qa_tc_dataset_*` 중 가장 최근 완료된 내보내기를 읽는다. JSONL은 Git에서 제외되어 있으므로 **내보내기와 Runner가 같은 Mac의 같은 프로젝트 경로를 사용해야 한다**. 다른 Mac에서 내보낸 데이터는 이 경로로 전달해야 한다. 새 내보내기만 만들고 푸시하지 않으면 자동 실행되지 않는다.

초기 시작 모델은 해당 커밋의 `finetuning/model_registry.json`을 사용한다. 이후에는 지속 저장되는 `finetuning/.runner/model_registry.json`의 직전 성공한 병합 모델을 사용한다. v0.35.0 커밋의 새 후보 이름은 `qa-tc-optimizer-v35`이다. 같은 JSONL 내용은 다시 학습하지 않고 기존 성공 모델을 배포한다.

실행별 데이터 사본·어댑터·병합 모델·GGUF·상태는 `finetuning/.runner/runs/<전체커밋>/`에 보존한다. 학습 실패 시 후속 단계는 중단된다. 평가·변환이 완료된 뒤 게시 실패 시 같은 커밋으로 재실행하면 생성된 후보를 재사용한다. Drive 업로드 및 Ollama 등록이 모두 성공해야 지속 레지스트리를 갱신한다. 중단된 학습 자체는 로그와 어댑터를 확인해야 하며 자동 재학습으로 덮어쓰지 않는다. 동시 실행은 잠금으로 차단한다.

Drive 게시에는 resumable upload를 사용한다. 선택 기능인 모델 패키지도 스트리밍 처리한다. 같은 이름의 같은 파일은 재사용하고 다른 파일은 덮어쓰지 않는다. 완료 후 Drive 크기·MD5를 다시 조회한다. 프로세스 재시작 시 중단된 업로드 세션 자체는 복원하지 않지만 완료된 동일 파일은 재사용한다. 보고서만 Bitbucket artifact로 보관하며 큰 ZIP은 Drive에 저장한다.

로컬 계획 확인:

```bash
python3 runner_model_pipeline.py --commit HEAD --dry-run
```

스크립트와 소스가 커밋된 뒤 해당 커밋으로 실행한다. 실제 패키징은 동일 커밋의 RAG 동기화 완료 기록과 Open WebUI 인증이 필요하다.

## 다운로드 사용자

Ollama와 Open WebUI는 먼저 설치되어 있어야 한다. 플랫폼별 Ollama 설치와 서버 실행은 이 패키지가 대신하지 않는다.

MODEL ZIP을 풀고:

```bash
python3 install_package.py --model
```

지식 ZIP을 풀고 수신 Open WebUI의 임베딩 엔진·모델을 설정한 뒤, 자신의 `OPENWEBUI_URL`과 `OPENWEBUI_API_KEY`를 환경변수로 지정하고:

```bash
python3 install_package.py --knowledge
```

원문을 수신 서버에서 재색인하고 새 지식 기반 ID를 출력한다. QA 프로그램에서 해당 모델과 QA/웹 지식 기반 ID를 선택한다. 다른 PC의 서버 UUID나 벡터 DB를 그대로 가져오지 않는다. API Key는 패키지에 들어 있지 않으며 자신의 서버용 키를 사용한다.
