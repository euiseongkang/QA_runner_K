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

   TC를 더블 클릭하거나 하나 선택하고 오른쪽 **수정** 버튼을 누르면 **TC 상세정보** 팝업이 열립니다. TC 번호는 한 줄의 읽기 전용 입력란이며, 제목·사전조건·절차·예상 결과는 편집 가능합니다. 우선순위와 시트는 선택 상자입니다. 비고·최근 실행결과·최근 실행 사유는 읽기 전용입니다. **닫기** 왼쪽의 **저장**은 원본과 달라진 항목이 있을 때만 활성화됩니다. 저장하면 원래 Excel·로컬 DB·서버 TC와 프로그램 목록에 반영되며, 기존 결과를 비워 재실행하도록 합니다. 다른 곳에서 먼저 수정한 TC는 덮어쓰지 않습니다. 서버 저장은 확장된 `PUT /api/tcs/<id>`를 제공하는 `dashboard_server.py`와 `results_store.py` 배포가 필요합니다. AI 최적화는 아래 안내를 참고하세요. **전체 선택 / 선택 해제** 버튼은 목록 아래 왼쪽에 있습니다.

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

## Ollama 연결 및 모델 설치

1. **AI Provider → Ollama**를 선택합니다. API Key는 필요 없습니다.
2. **로컬**은 `http://127.0.0.1:11434`를 사용합니다. 다른 서버는 **IP·포트 직접 입력**에서 호스트와 포트를 별도로 입력합니다. 해당 서버에 Ollama API가 실행되어 있어야 합니다.
3. 연결 상태는 선택 시와 15초 간격으로 확인하며 **연결 확인**으로 다시 확인할 수 있습니다.
4. 모델 목록에는 설치된 모델과 인터넷에서 공식 모델 페이지를 확인한 TC용 권장 모델이 표시됩니다. 전체 Ollama 라이브러리 목록은 아닙니다. 설치된 모델은 **[설치완료]**, 권장 미설치 모델은 **[미설치]**로 표시합니다.
5. 미설치 모델 선택 후 **설치**를 누르면 선택한 Ollama 서버에 다운로드합니다. 진행률을 표시하며 완료 후 목록을 갱신합니다. 원격 선택 시 내 PC가 아닌 원격 서버의 디스크에 설치됩니다. 원격 서버에도 인터넷 연결과 충분한 디스크 공간이 필요합니다.
6. 모델 설명에는 권장 용도, 다운로드 크기, 이미지 지원 여부와 권장 RAM을 표시합니다. RAM은 여유를 고려한 권장치이며 OS·컨텍스트 길이·GPU 구성에 따라 달라집니다.
7. **설정 저장**으로 Provider·연결 대상·IP·포트·모델을 저장합니다. AI를 사용한 QA 실행은 **AI 없이 규칙 기반으로만 실행**을 해제해야 합니다.

기본 설치 권장은 **`qwen2.5:1.5b` (약 986MB)**이며, **`gemma3:1b` (약 815MB)**는 짧은 문장 정리용 초경량 대안입니다. 다운로드 크기는 실행 메모리 크기와 다르며 작은 모델의 TC 개선안도 사람이 검토해야 합니다. 두 모델은 텍스트 전용입니다. 스크린샷을 입력하는 AI 판정에는 별도로 설치한 `gemma3:4b` 등 이미지 지원 모델이 필요합니다. 7B·12B·14B 모델은 기본 미설치 권장 목록에서 제외하며, 이미 설치된 모델은 계속 목록에 표시합니다. 로컬의 저장된 12B·14B 선택은 다음 프로그램 시작 시 `qwen2.5:1.5b`로 전환하며, 원격 모델 선택은 유지합니다.

Ollama 요청은 `num_ctx=4096`으로 컨텍스트 크기를 제한하고 `keep_alive=0`으로 응답 후 모델 메모리를 해제하도록 요청합니다. 다시 호출할 때 로딩 시간이 발생할 수 있습니다. Ollama AI 호출은 최소 180초의 응답 제한을 사용합니다. `:cloud` 모델은 외부에서 실행되며 Ollama 로그인과 인터넷 연결이 필요합니다.

TC 최적화 요청은 판정 규칙 전문도 함께 전달하므로 `num_ctx=8192`를 사용합니다. 일반 QA 실행보다 컨텍스트 메모리가 더 필요하므로 경량 모델을 권장합니다. 로컬 모델 최적화에는 세 항목 JSON 스키마와 `temperature=0`을 지정합니다. Ollama Cloud는 구조화 출력을 지원하지 않아 `:cloud` 모델에는 스키마 옵션을 보내지 않습니다. 응답이 잘리거나 필수 항목이 없으면 적용하지 않고 오류를 안내합니다.

최적화 출력 한도는 3072토큰입니다. Ollama가 길이 제한으로 불완전한 JSON을 반환하면 최대 4096토큰으로 한 번만 다시 요청합니다. 재시도해도 모델과 컨텍스트 크기는 유지합니다. 완전한 JSON으로 끝났다면 종료 사유가 길이 제한이어도 항목 검증 후 사용할 수 있습니다. 두 번째 응답도 잘렸다면 적용하지 않고 입력 내용을 유지합니다.

공식 문서: [모델 목록 API](https://docs.ollama.com/api/tags), [모델 설치 API](https://docs.ollama.com/api/pull), [Qwen2.5](https://ollama.com/library/qwen2.5), [Gemma3](https://ollama.com/library/gemma3).

## TC 상세정보 AI 최적화

TC 목록의 **수정** 또는 더블 클릭으로 상세정보를 열고, 하단 왼쪽 **최적화**를 누릅니다. 현재 선택한 AI Provider와 모델로 사전조건·테스트 절차·예상 결과를 다듬습니다. Claude/OpenAI는 유효한 API Key와 이용 가능한 API 계정이 필요하며, Ollama는 연결된 서버의 설치된 모델을 사용합니다. 이 버튼은 **AI 없이 규칙 기반으로만 실행** 설정과 별개로 AI를 호출합니다.

요청에는 해당 TC의 최근 실행결과(PASS·확인 필요·FAIL)와 실행 사유도 함께 전달합니다. AI는 이를 참고해 초기 상태·동작·검증 기준을 구체화하며, 실패를 숨기도록 예상 결과를 바꾸거나 검증 강도를 낮추지 않도록 지시합니다. 실행 이력이 없으면 두 값은 빈 문자열로 전달합니다.

작업 중 안내 모달에 **현재 AI최적화 진행 중 입니다...**, 진행 막대와 대기 커서를 표시합니다. 완료되면 변경 전후를 보여줍니다. **적용**은 상세정보 입력란에만 제안을 반영하고, **취소**는 기존 입력 내용을 유지합니다. 제목·우선순위·시트 등 다른 TC 항목은 변경하지 않습니다. 원본 로컬/서버 데이터에 반영하려면 상세정보의 **저장**을 눌러야 합니다.

취소해도 이미 전송된 AI 요청은 종료될 때까지 처리될 수 있으며, 그 응답은 적용하지 않습니다. 이전 요청이 종료되기 전에는 새 최적화 요청을 시작하지 않습니다. 작은 모델의 제안도 테스트 목적과 실제 화면에 맞는지 확인한 뒤 저장하세요.

최적화 요청에는 [TC 실행·판정 규칙](TC_EXECUTION_RULES.md) 전문도 함께 전달합니다. 요청마다 파일을 읽으므로 Python 실행 시 문서 수정이 다음 요청에 반영됩니다. 규칙 파일이 없거나 비어 있으면 최적화 오류를 안내합니다. Windows 빌드 워크플로는 이 파일을 EXE에 포함합니다. 수동 PyInstaller 빌드 시에도 `--add-data "TC_EXECUTION_RULES.md:."` 옵션을 추가해야 합니다(PyInstaller 구버전 Windows는 구분자로 `;` 사용). 판정/액션 코드를 변경할 때 문서도 함께 갱신하세요.

최적화 품질을 위해 검색·검색어 지우기·체크박스 해제·환자 구분 필터·팝업에 해당하는 작성 예시를 요청에 함께 전달합니다. 예시는 실제 TC의 입력값과 목적을 보존해 적용하도록 지시합니다. 응답은 세 항목 형식 외에 원문 입력값과 순서, 입력·Enter·지우기 실행 단계의 보존, 미노출 조건 누락 여부를 검사합니다. 내 환자만 보기 해제 TC는 사전조건의 최초 선택 상태와 절차의 해제 목표도 검사합니다. 변경 불필요 판단에는 구체적인 검토 이유가 필요합니다. 검사에 실패하면 한 번만 보완 요청하며, 계속 실패하거나 응답 형식이 부적절하면 AI 내용 개선안을 채택하지 않고 원문 기반 기본 교정으로 전환합니다. 이 검사는 의미 전체나 실제 서비스 동작의 정확성을 보장하지 않으므로 최종 적용·저장은 사용자가 검토합니다.

v0.33.0에서는 AI가 변경 불필요로 판단한 경우에도 기본 교정을 제공합니다. 공백·줄 정렬·기존 번호의 연속 순서와 명확한 서술 오타(`됬`, `되엇`, `확인한 다`, `클릭한 다`)를 교정합니다. 대괄호 대상과 따옴표 안의 입력값은 그대로 보존하며 동작과 검증 조건을 추가하거나 바꾸지 않습니다. 변경이 있으면 `✓ 기본 교정` 미리보기에서 적용할 수 있고, 기본 교정도 필요하지 않으면 변경 불필요로 표시합니다. API 연결 오류는 별도로 안내합니다.

경량 모델이 초기 상태를 빠뜨리는 문제를 줄이기 위해 규칙으로 정리한 초안도 함께 전달합니다. 초안은 내 환자만 보기 해제 시 최초 선택 상태·비교할 테스트 데이터의 준비 조건·해제 목표를 명시하며, 한 줄에 붙은 번호 항목의 줄바꿈도 정리합니다. 실제 데이터가 존재한다고 단정하지 않습니다. 원본과 초안을 모두 전달하고 제안은 원본 기준으로 검증합니다. Ollama에는 판정 규칙 전문을 system 메시지로, 해당 TC의 편집 요구·실행 사유·초안을 user 메시지로 분리합니다. 보완 요청도 규칙을 유지하되 실패한 항목에 집중합니다.

검색어 지우기 TC는 입력창에 연결된 X 버튼(`aria-label="입력 지우기"` 포함)을 클릭하고, 빈 입력값·검색 조건 없는 조회 성공·초기 환자 목록 복귀를 코드로 검증합니다. 화면 본문에 '입력창', '비어', '검색어'라는 단어가 없다는 이유로 확인 필요로 판정하지 않습니다. 목록 복귀 근거가 부족하면 확인 필요를 유지합니다.

환자 목록의 페이지 이동 TC는 페이지네이션 숫자 버튼을 정확히 식별해 클릭합니다. ‘선택 상태인지 확인’ 문장을 추가 클릭으로 실행하지 않습니다. 대상 페이지 선택·해당 page의 조회 성공·환자 목록 변경을 수집하며, 시작 URL과 선택 번호에서 페이지 인덱스 기준을 확인하지 못하면 확인 필요를 유지합니다.

페이지 이동 전 필터 해제가 필요하면 테스트 절차에 `[내 환자만 보기] 체크박스를 해제 상태로 설정한다`를 명시합니다. 체크박스 상태 설정은 실제 체크박스를 찾아 목표 상태로 설정하며, 이미 해제되어 있으면 유지합니다. ‘체크박스가 해제되어 있고 [2] 버튼이 표시되는지 확인한다’ 같은 확인 문장은 클릭으로 실행하지 않습니다.
v0.33.0의 값이 없는 항목 표시 TC는 휴대전화번호·병동·병실의 실제 셀에서 하이픈(`-`)과 빈칸을 검사합니다. 지정 열마다 하이픈 사례가 있고 빈 셀이 없으면 PASS, 빈 셀이 있으면 FAIL, 열이나 검증할 사례가 없으면 확인 필요입니다. 현재 조회 목록의 표시 검사이며 서버 원본 데이터의 null 여부를 검증하는 기능은 아닙니다.

# Open WebUI Provider 설정

AI Provider에서 `Open WebUI (RAG)`를 선택한다. API 주소 기본값은 `http://localhost:8080`이며 다른 서버 또는 프록시의 기본 경로로 변경할 수 있다.

1. Open WebUI의 프로필 → 설정 → 계정 → API Keys에서 키를 발급한다. 항목이 없으면 관리자 인증 설정의 API Keys 활성화 및 계정 권한을 확인한다. 기존 키가 있으면 재발급하지 않고 그 키를 사용한다.
2. QA 프로그램의 Open WebUI API Key 입력란에 키를 입력한다. 키는 설정 JSON에 저장하지 않는다. 매 실행 입력하거나 실행 환경의 `OPENWEBUI_API_KEY`로 제공할 수 있다.
3. `연결 확인 / 목록 갱신`을 누른다. API Key 인증으로 접근 가능한 대화용 모델과 지식 기반을 조회한다. 임베딩 모델은 답변 모델 목록에서 제외한다.
4. 대화용 모델은 설치된 `qwen2.5:1.5b` 등으로 선택한다. `embeddinggemma`는 Open WebUI 문서 검색의 임베딩 설정에서 사용하고, 대화용으로 선택하지 않는다.
5. QA 지식 기반에서 `QA_runner_K 프로젝트 지식`, 웹 소스 지식 기반에서 `web-labconnect21 웹 소스`를 선택하고 설정을 저장한다. 지식 기반 ID를 직접 입력해도 된다.

TC 상세 최적화 요청은 선택한 지식 기반을 Open WebUI의 `/api/chat/completions`에 collection으로 첨부한다. 검색 근거가 없는 응답, 잘린 응답 및 기존 품질 검증을 통과하지 못한 제안은 적용하지 않는다. 원본 TC는 적용/저장 전까지 유지된다. Open WebUI 폴더 설정은 이 API 요청으로 자동 상속되지 않으므로 프로그램에서도 지식 기반을 선택해야 한다.

API Key 엔드포인트 제한을 사용한다면 `/api/models`, `/api/v1/knowledge`, `/api/chat/completions` 접근이 필요하다. 실제 서버 인증과 최적화 품질은 발급한 키를 입력한 뒤 연결 확인 및 TC 시범 실행으로 확인해야 한다.
