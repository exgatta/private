#!/usr/bin/env python3
"""
fix_missing_labels.py - Adobe/FC2/Sony の未作成ラベルを修正

問題: fix_all_labels2.py の複数回実行で Adobe/FC2/Sony のラベルが
      作成されずに source ラベルだけ削除されてしまった。

対応:
  1. テック・アプリ/Adobe, テック・アプリ/FC2, テック・アプリ/Sony を作成
  2. 各サービスのメールを Gmail 検索で抽出して再ラベリング

使い方:
  USE_LOCAL=1 python3 fix_missing_labels.py --dry-run
  USE_LOCAL=1 python3 fix_missing_labels.py
"""

import json
import os
import sys
import time

import google.auth.transport.requests
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

DRY_RUN = "--dry-run" in sys.argv
LOCAL_CREDS_PATH = os.path.expanduser("~/.gmail_local_credentials.json")

# =====================================================================
# 宛先ラベルと検索クエリの定義
# =====================================================================
REPAIRS = [
    {
        "label": "テック・アプリ/Adobe",
        "queries": [
            "from:@adobe.com",
            "from:@adobecc.com",
            "from:@adobe-email.com",
            "from:@adobecampaign.com",
            "from:@creativecloud.adobe.com",
        ],
    },
    {
        "label": "テック・アプリ/FC2",
        "queries": [
            "from:@fc2.com",
            "from:@fc2inc.com",
        ],
    },
    {
        "label": "テック・アプリ/Sony",
        "queries": [
            # sonyentertainmentnetwork は PlayStation カテゴリなので除外
            "from:@sony.com",
            "from:@sonycreativesoftware.com",
            "from:@playmemoriesonline.com",
            "from:@email.sony.com",
            "from:@mysonyclub.sony.com",
        ],
    },
]


def get_service():
    with open(LOCAL_CREDS_PATH) as f:
        d = json.load(f)
    creds = Credentials(
        token=d.get("token"),
        refresh_token=d["refresh_token"],
        token_uri=d.get("token_uri", "https://oauth2.googleapis.com/token"),
        client_id=d["client_id"],
        client_secret=d["client_secret"],
    )
    if not creds.valid:
        creds.refresh(google.auth.transport.requests.Request())
    return build("gmail", "v1", credentials=creds, cache_discovery=False)


def ensure_label(svc, name2id, name):
    if name in name2id:
        return name2id[name]
    print(f"  作成: 「{name}」")
    if DRY_RUN:
        name2id[name] = f"DRY_{name}"
        return name2id[name]
    result = svc.users().labels().create(
        userId="me",
        body={"name": name,
              "labelListVisibility": "labelShow",
              "messageListVisibility": "show"}
    ).execute()
    name2id[name] = result["id"]
    time.sleep(0.3)
    return result["id"]


def search_and_label(svc, query, label_id, label_name):
    """クエリで検索したスレッドにラベルを付ける"""
    threads = []
    page_token = None
    while True:
        kwargs = {"userId": "me", "q": query, "maxResults": 500}
        if page_token:
            kwargs["pageToken"] = page_token
        resp = svc.users().threads().list(**kwargs).execute()
        threads.extend(resp.get("threads", []))
        page_token = resp.get("nextPageToken")
        if not page_token:
            break

    if not threads:
        return 0

    print(f"    {query!r} → {len(threads)} スレッド")
    if DRY_RUN:
        return len(threads)

    ok = err = 0
    for i, t in enumerate(threads):
        try:
            svc.users().threads().modify(
                userId="me", id=t["id"],
                body={"addLabelIds": [label_id]}
            ).execute()
            ok += 1
        except Exception as e:
            print(f"      ❌ {e}")
            err += 1
        if (i + 1) % 100 == 0:
            print(f"    ... {i+1}/{len(threads)}")
        time.sleep(0.05)

    return ok


def main():
    if DRY_RUN:
        print("🔍 DRY RUN モード")
    else:
        print("🚀 本番実行モード")

    svc = get_service()
    resp = svc.users().labels().list(userId="me").execute()
    name2id = {l["name"]: l["id"] for l in resp.get("labels", [])}
    print(f"  ラベル総数: {len(name2id)}")

    for repair in REPAIRS:
        label_name = repair["label"]
        print(f"\n  ── {label_name} ──")

        label_id = ensure_label(svc, name2id, label_name)
        total = 0
        for q in repair["queries"]:
            n = search_and_label(svc, q, label_id, label_name)
            total += n

        print(f"  → 合計 {total} スレッドにラベル付与")

    print("\n✅ 完了")


if __name__ == "__main__":
    main()
