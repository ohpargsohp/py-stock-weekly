import logging
import os

import requests

from core.base import DataProvider

log = logging.getLogger(__name__)


class MarketVixProvider(DataProvider):
    """CBOE VIX 恐慌指數(FRED 官方序列 VIXCLS),用來判斷「VIX > 35」這類
    極端恐慌的總經條件單訊號。

    需在 .env 設定 FRED_API_KEY(免費申請: https://fredaccount.stlouisfed.org/apikeys),
    未設定則印警告並略過,不中斷主流程,做法比照 core/mailer.py 的寄信設定。

    FRED 資料本身有落後(美股當日 VIX 收盤要等美東時間當天稍晚才會更新到 FRED,
    對台灣使用者來說等於「昨天」的數字),所以實際存檔日期依 FRED 回傳的
    observation date 為準,不強求等於 date_str。
    """

    name = "market_vix"
    pk = ["trade_date"]
    schema = {
        "trade_date": "TEXT",
        "vix": "REAL",
    }

    def fetch(self, date_str):
        api_key = os.environ.get("FRED_API_KEY")
        if not api_key:
            log.warning("未設定 FRED_API_KEY,略過 VIX 抓取")
            return []

        url = "https://api.stlouisfed.org/fred/series/observations"
        params = {
            "series_id": "VIXCLS",
            "api_key": api_key,
            "file_type": "json",
            "sort_order": "desc",
            "limit": 5,
        }
        try:
            r = requests.get(url, params=params, timeout=20)
            data = r.json()
        except (requests.RequestException, ValueError) as e:
            log.warning(f"VIX 抓取失敗: {e}")
            return []

        obs = next((o for o in data.get("observations", [])
                    if o.get("value") not in (None, ".")), None)
        if not obs:
            log.warning(f"VIX 無有效資料: {data.get('error_message', data)}")
            return []

        return [{
            "trade_date": obs["date"].replace("-", ""),
            "vix": float(obs["value"]),
        }]

    def describe(self, rows):
        if not rows:
            return None
        r = rows[0]
        alert = " 🚨 VIX>35 極端恐慌" if r["vix"] > 35 else ""
        return f"   VIX {r['vix']:.2f}{alert}"
