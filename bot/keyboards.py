"""Inline and reply keyboard helpers."""

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup

# ------------------------------------------------------------------ #
# Main menu (MVP)
# ------------------------------------------------------------------ #

MAIN_MENU_KB = ReplyKeyboardMarkup(
    [
        ["📅 Сегодня", "🎯 Цель"],
        ["👤 Профиль", "🔗 Подключить"],
        ["📆 История", "🔄 Синхронизация"],
        ["⚙️ Настройки"],
    ],
    resize_keyboard=True,
    input_field_placeholder="Выберите действие…",
)


# ------------------------------------------------------------------ #
# Goal selection
# ------------------------------------------------------------------ #

GOAL_KB = InlineKeyboardMarkup(
    [
        [InlineKeyboardButton("🏃 10 км за 60 мин", callback_data="ob_goal:run_10k_60")],
        [InlineKeyboardButton("🏃 Полумарафон за 2:20", callback_data="ob_goal:run_half_220")],
        [InlineKeyboardButton("🏃 Марафон — финишировать", callback_data="ob_goal:run_marathon_finish")],
    ]
)

# Separate keyboard for profile goal change (different prefix to avoid onboarding conflict)
PROFILE_GOAL_KB = InlineKeyboardMarkup(
    [
        [InlineKeyboardButton("🏃 10 км за 60 мин", callback_data="set_goal:run_10k_60")],
        [InlineKeyboardButton("🏃 Полумарафон за 2:20", callback_data="set_goal:run_half_220")],
        [InlineKeyboardButton("🏃 Марафон — финишировать", callback_data="set_goal:run_marathon_finish")],
    ]
)


# ------------------------------------------------------------------ #
# Workout feedback
# ------------------------------------------------------------------ #

def workout_feedback_keyboard(workout_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("✅ Сделал", callback_data=f"workout:done:{workout_id}"),
                InlineKeyboardButton("❌ Не сделал", callback_data=f"workout:skipped:{workout_id}"),
            ]
        ]
    )


# ------------------------------------------------------------------ #
# Plan type selection (legacy — kept for existing plan handlers)
# ------------------------------------------------------------------ #

def plan_type_keyboard(sport: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "📅 Недельный план", callback_data=f"plan:weekly:{sport}"
                ),
                InlineKeyboardButton(
                    "🎯 Одна тренировка", callback_data=f"plan:session:{sport}"
                ),
            ],
            [
                InlineKeyboardButton(
                    "📋 Последний план", callback_data=f"plan:last:{sport}"
                ),
            ],
        ]
    )


# ------------------------------------------------------------------ #
# Sync menu
# ------------------------------------------------------------------ #

SYNC_KB = InlineKeyboardMarkup(
    [
        [
            InlineKeyboardButton("⌚ Синхр. Garmin", callback_data="sync:garmin"),
            InlineKeyboardButton("💍 Синхр. WHOOP", callback_data="sync:whoop"),
        ],
        [InlineKeyboardButton("🔄 Синхр. оба", callback_data="sync:all")],
        [InlineKeyboardButton("📅 История WHOOP 4 недели", callback_data="sync:whoop_history")],
        [InlineKeyboardButton("⌚ История Garmin 4 недели", callback_data="sync:garmin_history")],
    ]
)


# ------------------------------------------------------------------ #
# Settings menu
# ------------------------------------------------------------------ #

SETTINGS_KB = InlineKeyboardMarkup(
    [
        [InlineKeyboardButton("⌚ Настроить Garmin", callback_data="settings:garmin")],
        [InlineKeyboardButton("💍 Подключить WHOOP", callback_data="settings:whoop")],
        [InlineKeyboardButton("ℹ️ Статус подключений", callback_data="settings:status")],
    ]
)


# ------------------------------------------------------------------ #
# Back button
# ------------------------------------------------------------------ #

def back_keyboard(callback: str = "back:main") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton("⬅️ Назад", callback_data=callback)]]
    )
