# daolab-bot

DAOLab Discord 봇입니다. 출석 체크, 감사 포인트 등을 제공합니다.

## 요구사항

- uv
- MongoDB
- Discord Bot Token

## 설치

```sh
# 가상환경 생성
uv venv

# 의존성 설치
uv sync
```

## 환경 설정

프로젝트 루트에 `.env` 파일을 생성하고 다음 변수를 설정:

```env
DISCORD_TOKEN=your_discord_bot_token
MONGO_HOST=localhost
MONGO_USER=your_mongo_username
MONGO_PASS=your_mongo_password
MONGO_PORT=27017
```

## 실행

```sh
# 봇 실행
uv run python app/main.py

# 또는 가상환경에서
python app/main.py
```

## 테스트

```sh
# 모든 테스트 실행 (Mongo가 없으면 통과로 스킵)
uv run pytest -q

# 특정 통합 테스트 스크립트 직접 실행
uv run python tests/test_attendance.py
uv run python tests/test_core_mongo.py
```
