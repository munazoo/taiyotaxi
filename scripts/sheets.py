"""
Google Sheetsの読み書きモジュール。

スプレッドシートの想定列構成（1行目は見出し）:
| date | x_text | fb_text | ig_caption | image_url | status | notes |
| 2026-04-27 | ... | ... | ... | https://... | pending | ... |

- date は YYYY-MM-DD（JST想定）
- status は空 or pending → 投稿対象。posted/skipped は対象外。
- image_url は IG 投稿に必須。空なら IG はスキップ。
- x_text / fb_text / ig_caption は空ならそのプラットフォームをスキップ。
"""
from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from typing import Optional

import gspread
from google.oauth2.service_account import Credentials

logger = logging.getLogger(__name__)

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive.readonly",
]

# 列名（ヘッダーと一致させる）
COL_DATE = "date"
COL_X = "x_text"
COL_FB = "fb_text"
COL_IG = "ig_caption"
COL_IMAGE = "image_url"
COL_STATUS = "status"
COL_NOTES = "notes"


@dataclass
class PostRow:
    row_index: int  # 1-indexed (ヘッダーが1行目なので実データは2以降)
    date: str
    x_text: str
    fb_text: str
    ig_caption: str
    image_url: str
    status: str
    notes: str


def _client() -> gspread.Client:
    raw = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON", "")
    if not raw:
        raise RuntimeError("GOOGLE_SERVICE_ACCOUNT_JSON が未設定です。")
    info = json.loads(raw)
    creds = Credentials.from_service_account_info(info, scopes=SCOPES)
    return gspread.authorize(creds)


def _open_worksheet() -> gspread.Worksheet:
    sheet_id = os.environ["SHEET_ID"]
    sheet_name = os.environ.get("SHEET_NAME", "投稿カレンダー")
    gc = _client()
    sh = gc.open_by_key(sheet_id)
    try:
        return sh.worksheet(sheet_name)
    except gspread.WorksheetNotFound as e:
        raise RuntimeError(f"シート '{sheet_name}' が見つかりません。") from e


def fetch_row_for_date(date_str: str) -> Optional[PostRow]:
    """指定日付の行を取得。なければNone。statusがposted/skippedなら除外。"""
    ws = _open_worksheet()
    records = ws.get_all_records()  # 1行目をヘッダーとして辞書化
    for idx, rec in enumerate(records, start=2):  # データ行は2行目から
        # date列が日付オブジェクトでなく文字列で来ることを期待
        d = str(rec.get(COL_DATE, "")).strip()
        if d != date_str:
            continue
        status = str(rec.get(COL_STATUS, "")).strip().lower()
        if status in {"posted", "skipped", "skip", "done"}:
            logger.info("行 %d はステータス %s のためスキップ", idx, status)
            return None
        return PostRow(
            row_index=idx,
            date=d,
            x_text=str(rec.get(COL_X, "")).strip(),
            fb_text=str(rec.get(COL_FB, "")).strip(),
            ig_caption=str(rec.get(COL_IG, "")).strip(),
            image_url=str(rec.get(COL_IMAGE, "")).strip(),
            status=status,
            notes=str(rec.get(COL_NOTES, "")).strip(),
        )
    return None


def update_status(row_index: int, status: str, notes: str = "") -> None:
    """status / notes 列を更新。"""
    ws = _open_worksheet()
    headers = ws.row_values(1)
    try:
        status_col = headers.index(COL_STATUS) + 1
        notes_col = headers.index(COL_NOTES) + 1
    except ValueError as e:
        raise RuntimeError(
            f"ヘッダーに {COL_STATUS} または {COL_NOTES} 列が見つかりません。"
        ) from e
    ws.update_cell(row_index, status_col, status)
    if notes:
        ws.update_cell(row_index, notes_col, notes)
