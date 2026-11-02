import os
import time
from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import FileResponse
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from app import database
from app.auth import AuthError, validate_init_data

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")
LANGUAGES = {"kk", "ru", "en", "tr", "uz", "ky", "de", "es"}


@asynccontextmanager
async def lifespan(app: FastAPI):
    database.initialize()
    yield


app = FastAPI(lifespan=lifespan)
app.mount("/static", StaticFiles(directory=ROOT / "static"), name="static")


@app.get("/")
def index():
    return FileResponse(ROOT / "static" / "index.html")


def authenticated_user(init_data: str):
    token = os.getenv("BOT_TOKEN", "").strip()
    if not token:
        raise HTTPException(status_code=503, detail="Bot token is not configured")
    try:
        return validate_init_data(init_data, token)
    except AuthError:
        raise HTTPException(status_code=401, detail="Invalid or expired Telegram data") from None


@app.get("/api/settings")
def get_settings(x_telegram_init_data: str = Header(default="")):
    user = authenticated_user(x_telegram_init_data)
    language = database.get_language(user["id"])
    telegram_language = user.get("language_code", "")
    telegram_language = telegram_language.lower().split("-")[0] if isinstance(telegram_language, str) else ""
    return JSONResponse({"language": language if language in LANGUAGES else telegram_language if telegram_language in LANGUAGES else "ru"}, headers={"Cache-Control": "no-store"})


@app.get("/api/account")
def get_account(x_telegram_init_data: str = Header(default="")):
    user = authenticated_user(x_telegram_init_data)
    view = database.subscription_view(user["id"])
    return JSONResponse({"subscription": view["subscription"], "source": view["source"],
                         "vpn": view["vpn"], "server_time": int(time.time())},
                        headers={"Cache-Control": "no-store"})


class Settings(BaseModel):
    language: str


@app.put("/api/settings")
def put_settings(settings: Settings, x_telegram_init_data: str = Header(default="")):
    user = authenticated_user(x_telegram_init_data)
    if settings.language not in LANGUAGES:
        raise HTTPException(status_code=400, detail="Unsupported language")
    database.save_language(user["id"], settings.language)
    return JSONResponse({"language": settings.language}, headers={"Cache-Control": "no-store"})
