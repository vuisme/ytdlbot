#!/usr/local/bin/python3
# coding: utf-8

# ytdlbot - constant.py
# 8/16/21 16:59
#

__author__ = "Benny <benny.think@gmail.com>"

import os

from config import (
    AFD_LINK,
    COFFEE_LINK,
    ENABLE_CELERY,
    FREE_DOWNLOAD,
    REQUIRED_MEMBERSHIP,
    TOKEN_PRICE,
)
from database import InfluxDB
from utils import get_func_queue


class BotText:
    start = """
    Taobao Media Version 3.0.0
    Miễn phí: 10 lượt tải/ngày.
    Premium: 50 lượt tải/ngày, hỗ trợ tải thêm ảnh và video trong mô tả sản phẩm

    Gõ /help để biết thêm chi tiết"""

    help = """
Gửi đúng định dạng link để ít gặp lỗi không đáng có!
1. Hỗ trợ tải từ Taobao (link dạng item.taobao.com, tmall.com, tb.cn...)

2. Hỗ trợ tải từ Pindoudou (link dạng mobile.yangkedou.com)

3. Tải từ YouTube và các trang media lớn (kể cả pornhub, xnxx...) mà plugin yt-dlp hỗ trợ, chỉ cần gửi link để thử.

4. Một số link đặc biệt cần dùng lệnh `/spdl {liên kết}`. Xem thêm các link đó tại https://github.com/SanujaNS/ytdlbot-telegram#supported-websites 

5. Gặp lỗi hãy gửi vào kênh hỗ trợ.

6. Wanna deploy it yourself?\nHere's the source code: https://github.com/tgbot-collection/ytdlbot
    """

    about = "Taobao Media Bot Ver 3.0.0 by @cpanel10x. \n\nPhát triển từ YouTube Downloader by @BennyThink.\n\nOpen source on GitHub: https://github.com/tgbot-collection/ytdlbot"

    buy = f"""
**Terms:**
1. You can use this bot to download video for {FREE_DOWNLOAD} times within a 24-hour period.

2. You can buy additional download tokens, valid permanently.

3. Refunds are possible, contact me if you need that @cpanel10x

4. Download for paid user will be automatically changed to Local mode to avoid queuing.

5. Paid user can download files larger than 2GB.

**Price:**
valid permanently
1. 1 USD == {TOKEN_PRICE} tokens
2. 7 CNY == {TOKEN_PRICE} tokens
3. 10 TRX == {TOKEN_PRICE} tokens

**Payment options:**
Pay any amount you want. For example you can send 20 TRX for {TOKEN_PRICE * 2} tokens.
1. AFDIAN(AliPay, WeChat Pay and PayPal): {AFD_LINK}
2. Buy me a coffee: {COFFEE_LINK}
3. Telegram Bot Payment(Stripe), please click Bot Payment button.
4. TRON(TRX), please click TRON(TRX) button.

**After payment:**
1. Afdian: attach order number with /redeem command (e.g., `/redeem 123456`).
2. Buy Me a Coffee: attach email with /redeem command (e.g., `/redeem 123@x.com`). **Use different email each time.**
3. Telegram Payment & Tron(TRX): automatically activated within 60s. Check /start to see your balance.

Want to buy more token with Telegram payment? Let's say 100? Here you go! `/buy 123`
    """

    private = "This bot is for private use"

    membership_require = f"You need to join this group or channel to use this bot\n\nhttps://t.me/{REQUIRED_MEMBERSHIP}"

    settings = """
Please choose the preferred format and video quality for your video. These settings only **apply to YouTube videos**.

High quality is recommended. Medium quality aims to 720P, while low quality is 480P.

If you choose to send the video as a document, it will not be possible to stream it.

Your current settings:
Video quality: **{0}**
Sending format: **{1}**
"""
    custom_text = os.getenv("CUSTOM_TEXT", "")

    premium_warning = """
    Your file is too big, do you want me to try to send it as premium user? 
    This is an experimental feature so you can only use it once per day.
    Also, the premium user will know who you are and what you are downloading. 
    You may be banned if you abuse this feature.
    """

    @staticmethod
    def get_receive_link_text() -> str:
        reserved = get_func_queue("reserved")
        if ENABLE_CELERY and reserved:
            text = f"Your tasks was added to the reserved queue {reserved}. Processing...\n\n"
        else:
            text = "Your task was added to active queue.\nProcessing...\n\n"

        return text

    @staticmethod
    def ping_worker() -> str:
        from tasks import app as celery_app

        workers = InfluxDB().extract_dashboard_data()
        # [{'celery@BennyのMBP': 'abc'}, {'celery@BennyのMBP': 'abc'}]
        response = celery_app.control.broadcast("ping_revision", reply=True)
        revision = {}
        for item in response:
            revision.update(item)

        text = ""
        for worker in workers:
            fields = worker["fields"]
            hostname = worker["tags"]["hostname"]
            status = {True: "✅"}.get(fields["status"], "❌")
            active = fields["active"]
            load = "{},{},{}".format(fields["load1"], fields["load5"], fields["load15"])
            rev = revision.get(hostname, "")
            text += f"{status}{hostname} **{active}** {load} {rev}\n"

        return text
