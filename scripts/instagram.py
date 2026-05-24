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


def _wait_for_finish(ig_user_id: str, token: str, container_id: str, max_wait_sec: int = 180) -> None:
    """コンテナのstatus_codeがFINISHEDになるまで待機。

    Instagramは画像URLを非同期に取得・処理するため、混雑時やraw URL応答が
    遅いと60秒では足りないことがある。デフォルト180秒まで待つ。
    環境変数 IG_CONTAINER_TIMEOUT_SEC で上書き可能。
    """
    override = os.environ.get("IG_CONTAINER_TIMEOUT_SEC", "").strip()
    if override.isdigit():
        max_wait_sec = int(override)

    url = f"{GRAPH_BASE}/{container_id}"
    deadline = time.monotonic() + max_wait_sec
    poll_interval = 5
    last_status = "UNKNOWN"
    polls = 0
    while time.monotonic() < deadline:
        try:
            r = requests.get(
                url,
                params={"fields": "status_code,status", "access_token": token},
                timeout=15,
            )
            if r.ok:
                last_status = r.json().get("status_code", "UNKNOWN")
                polls += 1
                logger.info("[IG] container status=%s (poll %d)", last_status, polls)
                if last_status == "FINISHED":
                    return
                if last_status == "ERROR":
                    raise RuntimeError(f"IG container error: {r.text}")
            else:
                logger.warning("[IG] status poll failed status=%s body=%s",
                               r.status_code, r.text[:200])
        except requests.RequestException as e:
            logger.warning("[IG] status poll request error: %s", e)
        time.sleep(poll_interval)
    raise RuntimeError(
        f"IG container did not reach FINISHED within {max_wait_sec}s "
        f"(last status: {last_status})"
    )


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
        raise ValueError("IG caption is empty.")

    if dry_run:
        logger.info(
            "[DRY_RUN][IG] ig_user_id=%s len=%d image=%s head80=%s",
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

    # publish はコンテナFINISHED直後に稀に失敗するため軽くリトライ
    last_err = None
    for attempt in range(3):
        try:
            media_id = _publish(ig_user_id, token, container_id)
            logger.info("[IG] post success media_id=%s", media_id)
            return media_id
        except Exception as e:
            last_err = e
            logger.warning("[IG] publish attempt %d failed: %s", attempt + 1, e)
            time.sleep(5)
    raise RuntimeError(f"IG publish failed after retries: {last_err}")
