import os
import re
from datetime import date, datetime
from collections import defaultdict
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from telegram import Update, ReplyKeyboardMarkup
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
BTN_DAY = "📊 Tổng kết ngày"
BTN_MONTH = "📅 Tổng kết tháng"
BTN_YEAR = "📈 Tổng kết năm"

MAIN_KEYBOARD = ReplyKeyboardMarkup(
    [[BTN_DAY, BTN_MONTH], [BTN_YEAR, "ℹ️ Help"]],
    resize_keyboard=True,
)

# =========================
# COMMANDS
# =========================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("👋 Chào bạn!", reply_markup=MAIN_KEYBOARD)

async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📘 HƯỚNG DẪN\n\n"
        "➕ Ghi sổ:\n"
        "20K CF\n"
        "+1M LUONG\n\n"
        "➕ Ghi theo ngày:\n"
        "20260101 20K CF\n\n"
        "📊 Báo cáo:\n"
        "/year 2026\n",
        reply_markup=MAIN_KEYBOARD,
    )

# =========================
# PARSE LINE
# =========================
def parse_line(line: str):
    parts = line.strip().split()

    if re.fullmatch(r"\d{8}", parts[0]):
        tx_date = datetime.strptime(parts[0], "%Y%m%d").date()
        amount_token = parts[1]
        category = " ".join(parts[2:]) if len(parts) > 2 else "KHÁC"
    else:
        tx_date = date.today()
        amount_token = parts[0]
        category = " ".join(parts[1:]) if len(parts) > 1 else "KHÁC"

    token = amount_token.upper().replace(",", "")

    sign = -1
    if token.startswith("+"):
        sign = 1
        token = token[1:]
    elif token.startswith("-"):
        sign = -1
        token = token[1:]

    m = re.fullmatch(r"(\d+)(K|M)?", token)
    if not m:
        raise ValueError

    value = int(m.group(1))
    if m.group(2) == "K":
        value *= 1_000
    elif m.group(2) == "M":
        value *= 1_000_000

    return tx_date, sign * value, category

# =========================
# HANDLE MONEY (MULTI-LINE)
# =========================
async def handle_money(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.message.from_user.username or "unknown"
    lines = update.message.text.strip().splitlines()

    ok, bad = 0, []

    for line in lines:
        try:
            tx_date, amount, category = parse_line(line)
            append_expense(tx_date, user, amount, category)
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
async def report_year(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("❗ Ví dụ: /year 2026")
        return

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
# HANDLERS (THỨ TỰ QUYẾT ĐỊNH TẤT CẢ)
# =========================
application.add_handler(CommandHandler("start", start))
application.add_handler(CommandHandler("help", help_cmd))
application.add_handler(CommandHandler("year", report_year))

application.add_handler(MessageHandler(filters.Regex(f"^{BTN_DAY}$"), lambda u, c: u.message.reply_text("📊 Đang làm")))
application.add_handler(MessageHandler(filters.Regex(f"^{BTN_MONTH}$"), lambda u, c: u.message.reply_text("📅 Đang làm")))
application.add_handler(MessageHandler(filters.Regex(f"^{BTN_YEAR}$"), lambda u, c: u.message.reply_text("📈 Gõ /year 2026")))

# ⚠️ CHỈ BẮT DÒNG TIỀN
application.add_handler(
    MessageHandler(
        filters.TEXT & filters.Regex(r"^(\d{8}\s+)?[+-]?\d"),
        handle_money,
    )
)

# =========================
# WEBHOOK
# =========================
@fastapi_app.post("/webhook")
async def webhook(req: Request):
    update = Update.de_json(await req.json(), application.bot)
    await application.process_update(update)
    return {"ok": True}
