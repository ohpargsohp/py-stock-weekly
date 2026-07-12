import sqlite3

from openpyxl import Workbook
from openpyxl.styles import Font
from openpyxl.utils import get_column_letter


def export_excel(db_path, out_path):
    """把資料庫裡每張表匯出成 Excel 的一個分頁,最新日期排最上面。"""
    conn = sqlite3.connect(db_path)
    tables = [r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]

    wb = Workbook()
    wb.remove(wb.active)

    for t in tables:
        cols = [r[1] for r in conn.execute(f"PRAGMA table_info({t})")]
        order_col = "trade_date" if "trade_date" in cols else cols[0]
        rows = conn.execute(f"SELECT * FROM {t} ORDER BY {order_col} DESC").fetchall()

        ws = wb.create_sheet(title=t[:31])
        ws.append(cols)
        for cell in ws[1]:
            cell.font = Font(bold=True)
        ws.freeze_panes = "A2"

        widths = [len(c) for c in cols]
        for row in rows:
            ws.append(list(row))
            for i, v in enumerate(row):
                widths[i] = max(widths[i], len(str(v)))
        for i, w in enumerate(widths, 1):
            ws.column_dimensions[get_column_letter(i)].width = min(w + 2, 40)

    conn.close()
    wb.save(out_path)
    return out_path
