#!/usr/bin/env python3
# coding: utf-8

# ytdlbot - premium.py
# 2023-12-20  17:53

import json
import logging
import pathlib
import tempfile
from unittest.mock import MagicMock

import yt_dlp
from pyrogram import Client, filters, types

from config import APP_HASH, APP_ID, PYRO_WORKERS, TOKEN
from limit import Payment
from utils import apply_log_formatter

apply_log_formatter()
app = Client("premium", APP_ID, APP_HASH, workers=PYRO_WORKERS)

BOT_ID = int(TOKEN.split(":")[0])


def download_hook(d: dict):
    downloaded = d.get("downloaded_bytes", 0)
    total = d.get("total_bytes") or d.get("total_bytes_estimate", 0)
    print(downloaded, total)


@app.on_message(filters.user(BOT_ID) & filters.incoming)
async def hello(client: Client, message: types.Message):
    text = message.text
    try:
        data = json.loads(text)
    except json.decoder.JSONDecodeError:
        return
    url = data["url"]
    user_id = data["user_id"]

    tempdir = tempfile.TemporaryDirectory(prefix="ytdl-")
    output = pathlib.Path(tempdir.name, "%(title).70s.%(ext)s").as_posix()
    ydl_opts = {"restrictfilenames": False, "quiet": True, "outtmpl": output, "progress_hooks": [download_hook]}
    formats = [
        # webm , vp9 and av01 are not streamable on telegram, so we'll extract only mp4
        "bestvideo[ext=mp4][vcodec!*=av01][vcodec!*=vp09]+bestaudio[ext=m4a]/bestvideo+bestaudio",
        "bestvideo[vcodec^=avc]+bestaudio[acodec^=mp4a]/best[vcodec^=avc]/best",
        None,
    ]

    for f in formats:
        ydl_opts["format"] = f
        logging.info("Downloading BIG FILE for %s with format %s", url, f)
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([url])
            break
        except Exception as e:
            logging.error("Download failed for %s: %s", url, e)

    payment = Payment()
    settings = payment.get_user_settings(user_id)
    video_path = next(pathlib.Path(tempdir.name).glob("*"))
    logging.info("filesize: %s", video_path.stat().st_size)
    if settings[2] == "video" or isinstance(settings[2], MagicMock):
        logging.info("Sending as video")
        await client.send_video(
            BOT_ID,
            video_path.as_posix(),
            caption="Powered by ytdlbot",
            supports_streaming=True,
            file_name=f"{user_id}.mp4",
        )
    elif settings[2] == "audio":
        logging.info("Sending as audio")
        await client.send_audio(
            BOT_ID,
            video_path.as_posix(),
            caption="Powered by ytdlbot ",
            file_name=f"{user_id}.mp3",
        )
    elif settings[2] == "document":
        logging.info("Sending as document")
        await client.send_document(
            BOT_ID,
            video_path.as_posix(),
            caption="Powered by ytdlbot",
            file_name=f"{user_id}.mp4",
        )
    else:
        logging.error("Send type is not video or audio")

    tempdir.cleanup()


if __name__ == "__main__":
    app.run()
