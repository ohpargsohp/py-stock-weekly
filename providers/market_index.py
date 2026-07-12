import logging

import requests

from core.base import DataProvider

log = logging.getLogger(__name__)
HEADERS = {"User-Agent": "Mozilla/5.0"}


def _to_num(s):
    return float(str(s).replace(",", "").strip() or 0)


def _roc_to_ymd(roc_date):
    """'115/07/09' -> '20260709'"""
    y, m, d = roc_date.split("/")
    return f"{int(y) + 1911:04d}{m}{d}"


class MarketIndexProvider(DataProvider):
    """大盤(發行量加權股價指數)收盤/漲跌/成交量(FMTQIK,月資料依日期過濾)。"""

    name = "market_index"
    pk = ["trade_date"]
    schema = {
        "trade_date": "TEXT",
        "close": "REAL",
        "change_pts": "REAL",
        "change_pct": "REAL",
        "volume_yi": "REAL",   # 成交金額,億元
    }

    def fetch(self, date_str):
        url = f"https://www.twse.com.tw/rwd/zh/afterTrading/FMTQIK?response=json&date={date_str}"
        r = requests.get(url, headers=HEADERS, timeout=20)
        r.encoding = "utf-8"
        j = r.json()
        if j.get("stat") != "OK" or not j.get("data"):
            log.warning(f"{date_str} 大盤指數無資料(可能休市)")
            return []

        row = next((r for r in j["data"] if _roc_to_ymd(r[0]) == date_str), None)
        if not row:
            return []

        close = _to_num(row[4])
        change_pts = _to_num(row[5])
        prev_close = close - change_pts
        return [{
            "trade_date": date_str,
            "close": close,
            "change_pts": change_pts,
            "change_pct": round(change_pts / prev_close * 100, 2) if prev_close else 0,
            "volume_yi": round(_to_num(row[2]) / 1e8, 2),
        }]

    def describe(self, rows):
        if not rows:
            return None
        m = rows[0]
        return (f"📈 {m['trade_date']} 大盤指數 {m['close']:,.2f} "
                f"({m['change_pts']:+.2f}, {m['change_pct']:+.2f}%) "
                f"成交金額 {m['volume_yi']:,.0f}億")
