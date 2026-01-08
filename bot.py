import os
import re
import logging
from datetime import datetime, date
from collections import defaultdict
from contextlib import asynccontextmanager
from typing import List, Tuple, Optional

from fastapi import FastAPI, Request
from telegram import (
    Update,
    ReplyKeyboardMarkup,
    KeyboardButton,
)
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
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s - %(message)s",
)
log = logging.getLogger("finance-bot")


# =========================
# CONFIG
# =========================
OWNER_USERNAME = os.getenv("OWNER_USERNAME", "ltkngan198").replace("@", "")
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
RENDER_EXTERNAL_URL = os.getenv("RENDER_EXTERNAL_URL", "").rstrip("/")

if not BOT_TOKEN:
    raise RuntimeError("Missing TELEGRAM_BOT_TOKEN env var")
if not RENDER_EXTERNAL_URL:
    raise RuntimeError("Missing RENDER_EXTERNAL_URL env var")


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
# PARSING HELPERS
# =========================
AMOUNT_TOKEN_RE = re.compile(r"([+-]?\d+(?:\.\d+)?)([KM]?)", re.IGNORECASE)
DATE_PREFIX_RE = re.compile(r"^(\d{8})\s+(.*)$")


def parse_amount_token(text: str) -> Tuple[int, bool]:
    """
    Returns (amount, has_explicit_sign).
    - amount includes sign if present in token
    - has_explicit_sign True if token starts with + or -
    """
    s = text.upper().replace(",", "").strip()
    m = AMOUNT_TOKEN_RE.search(s)
    if not m:
        return 0, False

    raw = m.group(1)
    unit = (m.group(2) or "").upper()
    has_sign = raw.startswith("+") or raw.startswith("-")

    num = float(raw)
    if unit == "K":
        num *= 1_000
    elif unit == "M":
        num *= 1_000_000

    return int(num), has_sign


def strip_amount_from_text(text: str) -> str:
    # remove first amount token occurrence, keep rest as category
    return AMOUNT_TOKEN_RE.sub("", text, count=1).strip()


def parse_lines(text: str) -> List[Tuple[date, int, bool, str]]:
    """
    Parse user input into entries:
    returns list of (date, amount_raw, has_explicit_sign, category)
    amount_raw is signed only if user included +/-; otherwise positive.
    """
    results: List[Tuple[date, int, bool, str]] = []
    lines = [ln.strip() for ln in text.strip().splitlines() if ln.strip()]
    for line in lines:
        dm = DATE_PREFIX_RE.match(line)
        if dm:
            d = datetime.strptime(dm.group(1), "%Y%m%d").date()
            content = dm.group(2).strip()
        else:
            d = datetime.today().date()
            content = line

        amount, has_sign = parse_amount_token(content)
        category = strip_amount_from_text(content)

        if amount == 0 or not category:
            continue

        results.append((d, amount, has_sign, category))
    return results


def parse_yyyymmdd(s: str) -> Optional[date]:
    try:
        return datetime.strptime(s, "%Y%m%d").date()
    except Exception:
        return None


def parse_yyyymm(s: str) -> Optional[Tuple[int, int]]:
    try:
        dt = datetime.strptime(s, "%Y%m")
        return dt.year, dt.month
    except Exception:
        return None


# =========================
# TELEGRAM HANDLERS
# =========================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Reset "mode" only when user explicitly starts
    context.user_data.clear()
    await update.message.reply_text(
        "👋 Chào bạn!\nChọn chức năng bên dưới ⬇️\n"
        "💡 Bạn cũng có thể nhập trực tiếp, ví dụ: `-20K CF` hoặc `+1M LUONG`",
        reply_markup=MAIN_MENU,
    )


async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📌 HƯỚNG DẪN SỬ DỤNG BOT\n\n"
        "✍️ Ghi thu / chi (có thể nhập trực tiếp, KHÔNG cần bấm menu):\n"
        "• -20K CF (chi)\n"
        "• +1M LUONG (thu)\n"
        "• 20260101 -20K CF\n"
        "• 20260101 +1M LUONG\n"
        "• Có thể nhiều dòng\n\n"
        "🟦 Nếu bạn KHÔNG ghi dấu + / - thì bot sẽ dùng chế độ bạn chọn:\n"
        "• Bấm ➕ Ghi thu rồi nhập: 20K THUONG\n"
        "• Bấm ➖ Ghi chi rồi nhập: 20K CF\n\n"
        "📊 Báo cáo:\n"
        "• 📊 Tổng kết ngày (mặc định hôm nay)\n"
        "• /day 20260101 (tổng kết theo ngày cụ thể)\n"
        "• 📅 Tổng kết tháng (mặc định tháng hiện tại)\n"
        "• /month 202601 (tổng kết theo tháng cụ thể)\n"
        "• 📈 Tổng kết năm (menu sẽ nhắc cú pháp)\n"
        "• /year 2026\n"
        "• /year 2026 @username (chỉ OWNER)\n\n"
        "ℹ️ Ghi chú:\n"
        "• K = nghìn | M = triệu\n"
        "• Thu: số dương | Chi: số âm\n",
        reply_markup=MAIN_MENU,
    )


async def set_mode_income(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["mode"] = "thu"
    await update.message.reply_text(
        "➕ Đang ghi THU\nNhập nội dung (có thể nhiều dòng). Ví dụ:\n"
        "• 20K THUONG\n• 20260101 1M LUONG\n• +1M LUONG",
        reply_markup=MAIN_MENU,
    )


async def set_mode_expense(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["mode"] = "chi"
    await update.message.reply_text(
        "➖ Đang ghi CHI\nNhập nội dung (có thể nhiều dòng). Ví dụ:\n"
        "• 20K CF\n• 20260101 500K SPA\n• -20K CF",
        reply_markup=MAIN_MENU,
    )


async def summary_day_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # /day [YYYYMMDD]
    target = datetime.today().date()
    if context.args:
        d = parse_yyyymmdd(context.args[0])
        if not d:
            await update.message.reply_text("❗ Ví dụ đúng: /day 20260101")
            return
        target = d

    rows = get_all_rows()
    thu = chi = 0
    for r in rows:
        if r.get("date") != str(target):
            continue
        amt = int(r.get("amount", 0))
        if amt > 0:
            thu += amt
        else:
            chi += abs(amt)

    await update.message.reply_text(
        f"📊 TỔNG KẾT NGÀY {target.strftime('%Y-%m-%d')}\n"
        f"💰 Thu: {thu:,} đ\n"
        f"💸 Chi: {chi:,} đ\n"
        f"📉 Còn: {thu - chi:,} đ",
        reply_markup=MAIN_MENU,
    )


async def summary_month_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # /month [YYYYMM]
    now = datetime.today()
    year, month = now.year, now.month

    if context.args:
        ym = parse_yyyymm(context.args[0])
        if not ym:
            await update.message.reply_text("❗ Ví dụ đúng: /month 202601")
            return
        year, month = ym

    rows = get_all_rows()
    thu = chi = 0
    for r in rows:
        try:
            d = datetime.strptime(r["date"], "%Y-%m-%d")
        except Exception:
            continue
        if d.year == year and d.month == month:
            amt = int(r.get("amount", 0))
            if amt > 0:
                thu += amt
            else:
                chi += abs(amt)

    await update.message.reply_text(
        f"📅 TỔNG KẾT THÁNG {year}-{month:02d}\n"
        f"💰 Thu: {thu:,} đ\n"
        f"💸 Chi: {chi:,} đ\n"
        f"📉 Còn: {thu - chi:,} đ",
        reply_markup=MAIN_MENU,
    )


async def summary_year(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # /year YYYY [@user]
    if not context.args:
        await update.message.reply_text("❗ Ví dụ: /year 2026")
        return

    try:
        year = int(context.args[0])
    except Exception:
        await update.message.reply_text("❗ Ví dụ đúng: /year 2026")
        return

    # Target user rule:
    # - default: current user
    # - owner can specify @user
    if len(context.args) > 1 and (update.effective_user.username or "") == OWNER_USERNAME:
        target_user = context.args[1].replace("@", "").strip()
    else:
        target_user = (update.effective_user.username or "").strip()

    if not target_user:
        await update.message.reply_text("❗ Tài khoản Telegram của bạn chưa có username (@...).")
        return

    rows = get_all_rows()
    monthly = defaultdict(lambda: {"thu": 0, "chi": 0})

    for r in rows:
        if r.get("user") != target_user:
            continue
        try:
            d = datetime.strptime(r["date"], "%Y-%m-%d")
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
        await update.message.reply_text(
            f"❌ Không có dữ liệu năm {year} cho @{target_user}.",
            reply_markup=MAIN_MENU,
        )
        return

    total_thu = total_chi = 0
    lines = []
    for m in range(1, 13):
        if m not in monthly:
            continue
        t = monthly[m]["thu"]
        c = monthly[m]["chi"]
        total_thu += t
        total_chi += c
        lines.append(f"• Tháng {m:02d}: Thu {t:,} | Chi {c:,} | Còn {t - c:,}")

    # worst by chi, best by (thu-chi)
    worst = max(monthly, key=lambda x: monthly[x]["chi"])
    best = max(monthly, key=lambda x: monthly[x]["thu"] - monthly[x]["chi"])

    evaluation = []
    evaluation.append("✅ Thu > Chi cả năm" if total_thu > total_chi else "⚠️ Chi > Thu cả năm")
    evaluation.append(f"🔥 Tháng chi nhiều nhất: {worst:02d}")
    evaluation.append(f"💚 Tháng tiết kiệm tốt nhất: {best:02d}")

    await update.message.reply_text(
        f"📈 BÁO CÁO THU–CHI NĂM {year}\n"
        f"👤 User: @{target_user}\n\n"
        f"💰 Tổng thu: {total_thu:,} đ\n"
        f"💸 Tổng chi: {total_chi:,} đ\n"
        f"📉 Còn lại: {total_thu - total_chi:,} đ\n\n"
        "📅 CHI TIẾT THEO THÁNG:\n"
        + "\n".join(lines)
        + "\n\n📌 ĐÁNH GIÁ:\n"
        + "\n".join(evaluation),
        reply_markup=MAIN_MENU,
    )


async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (update.message.text or "").strip()
    if not text:
        await update.message.reply_text("❗ Bạn gửi nội dung trống.", reply_markup=MAIN_MENU)
        return

    # 1) MENU buttons
    if text == "➕ Ghi thu":
        await set_mode_income(update, context)
        return

    if text == "➖ Ghi chi":
        await set_mode_expense(update, context)
        return

    if text == "📊 Tổng kết ngày":
        await summary_day_cmd(update, context)
        return

    if text == "📅 Tổng kết tháng":
        await summary_month_cmd(update, context)
        return

    if text == "📈 Tổng kết năm":
        await update.message.reply_text("📌 Gõ: /year 2026", reply_markup=MAIN_MENU)
        return

    if text == "ℹ️ Help":
        await help_cmd(update, context)
        return

    # 2) DATA input (ALWAYS try parse, never silent)
    entries = parse_lines(text)
    if not entries:
        await update.message.reply_text(
            "❌ Sai định dạng.\nVí dụ đúng:\n"
            "• -20K CF\n"
            "• +1M LUONG\n"
            "• 20260101 500K SPA (nếu bạn đã chọn Ghi chi/thu)\n"
            "• 20260101 -500K SPA",
            reply_markup=MAIN_MENU,
        )
        return

    mode = context.user_data.get("mode")  # "thu" | "chi" | None
    username = (update.effective_user.username or "").strip()

    if not username:
        await update.message.reply_text(
            "❗ Telegram của bạn chưa có username (@...).\n"
            "Hãy vào Telegram > Settings > Username để đặt username, rồi dùng lại bot.",
            reply_markup=MAIN_MENU,
        )
        return

    # Determine each entry sign:
    # - If user explicitly signed (+/-) => use as is.
    # - Else:
    #     - if mode chosen => apply mode
    #     - else => ask choose (do not write anything)
    needs_mode = any((not has_sign) for (_, _, has_sign, _) in entries)
    if needs_mode and mode not in ("thu", "chi"):
        await update.message.reply_text(
            "⚠️ Bạn chưa chọn Thu/Chi.\n"
            "➡️ Cách nhanh:\n"
            "• Gõ `-` để chi, `+` để thu. Ví dụ: `-20K CF`, `+1M LUONG`\n"
            "• Hoặc bấm menu: ➕ Ghi thu / ➖ Ghi chi rồi gửi lại nội dung.",
            reply_markup=MAIN_MENU,
        )
        return

    count = 0
    for d, amount_raw, has_sign, category in entries:
        amount = amount_raw

        if not has_sign:
            # no explicit sign -> depend on mode
            if mode == "chi":
                amount = -abs(amount_raw)
            else:
                amount = abs(amount_raw)

        # Final safety: chi must be negative, thu positive (based on sign)
        if amount == 0:
            continue

        try:
            append_expense(
                date=str(d),
                user=username,
                amount=int(amount),
                category=category,
            )
            count += 1
        except Exception as e:
            log.exception("append_expense failed: %s", e)
            await update.message.reply_text(
                f"❌ Lỗi khi ghi dữ liệu: {e}",
                reply_markup=MAIN_MENU,
            )
            return

    await update.message.reply_text(
        f"✅ Ghi thành công: {count} dòng\n"
        f"🧾 User: @{username}",
        reply_markup=MAIN_MENU,
    )
    # Do NOT clear mode automatically; user can keep using the same mode.
    # context.user_data.clear()


# =========================
# BUILD TELEGRAM APP
# =========================
telegram_app: Application = ApplicationBuilder().token(BOT_TOKEN).build()

telegram_app.add_handler(CommandHandler("start", start))
telegram_app.add_handler(CommandHandler("help", help_cmd))
telegram_app.add_handler(CommandHandler("day", summary_day_cmd))
telegram_app.add_handler(CommandHandler("month", summary_month_cmd))
telegram_app.add_handler(CommandHandler("year", summary_year))

telegram_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))


# =========================
# FASTAPI (RENDER WEBHOOK)
# =========================
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Initialize & start PTB app
    await telegram_app.initialize()
    await telegram_app.start()

    # Set Telegram webhook to Render URL
    webhook_url = f"{RENDER_EXTERNAL_URL}/webhook"
    try:
        await telegram_app.bot.set_webhook(webhook_url)
        log.info("Webhook set to %s", webhook_url)
    except Exception as e:
        log.exception("Failed to set webhook: %s", e)
        # still continue, user can set webhook manually

    yield

    # Stop PTB app gracefully
    await telegram_app.stop()
    await telegram_app.shutdown()


fastapi_app = FastAPI(lifespan=lifespan)


@fastapi_app.get("/")
async def root():
    return {"ok": True, "service": "telegram-finance-bot"}


@fastapi_app.post("/webhook")
async def webhook(request: Request):
    data = await request.json()
    update = Update.de_json(data, telegram_app.bot)
    await telegram_app.process_update(update)
    return {"ok": True}
