#!/usr/local/bin/python3
# coding: utf-8

# ytdlbot - constant.py
# 8/16/21 16:59
#

__author__ = "Benny <benny.think@gmail.com>"

import os
import time
import logging

from config import (AFD_LINK, BURST, COFFEE_LINK, ENABLE_CELERY, ENABLE_VIP,
                    EX, MULTIPLY, RATE, REQUIRED_MEMBERSHIP, USD2CNY)
from db import InfluxDB
from downloader import sizeof_fmt
from limit import QUOTA, VIP
from utils import get_func_queue, customize_logger

customize_logger(["pyrogram.client", "pyrogram.session.session", "pyrogram.connection.connection"])
logging.getLogger('apscheduler.executors.default').propagate = False

class BotText:
    start = "Taobao Media 1.1.6 - Công cụ hỗ trợ tải ảnh/video từ nhiều nguồn. Gõ /help để xem thêm chi tiết!"

    help = f"""
1. Nếu gặp bất kỳ lỗi gì khi tải, vui lòng nhắn tin vào nhóm hỗ trợ.

2. Duy trì bot hoạt động rất tốn kém do đặc thù việc tải và gửi video chiếm băng thông rất nhiều, vì vậy chúng tôi giới hạn **{sizeof_fmt(QUOTA)} dung lượng mỗi {int(EX / 3600)} giờ.**

3. Một số video khi tải về có định dạng MKV hoặc Webm sẽ không thể xem trực tiếp được, hệ thống sử tự động chuyển đổi sang định dạng MP4 để có thể xem trực tiếp trên điện thoại. Thành viên miễn phí chỉ có thể chuyển đổi video có thời lượng nhỏ hơn **5 phút**.

4. Bạn có thể trở thành 'VIP' nếu có nhu cầu dung lượng cao hơn hoặc không giới hạn chuyển đổi định dạng. Gõ /vip để biết thêm chi tiết.

5. Giới hạn số lần request áp dụng cho mọi thành viên ngoại trừ VIP.

6. For english, type /en

    """ if ENABLE_VIP else "Help text"

    about = "Công cụ được phát triển từ YouTube-DL bởi @BennyThink. Mã nguồn mở trên GitHub: https://github.com/tgbot-collection/ytdlbot"

    terms = f"""
1. Thành viên miễn phí có thể sử dụng {sizeof_fmt(QUOTA)} mỗi {int(EX / 3600)} giờ.

2. Công cụ không thu nhập dữ liệu cá nhân từ người dùng ngoài ID Telegram

3. Để trở thành VIP và hưởng các đặc quyền, vui lòng gõ /vip
    """ if ENABLE_VIP else "Please contact the actual owner of this bot"

    vip = f"""
**Điều lệ:**
1. Không hoàn tiền.
2. VIPs trạng thái VIP và các đặc quyền sẽ có thời hạn sử dụng vĩnh viễn.

**Các hạng:**
1. Miễn phí: {sizeof_fmt(QUOTA)} mỗi {int(EX / 3600)} giờ
2. VIP1: ${MULTIPLY} or ¥{MULTIPLY * USD2CNY}, {sizeof_fmt(QUOTA * 5)} per {int(EX / 3600)} hours
3. VIP2: ${MULTIPLY * 2} or ¥{MULTIPLY * USD2CNY * 2}, {sizeof_fmt(QUOTA * 5 * 2)} per {int(EX / 3600)} hours
4. VIP4....VIPn.
5. Unlimited streaming conversion support.
Note: If you pay $9, you'll become VIP1 instead of VIP2.

**Payment method:**
1. (afdian) Mainland China: {AFD_LINK}
2. (buy me a coffee) Other countries or regions: {COFFEE_LINK}

**After payment:**
1. afdian: with your order number `/vip 123456`
2. buy me a coffee: with your email `/vip someone@else.com`
    """ if ENABLE_VIP else "VIP is not enabled."
    vip_pay = "Processing your payments...If it's not responding after one minute, please contact @BennyThink."

    private = "This bot is for private use"
    membership_require = f"You need to join this group or channel to use this bot\n\nhttps://t.me/{REQUIRED_MEMBERSHIP}"

    settings = """
Select sending format and video quality. **Only applies to YouTube**
High quality is recommended; Medium quality is aimed as 480P while low quality is aimed as 360P and 240P.

Remember if you choose to send as document, there will be no streaming.

Your current settings:
Video quality: **{0}**
Sending format: **{1}**
"""
    custom_text = os.getenv("CUSTOM_TEXT", "")

    def remaining_quota_caption(self, chat_id):
        if not ENABLE_VIP:
            return ""
        used, total, ttl = self.return_remaining_quota(chat_id)
        refresh_time = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(ttl + time.time()))
        caption = f"Remaining quota: **{sizeof_fmt(used)}/{sizeof_fmt(total)}**, " \
                  f"refresh at {refresh_time}\n"
        return caption

    @staticmethod
    def return_remaining_quota(chat_id):
        used, total, ttl = VIP().check_remaining_quota(chat_id)
        return used, total, ttl

    @staticmethod
    def get_vip_greeting(chat_id):
        if not ENABLE_VIP:
            return ""
        v = VIP().check_vip(chat_id)
        if v:
            return f"Hello {v[1]}, VIP{v[-2]}☺️\n\n"
        else:
            return ""

    @staticmethod
    def get_receive_link_text():
        reserved = get_func_queue("reserved")
        if ENABLE_CELERY and reserved:
            text = f"Too many tasks. Your tasks was added to the reserved queue {reserved}."
        else:
            text = "Đang lấy ảnh/video, vui lòng chờ...\nProcessing...\n\n"

        return text

    @staticmethod
    def ping_worker():
        from tasks import app as celery_app
        workers = InfluxDB().extract_dashboard_data()
        # logging.info(workers)
        # [{'celery@BennyのMBP': 'abc'}, {'celery@BennyのMBP': 'abc'}]
        response = celery_app.control.broadcast("ping_revision", reply=True)
        logging.info("response is %s", response)
        # revision = {}
        # for item in response:
        #     revision.update(item)
        text = "Online Servers: \n```"
        if response is not None:
            for i in range(len(response)):
                text += f"{list(response[i].keys())[0]} 🟢\n"
                text += "```"
            logging.info(text)
        else:
            text = "All server offline 🔴\n```"
            logging.info(text)
        return text
        # for worker in workers:
        #     fields = worker["fields"]
        #     hostname = worker["tags"]["hostname"]
        #     status = {True: "✅"}.get(fields["status"], "❌")
        #     active = fields["active"]
        #     load = "{},{},{}".format(fields["load1"], fields["load5"], fields["load15"])
        #     rev = revision.get(hostname, "")
        #     text += f"{status}{hostname} **{active}** {load} {rev}\n"

        # return text
    too_fast = f"Bạn đã vượt quá giới hạn cho phép. Chỉ được gửi 01 request mỗi {RATE} giây, {BURST - 1} bursts."
