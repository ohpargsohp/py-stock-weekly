def dealer_streak(conn, days=6):
    """大盤自營商(自行買賣)近 N 日方向,判斷連續同向(核心指標)"""
    return conn.execute("""
        SELECT trade_date, dealer_self_net FROM market_chip
        ORDER BY trade_date DESC LIMIT ?
    """, (days,)).fetchall()


def revenue_streak(conn, stock_id, periods=6):
    """個股近 N 期月營收 YoY 增減(%),用來判斷連續正/負成長(營收動能核心指標)。
    只回傳實際有 YoY 數字的期別,依 period DESC 排序(最新一期在前)。"""
    return conn.execute("""
        SELECT period, revenue_yoy_pct FROM monthly_revenue
        WHERE stock_id = ? AND revenue_yoy_pct IS NOT NULL
        ORDER BY period DESC LIMIT ?
    """, (stock_id, periods)).fetchall()


def pe_river(conn, stock_id):
    """個股歷史 PE 統計(自建版河流圖):用這支程式每天累積的 stock_quote.pe
    算出目前 PE 落在歷史分布的第幾百分位、歷史最小/最大值。
    這不是官方河流圖,樣本量完全取決於累積了多久的每日資料
    (或是否跑過 scripts/backfill_pe_history.py 回補歷史),資料點太少時
    百分位不具參考意義,呼叫端應自行依 sample_days 判斷是否要顯示警語。
    """
    rows = conn.execute("""
        SELECT trade_date, pe FROM stock_quote
        WHERE stock_id = ? AND pe IS NOT NULL
        ORDER BY trade_date
    """, (stock_id,)).fetchall()
    if not rows:
        return None

    pes_sorted = sorted(r[1] for r in rows)
    since, _ = rows[0]
    latest_date, latest_pe = rows[-1]
    n = len(pes_sorted)
    rank = sum(1 for v in pes_sorted if v <= latest_pe)
    return {
        "sample_days": n,
        "since": since,
        "as_of": latest_date,
        "current_pe": latest_pe,
        "min_pe": pes_sorted[0],
        "max_pe": pes_sorted[-1],
        "percentile": round(rank / n * 100, 1),
    }


def watchlist_industries(conn):
    """觀察名單各股票的產業別(來自 monthly_revenue,取每檔股票最新一期),
    回傳 {產業別: [stock_id, ...]}。ETF 等沒有月營收資料的標的不會出現。"""
    rows = conn.execute("""
        SELECT mr.stock_id, mr.industry
        FROM monthly_revenue mr
        WHERE mr.industry IS NOT NULL
          AND mr.period = (SELECT MAX(period) FROM monthly_revenue WHERE stock_id = mr.stock_id)
    """).fetchall()
    result = {}
    for sid, industry in rows:
        result.setdefault(industry, []).append(sid)
    return result


def industry_avg_pe(conn, industries):
    """同產業股票的 PE 平均值——僅限觀察名單內互相比較,不是全市場產業平均
    (觀察名單通常只有幾檔標的,全市場產業分類需要額外抓全市場 PE + 產業對照表,
    目前規模不做)。每檔股票各自取自己最新一天的 PE,不要求同一天,理由同
    export_json.py 對 watchlist 的處理原則。單一產業樣本數 < 2 不計算平均。
    """
    result = {}
    for industry, sids in industries.items():
        if len(sids) < 2:
            continue
        entries = []
        for sid in sids:
            row = conn.execute("""
                SELECT trade_date, pe FROM stock_quote
                WHERE stock_id = ? AND pe IS NOT NULL
                ORDER BY trade_date DESC LIMIT 1
            """, (sid,)).fetchone()
            if row:
                entries.append({"stock_id": sid, "trade_date": row[0], "pe": row[1]})
        if len(entries) < 2:
            continue
        pes = [e["pe"] for e in entries]
        result[industry] = {
            "members": entries,
            "avg_pe": round(sum(pes) / len(pes), 2),
            "sample_size": len(pes),
        }
    return result
