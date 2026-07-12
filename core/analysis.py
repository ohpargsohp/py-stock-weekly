def dealer_streak(conn, days=6):
    """大盤自營商(自行買賣)近 N 日方向,判斷連續同向(核心指標)"""
    return conn.execute("""
        SELECT trade_date, dealer_self_net FROM market_chip
        ORDER BY trade_date DESC LIMIT ?
    """, (days,)).fetchall()
