#!/usr/bin/env python3
"""
scan_ezweb_labels.py - 全ラベルを高速走査し、ezweb.ne.jp を含むメール
                       (from: または to:) がどのラベルに入っているか集計。
高速化: 各ラベルは1回のlist呼び出しで判定（>500件は "500+" 表示）。
進捗は逐次フラッシュ。

使い方:
  USE_LOCAL=1 python3 -u scan_ezweb_labels.py
"""

import json, os, sys

import google.auth.transport.requests
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

LOCAL_CREDS_PATH = os.path.expanduser("~/.gmail_local_credentials.json")
EZ_QUERY = "from:ezweb.ne.jp OR to:ezweb.ne.jp"
SYSTEM = {"INBOX", "SENT", "DRAFT", "SPAM", "TRASH", "UNREAD",
          "STARRED", "IMPORTANT", "CHAT"}
EZ_LABELS = {"EZ受信ボックス", "EZ受信ボックス/須藤亜紀子", "EZ送信ボックス"}


def get_service():
    d = json.load(open(LOCAL_CREDS_PATH))
    creds = Credentials(
        token=d.get("token"), refresh_token=d["refresh_token"],
        token_uri=d.get("token_uri", "https://oauth2.googleapis.com/token"),
        client_id=d["client_id"], client_secret=d["client_secret"])
    if not creds.valid:
        creds.refresh(google.auth.transport.requests.Request())
    return build("gmail", "v1", credentials=creds, cache_discovery=False)


def quick_count(svc, label_id):
    """1ページだけ取得。(件数, さらに有るか) を返す。一時エラーはリトライ。"""
    import time as _t
    for attempt in range(4):
        try:
            r = svc.users().messages().list(
                userId="me", labelIds=[label_id], q=EZ_QUERY, maxResults=500).execute()
            msgs = r.get("messages", [])
            return len(msgs), bool(r.get("nextPageToken"))
        except Exception as e:
            if attempt == 3:
                print(f"    ⚠️ count失敗(skip): {e}", flush=True)
                return 0, False
            _t.sleep(1.5 * (attempt + 1))


def count_q(svc, q):
    n, page = 0, None
    while True:
        kw = {"userId": "me", "q": q, "maxResults": 500}
        if page:
            kw["pageToken"] = page
        r = svc.users().messages().list(**kw).execute()
        n += len(r.get("messages", []))
        page = r.get("nextPageToken")
        if not page:
            break
    return n


def main():
    svc = get_service()
    labels = [(l["name"], l["id"])
              for l in svc.users().labels().list(userId="me").execute().get("labels", [])
              if not l["name"].startswith("CATEGORY_") and l["name"] not in SYSTEM]
    print(f"走査対象ラベル: {len(labels)}", flush=True)

    ez_hits, other_hits = [], []
    for i, (name, lid) in enumerate(labels, 1):
        c, more = quick_count(svc, lid)
        if c > 0:
            tag = f"{c}{'+' if more else ''}"
            if name in EZ_LABELS:
                ez_hits.append((name, c, tag))
            else:
                other_hits.append((name, c, tag))
                print(f"  ★EZ以外HIT {tag:>5}  {name}", flush=True)  # 即時出力
        if i % 100 == 0:
            print(f"  ...{i}/{len(labels)} 走査済 (EZ以外ヒット {len(other_hits)})", flush=True)

    print("\n=== EZ系ラベル内の ezweb メール ===", flush=True)
    for name, c, tag in sorted(ez_hits, key=lambda x: -x[1]):
        print(f"  {tag:>6}  {name}", flush=True)

    print(f"\n=== ★EZ以外★のラベルに入っている ezweb メール ({len(other_hits)}ラベル) ===", flush=True)
    if not other_hits:
        print("  なし", flush=True)
    for name, c, tag in sorted(other_hits, key=lambda x: -x[1]):
        print(f"  {tag:>6}  {name}", flush=True)

    print("\n=== 補足カウント ===", flush=True)
    print(f"  ezweb 総数(from OR to): {count_q(svc, EZ_QUERY)}", flush=True)
    print(f"  うち INBOX 内: {count_q(svc, EZ_QUERY + ' in:inbox')}", flush=True)
    print(f"  うち ラベル無し(アーカイブ): {count_q(svc, EZ_QUERY + ' -has:userlabels -in:inbox -in:sent -in:draft')}", flush=True)


if __name__ == "__main__":
    main()
