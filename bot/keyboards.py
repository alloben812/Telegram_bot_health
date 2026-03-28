"""Inline and reply keyboard helpers."""

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup

# ------------------------------------------------------------------ #
# Main menu
# ------------------------------------------------------------------ #

MAIN_MENU_KB = ReplyKeyboardMarkup(
    [
        ["📊 Статистика", "💤 Восстановление"],
        ["🏃 Бег", "🚴 Велосипед"],
        ["🏊 Плавание", "💪 Силовые"],
        ["🔄 Синхронизация", "⚙️ Настройки"],
    ],
    resize_keyboard=True,
    input_field_placeholder="Выберите действие…",
)


# ------------------------------------------------------------------ #
# Plan type selection
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
        [
            InlineKeyboardButton(
                "⌚ Настроить Garmin", callback_data="settings:garmin"
            )
        ],
        [
            InlineKeyboardButton(
                "💍 Подключить WHOOP", callback_data="settings:whoop"
            )
        ],
        [
            InlineKeyboardButton(
                "ℹ️ Статус подключений", callback_data="settings:status"
            )
        ],
    ]
)


# ------------------------------------------------------------------ #
# Back button
# ------------------------------------------------------------------ #

def back_keyboard(callback: str = "back:main") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton("⬅️ Назад", callback_data=callback)]]
    )
