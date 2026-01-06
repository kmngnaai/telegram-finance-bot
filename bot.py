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
OWNER_USERNAME = "ltkngan198"  # username Telegram (KHÔNG @)
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
RENDER_EXTERNAL_URL = os.getenv("RENDER_EXTERNAL_URL")  # Render auto set (https://xxx.onrender.com)

if not BOT_TOKEN:
    raise RuntimeError("Missing TELEGRAM_BOT_TOKEN env var")

# =========================
# MENU
# =========================
MAIN_MENU = ReplyKeyboardMarkup(
    [
        [KeyboardButton("➕ Ghi thu"), KeyboardButton("➖ Ghi chi")],
        [KeyboardButton("📊 Tổng kết ngày"), KeyboardButton("📅 Tổng kết tháng")],
        [KeyboardButton("📈 Tổng kết năm"), KeyboardButton("ℹ️ Help")],
    ],
    resize_keyboard=True,
)

# =========================
# PARSE AMOUNT
# =========================
def parse_amount(text: str) -> int:
    """
    Parse first number in text and convert K/M.
    Examples: "20K"->20000, "+1M"->1000000, "-50k"->-50000
    """
    s = text.strip().upper().replace(",", "")
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
    # remove the first occurrence of amount-like token
    return re.sub(r"[+-]?\d+(\.\d+)?[KM]?", "", text, count=1, flags=re.I).strip()

def parse_lines(text: str) -> List[Tuple[date, int, str]]:
    """
    Each line:
      - "YYYYMMDD <amount> <category...>"
      - or "<amount> <category...>" -> today
    Returns list of (date, amount, category).
    """
    results: List[Tuple[date, int, str]] = []
    for raw in text.strip().splitlines():
        line = raw.strip()
        if not line:
            continue

        m = re.match(r"^(\d{8})\s+(.*)$", line)
        if m:
            d = datetime.strptime(m.group(1), "%Y%m%d").date()
            content = m.group(2).strip()
        else:
            d = datetime.today().date()
            content = line

        amount = parse_amount(content)
        category = strip_amount(content)

        if amount != 0 and category:
            results.append((d, amount, category))
    return results

def format_vnd(n: int) -> str:
    return f"{n:,}".replace(",", ",")

# =========================
# TELEGRAM HANDLERS
# =========================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_text(
        "👋 Chào bạn!\nChọn chức năng bên dưới ⬇️",
        reply_markup=MAIN_MENU,
    )

async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📌 HƯỚNG DẪN SỬ DỤNG BOT\n\n"
        "✍️ Ghi thu / chi:\n"
        "• 20K CF\n"
        "• +1M LUONG\n"
        "• -50K ĂN\n"
        "• 20260101 500K SPA\n"
        "• Có thể gửi nhiều dòng (mỗi dòng = 1 giao dịch)\n\n"
        "📊 Báo cáo:\n"
        "• 📊 Tổng kết ngày (menu)\n"
        "• 📅 Tổng kết tháng (menu)\n"
        "• 📈 Tổng kết năm (menu) hoặc gõ: /year 2026\n"
        "• OWNER có thể xem user khác: /year 2026 @username\n\n"
        "ℹ️ Ghi chú:\n"
        "• K = nghìn | M = triệu\n"
        "• Thu: số dương | Chi: số âm\n",
        reply_markup=MAIN_MENU,
    )

async def summary_day(update: Update, context: ContextTypes.DEFAULT_TYPE):
    today = datetime.today().date()
    rows = get_all_rows()

    thu = 0
    chi = 0
    for r in rows:
        if r.get("date") == str(today):
            amt = int(r.get("amount", 0))
            if amt > 0:
                thu += amt
            else:
                chi += abs(amt)

    await update.message.reply_text(
        "📊 TỔNG KẾT NGÀY\n"
        f"💰 Thu: {format_vnd(thu)} đ\n"
        f"💸 Chi: {format_vnd(chi)} đ\n"
        f"📉 Còn: {format_vnd(thu - chi)} đ"
    )

async def summary_month(update: Update, context: ContextTypes.DEFAULT_TYPE):
    now = datetime.today()
    rows = get_all_rows()

    thu = 0
    chi = 0
    for r in rows:
        try:
            d = datetime.strptime(r.get("date", ""), "%Y-%m-%d")
        except Exception:
            continue

        if d.year == now.year and d.month == now.month:
            amt = int(r.get("amount", 0))
            if amt > 0:
                thu += amt
            else:
                chi += abs(amt)

    await update.message.reply_text(
        "📅 TỔNG KẾT THÁNG\n"
        f"💰 Thu: {format_vnd(thu)} đ\n"
        f"💸 Chi: {format_vnd(chi)} đ\n"
        f"📉 Còn: {format_vnd(thu - chi)} đ"
    )

async def summary_year(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args or []
    if not args:
        await update.message.reply_text("❗ Ví dụ: /year 2026")
        return

    try:
        year = int(args[0])
    except ValueError:
        await update.message.reply_text("❗ Năm phải là số. Ví dụ: /year 2026")
        return

    # rule:
    # - user thường: chỉ xem của chính mình
    # - owner: nếu có @user thì xem user đó, không có thì xem owner
    if len(args) > 1 and (update.effective_user.username == OWNER_USERNAME):
        target_user = args[1].replace("@", "")
    else:
        target_user = update.effective_user.username

    rows = get_all_rows()
    monthly = defaultdict(lambda: {"thu": 0, "chi": 0})

    for r in rows:
        if r.get("user") != target_user:
            continue
        try:
            d = datetime.strptime(r.get("date", ""), "%Y-%m-%d")
        except Exception:
            continue

        if d.year != year:
            continue

        amt = int(r.get("amount", 0))
        if amt > 0:
            monthly[d.month]["thu"] += amt
        else:
            monthly[d.month]["chi"] += abs(amt)

    if not monthly:
        await update.message.reply_text("❌ Không có dữ liệu.")
        return

    total_thu = 0
    total_chi = 0
    lines = []
    for m in sorted(monthly.keys()):
        t = monthly[m]["thu"]
        c = monthly[m]["chi"]
        total_thu += t
        total_chi += c
        lines.append(f"• Tháng {m:02d}: Thu {format_vnd(t)} | Chi {format_vnd(c)} | Còn {format_vnd(t-c)}")

    worst = max(monthly.keys(), key=lambda mm: monthly[mm]["chi"])
    best = max(monthly.keys(), key=lambda mm: (monthly[mm]["thu"] - monthly[mm]["chi"]))

    # đánh giá thêm (giữ format bạn thích)
    await update.message.reply_text(
        f"📈 BÁO CÁO THU–CHI NĂM {year}\n"
        f"👤 User: @{target_user}\n\n"
        f"💰 Tổng thu: {format_vnd(total_thu)} đ\n"
        f"💸 Tổng chi: {format_vnd(total_chi)} đ\n"
        f"📉 Còn lại: {format_vnd(total_thu - total_chi)} đ\n\n"
        "📅 CHI TIẾT THEO THÁNG:\n"
        + "\n".join(lines)
        + "\n\n📌 ĐÁNH GIÁ:\n"
        + ("✅ Thu > Chi cả năm\n" if total_thu > total_chi else "⚠️ Chi > Thu cả năm\n")
        + f"🔥 Tháng chi nhiều nhất: {worst:02d}\n"
        + f"💚 Tháng tiết kiệm tốt nhất: {best:02d}"
    )

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (update.message.text or "").strip()
    if not text:
        return

    # ===== MENU =====
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
        await update.message.reply_text("📌 Gõ: /year 2026 (hoặc /year 2026 @username nếu bạn là OWNER)")
        return

    # ===== CHỌN MODE =====
    if text == "➕ Ghi thu":
        context.user_data["mode"] = "thu"
        await update.message.reply_text("✍️ Đang ghi THU\nNhập nội dung:")
        return

    if text == "➖ Ghi chi":
        context.user_data["mode"] = "chi"
        await update.message.reply_text("✍️ Đang ghi CHI\nNhập nội dung:")
        return

    # ===== GHI DỮ LIỆU =====
    entries = parse_lines(text)
    if not entries:
        await update.message.reply_text(
            "❌ Sai định dạng.\nVí dụ:\n"
            "• 20K CF\n"
            "• +1M LUONG\n"
            "• -50K ĂN\n"
            "• 20260101 500K SPA"
        )
        return

    mode = context.user_data.get("mode")  # "thu" | "chi" | None

    # Nếu chưa chọn mode -> cho phép tự hiểu theo dấu +/-
    # - Nếu dòng có amount âm -> chi
    # - Nếu dòng có amount dương có dấu '+' hoặc user đang dùng +... -> thu
    # - Nếu dương không có dấu + và chưa chọn mode -> bắt chọn (tránh đoán sai)
    if not mode:
        has_negative = any(a < 0 for _, a, _ in entries)
        has_explicit_plus = any(re.search(r"(^|\s)\+\d", raw.strip()) for raw in text.splitlines())

        if has_negative and not has_explicit_plus:
            mode = "chi"
        elif has_explicit_plus and not has_negative:
            mode = "thu"
        else:
            # ambiguous: có dương không dấu / trộn + và -
            await update.message.reply_text("⚠️ Bạn hãy bấm ➕ Ghi thu hoặc ➖ Ghi chi trước rồi gửi lại nội dung.")
            return

    username = update.effective_user.username or "unknown"

    count = 0
    for d, amount, category in entries:
        # chuẩn hoá chi: nếu mode chi mà amount > 0 thì đổi âm
        if mode == "chi" and amount > 0:
            amount = -amount
        # chuẩn hoá thu: nếu mode thu mà amount < 0 thì đổi dương
        if mode == "thu" and amount < 0:
            amount = abs(amount)

        append_expense(
            date=str(d),
            user=username,
            amount=int(amount),
            category=category,
        )
        count += 1

    await update.message.reply_text(f"✅ Ghi thành công: {count} dòng", reply_markup=MAIN_MENU)

    # Giữ đúng “logic cũ”: ghi xong thì reset mode (để lần sau chọn lại)
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
# FASTAPI LIFESPAN
# =========================
@asynccontextmanager
async def lifespan(app: FastAPI):
    global telegram_app

    if not RENDER_EXTERNAL_URL:
        logger.warning("RENDER_EXTERNAL_URL is missing. Webhook set may fail.")
    webhook_url = f"{RENDER_EXTERNAL_URL}/webhook" if RENDER_EXTERNAL_URL else None

    telegram_app = build_telegram_app()

    # Proper init/start (NO create_task hacks)
    await telegram_app.initialize()
    await telegram_app.start()

    if webhook_url:
        await telegram_app.bot.set_webhook(webhook_url)
        logger.info("Webhook set to: %s", webhook_url)

    yield

    # Proper stop/shutdown
    if telegram_app:
        await telegram_app.stop()
        await telegram_app.shutdown()
        telegram_app = None

fastapi_app = FastAPI(lifespan=lifespan)

# health check
@fastapi_app.get("/")
async def root():
    return {"ok": True}

# webhook endpoint
@fastapi_app.post("/webhook")
async def webhook(req: Request):
    if telegram_app is None:
        return {"ok": False, "error": "telegram_app_not_ready"}

    data = await req.json()
    update = Update.de_json(data, telegram_app.bot)
    await telegram_app.process_update(update)
    return {"ok": True}
