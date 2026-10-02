# QA_runner_K 실행 가이드

테스트케이스(TC)를 읽고 Chromium 브라우저에서 테스트를 실행하는 Python GUI 프로그램입니다. 실행 결과(PASS / FAIL / 확인 필요)와 스크린샷은 로컬 웹 대시보드에서 확인할 수 있습니다.

- **Windows**: 배포된 EXE를 실행하거나 아래 소스 실행 절차를 사용합니다.
- **macOS(맥북)**: 아래 Python 소스 실행 절차를 사용합니다. 저장소의 배포 워크플로는 Windows EXE만 빌드합니다.

## 1. 실행 전 준비

소스로 실행하려면 다음을 준비하세요.

- **Python 3.11**: 저장소의 Windows 빌드와 Docker가 사용하는 버전입니다.
- **Tkinter**: 프로그램 창을 띄우는 데 필요합니다. `pip install tkinter`로 설치하는 패키지가 아닙니다.
- 프로젝트 소스: 저장소를 다운로드해 압축을 풀거나 Git으로 복제합니다.
- 인터넷 연결: 최초 패키지·Chromium 설치 및 테스트 대상 사이트 접속에 필요합니다.

Python은 [공식 다운로드 페이지](https://www.python.org/downloads/)에서 설치할 수 있습니다. Windows 설치 시 **Add python.exe to PATH**를 선택하고 Tcl/Tk 구성 요소를 포함하세요. macOS에서는 Tkinter를 포함한 python.org 설치본을 사용하면 아래 절차를 따라가기 편합니다.

이 문서의 명령어는 `requirements.txt`와 `qa_runner_k_gui.py`가 있는 **프로젝트 폴더**에서 실행합니다. 예시 경로는 실제 다운로드한 경로로 바꾸세요. 가상환경 Python을 직접 호출하므로 별도의 가상환경 활성화가 필요 없습니다.

## 2. Windows 실행

### 방법 A: 배포 EXE 사용

배포 파일을 받은 경우 Python을 따로 설치할 필요가 없습니다. 저장소의 빌드 설정은 Chromium을 EXE에 포함합니다.

1. `QA_Runner_K_v<버전>.exe`를 쓰기 가능한 폴더에 둡니다.
2. EXE를 더블클릭합니다.
3. 대시보드만 사용하려면 같은 폴더에 배포된 `QA_Runner_K_Dashboard.bat`를 두고 더블클릭합니다.

EXE는 macOS에서 실행할 수 없습니다. EXE와 소스 실행 방식은 각각 해당 파일이 있는 폴더에 데이터를 저장합니다.

### 방법 B: Python 소스로 실행

**PowerShell**을 열고 아래 명령어를 순서대로 실행하세요.

```powershell
cd "C:\Users\사용자명\Downloads\QA_runner_K"
py -3.11 --version
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m playwright install chromium
.\.venv\Scripts\python.exe -m tkinter
```

마지막 명령어로 작은 Tk 테스트 창이 열리면 닫고 본 프로그램을 실행합니다.

```powershell
.\.venv\Scripts\python.exe qa_runner_k_gui.py
```

`py` 명령어가 없다면 `python --version`으로 3.11인지 확인한 뒤, 처음 두 `py -3.11` 명령어를 `python`으로 바꿔 실행하세요.

**다음 실행부터**는 프로젝트 폴더에서 실행 명령어만 입력하면 됩니다.

```powershell
cd "C:\Users\사용자명\Downloads\QA_runner_K"
.\.venv\Scripts\python.exe qa_runner_k_gui.py
```

## 3. macOS(맥북) 실행

**터미널**을 열고 아래 명령어를 순서대로 실행하세요.

```bash
cd "$HOME/Downloads/QA_runner_K"
python3.11 --version
python3.11 -m venv .venv
./.venv/bin/python -m pip install --upgrade pip
./.venv/bin/python -m pip install -r requirements.txt
./.venv/bin/python -m playwright install chromium
./.venv/bin/python -m tkinter
```

마지막 명령어로 작은 Tk 테스트 창이 열리면 닫고 본 프로그램을 실행합니다.

```bash
./.venv/bin/python qa_runner_k_gui.py
```

`python3.11` 명령어가 없다면 `python3 --version`으로 3.11인지 확인한 뒤, 처음 두 `python3.11` 명령어를 `python3`으로 바꿔 실행하세요.

**다음 실행부터**는 프로젝트 폴더에서 실행 명령어만 입력하면 됩니다.

```bash
cd "$HOME/Downloads/QA_runner_K"
./.venv/bin/python qa_runner_k_gui.py
```

가상환경은 운영체제와 Python 설치 경로에 종속됩니다. Windows에서 만든 `.venv`를 맥북으로 복사하거나 그 반대로 사용하지 말고, 각 컴퓨터에서 새로 만드세요.

## 4. 처음 테스트 실행하기

입력란에서는 Windows의 `Ctrl+C / Ctrl+V / Ctrl+X / Ctrl+A`, macOS의 `⌘C / ⌘V / ⌘X / ⌘A`로 복사·붙여넣기·잘라내기·전체 선택을 사용할 수 있습니다. 우클릭 메뉴와 상단 **편집** 메뉴도 지원합니다. 로그와 TC 목록은 선택한 내용을 복사할 수 있으며 직접 수정할 수는 없습니다.

1. 프로그램의 **시작 지점 / 로그인 설정**에 테스트할 사이트의 시작 URL을 입력합니다.
2. 로그인 방식을 선택합니다.
   - `idpw`: ID와 PW를 입력합니다.
   - `none`: 로그인 없이 접속합니다.
   - `token`: 현재 코드에서는 구현되지 않았으므로 사용하지 마세요.
3. **저장**을 누릅니다.
4. 처음에는 **AI 없이 규칙 기반으로만 실행**을 체크한 상태로 진행합니다. 이 모드에서는 API 키가 필요 없습니다. 절차의 `[대괄호]`나 `"따옴표"` 표현을 규칙으로 해석하며, 근거가 부족한 결과는 **확인 필요**로 표시될 수 있습니다.
5. **TC 소스**를 선택합니다.
   - **로컬 엑셀 파일**: **엑셀 파일 선택...**으로 `.xlsx` 파일을 선택하면 TC를 바로 불러옵니다.
   - **대시보드 추가 TC**: **대시보드에서 TC 추가/수정...**으로 TC를 작성하거나 엑셀을 업로드합니다. **실행 포함** 상태로 저장하고 프로그램에서 해당 TC 소스를 선택하면 자동으로 불러옵니다. Python 소스 실행과 Windows EXE 모두 이 항목을 선택하면 **TC 소스** 제목 옆에 **로컬 QA 대시보드 / 서버** 선택 버튼이 나타납니다. 기본값은 로컬이며, 서버를 선택하면 팀 주소(기본 `https://qa.healthkoob.com/qa-k/`)의 TC 관리·조회 기능을 사용합니다. 서버 조회에는 아래 **서버 전송 토큰**이 필요하며, 서버에도 이 버전의 `dashboard_server.py`를 배포해야 합니다. 기존 EXE를 사용하는 경우에는 이 변경이 포함된 새 EXE로 교체해야 선택 버튼이 표시됩니다.
   - **서버 TC 세션**: 소스를 선택하면 세션 목록과 기본 세션의 TC를 자동으로 불러옵니다. 세션·시트 선택을 변경하면 TC 목록도 다시 불러옵니다. 로컬 엑셀 또는 로컬 대시보드 TC를 사용할 때는 서버 세션 연결이 필요 없습니다.

   TC·세션 불러오기 버튼은 사용하지 않습니다. 마지막 TC 소스·대시보드 연결 대상·엑셀 경로를 기억하여 다음 실행 때 복원하고 자동으로 불러옵니다. 대시보드 추가 TC는 첫 사용 시 로컬이 기본값이며, 로컬·서버 선택을 변경할 때마다 목록을 다시 불러옵니다. 대시보드에서 TC를 추가한 후에는 소스 라디오 버튼을 다시 눌러 목록을 갱신하세요.
6. 실행할 TC를 선택하거나 **전체 선택**을 누릅니다. 처음에는 **최대 실행 수**를 `1`로 설정해 동작을 확인하세요. `0`은 실행 수 제한이 없다는 뜻입니다.
   TC 목록은 **TC / 실행결과** 두 컬럼으로 표시하며 기존 우선순위·번호·제목 문구를 유지합니다. 기존 실행 기록이 있으면 최근 **PASS / 확인 필요 / FAIL**을 보여주고, 기록이 없으면 빈칸입니다. 과거 결과가 표시된 TC도 재실행할 수 있으며 실행이 끝나면 해당 행의 결과가 갱신됩니다. 로컬 기록은 이 PC의 DB에서, 서버 기록은 변경된 서버 `/api/tcs` 응답에서 조회합니다. 서버 기록 표시에는 `dashboard_server.py`와 `results_store.py`를 서버에 반영하고 이미지를 재빌드해야 합니다.

   TC를 더블 클릭하거나 하나 선택하고 오른쪽 **수정** 버튼을 누르면 **TC 상세정보** 팝업이 열립니다. TC 번호는 한 줄의 읽기 전용 입력란이며, 제목·사전조건·절차·예상 결과는 편집 가능합니다. 우선순위와 시트는 선택 상자입니다. 비고·최근 실행결과·최근 실행 사유는 읽기 전용입니다. **닫기** 왼쪽의 **저장**은 원본과 달라진 항목이 있을 때만 활성화됩니다. 저장하면 원래 Excel·로컬 DB·서버 TC와 프로그램 목록에 반영되며, 기존 결과를 비워 재실행하도록 합니다. 다른 곳에서 먼저 수정한 TC는 덮어쓰지 않습니다. 서버 저장은 확장된 `PUT /api/tcs/<id>`를 제공하는 `dashboard_server.py`와 `results_store.py` 배포가 필요합니다. 최적화는 아직 제공하지 않습니다. **전체 선택 / 선택 해제** 버튼은 목록 아래 왼쪽에 있습니다.

   목록의 우선순위 선택 상자 오른쪽에서 **전체 / PASS / 확인 필요 / FAIL**로 최근 실행결과를 필터링할 수 있습니다. 전체는 미실행 TC도 표시합니다. 전체 선택은 현재 표시된 행에만 적용됩니다.

   **시작**으로 QA를 실행하면 각 TC의 판정이 반환되는 즉시 해당 행의 **PASS / 확인 필요 / FAIL**과 최근 실행 사유를 갱신합니다. 서버에서 불러온 TC도 동일하며, 로컬 저장이나 서버 전송 완료를 기다리지 않습니다. 실행 중 결과 표시는 별도의 서버 조회 API나 주기적인 동기화가 필요하지 않습니다.
7. **시작**을 누르면 Chromium 창이 열리고 테스트가 진행됩니다. **중지**를 누르면 현재 TC가 완료된 후 멈춥니다.
8. **결과 보기**를 눌러 로컬 실행 결과와 스크린샷을 확인합니다.

창이 작거나 화면 배율이 높아 내용이 잘리면 오른쪽·하단 스크롤바로 이동하세요. 입력 영역 위에서 마우스 휠은 세로, Shift+휠은 가로로 이동합니다. TC 목록과 로그 위에서는 해당 영역이 별도로 스크롤됩니다.

AI 모드를 사용하려면 규칙 기반 체크를 해제하고 **AI Provider**와 해당 서비스의 **API Key**를 입력합니다. 모델 이름은 현재 코드의 `action_model_var`, `judge_model_var`에 지정되어 있으므로, 해당 계정에서 사용할 수 있는 모델인지 확인하고 필요하면 코드를 수정하세요.

### TC 엑셀 형식

- 첫 번째 행에 컬럼 제목을 작성합니다.
- 필수 컬럼은 **테스트 항목**, **테스트 절차**, **예상 결과**입니다. 각 TC 행의 세 값도 모두 입력해야 합니다.
- 선택 컬럼은 `No`, `사전조건`, `우선순위`, `결과(Pass/Fail)`, `비고`입니다.
- 시트 이름은 `테스트케이스` 또는 `TC_로그인`처럼 `TC`나 `테스트케이스`를 포함하도록 작성하면 됩니다. 해당 이름의 시트가 없으면 필수 컬럼을 가진 시트를 찾아 읽습니다.
- 테스트 절차는 셀 안에서 줄바꿈하여 번호를 붙여 작성할 수 있습니다.
- 필수 값이 빠진 행은 경고와 함께 건너뜁니다. 기존 `.xls` 파일은 `.xlsx`로 저장한 뒤 사용하세요.

## 5. 대시보드만 실행하기

TC 관리와 기존 결과 조회만 필요할 때는 본 프로그램 대신 대시보드를 실행할 수 있습니다. 아래 명령어는 위의 가상환경·패키지 설치를 완료한 상태를 전제로 합니다. 대시보드만 사용할 때는 Chromium 설치를 생략할 수 있습니다.

**Windows / PowerShell**

```powershell
.\.venv\Scripts\python.exe dashboard_app.py
```

**macOS / 터미널**

```bash
./.venv/bin/python dashboard_app.py
```

본 프로그램에 `--dashboard`를 붙여도 같은 모드로 실행할 수 있습니다.

- TC 관리: [http://127.0.0.1:8765/tcs](http://127.0.0.1:8765/tcs)
- 실행 결과: [http://127.0.0.1:8765/](http://127.0.0.1:8765/)

기본 포트 `8765`가 사용 중이면 다른 포트가 선택될 수 있으므로 **프로그램 창 또는 로그에 표시된 주소**를 사용하세요. 기본 설정에서는 같은 컴퓨터에서 접속하며 로그인이 필요 없습니다. 대시보드가 서버를 직접 시작한 경우 창을 닫으면 서버도 종료됩니다. 다른 프로그램이 이미 띄운 서버에 연결한 경우에는 그 프로그램이 서버를 유지합니다.

대시보드는 TC 관리·결과 조회용입니다. **TC 실행은 본 프로그램에서 진행합니다.**

### 로컬 결과와 팀 대시보드

- **결과 보기**는 이 컴퓨터의 로컬 대시보드를 엽니다.
- **대시보드 바로가기 / 주소 복사**는 Python 소스 실행에서는 선택한 대상을 사용하고, EXE에서는 기존 팀 대시보드 주소를 사용합니다.
- 서버 업로드 토큰을 비워두면 결과는 로컬에만 저장됩니다. 서버에도 결과를 보내려면 팀 대시보드 주소와 서버에서 발급한 업로드 토큰을 설정하고 **연결 확인**을 누르세요.

## 6. 저장 파일과 종료

소스 실행 시 다음 파일은 프로젝트 폴더에 생성됩니다. EXE 실행 시에는 EXE가 있는 폴더에 생성됩니다.

- `qa_runner_k_config.json`: 시작 URL, 로그인 정보, 팀 대시보드 주소, 업로드 토큰 등의 설정
- `qa_runner_k_results.db`: 실행 결과, 대시보드에서 작성한 TC 등을 저장하는 SQLite DB
- `qa_runner_k_screenshots/`: 실행별 스크린샷

현재 설정 파일에는 **로그인 비밀번호와 업로드 토큰이 평문으로 저장됩니다.** 이 파일을 다른 사람에게 공유하지 마세요. `.gitignore`는 설정 파일, `.env`, 가상환경, DB, 스크린샷과 서버의 `data/` 폴더를 Git 추적 대상에서 제외합니다. 이미 추적 중인 파일에는 제외 규칙이 소급 적용되지 않습니다.

백업하려면 프로그램을 종료한 뒤 위 세 항목을 함께 복사하세요. 대시보드에는 실행 내역·스크린샷 보관 기간 설정(`QA_RUNNER_K_RETAIN_DAYS`, 기본 `30`일)이 있으므로 오래된 결과가 필요하면 별도 백업하세요.

테스트가 진행 중이면 **중지**를 누르고 현재 TC가 끝난 뒤 창을 닫으세요. 터미널에서 강제 종료해야 할 경우 `Ctrl+C`를 사용할 수 있습니다.

## 7. 자주 발생하는 문제

### Python 명령어를 찾을 수 없음

Python 설치 여부와 버전을 확인하고 터미널을 새로 여세요. Windows는 `py -3.11 --version`, macOS는 `python3.11 --version`으로 확인합니다. 프로젝트 폴더와 Python 명령어가 위 예시와 다르면 실제 환경에 맞게 바꾸세요.

### `No module named tkinter` 또는 `_tkinter`

Tkinter가 포함되지 않은 Python을 사용한 경우입니다. Tcl/Tk를 포함한 Python 설치본을 사용하고 해당 Python으로 가상환경을 다시 만드세요. macOS에서는 python.org 설치본으로 `python3.11 -m tkinter`를 먼저 확인할 수 있습니다.

### `ModuleNotFoundError` 또는 Flask 등 패키지 없음

패키지를 설치한 Python과 실행하는 Python이 다를 수 있습니다. 위 절차대로 `.venv` 안의 Python으로 `-m pip install -r requirements.txt`를 실행한 뒤 동일한 Python으로 프로그램을 실행하세요.

### Chromium 실행 파일이 없다는 오류

Python 패키지 설치와 브라우저 설치는 별도입니다. 아래 명령어를 다시 실행하세요.

```powershell
# Windows
.\.venv\Scripts\python.exe -m playwright install chromium
```

```bash
# macOS
./.venv/bin/python -m playwright install chromium
```

### PowerShell에서 가상환경 활성화가 차단됨

이 README는 `Activate.ps1`을 사용하지 않습니다. `.\.venv\Scripts\python.exe`를 직접 실행하면 실행 정책을 변경할 필요가 없습니다.

### 대시보드가 열리지 않거나 방금 실행한 결과가 보이지 않음

프로그램이 켜져 있는지 확인하고 로그에 표시된 로컬 주소 또는 **결과 보기**를 사용하세요. 팀 대시보드는 업로드가 성공한 결과만 확인할 수 있습니다. 프로그램을 다른 폴더로 옮겼다면 DB와 스크린샷도 함께 옮겼는지 확인하세요.

### 엑셀을 선택했는데 TC가 없음

첫 행의 필수 컬럼명과 각 행의 필수 값을 확인하세요. 헤더의 공백은 무시하지만 컬럼명 자체는 일치해야 합니다. 로그에 표시되는 시트·행별 경고를 확인하세요.

## 8. 서버 배포 파일 안내

`deploy/`는 팀 서버에서 **대시보드만** 운영하기 위한 Docker·Nginx 구성입니다. Windows·맥북에서 본 프로그램을 실행할 때는 필요하지 않습니다.

현재 `deploy/docker-compose.yml`은 기존 외부 네트워크 `qa-runner_external`, Nginx 연결, `QA_RUNNER_K_SECRET_KEY` 등의 환경 설정을 전제로 하며, 호스트 포트를 직접 공개하지 않습니다. 로컬 실행용으로 그대로 `docker compose up`을 실행하는 대신 위 Python 실행 절차를 사용하세요.

### v0.28.0 서버 TC 조회 API 적용

`GET https://qa.healthkoob.com/qa-k/api/tcs`는 루트 홈페이지의 `/api/`와 별개입니다. 기존 Nginx의 `/qa-k/` 연결을 통해 **qa-runner-k** 컨테이너의 `GET /api/tcs`로 전달됩니다. 인수인계 문서에 기록된 서버 폴더는 `/opt/qa-runner-k`, 환경 설정은 `/opt/qa-runner-k/deploy/.env`입니다. 실제 서버 경로가 변경됐다면 해당 경로를 사용하세요.

Dockerfile이 Python 소스를 이미지에 `COPY`하므로 **파일 교체 후 재빌드**해야 합니다. Windows EXE 릴리즈나 `docker-compose restart`만으로는 API가 추가되지 않습니다. 저장소에는 서버 자동 배포나 Docker 이미지 레지스트리 push 단계가 없습니다.

**1. 내 PC: 서버용 코드 압축 및 전송**

macOS에서 프로젝트 폴더를 기준으로 실행합니다. 기존 서버의 Docker·Nginx 구성은 유지하며, 대시보드 서버 코드 4개만 전달합니다. `.env`, PC 설정, DB, 스크린샷은 패키지에 포함하지 않습니다.

```bash
mkdir -p dist
tar -czf dist/qa-runner-k-v0.28.0-server.tar.gz \
  dashboard_server.py dashboard_auth.py results_store.py tc_excel.py
tar -tzf dist/qa-runner-k-v0.28.0-server.tar.gz

# 실제로 사용하는 SSH 키 파일 경로를 넣으세요. 키 내용은 공유하지 않습니다.
scp -i <키파일경로> dist/qa-runner-k-v0.28.0-server.tar.gz ec2-user@54.180.98.47:/tmp/
ssh -i <키파일경로> ec2-user@54.180.98.47
```

**2. 서버: 기존 경로·설정 확인 및 백업**

이하 명령은 SSH로 접속한 **서버에서** 실행합니다. 인수인계 문서의 서버는 `docker-compose`(하이픈)를 사용합니다. `docker compose`가 설치된 서버라면 명령을 그에 맞게 바꾸세요.

```bash
cd /opt/qa-runner-k/deploy
sudo docker inspect qa-runner-k --format '{{range .Mounts}}{{println .Source "->" .Destination}}{{end}}'
sudo test -f .env
sudo docker exec qa-runner-k python -c 'import os; print("API 토큰 설정:", bool(os.environ.get("QA_RUNNER_K_API_TOKEN", "").strip()))'

qa_k_backup="/opt/qa-runner-k-code-backup-$(date +%Y%m%d-%H%M%S)"
sudo mkdir -p "$qa_k_backup"
sudo cp -p /opt/qa-runner-k/dashboard_server.py /opt/qa-runner-k/dashboard_auth.py \
  /opt/qa-runner-k/results_store.py /opt/qa-runner-k/tc_excel.py "$qa_k_backup/"
printf '코드 백업: %s\n' "$qa_k_backup"

# SQLite의 backup 기능으로 실행 중에도 일관된 DB 사본을 생성합니다.
sudo docker exec qa-runner-k python -c 'import os, sqlite3, time; p=os.environ["QA_RUNNER_K_DB_PATH"]; dst=p+".backup-"+time.strftime("%Y%m%d-%H%M%S"); src=sqlite3.connect(p); out=sqlite3.connect(dst); src.backup(out); out.close(); src.close(); print("DB 백업:", dst)'
```

`/data`가 기존 `/opt/qa-runner-k/data`에 연결됐는지 확인합니다. 토큰이 미설정이면 서버 관리자가 기존 `.env`의 `QA_RUNNER_K_API_TOKEN`을 설정하고, 프로그램에도 같은 값을 입력해야 합니다. 이미 설정된 토큰과 `QA_RUNNER_K_SECRET_KEY`는 유지합니다.

**3. 서버: 코드 반영 및 qa-runner-k만 재빌드**

```bash
qa_k_stage=$(mktemp -d /tmp/qa-runner-k-deploy.XXXXXX)
tar -xzf /tmp/qa-runner-k-v0.28.0-server.tar.gz -C "$qa_k_stage"
sudo cp "$qa_k_stage/dashboard_server.py" "$qa_k_stage/dashboard_auth.py" \
  "$qa_k_stage/results_store.py" "$qa_k_stage/tc_excel.py" /opt/qa-runner-k/

cd /opt/qa-runner-k/deploy
sudo docker-compose up -d --build --no-deps qa-runner-k
sudo docker ps --filter name=qa-runner-k --format '{{.Names}} {{.Status}}'
sudo docker logs --tail 50 qa-runner-k
```

재생성하는 동안 `/qa-k/`에 잠깐 접속되지 않을 수 있습니다. `/opt/qa-runner`의 원본 홈페이지 구성, `qa-nginx`, `qa-flask`, `qa-db`는 이번 배포 대상으로 지정하지 않습니다. 기존 `data`와 `.env`를 삭제하거나 교체하지 않으며 TC 재등록은 필요 없습니다. 기존 보관기간 설정에 따른 오래된 실행 결과 정리는 서버 시작 시에도 적용될 수 있습니다.

**4. 배포 검증**

```bash
# 서버 컨테이너 사이의 API 확인: 인증 토큰 없이 요청
sudo docker exec qa-nginx curl -sS -o /dev/null -w '%{http_code}\n' \
  http://qa-runner-k:8765/api/tcs

# 내 PC 또는 서버: 실제 HTTPS 경로 확인 (토큰 없이 요청)
curl -sS -o /dev/null -w '%{http_code}\n' https://qa.healthkoob.com/qa-k/api/tcs

# 서버: 컨테이너에 설정된 토큰으로 조회. 토큰이나 TC 내용 대신 건수만 출력
sudo docker exec qa-runner-k python -c 'import os, requests; token=os.environ.get("QA_RUNNER_K_API_TOKEN", "").strip(); r=requests.get("http://127.0.0.1:8765/api/tcs", headers={"Authorization": "Bearer "+token}, timeout=10); print("HTTP:", r.status_code); r.raise_for_status(); rows=r.json(); print("실행 포함 TC:", len(rows))'
```

- **401**: 토큰 없는 요청에 정상적으로 인증을 요구합니다. API가 등록됐다는 신호입니다.
- **503**: 서버 API 토큰이 미설정입니다.
- **404**: 실행 중인 이미지에 새 코드가 없거나 `/qa-k/` 프록시 경로가 맞지 않습니다. 내부 요청은 401인데 외부 요청만 404라면 Nginx 연결을 확인합니다.
- **200**: 올바른 토큰으로 TC 목록을 조회했습니다. 빈 목록 `[]`이면 서버 DB의 “실행 포함” TC가 없는 것입니다.
- **SSL 인증서 오류**: 서버 인증서 갱신·적용을 확인합니다. `-k`나 `verify=False`로 검증을 끄지 않습니다.

마지막으로 Python 프로그램에서 **대시보드 추가 TC → 서버** 선택로 HTTPS 경로와 토큰까지 확인합니다. **EC2 세션**의 `/api/sessions/...`는 다른 서비스의 조회 경로이며 이번 `/qa-k/api/tcs` 배포와 구분됩니다.

**코드만 되돌릴 때**는 위에서 기록한 백업 폴더의 Python 파일 4개를 `/opt/qa-runner-k/`에 복사한 후 같은 재빌드 명령을 실행합니다. `data`나 `.env`를 과거 사본으로 덮어쓰지 않습니다.
