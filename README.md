# SNS自動投稿システム（X / Facebook / Instagram）

Googleスプレッドシートで投稿カレンダーを管理し、GitHub Actionsで毎日定刻にX・Facebook・Instagramへ自動投稿するための一式です。

## 構成

```
sns-auto-post/
├── .github/workflows/sns-post.yml   # 毎日19:00 JST に実行
├── scripts/
│   ├── post_today.py                # メインエントリポイント
│   ├── sheets.py                    # Googleスプレッドシート読み書き
│   ├── x_post.py                    # X (Twitter) API v2
│   ├── facebook.py                  # Facebook Graph API
│   └── instagram.py                 # Instagram Graph API
├── templates/spreadsheet_template.csv  # Sheetsに貼り付ける雛形
├── requirements.txt
├── .env.sample                      # ローカル動作確認用
└── .gitignore
```

## スプレッドシートの作り方

1. 新しいGoogleスプレッドシートを作成し、シート名を「投稿カレンダー」にする。
2. `templates/spreadsheet_template.csv` の中身を1行目（ヘッダー）から貼り付ける。
3. 列の意味：
   - `date`: YYYY-MM-DD（JST）
   - `x_text`: Xに投稿する本文（最大1000文字目安）
   - `fb_text`: Facebookページに投稿する本文
   - `ig_caption`: Instagramのキャプション（2200字まで）
   - `image_url`: 公開画像のURL（IGは必須、FBは任意）
   - `status`: 空 or `pending` で投稿対象。投稿後に `posted` / `failed` / `partial` を自動セット
   - `notes`: 投稿結果のID等を自動記入
4. `status` 列が `posted` になった行は再投稿されない（リランしても二重投稿しない）。

## 必要なAPIキーとSecrets登録

GitHubリポジトリの **Settings → Secrets and variables → Actions** に以下を追加：

| Secret名 | 内容 |
|---|---|
| `GOOGLE_SERVICE_ACCOUNT_JSON` | サービスアカウントJSONを **そのまま全文貼り付け** |
| `SHEET_ID` | スプレッドシートURLの `/d/` と `/edit` の間のID |
| `SHEET_NAME` | シート名（例：`投稿カレンダー`） |
| `X_API_KEY` | X Developer Portal → Keys |
| `X_API_SECRET` | 同上 |
| `X_ACCESS_TOKEN` | 同上 |
| `X_ACCESS_TOKEN_SECRET` | 同上 |
| `X_BEARER_TOKEN` | 同上（任意） |
| `FB_PAGE_ACCESS_TOKEN` | 長期ページアクセストークン |
| `FB_PAGE_ID` | FacebookページのID |
| `IG_USER_ID` | Instagramビジネスアカウント ID |
| `IG_ACCESS_TOKEN` | IG投稿用トークン（FBと同一トークンで可） |

### Googleサービスアカウントの準備

1. Google Cloud Console で新規プロジェクト作成 → APIs & Services から **Google Sheets API** と **Google Drive API** を有効化。
2. IAM & Admin → Service Accounts でサービスアカウント作成 → Keys → Add Key → JSON でダウンロード。
3. ダウンロードしたJSONの `client_email`（例: `xxx@yyy.iam.gserviceaccount.com`）を、対象スプレッドシートに **編集者として共有**。
4. JSONの中身を丸ごと `GOOGLE_SERVICE_ACCOUNT_JSON` シークレットに登録（改行込みでもOK）。

## 投稿スケジュール

`.github/workflows/sns-post.yml` の `cron` は **UTC** 指定。

| やりたいこと | cron |
|---|---|
| 毎日 JST 19:00 | `0 10 * * *` （現状の設定） |
| 毎日 JST 12:00 | `0 3 * * *` |
| 毎日 JST 21:00 | `0 12 * * *` |
| 平日のみ JST 19:00 | `0 10 * * 1-5` |

複数枠で投稿したい場合は `schedule:` 配列に複数行追加：

```yaml
schedule:
  - cron: "0 3 * * *"   # JST 12:00
  - cron: "0 10 * * *"  # JST 19:00
```

## 手動実行

GitHubの **Actions タブ → SNS Daily Auto Post → Run workflow** から、対象日とDRY_RUNを指定して任意のタイミングで実行可。

## ローカル動作確認

```bash
cd sns-auto-post
python -m venv .venv
source .venv/bin/activate     # Windowsは .venv\Scripts\activate
pip install -r requirements.txt
cp .env.sample .env
# .env を編集して各値を入力
export $(grep -v '^#' .env | xargs)   # Windowsは別途方法あり
DRY_RUN=1 python scripts/post_today.py --date 2026-04-27
```

DRY_RUNモードはAPIを叩かず、各プラットフォームに何を送ろうとしたかをログ出力するだけ。本番投入前の確認に使う。

## Instagram投稿の前提

- IGはテキストのみ投稿不可。**`image_url` 列に公開画像URLが必須**。
- 推奨：別途のpublicリポジトリ（または同リポ内 `images/` 配下）に画像を置き、`https://raw.githubusercontent.com/<user>/<repo>/main/images/YYYY-MM-DD.jpg` の形でURLを指定。
- アスペクト比は 1:1（1080×1080）か 4:5（1080×1350）が安全。

## X長文（〜1000字）について

- X Premium 契約済アカウントは、API v2 `create_tweet` で最大25,000文字まで投稿可能。
- `x_post.py` は1000字超の場合に警告ログを出すだけで、投稿自体は試行する。運用上限の閾値はコード内 `X_LONG_LIMIT_OPERATIONAL` で変更可能。

## 失敗時の挙動

- いずれかのプラットフォームで失敗 → status `partial`、notesに `<platform>_err:メッセージ` が記録され、ジョブはfail（赤くなる）。
- 全失敗 → status `failed`。
- 該当日の行が無い／既に `posted` の場合 → 何もせず正常終了。

## 拡張アイデア

- 投稿成功/失敗をSlackに通知するステップを追加（`slackapi/slack-github-action`）。
- 画像を毎日Claudeで生成して `images/` にコミットする別ワークフロー。
- A/Bテスト：同じ日の行を2つ用意してランダム選択。
