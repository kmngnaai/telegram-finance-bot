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
BTN_IN = "➕ Ghi thu"
BTN_OUT = "➖ Ghi chi"
BTN_DAY = "📊 Tổng kết ngày"
BTN_MONTH = "📅 Tổng kết tháng"
BTN_YEAR = "📈 Tổng kết năm"

MAIN_KEYBOARD = ReplyKeyboardMarkup(
    [
        [BTN_IN, BTN_OUT],
        [BTN_DAY, BTN_MONTH],
        [BTN_YEAR, "ℹ️ Help"],
    ],
    resize_keyboard=True,
)

# =========================
# STATE (OPTIONAL)
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
        "20K CF  → Chi\n"
        "+1M LUONG → Thu\n"
        "20K CF\\n+1M LUONG → 2 dòng\n\n"
        "👉 Không cần chọn trước",
        reply_markup=MAIN_KEYBOARD,
    )

# =========================
# MODE BUTTONS (TÙY CHỌN)
# =========================
async def set_income(update: Update, context: ContextTypes.DEFAULT_TYPE):
    USER_MODE[update.message.from_user.username] = "IN"
    await update.message.reply_text("➕ Mặc định ghi THU")

async def set_expense(update: Update, context: ContextTypes.DEFAULT_TYPE):
    USER_MODE[update.message.from_user.username] = "OUT"
    await update.message.reply_text("➖ Mặc định ghi CHI")

# =========================
# PARSE
# =========================
def parse_amount(token: str, mode: str | None) -> int:
    token = token.upper().replace(",", "")

    if token.startswith("+"):
        sign = 1
        token = token[1:]
    elif token.startswith("-"):
        sign = -1
        token = token[1:]
    else:
        sign = 1 if mode == "IN" else -1  # mặc định CHI

    m = re.match(r"(\d+)(K|M)?$", token)
    if not m:
        raise ValueError

    value = int(m.group(1))
    if m.group(2) == "K":
        value *= 1_000
    elif m.group(2) == "M":
        value *= 1_000_000

    return sign * value

# =========================
# HANDLE MONEY (MULTI-LINE)
# =========================
async def handle_money(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.message.from_user.username or "unknown"
    mode = USER_MODE.get(user)

    lines = update.message.text.strip().splitlines()
    ok = 0
    bad = []

    for line in lines:
        try:
            parts = line.split(maxsplit=1)
            amount = parse_amount(parts[0], mode)
            category = parts[1] if len(parts) > 1 else "KHÁC"
            append_expense(date.today(), user, amount, category)
            ok += 1
        except Exception:
            bad.append(line)

    msg = f"✅ Ghi thành công: {ok} dòng"
    if bad:
        msg += "\n❌ Lỗi:\n" + "\n".join(bad)

    await update.message.reply_text(msg, reply_markup=MAIN_KEYBOARD)

# =========================
# REPORTS
# =========================
async def report_day(update: Update, context: ContextTypes.DEFAULT_TYPE):
    today = date.today().isoformat()
    rows = get_all_rows()
    thu = chi = 0

    for r in rows:
        if r["date"] == today:
            if r["amount"] >= 0:
                thu += r["amount"]
            else:
                chi += abs(r["amount"])

    await update.message.reply_text(
        f"📊 TỔNG KẾT NGÀY\n💰 Thu: {thu:,}\n💸 Chi: {chi:,}\n📌 Còn: {thu-chi:,}",
        reply_markup=MAIN_KEYBOARD,
    )

async def report_month(update: Update, context: ContextTypes.DEFAULT_TYPE):
    key = date.today().strftime("%Y-%m")
    rows = get_all_rows()
    thu = chi = 0

    for r in rows:
        if r["date"].startswith(key):
            if r["amount"] >= 0:
                thu += r["amount"]
            else:
                chi += abs(r["amount"])

    await update.message.reply_text(
        f"📅 TỔNG KẾT THÁNG\n💰 Thu: {thu:,}\n💸 Chi: {chi:,}\n📌 Còn: {thu-chi:,}",
        reply_markup=MAIN_KEYBOARD,
    )

async def report_year(update: Update, context: ContextTypes.DEFAULT_TYPE):
    year = date.today().strftime("%Y")
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
# HANDLERS ORDER (RẤT QUAN TRỌNG)
# =========================
application.add_handler(CommandHandler("start", start))
application.add_handler(CommandHandler("help", help_cmd))

application.add_handler(MessageHandler(filters.Regex(f"^{BTN_IN}$"), set_income))
application.add_handler(MessageHandler(filters.Regex(f"^{BTN_OUT}$"), set_expense))

application.add_handler(MessageHandler(filters.Regex(f"^{BTN_DAY}$"), report_day))
application.add_handler(MessageHandler(filters.Regex(f"^{BTN_MONTH}$"), report_month))
application.add_handler(MessageHandler(filters.Regex(f"^{BTN_YEAR}$"), report_year))

# ⚠️ CUỐI CÙNG MỚI BẮT GIAO DỊCH
application.add_handler(
    MessageHandler(filters.TEXT & filters.Regex(r"^[+\-]?\d"), handle_money)
)

# =========================
# WEBHOOK
# =========================
@fastapi_app.post("/webhook")
async def webhook(req: Request):
    update = Update.de_json(await req.json(), application.bot)
    await application.process_update(update)
    return {"ok": True}
