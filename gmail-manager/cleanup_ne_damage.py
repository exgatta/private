#!/usr/bin/env python3
"""
cleanup_ne_damage.py - テスト実行のバグで ne / 通信キャリア/ne に誤移動された
                       142件を正しいラベルへ振り分け、ne系ラベルを削除する。
"""
import json, os, re, time
import google.auth.transport.requests
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

CR = os.path.expanduser("~/.gmail_local_credentials.json")
BAD_LABELS = ["ne", "通信キャリア/ne"]
# 送信元ドメイン(部分一致) → 正しい宛先
DOMAIN_MAP = [
    ("ufit.ne.jp",      "マネー・金融/クレジットカード/CFカード"),
    ("docomo",          "通信キャリア/docomo"),
    ("spmode.ne.jp",    "通信キャリア/docomo"),
    ("printing.ne.jp",  "テック・アプリ/ネットプリント"),
    ("rimnet.ne.jp",    "ショッピング/ヤフオク"),
    ("castle.ocn.ne.jp","保険/エス・ケイ・ティ"),
]
FALLBACK = "INBOX"  # 判定不能は受信トレイに戻す


def svc_():
    d = json.load(open(CR))
    c = Credentials(token=d.get("token"), refresh_token=d["refresh_token"],
        token_uri=d.get("token_uri", "https://oauth2.googleapis.com/token"),
        client_id=d["client_id"], client_secret=d["client_secret"])
    if not c.valid: c.refresh(google.auth.transport.requests.Request())
    return build("gmail", "v1", credentials=c, cache_discovery=False)


def retry(fn, t=4):
    for a in range(t):
        try: return fn()
        except Exception as e:
            if a == t-1: raise
            time.sleep(1.2*(a+1))


def dom(f):
    m = re.search(r"@([\w.\-]+)", f or ""); return m.group(1).lower() if m else "?"


def dest_for(domain):
    for key, lbl in DOMAIN_MAP:
        if key in domain:
            return lbl
    return FALLBACK


def ensure(svc, n2i, name):
    if name in n2i: return n2i[name]
    r = retry(lambda: svc.users().labels().create(userId="me", body={"name": name,
        "labelListVisibility": "labelShow", "messageListVisibility": "show"}).execute())
    n2i[name] = r["id"]; time.sleep(0.25); return r["id"]


def main():
    svc = svc_()
    n2i = {l["name"]: l["id"] for l in svc.users().labels().list(userId="me").execute().get("labels", [])}
    from collections import Counter
    moved = Counter()
    for bad in BAD_LABELS:
        lid = n2i.get(bad)
        if not lid:
            print(f"  {bad}: なし"); continue
        ids, p = [], None
        while True:
            kw = {"userId": "me", "labelIds": [lid], "maxResults": 500}
            if p: kw["pageToken"] = p
            r = retry(lambda: svc.users().messages().list(**kw).execute())
            ids += [m["id"] for m in r.get("messages", [])]; p = r.get("nextPageToken")
            if not p: break
        print(f"  {bad}: {len(ids)}件 を振り分け中...")
        for mid in ids:
            md = retry(lambda: svc.users().messages().get(userId="me", id=mid,
                format="metadata", metadataHeaders=["From"]).execute())
            hs = md.get("payload", {}).get("headers", [])
            dst = dest_for(dom(next((h["value"] for h in hs if h["name"] == "From"), "")))
            add = "INBOX" if dst == "INBOX" else ensure(svc, n2i, dst)
            retry(lambda: svc.users().messages().modify(userId="me", id=mid,
                body={"addLabelIds": [add], "removeLabelIds": [lid]}).execute())
            moved[dst] += 1
            time.sleep(0.04)
        # 空になったbadラベルを削除
        left = retry(lambda: svc.users().messages().list(userId="me", labelIds=[lid], maxResults=1).execute()).get("messages", [])
        if not left:
            retry(lambda: svc.users().labels().delete(userId="me", id=lid).execute())
            print(f"  🗑 {bad} 削除")
        else:
            print(f"  ⚠️ {bad} にまだ残あり、保持")
    print("\n=== 振り分け結果 ===")
    for d, c in moved.most_common():
        print(f"  {c:>3}  → {d}")


if __name__ == "__main__":
    main()
