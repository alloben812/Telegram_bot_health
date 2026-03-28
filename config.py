import os
from dotenv import load_dotenv

load_dotenv()


class Config:
    # Telegram
    TELEGRAM_BOT_TOKEN: str = os.getenv("TELEGRAM_BOT_TOKEN", "")
    ADMIN_TELEGRAM_ID: int = int(os.getenv("ADMIN_TELEGRAM_ID", "0"))

    # Encryption key for sensitive DB fields (Garmin password, WHOOP tokens)
    SECRET_KEY: str = os.getenv("SECRET_KEY", "")

    # Garmin Connect (used as defaults; per-user credentials override these)
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

    def validate(self) -> None:
        """Raise on missing required keys so the bot fails fast at startup."""
        required = {
            "TELEGRAM_BOT_TOKEN": self.TELEGRAM_BOT_TOKEN,
            "ADMIN_TELEGRAM_ID": self.ADMIN_TELEGRAM_ID,
            "SECRET_KEY": self.SECRET_KEY,
        }
        missing = [k for k, v in required.items() if not v]
        if missing:
            raise EnvironmentError(
                f"Missing required environment variables: {', '.join(missing)}\n"
                "Copy .env.example → .env and fill in all values."
            )
        if self.ADMIN_TELEGRAM_ID == 0:
            raise EnvironmentError(
                "ADMIN_TELEGRAM_ID must be set to your Telegram user ID.\n"
                "Find it by messaging @userinfobot on Telegram."
            )
        if len(self.SECRET_KEY) < 32:
            raise EnvironmentError(
                "SECRET_KEY is too short (minimum 32 characters).\n"
                "Generate one with: python -c \"import secrets; print(secrets.token_hex(32))\""
            )


config = Config()
