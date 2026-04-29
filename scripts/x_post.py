"""
X (Twitter) API v2 への投稿モジュール。

X Premium 契約済アカウントは最大25,000文字までの長文ポストが可能。
本スクリプトは tweepy.Client.create_tweet を経由するため、
アカウントが Premium 状態であれば 1000 文字でも自動的に通る。
"""
from __future__ import annotations

import logging
import os
from typing import Optional

import tweepy

logger = logging.getLogger(__name__)

# X 長文の上限（API側はPremiumなら25,000、運用上1000で運用したいので警告閾値）
X_LONG_LIMIT_OPERATIONAL = 1000


def post_tweet(text: str, dry_run: bool = False) -> Optional[str]:
    """投稿に成功したら tweet_id を返す。dry_run の場合は None を返す。"""
    if not text:
        raise ValueError("投稿テキストが空です。")
    if len(text) > X_LONG_LIMIT_OPERATIONAL:
        logger.warning(
            "X投稿が運用上限 %d 文字を超えています（実際: %d 文字）。投稿は試行します。",
            X_LONG_LIMIT_OPERATIONAL,
            len(text),
        )

    if dry_run:
        logger.info("[DRY_RUN][X] %d文字 / 先頭80字: %s", len(text), text[:80])
        return None

    client = tweepy.Client(
        consumer_key=os.environ["X_API_KEY"],
        consumer_secret=os.environ["X_API_SECRET"],
        access_token=os.environ["X_ACCESS_TOKEN"],
        access_token_secret=os.environ["X_ACCESS_TOKEN_SECRET"],
        bearer_token=os.environ.get("X_BEARER_TOKEN"),
    )
    resp = client.create_tweet(text=text)
    tweet_id = resp.data.get("id") if resp and resp.data else None
    logger.info("[X] 投稿成功 tweet_id=%s 文字数=%d", tweet_id, len(text))
    return tweet_id
