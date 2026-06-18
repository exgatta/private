#!/usr/bin/env python3
"""
cleanup_misc.py - ツリー整理の仕上げ

(A) 冗長な @ezweb.ne.jp フラットラベル3個を削除
    - 削除前に「EZ受信ボックス外に1件も無い」ことを再検証（安全ガード）
    - ラベル削除＝メッセージからそのタグを外すだけ。メール本体はEZ受信ボックスに残る
(B) 残骨ラベル2個を正しい場所へ移動して削除
    - Google/Google(Googleアカウント通知) → テック・アプリ/Google Account
    - 佐川急便/佐川急便株式会社(配達通知)   → 宅配・物流/佐川急便
    - 移動後、残骨ラベルと、空になったトップレベル親(Google, 佐川急便)を削除

使い方:
  USE_LOCAL=1 python3 cleanup_misc.py --dry-run
  USE_LOCAL=1 python3 cleanup_misc.py
"""

import json, os, sys, time

import google.auth.transport.requests
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

DRY_RUN = "--dry-run" in sys.argv
LOCAL_CREDS_PATH = os.path.expanduser("~/.gmail_local_credentials.json")

EZWEB_LABELS = [
    "g-himagotanjyou@ezweb.ne.jp",
    "gleam_le_el@ezweb.ne.jp",
    "peach-sparrow21@ezweb.ne.jp",
]
# 残骨ラベル: (src, dst, 空になったら消すトップ親)
ANOMALIES = [
    ("Google/Google", "テック・アプリ/Google Account", "Google"),
    ("佐川急便/佐川急便株式会社", "宅配・物流/佐川急便", "佐川急便"),
]


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


def count(svc, q):
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


def list_ids(svc, label_id):
    ids, page = [], None
    while True:
        kw = {"userId": "me", "labelIds": [label_id], "maxResults": 500}
        if page:
            kw["pageToken"] = page
        r = svc.users().messages().list(**kw).execute()
        ids += [m["id"] for m in r.get("messages", [])]
        page = r.get("nextPageToken")
        if not page:
            break
    return ids


def children_of(names, parent):
    return [n for n in names if n == parent or n.startswith(parent + "/")]


def main():
    print("🔍 DRY RUN" if DRY_RUN else "🚀 本番実行", "（仕上げクリーンアップ）\n")
    svc = get_service()
    labels = {l["name"]: l["id"]
              for l in svc.users().labels().list(userId="me").execute().get("labels", [])}

    # (A) ezweb 冗長ラベル削除
    print("── (A) 冗長 @ezweb.ne.jp ラベル削除 ──")
    for name in EZWEB_LABELS:
        if name not in labels:
            print(f"  ・無し: {name}")
            continue
        outside = count(svc, f'label:"{name}" -label:"EZ受信ボックス" '
                             f'-label:"EZ送信ボックス" -label:"EZ受信ボックス/須藤亜紀子"')
        if outside > 0:
            print(f"  ⚠️ {name}: EZ箱外に {outside} 件 → 安全のため削除スキップ")
            continue
        print(f"  {'[DRY] ' if DRY_RUN else ''}削除: {name}（全件EZ受信ボックスに残存）")
        if not DRY_RUN:
            svc.users().labels().delete(userId="me", id=labels[name]).execute()
            time.sleep(0.2)

    # (B) 残骨ラベル整理
    print("\n── (B) 残骨ラベル整理 ──")
    names_now = set(labels.keys())
    for src, dst, top in ANOMALIES:
        if src not in labels:
            print(f"  ・無し: {src}")
            continue
        if dst not in labels:
            print(f"  ⚠️ 宛先が無い: {dst} → スキップ")
            continue
        ids = list_ids(svc, labels[src])
        print(f"  {'[DRY] ' if DRY_RUN else ''}{src} → {dst}: {len(ids)}件移動 → ラベル削除")
        if not DRY_RUN:
            for mid in ids:
                svc.users().messages().modify(
                    userId="me", id=mid,
                    body={"addLabelIds": [labels[dst]], "removeLabelIds": [labels[src]]}).execute()
                time.sleep(0.05)
            svc.users().labels().delete(userId="me", id=labels[src]).execute()
            time.sleep(0.2)
        # 空になったトップ親を削除（他に子が無ければ）
        remaining_children = [c for c in children_of(names_now, top) if c != src and c != top]
        if not remaining_children and top in labels:
            top_msgs = count(svc, f'label:"{top}"')
            if top_msgs == 0:
                print(f"  {'[DRY] ' if DRY_RUN else ''}空のトップ親を削除: {top}")
                if not DRY_RUN:
                    svc.users().labels().delete(userId="me", id=labels[top]).execute()
                    time.sleep(0.2)
            else:
                print(f"  ・{top} に {top_msgs}件あるため親は保持")
        else:
            print(f"  ・{top} に他の子 {remaining_children} があるため親は保持")

    print("\n✅ DRY RUN 完了" if DRY_RUN else "\n✅ クリーンアップ完了")


if __name__ == "__main__":
    main()
