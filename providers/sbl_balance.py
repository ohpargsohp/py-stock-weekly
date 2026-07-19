import logging

import requests

import config
from core.base import DataProvider

log = logging.getLogger(__name__)
HEADERS = {"User-Agent": "Mozilla/5.0"}


def _to_num(s):
    return float(str(s).replace(",", "").strip() or 0)


class SblBalanceProvider(DataProvider):
    """個股借券賣出餘額(TWT93U),僅取 config.WATCHLIST 內的股票。
    這支 API 回傳的表其實是「融券借券賣出餘額」,同一列前半段(idx2~7)是融券
    (跟 providers/margin_balance.py 的 MI_MARGN 融券欄位是兩個不同資料源,
    數字不會完全一樣),後半段(idx8~13)才是借券賣出——這支只取後半段。
    借券賣出是法人/大戶常用的放空管道,餘額異常放大可視為潛在賣壓訊號。
    單位為「股」,不是「張」(TWSE 回應 hints 已標明)。"""

    name = "sbl_balance"
    pk = ["trade_date", "stock_id"]
    schema = {
        "trade_date": "TEXT",
        "stock_id": "TEXT",
        "stock_name": "TEXT",
        "sbl_balance": "INTEGER",      # 借券賣出今日餘額(股)
        "sbl_balance_chg": "INTEGER",  # 較前日增減(股)
        "sbl_sell": "INTEGER",         # 當日借券賣出(股)
        "sbl_return": "INTEGER",       # 當日還券(股)
    }

    def fetch(self, date_str):
        url = f"https://www.twse.com.tw/rwd/zh/marginTrading/TWT93U?date={date_str}&response=json"
        try:
            r = requests.get(url, headers=HEADERS, timeout=20)
            r.encoding = "utf-8"
            j = r.json()
        except (requests.RequestException, ValueError) as e:
            log.warning(f"{date_str} 借券賣出餘額抓取失敗: {e}")
            return []

        if j.get("stat") != "OK":
            log.warning(f"{date_str} 借券賣出餘額無資料(可能休市)")
            return []

        # fields = [代號,名稱,前日餘額,賣出,買進,現券,今日餘額,次一營業日限額(以上為融券),
        #           前日餘額,當日賣出,當日還券,當日調整,當日餘額,次一營業日可限額(以上為借券賣出),備註]
        out = []
        for row in j.get("data", []):
            sid = row[0].strip()
            if sid not in config.WATCHLIST:
                continue
            sbl_prev, sbl_sell, sbl_return, sbl_bal = (
                int(_to_num(row[8])), int(_to_num(row[9])),
                int(_to_num(row[10])), int(_to_num(row[12])),
            )
            out.append({
                "trade_date": date_str,
                "stock_id": sid,
                "stock_name": config.WATCHLIST[sid],
                "sbl_balance": sbl_bal,
                "sbl_balance_chg": sbl_bal - sbl_prev,
                "sbl_sell": sbl_sell,
                "sbl_return": sbl_return,
            })
        return out

    def describe(self, rows):
        if not rows:
            return None
        return "\n".join(
            f"   {r['stock_name']}({r['stock_id']}) 借券賣出餘額 {r['sbl_balance']:,}股"
            f"({r['sbl_balance_chg']:+,})"
            for r in rows
        )
