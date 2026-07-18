import logging
import re

import requests

import config
from core.base import DataProvider

log = logging.getLogger(__name__)
HEADERS = {"User-Agent": "Mozilla/5.0"}

# 漲跌欄位是包著顏色的 HTML,例如 '<p style= color:red>+</p>' / '<p style= color:green>-</p>'——
# 紅漲綠跌是 TWSE 網頁慣例,平盤或無比較基準時通常不是這兩色,一律當平盤(0)處理。
_SIGN_RE = re.compile(r"color:(red|green)")


def _to_num_or_none(s):
    s = str(s).replace(",", "").strip()
    if s in ("", "-", "--"):
        return None
    return float(s)


def _sign(html):
    m = _SIGN_RE.search(html or "")
    if not m:
        return 0
    return 1 if m.group(1) == "red" else -1


class StockPriceActionProvider(DataProvider):
    """個股每日價格結構(開高低收 + 漲跌幅 + 成交量,MI_INDEX type=ALLBUT0999),
    僅取 config.WATCHLIST 內的股票。stock_quote 只有收盤價/PE/PB,缺這幾項技術面
    指標時無法算乖離率或量價結構,故獨立成一支 provider 用同一個 date_str 抓歷史資料
    (不同於 STOCK_DAY_ALL 只能拿到最新一天,這支 API 有 date 參數可回溯)。"""

    name = "stock_price_action"
    pk = ["trade_date", "stock_id"]
    schema = {
        "trade_date": "TEXT",
        "stock_id": "TEXT",
        "stock_name": "TEXT",
        "open": "REAL",
        "high": "REAL",
        "low": "REAL",
        "close": "REAL",
        "change_pts": "REAL",      # signed,紅漲為正、綠跌為負
        "change_pct": "REAL",
        "volume_lots": "REAL",     # 成交量,張(成交股數/1000)
        "turnover_yi": "REAL",     # 成交金額,億元
    }

    def fetch(self, date_str):
        url = (f"https://www.twse.com.tw/rwd/zh/afterTrading/MI_INDEX"
               f"?response=json&date={date_str}&type=ALLBUT0999")
        try:
            r = requests.get(url, headers=HEADERS, timeout=20)
            r.encoding = "utf-8"
            j = r.json()
        except (requests.RequestException, ValueError) as e:
            log.warning(f"個股價格結構抓取失敗: {e}")
            return []

        if j.get("stat") != "OK":
            log.warning(f"{date_str} 個股價格結構無資料(可能休市)")
            return []

        table = next((t for t in j.get("tables", []) if "開盤價" in (t.get("fields") or [])), None)
        if not table:
            return []

        idx = {name: i for i, name in enumerate(table["fields"])}
        out = []
        for row in table["data"]:
            sid = row[idx["證券代號"]].strip()
            if sid not in config.WATCHLIST:
                continue
            close = _to_num_or_none(row[idx["收盤價"]])
            change_pts = _to_num_or_none(row[idx["漲跌價差"]])
            if change_pts is not None:
                change_pts *= _sign(row[idx["漲跌(+/-)"]])
            prev_close = close - change_pts if close is not None and change_pts is not None else None
            volume_shares = _to_num_or_none(row[idx["成交股數"]])
            out.append({
                "trade_date": date_str,
                "stock_id": sid,
                "stock_name": config.WATCHLIST[sid],
                "open": _to_num_or_none(row[idx["開盤價"]]),
                "high": _to_num_or_none(row[idx["最高價"]]),
                "low": _to_num_or_none(row[idx["最低價"]]),
                "close": close,
                "change_pts": change_pts,
                "change_pct": round(change_pts / prev_close * 100, 2)
                    if change_pts is not None and prev_close else None,
                "volume_lots": round(volume_shares / 1000, 1) if volume_shares is not None else None,
                "turnover_yi": round(_to_num_or_none(row[idx["成交金額"]]) / 1e8, 2)
                    if _to_num_or_none(row[idx["成交金額"]]) is not None else None,
            })
        return out

    def describe(self, rows):
        if not rows:
            return None
        lines = []
        for r in rows:
            if r["change_pct"] is not None:
                lines.append(f"   {r['stock_name']}({r['stock_id']}) 收 {r['close']} "
                              f"({r['change_pts']:+.2f}, {r['change_pct']:+.2f}%) "
                              f"高 {r['high']} 低 {r['low']} 量 {r['volume_lots']:,.0f}張")
            else:
                lines.append(f"   {r['stock_name']}({r['stock_id']}) 收 {r['close']} "
                              f"高 {r['high']} 低 {r['low']} 量 {r['volume_lots']:,.0f}張")
        return "\n".join(lines)
