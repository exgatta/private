#!/usr/bin/env python3
"""
check_ne_safety.py - 「ne」ラベルが EZ受信/送信ボックス と重複していないか、
                     ezweb.ne.jp の中身が個人メールか調べる（読み取り専用）。
"""

import json, os, re
from collections import Counter

import google.auth.transport.requests
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

LOCAL_CREDS_PATH = os.path.expanduser("~/.gmail_local_credentials.json")


def get_service():
    d = json.load(open(LOCAL_CREDS_PATH))
    creds = Credentials(
        token=d.get("token"), refresh_token=d["refresh_token"],
        token_uri=d.get("token_uri", "https://oauth2.googleapis.com/token"),
        client_id=d["client_id"], client_secret=d["client_secret"])
    if not creds.valid:
        creds.refresh(google.auth.transport.requests.Request())
    return build("gmail", "v1", credentials=creds, cache_discovery=False)


def main():
    svc = get_service()
    labels = svc.users().labels().list(userId="me").execute().get("labels", [])
    name2id = {l["name"]: l["id"] for l in labels}
    id2name = {l["id"]: l["name"] for l in labels}

    ne_id = name2id.get("ne")
    ez_labels = [n for n in name2id if n.startswith("EZ受信ボックス") or n.startswith("EZ送信ボックス")]
    ez_ids = {name2id[n] for n in ez_labels}
    print(f"EZ系ラベル: {ez_labels}")
    print(f"neラベルID: {ne_id}\n")

    # ne の全メッセージを取得し、他に付いているラベルを集計
    msg_ids, page = [], None
    while True:
        kw = {"userId": "me", "labelIds": [ne_id], "maxResults": 500}
        if page:
            kw["pageToken"] = page
        r = svc.users().messages().list(**kw).execute()
        msg_ids.extend(m["id"] for m in r.get("messages", []))
        page = r.get("nextPageToken")
        if not page:
            break

    overlap_ez = 0
    other_labels = Counter()
    ezweb_subjects = []
    checked = 0
    for mid in msg_ids:
        md = svc.users().messages().get(
            userId="me", id=mid, format="metadata",
            metadataHeaders=["From", "Subject"]).execute()
        lids = set(md.get("labelIds", []))
        if lids & ez_ids:
            overlap_ez += 1
        for lid in lids:
            nm = id2name.get(lid, lid)
            if nm not in ("ne",) and not nm.startswith("CATEGORY_") and \
               nm not in ("INBOX", "UNREAD", "SENT", "IMPORTANT", "STARRED"):
                other_labels[nm] += 1
        hs = md.get("payload", {}).get("headers", [])
        frm = next((h["value"] for h in hs if h["name"] == "From"), "")
        subj = next((h["value"] for h in hs if h["name"] == "Subject"), "")
        if "ezweb.ne.jp" in frm.lower() and len(ezweb_subjects) < 15:
            ezweb_subjects.append(f"{frm[:30]:<32} | {subj[:40]}")
        checked += 1

    print(f"ne 総メッセージ: {len(msg_ids)}（確認 {checked}）")
    print(f"★ EZ受信/送信ボックスと重複: {overlap_ez} 件\n")
    print("ne に同時に付いている他ラベル Top15:")
    for nm, c in other_labels.most_common(15):
        print(f"  {c:>4}  {nm}")
    print("\nezweb.ne.jp 送信元のサンプル件名:")
    for s in ezweb_subjects:
        print("  ", s)


if __name__ == "__main__":
    main()
