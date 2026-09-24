"""ブラウザで動く結合選択画面 (ローカル Web UI)。

Python 側は 127.0.0.1 の空きポートで小さな HTTP サーバ (JSON API + 静的
ファイル) を立て、OS 既定のブラウザでページを開く。外部 CDN やフレーム
ワークには依存せず、静的ファイルはパッケージ内 ``static/`` に同梱する。

使い方:
    python -m gpmf_tool ui [フォルダ]          … サーバを立ててブラウザを開く
    gpmf_tool.webui.server.launch_in_background()  … Tk GUI から呼ぶ
"""
