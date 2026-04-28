# Telegram Health & Training Bot

Персональный ежедневный тренировочный ассистент в Telegram с интеграцией **Garmin Connect** и **WHOOP**, работающий на базе **OpenAI GPT-4o**.

## Возможности

- 📅 **Рекомендация на сегодня** — AI анализирует данные восстановления и строит персонализированный план тренировки
- 🎯 **Беговые цели** — выбор и смена пресетов (10 км, полумарафон, марафон)
- 👤 **Профиль спортсмена** — максимальный пульс, дни тренировок, силовые дни/нед.
- 📆 **История** — последние 7 дней рекомендаций и тренировок
- ✅ **Фидбек** — кнопки «Сделал / Не сделал» после каждой тренировки
- 🔄 **Синхронизация** — загрузка данных с Garmin и WHOOP

## Стек технологий

| Компонент | Технология |
|---|---|
| Бот | `python-telegram-bot` v21 (async) |
| Garmin | `garminconnect` + `garth` (OAuth token cache) |
| WHOOP | WHOOP API v1 (OAuth 2.0) |
| AI-планировщик | OpenAI GPT-4o за `AIProvider` абстракцией |
| База данных | SQLite (dev) / Neon Postgres (prod) + SQLAlchemy async |
| Деплой | Render Free Web Service (webhook) |

## Структура проекта

```
Telegram_bot_health/
├── ai/
│   ├── provider.py          # Абстракция AIProvider
│   ├── openai_provider.py   # OpenAI реализация
│   └── schemas.py           # Pydantic-схемы (DailyRecommendation, PlannedWorkout)
├── bot/
│   ├── main.py              # Точка входа, регистрация хэндлеров
│   ├── auth.py              # AuthMiddleware (только ADMIN_TELEGRAM_ID)
│   ├── keyboards.py         # Главное меню, Goal KB, Workout feedback KB
│   ├── scheduler.py         # Cron-джобы: утренний push, авто-синк 4x/день
│   └── handlers/
│       ├── onboarding.py    # /start, ConversationHandler (4 шага)
│       ├── today.py         # 📅 Сегодня — AI рекомендация
│       ├── history.py       # 📆 История — последние 7 дней
│       ├── profile.py       # 👤 Профиль, 🎯 Цель
│       ├── sync.py          # 🔄 Синхронизация Garmin/WHOOP
│       └── settings.py      # ⚙️ Настройки, подключение устройств
├── integrations/
│   ├── garmin.py            # Garmin Connect API (с garth token cache)
│   └── whoop.py             # WHOOP API (OAuth 2.0, auto-refresh)
├── training/
│   ├── planner.py           # TrainingPlanner, AthleteContext
│   ├── sports.py            # Нормализация спортов, дедупликация Garmin/WHOOP
│   └── goals.py             # GoalPreset пресеты (3 MVP цели)
├── web/
│   ├── routes.py            # FastAPI: healthcheck, WHOOP OAuth callback
│   ├── connect_tokens.py    # Токены подключения устройств
│   └── templates/
│       └── connect.html     # Web Connect UI для Garmin/WHOOP
├── database/
│   ├── models.py            # ORM-модели (User, Snapshot, Profile, Recommendation…)
│   └── db.py                # CRUD + шифрование токенов (Fernet)
├── security.py              # Fernet encryption (PBKDF2 от SECRET_KEY)
├── config.py                # Конфигурация из .env
├── run.py                   # Entrypoint (Telegram bot + FastAPI web server)
├── Dockerfile               # Python 3.12-slim, non-root user
├── render.yaml              # Render deployment blueprint
├── scripts/
│   ├── check_baseline.py    # Базовая проверка синтаксиса/импортов
│   └── garmin_login.py      # Ручная авторизация Garmin (при 429 cooldown)
├── requirements.txt
└── .env.example
```

## Быстрый старт

### 1. Клонируй репозиторий

```bash
git clone https://github.com/alloben812/Telegram_bot_health.git
cd Telegram_bot_health
```

### 2. Установи зависимости

```bash
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

### 3. Настрой переменные окружения

```bash
cp .env.example .env
```

Обязательные переменные:

| Переменная | Где взять |
|---|---|
| `TELEGRAM_BOT_TOKEN` | [@BotFather](https://t.me/BotFather) |
| `ADMIN_TELEGRAM_ID` | [@userinfobot](https://t.me/userinfobot) — твой числовой ID |
| `SECRET_KEY` | `python -c "import secrets; print(secrets.token_hex(32))"` |
| `OPENAI_API_KEY` | [platform.openai.com](https://platform.openai.com) |

Опциональные (подключаются через настройки бота):

| Переменная | Описание |
|---|---|
| `GARMIN_EMAIL` / `GARMIN_PASSWORD` | Аккаунт Garmin Connect |
| `WHOOP_CLIENT_ID` / `WHOOP_CLIENT_SECRET` | [developer.whoop.com](https://developer.whoop.com) |
| `WHOOP_REDIRECT_URI` | URL для OAuth redirect |

> **Важно:** `SECRET_KEY` нельзя менять после первого запуска — все зашифрованные поля в БД станут нечитаемы.

### 4. Запусти бота

```bash
python -m bot.main
```

## Деплой (Render + Neon Postgres)

Бот задеплоен на **Render** (Free Web Service) с базой данных **Neon Postgres**.

### Архитектура деплоя

- `run.py` запускает Telegram polling + FastAPI web server параллельно
- FastAPI обслуживает healthcheck (`/health`), WHOOP OAuth callback, Web Connect UI
- Render пингует `/health` для keep-alive
- БД: Neon Postgres (бесплатный tier), подключение через `asyncpg` + SSL
- Garmin OAuth токены хранятся зашифрованно в БД (не на файловой системе)

### Environment Variables на Render

Все обязательные переменные из таблицы выше + `DATABASE_URL` (Neon connection string).

### Ручной деплой

```bash
# Render деплоит автоматически при push в настроенную ветку
git push origin main
```

## Локальная проверка

```bash
venv/bin/python scripts/check_baseline.py
```

Проверяет синтаксис и импорт ключевых модулей без запуска бота и без вызовов внешних API.

## Главное меню бота

| Кнопка / Команда | Действие |
|---|---|
| `/start` | Онбординг (макс пульс → цель → дни → силовые) |
| `📅 Сегодня` | AI-рекомендация на день + план тренировки |
| `🎯 Цель` | Выбор/смена беговой цели |
| `👤 Профиль` | Просмотр профиля спортсмена |
| `🔗 Подключить` | Подключение устройств (Web Connect UI — Phase 5) |
| `📆 История` | Последние 7 дней рекомендаций |
| `🔄 Синхронизация` | Загрузить данные с Garmin и WHOOP |
| `⚙️ Настройки` | Учётные данные Garmin/WHOOP |

## Подключение устройств

### Garmin Connect
1. `⚙️ Настройки` → `⌚ Настроить Garmin`
2. Введи email и пароль от аккаунта Garmin Connect
3. Нажми `🔄 Синхронизация`

> При ошибке 429 (rate limit) запусти `python scripts/garmin_login.py` после cooldown.

### WHOOP
1. Зарегистрируй приложение на [developer.whoop.com](https://developer.whoop.com)
2. Укажи `Redirect URI`
3. `⚙️ Настройки` → `💍 Подключить WHOOP` → перейди по ссылке авторизации
4. После редиректа скопируй `code` из URL и отправь боту: `/whoop_code КОД`

## Статус разработки (Roadmap)

| Фаза | Статус | Содержание |
|---|---|---|
| Phase 0 | ✅ Merged (PR #8, #9) | Baseline hygiene |
| Phase 1 | ✅ Merged (PR #13) | AIProvider abstraction, OpenAI, Pydantic schemas |
| Phase 2 | ✅ Merged (PR #14) | Data models (Profile, Recommendation, WorkoutCompletion) |
| Phase 3 | ✅ Merged (PR #15, #16) | Telegram MVP: онбординг, Сегодня, История, Профиль |
| Phase 4 | ✅ Merged (PR #17) | Проактивный push 07:00, авто-синк 4x/день, HR зоны |
| **Pre-Phase 5** | ✅ Done | Render + Neon + WHOOP redirect URI |
| Phase 5 | ✅ Merged (PR #19) | FastAPI + Web Connect UI (Garmin, WHOOP OAuth) |
| Phase 6 | ✅ Merged (PR #20, #21) | Деплой: Render + Neon Postgres + Dockerfile |
| Phase 4+ | 🟡 In progress (PR #22) | AI quality: нормализация спортов, тренды, авто-детект тренировок |
| Phase 7 | ⬜ Planned | Hardening: логи, мониторинг, тесты |
