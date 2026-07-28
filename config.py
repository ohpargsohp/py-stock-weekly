# 觀察名單拆到 watchlist.py(個人清單,不進版控),複製 watchlist.example.py 建立
from watchlist import WATCHLIST

DB_PATH = "data/chip.db"
EXCEL_PATH = "data/chip_report.xlsx"
JSON_PATH = "data/weekly_scan.json"
SLEEP_SEC = 3  # API 呼叫間隔,禮貌性速率控制