#!/usr/bin/env python3
"""
enum_cone_domains.py - co / ne ラベル内の全メッセージの送信元ドメインを
                       漏れなく列挙し、件数と代表的な件名を出す。
個別振り分けの対応表を作るための調査用（読み取り専用）。

使い方:
  USE_LOCAL=1 python3 enum_cone_domains.py
"""

import json, os, re
from collections import defaultdict

import google.auth.transport.requests
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

LOCAL_CREDS_PATH = os.path.expanduser("~/.gmail_local_credentials.json")
TARGETS = ["co", "ne"]


def get_service():
    d = json.load(open(LOCAL_CREDS_PATH))
    creds = Credentials(
        token=d.get("token"), refresh_token=d["refresh_token"],
        token_uri=d.get("token_uri", "https://oauth2.googleapis.com/token"),
        client_id=d["client_id"], client_secret=d["client_secret"])
    if not creds.valid:
        creds.refresh(google.auth.transport.requests.Request())
    return build("gmail", "v1", credentials=creds, cache_discovery=False)


def domain_of(frm):
    m = re.search(r"[\w.\-+]+@([\w.\-]+)", frm or "")
    return m.group(1).lower() if m else "(不明)"


def main():
    svc = get_service()
    name2id = {l["name"]: l["id"]
               for l in svc.users().labels().list(userId="me").execute().get("labels", [])}

    for tgt in TARGETS:
        lid = name2id.get(tgt)
        if not lid:
            print(f"\n##### 「{tgt}」: ラベルなし")
            continue

        # 全メッセージID取得
        msg_ids, page = [], None
        while True:
            kw = {"userId": "me", "labelIds": [lid], "maxResults": 500}
            if page:
                kw["pageToken"] = page
            r = svc.users().messages().list(**kw).execute()
            msg_ids.extend(m["id"] for m in r.get("messages", []))
            page = r.get("nextPageToken")
            if not page:
                break

        dom_count = defaultdict(int)
        dom_subj = {}
        for mid in msg_ids:
            md = svc.users().messages().get(
                userId="me", id=mid, format="metadata",
                metadataHeaders=["From", "Subject"]).execute()
            hs = md.get("payload", {}).get("headers", [])
            frm = next((h["value"] for h in hs if h["name"] == "From"), "")
            subj = next((h["value"] for h in hs if h["name"] == "Subject"), "")
            dom = domain_of(frm)
            dom_count[dom] += 1
            dom_subj.setdefault(dom, subj)

        print(f"\n##### 「{tgt}」 合計 {len(msg_ids)} メッセージ / {len(dom_count)} ドメイン #####")
        for dom, cnt in sorted(dom_count.items(), key=lambda x: -x[1]):
            print(f"  {cnt:>3}  {dom:<32} 例: {dom_subj[dom][:42]}")


if __name__ == "__main__":
    main()
