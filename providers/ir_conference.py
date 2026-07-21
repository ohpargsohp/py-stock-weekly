import logging
import time

import requests
from bs4 import BeautifulSoup

import config
from core.base import DataProvider

log = logging.getLogger(__name__)
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                          "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"}


def _roc_to_ymd(roc_date):
    """'115/07/16' -> '20260716';日期若是區間('115/03/03 至 115/03/06')取起始日"""
    roc_date = roc_date.split(" 至 ")[0].strip()
    y, m, d = roc_date.split("/")
    return f"{int(y) + 1911:04d}{int(m):02d}{int(d):02d}"


class IRConferenceProvider(DataProvider):
    """觀察名單個股法人說明會(法說會)日期(MOPS t100sb02_1)。

    MOPS 官方網域 mops.twse.com.tw 對雲端/機房 IP 常觸發 WAF 直接擋下(已實測驗證),
    改走鏡像網域 mopsov.twse.com.tw 可正常查詢,兩者資料一致,只是後者較少被擋。

    這支查詢介面是「依公司代號 + 民國年」查歷年法說會列表(已開完的和已公告的
    未來場次都在同一份回應裡),不是「當天」資料,所以沒有比照大部分 provider
    做 date_str 過濾的概念——每次執行都整批 upsert,upsert 靠 pk 冪等不會重複
    灌資料,新公告的場次下次執行就會出現在結果裡。只查當年度(依 date_str
    換算的民國年),跨年度公告的場次要等年度切換後才查得到,是已知限制。

    目前只用 TYPEK=sii(上市)查詢,觀察名單若有上櫃(otc)個股不會查到資料;
    ETF(如 0050)本身不開法說會,查詢結果本來就是空的,不是抓取失敗。
    """

    name = "ir_conference"
    pk = ["stock_id", "conf_date"]
    schema = {
        "stock_id": "TEXT",
        "stock_name": "TEXT",
        "conf_date": "TEXT",  # 法說會日期(起始日),西元 YYYYMMDD
        "conf_time": "TEXT",
        "location": "TEXT",
        "summary": "TEXT",
    }

    def fetch(self, date_str):
        roc_year = str(int(date_str[:4]) - 1911)
        out = []
        for sid, name in config.WATCHLIST.items():
            try:
                r = requests.post(
                    "https://mopsov.twse.com.tw/mops/web/ajax_t100sb02_1",
                    data={
                        "encodeURIComponent": "1", "step": "1", "firstin": "1",
                        "off": "1", "TYPEK": "sii", "year": roc_year, "month": "",
                        "co_id": sid,
                    },
                    headers=HEADERS, timeout=20,
                )
                r.encoding = "utf-8"
            except requests.RequestException as e:
                log.warning(f"{name}({sid}) 法說會抓取失敗: {e}")
                time.sleep(config.SLEEP_SEC)
                continue

            soup = BeautifulSoup(r.text, "html.parser")
            for row in soup.select("table#myTable tr[data-type='body']"):
                cells = row.find_all("td")
                if len(cells) < 6:
                    continue
                raw_date = cells[2].get_text(strip=True)
                if not raw_date:
                    continue
                try:
                    conf_date = _roc_to_ymd(raw_date)
                except ValueError:
                    log.warning(f"{name}({sid}) 法說會日期格式無法解析: {raw_date!r}")
                    continue
                out.append({
                    "stock_id": sid,
                    "stock_name": name,
                    "conf_date": conf_date,
                    "conf_time": cells[3].get_text(strip=True),
                    "location": cells[4].get_text(strip=True),
                    "summary": cells[5].get_text(strip=True),
                })
            time.sleep(config.SLEEP_SEC)
        return out

    def describe(self, rows):
        if not rows:
            return None
        today = time.strftime("%Y%m%d")
        upcoming = sorted((r for r in rows if r["conf_date"] >= today), key=lambda r: r["conf_date"])
        if not upcoming:
            return None
        return "\n".join(
            f"   {r['stock_name']}({r['stock_id']}) 法說會 {r['conf_date']} {r['conf_time']} {r['location']}"
            for r in upcoming[:5]
        )
