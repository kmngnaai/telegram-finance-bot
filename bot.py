import os
import re
from datetime import datetime
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
# CONFIG
# =========================
OWNER_USERNAME = "ltkngan198"   # username Telegram (KHÔNG @)
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

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
# TELEGRAM APPLICATION
# =========================
application = ApplicationBuilder().token(BOT_TOKEN).build()

# =========================
# FASTAPI APP (BẮT BUỘC CÓ TÊN NÀY)
# =========================
fastapi_app = FastAPI()

# =========================
# FASTAPI LIFECYCLE (CHUẨN)
# =========================
@fastapi_app.on_event("startup")
async def on_startup():
    await application.initialize()
    await application.start()

@fastapi_app.on_event("shutdown")
async def on_shutdown():
    await application.stop()

# =========================
# /start
# =========================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_text(
        "👋 Chào bạn!\nChọn chức năng bên dưới ⬇️",
        reply_markup=MAIN_MENU
    )

# =========================
# /help
# =========================
async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📌 HƯỚNG DẪN SỬ DỤNG BOT\n\n"
        "✍️ Ghi thu / chi:\n"
        "• 20K CF\n"
        "• +1M LUONG\n"
        "• 20260101 20K CF\n"
        "• Có thể nhiều dòng\n\n"
        "📊 Báo cáo:\n"
        "• Tổng kết ngày (menu)\n"
        "• Tổng kết tháng (menu)\n"
        "• /year 2026\n"
        "• /year 2026 @username\n\n"
        "ℹ️ Ghi chú:\n"
        "• K = nghìn | M = triệu\n"
        "• Thu: số dương | Chi: số âm\n",
        reply_markup=MAIN_MENU
    )

# =========================
# PARSE AMOUNT
# =========================
def parse_amount(text: str) -> int:
    text = text.upper().replace(",", "")
    m = re.search(r"([+-]?\d+(?:\.\d+)?)([KM]?)", text)
    if not m:
        return 0
    num = float(m.group(1))
    unit = m.group(2)
    if unit == "K":
        num *= 1_000
    elif unit == "M":
        num *= 1_000_000
    return int(num)

# =========================
# PARSE LINES
# =========================
def parse_lines(text: str):
    results = []
    lines = text.strip().splitlines()
    for line in lines:
        date_match = re.match(r"^(\d{8})\s+(.*)$", line)
        if date_match:
            date = datetime.strptime(date_match.group(1), "%Y%m%d").date()
            content = date_match.group(2)
        else:
            date = datetime.today().date()
            content = line

        amount = parse_amount(content)
        category = re.sub(r"[+-]?\d+(\.\d+)?[KM]?", "", content, flags=re.I).strip()
        if amount != 0 and category:
            results.append((date, amount, category))
    return results

# =========================
# HANDLE TEXT (ghi thu/chi)
# =========================
async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()

    if text in ["➕ Ghi thu", "➖ Ghi chi"]:
        context.user_data["mode"] = "thu" if "thu" in text else "chi"
        await update.message.reply_text(
            f"✍️ Đang ghi {'THU' if context.user_data['mode']=='thu' else 'CHI'}\n"
            "Nhập nội dung:"
        )
        return

    if text in ["📊 Tổng kết ngày", "📅 Tổng kết tháng", "📈 Tổng kết năm"]:
        if "năm" in text:
            await update.message.reply_text("📌 Gõ: /year 2026")
        elif "tháng" in text:
            await summary_month(update, context)
        else:
            await summary_day(update, context)
        return

    if text == "ℹ️ Help":
        await help_cmd(update, context)
        return

    mode = context.user_data.get("mode")
    if not mode:
        return

    entries = parse_lines(text)
    if not entries:
        await update.message.reply_text("❌ Sai định dạng.\nVí dụ: 20K CF | +1M LUONG")
        return

    count = 0
    for date, amount, category in entries:
        if mode == "chi" and amount > 0:
            amount = -amount
        append_expense(
            date=str(date),
            user=update.effective_user.username,
            amount=amount,
            category=category
        )
        count += 1

    await update.message.reply_text(f"✅ Ghi thành công: {count} dòng")
    context.user_data.clear()

# =========================
# SUMMARY DAY
# =========================
async def summary_day(update: Update, context: ContextTypes.DEFAULT_TYPE):
    today = datetime.today().date()
    rows = get_all_rows()
    thu = chi = 0
    for r in rows:
        if r["date"] == str(today):
            if r["amount"] > 0:
                thu += r["amount"]
            else:
                chi += abs(r["amount"])
    await update.message.reply_text(
        f"📊 TỔNG KẾT NGÀY\n"
        f"💰 Thu: {thu:,}\n"
        f"💸 Chi: {chi:,}\n"
        f"📉 Còn: {thu-chi:,}"
    )

# =========================
# SUMMARY MONTH
# =========================
async def summary_month(update: Update, context: ContextTypes.DEFAULT_TYPE):
    now = datetime.today()
    rows = get_all_rows()
    thu = chi = 0
    for r in rows:
        d = datetime.strptime(r["date"], "%Y-%m-%d")
        if d.year == now.year and d.month == now.month:
            if r["amount"] > 0:
                thu += r["amount"]
            else:
                chi += abs(r["amount"])
    await update.message.reply_text(
        f"📅 TỔNG KẾT THÁNG\n"
        f"💰 Thu: {thu:,}\n"
        f"💸 Chi: {chi:,}\n"
        f"📉 Còn: {thu-chi:,}"
    )

# =========================
# /year YYYY [@user]
# =========================
async def summary_year(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args
    if not args:
        await update.message.reply_text("❗ Ví dụ: /year 2026")
        return

    year = int(args[0])
    if len(args) > 1 and update.effective_user.username == OWNER_USERNAME:
        target_user = args[1].replace("@", "")
    else:
        target_user = update.effective_user.username

    rows = get_all_rows()
    monthly = defaultdict(lambda: {"thu": 0, "chi": 0})

    for r in rows:
        if r["user"] != target_user:
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
        lines.append(f"• Tháng {m:02d}: Thu {t:,} | Chi {c:,} | Còn {t-c:,}")

    worst = max(monthly, key=lambda x: monthly[x]["chi"])
    best = max(monthly, key=lambda x: monthly[x]["thu"] - monthly[x]["chi"])

    await update.message.reply_text(
        f"📈 BÁO CÁO THU–CHI NĂM {year}\n"
        f"👤 User: @{target_user}\n\n"
        f"💰 Tổng thu: {total_thu:,}\n"
        f"💸 Tổng chi: {total_chi:,}\n"
        f"📉 Còn lại: {total_thu-total_chi:,}\n\n"
        "📅 CHI TIẾT THEO THÁNG:\n"
        + "\n".join(lines) +
        f"\n\n📌 ĐÁNH GIÁ:\n"
        f"🔥 Tháng chi nhiều nhất: {worst:02d}\n"
        f"💚 Tháng tiết kiệm tốt nhất: {best:02d}"
    )

# =========================
# REGISTER HANDLERS
# =========================
application.add_handler(CommandHandler("start", start))
application.add_handler(CommandHandler("help", help_cmd))
application.add_handler(CommandHandler("year", summary_year))
application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

# =========================
# WEBHOOK ENDPOINT
# =========================
@fastapi_app.post("/webhook")
async def telegram_webhook(req: Request):
    update = Update.de_json(await req.json(), application.bot)
    await application.process_update(update)
    return {"ok": True}
