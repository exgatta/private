#!/usr/bin/env python3
"""
migrate_ezweb_to_recv.py - ezweb.ne.jp メール(from: または to:)を
                            EZ受信ボックスへ集約し、空になった非EZラベルを削除。

安全ルール:
  - 追加は EZ受信ボックス のみ。
  - EZ系ラベル(EZ受信ボックス / EZ受信ボックス/須藤亜紀子 / EZ送信ボックス)は
    絶対に除去しない。除去するのは「それ以外のユーザーラベル」だけ。
  - 移動後、ユーザーラベルが完全に空(0件)になったものだけ削除。
  - システムラベル(INBOX, SENT, CATEGORY_* 等)は触らない。

使い方:
  USE_LOCAL=1 python3 -u migrate_ezweb_to_recv.py --dry-run
  USE_LOCAL=1 python3 -u migrate_ezweb_to_recv.py
"""

import json, os, sys, time

import google.auth.transport.requests
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

DRY_RUN = "--dry-run" in sys.argv
LOCAL_CREDS_PATH = os.path.expanduser("~/.gmail_local_credentials.json")
EZ_QUERY = "from:ezweb.ne.jp OR to:ezweb.ne.jp"
RECV = "EZ受信ボックス"
# 受信メールだけを対象にする。送信メール(EZ送信ボックス/送信済/下書き)と
# 須藤亜紀子ボックスは除外（送信メールは既にEZ送信ボックスにあり触らない）。
RECV_SCOPE = (f"({EZ_QUERY}) -label:\"EZ送信ボックス\" "
              f"-label:\"EZ受信ボックス/須藤亜紀子\" -in:sent -in:draft")
EZ_LABELS = {"EZ受信ボックス", "EZ受信ボックス/須藤亜紀子", "EZ送信ボックス"}
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


def retry(fn, tries=4):
    for a in range(tries):
        try:
            return fn()
        except Exception as e:
            if a == tries - 1:
                raise
            time.sleep(1.5 * (a + 1))


def ids_in(svc, label_id, q=None):
    out, page = [], None
    while True:
        kw = {"userId": "me", "labelIds": [label_id], "maxResults": 500}
        if q:
            kw["q"] = q
        if page:
            kw["pageToken"] = page
        r = retry(lambda: svc.users().messages().list(**kw).execute())
        out += [m["id"] for m in r.get("messages", [])]
        page = r.get("nextPageToken")
        if not page:
            break
    return out


def main():
    print("🔍 DRY RUN" if DRY_RUN else "🚀 本番実行", "（ezweb → EZ受信ボックス集約）\n", flush=True)
    svc = get_service()
    labels = svc.users().labels().list(userId="me").execute().get("labels", [])
    name2id = {l["name"]: l["id"] for l in labels}
    id2name = {l["id"]: l["name"] for l in labels}
    recv_id = name2id[RECV]
    ez_ids = {name2id[n] for n in EZ_LABELS if n in name2id}

    # 対象となる非EZユーザーラベルを走査
    user_labels = [(n, i) for n, i in name2id.items()
                   if n not in SYSTEM and not n.startswith("CATEGORY_") and n not in EZ_LABELS]

    print(f"非EZユーザーラベル走査: {len(user_labels)} 件", flush=True)
    affected = {}          # msg_id -> 何もしない（集合用）
    label_hits = {}        # label_name -> (ezweb件数, 総件数)
    union_ids = set()
    for k, (name, lid) in enumerate(user_labels, 1):
        ez_ids_in = retry(lambda: svc.users().messages().list(
            userId="me", labelIds=[lid], q=RECV_SCOPE, maxResults=500).execute())
        first = ez_ids_in.get("messages", [])
        if not first:
            if k % 100 == 0:
                print(f"  ...{k}/{len(user_labels)}", flush=True)
            continue
        # 受信ezweb件数（全ページ）
        ez_list = ids_in(svc, lid, RECV_SCOPE)
        total = len(ids_in(svc, lid))
        label_hits[name] = (len(ez_list), total)
        union_ids.update(ez_list)
        empties = " → 空になり削除" if len(ez_list) == total else f"（非ezweb {total-len(ez_list)}件は残る）"
        print(f"  ★ {name}: ezweb {len(ez_list)} / 全{total}{empties}", flush=True)
        if k % 100 == 0:
            print(f"  ...{k}/{len(user_labels)}", flush=True)

    will_delete = [n for n, (e, t) in label_hits.items() if e == t]
    will_keep = [n for n, (e, t) in label_hits.items() if e != t]

    print(f"\n=== サマリ ===", flush=True)
    print(f"  移動対象メール(ユニーク): {len(union_ids)} 件", flush=True)
    print(f"  影響ラベル: {len(label_hits)} 件", flush=True)
    print(f"  └ 空になり削除予定: {len(will_delete)} 件", flush=True)
    for n in sorted(will_delete):
        print(f"       🗑 {n} ({label_hits[n][0]}件)", flush=True)
    print(f"  └ 一部残り保持: {len(will_keep)} 件", flush=True)
    for n in sorted(will_keep):
        e, t = label_hits[n]
        print(f"        keep {n} (ezweb{e}/全{t} → {t-e}件残る)", flush=True)

    if DRY_RUN:
        print("\n[DRY] 変更なし。問題なければ --dry-run を外して実行。", flush=True)
        return

    # 本番: 各メールに EZ受信ボックス 追加 & 非EZユーザーラベル除去
    print(f"\n移動実行: {len(union_ids)} 件 ...", flush=True)
    done = 0
    for mid in union_ids:
        md = retry(lambda: svc.users().messages().get(
            userId="me", id=mid, format="minimal").execute())
        cur = set(md.get("labelIds", []))
        remove = [l for l in cur
                  if l in id2name                       # ユーザーラベル
                  and id2name[l] not in SYSTEM
                  and not str(l).startswith("CATEGORY_")
                  and l not in ez_ids]                  # EZ系は外さない
        body = {"addLabelIds": [recv_id]}
        if remove:
            body["removeLabelIds"] = remove
        retry(lambda: svc.users().messages().modify(userId="me", id=mid, body=body).execute())
        done += 1
        if done % 100 == 0:
            print(f"  ...{done}/{len(union_ids)}", flush=True)
        time.sleep(0.04)

    # 空になった非EZラベルを削除
    print("\n空ラベル削除:", flush=True)
    deleted = 0
    for name in will_delete:
        lid = name2id.get(name)
        if not lid:
            continue
        remain = retry(lambda: svc.users().messages().list(
            userId="me", labelIds=[lid], maxResults=1).execute()).get("messages", [])
        if remain:
            print(f"  ・{name}: まだ {len(remain)}+ 件あり保持", flush=True)
            continue
        retry(lambda: svc.users().labels().delete(userId="me", id=lid).execute())
        deleted += 1
        print(f"  🗑 削除: {name}", flush=True)
        time.sleep(0.2)

    print(f"\n✅ 完了: {done}件をEZ受信ボックスへ集約 / {deleted}ラベル削除", flush=True)


if __name__ == "__main__":
    main()
