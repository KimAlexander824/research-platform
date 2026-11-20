# Research Platform

Платформа управления научными исследованиями.

```
backend/    — серверная часть (FastAPI)
frontend/   — веб-интерфейс
```

## Backend

**Стек:** Python 3.13, FastAPI, PostgreSQL, SQLAlchemy 2 (async), Alembic, Redis, uv.

### Запуск через Docker

Нужен Docker Desktop.

```bash
cp backend/.env.example backend/.env
docker compose up --build
```

- API: http://localhost:8000
- Swagger: http://localhost:8000/docs
- ReDoc: http://localhost:8000/redoc

Миграции применяются автоматически при старте контейнера `api`.

### Запуск без Docker (для разработки)

Нужен [uv](https://docs.astral.sh/uv/). База и Redis запускаются в Docker:

```bash
docker compose up -d postgres redis
cd backend
cp .env.example .env
uv sync
uv run alembic upgrade head
uv run uvicorn app.main:app --reload
```

### Тесты

```bash
cd backend
uv run pytest
```

### Миграции

```bash
cd backend
uv run alembic revision --autogenerate -m "описание изменения"
uv run alembic upgrade head      # применить
uv run alembic downgrade -1      # откатить последнюю
```

### Переменные окружения

| Переменная | Описание | Пример |
|---|---|---|
| `ENVIRONMENT` | `development` или `production` | `development` |
| `LOG_LEVEL` | Уровень логирования | `INFO` |
| `DATABASE_URL` | Подключение к PostgreSQL | `postgresql+asyncpg://research:research@localhost:5432/research` |
| `REDIS_URL` | Подключение к Redis | `redis://localhost:6379/0` |
| `CORS_ORIGINS` | Адреса фронтенда через запятую | `http://localhost:5173` |

## Соглашения API

- Базовый путь: `/api/v1/`, формат — JSON, поля в camelCase.
- Даты — ISO 8601 в UTC (`2026-11-20T09:55:00Z`), даты без времени — `YYYY-MM-DD`.
- Пагинация: `?page=1&pageSize=20&sort=-createdAt` → `{"items": [...], "total": 134, "page": 1, "pageSize": 20}`.
- Ошибки всегда в одном формате:

```json
{
  "error": {
    "code": "VALIDATION_ERROR",
    "message": "Request validation failed",
    "fields": { "email": ["REQUIRED"] }
  }
}
```

`code` — стабильный код для фронтенда (переводится на язык интерфейса), `message` — техническое описание, `fields` — только для ошибок валидации.

## Структура backend

```
backend/app/
  core/       — общее: настройки, БД, ошибки, пагинация, логирование
  api.py      — подключение роутеров модулей
  main.py     — точка входа
```

Каждый модуль (accounts, projects, stages, ...) — отдельная папка с одинаковой структурой:
`models.py`, `schemas.py`, `repository.py`, `service.py`, `router.py`, `permissions.py`, `dependencies.py`, `exceptions.py`.
