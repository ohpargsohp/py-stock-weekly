import logging

import requests

from core.base import DataProvider

log = logging.getLogger(__name__)
HEADERS = {"User-Agent": "Mozilla/5.0"}

# 只關注最常被拿來當風向指標的幾個契約(可自行增減)
CONTRACTS = {"臺股期貨", "小型臺指期貨", "電子期貨", "金融期貨"}

# API 的 Item 欄位本身就含三大法人,不是只有外資(已用真實回應驗證過)
INSTITUTIONS = {"外資及陸資", "投信", "自營商"}


class ForeignFuturesOIProvider(DataProvider):
    """三大法人期貨未平倉部位(三大法人-區分各期貨契約-依日期,TAIFEX OpenAPI)。
    含外資及陸資、投信、自營商三種法人,可比對「土洋對作」。

    注意:此 API 沒有日期參數,永遠只回傳「最新一個交易日」的資料——
    這是期交所 OpenAPI 本身的限制,不是這支 provider 的 bug。
    所以無論呼叫 fetch() 時傳入的 date_str 是什麼,實際存檔用的日期一律以
    API 回傳的 Date 欄位為準;若與請求日期不同,會印警告並照實存檔,
    不會假裝抓到了你要的那天。
    """

    name = "foreign_futures_oi"
    pk = ["trade_date", "contract_code", "institution_type"]
    schema = {
        "trade_date": "TEXT",
        "contract_code": "TEXT",
        "institution_type": "TEXT",
        "oi_long": "INTEGER",   # 未沖銷多方口數
        "oi_short": "INTEGER",  # 未沖銷空方口數
        "oi_net": "INTEGER",    # 未沖銷淨部位(正=偏多,負=偏空)
    }

    def fetch(self, date_str):
        url = ("https://openapi.taifex.com.tw/v1/"
               "MarketDataOfMajorInstitutionalTradersDetailsOfFuturesContractsBytheDate")
        try:
            r = requests.get(url, headers=HEADERS, timeout=20)
            data = r.json()
        except (requests.RequestException, ValueError) as e:
            log.warning(f"三大法人期貨未平倉抓取失敗: {e}")
            return []

        rows = [d for d in data
                if d.get("Item") in INSTITUTIONS and d.get("ContractCode") in CONTRACTS]
        if not rows:
            return []

        actual_date = rows[0]["Date"]
        if actual_date != date_str:
            log.warning(f"三大法人期貨未平倉 API 僅提供最新資料({actual_date}),"
                        f"與請求日期({date_str})不同,已依實際日期存檔")

        return [{
            "trade_date": actual_date,
            "contract_code": d["ContractCode"],
            "institution_type": d["Item"],
            "oi_long": int(d["OpenInterest(Long)"]),
            "oi_short": int(d["OpenInterest(Short)"]),
            "oi_net": int(d["OpenInterest(Net)"]),
        } for d in rows]

    def describe(self, rows):
        if not rows:
            return None
        lines = [f"   三大法人期貨未平倉({r['trade_date']}) {r['contract_code']}/{r['institution_type']}: "
                  f"淨{r['oi_net']:+,}口" for r in rows]
        return "\n".join(lines)
