import os
import smtplib
from email.message import EmailMessage
from pathlib import Path


def send_report(attachments):
    """寄送每日籌碼報表。attachments: 檔案路徑 list。
    需在專案根目錄的 .env 設定 SENDER_EMAIL、SENDER_APP_PASSWORD
    (Gmail 應用程式密碼,不是登入密碼)與 EMAIL_TO(收件地址)。
    任一未設定則略過寄信,不中斷主流程。
    """
    sender = os.environ.get("SENDER_EMAIL")
    app_password = os.environ.get("SENDER_APP_PASSWORD")
    email_to = os.environ.get("EMAIL_TO")
    if not sender or not app_password or not email_to:
        print("⚠️ 未設定 SENDER_EMAIL / SENDER_APP_PASSWORD / EMAIL_TO,略過寄信")
        return

    existing = [Path(p) for p in attachments if Path(p).exists()]
    if not existing:
        print("⚠️ 找不到任何附件檔案,略過寄信")
        return

    msg = EmailMessage()
    msg["Subject"] = f"股票籌碼日報 {existing[0].stem}"
    msg["From"] = sender
    msg["To"] = email_to
    msg.set_content("附件為今日籌碼追蹤報表,詳見附加檔案。")

    for p in existing:
        msg.add_attachment(
            p.read_bytes(), maintype="application", subtype="octet-stream", filename=p.name
        )

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as smtp:
        smtp.login(sender, app_password)
        smtp.send_message(msg)
    print(f"📧 已寄出報表至 {email_to}")
