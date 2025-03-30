# GPT-TAP (Tistory Auto Poster)

구글 시트의 글을 티스토리에 자동으로 발행하는 웹 애플리케이션입니다.

## 기능

- 구글 시트에서 글 목록 가져오기
- 티스토리 계정 관리 및 로그인
- 즉시 발행 및 예약 발행 지원
- 발행 상태 모니터링

## 설치 방법

1. Python 3.7 이상을 설치합니다.

2. 필요한 패키지를 설치합니다:
```bash
pip install -r requirements.txt
```

3. Chrome WebDriver를 설치합니다:
- Windows: https://sites.google.com/chromium.org/driver/
- 다운로드한 chromedriver.exe를 시스템 PATH에 추가하거나 프로젝트 루트 디렉토리에 복사

4. Google API 인증 설정:
- Google Cloud Console에서 서비스 계정 생성
- credentials.json 파일을 다운로드하여 프로젝트 루트에 저장하거나
- .env 파일에 인증 정보 입력

## 실행 방법

1. 서버 실행:
```bash
uvicorn main:app --reload
```

2. 웹 브라우저에서 접속:
http://localhost:8000

## 사용 방법

1. 티스토리 계정 등록:
- "티스토리 로그인" 메뉴에서 계정 추가
- 여러 개의 계정 등록 가능

2. 구글 시트 연동:
- 구글 시트 URL, 시트 이름, 제목/내용 열 지정
- "데이터 가져오기" 클릭

3. 글 발행:
- 발행할 글 선택
- 즉시 발행 또는 예약 발행 선택
- 발행 계정 선택 후 발행

4. 상태 확인:
- "발행 상태 확인" 메뉴에서 발행 현황 모니터링
- 5초마다 자동 새로고침 