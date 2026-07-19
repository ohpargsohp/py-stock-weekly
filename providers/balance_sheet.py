import logging
import sqlite3
from datetime import date, datetime

import requests

import config
from core.base import DataProvider

log = logging.getLogger(__name__)
HEADERS = {"User-Agent": "Mozilla/5.0"}


def _to_num_or_none(s):
    s = str(s).strip()
    if s in ("", "-"):
        return None
    return float(s)


def _roc_date_to_ymd(roc_date):
    """'1150719' -> '20260719'"""
    if not roc_date or len(roc_date) < 6:
        return None
    return f"{int(roc_date[:-4]) + 1911:04d}{roc_date[-4:-2]}{roc_date[-2:]}"


def _expected_period(date_str):
    """t187ap07_L_ci 沒有日期參數,永遠只回傳「目前已揭露的最新一期」,
    同一期重複打 API 拿到的都是同一份資料。依台灣財報法定申報截止日
    (Q1 5/15、H1(Q2) 8/14、Q3 11/14、年報(Q4) 次年 3/31)反推 date_str
    當下「應該」是哪一期,用來跟資料庫已有的資料比對,不用每天都打 API。"""
    d = datetime.strptime(date_str, "%Y%m%d").date()
    y = d.year
    if d <= date(y, 3, 31):
        return f"{y - 1}Q3"
    if d <= date(y, 5, 15):
        return f"{y - 1}Q4"
    if d <= date(y, 8, 14):
        return f"{y}Q1"
    if d <= date(y, 11, 14):
        return f"{y}Q2"
    return f"{y}Q3"


class BalanceSheetProvider(DataProvider):
    """上市公司資產負債表-一般業(t187ap07_L_ci),僅取 config.WATCHLIST 內的公司。
    負債比率由這支 provider 自行計算(TWSE 只給資產/負債/權益總額等原始金額,
    不會直接給比率)。金融、證券期貨、保險、金控等特殊產業有各自的資產負債表格式,
    目前不支援,理由同 providers/financial_income.py。ETF(如 0050)不編製財報,
    不會有對應資料列。"""

    name = "balance_sheet"
    pk = ["period", "stock_id"]
    schema = {
        "period": "TEXT",               # 例如 '2026Q1'
        "stock_id": "TEXT",
        "stock_name": "TEXT",
        "fiscal_year": "TEXT",
        "fiscal_quarter": "TEXT",
        "current_assets": "REAL",       # 流動資產(仟元)
        "total_assets": "REAL",         # 資產總額(仟元)
        "current_liabilities": "REAL",  # 流動負債(仟元)
        "total_liabilities": "REAL",    # 負債總額(仟元)
        "total_equity": "REAL",         # 權益總額(仟元)
        "debt_ratio": "REAL",           # 負債比率(%),自行計算 = 負債總額/資產總額
        "book_value_per_share": "REAL",  # 每股參考淨值(元)
        "report_date": "TEXT",          # 出表日期 YYYYMMDD
    }

    def _existing_rows(self, period):
        """main.py 在呼叫 fetch() 前已先 ensure_table,故此時表一定存在(可能是空的)。
        用獨立連線唯讀查詢,不影響 main.py 自己的 Storage 連線。"""
        conn = sqlite3.connect(config.DB_PATH)
        conn.row_factory = sqlite3.Row
        placeholders = ",".join("?" * len(config.WATCHLIST))
        rows = conn.execute(
            f"SELECT * FROM {self.name} WHERE period = ? AND stock_id IN ({placeholders})",
            [period, *config.WATCHLIST.keys()],
        ).fetchall()
        conn.close()
        return [dict(r) for r in rows]

    def fetch(self, date_str):
        expected_period = _expected_period(date_str)
        existing = self._existing_rows(expected_period)
        if existing:
            log.info(f"資產負債表已是最新一期({expected_period}),資料庫已有資料,略過抓取")
            return existing

        url = "https://openapi.twse.com.tw/v1/opendata/t187ap07_L_ci"
        try:
            r = requests.get(url, headers=HEADERS, timeout=20)
            data = r.json()
        except (requests.RequestException, ValueError) as e:
            log.warning(f"財報(資產負債表)抓取失敗: {e}")
            return []

        out = []
        for row in data:
            sid = row.get("公司代號", "").strip()
            if sid not in config.WATCHLIST:
                continue
            fiscal_year_roc = row.get("年度", "").strip()
            fiscal_quarter = row.get("季別", "").strip()
            total_assets = _to_num_or_none(row.get("資產總額"))
            if not fiscal_year_roc or total_assets is None:
                continue

            fiscal_year = str(int(fiscal_year_roc) + 1911)
            total_liabilities = _to_num_or_none(row.get("負債總額"))

            out.append({
                "period": f"{fiscal_year}Q{fiscal_quarter}",
                "stock_id": sid,
                "stock_name": config.WATCHLIST[sid],
                "fiscal_year": fiscal_year,
                "fiscal_quarter": fiscal_quarter,
                "current_assets": _to_num_or_none(row.get("流動資產")),
                "total_assets": total_assets,
                "current_liabilities": _to_num_or_none(row.get("流動負債")),
                "total_liabilities": total_liabilities,
                "total_equity": _to_num_or_none(row.get("權益總額")),
                "debt_ratio": round(total_liabilities / total_assets * 100, 2)
                    if total_liabilities is not None and total_assets else None,
                "book_value_per_share": _to_num_or_none(row.get("每股參考淨值")),
                "report_date": _roc_date_to_ymd(row.get("出表日期", "")),
            })
        return out

    def describe(self, rows):
        if not rows:
            return None
        return "\n".join(
            f"   {r['stock_name']}({r['stock_id']}) {r['period']} 負債比率 "
            f"{r['debt_ratio']:.1f}% | 每股淨值 {r['book_value_per_share']}"
            if r["debt_ratio"] is not None else
            f"   {r['stock_name']}({r['stock_id']}) {r['period']} 負債比率 —"
            for r in rows
        )
