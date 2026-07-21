import logging
from datetime import datetime

import requests

log = logging.getLogger(__name__)
HEADERS = {"User-Agent": "Mozilla/5.0"}

_holidays = None  # None = 尚未載入;載入失敗或本身無資料時是空 set(而非 None),見 _load_holidays()


def _roc_to_ymd(roc_date):
    """'1150101' -> '20260101'"""
    return f"{int(roc_date[:-4]) + 1911:04d}{roc_date[-4:-2]}{roc_date[-2:]}"


def _load_holidays():
    """抓 TWSE 官方休市日期公告,只做一次(結果快取在模組層級的 _holidays,
    同一次執行(單一 python main.py 進程)裡重複呼叫 is_trading_day() 不會重複打 API)。"""
    global _holidays
    if _holidays is not None:
        return _holidays

    _holidays = set()
    try:
        r = requests.get(
            "https://openapi.twse.com.tw/v1/holidaySchedule/holidaySchedule",
            headers=HEADERS, timeout=20,
        )
        data = r.json()
    except (requests.RequestException, ValueError) as e:
        log.warning(f"交易日曆抓取失敗,本次執行無法判斷休市: {e}")
        return _holidays

    for row in data:
        # 這份清單裡混了兩種性質不同的項目:「農曆春節前最後交易日」「XX後開始交易日」
        # 只是提醒性質的交易日標記(市場當天正常交易),不是休市日;其餘(國定假日、
        # 補假、「僅辦理結算交割作業」等)才是真正不交易的日子。用 Name 是否含
        # 「交易日」三字排除前者,避免把正常交易日誤判成休市。
        if "交易日" in row.get("Name", ""):
            continue
        ymd = _roc_to_ymd(row["Date"])
        if ymd:
            _holidays.add(ymd)
    return _holidays


def is_trading_day(date_str):
    """判斷 date_str(YYYYMMDD)是否為台股交易日。

    回傳三態,呼叫端要分開處理,不能把 None 當成任何一種確定結果:
    - True:交易日
    - False:週末,或 TWSE 官方公告的休市日(含國定假日、補假、僅辦理結算交割)
    - None:日曆本身無法涵蓋這個年度(這支 TWSE API 沒有年度參數,只回傳「目前已
      公告」的年度,通常是當年度,約當年 Q4 起才會加上次年度),或抓取失敗——
      這兩種情況都代表「現在不知道」,不是「有交易」也不是「休市」。
    """
    d = datetime.strptime(date_str, "%Y%m%d").date()
    if d.weekday() >= 5:  # 週六=5,週日=6,不用查日曆就能確定
        return False

    holidays = _load_holidays()
    if not holidays:
        return None

    covered_years = {h[:4] for h in holidays}
    if date_str[:4] not in covered_years:
        return None

    return date_str not in holidays
