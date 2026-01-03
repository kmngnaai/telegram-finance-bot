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
# TELEGRAM APP
# =========================
application = ApplicationBuilder().token(BOT_TOKEN).build()

# =========================
# FASTAPI
# =========================
@asynccontextmanager
async def lifespan(app: FastAPI):
    await application.initialize()
    await application.start()
    yield
    await application.stop()

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
# STATE
# =========================
USER_MODE = {}  # username -> "IN" | "OUT"

# =========================
# COMMANDS
# =========================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    USER_MODE.pop(update.message.from_user.username, None)
    await update.message.reply_text("👋 Chào bạn!", reply_markup=MAIN_KEYBOARD)

async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📘 CÁCH NHẬP\n\n"
        "20K CF\n"
        "+1M LUONG\n"
        "50K ĂN TRƯA\n\n"
        "👉 Mỗi dòng = 1 giao dịch",
        reply_markup=MAIN_KEYBOARD,
    )

# =========================
# BUTTON MODE
# =========================
async def set_income(update: Update, context: ContextTypes.DEFAULT_TYPE):
    USER_MODE[update.message.from_user.username] = "IN"
    await update.message.reply_text("➕ Đang ghi THU")

async def set_expense(update: Update, context: ContextTypes.DEFAULT_TYPE):
    USER_MODE[update.message.from_user.username] = "OUT"
    await update.message.reply_text("➖ Đang ghi CHI")

# =========================
# PARSE
# =========================
def parse_amount(text: str, mode: str) -> int:
    text = text.upper().replace(",", "")
    sign = 1 if mode == "IN" else -1

    if text.startswith("+"):
        sign = 1
        text = text[1:]
    elif text.startswith("-"):
        sign = -1
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
# MESSAGE HANDLER (MULTI-LINE)
# =========================
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.message.from_user.username or "unknown"
    mode = USER_MODE.get(user)

    if not mode:
        await update.message.reply_text("⚠️ Chọn ➕ Ghi thu hoặc ➖ Ghi chi trước")
        return

    lines = update.message.text.strip().splitlines()
    success = 0
    failed = []

    for line in lines:
        try:
            parts = line.strip().split(maxsplit=1)
            amount = parse_amount(parts[0], mode)
            category = parts[1] if len(parts) > 1 else "KHÁC"
            append_expense(date.today(), user, amount, category)
            success += 1
        except Exception:
            failed.append(line)

    msg = f"✅ Ghi thành công: {success} dòng"
    if failed:
        msg += "\n❌ Lỗi:\n" + "\n".join(failed)

    await update.message.reply_text(msg, reply_markup=MAIN_KEYBOARD)

# =========================
# REPORTS
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
# HANDLERS
# =========================
application.add_handler(CommandHandler("start", start))
application.add_handler(CommandHandler("help", help_cmd))
application.add_handler(CommandHandler("year", year_report))
application.add_handler(MessageHandler(filters.Regex("^➕ Ghi thu$"), set_income))
application.add_handler(MessageHandler(filters.Regex("^➖ Ghi chi$"), set_expense))
application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

# =========================
# WEBHOOK
# =========================
@fastapi_app.post("/webhook")
async def webhook(req: Request):
    update = Update.de_json(await req.json(), application.bot)
    await application.process_update(update)
    return {"ok": True}
