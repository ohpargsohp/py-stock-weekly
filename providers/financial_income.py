import logging

import requests

import config
from core.base import DataProvider

log = logging.getLogger(__name__)
HEADERS = {"User-Agent": "Mozilla/5.0"}


def _to_num_or_none(s):
    s = str(s).strip()
    if s in ("", "-"):
        return None
    return float(s)


def _roc_date_to_ymd(roc_date):
    """'1150718' -> '20260718'"""
    if not roc_date or len(roc_date) < 6:
        return None
    return f"{int(roc_date[:-4]) + 1911:04d}{roc_date[-4:-2]}{roc_date[-2:]}"


class FinancialIncomeProvider(DataProvider):
    """上市公司綜合損益表-一般業(t187ap06_L_ci),僅取 config.WATCHLIST 內的公司。
    毛利率/營益率/淨利率由這支 provider 自行計算(TWSE 只給營收/成本/毛利等原始金額,
    不會直接給比率)。金融、證券、保險等特殊產業有各自的損益表格式,目前不支援,
    觀察名單目前全是一般業公司故暫不處理。"""

    name = "financial_income"
    pk = ["period", "stock_id"]
    schema = {
        "period": "TEXT",             # 例如 '2026Q1'
        "stock_id": "TEXT",
        "stock_name": "TEXT",
        "fiscal_year": "TEXT",
        "fiscal_quarter": "TEXT",
        "revenue": "REAL",             # 營業收入(仟元)
        "cost": "REAL",                # 營業成本(仟元)
        "gross_profit": "REAL",        # 營業毛利(毛損)淨額(仟元)
        "gross_margin": "REAL",        # 毛利率(%),自行計算
        "operating_income": "REAL",    # 營業利益(損失)(仟元)
        "operating_margin": "REAL",    # 營益率(%),自行計算
        "net_income": "REAL",          # 本期淨利(淨損)(仟元)
        "net_margin": "REAL",          # 淨利率(%),自行計算
        "eps": "REAL",                 # 基本每股盈餘(元)
        "report_date": "TEXT",         # 出表日期 YYYYMMDD
    }

    def fetch(self, date_str):
        url = "https://openapi.twse.com.tw/v1/opendata/t187ap06_L_ci"
        try:
            r = requests.get(url, headers=HEADERS, timeout=20)
            data = r.json()
        except (requests.RequestException, ValueError) as e:
            log.warning(f"財報(綜合損益表)抓取失敗: {e}")
            return []

        out = []
        for row in data:
            sid = row.get("公司代號", "").strip()
            if sid not in config.WATCHLIST:
                continue
            fiscal_year_roc = row.get("年度", "").strip()
            fiscal_quarter = row.get("季別", "").strip()
            revenue = _to_num_or_none(row.get("營業收入"))
            if not fiscal_year_roc or revenue is None:
                continue

            fiscal_year = str(int(fiscal_year_roc) + 1911)
            cost = _to_num_or_none(row.get("營業成本"))
            gross_profit = _to_num_or_none(row.get("營業毛利（毛損）淨額"))
            if gross_profit is None:
                gross_profit = _to_num_or_none(row.get("營業毛利（毛損）"))
            operating_income = _to_num_or_none(row.get("營業利益（損失）"))
            net_income = _to_num_or_none(row.get("本期淨利（淨損）"))

            out.append({
                "period": f"{fiscal_year}Q{fiscal_quarter}",
                "stock_id": sid,
                "stock_name": config.WATCHLIST[sid],
                "fiscal_year": fiscal_year,
                "fiscal_quarter": fiscal_quarter,
                "revenue": revenue,
                "cost": cost,
                "gross_profit": gross_profit,
                "gross_margin": round(gross_profit / revenue * 100, 2)
                    if gross_profit is not None and revenue else None,
                "operating_income": operating_income,
                "operating_margin": round(operating_income / revenue * 100, 2)
                    if operating_income is not None and revenue else None,
                "net_income": net_income,
                "net_margin": round(net_income / revenue * 100, 2)
                    if net_income is not None and revenue else None,
                "eps": _to_num_or_none(row.get("基本每股盈餘（元）")),
                "report_date": _roc_date_to_ymd(row.get("出表日期", "")),
            })
        return out

    def describe(self, rows):
        if not rows:
            return None
        return "\n".join(
            f"   {r['stock_name']}({r['stock_id']}) {r['period']} 毛利率 "
            f"{r['gross_margin']:.1f}%" if r["gross_margin"] is not None else
            f"   {r['stock_name']}({r['stock_id']}) {r['period']} 毛利率 —"
            for r in rows
        )
