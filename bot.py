import os
import re
import logging
from datetime import datetime, date
from collections import defaultdict
from typing import List, Tuple, Optional

from fastapi import FastAPI, Request
from contextlib import asynccontextmanager

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
# LOGGING
# =========================
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# =========================
# CONFIG
# =========================
OWNER_USERNAME = "ltkngan198"   # username Telegram (KHÔNG @)
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
RENDER_EXTERNAL_URL = os.getenv("RENDER_EXTERNAL_URL")

if not BOT_TOKEN:
    raise RuntimeError("Missing TELEGRAM_BOT_TOKEN")

# =========================
# MENU
# =========================
MAIN_MENU = ReplyKeyboardMarkup(
    [
        [KeyboardButton("➕ Ghi thu"), KeyboardButton("➖ Ghi chi")],
        [KeyboardButton("📊 Tổng kết ngày"), KeyboardButton("📅 Tổng kết tháng")],
        [KeyboardButton("📈 Tổng kết năm"), KeyboardButton("ℹ️ Help")],
    ],
    resize_keyboard=True
)

# =========================
# PARSE HELPERS
# =========================
def parse_amount(text: str) -> int:
    s = text.upper().replace(",", "")
    m = re.search(r"([+-]?\d+(?:\.\d+)?)([KM]?)", s)
    if not m:
        return 0
    num = float(m.group(1))
    unit = m.group(2)
    if unit == "K":
        num *= 1_000
    elif unit == "M":
        num *= 1_000_000
    return int(num)

def strip_amount(text: str) -> str:
    return re.sub(r"[+-]?\d+(\.\d+)?[KM]?", "", text, count=1, flags=re.I).strip()

def parse_lines(text: str) -> List[Tuple[date, int, str]]:
    results = []
    for raw in text.strip().splitlines():
        line = raw.strip()
        if not line:
            continue

        m = re.match(r"^(\d{8})\s+(.*)$", line)
        if m:
            d = datetime.strptime(m.group(1), "%Y%m%d").date()
            content = m.group(2)
        else:
            d = datetime.today().date()
            content = line

        amount = parse_amount(content)
        category = strip_amount(content)

        if amount != 0 and category:
            results.append((d, amount, category))
    return results

def fmt(n: int) -> str:
    return f"{n:,}".replace(",", ",")

# =========================
# COMMANDS
# =========================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_text(
        "👋 Chào bạn!\nChọn chức năng bên dưới ⬇️",
        reply_markup=MAIN_MENU
    )

async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📌 HƯỚNG DẪN SỬ DỤNG\n\n"
        "✍️ Ghi thu / chi:\n"
        "• 20K CF\n"
        "• +1M LUONG\n"
        "• -50K ĂN\n"
        "• 20260101 500K SPA\n"
        "• Có thể nhiều dòng\n\n"
        "📊 Báo cáo:\n"
        "• Tổng kết ngày / tháng (menu)\n"
        "• /year 2026\n"
        "• /year 2026 @username (OWNER)\n\n"
        "ℹ️ Ghi chú:\n"
        "• K = nghìn | M = triệu\n"
        "• Thu (+) | Chi (-)",
        reply_markup=MAIN_MENU
    )

# =========================
# SUMMARY
# =========================
async def summary_day(update: Update, context: ContextTypes.DEFAULT_TYPE):
    today = str(datetime.today().date())
    thu = chi = 0
    for r in get_all_rows():
        if r["date"] == today:
            if r["amount"] > 0:
                thu += r["amount"]
            else:
                chi += abs(r["amount"])
    await update.message.reply_text(
        f"📊 TỔNG KẾT NGÀY\n"
        f"💰 Thu: {fmt(thu)} đ\n"
        f"💸 Chi: {fmt(chi)} đ\n"
        f"📉 Còn: {fmt(thu - chi)} đ"
    )

async def summary_month(update: Update, context: ContextTypes.DEFAULT_TYPE):
    now = datetime.today()
    thu = chi = 0
    for r in get_all_rows():
        d = datetime.strptime(r["date"], "%Y-%m-%d")
        if d.year == now.year and d.month == now.month:
            if r["amount"] > 0:
                thu += r["amount"]
            else:
                chi += abs(r["amount"])
    await update.message.reply_text(
        f"📅 TỔNG KẾT THÁNG\n"
        f"💰 Thu: {fmt(thu)} đ\n"
        f"💸 Chi: {fmt(chi)} đ\n"
        f"📉 Còn: {fmt(thu - chi)} đ"
    )

async def summary_year(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("❗ Ví dụ: /year 2026")
        return

    year = int(context.args[0])

    if len(context.args) > 1 and update.effective_user.username == OWNER_USERNAME:
        user = context.args[1].replace("@", "")
    else:
        user = update.effective_user.username

    monthly = defaultdict(lambda: {"thu": 0, "chi": 0})

    for r in get_all_rows():
        if r["user"] != user:
            continue
        d = datetime.strptime(r["date"], "%Y-%m-%d")
        if d.year == year:
            if r["amount"] > 0:
                monthly[d.month]["thu"] += r["amount"]
            else:
                monthly[d.month]["chi"] += abs(r["amount"])

    if not monthly:
        await update.message.reply_text("❌ Không có dữ liệu.")
        return

    total_thu = total_chi = 0
    lines = []

    for m in sorted(monthly):
        t = monthly[m]["thu"]
        c = monthly[m]["chi"]
        total_thu += t
        total_chi += c
        lines.append(f"• Tháng {m:02d}: Thu {fmt(t)} | Chi {fmt(c)} | Còn {fmt(t - c)}")

    worst = max(monthly, key=lambda x: monthly[x]["chi"])
    best = max(monthly, key=lambda x: monthly[x]["thu"] - monthly[x]["chi"])

    await update.message.reply_text(
        f"📈 BÁO CÁO THU–CHI NĂM {year}\n"
        f"👤 User: @{user}\n\n"
        f"💰 Tổng thu: {fmt(total_thu)} đ\n"
        f"💸 Tổng chi: {fmt(total_chi)} đ\n"
        f"📉 Còn lại: {fmt(total_thu - total_chi)} đ\n\n"
        "📅 CHI TIẾT THEO THÁNG:\n"
        + "\n".join(lines) +
        f"\n\n📌 ĐÁNH GIÁ:\n"
        f"🔥 Tháng chi nhiều nhất: {worst:02d}\n"
        f"💚 Tháng tiết kiệm tốt nhất: {best:02d}"
    )

# =========================
# HANDLE TEXT (FIX CHÍNH)
# =========================
async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()

    # MENU
    if text == "ℹ️ Help":
        await help_cmd(update, context)
        return
    if text == "📊 Tổng kết ngày":
        await summary_day(update, context)
        return
    if text == "📅 Tổng kết tháng":
        await summary_month(update, context)
        return
    if text == "📈 Tổng kết năm":
        await update.message.reply_text("📌 Gõ: /year 2026")
        return

    # MODE
    if text == "➕ Ghi thu":
        context.user_data["mode"] = "thu"
        await update.message.reply_text("✍️ Đang ghi THU\nNhập nội dung:")
        return
    if text == "➖ Ghi chi":
        context.user_data["mode"] = "chi"
        await update.message.reply_text("✍️ Đang ghi CHI\nNhập nội dung:")
        return

    entries = parse_lines(text)
    if not entries:
        await update.message.reply_text("❌ Sai định dạng.\nVí dụ: 20K CF | +1M LUONG")
        return

    mode = context.user_data.get("mode")

    # ⚠️ FIX QUAN TRỌNG: chỉ auto-detect khi CHƯA chọn mode
    if mode is None:
        has_negative = any(a < 0 for _, a, _ in entries)
        has_plus = any(re.search(r"(^|\s)\+\d", raw) for raw in text.splitlines())

        if has_negative and not has_plus:
            mode = "chi"
        elif has_plus and not has_negative:
            mode = "thu"
        else:
            await update.message.reply_text("⚠️ Hãy bấm ➕ Ghi thu hoặc ➖ Ghi chi trước.")
            return

    count = 0
    user = update.effective_user.username

    for d, amount, category in entries:
        if mode == "chi" and amount > 0:
            amount = -amount
        if mode == "thu" and amount < 0:
            amount = abs(amount)

        append_expense(str(d), user, amount, category)
        count += 1

    await update.message.reply_text(f"✅ Ghi thành công: {count} dòng", reply_markup=MAIN_MENU)
    context.user_data.clear()

# =========================
# BUILD TELEGRAM APP
# =========================
def build_telegram_app() -> Application:
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("year", summary_year))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    return app

telegram_app: Optional[Application] = None

# =========================
# FASTAPI
# =========================
@asynccontextmanager
async def lifespan(app: FastAPI):
    global telegram_app
    telegram_app = build_telegram_app()
    await telegram_app.initialize()
    await telegram_app.start()

    if RENDER_EXTERNAL_URL:
        await telegram_app.bot.set_webhook(f"{RENDER_EXTERNAL_URL}/webhook")

    yield

    await telegram_app.stop()
    await telegram_app.shutdown()

fastapi_app = FastAPI(lifespan=lifespan)

@fastapi_app.get("/")
async def root():
    return {"ok": True}

@fastapi_app.post("/webhook")
async def webhook(req: Request):
    data = await req.json()
    update = Update.de_json(data, telegram_app.bot)
    await telegram_app.process_update(update)
    return {"ok": True}
