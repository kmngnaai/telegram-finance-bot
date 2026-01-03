import gspread
from google.oauth2.service_account import Credentials
from datetime import date

# =====================
# CONFIG
# =====================
SERVICE_ACCOUNT_FILE = "service_account.json"
SPREADSHEET_ID = "1MSplGrToXY0FayBmKdWoC0GAL9-IvacwgfwgOWRy6cQ"
SHEET_NAME = "Sheet1"

# =====================
# CONNECT
# =====================
SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]
creds = Credentials.from_service_account_file(
    SERVICE_ACCOUNT_FILE, scopes=SCOPES
)
client = gspread.authorize(creds)
sheet = client.open_by_key(SPREADSHEET_ID).worksheet(SHEET_NAME)

# =====================
# APPEND ROW
# =====================
def append_expense(date, user, amount, category):
    sheet.append_row(
        [
            date.strftime("%Y-%m-%d"),
            user or "unknown",
            amount,
            category,
        ],
        value_input_option="USER_ENTERED",
    )

# =====================
# READ ALL DATA
# =====================
def get_all_rows():
    return sheet.get_all_records()
