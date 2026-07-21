import csv
import io
import logging

import requests
import truststore

import config
from core.base import DataProvider

# TDCC 的憑證鏈掛在 TWCA Global Root CA 下,Python 內建(certifi)信任庫用嚴格模式
# 驗證會因缺少 Subject Key Identifier 而失敗(SSLCertVerificationError),但這條鏈
# 其實是 Windows/macOS 系統信任庫都認可的合法憑證,curl 用系統原生驗證就不會出錯。
# truststore 讓 Python 改用作業系統的信任庫驗證,而不是停用驗證(不是 verify=False)。
truststore.inject_into_ssl()

log = logging.getLogger(__name__)
HEADERS = {"User-Agent": "Mozilla/5.0"}

BIG_HOLDER_LEVEL = "15"  # TDCC 持股分級 15 = 持股 1,000,001 股(1,000張)以上,市場慣稱「千張大戶」
TOTAL_LEVEL = "17"       # TDCC 持股分級 17 = 合計(全體集保股數,比例固定 100%)


class HolderDistributionProvider(DataProvider):
    """集保戶股權分散表(TDCC OpenData id=1-5),取千張大戶(分級15)佔集保庫存比例。
    大戶比例連續下降常被視為聰明錢派發的領先訊號,連續上升則反映籌碼集中。

    TDCC 每週公布一次(以週五庫存為基準),不像大部分 provider 有日期參數可指定——
    這支 API 永遠只回傳「目前最新一週」的全市場資料,所以跟 foreign_futures_oi.py
    一樣,實際存檔日期依 CSV 的資料日期為準,可能跟呼叫時傳入的 date_str 不同,
    不強求對齊、也不會因此假裝抓到了當天的資料。
    """

    name = "holder_distribution"
    pk = ["trade_date", "stock_id"]
    schema = {
        "trade_date": "TEXT",
        "stock_id": "TEXT",
        "stock_name": "TEXT",
        "big_holder_count": "INTEGER",   # 千張大戶人數
        "big_holder_shares": "INTEGER",  # 千張大戶合計股數
        "big_holder_pct": "REAL",        # 千張大戶佔集保庫存比例(%)
        "total_holders": "INTEGER",      # 全體集保人數
    }

    def fetch(self, date_str):
        url = "https://opendata.tdcc.com.tw/getOD.ashx?id=1-5"
        try:
            r = requests.get(url, headers=HEADERS, timeout=30)
            r.encoding = "utf-8-sig"
        except requests.RequestException as e:
            log.warning(f"集保股權分散表抓取失敗: {e}")
            return []

        by_stock = {}
        reader = csv.reader(io.StringIO(r.text))
        next(reader, None)  # header
        for row in reader:
            if len(row) < 6:
                continue
            data_date, sid, level, count, shares, pct = row[:6]
            sid = sid.strip()
            if sid not in config.WATCHLIST:
                continue
            by_stock.setdefault(sid, {"_date": data_date})[level.strip()] = {
                "count": int(count), "shares": int(shares), "pct": float(pct),
            }

        if not by_stock:
            log.warning("集保股權分散表無觀察名單資料")
            return []

        actual_date = next(iter(by_stock.values()))["_date"]
        if actual_date != date_str:
            log.warning(f"集保股權分散表僅提供最新一期({actual_date}),"
                        f"與請求日期({date_str})不同,已依實際日期存檔")

        out = []
        for sid, levels in by_stock.items():
            big = levels.get(BIG_HOLDER_LEVEL)
            total = levels.get(TOTAL_LEVEL)
            if not big or not total:
                continue
            out.append({
                "trade_date": actual_date,
                "stock_id": sid,
                "stock_name": config.WATCHLIST[sid],
                "big_holder_count": big["count"],
                "big_holder_shares": big["shares"],
                "big_holder_pct": big["pct"],
                "total_holders": total["count"],
            })
        return out

    def describe(self, rows):
        if not rows:
            return None
        return "\n".join(
            f"   {r['stock_name']}({r['stock_id']}) 千張大戶佔比 {r['big_holder_pct']:.2f}%"
            f"(人數 {r['big_holder_count']:,})"
            for r in rows
        )
