"""
Facebook Graph API へのページ投稿モジュール。

長期ページアクセストークンを利用。
画像URLが指定されていれば写真付きで投稿、なければテキストのみ。
"""
from __future__ import annotations

import logging
import os
from typing import Optional

import requests

logger = logging.getLogger(__name__)

GRAPH_API_VERSION = "v20.0"
GRAPH_BASE = f"https://graph.facebook.com/{GRAPH_API_VERSION}"


def post_to_facebook(message: str, image_url: str = "", dry_run: bool = False) -> Optional[str]:
    """投稿に成功したら post_id を返す。"""
    if not message:
        raise ValueError("投稿メッセージが空です。")

    if dry_run:
        logger.info(
            "[DRY_RUN][FB] page=%s len=%d image=%s 先頭80字=%s",
            os.environ.get("FB_PAGE_ID", "(unset)"),
            len(message),
            image_url or "(none)",
            message[:80],
        )
        return None

    page_id = os.environ["FB_PAGE_ID"]
    token = os.environ["FB_PAGE_ACCESS_TOKEN"]

    if image_url:
        # 画像付き投稿: /photos エンドポイント
        url = f"{GRAPH_BASE}/{page_id}/photos"
        payload = {
            "caption": message,
            "url": image_url,
            "access_token": token,
        }
    else:
        # テキストのみ: /feed
        url = f"{GRAPH_BASE}/{page_id}/feed"
        payload = {
            "message": message,
            "access_token": token,
        }

    r = requests.post(url, data=payload, timeout=30)
    if not r.ok:
        logger.error("[FB] post failed status=%s body=%s", r.status_code, r.text)
        r.raise_for_status()
    data = r.json()
    post_id = data.get("post_id") or data.get("id")
    logger.info("[FB] post success post_id=%s", post_id)
    return post_id
