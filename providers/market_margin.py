import logging

from core.base import DataProvider
from providers._mi_margn import fetch_mi_margn

log = logging.getLogger(__name__)


def _to_num(s):
    return float(str(s).replace(",", "").strip() or 0)


class MarketMarginProvider(DataProvider):
    """全市場融資融券餘額(散戶槓桿總量),同一支 MI_MARGN API 的 tables[0]
    (跟 providers/margin_balance.py 抓的 tables[1] 個股明細是同一次查詢的兩張表,
    透過 providers/_mi_margn.py 共用快取,同一天只打一次 API)。"""

    name = "market_margin"
    pk = ["trade_date"]
    schema = {
        "trade_date": "TEXT",
        "margin_balance_lots": "INTEGER",      # 融資今日餘額(張)
        "margin_balance_lots_chg": "INTEGER",  # 較前日增減(張)
        "short_balance_lots": "INTEGER",       # 融券今日餘額(張)
        "short_balance_lots_chg": "INTEGER",   # 較前日增減(張)
        "margin_balance_yi": "REAL",           # 融資金額今日餘額(億元)
        "margin_balance_yi_chg": "REAL",       # 較前日增減(億元)
    }

    def fetch(self, date_str):
        j = fetch_mi_margn(date_str)
        if j.get("stat") != "OK" or len(j.get("tables", [])) < 1:
            log.warning(f"{date_str} 全市場融資融券無資料(可能休市)")
            return []

        d = {row[0].strip(): row for row in j["tables"][0]["data"]}
        margin = d.get("融資(交易單位)")
        short = d.get("融券(交易單位)")
        amount = d.get("融資金額(仟元)")
        if not (margin and short and amount):
            return []

        # tables[0] 只有「項目」一個標籤欄(不像 tables[1] 有代號+名稱兩欄),
        # fields=[項目,買進,賣出,現金(券)償還,前日餘額,今日餘額] -> idx4=前日 idx5=今日
        margin_bal, margin_prev = _to_num(margin[5]), _to_num(margin[4])
        short_bal, short_prev = _to_num(short[5]), _to_num(short[4])
        amt_bal, amt_prev = _to_num(amount[5]) / 1e5, _to_num(amount[4]) / 1e5  # 仟元 -> 億元

        return [{
            "trade_date": date_str,
            "margin_balance_lots": int(margin_bal),
            "margin_balance_lots_chg": int(margin_bal - margin_prev),
            "short_balance_lots": int(short_bal),
            "short_balance_lots_chg": int(short_bal - short_prev),
            "margin_balance_yi": round(amt_bal, 2),
            "margin_balance_yi_chg": round(amt_bal - amt_prev, 2),
        }]

    def describe(self, rows):
        if not rows:
            return None
        m = rows[0]
        return (f"🏦 {m['trade_date']} 全市場融資餘額 {m['margin_balance_yi']:,.2f}億"
                f"({m['margin_balance_yi_chg']:+.2f}) | {m['margin_balance_lots']:,}張"
                f"({m['margin_balance_lots_chg']:+d})")
