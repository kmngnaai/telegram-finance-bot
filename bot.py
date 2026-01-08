import os
import re
import json
import logging
from datetime import datetime, date
from collections import defaultdict
from typing import Optional, Tuple, List

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

# Đảm bảo file google_sheet_store.py nằm cùng thư mục
from google_sheet_store import append_expense, get_all_rows

# =========================
# LOGGING
# =========================
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("finance-bot")

# =========================
# CONFIG
# =========================
OWNER_USERNAME = os.getenv("OWNER_USERNAME", "ltkngan198").lstrip("@")
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
RENDER_EXTERNAL_URL = (os.getenv("RENDER_EXTERNAL_URL") or "").rstrip("/")
WEBHOOK_PATH = "/webhook"
WEBHOOK_URL = f"{RENDER_EXTERNAL_URL}{WEBHOOK_PATH}" if RENDER_EXTERNAL_URL else ""

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
    resize_keyboard=True
)

# =========================
# HELP TEXT
# =========================
HELP_TEXT = (
    "📌 HƯỚNG DẪN SỬ DỤNG BOT\n\n"
    "✅ Quy ước Thu/Chi (KHÔNG cần bấm menu vẫn dùng được):\n"
    "• Mặc định KHÔNG có dấu +/− => CHI\n"
    "   - VD: 500K SPA  => Chi 500,000 (SPA)\n"
    "• Có dấu + => THU\n"
    "   - VD: +4M LUONG => Thu 4,000,000 (LUONG)\n"
    "• Có dấu - => CHI\n"
    "   - VD: -20K CF   => Chi 20,000 (CF)\n\n"
    "📅 Ghi theo ngày:\n"
    "• 20260104 500K SPA     => Chi 500,000 ngày 04/01/2026\n"
    "• 20260104 +4M LUONG    => Thu 4,000,000 ngày 04/01/2026\n\n"
    "🧾 Nhiều dòng (mỗi dòng = 1 giao dịch):\n"
    "500K SPA\n"
    "+4M LUONG\n"
    "-20K CF\n\n"
    "📊 Báo cáo:\n"
    "• 📊 Tổng kết ngày (menu)  (hôm nay)\n"
    "• 📅 Tổng kết tháng (menu) (tháng này)\n"
    "• 📈 Tổng kết năm (menu) hoặc gõ: /year 2026\n"
    "• Owner có thể xem user khác: /year 2026 @username\n\n"
    "🔤 K = nghìn | M = triệu\n"
)

# =========================
# /start
# =========================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_text(
        "👋 Chào bạn!\nChọn chức năng bên dưới ⬇️\n\n"
        "💡 Tip: Bạn có thể nhập thẳng:\n"
        "• 500K SPA (mặc định CHI)\n"
        "• +4M LUONG (THU)\n"
        "• 20260104 500K SPA (ghi theo ngày)",
        reply_markup=MAIN_MENU
    )

# =========================
# /help
# =========================
async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(HELP_TEXT, reply_markup=MAIN_MENU)

# =========================
# PARSE AMOUNT + SIGN
# =========================
_AMOUNT_RE = re.compile(r"(?i)\b([+-]?)\s*(\d+(?:\.\d+)?)\s*([KM]?)\b")

def _parse_amount_with_sign(text: str) -> Tuple[int, Optional[str]]:
    """
    Returns (abs_amount_int, sign_char_or_None)
    sign_char: '+', '-', or None if not explicitly provided.
    """
    s = text.upper().replace(",", "")
    m = _AMOUNT_RE.search(s)
    if not m:
        return 0, None
    sign = m.group(1) or None
    num = float(m.group(2))
    unit = (m.group(3) or "").upper()

    if unit == "K":
        num *= 1_000
    elif unit == "M":
        num *= 1_000_000

    amt = int(num)
    if amt == 0:
        return 0, sign
    return abs(amt), sign

def _strip_amount(text: str) -> str:
    """Remove the first amount token from text to get category."""
    return _AMOUNT_RE.sub("", text, count=1).strip()

# =========================
# PARSE LINES
# =========================
_DATE_PREFIX_RE = re.compile(r"^(\d{8})\s+(.*)$")

def parse_lines(text: str, fallback_mode: Optional[str]) -> List[Tuple[date, int, str]]:
    """
    Each line => (date, signed_amount, category)
    Rules:
      - If amount has '+' => THU (positive)
      - If amount has '-' => CHI (negative)
      - If no sign:
          - if fallback_mode == 'thu' => positive
          - elif fallback_mode == 'chi' => negative
          - else => default CHI (negative)
    """
    results: List[Tuple[date, int, str]] = []
    lines = [ln.strip() for ln in text.strip().splitlines() if ln.strip()]

    for line in lines:
        m = _DATE_PREFIX_RE.match(line)
        if m:
            d = datetime.strptime(m.group(1), "%Y%m%d").date()
            content = m.group(2).strip()
        else:
            d = datetime.today().date()
            content = line

        abs_amt, sign = _parse_amount_with_sign(content)
        if abs_amt == 0:
            continue

        category = _strip_amount(content)
        if not category:
            continue

        # Decide final sign
        if sign == "+":
            amount = abs_amt
        elif sign == "-":
            amount = -abs_amt
        else:
            # no explicit sign -> use mode if set, else default CHI
            if fallback_mode == "thu":
                amount = abs_amt
            elif fallback_mode == "chi":
                amount = -abs_amt
            else:
                amount = -abs_amt  # DEFAULT = CHI

        results.append((d, int(amount), category))
    return results

# =========================
# SUMMARY HELPERS
# =========================
def _fmt_money(n: int) -> str:
    return f"{n:,}"

def _safe_username(update: Update) -> str:
    u = update.effective_user
    return (u.username or str(u.id))

# =========================
# SUMMARY DAY (today OR yyyymmdd)
# =========================
async def summary_day(update: Update, context: ContextTypes.DEFAULT_TYPE, yyyymmdd: Optional[str] = None):
    if yyyymmdd:
        try:
            target = datetime.strptime(yyyymmdd, "%Y%m%d").date()
        except Exception:
            await update.message.reply_text("❗ Sai định dạng ngày. Ví dụ: 20260101")
            return
    else:
        target = datetime.today().date()

    rows = get_all_rows()
    thu = chi = 0
    for r in rows:
        if r.get("date") == str(target):
            amt = int(r.get("amount", 0))
            if amt > 0:
                thu += amt
            else:
                chi += abs(amt)

    await update.message.reply_text(
        f"📊 TỔNG KẾT NGÀY ({target.strftime('%d/%m/%Y')})\n"
        f"💰 Thu: {_fmt_money(thu)}\n"
        f"💸 Chi: {_fmt_money(chi)}\n"
        f"📉 Còn: {_fmt_money(thu - chi)}",
        reply_markup=MAIN_MENU
    )

# =========================
# SUMMARY MONTH (this month OR yyyymm)
# =========================
async def summary_month(update: Update, context: ContextTypes.DEFAULT_TYPE, yyyymm: Optional[str] = None):
    if yyyymm:
        if not re.fullmatch(r"\d{6}", yyyymm):
            await update.message.reply_text("❗ Sai định dạng tháng. Ví dụ: 202601")
            return
        y = int(yyyymm[:4])
        m = int(yyyymm[4:])
        if m < 1 or m > 12:
            await update.message.reply_text("❗ Tháng không hợp lệ. Ví dụ: 202601")
            return
        target_year, target_month = y, m
    else:
        now = datetime.today()
        target_year, target_month = now.year, now.month

    rows = get_all_rows()
    thu = chi = 0
    for r in rows:
        try:
            d = datetime.strptime(r["date"], "%Y-%m-%d")
        except Exception:
            continue
        if d.year == target_year and d.month == target_month:
            amt = int(r.get("amount", 0))
            if amt > 0:
                thu += amt
            else:
                chi += abs(amt)

    await update.message.reply_text(
        f"📅 TỔNG KẾT THÁNG ({target_month:02d}/{target_year})\n"
        f"💰 Thu: {_fmt_money(thu)}\n"
        f"💸 Chi: {_fmt_money(chi)}\n"
        f"📉 Còn: {_fmt_money(thu - chi)}",
        reply_markup=MAIN_MENU
    )

# =========================
# /year YYYY [@user]
# =========================
async def summary_year(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args
    if not args:
        await update.message.reply_text("❗ Ví dụ: /year 2026", reply_markup=MAIN_MENU)
        return

    # Parse year
    try:
        year = int(args[0])
    except Exception:
        await update.message.reply_text("❗ Năm không hợp lệ. Ví dụ: /year 2026", reply_markup=MAIN_MENU)
        return

    requester = _safe_username(update)

    # Target user logic:
    # - default: user's own
    # - if owner uses /year 2026 @user -> show that user
    target_user = requester
    if len(args) > 1 and requester == OWNER_USERNAME:
        target_user = args[1].replace("@", "").strip() or requester

    rows = get_all_rows()
    monthly = defaultdict(lambda: {"thu": 0, "chi": 0})

    for r in rows:
        if (r.get("user") or "") != target_user:
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
        await update.message.reply_text(f"❌ Không có dữ liệu năm {year} cho @{target_user}.", reply_markup=MAIN_MENU)
        return

    total_thu = total_chi = 0
    lines = []
    for m in range(1, 13):
        t = monthly[m]["thu"]
        c = monthly[m]["chi"]
        if t == 0 and c == 0:
            continue
        total_thu += t
        total_chi += c
        lines.append(f"• Tháng {m:02d}: Thu {_fmt_money(t)} | Chi {_fmt_money(c)} | Còn {_fmt_money(t - c)}")

    # Worst/best month among months that have any data
    months_with_data = [m for m in monthly.keys() if monthly[m]["thu"] != 0 or monthly[m]["chi"] != 0]
    worst = max(months_with_data, key=lambda x: monthly[x]["chi"])
    best = max(months_with_data, key=lambda x: monthly[x]["thu"] - monthly[x]["chi"])

    # Evaluation line
    eval_line = "✅ Thu > Chi cả năm" if total_thu >= total_chi else "⚠️ Chi > Thu cả năm"

    await update.message.reply_text(
        f"📈 BÁO CÁO THU–CHI NĂM {year}\n"
        f"👤 User: @{target_user}\n\n"
        f"💰 Tổng thu: {_fmt_money(total_thu)}\n"
        f"💸 Tổng chi: {_fmt_money(total_chi)}\n"
        f"📉 Còn lại: {_fmt_money(total_thu - total_chi)}\n\n"
        f"📅 CHI TIẾT THEO THÁNG:\n" + ("\n".join(lines) if lines else "• (Không có dòng nào)") +
        f"\n\n📌 ĐÁNH GIÁ:\n"
        f"{eval_line}\n"
        f"🔥 Tháng chi nhiều nhất: {worst:02d}\n"
        f"💚 Tháng tiết kiệm tốt nhất: {best:02d}",
        reply_markup=MAIN_MENU
    )

# =========================
# HANDLE TEXT (menu + input)
# =========================
async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (update.message.text or "").strip()
    if not text:
        return

    # Menu buttons
    if text in ["➕ Ghi thu", "➖ Ghi chi"]:
        context.user_data["mode"] = "thu" if "thu" in text else "chi"
        await update.message.reply_text(
            f"✍️ Đang ghi {'THU' if context.user_data['mode']=='thu' else 'CHI'}\n"
            "Nhập nội dung (có thể nhiều dòng). Ví dụ:\n"
            "• 20K CF\n"
            "• 20260101 500K SPA\n"
            "• +4M LUONG\n",
            reply_markup=MAIN_MENU
        )
        return

    if text in ["📊 Tổng kết ngày", "📅 Tổng kết tháng", "📈 Tổng kết năm"]:
        if "năm" in text:
            await update.message.reply_text("📌 Gõ: /year 2026", reply_markup=MAIN_MENU)
        elif "tháng" in text:
            await summary_month(update, context)
        else:
            await summary_day(update, context)
        return

    if text == "ℹ️ Help":
        await help_cmd(update, context)
        return

    # Special quick commands in plain text (optional)
    m_day = re.fullmatch(r"(?i)(day|ngay)\s+(\d{8})", text)
    if m_day:
        await summary_day(update, context, m_day.group(2))
        return
    m_month = re.fullmatch(r"(?i)(month|thang)\s+(\d{6})", text)
    if m_month:
        await summary_month(update, context, m_month.group(2))
        return

    # Main input: parse & append
    mode = context.user_data.get("mode")  # can be None
    entries = parse_lines(text, fallback_mode=mode)

    if not entries:
        await update.message.reply_text(
            "❌ Sai định dạng.\n\n"
            "✅ Ví dụ đúng:\n"
            "• 500K SPA    (mặc định CHI)\n"
            "• +4M LUONG   (THU)\n"
            "• 20260104 500K SPA\n"
            "• -20K CF\n",
            reply_markup=MAIN_MENU
        )
        return

    username = _safe_username(update)
    ok = 0
    errors = 0

    for d, amount, category in entries:
        try:
            # ================================================================
            # ✅ ĐÃ FIX LỖI 1 + LỖI 2:
            # - Truyền 'd' (datetime.date) trực tiếp, KHÔNG dùng str(d)
            # - Dùng positional arguments cho đúng hàm bên google_sheet_store
            # ================================================================
            append_expense(d, username, int(amount), category)
            ok += 1
        except Exception as e:
            errors += 1
            logger.exception("append_expense failed: %s", e)

    if errors == 0:
        await update.message.reply_text(
            f"✅ Ghi thành công: {ok} dòng\n"
            f"👤 @{username}\n"
            f"📌 Mẹo: Không có dấu +/− thì mặc định là CHI.",
            reply_markup=MAIN_MENU
        )
    else:
        await update.message.reply_text(
            f"⚠️ Ghi được {ok} dòng, lỗi {errors} dòng.\n"
            f"Vui lòng xem Logs Render để biết chi tiết.",
            reply_markup=MAIN_MENU
        )

# =========================
# BUILD TELEGRAM APPLICATION
# =========================
def build_application() -> Application:
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("year", summary_year))

    # Keep menu text + free input
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    return app

application: Application = build_application()

# =========================
# FASTAPI (Render Web Service)
# =========================
fastapi_app = FastAPI()

@fastapi_app.get("/")
async def health():
    return {"ok": True, "service": "telegram-finance-bot"}

@fastapi_app.on_event("startup")
async def on_startup():
    # Start PTB app
    await application.initialize()
    await application.start()
    logger.info("Application started")

    # Set webhook (only if Render external url available)
    if WEBHOOK_URL:
        await application.bot.set_webhook(url=WEBHOOK_URL, allowed_updates=Update.ALL_TYPES)
        logger.info("Webhook set to %s", WEBHOOK_URL)
    else:
        logger.warning("RENDER_EXTERNAL_URL not set; webhook was not configured automatically.")

@fastapi_app.on_event("shutdown")
async def on_shutdown():
    await application.stop()
    await application.shutdown()
    logger.info("Application stopped")

@fastapi_app.post(WEBHOOK_PATH)
async def telegram_webhook(request: Request):
    payload = await request.json()
    update = Update.de_json(payload, application.bot)
    await application.process_update(update)
    return {"ok": True}
