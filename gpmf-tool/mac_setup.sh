#!/usr/bin/env bash
# Mac (Apple Silicon) 用アプリ GPMF-GoPro.app を 1 コマンドで取得・設置する。
# 実行後は Finder でダブルクリックするだけで起動できる (Gatekeeper 警告なし)。
#
#   使い方 (Mac のターミナルで):
#     ./mac_setup.sh            # ~/Applications に設置
#     ./mac_setup.sh /path/dir  # 設置先を指定
#
# やること:
#   1. GitHub Actions の最新成功ビルドから .app の zip を取得
#   2. 展開して指定フォルダ (既定 ~/Applications) に設置
#   3. Gatekeeper の隔離属性を除去 (未署名アプリを右クリックせず起動できる)
#
# 前提: GitHub CLI (gh) がインストール&ログイン済み。
#   brew install gh && gh auth login
set -euo pipefail

REPO="exgatta/gmail-manager"
BRANCH="claude/gpmf-parser-metadata-tool-myrzwo"
ARTIFACT="gpmf-macos-arm64"
APP_NAME="GPMF-GoPro.app"
DEST_DIR="${1:-$HOME/Applications}"

if ! command -v gh >/dev/null 2>&1; then
  echo "エラー: GitHub CLI (gh) が必要です。" >&2
  echo "  brew install gh && gh auth login" >&2
  exit 1
fi

echo "==> 最新の成功ビルドを検索 ($REPO / $BRANCH)"
RUN_ID=$(gh run list --repo "$REPO" --workflow build-app.yml --branch "$BRANCH" \
  --status success --limit 1 --json databaseId --jq '.[0].databaseId')
if [ -z "${RUN_ID:-}" ] || [ "$RUN_ID" = "null" ]; then
  echo "エラー: 成功したビルドが見つかりません。" >&2
  exit 1
fi
echo "    run id = $RUN_ID"

TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT

echo "==> アーティファクトをダウンロード"
gh run download "$RUN_ID" --repo "$REPO" --name "$ARTIFACT" --dir "$TMP"

ZIP=$(find "$TMP" -name '*.zip' | head -1)
if [ -z "${ZIP:-}" ]; then
  echo "エラー: zip が見つかりません。" >&2
  exit 1
fi

echo "==> 展開して設置: $DEST_DIR/$APP_NAME"
mkdir -p "$DEST_DIR"
rm -rf "$DEST_DIR/$APP_NAME"
# ditto でリソースフォークを保ったまま展開
ditto -x -k "$ZIP" "$TMP/unzipped"
APP_SRC=$(find "$TMP/unzipped" -maxdepth 2 -name "$APP_NAME" -type d | head -1)
if [ -z "${APP_SRC:-}" ]; then
  echo "エラー: $APP_NAME が見つかりません。" >&2
  exit 1
fi
ditto "$APP_SRC" "$DEST_DIR/$APP_NAME"

echo "==> Gatekeeper の隔離属性を除去"
xattr -dr com.apple.quarantine "$DEST_DIR/$APP_NAME" 2>/dev/null || true

echo ""
echo "==> 完了！"
echo "  Finder で $DEST_DIR/$APP_NAME をダブルクリックすれば起動します。"
echo "  (Launchpad や Spotlight で 'GPMF' でも探せます)"
echo ""
echo "CLI として使う場合:"
echo "  \"$DEST_DIR/$APP_NAME/Contents/MacOS/gpmf\" inject in.mp4 -o out.mp4 --gpx ride.gpx --device hero11"
