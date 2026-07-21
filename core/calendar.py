import logging
import re
import xml.etree.ElementTree as ET
from datetime import datetime

import requests

log = logging.getLogger(__name__)
HEADERS = {"User-Agent": "Mozilla/5.0"}

_holidays = None           # None = 尚未載入;載入失敗或本身無資料時是空 set(而非 None)
_typhoon_closures = None   # None = 尚未載入;內容是「臺北市已確定停止上班」的日期(YYYYMMDD)set

# 行政院人事行政總處「天然災害停止上班及上課情形」CAP 告警 Atom feed(AlertType=33 為停班停課類別)
# 資料集頁面:https://data.gov.tw/dataset/20457
TYPHOON_FEED_URL = "https://alerts.ncdr.nat.gov.tw/RssAtomFeed.ashx?AlertType=33"
_ATOM_NS = {"atom": "http://www.w3.org/2005/Atom"}

# 摘要格式範例:'[停班停課通知]臺北市:7/10停止上班、停止上課。行政院人事行政總處。...'
_SUMMARY_RE = re.compile(r"^\[停班停課通知\](?:臺北市|台北市)[:：](?P<rest>.+)$")
_MD_RE = re.compile(r"(\d{1,2})/(\d{1,2})")


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


def _load_typhoon_closures():
    """抓天然災害停止上班上課的 CAP 告警 feed,只取「臺北市確定停止上班」的日期。

    證交所實務上跟臺北市政府的停止上班決定走(公司所在地),所以只認臺北市,
    其他縣市單獨停班停課不影響台股交易。這份 feed 平時是空的,只有颱風/地震等
    天然災害發生時才會有內容,每次執行照樣打一次 API 不會有額外負擔。

    只採信「明確寫停止上班」的公告,排除「已達停止上班及上課標準」這種預告性質
    的用語(可能還會變動,不是正式決定)。目前只解析摘要裡明確寫出的「M/D」日期,
    「今天」「明天」這種相對日期描述的公告不解析(寧可漏判,不要因為誤判日期
    而錯殺一個正常交易日)。
    """
    global _typhoon_closures
    if _typhoon_closures is not None:
        return _typhoon_closures

    _typhoon_closures = set()
    try:
        r = requests.get(TYPHOON_FEED_URL, headers=HEADERS, timeout=20)
        root = ET.fromstring(r.content)
    except (requests.RequestException, ET.ParseError) as e:
        log.warning(f"停班停課(天然災害)公告抓取失敗,本次執行不納入判斷: {e}")
        return _typhoon_closures

    for entry in root.findall("atom:entry", _ATOM_NS):
        summary_el = entry.find("atom:summary", _ATOM_NS)
        updated_el = entry.find("atom:updated", _ATOM_NS)
        if summary_el is None or summary_el.text is None or updated_el is None:
            continue

        m = _SUMMARY_RE.match(summary_el.text.strip())
        if not m:
            continue
        rest = m.group("rest")
        if "停止上班" not in rest or "已達" in rest:
            continue

        date_m = _MD_RE.search(rest)
        if not date_m:
            continue
        year = updated_el.text[:4]
        month, day = int(date_m.group(1)), int(date_m.group(2))
        _typhoon_closures.add(f"{year}{month:02d}{day:02d}")
    return _typhoon_closures


def is_trading_day(date_str):
    """判斷 date_str(YYYYMMDD)是否為台股交易日。

    回傳三態,呼叫端要分開處理,不能把 None 當成任何一種確定結果:
    - True:交易日
    - False:週末、TWSE 官方公告的休市日(含國定假日、補假、僅辦理結算交割),
      或臺北市政府已確定公告天然災害停止上班(見 _load_typhoon_closures)
    - None:年度例行休市日曆本身無法涵蓋這個年度(這支 TWSE API 沒有年度參數,
      只回傳「目前已公告」的年度,通常是當年度,約當年 Q4 起才會加上次年度),
      或抓取失敗——這兩種情況都代表「現在不知道」,不是「有交易」也不是「休市」。

    天然災害停班的判斷只會把 True 改判成 False,不會影響 None 的判定——就算
    停班公告 feed 本身抓取失敗,也只是「這次沒查到停班」,不會連累原本靠年度
    休市日曆就能確定的結果退化成無法判斷。
    """
    d = datetime.strptime(date_str, "%Y%m%d").date()
    if d.weekday() >= 5:  # 週六=5,週日=6,不用查日曆就能確定
        return False

    if date_str in _load_typhoon_closures():
        return False

    holidays = _load_holidays()
    if not holidays:
        return None

    covered_years = {h[:4] for h in holidays}
    if date_str[:4] not in covered_years:
        return None

    return date_str not in holidays
