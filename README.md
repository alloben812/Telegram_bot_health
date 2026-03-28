# Telegram Health & Training Bot

Персональный тренировочный бот для Telegram с интеграцией **Garmin Connect** и **WHOOP**, работающий на базе **Claude AI**.

## Возможности

- 📊 **Статистика** — просмотр метрик активности, HRV, ЧСС покоя за последние 7 дней
- 💤 **Восстановление** — анализ WHOOP Recovery, качества сна и готовности к тренировкам
- 🏃 **Планы бега** — недельные планы и отдельные сессии, адаптированные под твоё состояние
- 🚴 **Планы велосипеда** — структурированные велосессии с зонами мощности
- 🏊 **Планы плавания** — тренировки по стилям с объёмом и интенсивностью
- 💪 **Силовые тренировки** — программы, учитывающие усталость и восстановление
- 🤖 **AI-тренер** — свободный диалог, ответы на вопросы о тренировках

## Стек технологий

| Компонент | Технология |
|---|---|
| Бот | `python-telegram-bot` v21 (async) |
| Garmin | `garminconnect` library |
| WHOOP | WHOOP API v1 (OAuth 2.0) |
| AI-планировщик | Anthropic Claude (`claude-sonnet-4-6`) |
| База данных | SQLite + SQLAlchemy (async) |

## Структура проекта

```
Telegram_bot_health/
├── bot/
│   ├── main.py              # Точка входа
│   ├── keyboards.py         # Клавиатуры
│   └── handlers/
│       ├── start.py         # /start, настройки, авторизация
│       ├── sync.py          # Синхронизация Garmin/WHOOP
│       ├── stats.py         # Статистика и восстановление
│       └── plans.py         # Тренировочные планы + AI Q&A
├── integrations/
│   ├── garmin.py            # Garmin Connect API
│   └── whoop.py             # WHOOP API (OAuth 2.0)
├── training/
│   └── planner.py           # AI-тренер (Claude)
├── database/
│   ├── models.py            # ORM-модели
│   └── db.py                # CRUD-операции
├── config.py                # Конфигурация из .env
├── requirements.txt
└── .env.example
```

## Быстрый старт

### 1. Клонируй репозиторий

```bash
git clone https://github.com/alloben812/telegram_bot_health.git
cd telegram_bot_health
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

Заполни `.env`:

| Переменная | Где взять |
|---|---|
| `TELEGRAM_BOT_TOKEN` | [@BotFather](https://t.me/BotFather) |
| `GARMIN_EMAIL` / `GARMIN_PASSWORD` | Аккаунт Garmin Connect |
| `WHOOP_CLIENT_ID` / `WHOOP_CLIENT_SECRET` | [developer.whoop.com](https://developer.whoop.com) |
| `WHOOP_REDIRECT_URI` | URL твоего сервера или ngrok |
| `ANTHROPIC_API_KEY` | [console.anthropic.com](https://console.anthropic.com) |

### 4. Запусти бота

```bash
python -m bot.main
```

## Подключение устройств

### Garmin Connect
1. Открой бота → ⚙️ Настройки → ⌚ Настроить Garmin
2. Введи email и пароль от аккаунта Garmin Connect
3. Нажми 🔄 Синхронизация → Garmin

### WHOOP
1. Зарегистрируй приложение на [developer.whoop.com](https://developer.whoop.com)
2. Укажи `Redirect URI` (например, через [ngrok](https://ngrok.com))
3. Открой бота → ⚙️ Настройки → 💍 Подключить WHOOP
4. Перейди по ссылке авторизации
5. После редиректа скопируй `code` из URL и отправь боту: `/whoop_code КОД`

## Команды бота

| Команда/Кнопка | Действие |
|---|---|
| `/start` | Приветствие и главное меню |
| `📊 Статистика` | Метрики за 7 дней |
| `💤 Восстановление` | Анализ восстановления + AI |
| `🏃 Бег` | Планы беговых тренировок |
| `🚴 Велосипед` | Планы вело-тренировок |
| `🏊 Плавание` | Планы по плаванию |
| `💪 Силовые` | Силовые программы |
| `🔄 Синхронизация` | Обновить данные с устройств |
| `⚙️ Настройки` | Подключение устройств |
| Любой текст | Вопрос AI-тренеру |
| `/whoop_code КОД` | Завершить авторизацию WHOOP |
