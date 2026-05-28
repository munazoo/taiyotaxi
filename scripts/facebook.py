"""
Facebook Graph API へのページ投稿モジュール。

FB_PAGE_ACCESS_TOKEN には Meta Business Manager の System User Token を入れる前提。
System User Token は user-level なので、Page 投稿エンドポイント
(POST /{page_id}/photos, /feed) を直接叩くと `(#200) publish_actions deprecated` の
権限エラーになる。これを避けるため、投稿の直前に Page Access Token を
動的に派生取得（GET /{page_id}?fields=access_token）してから POST する。

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


def _extract_api_error(r: requests.Response) -> str:
    """Graph APIのエラーレスポンスから要点（message / code / subcode）を抽出し、
    notesに残しやすい短い文字列にして返す。"""
    try:
        err = r.json().get("error", {})
        msg = err.get("message", "unknown error")
        code = err.get("code")
        subcode = err.get("error_subcode")
    except (ValueError, AttributeError):
        return r.text[:120]
    if code is not None:
        tag = f"code={code}" + (f" subcode={subcode}" if subcode is not None else "")
        return f"{msg} [{tag}]"
    return msg


def _get_page_token(page_id: str, user_token: str) -> str:
    """System User Token から Page Access Token を派生取得する。

    System User Token は user-level token で、Page 投稿エンドポイント
    (POST /{page_id}/photos など) には Page Access Token が必要。
    System User Token を基にした Page Token は System User の権限に従い、
    取得のたびに新しい値が返るため期限切れを意識せずに使える。
    """
    url = f"{GRAPH_BASE}/{page_id}"
    params = {"fields": "access_token", "access_token": user_token}
    r = requests.get(url, params=params, timeout=15)
    if not r.ok:
        detail = _extract_api_error(r)
        logger.error("[FB] page token fetch failed status=%s body=%s", r.status_code, r.text)
        raise RuntimeError(f"FB page token fetch failed (HTTP {r.status_code}): {detail}")
    page_token = r.json().get("access_token")
    if not page_token:
        raise RuntimeError(f"FB page token not in response: {r.text[:200]}")
    return page_token


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
    user_token = os.environ["FB_PAGE_ACCESS_TOKEN"]  # 実体は System User Token

    # System User Token → Page Access Token に派生変換（Page投稿には Page Token が必要）
    page_token = _get_page_token(page_id, user_token)
    logger.info("[FB] page token acquired (length=%d)", len(page_token))

    if image_url:
        # 画像付き投稿: /photos エンドポイント
        url = f"{GRAPH_BASE}/{page_id}/photos"
        payload = {
            "caption": message,
            "url": image_url,
            "access_token": page_token,
        }
    else:
        # テキストのみ: /feed
        url = f"{GRAPH_BASE}/{page_id}/feed"
        payload = {
            "message": message,
            "access_token": page_token,
        }

    r = requests.post(url, data=payload, timeout=30)
    if not r.ok:
        detail = _extract_api_error(r)
        logger.error("[FB] post failed status=%s body=%s", r.status_code, r.text)
        raise RuntimeError(f"FB post failed (HTTP {r.status_code}): {detail}")
    data = r.json()
    post_id = data.get("post_id") or data.get("id")
    logger.info("[FB] post success post_id=%s", post_id)
    return post_id
