from abc import ABC, abstractmethod


class DataProvider(ABC):
    """所有數據源共用的介面。新增數據源只需繼承此類別、丟進 providers/，
    不用修改 main.py / storage.py 或其他 provider。"""

    name: str = "base"           # 資料表名
    schema: dict = {}            # {欄位名: SQL型別}
    pk: list = ["trade_date"]    # 主鍵(冪等用)
    # 補抓窗口(交易日數):> 0 時,main.py 每次執行除了抓 date_str 本身,還會往回檢查
    # 前 N 個交易日,資料表裡缺哪天就補抓哪天。給「公布時間晚於排程時間」的資料源用
    # (例如 MI_MARGN/TWT93U 約 21:00 後才公布,20:00 排程當天必定抓不到),
    # 讓隔天的排程自動補上前一天,不必依賴人工深夜重跑。
    catchup_days: int = 0

    @abstractmethod
    def fetch(self, date_str: str) -> list:
        """回傳 list of dict,每個 dict 的 key 對應 schema。無資料(如休市)回 []"""
        ...

    def describe(self, rows: list):
        """選配:自訂主控台輸出文字。回 None 則用 main.py 的預設訊息。"""
        return None
