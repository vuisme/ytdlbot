#!/usr/local/bin/python3
# coding: utf-8

# ytdlbot - utils.py
# 9/1/21 22:50
#

__author__ = "Benny <benny.think@gmail.com>"

# import requests
import contextlib
import inspect as pyinspect
import logging
import os
import pathlib
import shutil
import subprocess
import tempfile
import time
import uuid
import re
import ffmpeg
import psutil

from db import MySQL
from flower_tasks import app
from bs4 import BeautifulSoup
from urllib.request import urlopen, Request
from config import (URL_ARRAY)
inspect = app.control.inspect()


def tbcn(tbcnurl):
    # logger.info(tbcnurl)
    uagent = "Mozilla/5.0 (iPhone; CPU iPhone OS 10_2 like Mac OS X) AppleWebKit/602.3.12 (KHTML, like Gecko) Mobile/14C92 ChannelId(3) Nebula PSDType(1) AlipayDefined(nt:WIFI,ws:375|647|2.0) AliApp(AP/10.0.1.123008) AlipayClient/10.0.1.123008 Alipay Language/zh-Hans"
    headers = {'User-Agent': uagent}
    openpage = urlopen(Request(tbcnurl, headers=headers))
    # print(openpage)
    search_page_soup = BeautifulSoup(openpage, 'html5lib')
    # print(search_page_soup)
    # logger.info(search_page_soup)
    head = search_page_soup.find_all('head')
    # logger.info(head)
    pattern = re.compile(r"var url = '(.*?)';$", re.MULTILINE | re.DOTALL)
    # logger.info(head.text)
    # logger.info(pattern.search(head[0].text))
    # logger.info(pattern.search(head[0].text).group(1))
    tblink = pattern.search(head[0].text).group(1)
    # logger.info(tblink)
    return tblink


def qr1688(url1688):
    # logger.info(tbcnurl)
    uagent = "Mozilla/5.0 (iPhone; CPU iPhone OS 10_2 like Mac OS X) AppleWebKit/602.3.12 (KHTML, like Gecko) Mobile/14C92 ChannelId(3) Nebula PSDType(1) AlipayDefined(nt:WIFI,ws:375|647|2.0) AliApp(AP/10.0.1.123008) AlipayClient/10.0.1.123008 Alipay Language/zh-Hans"
    headers = {'User-Agent': uagent}
    openpage = urlopen(Request(url1688, headers=headers))
    # print(openpage)
    search_page_soup = BeautifulSoup(openpage, 'html.parser')
    # print(search_page_soup)
    # logger.info(search_page_soup)
    script = search_page_soup.find_all('script')
    # print(script[1])
    # logger.info(head)
    pattern = re.compile(r"var shareUrl = '(.*?)';$", re.MULTILINE | re.DOTALL)
    # logger.info(head.text)
    # logger.info(pattern.search(head[0].text))
    # logger.info(pattern.search(head[0].text).group(1))
    alibabalink = pattern.search(script[1].text).group(1)
    # print(alibabalink)
    # logger.info(tblink)
    return alibabalink


def apply_log_formatter():
    logging.basicConfig(
        level=logging.INFO,
        format='[%(asctime)s %(filename)s:%(lineno)d %(levelname).1s] %(message)s',
        datefmt="%Y-%m-%d %H:%M:%S"
    )


def customize_logger(logger: "list"):
    apply_log_formatter()
    for log in logger:
        logging.getLogger(log).setLevel(level=logging.INFO)


def get_user_settings(user_id: "str") -> "tuple":
    db = MySQL()
    cur = db.cur
    cur.execute("SELECT * FROM settings WHERE user_id = %s", (user_id,))
    data = cur.fetchone()
    if data is None:
        return 100, "high", "video", "Celery"
    return data


def set_user_settings(user_id: int, field: "str", value: "str"):
    db = MySQL()
    cur = db.cur
    cur.execute("SELECT * FROM settings WHERE user_id = %s", (user_id,))
    data = cur.fetchone()
    if data is None:
        resolution = method = ""
        if field == "resolution":
            method = "video"
            resolution = value
        if field == "method":
            method = value
            resolution = "high"
        cur.execute("INSERT INTO settings VALUES (%s,%s,%s,%s)", (user_id, resolution, method, "Celery"))
    else:
        cur.execute(f"UPDATE settings SET {field} =%s WHERE user_id = %s", (value, user_id))
    db.con.commit()


def is_youtube(url: "str"):
    if url.startswith("https://www.youtube.com/") or url.startswith("https://youtu.be/"):
        return True


def add_cookies(url: "str", opt: "dict"):
    for link in URL_ARRAY:
        if link in url:
            opt['cookiefile'] = '/ytdlbot/ytdlbot/cookies/%s.txt' % link
            logging.info("add %s cookies" % link)


def add_retries(url: "str", opt: "dict"):
    if "amazon.com" in url:
        opt['extractor_retries'] = 20
        opt['retry_sleep'] = 'extractor:10'
        logging.info("add 20 times retries")


def add_proxies(url: "str", opt: "dict"):
    linkTaobao = "taobao.com"
    link1688 = "1688.com"
    if (linkTaobao in url) or (link1688 in url):
        opt['proxy'] = os.getenv("TAOBAO_PROXY")
        logging.info("add %s proxy" % linkTaobao)


def add_image_download(url: "str", opt: "dict"):
    for link in URL_ARRAY:
        if link in url:
            opt['write_all_thumbnails'] = True
            logging.info("add image download")


def adjust_formats(user_id: "str", url: "str", formats: "list", hijack=None):
    # high: best quality 1080P, 2K, 4K, 8K
    # medium: 720P
    # low: 480P
    if hijack:
        formats.insert(0, hijack)
        return

    mapping = {"high": [], "medium": [720], "low": [480]}
    settings = get_user_settings(user_id)
    if settings and is_youtube(url):
        for m in mapping.get(settings[1], []):
            formats.insert(0, f"bestvideo[vcodec^=h264][ext=mp4][height={m}]+bestaudio[ext=m4a]")
            formats.insert(1, f"bestvideo[ext=mp4][height={m}]+bestaudio[ext=m4a]")
            formats.insert(2, f"bestvideo[vcodec^=avc][height={m}]+bestaudio[acodec^=mp4a]/best[vcodec^=avc]/best")

    if settings[2] == "audio":
        formats.insert(0, "bestaudio[ext=m4a]")


def get_metadata(video_path):
    width, height, duration = 1280, 720, 0
    try:
        video_streams = ffmpeg.probe(video_path, select_streams="v")
        for item in video_streams.get("streams", []):
            height = item["height"]
            width = item["width"]
        duration = int(float(video_streams["format"]["duration"]))
    except Exception as e:
        logging.error(e)
    try:
        thumb = pathlib.Path(video_path).parent.joinpath(f"{uuid.uuid4().hex}-thunmnail.png").as_posix()
        ffmpeg.input(video_path, ss=duration / 2).filter('scale', width, -1).output(thumb, vframes=1).run()
    except ffmpeg._run.Error:
        thumb = None

    return dict(height=height, width=width, duration=duration, thumb=thumb)


def current_time(ts=None):
    return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(ts))


def get_revision():
    with contextlib.suppress(subprocess.SubprocessError):
        return subprocess.check_output("git -C ../ rev-parse --short HEAD".split()).decode("u8").replace("\n", "")
    return "unknown"


def get_func_queue(func) -> int:
    try:
        count = 0
        data = getattr(inspect, func)() or {}
        for _, task in data.items():
            count += len(task)
        return count
    except Exception:
        return 0


def tail_log(f, lines=1, _buffer=4098):
    """Tail a file and get X lines from the end"""
    # place holder for the lines found
    lines_found = []

    # block counter will be multiplied by buffer
    # to get the block size from the end
    block_counter = -1

    # loop until we find X lines
    while len(lines_found) < lines:
        try:
            f.seek(block_counter * _buffer, os.SEEK_END)
        except IOError:  # either file is too small, or too many lines requested
            f.seek(0)
            lines_found = f.readlines()
            break

        lines_found = f.readlines()

        # we found enough lines, get out
        # Removed this line because it was redundant the while will catch
        # it, I left it for history
        # if len(lines_found) > lines:
        #    break

        # decrement the block counter to get the
        # next X bytes
        block_counter -= 1

    return lines_found[-lines:]


class Detector:
    def __init__(self, logs: "str"):
        self.logs = logs

    @staticmethod
    def func_name():
        with contextlib.suppress(Exception):
            return pyinspect.stack()[1][3]
        return "N/A"

    def updates_too_long_detector(self):
        # If you're seeing this, that means you have logged more than 10 device
        # and the earliest account was kicked out. Restart the program could get you back in.
        indicators = [
            "types.UpdatesTooLong",
            "Got shutdown from remote",
            "Code is updated",
            'Retrying "messages.GetMessages"',
            "OSError: Connection lost",
            "[Errno -3] Try again",
            "MISCONF",
        ]
        for indicator in indicators:
            if indicator in self.logs:
                logging.critical("kick out crash: %s", self.func_name())
                return True
        logging.debug("No crash detected.")

    def next_salt_detector(self):
        text = "Next salt in"
        if self.logs.count(text) >= 4:
            logging.critical("Next salt crash: %s", self.func_name())
            return True

    def msg_id_detector(self):
        text = "The msg_id is too low"
        if text in self.logs:
            logging.critical("msg id crash: %s ", self.func_name())
            for item in pathlib.Path(__file__).parent.glob("ytdl-*"):
                item.unlink(missing_ok=True)
            time.sleep(3)
            return True

    def idle_detector(self):
        mtime = os.stat("/var/log/ytdl.log").st_mtime
        cur_ts = time.time()
        if cur_ts - mtime > 1800:
            logging.warning("Potential crash detected by %s, it's time to commit suicide...", self.func_name())
            return True


def auto_restart():
    log_path = "/var/log/ytdl.log"
    if not os.path.exists(log_path):
        return
    with open(log_path) as f:
        logs = "".join(tail_log(f, lines=100))

    det = Detector(logs)
    method_list = [getattr(det, func) for func in dir(det) if func.endswith("_detector")]
    for method in method_list:
        if method():
            logging.critical("%s bye bye world!☠️", method)
            for item in pathlib.Path(tempfile.gettempdir()).glob("ytdl-*"):
                shutil.rmtree(item, ignore_errors=True)
                logging.critical("removed %s", item)
            time.sleep(5)
            psutil.Process().kill()


def clean_tempfile():
    for item in pathlib.Path(tempfile.gettempdir()).glob("ytdl-*"):
        if time.time() - item.stat().st_ctime > 3600:
            shutil.rmtree(item, ignore_errors=True)


if __name__ == '__main__':
    auto_restart()
