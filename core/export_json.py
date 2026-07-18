import json
import sqlite3
from datetime import datetime, timedelta, timezone

from core.analysis import dealer_streak, pe_river, revenue_streak

TW_TZ = timezone(timedelta(hours=8))


def _iso(date_str):
    """'20260709' -> '2026-07-09'"""
    return f"{date_str[0:4]}-{date_str[4:6]}-{date_str[6:8]}" if date_str else None


def _table_exists(conn, name):
    return conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)
    ).fetchone() is not None


def build_weekly_scan(db_path):
    """把 SQLite 裡的資料組成給 AI 判讀用的正規化 JSON。
    只放實際有抓到的資料;抓不到的欄位(大盤指數、個股股價/PE、市場層級融資
    彙總、明確的休市標記)一律列在 data_quality.unavailable,不用假數字填充。
    """
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    verified = []
    unavailable = [
        "market_pb(大盤股價淨值比)——TWSE 沒有官方每日 API,要算需自行對全市場個股做市值加權,"
        "目前沒有流通股數/市值資料源可用,故不提供(不做未加權簡易平均,避免誤導)",
        "market_closed 明確標記——目前『當天沒有資料』可能是休市,也可能是抓取失敗,兩者尚未區分",
        "industry_avg_pe(同業估值比較)——觀察名單每個產業通常只有 2~3 檔標的,"
        "屬極小樣本,對照組不具統計意義,直接拿來判斷個股「相對同業低估/高估」會誤導;"
        "需要全市場同產業成分股 + 市值加權才有參考價值,目前沒有全市場 PE + 產業對照表資料源,故不提供",
    ]

    anchor = conn.execute("SELECT MAX(trade_date) FROM market_chip").fetchone()[0] \
        if _table_exists(conn, "market_chip") else None

    result = {
        "report_type": "weekly_scan",
        "as_of": _iso(anchor),
        "generated_at": datetime.now(TW_TZ).isoformat(),
    }

    # 大盤指數(收盤/漲跌/成交量)
    if _table_exists(conn, "market_index"):
        r = conn.execute(
            "SELECT * FROM market_index ORDER BY trade_date DESC LIMIT 1"
        ).fetchone()
        if r:
            result["market_index"] = {
                "trade_date": _iso(r["trade_date"]),
                "source": "TWSE-FMTQIK",
                "close": r["close"],
                "change_pts": r["change_pts"],
                "change_pct": r["change_pct"],
                "volume_yi": r["volume_yi"],
                "unit_volume": "億元",
            }
            verified.append("market_index")

    # 全市場融資融券餘額(散戶槓桿總量)
    if _table_exists(conn, "market_margin"):
        r = conn.execute(
            "SELECT * FROM market_margin ORDER BY trade_date DESC LIMIT 1"
        ).fetchone()
        if r:
            result["market_margin"] = {
                "trade_date": _iso(r["trade_date"]),
                "source": "TWSE-MI_MARGN",
                "unit_lots": "張",
                "unit_amount": "億元",
                "margin_balance_lots": r["margin_balance_lots"],
                "margin_balance_lots_chg": r["margin_balance_lots_chg"],
                "short_balance_lots": r["short_balance_lots"],
                "short_balance_lots_chg": r["short_balance_lots_chg"],
                "margin_balance_yi": r["margin_balance_yi"],
                "margin_balance_yi_chg": r["margin_balance_yi_chg"],
            }
            verified.append("market_margin")

    # 大盤三大法人近 5 日
    if _table_exists(conn, "market_chip"):
        rows = conn.execute("""
            SELECT trade_date, foreign_net, trust_net, dealer_self_net,
                   dealer_hedge_net, dealer_total_net
            FROM market_chip ORDER BY trade_date DESC LIMIT 5
        """).fetchall()
        if rows:
            result["institutional_5d"] = [{
                "trade_date": _iso(r["trade_date"]),
                "source": "TWSE-BFI82U",
                "unit": "億元",
                "foreign_net": r["foreign_net"],
                "trust_net": r["trust_net"],
                "dealer_self_net": r["dealer_self_net"],
                "dealer_hedge_net": r["dealer_hedge_net"],
                "dealer_total_net": r["dealer_total_net"],
            } for r in rows]
            verified.append("institutional_5d")

    # 自營商(自行買賣)連續方向——核心指標
    if _table_exists(conn, "market_chip"):
        streak = dealer_streak(conn, 6)
        if streak:
            # streak 是 DESC(最新日在前),從最新日往回數,遇到變號就停
            signs = ["買" if v > 0 else "賣" for _, v in streak]
            streak_days = 1
            for s in signs[1:]:
                if s != signs[0]:
                    break
                streak_days += 1
            result["dealer_self_streak"] = {
                "target": "market_dealer_self",
                "source": "TWSE-BFI82U",
                "unit": "億元",
                "recent": [{"trade_date": _iso(d), "net": v} for d, v in streak],
                "streak_days": streak_days,
                "streak_direction": signs[0] if signs else None,
                "signal": f"連{streak_days}{signs[0]}超" if streak_days >= 5 else None,
            }
            verified.append("dealer_self_streak")

    # 三大法人期貨未平倉(TAIFEX API 只給最新一個交易日,不一定等於 anchor 日期)
    if _table_exists(conn, "foreign_futures_oi"):
        fut_latest = conn.execute("SELECT MAX(trade_date) FROM foreign_futures_oi").fetchone()[0]
        if fut_latest:
            rows = conn.execute("""
                SELECT contract_code, institution_type, oi_long, oi_short, oi_net
                FROM foreign_futures_oi WHERE trade_date = ?
            """, (fut_latest,)).fetchall()
            # headline 沿用舊定義:臺股期貨的外資淨未平倉(最常被拿來當風向指標)
            headline = next((
                r for r in rows
                if r["contract_code"] == "臺股期貨" and r["institution_type"] == "外資及陸資"
            ), None)
            result["foreign_futures_oi"] = {
                "as_of": _iso(fut_latest),
                "source": "TAIFEX-MarketDataOfMajorInstitutionalTradersDetailsOfFuturesContractsBytheDate",
                "unit": "口",
                "headline_contract": "臺股期貨",
                "headline_institution": "外資及陸資",
                "headline_net": headline["oi_net"] if headline else None,
                "by_contract": [{
                    "contract_code": r["contract_code"],
                    "institution_type": r["institution_type"],
                    "oi_long": r["oi_long"],
                    "oi_short": r["oi_short"],
                    "oi_net": r["oi_net"],
                } for r in rows],
            }
            verified.append("foreign_futures_oi")

    # watchlist:個股三大法人 + 融資融券 + 收盤價
    # 以 stock_chip 自己最新的一天為準,不要求和大盤 anchor 同一天——
    # 跟 foreign_futures_oi 一樣,TWSE 個股三大法人/收盤價 API 常常比大盤指數
    # 慢好幾天更新,硬要求同天會讓整段資料在 API 落後時消失不見。
    # 每筆 entry 仍帶自己的 trade_date,不會誤標成 anchor 當天的資料。
    if _table_exists(conn, "stock_chip"):
        stock_latest = conn.execute("SELECT MAX(trade_date) FROM stock_chip").fetchone()[0]
        stock_rows = conn.execute(
            "SELECT * FROM stock_chip WHERE trade_date = ?", (stock_latest,)
        ).fetchall() if stock_latest else []
        margin_by_id = {}
        if stock_latest and _table_exists(conn, "margin_balance"):
            margin_by_id = {
                r["stock_id"]: r for r in conn.execute(
                    "SELECT * FROM margin_balance WHERE trade_date = ?", (stock_latest,)
                ).fetchall()
            }
        quote_by_id = {}
        if _table_exists(conn, "stock_quote"):
            quote_latest = conn.execute("SELECT MAX(trade_date) FROM stock_quote").fetchone()[0]
            if quote_latest:
                quote_by_id = {
                    r["stock_id"]: r for r in conn.execute(
                        "SELECT * FROM stock_quote WHERE trade_date = ?", (quote_latest,)
                    ).fetchall()
                }
        # 月營收/財報屬低頻資料,各自取每檔股票自己最新一期,不要求跟大盤/個股
        # 三大法人同一天——理由同 foreign_futures_oi、watchlist 本身的落後資料處理原則。
        revenue_by_id = {}
        if _table_exists(conn, "monthly_revenue"):
            revenue_by_id = {
                r["stock_id"]: r for r in conn.execute("""
                    SELECT * FROM monthly_revenue mr
                    WHERE period = (SELECT MAX(period) FROM monthly_revenue WHERE stock_id = mr.stock_id)
                """).fetchall()
            }
        financial_by_id = {}
        if _table_exists(conn, "financial_income"):
            financial_by_id = {
                r["stock_id"]: r for r in conn.execute("""
                    SELECT * FROM financial_income fi
                    WHERE period = (SELECT MAX(period) FROM financial_income WHERE stock_id = fi.stock_id)
                """).fetchall()
            }
        price_action_by_id = {}
        if _table_exists(conn, "stock_price_action"):
            price_latest = conn.execute("SELECT MAX(trade_date) FROM stock_price_action").fetchone()[0]
            if price_latest:
                price_action_by_id = {
                    r["stock_id"]: r for r in conn.execute(
                        "SELECT * FROM stock_price_action WHERE trade_date = ?", (price_latest,)
                    ).fetchall()
                }
        has_revenue_momentum = has_gross_margin = has_pe_river = has_price_action = False
        watchlist = []
        for r in stock_rows:
            entry = {
                "id": r["stock_id"],
                "name": r["stock_name"],
                "trade_date": _iso(r["trade_date"]),
                "source": "TWSE-T86",
                "unit_institutional": "張",
                "foreign_net": r["foreign_net"],
                "trust_net": r["trust_net"],
                "dealer_self_net": r["dealer_self_net"],
                "dealer_hedge_net": r["dealer_hedge_net"],
            }
            m = margin_by_id.get(r["stock_id"])
            if m:
                entry.update({
                    "unit_margin": "張",
                    "margin_balance": m["margin_balance"],
                    "margin_balance_chg": m["margin_balance_chg"],
                    "short_balance": m["short_balance"],
                    "short_balance_chg": m["short_balance_chg"],
                })
            q = quote_by_id.get(r["stock_id"])
            if q:
                # ETF(如 0050)沒有本益比/淨值比,close 仍可能有值、pe/pb 會是 None
                entry.update({
                    "close": q["close"],
                    "dividend_yield": q["dividend_yield"],
                    "pe": q["pe"],
                    "pb": q["pb"],
                })

            pa = price_action_by_id.get(r["stock_id"])
            if pa:
                # 獨立帶自己的 trade_date/close,不強制跟 stock_quote 同一天——
                # 兩支 provider 來源不同 API,理由同本區塊其他低頻資料的落後處理原則。
                entry["price_action"] = {
                    "trade_date": _iso(pa["trade_date"]),
                    "source": "TWSE-MI_INDEX",
                    "open": pa["open"],
                    "high": pa["high"],
                    "low": pa["low"],
                    "close": pa["close"],
                    "change_pts": pa["change_pts"],
                    "change_pct": pa["change_pct"],
                    "unit_volume": "張",
                    "volume_lots": pa["volume_lots"],
                    "unit_turnover": "億元",
                    "turnover_yi": pa["turnover_yi"],
                }
                has_price_action = True

            rev = revenue_by_id.get(r["stock_id"])
            if rev:
                streak_rows = revenue_streak(conn, r["stock_id"], 6)
                momentum = {
                    "period": rev["period"],
                    "source": "TWSE-t187ap05_L",
                    "unit": "仟元",
                    "revenue": rev["revenue"],
                    "revenue_mom_pct": rev["revenue_mom_pct"],
                    "revenue_yoy_pct": rev["revenue_yoy_pct"],
                }
                if streak_rows:
                    signs = ["正" if v > 0 else "負" for _, v in streak_rows]
                    streak_months = 1
                    for s in signs[1:]:
                        if s != signs[0]:
                            break
                        streak_months += 1
                    momentum["yoy_streak_months"] = streak_months
                    momentum["yoy_streak_direction"] = signs[0]
                entry["revenue_momentum"] = momentum
                has_revenue_momentum = True

            fin = financial_by_id.get(r["stock_id"])
            if fin:
                entry["gross_margin"] = {
                    "period": fin["period"],
                    "source": "TWSE-t187ap06_L_ci",
                    "gross_margin_pct": fin["gross_margin"],
                    "operating_margin_pct": fin["operating_margin"],
                    "net_margin_pct": fin["net_margin"],
                    "eps": fin["eps"],
                }
                has_gross_margin = True

            river = pe_river(conn, r["stock_id"])
            if river:
                river = dict(river)
                river["note"] = ("自建歷史資料庫統計,非官方河流圖;樣本數 < 60 天時"
                                  "百分位不具參考意義") if river["sample_days"] < 60 else \
                                 "自建歷史資料庫統計,非官方河流圖"
                entry["pe_river"] = river
                has_pe_river = True

            watchlist.append(entry)
        if watchlist:
            result["watchlist"] = watchlist
            verified.append("watchlist")
            if has_revenue_momentum:
                verified.append("watchlist[].revenue_momentum")
            if has_gross_margin:
                verified.append("watchlist[].gross_margin")
            if has_pe_river:
                verified.append("watchlist[].pe_river")
            if has_price_action:
                verified.append("watchlist[].price_action")

    result["data_quality"] = {"verified": verified, "unavailable": unavailable}

    conn.close()
    return result


def export_weekly_scan(db_path, out_path):
    data = build_weekly_scan(db_path)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    return out_path
