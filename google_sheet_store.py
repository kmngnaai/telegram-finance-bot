import gspread
from google.oauth2.service_account import Credentials
from datetime import date

# =====================
# GOOGLE SHEETS CONFIG
# =====================

# ⚠️ Render Secret File được mount tại /etc/secrets/
SERVICE_ACCOUNT_FILE = "/etc/secrets/service_account.json"

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

# 🔴 ID Google Sheet của bạn (GIỮ NGUYÊN)
SPREADSHEET_ID = "1MSplGrToXY0FayBmKdWoC0GAL9-IvacwgfwgOWRy6cQ"
SHEET_NAME = "Sheet1"

# =====================
# INIT CLIENT
# =====================
creds = Credentials.from_service_account_file(
    SERVICE_ACCOUNT_FILE,
    scopes=SCOPES
)

client = gspread.authorize(creds)
sheet = client.open_by_key(SPREADSHEET_ID).worksheet(SHEET_NAME)

# =====================
# APPEND EXPENSE
# =====================
def append_expense(expense_date, user, amount, category):
    """
    expense_date: datetime.date
    user: telegram username
    amount: int (+ thu, - chi)
    category: string
    """
    sheet.append_row(
        [
            expense_date.strftime("%Y-%m-%d"),
            user or "unknown",
            int(amount),
            category,
        ],
        value_input_option="USER_ENTERED",
    )

# =====================
# GET ALL ROWS
# =====================
def get_all_rows():
    """
    Return list of dict:
    {
        date: YYYY-MM-DD,
        user: string,
        amount: int,
        category: string
    }
    """
    records = sheet.get_all_records()
    rows = []

    for r in records:
        try:
            rows.append(
                {
                    "date": str(r.get("date")),
                    "user": r.get("user"),
                    "amount": int(r.get("amount")),
                    "category": r.get("category"),
                }
            )
        except Exception:
            # Bỏ qua dòng lỗi
            continue

    return rows
