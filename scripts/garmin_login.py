#!/usr/bin/env python
"""
One-time Garmin login script.

Run this ONCE from Terminal to create the token cache.
After that, the bot will use cached tokens and never hit SSO again
(garth auto-refreshes OAuth2 using the refresh token silently).

Usage:
    cd /Users/alloben/Applications/Telegram_bot_health
    venv/bin/python scripts/garmin_login.py
"""
import sys
import os
from pathlib import Path

# Make sure project root is on the path
sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv()

import garminconnect
import getpass

email = os.getenv("GARMIN_EMAIL", "").strip()
password = os.getenv("GARMIN_PASSWORD", "").strip()

if not email:
    email = input("Garmin email: ").strip()
if not password:
    password = getpass.getpass("Garmin password: ")

print(f"\nЛогинимся как {email} ...")
print("(это единственный запрос к SSO — потом будем использовать кеш)\n")

safe = email.replace("@", "_at_").replace(".", "_")
cache_dir = Path(__file__).parent.parent / ".garth_cache" / safe

try:
    client = garminconnect.Garmin(email, password)
    client.login()
    cache_dir.mkdir(parents=True, exist_ok=True)
    client.garth.dump(str(cache_dir))
    print(f"✅ Токены сохранены в: {cache_dir}")
    print("\nПроверяем подключение...")
    name = client.get_full_name()
    print(f"✅ Авторизован как: {name}")
    print("\n🎉 Готово! Теперь запускай бота — Garmin будет работать без SSO.")
except Exception as exc:
    if "429" in str(exc):
        print("❌ Garmin вернул 429 — SSO временно заблокирован.")
        print("   Подожди 60 минут и попробуй снова.")
        print(f"   Полная ошибка: {exc}")
    else:
        print(f"❌ Ошибка: {exc}")
    sys.exit(1)
