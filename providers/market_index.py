import logging

import requests

from core.base import DataProvider

log = logging.getLogger(__name__)
HEADERS = {"User-Agent": "Mozilla/5.0"}

# FMTQIK 的成交金額官方註明「含大盤、零股、盤後定價及鉅額交易」,
# 是四類加總的總額,比媒體常引用的「一般交易時段」口徑要大一截。
# 這三支報表可以查到各自的「合計/總計」列,拿來扣減對照用。
AFTER_HOURS_URL = "https://www.twse.com.tw/rwd/zh/afterTrading/BFT41U?response=json&date={date}&selectType=ALL"
ODD_LOT_URL = "https://www.twse.com.tw/rwd/zh/afterTrading/TWT53U?response=json&date={date}&selectType=ALL"
BLOCK_TRADE_URL = "https://www.twse.com.tw/rwd/zh/block/BFIAUU?response=json&date={date}&selectType=S"


def _to_num(s):
    return float(str(s).replace(",", "").strip() or 0)


def _fetch_total_value(date_str, url, value_idx):
    """抓 TWSE 明細表,回傳表尾『合計/總計』列的成交金額(元)。抓不到就回 0(不影響大盤主數字)。"""
    try:
        r = requests.get(url.format(date=date_str), headers=HEADERS, timeout=20)
        r.encoding = "utf-8"
        j = r.json()
        for row in j.get("data", []):
            if any(c.strip() in ("合計", "總計") for c in row[:2]):
                return _to_num(row[value_idx])
    except Exception as e:
        log.warning(f"{date_str} 明細表抓取失敗({url}): {e}")
    return 0.0


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
        "volume_yi": "REAL",        # 成交金額,億元(FMTQIK 總額:大盤+零股+盤後定價+鉅額)
        "volume_yi_core": "REAL",   # 扣除零股/盤後定價/鉅額(單一證券)後,較接近媒體常引用的口徑
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
        volume_yi = round(_to_num(row[2]) / 1e8, 2)

        excluded = (
            _fetch_total_value(date_str, AFTER_HOURS_URL, 4)
            + _fetch_total_value(date_str, ODD_LOT_URL, 4)
            + _fetch_total_value(date_str, BLOCK_TRADE_URL, 5)
        )
        volume_yi_core = round(volume_yi - excluded / 1e8, 2)

        return [{
            "trade_date": date_str,
            "close": close,
            "change_pts": change_pts,
            "change_pct": round(change_pts / prev_close * 100, 2) if prev_close else 0,
            "volume_yi": volume_yi,
            "volume_yi_core": volume_yi_core,
        }]

    def describe(self, rows):
        if not rows:
            return None
        m = rows[0]
        return (f"📈 {m['trade_date']} 大盤指數 {m['close']:,.2f} "
                f"({m['change_pts']:+.2f}, {m['change_pct']:+.2f}%) "
                f"成交金額 {m['volume_yi']:,.0f}億(一般時段口徑 {m['volume_yi_core']:,.0f}億)")
