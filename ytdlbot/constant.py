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
🕹 Taobao Media - Version: 2.0.0 🕹
Công cụ hỗ trợ tải ảnh/video từ nhiều nguồn
\n
***Sàn TMĐT:***
```
🇨🇳 Taobao.com
🇨🇳 1688.com
🇺🇸 Ebay.com
🇺🇸 Amazon.com (Store & Video Review)
```
***Và các trang chia sẻ video/mạng xã hội:***
```
Tiktok.com
Facebook.com
Yotube.com
Pornhub.com...
```
Và nhiều trang khác.\n
[Xem toàn bộ](https://github.com/yt-dlp/yt-dlp/blob/master/supportedsites.md)
\nGõ /help để xem thêm chi tiết!
"""

    help = f"""
1. Nếu gặp bất kỳ lỗi gì khi tải, vui lòng nhắn tin vào nhóm hỗ trợ để được hướng dẫn.
2. Mỗi thành viên sẽ có {FREE_DOWNLOAD} lượt tải miễn phí và được reset mỗi 24h.
3. Một số video khi tải về có định dạng MKV hoặc Webm sẽ không thể xem trực tiếp được, hệ thống sử tự động chuyển đổi sang định dạng MP4 để có thể xem trực tiếp trên điện thoại. Thành viên miễn phí chỉ có thể chuyển đổi video có thời lượng nhỏ hơn **5 phút**.
4. Bạn có thể mua thêm lượt tải.
"""

    about = "Phát triển dựa trên YouTube Downloader by @BennyThink.\n\nLiên hệ @cpanel10x nếu có nhu câu"

    buy = f"""
**Điều lệ:**
1. Mỗi thành viên sẽ có {FREE_DOWNLOAD} lượt tải miễn phí và được reset mỗi 24h.

2. Mua thêm lượt tải trong ngày qua @cpanel10x.

3. Không hoàn tiền dưới mọi hình thức.

4. Đối với các lượt tải trả phí sẽ không bị xếp vào hàng đợi và sẽ nhanh hơn rất nhiều.

5. Thành viên mua vip có thể tải file lớn hơn 2GB.

**Giá bán:**
Có hiệu lực ngay lập tức
1. 1 USD == {TOKEN_PRICE} tokens
2. 20K VND == {TOKEN_PRICE} tokens
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

    membership_require = f"Bạn cần bấm đăng kí theo dõi kênh thông báo Taobao Tools để có thể sử dụng bot\n\nhttps://t.me/{REQUIRED_MEMBERSHIP}"

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
            text = "Đang phân tích liên kết, vui lòng chờ...\nNếu thời gian chờ quá lâu (Hơn 3 phút), vui lòng gửi lại một lần nữa...\n\n"

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
