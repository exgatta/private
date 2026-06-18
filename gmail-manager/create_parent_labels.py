#!/usr/bin/env python3
"""
create_parent_labels.py - 入れ子ラベルの「欠けている親ラベル」を
                          単独ラベルとして作成し、ツリー表示を修復する。

- "A/B/C" があるのに "A" や "A/B" が単独ラベルとして無いと、
  Gmail サイドバーのツリーが暗黙の親になり畳めない/崩れて見える。
- メールの移動・ラベル削除は一切しない（純粋な作成のみ）。
- EZ受信ボックス等は既に単独で存在するので対象外。

使い方:
  USE_LOCAL=1 python3 create_parent_labels.py --dry-run
  USE_LOCAL=1 python3 create_parent_labels.py
"""

import json, os, sys, time

import google.auth.transport.requests
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

DRY_RUN = "--dry-run" in sys.argv
LOCAL_CREDS_PATH = os.path.expanduser("~/.gmail_local_credentials.json")
SYSTEM = {"INBOX", "SENT", "DRAFT", "SPAM", "TRASH", "UNREAD",
          "STARRED", "IMPORTANT", "CHAT"}


def get_service():
    if os.getenv("USE_LOCAL", "0") != "1":
        print("❌ USE_LOCAL=1 が必要です。"); sys.exit(1)
    d = json.load(open(LOCAL_CREDS_PATH))
    creds = Credentials(
        token=d.get("token"), refresh_token=d["refresh_token"],
        token_uri=d.get("token_uri", "https://oauth2.googleapis.com/token"),
        client_id=d["client_id"], client_secret=d["client_secret"])
    if not creds.valid:
        creds.refresh(google.auth.transport.requests.Request())
    return build("gmail", "v1", credentials=creds, cache_discovery=False)


def main():
    print("🔍 DRY RUN" if DRY_RUN else "🚀 本番実行", "（欠けた親ラベル作成）\n")
    svc = get_service()
    names = [l["name"] for l in svc.users().labels().list(userId="me").execute().get("labels", [])
             if not l["name"].startswith("CATEGORY_") and l["name"] not in SYSTEM]
    nameset = set(names)

    missing = set()
    for n in names:
        parts = n.split("/")
        for i in range(1, len(parts)):
            anc = "/".join(parts[:i])
            if anc not in nameset:
                missing.add(anc)

    # 浅い階層から作る（親→子の順）
    ordered = sorted(missing, key=lambda x: (x.count("/"), x))
    print(f"作成対象: {len(ordered)} 件")
    for m in ordered:
        print(f"  + {m}")

    if DRY_RUN:
        print("\n[DRY] 変更なし。問題なければ --dry-run を外して実行。")
        return

    created = 0
    for name in ordered:
        try:
            svc.users().labels().create(
                userId="me",
                body={"name": name, "labelListVisibility": "labelShow",
                      "messageListVisibility": "show"}).execute()
            created += 1
            print(f"  ✅ {name}")
            time.sleep(0.2)
        except Exception as e:
            if "409" in str(e):
                print(f"  ・既存: {name}")
            else:
                print(f"  ❌ {name}: {e}")
    print(f"\n✅ 完了: {created} 件の親ラベルを作成しました。")


if __name__ == "__main__":
    main()
