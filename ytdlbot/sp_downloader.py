#!/usr/local/bin/python3
# coding: utf-8

# ytdlbot - sp_downloader.py
# 3/16/24 16:32
#

__author__ = "SanujaNS <sanujas@sanuja.biz>"

import functools
import os
import json
import logging
import pathlib
import re
import traceback
from urllib.parse import urlparse, parse_qs, urljoin, unquote

from pyrogram import types
from tqdm import tqdm
import filetype
import requests
from bs4 import BeautifulSoup
import yt_dlp as ytdl

from config import (
    PREMIUM_USER,
    TG_NORMAL_MAX_SIZE,
    TG_PREMIUM_MAX_SIZE,
    FileTooBig,
    IPv6,
    API_TAOBAO,
    API_TAOBAO2,
    API_PDD
)
from downloader import (
    edit_text,
    remove_bash_color,
    ProgressBar,
    tqdm_progress,
    download_hook,
    upload_hook,
)
from limit import Payment
from utils import sizeof_fmt, parse_cookie_file, extract_code_from_instagram_url


def extract_taobao_id(url: str) -> str:
    """Extract Taobao ID from the URL."""
    match = re.search(r'id=(\d+)', url)
    if match:
        return match.group(1)
    return None

def taobao(url: str, tempdir: str, bm, **kwargs) -> dict:
    """Download media from Taobao."""
    payment = Payment()
    user_id = bm.chat.id
    taobao_id = extract_taobao_id(url)
    if not taobao_id:
        raise ValueError("Invalid Taobao link format.")
    logging.info(taobao_id)
    logging.info(API_TAOBAO)
    payload = {'id': taobao_id}
    headers = {'Content-Type': 'application/json'}
    
    try:
        response = requests.post(API_TAOBAO, headers=headers, data=json.dumps(payload))
        logging.info(f"Response from first API: {response}")
        logging.info(f"Response content: {response.content.decode('utf-8')}")
        if response.status_code != 200:
            logging.error(f"Failed to fetch image details, status code: {response.status_code}")
            raise Exception("Failed to fetch image details.")
        data = response.json()
    except Exception as e:
        logging.error(f"Error during first API request: {e}")
        raise
    
    paid_token = payment.get_pay_token(user_id)
    logging.info(paid_token)
    if paid_token > 0:
        # Second API request
        response2 = requests.post(API_TAOBAO2, headers=headers, data=json.dumps(payload))
        if response2.status_code != 200:
            raise Exception("Failed to fetch image desc.")
    
        data2 = response2.json()
        img_urls = {
            'video': data.get('video', []),
            'descVideos': data2.get('descVideos', []),
            'baseImages': data.get('baseImages', []),
            'skuImages': data.get('skuImages', []),
            'descImages': data2.get('descImages', [])
        }
    else:
        img_urls = {
            'video': data.get('video', []),
            'baseImages': data.get('baseImages', []),
        }
    logging.info(img_urls)
    
    # Clean and deduplicate URLs
    for key in img_urls:
        img_urls[key] = list(set(img['url'] for img in img_urls[key] if 'url' in img))

    video_paths = {
        'video': [],
        'descVideos': [],
        'baseImages': [],
        'skuImages': [],
        'descImages': []
    }

    headers = { 'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36' }

    for category, urls in img_urls.items():
        for idx, img_url in enumerate(urls):
            try:
                req = requests.get(img_url, headers=headers, stream=True)
            
                if req.status_code != 200:
                    logging.error(f"Lỗi khi tải về URL: {img_url} với mã trạng thái: {req.status_code}")
                    continue
            
                content_type = req.headers.get('Content-Type')
                if 'image' not in content_type and 'video' not in content_type:
                    logging.error(f"Nội dung không phải là hình ảnh hoặc video từ URL: {img_url}")
                    continue
            
                parsed_url = urlparse(img_url)
                filename = pathlib.Path(parsed_url.path).name

                save_path = pathlib.Path(tempdir, filename)
                logging.info(f"Saving file to: {save_path}")
            
                os.makedirs(tempdir, exist_ok=True)
            
                with open(save_path, "wb") as fp:
                    for chunk in req.iter_content(chunk_size=8192):
                        if chunk:
                            fp.write(chunk)
            
                if os.path.getsize(save_path) <= 10000:
                    logging.error(f"Tệp quá nhỏ hoặc không hợp lệ: {save_path}")
                    continue
        
                video_paths[category].append(save_path)
        
            except Exception as e:
                logging.error(f"Đã xảy ra lỗi khi tải về hoặc ghi tệp: {e}")

    logging.info(video_paths)
    return video_paths
    
# def taobao(url: str, tempdir: str, bm, **kwargs) -> list:
#     """Download media from Taobao."""
#     payment = Payment()
#     user_id = bm.chat.id
#     taobao_id = extract_taobao_id(url)
#     if not taobao_id:
#         raise ValueError("Invalid Taobao link format.")
#     logging.info(taobao_id)
#     logging.info(API_TAOBAO)
#     payload = {'id': taobao_id}
#     headers = {'Content-Type': 'application/json'}
    
#     try:
#         response = requests.post(API_TAOBAO, headers=headers, data=json.dumps(payload))
#         logging.info(f"Response from first API: {response}")
#         logging.info(f"Response content: {response.content.decode('utf-8')}")
#         if response.status_code != 200:
#             logging.error(f"Failed to fetch image details, status code: {response.status_code}")
#             raise Exception("Failed to fetch image details.")
#         data = response.json()
#     except Exception as e:
#         logging.error(f"Error during first API request: {e}")
#         raise
    
#     data = response.json()
#     paid_token = payment.get_pay_token(user_id)
#     logging.info(paid_token)
#     if paid_token > 0:
#         # Second API request
#         response2 = requests.post(API_TAOBAO2, headers=headers, data=json.dumps(payload))
#         if response2.status_code != 200:
#             raise Exception("Failed to fetch image desc.")
    
#         data2 = response2.json()
#         img_urls = data.get('video', []) + data2.get('descVideos', []) + data.get('baseImages', []) + data.get('skuImages', []) + data2.get('descImages', [])
#     # Extract URLs
#     else:
#         img_urls = data.get('video', []) + data.get('baseImages', [])
#     logging.info(img_urls)
#     # Clean and deduplicate URLs
#     cleaned_urls = list(set(img['url'] for img in img_urls if 'url' in img))
    
#     if not cleaned_urls:
#         raise Exception("No valid image URLs found.")
#     logging.info(cleaned_urls)
#     video_paths = []

#     # Header với User-Agent
#     headers = { 'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36' }

#     for idx, img_url in enumerate(cleaned_urls):
#         try:
#             req = requests.get(img_url, headers=headers, stream=True)
        
#             # Kiểm tra mã trạng thái HTTP
#             if req.status_code != 200:
#                 logging.error(f"Lỗi khi tải về URL: {img_url} với mã trạng thái: {req.status_code}")
#                 continue
        
#             # Kiểm tra loại nội dung 
#             content_type = req.headers.get('Content-Type')
#             if 'image' not in content_type:
#                 logging.error(f"Nội dung không phải là hình ảnh từ URL: {img_url}")
                
        
#             # Trích xuất tên tệp từ URL mà không có query parameters.
#             parsed_url = urlparse(img_url)
#             filename = pathlib.Path(parsed_url.path).name  # Chỉ lấy phần tên tệp từ đường dẫn

#             # Tạo đường dẫn lưu tệp.   
#             save_path = pathlib.Path(tempdir, filename)
#             logging.info(f"Saving image to: {save_path}")
        
#             # Tạo thư mục nếu chưa tồn tại
#             os.makedirs(tempdir, exist_ok=True)
        
#             with open(save_path, "wb") as fp:
#                 for chunk in req.iter_content(chunk_size=8192):
#                     if chunk:  # Kiểm tra nếu đoạn không rỗng
#                         fp.write(chunk)
        
#             # Kiểm tra kích thước tệp sau khi tải về
#             if os.path.getsize(save_path) <= 10000:
#                 logging.error(f"Tệp quá nhỏ hoặc không hợp lệ: {save_path}")
#                 continue
    
#             # Thêm đường dẫn tệp vào danh sách
#             video_paths.append(save_path)
    
#         except Exception as e:
#             logging.error(f"Đã xảy ra lỗi khi tải về hoặc ghi tệp: {e}")

#     logging.info(video_paths)
#     return video_paths


# def pindoudou(url: str, tempdir: str, bm, **kwargs) -> list:
#     """Download media from Pindoudou."""
#     payment = Payment()
#     user_id = bm.chat.id
#     payload = {'linksp': url}
#     headers = {'Content-Type': 'application/json'}
    
#     try:
#         response = requests.post(API_PDD, headers=headers, data=json.dumps(payload))
#         logging.info(f"Response from first API: {response}")
#         logging.info(f"Response content: {response.content.decode('utf-8')}")
#         if response.status_code != 200:
#             logging.error(f"Failed to fetch PINDOUDOU details, status code: {response.status_code}")
#             raise Exception("Failed to fetch Pindoudou details.")
#         data = response.json()
#     except Exception as e:
#         logging.error(f"Error during first API request: {e}")
#         raise
    
#     data = response.json()
#     paid_token = payment.get_pay_token(user_id)
#     logging.info(paid_token)
#     if paid_token > 0:
#     # Extract URLs
#         img_urls = data.get('topImages', []) + data.get('baseImages', []) + data.get('skuImages', []) + data.get('descImages', []) + data.get('video', []) + data.get('liveVideo', [])
#         logging.info(img_urls)
#     else:
#         img_urls = data.get('topImages', []) + data.get('baseImages', []) + data.get('video', []) + data.get('liveVideo', [])
#     # Clean and deduplicate URLs
#     cleaned_urls = list(set(img['url'] for img in img_urls if 'url' in img))
    
#     if not cleaned_urls:
#         raise Exception("No valid image URLs found.")
#     logging.info(cleaned_urls)
#     video_paths = []

#     # Header với User-Agent
#     headers = { 'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36' }

#     for idx, img_url in enumerate(cleaned_urls):
#         try:
#             req = requests.get(img_url, headers=headers, stream=True)
        
#             # Kiểm tra mã trạng thái HTTP
#             if req.status_code != 200:
#                 logging.error(f"Lỗi khi tải về URL: {img_url} với mã trạng thái: {req.status_code}")
#                 continue
        
#             # Kiểm tra loại nội dung 
#             content_type = req.headers.get('Content-Type')
#             if 'image' not in content_type:
#                 logging.error(f"Nội dung không phải là hình ảnh từ URL: {img_url}")
                
        
#             # Trích xuất tên tệp từ URL mà không có query parameters.
#             parsed_url = urlparse(img_url)
#             filename = pathlib.Path(parsed_url.path).name  # Chỉ lấy phần tên tệp từ đường dẫn

#             # Tạo đường dẫn lưu tệp.   
#             save_path = pathlib.Path(tempdir, filename)
#             logging.info(f"Saving image to: {save_path}")
        
#             # Tạo thư mục nếu chưa tồn tại
#             os.makedirs(tempdir, exist_ok=True)
        
#             with open(save_path, "wb") as fp:
#                 for chunk in req.iter_content(chunk_size=8192):
#                     if chunk:  # Kiểm tra nếu đoạn không rỗng
#                         fp.write(chunk)
        
#             # Kiểm tra kích thước tệp sau khi tải về
#             if os.path.getsize(save_path) <= 10000:
#                 logging.error(f"Tệp quá nhỏ hoặc không hợp lệ: {save_path}")
#                 continue
    
#             # Thêm đường dẫn tệp vào danh sách
#             video_paths.append(save_path)
    
#         except Exception as e:
#             logging.error(f"Đã xảy ra lỗi khi tải về hoặc ghi tệp: {e}")

#     logging.info(video_paths)
#     return video_paths

def pindoudou(url: str, tempdir: str, bm, **kwargs) -> dict:
    """Download media from Pindoudou."""
    payload = {'linksp': url}
    headers = {'Content-Type': 'application/json'}
    
    try:
        response = requests.post(API_PDD, headers=headers, data=json.dumps(payload))
        logging.info(f"Response from first API: {response}")
        logging.info(f"Response content: {response.content.decode('utf-8')}")
        if response.status_code != 200:
            logging.error(f"Failed to fetch PINDOUDOU details, status code: {response.status_code}")
            raise Exception("Failed to fetch Pindoudou details.")
        data = response.json()
    except Exception as e:
        logging.error(f"Error during first API request: {e}")
        raise
    
    # Define the keys to extract URLs from
    keys = ['topImages', 'baseImages', 'skuImages', 'descImages', 'video', 'liveVideo']
    video_paths = {key: [] for key in keys}

    # Header with User-Agent
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'}
    
    for key in keys:
        if key in data:
            for img_info in data[key]:
                img_url = img_info.get('url')
                if not img_url:
                    continue
                
                try:
                    req = requests.get(img_url, headers=headers, stream=True)
                
                    # Check HTTP status code
                    if req.status_code != 200:
                        logging.error(f"Error downloading URL: {img_url} with status code: {req.status_code}")
                        continue
                
                    # Check content type
                    content_type = req.headers.get('Content-Type')
                    if 'image' not in content_type and 'video' not in content_type:
                        logging.error(f"Content is not an image or video from URL: {img_url}")
                        continue
                
                    # Extract filename from URL without query parameters
                    parsed_url = urlparse(img_url)
                    filename = pathlib.Path(parsed_url.path).name  # Only get the file name from the path

                    # Create file path to save
                    save_path = pathlib.Path(tempdir, filename)
                    logging.info(f"Saving media to: {save_path}")
                
                    # Create directory if it doesn't exist
                    os.makedirs(tempdir, exist_ok=True)
                
                    with open(save_path, "wb") as fp:
                        for chunk in req.iter_content(chunk_size=8192):
                            if chunk:  # Check if chunk is not empty
                                fp.write(chunk)
                
                    # Check file size after download
                    if os.path.getsize(save_path) <= 10000:
                        logging.error(f"File too small or invalid: {save_path}")
                        continue
            
                    # Update img_info with the local file path
                    img_info['url'] = str(save_path)
                    video_paths[key].append(img_info)
            
                except Exception as e:
                    logging.error(f"Error downloading or writing file: {e}")

    logging.info(video_paths)
    return video_paths


def sp_dl(url: str, tempdir: str, bm, **kwargs) -> list:
    """Specific link downloader"""
    domain = urlparse(url).hostname
    if "youtube.com" in domain or "youtu.be" in domain:
        raise ValueError("ERROR: This is ytdl bot for Youtube links just send the link.")
    elif "www.instagram.com" in domain:
        return instagram(url, tempdir, bm, **kwargs)
    elif "pixeldrain.com" in domain:
        return pixeldrain(url, tempdir, bm, **kwargs)
    elif "krakenfiles.com" in domain:
        return krakenfiles(url, tempdir, bm, **kwargs)
    elif "item.taobao.com" in domain:
        return taobao(url, tempdir, bm, **kwargs)
    elif "mobile.yangkeduo.com" in domain:
        return pindoudou(url, tempdir, bm, **kwargs)
    elif any(
        x in domain
        for x in [
            "terabox.com",
            "nephobox.com",
            "4funbox.com",
            "mirrobox.com",
            "momerybox.com",
            "teraboxapp.com",
            "1024tera.com",
            "terabox.app",
            "gibibox.com",
            "goaibox.com",
        ]
    ):
        return terabox(url, tempdir, bm, **kwargs)
    else:
        raise ValueError(f"Invalid URL: No specific link function found for {url}")
    
    return []


def sp_ytdl_download(url: str, tempdir: str, bm, filename=None, **kwargs) -> list:
    payment = Payment()
    chat_id = bm.chat.id
    if filename:
        output = pathlib.Path(tempdir, filename).as_posix()
    else:
        output = pathlib.Path(tempdir, "%(title).70s.%(ext)s").as_posix()
    ydl_opts = {
        "progress_hooks": [lambda d: download_hook(d, bm)],
        "outtmpl": output,
        "restrictfilenames": False,
        "quiet": True,
        "format": None,
    }

    address = ["::", "0.0.0.0"] if IPv6 else [None]
    error = None
    video_paths = None
    for addr in address:
        ydl_opts["source_address"] = addr
        try:
            logging.info("Downloading %s", url)
            with ytdl.YoutubeDL(ydl_opts) as ydl:
                ydl.download([url])
            video_paths = list(pathlib.Path(tempdir).glob("*"))
            break
        except FileTooBig as e:
                raise e
        except Exception:
            error = traceback.format_exc()
            logging.error("Download failed for %s - %s", url)

    if not video_paths:
        raise Exception(error)

    return video_paths


def instagram(url: str, tempdir: str, bm, **kwargs):
    resp = requests.get(f"http://192.168.6.1:15000/?url={url}").json()
    code = extract_code_from_instagram_url(url)
    counter = 1
    video_paths = []
    if url_results := resp.get("data"):
        for link in url_results:
            req = requests.get(link, stream=True)
            length = int(req.headers.get("content-length"))
            content = req.content
            ext = filetype.guess_extension(content)
            filename = f"{code}_{counter}.{ext}"
            save_path = pathlib.Path(tempdir, filename)
            chunk_size = 4096
            downloaded = 0
            for chunk in req.iter_content(chunk_size):
                text = tqdm_progress(f"Downloading: {filename}", length, downloaded)
                edit_text(bm, text)
                with open(save_path, "ab") as fp:
                    fp.write(chunk)
                downloaded += len(chunk)
            video_paths.append(save_path)
            counter += 1
    return video_paths


def pixeldrain(url: str, tempdir: str, bm, **kwargs):
    user_page_url_regex = r"https://pixeldrain.com/u/(\w+)"
    match = re.match(user_page_url_regex, url)
    if match:
        url = "https://pixeldrain.com/api/file/{}?download".format(match.group(1))
        return sp_ytdl_download(url, tempdir, bm, **kwargs)
    else:
        return url


def krakenfiles(url: str, tempdir: str, bm, **kwargs):
    resp = requests.get(url)
    html = resp.content
    soup = BeautifulSoup(html, "html.parser")
    link_parts = []
    token_parts = []
    for form_tag in soup.find_all("form"):
        action = form_tag.get("action")
        if action and "krakenfiles.com" in action:
            link_parts.append(action)
        input_tag = form_tag.find("input", {"name": "token"})
        if input_tag:
            value = input_tag.get("value")
            token_parts.append(value)
    for link_part, token_part in zip(link_parts, token_parts):
        link = f"https:{link_part}"
        data = {
            "token": token_part
        }
        response = requests.post(link, data=data)
        json_data = response.json()
        url = json_data["url"]
    return sp_ytdl_download(url, tempdir, bm, **kwargs)


def find_between(s, start, end):
    return (s.split(start))[1].split(end)[0]

def terabox(url: str, tempdir: str, bm, **kwargs):
    cookies_file = os.path.join(os.path.dirname(os.path.realpath(__file__)), "terabox.txt")
    cookies = parse_cookie_file(cookies_file)
    
    headers = {
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
        "Accept-Encoding": "gzip, deflate, br",
        "Accept-Language": "en-US,en;q=0.9,hi;q=0.8",
        "Connection": "keep-alive",
        "DNT": "1",
        "Host": "www.terabox.app",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "none",
        "Sec-Fetch-User": "?1",
        "Upgrade-Insecure-Requests": "1",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
        "sec-ch-ua": "'Not A(Brand';v='99', 'Google Chrome';v='121', 'Chromium';v='121'",
        "sec-ch-ua-mobile": "?0",
        "sec-ch-ua-platform": "'Windows'",
    }
    
    session = requests.Session()
    session.headers.update(headers)
    session.cookies.update(cookies)
    temp_req = session.get(url)
    request_url = urlparse(temp_req.url)
    surl = parse_qs(request_url.query).get("surl")
    req = session.get(temp_req.url)
    respo = req.text
    js_token = find_between(respo, "fn%28%22", "%22%29")
    logid = find_between(respo, "dp-logid=", "&")
    bdstoken = find_between(respo, 'bdstoken":"', '"')
    
    params = {
        "app_id": "250528",
        "web": "1",
        "channel": "dubox",
        "clienttype": "0",
        "jsToken": js_token,
        "dp-logid": logid,
        "page": "1",
        "num": "20",
        "by": "name",
        "order": "asc",
        "site_referer": temp_req.url,
        "shorturl": surl,
        "root": "1,",
    }
    
    req2 = session.get("https://www.terabox.app/share/list", params=params)
    response_data2 = req2.json()
    file_name = response_data2["list"][0]["server_filename"]
    sizebytes = int(response_data2["list"][0]["size"])
    if sizebytes > 48 * 1024 * 1024:
        direct_link = response_data2["list"][0]["dlink"]
        url = direct_link.replace("d.terabox.app", "d3.terabox.app")
    else:
        direct_link_response = session.head(response_data2["list"][0]["dlink"])
        direct_link_response_headers = direct_link_response.headers
        direct_link = direct_link_response_headers["Location"]
        url = direct_link
    
    return sp_ytdl_download(url, tempdir, bm, filename=file_name, **kwargs)
