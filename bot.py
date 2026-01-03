import os
import re
from datetime import datetime, date
from dotenv import load_dotenv
from collections import defaultdict

from telegram import (
    Update,
    ReplyKeyboardMarkup,
    KeyboardButton,
)
from telegram.ext import (
    ApplicationBuilder,
    MessageHandler,
    CommandHandler,
    ContextTypes,
    filters,
)

from google_sheet_store import append_expense, get_all_rows

# =====================
# CONFIG
# =====================
OWNER_USERNAME = "ltkngan198"  # 🔥 đổi thành username Telegram của bạn (KHÔNG @)

# =====================
# LOAD ENV
# =====================
load_dotenv()
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

# =====================
# MENU
# =====================
def main_menu():
    return ReplyKeyboardMarkup(
        [
            [KeyboardButton("📒 Hướng dẫn")],
            [KeyboardButton("➕ Ghi thu"), KeyboardButton("➖ Ghi chi")],
            [KeyboardButton("📊 Tổng kết tháng"), KeyboardButton("📊 Tổng kết ngày")],
            [KeyboardButton("📊 Báo cáo năm")],
        ],
        resize_keyboard=True,
    )

# =====================
# PARSE AMOUNT
# =====================
def parse_amount(text: str) -> int:
    text = text.strip().upper()

    sign = -1
    if text.startswith("+"):
        sign = 1
        text = text[1:]

    match = re.fullmatch(r"(\d+(?:\.\d+)?)(K|M)?", text)
    if not match:
        raise ValueError

    number = float(match.group(1))
    unit = match.group(2)

    if unit == "K":
        number *= 1_000
    elif unit == "M":
        number *= 1_000_000

    return int(number * sign)

# =====================
# PARSE DATE
# =====================
def parse_date_and_rest(parts):
    if re.fullmatch(r"\d{8}", parts[0]):
        d = datetime.strptime(parts[0], "%Y%m%d").date()
        return d, parts[1:]
    return date.today(), parts

# =====================
# /START
# =====================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 Chào bạn!\nChọn chức năng bên dưới 👇",
        reply_markup=main_menu(),
    )

# =====================
# /HELP
# =====================
async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📒 HƯỚNG DẪN\n\n"
        "➖ Ghi CHI:\n20K CF\n1M ĂN\n\n"
        "➕ Ghi THU:\n+5M LƯƠNG\n+200K THƯỞNG\n\n"
        "📊 Báo cáo:\n"
        "/summary 202601\n"
        "/summary 20260101\n"
        "/year 2026",
        reply_markup=main_menu(),
    )

# =====================
# /SUMMARY (YYYYMM / YYYYMMDD) – CHỈ CỦA USER
# =====================
async def summary(update: Update, context: ContextTypes.DEFAULT_TYPE):
    rows = get_all_rows()
    caller = update.effective_user.username

    income = 0
    expense = 0

    target_year = date.today().year
    target_month = date.today().month
    target_day = None

    if context.args:
        arg = context.args[0]
        if re.fullmatch(r"\d{8}", arg):
            target_day = datetime.strptime(arg, "%Y%m%d").date()
            target_year = target_day.year
            target_month = target_day.month
        elif re.fullmatch(r"\d{6}", arg):
            target_year = int(arg[:4])
            target_month = int(arg[4:6])
        else:
            await update.message.reply_text("❌ Dùng /summary 202601 hoặc /summary 20260101")
            return

    for r in rows:
        if r.get("user") != caller:
            continue

        d = datetime.strptime(r["date"], "%Y-%m-%d").date()
        amount = int(r["amount"])

        if target_day:
            if d != target_day:
                continue
        else:
            if d.year != target_year or d.month != target_month:
                continue

        if amount > 0:
            income += amount
        else:
            expense += abs(amount)

    if income == 0 and expense == 0:
        await update.message.reply_text("❗ Không có dữ liệu")
        return

    title = (
        f"📊 Tổng kết ngày {target_day.strftime('%d/%m/%Y')}"
        if target_day
        else f"📊 Tổng kết tháng {target_month:02d}/{target_year}"
    )

    await update.message.reply_text(
        f"{title}\n\n"
        f"💰 Thu: {income:,} đ\n"
        f"💸 Chi: {expense:,} đ\n"
        f"🧮 Còn lại: {income - expense:,} đ"
    )

# =====================
# /YEAR YYYY [@user]
# =====================
async def year_report(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args or not re.fullmatch(r"\d{4}", context.args[0]):
        await update.message.reply_text("Dùng: /year 2026 [@username]")
        return

    year = int(context.args[0])
    caller = update.effective_user.username
    target_user = caller

    # OWNER xem user khác
    if len(context.args) >= 2:
        if caller != OWNER_USERNAME:
            await update.message.reply_text("⛔ Bạn không có quyền xem user khác")
            return
        target_user = context.args[1].lstrip("@")

    rows = get_all_rows()
    months = defaultdict(lambda: {"income": 0, "expense": 0})

    total_income = 0
    total_expense = 0

    for r in rows:
        if r.get("user") != target_user:
            continue

        d = datetime.strptime(r["date"], "%Y-%m-%d").date()
        if d.year != year:
            continue

        amount = int(r["amount"])

        if amount > 0:
            months[d.month]["income"] += amount
            total_income += amount
        else:
            months[d.month]["expense"] += abs(amount)
            total_expense += abs(amount)

    if total_income == 0 and total_expense == 0:
        await update.message.reply_text(f"❗ Không có dữ liệu năm {year}")
        return

    msg = (
        f"📊 BÁO CÁO THU–CHI NĂM {year}\n"
        f"👤 User: @{target_user}\n\n"
        f"💰 Tổng thu: {total_income:,} đ\n"
        f"💸 Tổng chi: {total_expense:,} đ\n"
        f"🧮 Còn lại: {total_income - total_expense:,} đ\n\n"
        "📅 CHI TIẾT THEO THÁNG:\n"
    )

    max_expense = 0
    max_month = None
    best_month = None
    best_balance = None

    for m in range(1, 13):
        inc = months[m]["income"]
        exp = months[m]["expense"]

        if inc == 0 and exp == 0:
            continue

        balance = inc - exp
        msg += f"• Tháng {m:02d}: Thu {inc:,} | Chi {exp:,} | Còn {balance:,}\n"

        if exp > max_expense:
            max_expense = exp
            max_month = m

        if best_balance is None or balance > best_balance:
            best_balance = balance
            best_month = m

    msg += "\n📌 ĐÁNH GIÁ:\n"
    msg += "✅ Thu > Chi cả năm\n" if total_income >= total_expense else "⚠️ Chi > Thu cả năm\n"
    if max_month:
        msg += f"🔥 Tháng chi nhiều nhất: {max_month:02d}\n"
    if best_month:
        msg += f"💚 Tháng tiết kiệm tốt nhất: {best_month:02d}"

    await update.message.reply_text(msg)

# =====================
# HANDLE MESSAGE
# =====================
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()

    if text == "📒 Hướng dẫn":
        await help_cmd(update, context)
        return

    if text == "📊 Tổng kết tháng":
        context.args = [date.today().strftime("%Y%m")]
        await summary(update, context)
        return

    if text == "📊 Tổng kết ngày":
        context.args = [date.today().strftime("%Y%m%d")]
        await summary(update, context)
        return

    if text == "📊 Báo cáo năm":
        context.args = [str(date.today().year)]
        await year_report(update, context)
        return

    if text == "➕ Ghi thu":
        await update.message.reply_text("+5M LƯƠNG\n+200K THƯỞNG")
        return

    if text == "➖ Ghi chi":
        await update.message.reply_text("20K CF\n1M ĂN")
        return

    # ===== GHI SỔ =====
    lines = [l for l in text.splitlines() if l.strip()]
    success = 0
    errors = []

    for line in lines:
        try:
            parts = line.split()
            d, rest = parse_date_and_rest(parts)
            amount = parse_amount(rest[0])
            category = " ".join(rest[1:])

            append_expense(d, update.effective_user.username, amount, category)
            success += 1
        except Exception:
            errors.append(line)

    msg = f"✅ Ghi sổ thành công: {success} dòng"
    if errors:
        msg += "\n❌ Lỗi:\n" + "\n".join(errors)

    await update.message.reply_text(msg)

# =====================
# MAIN
# =====================
def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("summary", summary))
    app.add_handler(CommandHandler("year", year_report))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    app.run_polling()

if __name__ == "__main__":
    main()
