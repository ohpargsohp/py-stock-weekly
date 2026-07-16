import requests

HEADERS = {"User-Agent": "Mozilla/5.0"}

_cache = {}


def fetch_mi_margn(date_str):
    """MI_MARGN 是 margin_balance(個股)和 market_margin(全市場)共用的同一個
    API 端點,同一次查詢就同時回傳兩者需要的表(tables[0]=全市場, tables[1]=個股)。
    這裡按 date_str 快取,確保同一次執行同一天只打一次 API,不重複發送請求。
    """
    if date_str not in _cache:
        url = f"https://www.twse.com.tw/rwd/zh/marginTrading/MI_MARGN?response=json&date={date_str}&selectType=ALL"
        r = requests.get(url, headers=HEADERS, timeout=20)
        r.encoding = "utf-8"
        _cache[date_str] = r.json()
    return _cache[date_str]
