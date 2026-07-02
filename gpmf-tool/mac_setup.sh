#!/usr/bin/env bash
# Mac (Apple Silicon) 用 gpmf バイナリを 1 コマンドで取得・展開・実行可能化する。
#
#   使い方 (Mac のターミナルで):
#     ./mac_setup.sh
#
# やること:
#   1. GitHub Actions の最新成功ビルドから gpmf-macos-arm64 を取得
#   2. zip を展開
#   3. 実行権限を付与 (chmod +x)
#   4. Gatekeeper の隔離属性を除去 (未署名バイナリを右クリックせず起動できる)
#   5. 動作確認 (--help)
#
# 前提: GitHub CLI (gh) がインストール&ログイン済み。
#   brew install gh && gh auth login
set -euo pipefail

REPO="exgatta/gmail-manager"
BRANCH="claude/gpmf-parser-metadata-tool-myrzwo"
ARTIFACT="gpmf-macos-arm64"
DEST="${1:-./gpmf-mac}"

if ! command -v gh >/dev/null 2>&1; then
  echo "エラー: GitHub CLI (gh) が必要です。'brew install gh && gh auth login' を実行してください。" >&2
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

echo "==> アーティファクトをダウンロード & 展開"
rm -rf "$DEST"
mkdir -p "$DEST"
gh run download "$RUN_ID" --repo "$REPO" --name "$ARTIFACT" --dir "$DEST"

BIN="$DEST/$ARTIFACT"
if [ ! -f "$BIN" ]; then
  # 念のため中身を探す
  BIN=$(find "$DEST" -type f -name "$ARTIFACT" | head -1)
fi
if [ -z "${BIN:-}" ] || [ ! -f "$BIN" ]; then
  echo "エラー: バイナリが見つかりません ($DEST 内)。" >&2
  exit 1
fi

echo "==> 実行権限を付与 & 隔離属性を除去"
chmod +x "$BIN"
xattr -d com.apple.quarantine "$BIN" 2>/dev/null || true

# 分かりやすい名前にリネーム
FINAL="$DEST/gpmf"
mv -f "$BIN" "$FINAL"

echo ""
echo "==> 完了: $FINAL"
echo "==> 動作確認:"
"$FINAL" --help || true
echo ""
echo "使い方:"
echo "  $FINAL                                  # GUI を起動"
echo "  $FINAL inject in.mp4 -o out.mp4 --gpx ride.gpx --device hero11"
echo "  $FINAL info out.mp4"
