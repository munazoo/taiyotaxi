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


def _create_container(ig_user_id: str, token: str, image_url: str, caption: str) -> str:
    url = f"{GRAPH_BASE}/{ig_user_id}/media"
    payload = {
        "image_url": image_url,
        "caption": caption[:IG_CAPTION_LIMIT],
        "access_token": token,
    }
    r = requests.post(url, data=payload, timeout=30)
    if not r.ok:
        detail = _extract_api_error(r)
        logger.error("[IG] container create failed status=%s body=%s", r.status_code, r.text)
        raise RuntimeError(f"IG container create failed (HTTP {r.status_code}): {detail}")
    return r.json()["id"]


def _wait_for_finish(ig_user_id: str, token: str, container_id: str, max_wait_sec: int = 180) -> None:
    """コンテナのstatus_codeがFINISHEDになるまで待機。

    Instagramは画像URLを非同期に取得・処理するため、混雑時やraw URL応答が
    遅いと60秒では足りないことがある。デフォルト180秒まで待つ。
    環境変数 IG_CONTAINER_TIMEOUT_SEC で上書き可能。

    ポーリングが認証・権限・不正リクエスト系のエラー（HTTP 400/401/403）を
    返した場合は、リトライしても回復しないため待機を打ち切って即座に中断し、
    Graph APIのエラー内容（message / code / subcode）を添えて送出する。
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
            elif r.status_code in (400, 401, 403):
                # 認証・権限・不正リクエスト系。リトライしても回復しないため即中断。
                detail = _extract_api_error(r)
                logger.error(
                    "[IG] status poll rejected (non-retryable) status=%s body=%s",
                    r.status_code, r.text[:300],
                )
                raise RuntimeError(
                    f"IG container read denied (HTTP {r.status_code}): {detail}"
                )
            else:
                # 429・5xx 等は一時的な可能性があるためリトライを継続
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
        detail = _extract_api_error(r)
        logger.error("[IG] publish failed status=%s body=%s", r.status_code, r.text)
        raise RuntimeError(f"IG publish failed (HTTP {r.status_code}): {detail}")
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
