
import requests
import json
import time
import os
import logging

from config import WECHAT_APPID, WECHAT_APPSECRET

logger = logging.getLogger(__name__)

_TOKEN_CACHE = {"token": None, "expires_at": 0}


def get_access_token() -> str:
    now = time.time()
    if _TOKEN_CACHE["token"] and now < _TOKEN_CACHE["expires_at"]:
        return _TOKEN_CACHE["token"]

    url = (
        "https://api.weixin.qq.com/cgi-bin/token"
        f"?grant_type=client_credential&appid={WECHAT_APPID}&secret={WECHAT_APPSECRET}"
    )

    try:
        resp = requests.get(url, timeout=10)
        resp.raise_for_status()
        data = resp.json()

        if "access_token" in data:
            _TOKEN_CACHE["token"] = data["access_token"]
            _TOKEN_CACHE["expires_at"] = now + data.get("expires_in", 7200) - 300
            logger.info("access_token获取成功")
            return data["access_token"]
        else:
            raise Exception(f"获取access_token失败: {data}")
    except Exception as e:
        logger.error(f"获取access_token异常: {str(e)}")
        raise


def upload_permanent_image(access_token: str, file_path: str) -> str:
    url = f"https://api.weixin.qq.com/cgi-bin/material/add_material?access_token={access_token}&type=image"

    if not os.path.isfile(file_path):
        raise FileNotFoundError(f"图片文件不存在: {file_path}")

    with open(file_path, "rb") as f:
        files = {"media": (os.path.basename(file_path), f)}
        resp = requests.post(url, files=files, timeout=30)

    data = resp.json()

    if "media_id" in data:
        logger.info(f"永久图片上传成功: media_id={data['media_id']}")
        return data["media_id"]
    else:
        raise Exception(f"上传永久图片失败: {data}")


def upload_content_image(access_token: str, file_path: str) -> str:
    url = f"https://api.weixin.qq.com/cgi-bin/media/uploadimg?access_token={access_token}"

    if not os.path.isfile(file_path):
        raise FileNotFoundError(f"图片文件不存在: {file_path}")

    with open(file_path, "rb") as f:
        files = {"media": (os.path.basename(file_path), f)}
        resp = requests.post(url, files=files, timeout=30)

    data = resp.json()

    if "url" in data:
        logger.info(f"正文图片上传成功: {data['url']}")
        return data["url"]
    else:
        raise Exception(f"上传正文图片失败: {data}")


def create_draft(
    access_token: str,
    title: str,
    content: str,
    thumb_media_id: str,
    author: str = "",
    digest: str = "",
    content_source_url: str = "",
    show_cover_pic: int = 0,
    need_open_comment: int = 1,
    only_fans_can_comment: int = 0
) -> dict:
    url = f"https://api.weixin.qq.com/cgi-bin/draft/add?access_token={access_token}"

    payload = {
        "articles": [
            {
                "title": title,
                "thumb_media_id": thumb_media_id,
                "author": author,
                "digest": digest[:120] if digest else "",
                "show_cover_pic": show_cover_pic,
                "content": content,
                "content_source_url": content_source_url,
                "need_open_comment": need_open_comment,
                "only_fans_can_comment": only_fans_can_comment
            }
        ]
    }

    headers = {"Content-Type": "application/json"}

    resp = requests.post(
        url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers=headers,
        timeout=30
    )

    data = resp.json()

    if "media_id" in data:
        logger.info(f"草稿创建成功: media_id={data['media_id']}")
        return {"success": True, "media_id": data["media_id"]}
    else:
        logger.error(f"草稿创建失败: {data}")
        return {"success": False, "error": data}
