#!/usr/bin/env python3
"""
inspect_flat_labels.py - 指定ラベルの送信元ドメインをサンプリングして
                         単一ブランドか混在かを判定する。

使い方:
  USE_LOCAL=1 python3 inspect_flat_labels.py
"""

import base64
import json
import os
import re
import sys
from collections import Counter

import google.auth.transport.requests
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

LOCAL_CREDS_PATH = os.path.expanduser("~/.gmail_local_credentials.json")

# 判定が曖昧（汎用名 or TLD断片）なラベルだけを再確認する
AMBIGUOUS = [
    "co", "ne", "com", "go",
    "重要なお知らせメール",
    "CustomerCare",
    "apap",
    "dga",
    "mrso",
    "whitecloud",
    "tpgaw",
    "ONESTOP",
    "Raku-P",
    "aucfan",
    "jam-id",
    "yubin-info",
    "steach",
    "yoyakuru",
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


def domain_of(from_header):
    m = re.search(r"[\w.\-+]+@([\w.\-]+)", from_header or "")
    return m.group(1).lower() if m else "(不明)"


def main():
    svc = get_service()
    resp = svc.users().labels().list(userId="me").execute()
    name2id = {l["name"]: l["id"] for l in resp.get("labels", [])}

    for name in AMBIGUOUS:
        lid = name2id.get(name)
        if lid is None:
            print(f"\n── 「{name}」: ❌ ラベルが存在しない（既に処理済み？）")
            continue

        # このラベルのメッセージを最大30件サンプリング
        msgs = []
        page_token = None
        while len(msgs) < 30:
            kwargs = {"userId": "me", "labelIds": [lid], "maxResults": 30}
            if page_token:
                kwargs["pageToken"] = page_token
            r = svc.users().messages().list(**kwargs).execute()
            msgs.extend(r.get("messages", []))
            page_token = r.get("nextPageToken")
            if not page_token:
                break

        domains = Counter()
        for m in msgs[:30]:
            md = svc.users().messages().get(
                userId="me", id=m["id"], format="metadata",
                metadataHeaders=["From"]
            ).execute()
            headers = md.get("payload", {}).get("headers", [])
            frm = next((h["value"] for h in headers if h["name"] == "From"), "")
            domains[domain_of(frm)] += 1

        total = sum(domains.values())
        top = domains.most_common(6)
        verdict = "単一ブランド" if len(domains) == 1 else (
            "ほぼ単一" if top and top[0][1] / max(total, 1) >= 0.8 else "★混在★")
        print(f"\n── 「{name}」({total}件サンプル) → {verdict}")
        for dom, cnt in top:
            print(f"     {cnt:>3}  {dom}")


if __name__ == "__main__":
    main()
