import os
from dotenv import load_dotenv

load_dotenv()


class Config:
    # Telegram
    TELEGRAM_BOT_TOKEN: str = os.getenv("TELEGRAM_BOT_TOKEN", "")
    ADMIN_TELEGRAM_ID: int = int(os.getenv("ADMIN_TELEGRAM_ID", "0"))

    # Garmin Connect
    GARMIN_EMAIL: str = os.getenv("GARMIN_EMAIL", "")
    GARMIN_PASSWORD: str = os.getenv("GARMIN_PASSWORD", "")

    # WHOOP OAuth 2.0
    WHOOP_CLIENT_ID: str = os.getenv("WHOOP_CLIENT_ID", "")
    WHOOP_CLIENT_SECRET: str = os.getenv("WHOOP_CLIENT_SECRET", "")
    WHOOP_REDIRECT_URI: str = os.getenv("WHOOP_REDIRECT_URI", "")
    WHOOP_AUTH_URL: str = "https://api.prod.whoop.com/oauth/oauth2/auth"
    WHOOP_TOKEN_URL: str = "https://api.prod.whoop.com/oauth/oauth2/token"
    WHOOP_API_BASE: str = "https://api.prod.whoop.com/developer/v1"

    # Anthropic
    ANTHROPIC_API_KEY: str = os.getenv("ANTHROPIC_API_KEY", "")
    CLAUDE_MODEL: str = "claude-sonnet-4-6"

    # Database
    DATABASE_URL: str = os.getenv(
        "DATABASE_URL", "sqlite+aiosqlite:///./health_bot.db"
    )


config = Config()
