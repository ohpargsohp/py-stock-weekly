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


def holder_pct_streak(conn, stock_id, weeks=6):
    """個股近 N 期千張大戶(TDCC 持股分級最高級距)佔集保庫存比例的週對週增減,
    用來判斷連續加碼/派發週數(大戶籌碼動向核心指標)。
    holder_distribution 是每週更新一次的快照,回傳 (trade_date, 較前一期增減百分點)、
    最新一期在前,格式比照 dealer_streak 方便呼叫端用同一套「連續同向」邏輯處理。"""
    rows = conn.execute("""
        SELECT trade_date, big_holder_pct FROM holder_distribution
        WHERE stock_id = ? ORDER BY trade_date DESC LIMIT ?
    """, (stock_id, weeks + 1)).fetchall()
    return [(rows[i][0], round(rows[i][1] - rows[i + 1][1], 2)) for i in range(len(rows) - 1)]


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
