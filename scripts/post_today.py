"""
当日分のSNS投稿をスプレッドシートから読み取り、X/FB/IGに投稿するメインスクリプト。

実行例:
  python scripts/post_today.py
  python scripts/post_today.py --date 2026-04-27
  DRY_RUN=1 python scripts/post_today.py
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
import traceback
from datetime import datetime, timezone, timedelta

# 同フォルダのモジュールをimport可能にする
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from sheets import fetch_row_for_date, update_status  # noqa: E402
from x_post import post_tweet  # noqa: E402
from facebook import post_to_facebook  # noqa: E402
from instagram import post_to_instagram  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("post_today")

JST = timezone(timedelta(hours=9))


def today_jst() -> str:
    override = os.environ.get("OVERRIDE_DATE", "").strip()
    if override:
        return override
    return datetime.now(JST).strftime("%Y-%m-%d")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", help="対象日 (YYYY-MM-DD)。省略時はJSTの今日。")
    parser.add_argument("--dry-run", action="store_true", help="API呼び出しを行わずログのみ。")
    args = parser.parse_args()

    dry_run = args.dry_run or os.environ.get("DRY_RUN", "0") == "1"
    target_date = args.date or today_jst()
    logger.info("対象日: %s / DRY_RUN=%s", target_date, dry_run)

    try:
        row = fetch_row_for_date(target_date)
    except Exception:
        logger.exception("シート読み込み失敗")
        return 1

    if row is None:
        logger.info("対象日 %s の投稿なし（行なし or status=posted）。終了。", target_date)
        return 0

    logger.info(
        "行 %d を処理。X=%d字, FB=%d字, IG=%d字, image=%s",
        row.row_index,
        len(row.x_text),
        len(row.fb_text),
        len(row.ig_caption),
        row.image_url or "(none)",
    )

    results: dict[str, str] = {}
    errors: dict[str, str] = {}

    # X投稿
    if row.x_text:
        try:
            tid = post_tweet(row.x_text, dry_run=dry_run)
            results["x"] = tid or "dry-run"
        except Exception as e:
            logger.exception("X投稿失敗")
            errors["x"] = str(e)
    else:
        logger.info("X: 本文が空のためスキップ")

    # Facebook投稿
    if row.fb_text:
        try:
            pid = post_to_facebook(row.fb_text, image_url=row.image_url, dry_run=dry_run)
            results["fb"] = pid or "dry-run"
        except Exception as e:
            logger.exception("FB投稿失敗")
            errors["fb"] = str(e)
    else:
        logger.info("FB: 本文が空のためスキップ")

    # Instagram投稿（画像URL必須）
    if row.ig_caption:
        if not row.image_url:
            logger.warning("IG: image_url が空のためスキップ")
        else:
            try:
                mid = post_to_instagram(row.ig_caption, row.image_url, dry_run=dry_run)
                results["ig"] = mid or "dry-run"
            except Exception as e:
                logger.exception("IG投稿失敗")
                errors["ig"] = str(e)
    else:
        logger.info("IG: キャプションが空のためスキップ")

    # ステータス更新
    note_parts = []
    for k, v in results.items():
        note_parts.append(f"{k}:{v}")
    for k, v in errors.items():
        note_parts.append(f"{k}_err:{v[:120]}")
    notes = " / ".join(note_parts)

    if errors and not results:
        new_status = "failed"
        rc = 1
    elif errors:
        new_status = "partial"
        rc = 1
    else:
        new_status = "posted" if not dry_run else "dry-run-ok"
        rc = 0

    if not dry_run:
        try:
            update_status(row.row_index, new_status, notes)
        except Exception:
            logger.exception("ステータス更新失敗（投稿自体は成功している可能性あり）")
            rc = max(rc, 1)
    else:
        logger.info("[DRY_RUN] ステータス更新はスキップ。仮に書くなら status=%s notes=%s", new_status, notes)

    logger.info("完了 status=%s results=%s errors=%s", new_status, results, errors)
    return rc


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        traceback.print_exc()
        sys.exit(1)
