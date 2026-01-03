import os
import re
from datetime import datetime, date
from collections import defaultdict
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

from google_sheet_store import append_expense, get_all_rows

# =====================
# CONFIG
# =====================
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
if not BOT_TOKEN:
    raise RuntimeError("Missing TELEGRAM_BOT_TOKEN")

BTN_DAY = "📊 Tổng kết ngày"
BTN_MONTH = "📅 Tổng kết tháng"
BTN_YEAR = "📈 Tổng kết năm"
BTN_HELP = "ℹ️ Help"

KEYBOARD = ReplyKeyboardMarkup(
    [[BTN_DAY, BTN_MONTH], [BTN_YEAR, BTN_HELP]],
    resize_keyboard=True,
)

# =====================
# TELEGRAM APP
# =====================
application = ApplicationBuilder().token(BOT_TOKEN).build()

# =====================
# FASTAPI
# =====================
@asynccontextmanager
async def lifespan(app: FastAPI):
    await application.initialize()
    await application.start()
    yield
    await application.stop()

fastapi_app = FastAPI(lifespan=lifespan)

# =====================
# UTIL
# =====================
def parse_money_line(line: str):
    parts = line.strip().split()

    # Có ngày
    if re.fullmatch(r"\d{8}", parts[0]):
        tx_date = datetime.strptime(parts[0], "%Y%m%d").date()
        money = parts[1]
        category = " ".join(parts[2:]) if len(parts) > 2 else "KHÁC"
    else:
        tx_date = date.today()
        money = parts[0]
        category = " ".join(parts[1:]) if len(parts) > 1 else "KHÁC"

    sign = -1
    if money.startswith("+"):
        sign = 1
        money = money[1:]
    elif money.startswith("-"):
        sign = -1
        money = money[1:]

    money = money.upper().replace(",", "")
    m = re.fullmatch(r"(\d+)(K|M)?", money)
    if not m:
        raise ValueError("Sai định dạng")

    value = int(m.group(1))
    if m.group(2) == "K":
        value *= 1_000
    elif m.group(2) == "M":
        value *= 1_000_000

    return tx_date, sign * value, category

# =====================
# COMMANDS
# =====================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 Chào bạn!\nGõ tiền hoặc dùng menu bên dưới 👇",
        reply_markup=KEYBOARD,
    )

async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📘 HƯỚNG DẪN\n\n"
        "➕ Ghi tiền:\n"
        "20K CF\n"
        "+1M LUONG\n\n"
        "➕ Ghi theo ngày:\n"
        "20260101 20K CF\n\n"
        "📊 Báo cáo:\n"
        "/year 2026\n",
        reply_markup=KEYBOARD,
    )

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

    total_in = sum(v["in"] for v in by_month.values())
    total_out = sum(v["out"] for v in by_month.values())

    text = f"📈 BÁO CÁO THU–CHI NĂM {year}\n\n"
    text += f"💰 Thu: {total_in:,}\n"
    text += f"💸 Chi: {total_out:,}\n"
    text += f"📊 Còn: {total_in - total_out:,}\n\n"

    text += "📅 CHI TIẾT THEO THÁNG:\n"
    for m in sorted(by_month):
        i = by_month[m]["in"]
        o = by_month[m]["out"]
        text += f"• Tháng {m}: Thu {i:,} | Chi {o:,} | Còn {i-o:,}\n"

    await update.message.reply_text(text, reply_markup=KEYBOARD)

# =====================
# MENU HANDLERS
# =====================
async def summary_day(update: Update, context: ContextTypes.DEFAULT_TYPE):
    today = date.today().isoformat()
    rows = [r for r in get_all_rows() if r["date"] == today]

    inc = sum(r["amount"] for r in rows if r["amount"] > 0)
    out = sum(-r["amount"] for r in rows if r["amount"] < 0)

    await update.message.reply_text(
        f"📊 TỔNG KẾT NGÀY\n"
        f"Thu: {inc:,}\n"
        f"Chi: {out:,}\n"
        f"Còn: {inc-out:,}",
        reply_markup=KEYBOARD,
    )

async def summary_month(update: Update, context: ContextTypes.DEFAULT_TYPE):
    now = date.today()
    prefix = now.strftime("%Y-%m")
    rows = [r for r in get_all_rows() if r["date"].startswith(prefix)]

    inc = sum(r["amount"] for r in rows if r["amount"] > 0)
    out = sum(-r["amount"] for r in rows if r["amount"] < 0)

    await update.message.reply_text(
        f"📅 TỔNG KẾT THÁNG\n"
        f"Thu: {inc:,}\n"
        f"Chi: {out:,}\n"
        f"Còn: {inc-out:,}",
        reply_markup=KEYBOARD,
    )

# =====================
# MONEY INPUT
# =====================
async def handle_money(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.message.from_user.username or "unknown"
    lines = update.message.text.splitlines()

    ok, fail = 0, []

    for line in lines:
        try:
            d, amt, cat = parse_money_line(line)
            append_expense(d, user, amt, cat)
            ok += 1
        except Exception:
            fail.append(line)

    msg = f"✅ Ghi thành công: {ok} dòng"
    if fail:
        msg += "\n❌ Lỗi:\n" + "\n".join(fail)

    await update.message.reply_text(msg, reply_markup=KEYBOARD)

# =====================
# REGISTER HANDLERS (THỨ TỰ QUYẾT ĐỊNH)
# =====================
application.add_handler(CommandHandler("start", start))
application.add_handler(CommandHandler("help", help_cmd))
application.add_handler(CommandHandler("year", report_year))

application.add_handler(MessageHandler(filters.Regex(f"^{BTN_DAY}$"), summary_day))
application.add_handler(MessageHandler(filters.Regex(f"^{BTN_MONTH}$"), summary_month))
application.add_handler(MessageHandler(filters.Regex(f"^{BTN_YEAR}$"), lambda u, c: u.message.reply_text("📌 Gõ: /year 2026")))
application.add_handler(MessageHandler(filters.Regex(f"^{BTN_HELP}$"), help_cmd))

application.add_handler(
    MessageHandler(
        filters.TEXT & filters.Regex(r"^(\d{8}\s+)?[+-]?\d"),
        handle_money,
    )
)

# =====================
# WEBHOOK
# =====================
@fastapi_app.post("/webhook")
async def webhook(req: Request):
    update = Update.de_json(await req.json(), application.bot)
    await application.process_update(update)
    return {"ok": True}
