#!/usr/bin/env python3
"""
ローカル OAuth フローで Gmail トークンを取得し、
~/.gmail_local_credentials.json に保存するヘルパースクリプト。

label_consolidation.py をローカルで実行するために使います。

使い方:
  GCP_PROJECT=gmail-manager-auto python3 get_local_token.py
"""

import json
import os
import sys

from google.cloud import secretmanager
from google_auth_oauthlib.flow import InstalledAppFlow

PROJECT_ID = os.getenv("GCP_PROJECT", "gmail-manager-auto")
SCOPES = ["https://www.googleapis.com/auth/gmail.modify"]
LOCAL_CREDS_PATH = os.path.expanduser("~/.gmail_local_credentials.json")


def main():
    print("🔑 Secret Manager から OAuth クライアント情報を取得中...")
    client = secretmanager.SecretManagerServiceClient()
    name = f"projects/{PROJECT_ID}/secrets/gmail-oauth-credentials/versions/latest"
    resp = client.access_secret_version(request={"name": name})
    d = json.loads(resp.payload.data.decode())

    client_config = {
        "installed": {
            "client_id": d["client_id"],
            "client_secret": d["client_secret"],
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": d.get("token_uri", "https://oauth2.googleapis.com/token"),
            "redirect_uris": ["urn:ietf:wg:oauth:2.0:oob", "http://localhost"],
        }
    }

    print("🌐 ブラウザで Gmail 認証を行います...")
    print("   (ブラウザが自動で開かない場合は表示される URL をコピーしてください)\n")

    flow = InstalledAppFlow.from_client_config(client_config, scopes=SCOPES)
    creds = flow.run_local_server(port=0)

    # 認証情報をローカルに保存
    creds_data = {
        "token": creds.token,
        "refresh_token": creds.refresh_token,
        "token_uri": creds.token_uri,
        "client_id": creds.client_id,
        "client_secret": creds.client_secret,
        "scopes": list(creds.scopes) if creds.scopes else SCOPES,
    }

    with open(LOCAL_CREDS_PATH, "w") as f:
        json.dump(creds_data, f, indent=2)

    print(f"\n✅ 認証完了！トークンを保存しました: {LOCAL_CREDS_PATH}")
    print("\n次のコマンドで label_consolidation.py を実行してください:")
    print(f"  USE_LOCAL=1 GCP_PROJECT={PROJECT_ID} python3 ~/gmail_function/label_consolidation.py --dry-run")


if __name__ == "__main__":
    main()
