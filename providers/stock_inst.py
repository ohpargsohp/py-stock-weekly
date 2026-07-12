import logging

import requests

import config
from core.base import DataProvider

log = logging.getLogger(__name__)
HEADERS = {"User-Agent": "Mozilla/5.0"}


def _to_num(s):
    return float(str(s).replace(",", "").strip() or 0)


def _to_lots(s):
    """T86 回傳單位是「股」,個股慣例以「張」(1張=1000股)呈現。"""
    return int(round(_to_num(s) / 1000))


class StockInstProvider(DataProvider):
    """個股三大法人買賣超(T86),僅取 config.WATCHLIST 內的股票。"""

    name = "stock_chip"
    pk = ["trade_date", "stock_id"]
    schema = {
        "trade_date": "TEXT",
        "stock_id": "TEXT",
        "stock_name": "TEXT",
        "foreign_net": "INTEGER",
        "trust_net": "INTEGER",
        "dealer_self_net": "INTEGER",
        "dealer_hedge_net": "INTEGER",
    }

    def fetch(self, date_str):
        url = f"https://www.twse.com.tw/rwd/zh/fund/T86?response=json&date={date_str}&selectType=ALL"
        r = requests.get(url, headers=HEADERS, timeout=20)
        j = r.json()
        if j.get("stat") != "OK" or not j.get("data"):
            log.warning(f"{date_str} 個股無資料(可能休市)")
            return []

        out = []
        for row in j["data"]:
            sid = row[0].strip()
            if sid in config.WATCHLIST:
                # 欄位依 T86 實際 fields 順序核對(已用真實 API 回應驗證過):
                # 4=外陸資買賣超(不含外資自營商) 10=投信買賣超
                # 14=自營商買賣超(自行買賣) 17=自營商買賣超(避險)
                out.append({
                    "trade_date": date_str,
                    "stock_id": sid,
                    "stock_name": config.WATCHLIST[sid],
                    "foreign_net": _to_lots(row[4]),
                    "trust_net": _to_lots(row[10]),
                    "dealer_self_net": _to_lots(row[14]),
                    "dealer_hedge_net": _to_lots(row[17]),
                })
        return out

    def describe(self, rows):
        if not rows:
            return None
        return "\n".join(
            f"   {r['stock_name']}({r['stock_id']}) 自營自行 {r['dealer_self_net']:+d}張"
            for r in rows
        )
