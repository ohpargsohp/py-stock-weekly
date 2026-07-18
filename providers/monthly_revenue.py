import logging

import requests

import config
from core.base import DataProvider

log = logging.getLogger(__name__)
HEADERS = {"User-Agent": "Mozilla/5.0"}

# 月營收依法須在每月10日前公告,只在每月1~15日(含緩衝)才呼叫 API,
# 其餘天數直接回空清單——這支 API 沒有回溯查詢,平常打了也只會拿到同一期舊資料。
FETCH_DAY_RANGE = (1, 15)


def _to_num_or_none(s):
    s = str(s).strip()
    if s in ("", "-"):
        return None
    return float(s)


def _roc_period_to_western(roc_period):
    """'11506' -> '202606'"""
    if not roc_period or len(roc_period) < 5:
        return None
    return f"{int(roc_period[:-2]) + 1911:04d}{roc_period[-2:]}"


def _roc_date_to_ymd(roc_date):
    """'1150716' -> '20260716'"""
    if not roc_date or len(roc_date) < 6:
        return None
    return f"{int(roc_date[:-4]) + 1911:04d}{roc_date[-4:-2]}{roc_date[-2:]}"


class MonthlyRevenueProvider(DataProvider):
    """上市公司每月營業收入(t187ap05_L),僅取 config.WATCHLIST 內的公司。
    ETF(如 0050)不適用月營收公告,不會有對應資料列。
    YoY/MoM 增減幅由 TWSE 直接提供,不用自己重算;「連續成長月數」則靠
    這支程式每月累積出的歷史資料在 core/analysis.py 算出(核心動能訊號)。"""

    name = "monthly_revenue"
    pk = ["period", "stock_id"]
    schema = {
        "period": "TEXT",                    # 資料年月,西元 YYYYMM
        "stock_id": "TEXT",
        "stock_name": "TEXT",
        "industry": "TEXT",
        "revenue": "REAL",                    # 當月營收(仟元)
        "revenue_prev_month": "REAL",         # 上月營收(仟元)
        "revenue_last_year_month": "REAL",    # 去年當月營收(仟元)
        "revenue_mom_pct": "REAL",            # 上月比較增減(%)
        "revenue_yoy_pct": "REAL",            # 去年同月增減(%)
        "report_date": "TEXT",                # 出表日期 YYYYMMDD
    }

    def fetch(self, date_str):
        day = int(date_str[6:8])
        lo, hi = FETCH_DAY_RANGE
        if not (lo <= day <= hi):
            return []

        url = "https://openapi.twse.com.tw/v1/opendata/t187ap05_L"
        try:
            r = requests.get(url, headers=HEADERS, timeout=20)
            data = r.json()
        except (requests.RequestException, ValueError) as e:
            log.warning(f"月營收抓取失敗: {e}")
            return []

        out = []
        for row in data:
            sid = row.get("公司代號", "").strip()
            if sid not in config.WATCHLIST:
                continue
            period = _roc_period_to_western(row.get("資料年月", ""))
            if not period:
                continue
            out.append({
                "period": period,
                "stock_id": sid,
                "stock_name": config.WATCHLIST[sid],
                "industry": row.get("產業別") or None,
                "revenue": _to_num_or_none(row.get("營業收入-當月營收")),
                "revenue_prev_month": _to_num_or_none(row.get("營業收入-上月營收")),
                "revenue_last_year_month": _to_num_or_none(row.get("營業收入-去年當月營收")),
                "revenue_mom_pct": _to_num_or_none(row.get("營業收入-上月比較增減(%)")),
                "revenue_yoy_pct": _to_num_or_none(row.get("營業收入-去年同月增減(%)")),
                "report_date": _roc_date_to_ymd(row.get("出表日期", "")),
            })
        return out

    def describe(self, rows):
        if not rows:
            return None
        lines = []
        for r in rows:
            yoy = r["revenue_yoy_pct"]
            mom = r["revenue_mom_pct"]
            if yoy is not None and mom is not None:
                lines.append(f"   {r['stock_name']}({r['stock_id']}) {r['period']} 營收 "
                              f"YoY {yoy:+.1f}% | MoM {mom:+.1f}%")
            else:
                lines.append(f"   {r['stock_name']}({r['stock_id']}) {r['period']} 營收 {r['revenue']}")
        return "\n".join(lines)
