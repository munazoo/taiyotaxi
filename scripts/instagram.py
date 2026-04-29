"""
Instagram Graph API への投稿モジュール。

仕様上、Instagram投稿には画像（または動画）が必須。
2段階フロー:
  1. メディアコンテナ作成 (POST /{ig-user-id}/media, image_url + caption)
  2. パブリッシュ (POST /{ig-user-id}/media_publish, creation_id)

image_url はインターネットから到達可能な公開URLである必要がある
（GitHub raw, S3, Cloudinaryなど）。
"""
from __future__ import annotations

import logging
import os
import time
from typing import Optional

import requests

logger = logging.getLogger(__name__)

GRAPH_API_VERSION = "v20.0"
GRAPH_BASE = f"https://graph.facebook.com/{GRAPH_API_VERSION}"

# IGキャプション上限（仕様: 2200字）
IG_CAPTION_LIMIT = 2200


def _create_container(ig_user_id: str, token: str, image_url: str, caption: str) -> str:
    url = f"{GRAPH_BASE}/{ig_user_id}/media"
    payload = {
        "image_url": image_url,
        "caption": caption[:IG_CAPTION_LIMIT],
        "access_token": token,
    }
    r = requests.post(url, data=payload, timeout=30)
    if not r.ok:
        logger.error("[IG] container create failed status=%s body=%s", r.status_code, r.text)
        r.raise_for_status()
    return r.json()["id"]


def _wait_for_finish(ig_user_id: str, token: str, container_id: str, max_wait_sec: int = 60) -> None:
    """コンテナのstatus_codeがFINISHEDになるまで待機。"""
    url = f"{GRAPH_BASE}/{container_id}"
    deadline = time.monotonic() + max_wait_sec
    while time.monotonic() < deadline:
        r = requests.get(url, params={"fields": "status_code", "access_token": token}, timeout=15)
        if r.ok:
            status = r.json().get("status_code")
            logger.debug("[IG] container status=%s", status)
            if status == "FINISHED":
                return
            if status == "ERROR":
                raise RuntimeError(f"IG container error: {r.text}")
        time.sleep(3)
    raise RuntimeError("IG container did not reach FINISHED within timeout")


def _publish(ig_user_id: str, token: str, container_id: str) -> str:
    url = f"{GRAPH_BASE}/{ig_user_id}/media_publish"
    payload = {"creation_id": container_id, "access_token": token}
    r = requests.post(url, data=payload, timeout=30)
    if not r.ok:
        logger.error("[IG] publish failed status=%s body=%s", r.status_code, r.text)
        r.raise_for_status()
    return r.json()["id"]


def post_to_instagram(caption: str, image_url: str, dry_run: bool = False) -> Optional[str]:
    """投稿に成功したら media_id を返す。画像URLがなければNone（呼び出し側でスキップ判定）。"""
    if not image_url:
        logger.info("[IG] image_url is empty, skipping")
        return None
    if not caption:
        raise ValueError("IGキャプションが空です。")

    if dry_run:
        logger.info(
            "[DRY_RUN][IG] ig_user_id=%s len=%d image=%s 先頭80字=%s",
            os.environ.get("IG_USER_ID", "(unset)"),
            len(caption),
            image_url,
            caption[:80],
        )
        return None

    ig_user_id = os.environ["IG_USER_ID"]
    token = os.environ["IG_ACCESS_TOKEN"]

    container_id = _create_container(ig_user_id, token, image_url, caption)
    logger.info("[IG] container created id=%s", container_id)
    _wait_for_finish(ig_user_id, token, container_id)
    media_id = _publish(ig_user_id, token, container_id)
    logger.info("[IG] post success media_id=%s", media_id)
    return media_id
