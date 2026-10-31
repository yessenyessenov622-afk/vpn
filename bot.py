import ipaddress
import os
import re
from pathlib import Path
from urllib.parse import urlsplit

from dotenv import load_dotenv
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update, WebAppInfo
from telegram.ext import Application, CommandHandler, ContextTypes


def valid_url(value: str) -> bool:
    try:
        url = urlsplit(value)
        host = url.hostname
        if url.scheme != "https" or not host or url.username or url.password or url.port not in (None, 443):
            return False
        if host.lower() == "localhost" or host.lower().endswith(".localhost") or "." not in host:
            return False
        try:
            return ipaddress.ip_address(host).is_global
        except ValueError:
            labels = host.rstrip(".").split(".")
            return len(host) <= 253 and all(re.fullmatch(r"[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?", label) for label in labels)
    except ValueError:
        return False


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type != "private":
        await update.message.reply_text("Откройте личный чат с ботом, чтобы запустить приложение.")
        return
    keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("Открыть приложение", web_app=WebAppInfo(url=context.bot_data["mini_app_url"]))]])
    await update.message.reply_text("Привет! Откройте приложение и выберите язык интерфейса.", reply_markup=keyboard)


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Сейчас доступны Mini App и выбор языка. VPN и подписки находятся в разработке. Используйте /start, чтобы открыть приложение.")


def main():
    load_dotenv(Path(__file__).resolve().parent / ".env")
    token = os.getenv("BOT_TOKEN", "").strip()
    url = os.getenv("MINI_APP_URL", "").strip()
    if not token:
        raise SystemExit("Ошибка конфигурации: укажите BOT_TOKEN в файле .env.")
    if not valid_url(url):
        raise SystemExit("Ошибка конфигурации: укажите в MINI_APP_URL публичный HTTPS-адрес приложения в файле .env.")
    application = Application.builder().token(token).build()
    application.bot_data["mini_app_url"] = url
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    print("Бот запущен. Для остановки нажмите Ctrl+C.")
    application.run_polling()


if __name__ == "__main__":
    main()
