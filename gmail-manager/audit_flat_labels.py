#!/usr/bin/env python3
"""
audit_flat_labels.py - 残りのフラット(階層なし)ラベルを精査。
ドメインだけでなく【件名＋本文プレビュー(snippet)】も必ず確認して分類する。

各フラットラベルについて:
  - 件数 (labels.get の messagesTotal)
  - サンプルメール最大3件の「送信元ドメイン / 件名 / 本文プレビュー」

使い方:
  USE_LOCAL=1 python3 -u audit_flat_labels.py
"""

import html
import json, os, re, sys, time

import google.auth.transport.requests
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

LOCAL_CREDS_PATH = os.path.expanduser("~/.gmail_local_credentials.json")
SYSTEM = {"INBOX", "SENT", "DRAFT", "SPAM", "TRASH", "UNREAD",
          "STARRED", "IMPORTANT", "CHAT"}
EZ = {"EZ受信ボックス", "EZ送信ボックス"}
SAMPLES = 3


def get_service():
    d = json.load(open(LOCAL_CREDS_PATH))
    creds = Credentials(
        token=d.get("token"), refresh_token=d["refresh_token"],
        token_uri=d.get("token_uri", "https://oauth2.googleapis.com/token"),
        client_id=d["client_id"], client_secret=d["client_secret"])
    if not creds.valid:
        creds.refresh(google.auth.transport.requests.Request())
    return build("gmail", "v1", credentials=creds, cache_discovery=False)


def retry(fn, t=4):
    for a in range(t):
        try:
            return fn()
        except Exception as e:
            if a == t-1:
                raise
            time.sleep(1.2*(a+1))


def domain_of(frm):
    m = re.search(r"[\w.\-+]+@([\w.\-]+)", frm or "")
    return m.group(1).lower() if m else "?"


def samples(svc, lid, k=SAMPLES):
    r = retry(lambda: svc.users().messages().list(
        userId="me", labelIds=[lid], maxResults=k).execute())
    out = []
    for m in r.get("messages", [])[:k]:
        md = retry(lambda: svc.users().messages().get(
            userId="me", id=m["id"], format="metadata",
            metadataHeaders=["From", "Subject"]).execute())
        hs = md.get("payload", {}).get("headers", [])
        frm = next((h["value"] for h in hs if h["name"] == "From"), "")
        subj = next((h["value"] for h in hs if h["name"] == "Subject"), "")
        snip = html.unescape(md.get("snippet", ""))
        out.append((domain_of(frm), subj, snip))
    return out


def main():
    svc = get_service()
    labels = svc.users().labels().list(userId="me").execute().get("labels", [])
    names = [l["name"] for l in labels]
    name2id = {l["name"]: l["id"] for l in labels}

    def is_parent(n):
        return any(o.startswith(n + "/") for o in names)

    flats = [n for n in names
             if "/" not in n and n not in SYSTEM and not n.startswith("CATEGORY_")
             and n not in EZ and not is_parent(n)]
    addr = sorted([n for n in flats if "@" in n])
    cat = sorted([n for n in flats if "@" not in n])
    print(f"精査対象フラット: {len(flats)} (カテゴリ化候補/個人名 {len(cat)} / アドレス名 {len(addr)})\n", flush=True)

    for i, n in enumerate(cat, 1):
        lid = name2id[n]
        total = retry(lambda: svc.users().labels().get(
            userId="me", id=lid).execute()).get("messagesTotal", "?")
        print(f"\n[{i}/{len(cat)}] 「{n}」  ({total}件)", flush=True)
        for dom, subj, snip in samples(svc, lid):
            print(f"    ◦ {dom}", flush=True)
            print(f"      件名: {subj[:60]}", flush=True)
            print(f"      本文: {snip[:90]}", flush=True)

    print(f"\n\n===== アドレス名ラベル(@含む) {len(addr)}件 =====", flush=True)
    for n in addr:
        lid = name2id[n]
        total = retry(lambda: svc.users().labels().get(
            userId="me", id=lid).execute()).get("messagesTotal", "?")
        print(f"  [{total:>4}] {n}", flush=True)


if __name__ == "__main__":
    main()
