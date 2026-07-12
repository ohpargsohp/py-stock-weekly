import logging

import requests

from core.base import DataProvider

log = logging.getLogger(__name__)
HEADERS = {"User-Agent": "Mozilla/5.0"}


def _to_num(s):
    return float(str(s).replace(",", "").strip() or 0)


class MarketInstProvider(DataProvider):
    """大盤三大法人買賣超(BFI82U)。★ 自營商(自行買賣)是核心指標。"""

    name = "market_chip"
    pk = ["trade_date"]
    schema = {
        "trade_date": "TEXT",
        "foreign_net": "REAL",
        "trust_net": "REAL",
        "dealer_self_net": "REAL",
        "dealer_hedge_net": "REAL",
        "dealer_total_net": "REAL",
    }

    def fetch(self, date_str):
        url = f"https://www.twse.com.tw/rwd/zh/fund/BFI82U?response=json&dayDate={date_str}"
        r = requests.get(url, headers=HEADERS, timeout=15)
        j = r.json()
        if j.get("stat") != "OK" or not j.get("data"):
            log.warning(f"{date_str} 大盤無資料(可能休市)")
            return []

        d = {row[0].strip(): row for row in j["data"]}

        def net(key):
            # BFI82U fields: [單位名稱, 買進金額, 賣出金額, 買賣差額] ——
            # 買賣差額(index 3)已經是算好的淨額,不用再減一次賣出金額
            row = d.get(key)
            return round(_to_num(row[3]) / 1e8, 2) if row else 0

        self_net = net("自營商(自行買賣)")
        hedge_net = net("自營商(避險)")
        return [{
            "trade_date": date_str,
            "foreign_net": net("外資及陸資(不含外資自營商)") or net("外資及陸資"),
            "trust_net": net("投信"),
            "dealer_self_net": self_net,
            "dealer_hedge_net": hedge_net,
            "dealer_total_net": round(self_net + hedge_net, 2),
        }]

    def describe(self, rows):
        if not rows:
            return None
        m = rows[0]
        return (f"✅ {m['trade_date']} 大盤:自營商(自行買賣) {m['dealer_self_net']:+.2f}億 "
                f"| 避險 {m['dealer_hedge_net']:+.2f}億")
