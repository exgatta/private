#!/usr/bin/env bash
# 単体実行ファイルをビルドする (実行した OS 向けのバイナリが作られる)。
#
#   Linux   -> dist/gpmf
#   Windows -> dist\gpmf.exe        (Git Bash / WSL でなく通常のコマンドプロンプトなら build_app.bat)
#   macOS   -> dist/gpmf と dist/GPMF GoPro化ツール.app
#
# PyInstaller はクロスコンパイル不可。配布したい OS ごとに、その OS 上で実行すること。
set -euo pipefail
cd "$(dirname "$0")"

echo "==> PyInstaller を確認/インストール"
python3 -m pip install --quiet --upgrade pyinstaller

echo "==> 旧ビルドを掃除"
rm -rf build dist

echo "==> ビルド"
python3 -m PyInstaller --clean --noconfirm gpmf_tool.spec

echo ""
echo "==> 完了。生成物:"
ls -lh dist/ 2>/dev/null || true
echo ""
echo "使い方の例:"
echo "  ./dist/gpmf                              # GUI を起動"
echo "  ./dist/gpmf inject in.mp4 -o out.mp4 --gpx ride.gpx --device hero11"
echo "  ./dist/gpmf info out.mp4"
