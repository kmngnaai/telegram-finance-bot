import os
import re
from datetime import datetime, date
from collections import defaultdict

from fastapi import FastAPI, Request

from telegram import (
    Update,
    ReplyKeyboardMarkup,
    KeyboardButton,
)
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

from google_sheet_store import append_expense, get_all_rows

# =========================
# FASTAPI APP (BẮT BUỘC)
# =========================
fastapi_app = FastAPI()

# =========================
# CONFIG
# =========================
OWNER_USERNAME = "ltkngan198"  # ❗ đổi thành username Telegram của bạn (KHÔNG có @)

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
if not BOT_TOKEN:
    raise RuntimeError("TELEGRAM_BOT_TOKEN not set")

application = ApplicationBuilder().token(BOT_TOKEN).build()

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
# HELP / START
# =========================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 Chào bạn!\nChọn chức năng bên dưới 👇",
        reply_markup=MAIN_KEYBOARD,
    )

async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "📘 HƯỚNG DẪN\n\n"
        "➕ Ghi THU:\n"
        "+5M LUONG\n\n"
        "➖ Ghi CHI:\n"
        "20K CF\n\n"
        "📊 Báo cáo:\n"
        "/summary 20260101  (ngày)\n"
        "/summary 202601    (tháng)\n"
        "/year 2026         (năm)\n"
    )
    await update.message.reply_text(text, reply_markup=MAIN_KEYBOARD)

# =========================
# PARSE AMOUNT
# =========================
def parse_amount(text: str) -> int:
    text = text.upper().replace(",", "").strip()
    sign = 1
    if text.startswith("+"):
        sign = 1
        text = text[1:]
    m = re.match(r"(\d+)(K|M)?", text)
    if not m:
        raise ValueError("Invalid amount")
    value = int(m.group(1))
    unit = m.group(2)
    if unit == "K":
        value *= 1_000
    elif unit == "M":
        value *= 1_000_000
    return sign * value

# =========================
# MESSAGE HANDLER (GHI THU / CHI)
# =========================
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    user = update.message.from_user.username or "unknown"

    try:
        parts = text.split(maxsplit=1)
        amount = parse_amount(parts[0])
        category = parts[1] if len(parts) > 1 else "KHÁC"

        append_expense(date.today(), user, amount, category)

        await update.message.reply_text(
            f"✅ Ghi sổ thành công\n"
            f"Số tiền: {amount:,} đ\n"
            f"Loại: {category}",
            reply_markup=MAIN_KEYBOARD,
        )
    except Exception as e:
        await update.message.reply_text(
            f"❌ Lỗi nhập liệu\nVí dụ: 20K CF hoặc +1M LUONG",
            reply_markup=MAIN_KEYBOARD,
        )

# =========================
# SUMMARY DAY / MONTH
# =========================
async def summary(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("❌ Thiếu tham số. Ví dụ: /summary 20260101")
        return

    key = context.args[0]
    rows = get_all_rows()

    income = expense = 0
    for r in rows:
        if r["date"].replace("-", "").startswith(key):
            if r["amount"] >= 0:
                income += r["amount"]
            else:
                expense += abs(r["amount"])

    await update.message.reply_text(
        f"📊 Tổng kết\n"
        f"💰 Thu: {income:,} đ\n"
        f"💸 Chi: {expense:,} đ\n"
        f"📌 Còn lại: {income - expense:,} đ",
        reply_markup=MAIN_KEYBOARD,
    )

# =========================
# YEAR REPORT
# =========================
async def year_report(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("❌ Thiếu năm. Ví dụ: /year 2026")
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
    total_in = total_out = 0

    for m in sorted(by_month):
        i = by_month[m]["in"]
        o = by_month[m]["out"]
        total_in += i
        total_out += o
        text += f"• Tháng {m}: Thu {i:,} | Chi {o:,} | Còn {i-o:,}\n"

    text += (
        f"\n📌 TỔNG CỘNG\n"
        f"💰 Thu: {total_in:,}\n"
        f"💸 Chi: {total_out:,}\n"
        f"📊 Còn: {total_in-total_out:,}"
    )

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
# WEBHOOK ENDPOINT (BẮT BUỘC)
# =========================
@fastapi_app.post("/webhook")
async def telegram_webhook(request: Request):
    data = await request.json()
    update = Update.de_json(data, application.bot)
    await application.process_update(update)
    return {"ok": True}
