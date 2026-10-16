# 새 Mac에서 작업 이어가기

이 문서는 2026-10-16 현재 Mac에서 새 Mac으로 개발 장소를 옮기기 위한 인계 기록이다. 작업 저장소는 `https://github.com/tmdals5488-max/autoBit.git`, 작업 브랜치는 `codex/multifactor-risk-overlay-v1-2`다. 원본 저장소는 `https://github.com/seungminbluebox/autoBit.git`이며 현재 로그인 계정에는 읽기 권한만 있다. 실제 업비트 주문은 잠겨 있다.

## 새 Mac에서 시작

2026-10-16 현재 `tmdals5488-max` 계정의 인증을 갱신했지만 원본 `seungminbluebox/autoBit` 저장소에 대한 권한은 `READ`라서 업로드가 HTTP 403으로 거절됐다. 로그인한 계정에 공개 포크를 만들고 이 작업 브랜치를 업로드했다. 아래 GitHub 절차를 우선 사용한다.

### GitHub에서 바로 받기

1. GitHub에서 `tmdals5488-max` 계정으로 로그인한다.
2. 새 Mac의 터미널에서 원하는 작업 폴더에 포크를 복제하고 작업 브랜치를 체크아웃한다.

   ```sh
   git clone https://github.com/tmdals5488-max/autoBit.git
   cd autoBit
   git switch --track origin/codex/multifactor-risk-overlay-v1-2
   git status --short
   ```

### GitHub 접속이 안 될 때 파일 이동

1. 현재 Mac의 `자동 트레이딩/autoBit-new-mac-20261016.bundle` 파일을 새 Mac의 `Downloads` 폴더로 옮긴다. Git 이력과 현재 작업 브랜치를 담은 파일이며 모의 원장과 계정 키는 담지 않는다.
2. 새 Mac의 터미널에서 다음을 실행한다.

   ```sh
   cd ~/Documents
   git clone -b codex/multifactor-risk-overlay-v1-2 ~/Downloads/autoBit-new-mac-20261016.bundle autoBit
   cd autoBit
   git remote set-url origin https://github.com/tmdals5488-max/autoBit.git
   git status --short
   ```

3. ChatGPT 데스크톱 앱에서 같은 ChatGPT 계정과 워크스페이스로 로그인하고 Codex에서 새로 받은 `autoBit` 폴더를 프로젝트로 연다. 이전 Mac의 로컬 Codex 대화가 보이지 않아도 코드는 이 브랜치에서 이어진다.
4. 새 Codex 작업에서 이 문서와 `docs/runbooks/operational-readiness-20261016.md`, `docs/runbooks/first-cloud-server.md`를 읽고 이어서 진행하도록 요청한다.

## 현재 상태

- 4시간봉 KRW-BTC 핵심 시스템은 기존대로다. Multi-Factor Overlay v1.2는 연구용 백테스트 경로에만 추가됐다. Macro stress의 임계값과 발표 시각 포함 데이터가 없으므로 실데이터 성과 판단은 `NEED MORE DATA`다.
- 현재 Mac에서 실제 업비트 공개 시세로 `paper-once` 한 번을 실행했다. 모의 주문은 0건, 원장 건강은 `NORMAL`이었다. 이 1회 실행은 지속 운용이나 수익성 증거가 아니다.
- 현재 Mac의 SQLite 모의 원장, 공개 시세 원본, 연구 보고서는 Git에서 제외되어 새 Mac으로 자동 이동하지 않는다. 새 Mac 또는 서버의 모의 운용은 별도의 새 원장으로 시작한다. 이전 기록을 합산하지 않는다.
- 서버는 아직 생성되지 않았다. 사용자는 컴퓨터를 꺼도 모의매매가 돌아가는 서버를 원한다. 계정 보유 여부와 무료/유료 예산은 확인이 필요하다. 세부 준비와 미해결 설치 항목은 `first-cloud-server.md`를 참조한다.
- 전체 검증에서 Linux 전용 배포 테스트가 macOS에서 실패했고, 기존 golden PBO 수치가 미세한 부동소수점 순위 차이로 맞지 않았다. 원본 main에서도 재현됐다. 상세 증거는 `operational-readiness-20261016.md`에 있다. 배포 전 Linux에서 검증한다.

## 계속할 때 지킬 경계

- 실거래 잠금 해제, 업비트 API 키 요청, 실주문 실행은 별도 명시적 지시 전까지 하지 않는다.
- 서버가 준비되면 먼저 paper-only 서비스를 확인하고 실제 처리 기록을 쌓는다. Mac 종료 여부와 무관한 운영 상태는 서버에서 검증한다.
- 새 Mac의 GitHub/클라우드 로그인과 결제 정보 입력은 사용자가 직접 한다. 비밀번호, 인증 코드, 개인 키 원문을 대화나 저장소에 붙여 넣지 않는다.
