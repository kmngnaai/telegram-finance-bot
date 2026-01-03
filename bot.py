import os
import re
from datetime import date
from collections import defaultdict
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import (
    Application,
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

from google_sheet_store import append_expense, get_all_rows

# =========================
# CONFIG
# =========================
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
if not BOT_TOKEN:
    raise RuntimeError("Missing TELEGRAM_BOT_TOKEN")

OWNER_USERNAME = "ltkngan198"

# =========================
# TELEGRAM APPLICATION
# =========================
application: Application = ApplicationBuilder().token(BOT_TOKEN).build()

# =========================
# FASTAPI LIFESPAN (QUAN TRỌNG)
# =========================
@asynccontextmanager
async def lifespan(app: FastAPI):
    # STARTUP
    await application.initialize()
    await application.start()
    print("✅ Telegram Application started")

    yield

    # SHUTDOWN
    await application.stop()
    print("🛑 Telegram Application stopped")

fastapi_app = FastAPI(lifespan=lifespan)

# =========================
# KEYBOARD
# =========================
MAIN_KEYBOARD = ReplyKeyboardMarkup(
    [
        [KeyboardButton("➕ Ghi thu"), KeyboardButton("➖ Ghi chi")],
        [KeyboardButton("📊 Tổng kết ngày"), KeyboardButton("📅 Tổng kết tháng")],
        [KeyboardButton("📈 Tổng kết năm"), KeyboardButton("ℹ️ Help")],
    ],
    resize_keyboard=True,
)

# =========================
# COMMANDS
# =========================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 Chào bạn!\nChọn chức năng bên dưới 👇",
        reply_markup=MAIN_KEYBOARD,
    )

async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📘 HƯỚNG DẪN\n\n"
        "20K CF\n"
        "+1M LUONG\n\n"
        "/summary 20260101\n"
        "/summary 202601\n"
        "/year 2026",
        reply_markup=MAIN_KEYBOARD,
    )

# =========================
# PARSE AMOUNT
# =========================
def parse_amount(text: str) -> int:
    text = text.upper().replace(",", "")
    sign = -1
    if text.startswith("+"):
        sign = 1
        text = text[1:]

    m = re.match(r"(\d+)(K|M)?", text)
    if not m:
        raise ValueError

    value = int(m.group(1))
    if m.group(2) == "K":
        value *= 1_000
    elif m.group(2) == "M":
        value *= 1_000_000

    return sign * value

# =========================
# MESSAGE HANDLER
# =========================
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        text = update.message.text.strip()
        user = update.message.from_user.username or "unknown"

        parts = text.split(maxsplit=1)
        amount = parse_amount(parts[0])
        category = parts[1] if len(parts) > 1 else "KHÁC"

        append_expense(date.today(), user, amount, category)

        await update.message.reply_text(
            f"✅ Đã ghi\n{amount:,} đ\n{category}",
            reply_markup=MAIN_KEYBOARD,
        )
    except Exception:
        await update.message.reply_text(
            "❌ Sai định dạng\nVí dụ: 20K CF | +1M LUONG",
            reply_markup=MAIN_KEYBOARD,
        )

# =========================
# SUMMARY
# =========================
async def summary(update: Update, context: ContextTypes.DEFAULT_TYPE):
    key = context.args[0]
    rows = get_all_rows()

    thu = chi = 0
    for r in rows:
        if r["date"].replace("-", "").startswith(key):
            if r["amount"] >= 0:
                thu += r["amount"]
            else:
                chi += abs(r["amount"])

    await update.message.reply_text(
        f"📊 TỔNG KẾT\n"
        f"💰 Thu: {thu:,}\n"
        f"💸 Chi: {chi:,}\n"
        f"📌 Còn: {thu - chi:,}",
        reply_markup=MAIN_KEYBOARD,
    )

# =========================
# YEAR REPORT
# =========================
async def year_report(update: Update, context: ContextTypes.DEFAULT_TYPE):
    year = context.args[0]
    rows = get_all_rows()
    by_month = defaultdict(lambda: {"in": 0, "out": 0})

    for r in rows:
        if r["date"].startswith(year):
            m = r["date"][5:7]
            if r["amount"] >= 0:
                by_month[m]["in"] += r["amount"]
            else:
                by_month[m]["out"] += abs(r["amount"])

    text = f"📈 BÁO CÁO NĂM {year}\n\n"
    for m in sorted(by_month):
        i = by_month[m]["in"]
        o = by_month[m]["out"]
        text += f"• Tháng {m}: Thu {i:,} | Chi {o:,} | Còn {i-o:,}\n"

    await update.message.reply_text(text, reply_markup=MAIN_KEYBOARD)

# =========================
# REGISTER HANDLERS
# =========================
application.add_handler(CommandHandler("start", start))
application.add_handler(CommandHandler("help", help_cmd))
application.add_handler(CommandHandler("summary", summary))
application.add_handler(CommandHandler("year", year_report))
application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

# =========================
# WEBHOOK
# =========================
@fastapi_app.post("/webhook")
async def telegram_webhook(request: Request):
    data = await request.json()
    update = Update.de_json(data, application.bot)
    await application.process_update(update)
    return {"ok": True}
