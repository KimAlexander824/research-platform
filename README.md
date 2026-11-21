# Research Platform

Платформа управления научными исследованиями.

```
backend/    — серверная часть (FastAPI)
frontend/   — веб-интерфейс
```

## Backend

**Стек:** Python 3.13, FastAPI, PostgreSQL, SQLAlchemy 2 (async), Alembic, Redis, S3-совместимое хранилище файлов, uv.

### Запуск через Docker

Нужен Docker Desktop.

```bash
cp backend/.env.example backend/.env
docker compose up --build -d
```

```bash
docker compose logs -f api   # логи API (Ctrl+C — выйти из просмотра)
docker compose down          # остановить
```

- API: http://localhost:8000
- Swagger: http://localhost:8000/docs
- ReDoc: http://localhost:8000/redoc
- Админ-панель: http://localhost:8000/admin (вход — email и пароль администратора)
- Консоль файлового хранилища (RustFS): http://localhost:9001 — логин `research`, пароль `research-secret`

Миграции применяются автоматически при старте контейнера `api`.

### Первый администратор

Через API стать администратором нельзя — первый администратор создаётся командой:

```bash
docker compose exec api python -m app.accounts.cli create-admin --email admin@example.com --password "Пароль123" --name "Администратор"
```

Если пользователь с таким email уже зарегистрирован, ему выдаётся роль `admin` (пароль не меняется, `--password` можно не указывать).

### Запуск без Docker (для разработки)

Нужен [uv](https://docs.astral.sh/uv/). База, Redis и хранилище запускаются в Docker:

```bash
docker compose up -d postgres redis storage
cd backend
cp .env.example .env
uv sync
uv run alembic upgrade head
uv run uvicorn app.main:app --reload
```

### Тесты

Тесты используют PostgreSQL и Redis из Docker (отдельная база `research_test` и Redis DB 15 — данные разработки не затрагиваются). Хранилище файлов в тестах эмулируется в памяти:

```bash
docker compose up -d postgres redis
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
| `JWT_SECRET` | Секрет подписи токенов, не короче 32 символов. В production обязателен | случайная строка |
| `ACCESS_TOKEN_TTL_MINUTES` | Время жизни access-токена, минуты | `15` |
| `REFRESH_TOKEN_TTL_DAYS` | Время жизни refresh-токена (сессии), дни | `30` |
| `LOGIN_MAX_ATTEMPTS` | Неудачных попыток входа до блокировки | `5` |
| `LOGIN_LOCKOUT_MINUTES` | Время блокировки входа, минуты | `15` |
| `AUTH_RATE_LIMIT_PER_MINUTE` | Лимит запросов к `/auth/*` с одного IP в минуту | `20` |
| `FRONTEND_URL` | Адрес фронтенда для ссылок в письмах | `http://localhost:5173` |
| `FRONTEND_VERIFY_EMAIL_PATH` | Страница подтверждения email | `/verify-email` |
| `FRONTEND_RESET_PASSWORD_PATH` | Страница нового пароля | `/reset-password` |
| `EMAIL_VERIFICATION_TTL_HOURS` | Срок ссылки подтверждения email, часы | `24` |
| `PASSWORD_RESET_TTL_MINUTES` | Срок ссылки восстановления пароля, минуты | `60` |
| `EMAIL_RESEND_COOLDOWN_SECONDS` | Минимальный интервал между письмами на один адрес | `60` |
| `MAIL_BACKEND` | `console` (письма в лог) или `resend` | `console` |
| `MAIL_FROM` | Отправитель | `Research Platform <onboarding@resend.dev>` |
| `RESEND_API_KEY` | API-ключ Resend (обязателен при `MAIL_BACKEND=resend`) | — |
| `S3_ENDPOINT_URL` | Адрес S3-хранилища для API | `http://localhost:9000` |
| `S3_PUBLIC_ENDPOINT_URL` | Адрес хранилища, доступный браузеру (для временных ссылок) | `http://localhost:9000` |
| `S3_ACCESS_KEY` / `S3_SECRET_KEY` | Ключи доступа к хранилищу | `research` / `research-secret` |
| `S3_REGION` | Регион | `us-east-1` |
| `S3_BUCKET` | Бакет для файлов | `research-files` |
| `S3_AUTO_CREATE_BUCKET` | Создавать бакет при старте | `true` |
| `S3_PRESIGNED_URL_TTL_SECONDS` | Срок действия ссылки на файл, секунды | `3600` |
| `AVATAR_MAX_SIZE_MB` | Максимальный размер фото профиля, МБ | `5` |
| `FRONTEND_INVITATIONS_PATH` | Страница приглашений (ссылка в письме-приглашении) | `/invitations` |
| `INVITATION_TTL_DAYS` | Срок действия приглашения в проект, дни | `7` |

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

Неизвестные поля в теле запроса не игнорируются — возвращается `422` с кодом поля `NOT_ALLOWED`.

### Авторизация

- `POST /auth/register`, `POST /auth/login` возвращают `{"accessToken", "tokenType", "expiresIn"}` и ставят refresh-токен в httpOnly cookie.
- Access-токен передаётся в заголовке `Authorization: Bearer <token>`, живёт 15 минут.
- При ответе `401` — один раз вызвать `POST /auth/refresh` (cookie отправляется автоматически), при неудаче — на страницу входа.
- `GET /me` — текущий пользователь, роль, язык, подтверждён ли email.
- Подтверждение email: ссылка из письма ведёт на `FRONTEND_URL/verify-email?token=...`, фронтенд отправляет токен на `POST /auth/verify-email/confirm`.
- Восстановление пароля: `POST /auth/password/forgot` → письмо со ссылкой на `FRONTEND_URL/reset-password?token=...` → `POST /auth/password/reset`.

### Роли и права

- Системные роли: `researcher` (по умолчанию при регистрации), `supervisor`, `admin`. Роль `supervisor` назначает администратор в админ-панели.
- Права проверяются на сервере на каждом запросе; роль и блокировка вступают в силу сразу, без повторного входа.
- Нет права читать объект — `404` (не раскрываем, что объект существует); объект виден, но действие запрещено — `403`.
- Заблокированный пользователь получает `403 ACCOUNT_DISABLED` на любой запрос.

### Админ-панель (`/admin`)

- Пользователи: поиск, фильтр по роли и активности, редактирование данных, назначение роли, блокировка. Пользователей не удаляют — блокируют.
- Журнал действий: только просмотр.
- Администратор не может снять роль или заблокировать сам себя.

### Журнал действий

Значимые действия записываются в таблицу `audit_logs`: кто, что, над каким объектом, какие поля изменились (`{"поле": [старое, новое]}`), IP. Пароли и токены в журнал не пишутся. Запись сохраняется в той же транзакции, что и само изменение.

### Проекты и участники

Пользователь видит только проекты, в которых участвует. Роли в проекте:

| Действие | owner | editor | supervisor | viewer |
|---|:-:|:-:|:-:|:-:|
| Видеть проект и материалы | ✓ | ✓ | ✓ | ✓ |
| Редактировать проект и материалы | ✓ | ✓ | | |
| Приглашать, менять роли, удалять участников | ✓ | | | |
| Архивировать, восстанавливать, удалять проект | ✓ | | | |

- Архивный проект — только для чтения, пока его не восстановят.
- Удаление проекта удаляет все связанные данные без возможности восстановления.
- Приглашение: владелец указывает email и роль → письмо со ссылкой на `FRONTEND_URL/invitations`. Зарегистрированный пользователь видит приглашение в `GET /invitations`; незарегистрированный — после регистрации с этим email. Принять можно только с подтверждённым email. Приглашение действует `INVITATION_TTL_DAYS` дней.
- Приглашённый руководителем (`supervisor`) получает системную роль `supervisor`.

### Научные работы

`/projects/{projectId}/works` — работы проекта (в проекте может быть несколько работ). Владелец, редакторы и наблюдатели видят все работы проекта; руководитель (`supervisor`) — только работы, где он указан руководителем. Создают и редактируют владелец и редакторы.

- Типы (`type`): `article`, `research`, `coursework`, `diploma`, `master_thesis`, `dissertation`, `theses`, `conference_paper`, `custom` (свой тип — название в `customTypeName`).
- Авторы (`authors`): список, первый — автор, остальные — соавторы. Каждый элемент — `{"userId"}` (участник проекта) или `{"fullName"}` (человек не на платформе). По умолчанию автор — создатель работы.
- Руководитель: `supervisorId` (участник проекта с ролью `supervisor`) или `supervisorName` (если руководитель не на платформе).
- Сроки: `startDate`, `endDate` (`YYYY-MM-DD`).
- Фильтры: `type`, `search` (название, тема, описание); сортировка: `createdAt`, `updatedAt`, `title`, `startDate`, `endDate`.

### Этапы (roadmap)

`/projects/{projectId}/works/{workId}/stages` — этапы научной работы (по решению команды этапы у каждой работы, а не у проекта).

Статусы: `not_started`, `in_progress`, `pending_review`, `needs_revision`, `completed`, `rejected`.

| Кто | Переход |
|---|---|
| Исследователь (owner/editor) | `not_started → in_progress` (если этап не заблокирован) |
| | `in_progress → pending_review` (если у работы есть руководитель на платформе) |
| | `in_progress → completed` (необязательный этап, или у работы нет руководителя) |
| | `needs_revision → in_progress` / `needs_revision → pending_review` |
| Руководитель работы | `pending_review → completed` / `needs_revision` / `rejected` |
| | `rejected → needs_revision` (пересмотреть отказ) |

- Обязательный незавершённый этап блокирует все этапы после него: `isBlocked`, `blockedBy` (какой этап и в каком статусе).
- `availableTransitions` — статусы, в которые текущий пользователь может перевести этап (для кнопок).
- `rejected` — отказ в принятии этапа; руководитель может пересмотреть его и вернуть этап на доработку. `completed` — окончательный.
- Обязательность можно поменять, а обязательный этап удалить — только пока он не начат.
- Смена статуса: `POST .../stages/{id}/status` `{"status", "comment"}`; история: `GET .../stages/{id}/history`; порядок: `PUT .../stages/order` `{"stageIds": [...]}`.

**Прогресс** (`progress: {completed, total, percent}`): у работы — завершённые этапы / все этапы работы; у проекта — завершённые этапы всех работ / все этапы всех работ. Для руководителя прогресс проекта считается только по его работам.

### Профиль

- `GET /me` — профиль; `PATCH /me` — изменить (передаются только изменяемые поля, `null` очищает необязательное поле).
- `POST /me/email` — сменить email (нужен текущий пароль; новый email нужно подтвердить).
- `PUT /me/avatar` (multipart, поле `file`) — загрузить фото, `DELETE /me/avatar` — удалить.
- `avatarUrl` — временная ссылка на фото (действует `S3_PRESIGNED_URL_TTL_SECONDS`), её не нужно сохранять: при каждом `GET /me` выдаётся новая.

### Файлы

Файлы хранятся в приватном S3-хранилище, прямого доступа к нему нет. Бэкенд проверяет права и выдаёт временную ссылку. Тип файла проверяется по содержимому, а не по расширению.

### Почта

Пока `MAIL_BACKEND=console`, письма не отправляются, а выводятся в лог API (`docker compose logs api`).
Для отправки через Resend: `MAIL_BACKEND=resend` и `RESEND_API_KEY`. В тестовом режиме Resend (без подтверждённого домена) письма доходят только на email владельца аккаунта Resend.

## Структура backend

```
backend/app/
  core/       — общее: настройки, БД, ошибки, пагинация, логирование
  api.py      — подключение роутеров модулей
  main.py     — точка входа
```

Каждый модуль (accounts, projects, stages, ...) — отдельная папка с одинаковой структурой:
`models.py`, `schemas.py`, `repository.py`, `service.py`, `router.py`, `permissions.py`, `dependencies.py`, `exceptions.py`.
