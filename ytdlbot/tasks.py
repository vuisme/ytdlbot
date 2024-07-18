#!/usr/local/bin/python3
# coding: utf-8

# ytdlbot - tasks.py
# 12/29/21 14:57
#

__author__ = "Benny <benny.think@gmail.com>"

import asyncio
import logging
import os
import pathlib
import re
import shutil
import subprocess
import tempfile
import threading
import time
import traceback
import typing
from typing import Any, List
from urllib.parse import quote_plus
from pathlib import Path

import filetype
import psutil
import pyrogram.errors
import requests
from apscheduler.schedulers.background import BackgroundScheduler
from celery import Celery
from celery.worker.control import Panel
from pyrogram import Client, enums, idle, types
from pyrogram.types import InputMediaPhoto, InputMediaVideo

from channel import Channel
from client_init import create_app
from config import (
    ARCHIVE_ID,
    BROKER,
    ENABLE_CELERY,
    ENABLE_VIP,
    OWNER,
    RATE_LIMIT,
    RCLONE_PATH,
    TMPFILE_PATH,
    WORKERS,
    FileTooBig,
)
from constant import BotText
from database import Redis, MySQL
from downloader import edit_text, tqdm_progress, upload_hook, ytdl_download
from sp_downloader import sp_dl
from limit import Payment
from utils import (
    apply_log_formatter,
    auto_restart,
    customize_logger,
    get_metadata,
    get_revision,
    sizeof_fmt,
)

customize_logger(["pyrogram.client", "pyrogram.session.session", "pyrogram.connection.connection"])
apply_log_formatter()
bot_text = BotText()
logging.getLogger("apscheduler.executors.default").propagate = False

app = Celery("tasks", broker=BROKER)
bot = create_app("tasks")
channel = Channel()


def retrieve_message(chat_id: int, message_id: int) -> types.Message | Any:
    # this should only be called by celery tasks
    try:
        return bot.get_messages(chat_id, message_id)
    except ConnectionError as e:
        logging.critical("BOT IS NOT STARTED YET: %s", e)
        bot.start()
        return bot.get_messages(chat_id, message_id)


def premium_button(user_id):
    redis = Redis()
    payment = Payment()
    used = redis.r.hget("premium", user_id)
    ban = redis.r.hget("ban", user_id)
    paid_token = payment.get_pay_token(user_id)

    if ban:
        return None
    # vip mode: vip user can use once per day, normal user can't use
    # non vip mode: everyone can use once per day
    if used or (ENABLE_VIP and paid_token == 0):
        return None

    markup = types.InlineKeyboardMarkup(
        [
            [
                types.InlineKeyboardButton("Yes", callback_data="premium-yes"),
                types.InlineKeyboardButton("No", callback_data="premium-no"),
            ]
        ]
    )
    return markup


@app.task(rate_limit=f"{RATE_LIMIT}/m")
def ytdl_download_task(chat_id: int, message_id: int, url: str):
    logging.info("YouTube celery tasks started for %s", url)
    bot_msg = retrieve_message(chat_id, message_id)
    try:
        ytdl_normal_download(bot, bot_msg, url)
    except FileTooBig as e:
        # if you can go there, that means you have premium users set up
        logging.warning("Seeking for help from premium user...")
        markup = premium_button(chat_id)
        if markup:
            bot_msg.edit_text(f"{e}\n\n{bot_text.premium_warning}", reply_markup=markup)
        else:
            bot_msg.edit_text(f"{e}\nBig file download is not available now. Please /buy or try again later ")
    except Exception:
        error_msg = traceback.format_exc().split("yt_dlp.utils.DownloadError: ERROR: ")
        if len(error_msg) > 1:
            bot_msg.edit_text(f"Download failed!❌\n\n`{error_msg[-1]}", disable_web_page_preview=True)
        else:
            bot_msg.edit_text(f"Download failed!❌\n\n`{traceback.format_exc()[-2000:]}`", disable_web_page_preview=True)
    logging.info("YouTube celery tasks ended.")


@app.task()
def audio_task(chat_id: int, message_id: int):
    logging.info("Audio celery tasks started for %s-%s", chat_id, message_id)
    bot_msg = retrieve_message(chat_id, message_id)
    normal_audio(bot, bot_msg)
    logging.info("Audio celery tasks ended.")


@app.task()
def direct_download_task(chat_id: int, message_id: int, url: str):
    logging.info("Direct download celery tasks started for %s", url)
    bot_msg = retrieve_message(chat_id, message_id)
    direct_normal_download(bot, bot_msg, url)
    logging.info("Direct download celery tasks ended.")


@app.task()
def image_task(chat_id: int, message_id: int):
    logging.info("Image celery tasks started for %s-%s", chat_id, message_id)
    bot_msg = retrieve_message(chat_id, message_id)
    normal_image(bot, bot_msg)
    logging.info("Image celery tasks ended.")


def get_unique_clink(original_url: str, user_id: int):
    payment = Payment()
    settings = payment.get_user_settings(user_id)
    clink = channel.extract_canonical_link(original_url)
    try:
        # different user may have different resolution settings
        unique = "{}?p={}{}".format(clink, *settings[1:])
    except IndexError:
        unique = clink
    return unique


def forward_video(client, bot_msg: types.Message | Any, url: str, cached_fid: str):
    res_msg = upload_processor(client, bot_msg, url, cached_fid)
    obj = res_msg.document or res_msg.video or res_msg.audio or res_msg.animation or res_msg.photo

    caption, _ = gen_cap(bot_msg, url, obj)
    res_msg.edit_text(caption, reply_markup=gen_video_markup())
    bot_msg.edit_text(f"Download success!✅")
    return True


def ytdl_download_entrance(client: Client, bot_msg: types.Message, url: str, mode=None):
    # in Local node and forward mode, we pass client from main
    # in celery mode, we need to use our own client called bot
    payment = Payment()
    redis = Redis()
    chat_id = bot_msg.chat.id
    unique = get_unique_clink(url, chat_id)
    cached_fid = redis.get_send_cache(unique)

    try:
        if cached_fid:
            forward_video(client, bot_msg, url, cached_fid)
            redis.update_metrics("cache_hit")
            return
        redis.update_metrics("cache_miss")
        mode = mode or payment.get_user_settings(chat_id)[3]
        if ENABLE_CELERY and mode in [None, "Celery"]:
            # in celery mode, producer has lost control of this task.
            ytdl_download_task.delay(chat_id, bot_msg.id, url)
        else:
            ytdl_normal_download(client, bot_msg, url)
    except FileTooBig as e:
        logging.warning("Seeking for help from premium user...")
        # this is only for normal node. Celery node will need to do it in celery tasks
        markup = premium_button(chat_id)
        if markup:
            bot_msg.edit_text(f"{e}\n\n{bot_text.premium_warning}", reply_markup=markup)
        else:
            bot_msg.edit_text(f"{e}\nBig file download is not available now. Please /buy or try again later ")
    except Exception as e:
        logging.error("Failed to download %s, error: %s", url, e)
        error_msg = traceback.format_exc().split("yt_dlp.utils.DownloadError: ERROR: ")
        if len(error_msg) > 1:
            bot_msg.edit_text(f"Download failed!❌\n\n`{error_msg[-1]}", disable_web_page_preview=True)
        else:
            bot_msg.edit_text(f"Download failed!❌\n\n`{traceback.format_exc()[-2000:]}`", disable_web_page_preview=True)


def direct_download_entrance(client: Client, bot_msg: typing.Union[types.Message, typing.Coroutine], url: str):
    if ENABLE_CELERY:
        direct_normal_download(client, bot_msg, url)
        # direct_download_task.delay(bot_msg.chat.id, bot_msg.id, url)
    else:
        direct_normal_download(client, bot_msg, url)


def spdl_download_entrance(client: Client, bot_msg: types.Message, url: str, mode=None):
    payment = Payment()
    redis = Redis()
    chat_id = bot_msg.chat.id
    unique = get_unique_clink(url, chat_id)
    cached_fid = redis.get_send_cache(unique)
    
    try:
        if cached_fid:
            forward_video(client, bot_msg, url, cached_fid)
            redis.update_metrics("cache_hit")
            return
        redis.update_metrics("cache_miss")
        mode = mode or payment.get_user_settings(chat_id)[3]
        spdl_normal_download(client, bot_msg, url)
    except FileTooBig as e:
        logging.warning("Seeking for help from premium user...")
        # this is only for normal node. Celery node will need to do it in celery tasks
        markup = premium_button(chat_id)
        if markup:
            bot_msg.edit_text(f"{e}\n\n{bot_text.premium_warning}", reply_markup=markup)
        else:
            bot_msg.edit_text(f"{e}\nBig file download is not available now. Please /buy or try again later ")
    except ValueError as e:
        logging.error("Invalid URL provided: %s", e)
        bot_msg.edit_text(f"Download failed!❌\n\n{e}", disable_web_page_preview=True)
    except Exception as e:
        logging.error("Failed to download %s, error: %s", url, e)
        error_msg = "Sorry, Something went wrong."
        bot_msg.edit_text(f"Download failed!❌\n\n`{error_msg}", disable_web_page_preview=True)


def cn_download_entrance(client: Client, bot_msg: types.Message, url: str, mode=None):
    payment = Payment()
    redis = Redis()
    chat_id = bot_msg.chat.id
    unique = get_unique_clink(url, chat_id)
    cached_fid = redis.get_send_cache(unique)
    
    try:
        if cached_fid:
            forward_video(client, bot_msg, url, cached_fid)
            redis.update_metrics("cache_hit")
            return
        redis.update_metrics("cache_miss")
        mode = mode or payment.get_user_settings(chat_id)[3]
        cn_normal_download(client, bot_msg, url)
    except FileTooBig as e:
        logging.warning("Seeking for help from premium user...")
        # this is only for normal node. Celery node will need to do it in celery tasks
        markup = premium_button(chat_id)
        if markup:
            bot_msg.edit_text(f"{e}\n\n{bot_text.premium_warning}", reply_markup=markup)
        else:
            bot_msg.edit_text(f"{e}\nBig file download is not available now. Please /buy or try again later ")
    except ValueError as e:
        logging.error("Invalid URL provided: %s", e)
        bot_msg.edit_text(f"Download failed!❌\n\n{e}", disable_web_page_preview=True)
    except Exception as e:
        logging.error("Failed to download %s, error: %s", url, e)
        error_msg = "Sorry, Something went wrong."
        bot_msg.edit_text(f"Download failed!❌\n\n`{error_msg}", disable_web_page_preview=True)
        

def audio_entrance(client: Client, bot_msg: types.Message):
    if ENABLE_CELERY:
        audio_task.delay(bot_msg.chat.id, bot_msg.id)
    else:
        normal_audio(client, bot_msg)


def image_entrance(client: Client, bot_msg: types.Message):
    if ENABLE_CELERY:
        image_task.delay(bot_msg.chat.id, bot_msg.id)
    else:
        normal_image(client, bot_msg)


def direct_normal_download(client: Client, bot_msg: typing.Union[types.Message, typing.Coroutine], url: str):
    chat_id = bot_msg.chat.id
    headers = {
        "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.3987.149 Safari/537.36"
    }
    length = 0

    req = None
    try:
        req = requests.get(url, headers=headers, stream=True)
        length = int(req.headers.get("content-length"))
        filename = re.findall("filename=(.+)", req.headers.get("content-disposition"))[0]
    except TypeError:
        filename = getattr(req, "url", "").rsplit("/")[-1]
    except Exception as e:
        bot_msg.edit_text(f"Download failed!❌\n\n```{e}```", disable_web_page_preview=True)
        return

    if not filename:
        filename = quote_plus(url)

    with tempfile.TemporaryDirectory(prefix="ytdl-", dir=TMPFILE_PATH) as f:
        filepath = f"{f}/{filename}"
        # consume the req.content
        downloaded = 0
        for chunk in req.iter_content(1024 * 1024):
            text = tqdm_progress("Downloading...", length, downloaded)
            edit_text(bot_msg, text)
            with open(filepath, "ab") as fp:
                fp.write(chunk)
            downloaded += len(chunk)
        logging.info("Downloaded file %s", filename)
        st_size = os.stat(filepath).st_size

        client.send_chat_action(chat_id, enums.ChatAction.UPLOAD_DOCUMENT)
        client.send_document(
            bot_msg.chat.id,
            filepath,
            caption=f"filesize: {sizeof_fmt(st_size)}",
            progress=upload_hook,
            progress_args=(bot_msg,),
        )
        bot_msg.edit_text("Download success!✅")


def normal_image(client: Client, bot_msg: typing.Union[types.Message, typing.Coroutine]):
    url: str = re.findall(r"https?://.*", bot_msg.caption)[0]
    chat_id = bot_msg.chat.id
    temp_dir = tempfile.TemporaryDirectory(prefix="cndl-", dir=TMPFILE_PATH)
    status_msg: typing.Union[types.Message, typing.Coroutine] = bot_msg.reply_text(
        "Đang lấy ảnh, vui lòng chờ...", quote=True
    )
    chat_id = bot_msg.chat.id
    try:
        # Download video and get file paths
        downloaded_paths = sp_dl(url, temp_dir.name, bot_msg)
        logging.info("Download complete.")
        logging.info(downloaded_paths)
        if not downloaded_paths:
            bot_msg.edit_text("Không có ảnh và video phù hợp.")
            return
        # Notify user about upload progress
        client.send_chat_action(chat_id, enums.ChatAction.UPLOAD_DOCUMENT)
        bot_msg.edit_text("Đã tải xong, đang upload...")
        image_categories = ["topImages", "baseImages", "skuImages", "descImages"]
        for category in image_categories:
            if category in downloaded_paths:
                image_list = [img_info['url'] for img_info in downloaded_paths[category]]
                logging.info(category)
                logging.info(image_list)    
                send_images(client, bot_msg, chat_id, url, category, image_list)
            else:
                logging.info("No images found for %s", category)
        if RCLONE_PATH:
            for item in os.listdir(temp_dir.name):
                logging.info("Copying %s to %s", item, RCLONE_PATH)
                shutil.copy(os.path.join(temp_dir.name, item), RCLONE_PATH)
    finally:
        temp_dir.cleanup()


def normal_audio(client: Client, bot_msg: typing.Union[types.Message, typing.Coroutine]):
    chat_id = bot_msg.chat.id
    # fn = getattr(bot_msg.video, "file_name", None) or getattr(bot_msg.document, "file_name", None)
    status_msg: typing.Union[types.Message, typing.Coroutine] = bot_msg.reply_text(
        "Converting to audio...please wait patiently", quote=True
    )
    orig_url: str = re.findall(r"https?://.*", bot_msg.caption)[0]
    with tempfile.TemporaryDirectory(prefix="ytdl-", dir=TMPFILE_PATH) as tmp:
        client.send_chat_action(chat_id, enums.ChatAction.RECORD_AUDIO)
        # just try to download the audio using yt-dlp
        filepath = ytdl_download(orig_url, tmp, status_msg, hijack="bestaudio[ext=m4a]")
        status_msg.edit_text("Sending audio now...")
        client.send_chat_action(chat_id, enums.ChatAction.UPLOAD_AUDIO)
        for f in filepath:
            client.send_audio(chat_id, f)
        status_msg.edit_text("✅ Conversion complete.")
        Redis().update_metrics("audio_success")


def ytdl_normal_download(client: Client, bot_msg: types.Message | typing.Any, url: str):
    """
    This function is called by celery task or directly by bot
    :param client: bot client, either from main or bot(celery)
    :param bot_msg: bot message
    :param url: url to download
    """
    chat_id = bot_msg.chat.id
    temp_dir = tempfile.TemporaryDirectory(prefix="ytdl-", dir=TMPFILE_PATH)

    video_paths = ytdl_download(url, temp_dir.name, bot_msg)
    logging.info("Download complete.")
    client.send_chat_action(chat_id, enums.ChatAction.UPLOAD_DOCUMENT)
    bot_msg.edit_text("Download complete. Sending now...")
    data = MySQL().get_user_settings(chat_id)
    if data[4] == "ON":
        logging.info("Adding to history...")
        MySQL().add_history(chat_id, url, pathlib.Path(video_paths[0]).name)
    try:
        upload_processor(client, bot_msg, url, video_paths)
    except pyrogram.errors.Flood as e:
        logging.critical("FloodWait from Telegram: %s", e)
        client.send_message(
            chat_id,
            f"I'm being rate limited by Telegram. Your video will come after {e} seconds. Please wait patiently.",
        )
        client.send_message(OWNER, f"CRITICAL INFO: {e}")
        time.sleep(e.value)
        upload_processor(client, bot_msg, url, video_paths)

    bot_msg.edit_text("Download success!✅")

    # setup rclone environment var to back up the downloaded file
    if RCLONE_PATH:
        for item in os.listdir(temp_dir.name):
            logging.info("Copying %s to %s", item, RCLONE_PATH)
            shutil.copy(os.path.join(temp_dir.name, item), RCLONE_PATH)
    temp_dir.cleanup()


def spdl_normal_download(client: Client, bot_msg: types.Message | typing.Any, url: str):
    chat_id = bot_msg.chat.id
    temp_dir = tempfile.TemporaryDirectory(prefix="spdl-", dir=TMPFILE_PATH)

    video_paths = sp_dl(url, temp_dir.name, bot_msg)
    logging.info("Download complete.")
    client.send_chat_action(chat_id, enums.ChatAction.UPLOAD_DOCUMENT)
    bot_msg.edit_text("Download complete. Sending now...")
    data = MySQL().get_user_settings(chat_id)
    if data[4] == "ON":
        logging.info("Adding to history...")
        MySQL().add_history(chat_id, url, pathlib.Path(video_paths[0]).name)
    try:
        upload_processor(client, bot_msg, url, video_paths)
    except pyrogram.errors.Flood as e:
        logging.critical("FloodWait from Telegram: %s", e)
        client.send_message(
            chat_id,
            f"I'm being rate limited by Telegram. Your video will come after {e} seconds. Please wait patiently.",
        )
        client.send_message(OWNER, f"CRITICAL INFO: {e}")
        time.sleep(e.value)
        upload_processor(client, bot_msg, url, video_paths)

    bot_msg.edit_text("Download success!✅")

    if RCLONE_PATH:
        for item in os.listdir(temp_dir.name):
            logging.info("Copying %s to %s", item, RCLONE_PATH)
            shutil.copy(os.path.join(temp_dir.name, item), RCLONE_PATH)
    temp_dir.cleanup()


def send_images(client, bot_msg, chat_id, url, image_category, image_list):
    """Function to send images for a specific category."""
    category_descriptions = {
        'topImages': 'Ảnh chính của sản phẩm',
        'baseImages': 'Ảnh chính của sản phẩm',
        'skuImages': 'Ảnh thuộc tính của sản phẩm',
        'descImages': 'Ảnh mô tả của sản phẩm',
        'rateImages': 'Ảnh đánh giá',
        'rateVideos': 'Video đánh giá'
    }
    typeImages = category_descriptions.get(image_category, image_category)
    split_lists = split_image_lists(image_list, max_images_per_list=9)
    if split_lists:
        for i, image_paths in enumerate(split_lists, start=1):
            try:
                logging.info("Sending batch %s for %s", i, image_category)
                logging.info(image_paths)
                upload_processor(client, bot_msg, url, image_paths, typeImages)
            except pyrogram.errors.Flood as e:
                logging.critical("FloodWait from Telegram: %s", e)
                time.sleep(e.value)
                upload_processor(client, bot_msg, url, image_paths, typeImages)
    else:
        logging.info("No images found for %s", image_category)


def cn_normal_download(client: Client, bot_msg: types.Message | typing.Any, url: str):
    chat_id = bot_msg.chat.id
    temp_dir = tempfile.TemporaryDirectory(prefix="cndl-", dir=TMPFILE_PATH)

    try:
        # Download video and get file paths
        downloaded_paths = sp_dl(url, temp_dir.name, bot_msg)
        logging.info("Download complete.")
        logging.info(downloaded_paths)
        if not downloaded_paths:
            bot_msg.edit_text("Không có ảnh và video phù hợp.")
            return
        # Notify user about upload progress
        client.send_chat_action(chat_id, enums.ChatAction.UPLOAD_DOCUMENT)
        mp4_paths = []
        # mp4_paths = [path for path in downloaded_paths if path.suffix.lower() == '.mp4']
        if 'video' in downloaded_paths:
                for file_info in downloaded_paths['video']:
                    if file_info['url'].endswith('.mp4'):
                        mp4_paths.append(file_info['url'])

        if 'descVideos' in downloaded_paths:
                for file_info in downloaded_paths['descVideos']:
                    if file_info['url'].endswith('.mp4'):
                        mp4_paths.append(file_info['url'])
                        
        if 'liveVideo' in downloaded_paths:
                for file_info in downloaded_paths['liveVideo']:
                    if file_info['url'].endswith('.mp4'):
                        mp4_paths.append(file_info['url'])
        bot_msg.edit_text("Đã tải xong, đang upload...")
        if mp4_paths:
            try:
                logging.info(mp4_paths)
                upload_processor(client, bot_msg, url, mp4_paths)
            except pyrogram.errors.Flood as e:
                logging.critical("FloodWait from Telegram: %s", e)
                time.sleep(e.value)
                upload_processor(client, bot_msg, url, mp4_paths)
        image_categories = ["topImages", "baseImages", "skuImages", "descImages", "rateImages", "rateVideos"]
        for category in image_categories:
            if category in downloaded_paths:
                image_list = [img_info['url'] for img_info in downloaded_paths[category]]
                logging.info(category)
                logging.info(image_list)    
                send_images(client, bot_msg, chat_id, url, category, image_list)
            else:
                logging.info("No images found for %s", category)
        if RCLONE_PATH:
            for item in os.listdir(temp_dir.name):
                logging.info("Copying %s to %s", item, RCLONE_PATH)
                shutil.copy(os.path.join(temp_dir.name, item), RCLONE_PATH)
    finally:
        bot_msg.edit_text("Đã xong tác vụ!✅")
        temp_dir.cleanup()


def generate_input_media(file_paths: list, cap: str) -> list:
    input_media = []
    for path in file_paths:
        mime = filetype.guess_mime(path)
        if "video" in mime:
            input_media.append(pyrogram.types.InputMediaVideo(media=path))
        elif "image" in mime:
            input_media.append(pyrogram.types.InputMediaPhoto(media=path))
        elif "audio" in mime:
            input_media.append(pyrogram.types.InputMediaAudio(media=path))
        else:
            input_media.append(pyrogram.types.InputMediaDocument(media=path))

    input_media[0].caption = cap
    logging.info(input_media)
    return input_media


def upload_processor(client: Client, bot_msg: types.Message, url: str, vp_or_fid: str | list, custom_cap: str = None):
    redis = Redis()
    # raise pyrogram.errors.exceptions.FloodWait(13)
    # if is str, it's a file id; else it's a list of paths
    logging.info(custom_cap)
    payment = Payment()
    chat_id = bot_msg.chat.id
    markup = gen_video_markup()
    logging.info(vp_or_fid)
    if (isinstance(vp_or_fid, list) and len(vp_or_fid) > 1) or custom_cap:
        # just generate the first for simplicity, send as media group(2-20)
        cap, meta = gen_cap(bot_msg, url, vp_or_fid[0])
        if custom_cap:
            cap = custom_cap
        res_msg: list["types.Message"] | Any = client.send_media_group(chat_id, generate_input_media(vp_or_fid, cap))
        # TODO no cache for now
        return res_msg[0]
    elif isinstance(vp_or_fid, list) and len(vp_or_fid) == 1:
        # normal download, just contains one file in video_paths
        vp_or_fid = vp_or_fid[0]
        cap, meta = gen_cap(bot_msg, url, vp_or_fid)
    else:
        # just a file id as string
        cap, meta = gen_cap(bot_msg, url, vp_or_fid)

    settings = payment.get_user_settings(chat_id)
    if ARCHIVE_ID and isinstance(vp_or_fid, pathlib.Path):
        chat_id = ARCHIVE_ID

    if settings[2] == "document":
        logging.info("Sending as document")
        try:
            # send as document could be sent as video even if it's a document
            res_msg = client.send_document(
                chat_id,
                vp_or_fid,
                caption=cap,
                progress=upload_hook,
                progress_args=(bot_msg,),
                reply_markup=markup,
                thumb=meta["thumb"],
                force_document=True,
            )
        except ValueError:
            logging.error("Retry to send as video")
            res_msg = client.send_video(
                chat_id,
                vp_or_fid,
                supports_streaming=True,
                caption=cap,
                progress=upload_hook,
                progress_args=(bot_msg,),
                reply_markup=markup,
                **meta,
            )
    elif settings[2] == "audio":
        logging.info("Sending as audio")
        res_msg = client.send_audio(
            chat_id,
            vp_or_fid,
            caption=cap,
            progress=upload_hook,
            progress_args=(bot_msg,),
        )
    else:
        # settings==video
        logging.info("Sending as video")
        try:
            res_msg = client.send_video(
                chat_id,
                vp_or_fid,
                supports_streaming=True,
                caption=cap,
                progress=upload_hook,
                progress_args=(bot_msg,),
                reply_markup=markup,
                **meta,
            )
        except Exception:
            # try to send as annimation, photo
            try:
                logging.warning("Retry to send as animation")
                res_msg = client.send_animation(
                    chat_id,
                    vp_or_fid,
                    caption=cap,
                    progress=upload_hook,
                    progress_args=(bot_msg,),
                    reply_markup=markup,
                    **meta,
                )
            except Exception:
                # this is likely a photo
                logging.warning("Retry to send as photo")
                res_msg = client.send_photo(
                    chat_id,
                    vp_or_fid,
                    caption=cap,
                    progress=upload_hook,
                    progress_args=(bot_msg,),
                )

    unique = get_unique_clink(url, bot_msg.chat.id)
    obj = res_msg.document or res_msg.video or res_msg.audio or res_msg.animation or res_msg.photo
    redis.add_send_cache(unique, getattr(obj, "file_id", None))
    redis.update_metrics("video_success")
    if ARCHIVE_ID and isinstance(vp_or_fid, pathlib.Path):
        client.forward_messages(bot_msg.chat.id, ARCHIVE_ID, res_msg.id)
    return res_msg


def gen_cap(bm, url, video_path):
    payment = Payment()
    chat_id = bm.chat.id
    user = bm.chat
    try:
        user_info = "@{}({})-{}".format(user.username or "N/A", user.first_name or "" + user.last_name or "", user.id)
    except Exception:
        user_info = ""

    if isinstance(video_path, pathlib.Path):
        meta = get_metadata(video_path)
        file_name = video_path.name
        file_size = sizeof_fmt(os.stat(video_path).st_size)
    else:
        file_name = getattr(video_path, "file_name", "")
        file_size = sizeof_fmt(getattr(video_path, "file_size", (2 << 2) + ((2 << 2) + 1) + (2 << 5)))
        meta = dict(
            width=getattr(video_path, "width", 0),
            height=getattr(video_path, "height", 0),
            duration=getattr(video_path, "duration", 0),
            thumb=getattr(video_path, "thumb", None),
        )
    free = payment.get_free_token(chat_id)
    pay = payment.get_pay_token(chat_id)
    if ENABLE_VIP:
        remain = f"Lượt tải còn lại: {free} lượt miễn phí, {pay} lượt trả phí"
    else:
        remain = ""

    if worker_name := os.getenv("WORKER_NAME"):
        worker = f"Downloaded by {worker_name}"
    else:
        worker = ""
    cap = (
        f"{user_info}\n{file_name}\n\n{url}\n\nInfo: {meta['width']}x{meta['height']} {file_size}\t"
        f"{meta['duration']}s\n{remain}\n{worker}\n{bot_text.custom_text}"
    )
    return cap, meta


# Ví dụ danh sách các đường dẫn tệp hợp  
def gen_video_markup():
    markup = types.InlineKeyboardMarkup(
        [
            [
                types.InlineKeyboardButton(  # Generates a callback query when pressed
                    "📥 Image (Taobao/Pindoudou)",
                    callback_data="getimg"
                ),
                types.InlineKeyboardButton(  # Generates a callback query when pressed
                    "🎧 Audio", callback_data="convert"
                )
            ]
        ]
    )
    return markup


@Panel.register
def ping_revision(*args):
    return get_revision()


@Panel.register
def hot_patch(*args):
    app_path = pathlib.Path().cwd().parent
    logging.info("Hot patching on path %s...", app_path)

    pip_install = "pip install -r requirements.txt"
    unset = "git config --unset http.https://github.com/.extraheader"
    pull_unshallow = "git pull origin --unshallow"
    pull = "git pull"

    subprocess.call(unset, shell=True, cwd=app_path)
    if subprocess.call(pull_unshallow, shell=True, cwd=app_path) != 0:
        logging.info("Already unshallow, pulling now...")
        subprocess.call(pull, shell=True, cwd=app_path)

    logging.info("Code is updated, applying hot patch now...")
    subprocess.call(pip_install, shell=True, cwd=app_path)
    psutil.Process().kill()


def filter_images(posix_paths, min_size_kb):
    image_paths = []
    for posix_path in posix_paths:
        filepath = str(posix_path)
        try:
            # Kiểm tra định dạng ảnh và kích thước
            if filepath.lower().endswith(('.jpeg', '.jpg', '.png')) and os.path.getsize(filepath) > min_size_kb * 1024:
                image_paths.append(filepath)
        except Exception as e:
            pass  # Bỏ qua nếu không phải là ảnh hoặc có lỗi khi đọc kích thước
    return image_paths

def split_image_lists_bk(image_paths, max_images_per_list):
    """
    Chia danh sách các đường dẫn hình ảnh thành các danh sách nhỏ hơn, mỗi danh sách có tối đa số lượng hình ảnh được chỉ định.

    Parameters:
    image_paths (list): Danh sách các đường dẫn hình ảnh.
    max_images_per_list (int): Số lượng hình ảnh tối đa trong mỗi danh sách nhỏ.

    Returns:
    list: Danh sách chứa các danh sách nhỏ hơn của các đường dẫn hình ảnh.
    """
    if not image_paths:
        print("Không có hình ảnh phù hợp.")
        return []

    if max_images_per_list <= 0:
        raise ValueError("Số lượng hình ảnh tối đa trong mỗi danh sách phải lớn hơn 0.")

    image_groups = []
    count = 0

    supported_extensions = ['.jpg', '.jpeg', '.png', '.gif']

    for path in image_paths:
        path_str = str(path)  # Chuyển đổi PosixPath thành chuỗi
        if any(path_str.lower().endswith(ext) for ext in supported_extensions):
            if count % max_images_per_list == 0:
                image_groups.append([])
            image_groups[-1].append(path)
            count += 1

    return image_groups


def split_image_lists(image_paths, max_images_per_list):
    """
    Chia danh sách các đường dẫn hình ảnh thành các danh sách nhỏ hơn, mỗi danh sách có tối đa số lượng hình ảnh được chỉ định.

    Parameters:
    image_paths (list): Danh sách các đường dẫn hình ảnh.
    max_images_per_list (int): Số lượng hình ảnh tối đa trong mỗi danh sách nhỏ.

    Returns:
    list: Danh sách chứa các danh sách nhỏ hơn của các đường dẫn hình ảnh.
    """
    if not image_paths:
        print("Không có hình ảnh phù hợp.")
        return []

    if max_images_per_list <= 0:
        raise ValueError("Số lượng hình ảnh tối đa trong mỗi danh sách phải lớn hơn 0.")

    image_groups = []
    count = 0

    supported_extensions = ['.jpg', '.jpeg', '.png', '.gif']

    for path in image_paths:
        path_str = str(path)  # Chuyển đổi PosixPath thành chuỗi
        if any(path_str.lower().endswith(ext) for ext in supported_extensions):
            if count % max_images_per_list == 0:
                image_groups.append([])
            image_groups[-1].append(path)
            count += 1

    return image_groups



def purge_tasks():
    count = app.control.purge()
    return f"purged {count} tasks."


def run_celery():
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    worker_name = os.getenv("WORKER_NAME", "")
    argv = ["-A", "tasks", "worker", "--loglevel=info", "--pool=threads", f"--concurrency={WORKERS}", "-n", worker_name]
    app.worker_main(argv)


if __name__ == "__main__":
    print("Bootstrapping Celery worker now.....")
    time.sleep(5)
    threading.Thread(target=run_celery, daemon=True).start()

    scheduler = BackgroundScheduler(timezone="Europe/London")
    scheduler.add_job(auto_restart, "interval", seconds=900)
    scheduler.start()

    idle()
    bot.stop()
