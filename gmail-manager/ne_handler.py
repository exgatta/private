#!/usr/bin/env python3
"""
ne_handler.py - 「ne」ラベル(.ne.jp 由来、大半が ezweb 個人メール)を
                ユーザー指示どおりに処理する。

ユーザー指示:
  - ezweb.ne.jp 由来のメール → 「EZ受信ボックス」へ入れる
  - それ以外の未分類      → 通常の受信トレイ(INBOX)へ戻す（カテゴリラベルなし）
  - 処理後 ne が空なら ne ラベル削除

実装:
  - 送信元の判定は Gmail 検索クエリでサーバ側に任せる（高速・タイムアウト回避）
  - batchModify で一括ラベル変更
  - EZ送信ボックス に既に入っているものは受信ボックス化しない（安全ガード）

使い方:
  USE_LOCAL=1 python3 ne_handler.py --dry-run
  USE_LOCAL=1 python3 ne_handler.py
"""

import json, os, sys, time

import google.auth.transport.requests
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

DRY_RUN = "--dry-run" in sys.argv
LOCAL_CREDS_PATH = os.path.expanduser("~/.gmail_local_credentials.json")

EZ_RECV = "EZ受信ボックス"
EZ_SEND = "EZ送信ボックス"


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


def list_ids(svc, q):
    ids, page = [], None
    while True:
        kw = {"userId": "me", "q": q, "maxResults": 500}
        if page:
            kw["pageToken"] = page
        r = svc.users().messages().list(**kw).execute()
        ids += [m["id"] for m in r.get("messages", [])]
        page = r.get("nextPageToken")
        if not page:
            break
    return ids


def chunks(lst, n=1000):
    for i in range(0, len(lst), n):
        yield lst[i:i + n]


def main():
    print("🔍 DRY RUN" if DRY_RUN else "🚀 本番実行", "（ne 処理）\n")
    svc = get_service()
    name2id = {l["name"]: l["id"]
               for l in svc.users().labels().list(userId="me").execute().get("labels", [])}

    ne_id = name2id.get("ne")
    if not ne_id:
        print("ne ラベルが見つかりません。終了。"); return
    ez_recv_id = name2id.get(EZ_RECV)
    if not ez_recv_id:
        print(f"❌ 「{EZ_RECV}」が見つかりません。中止。"); return

    # 1) ezweb 由来（EZ送信ボックスに入っていないもの）→ EZ受信ボックス
    ezweb_ids = list_ids(svc, f'label:ne from:ezweb.ne.jp -label:"{EZ_SEND}"')
    # 参考: EZ送信ボックスに入っている ezweb（受信ボックス化しない＝ne除去のみ）
    ezweb_in_send = list_ids(svc, f'label:ne from:ezweb.ne.jp label:"{EZ_SEND}"')
    # 2) それ以外（ezweb以外）→ INBOX、ラベルなし
    other_ids = list_ids(svc, 'label:ne -from:ezweb.ne.jp')

    print(f"ezweb由来 → 「{EZ_RECV}」へ      : {len(ezweb_ids)} 件")
    if ezweb_in_send:
        print(f"  └ うちEZ送信ボックス在籍(受信化せずne除去のみ): {len(ezweb_in_send)} 件")
    print(f"ezweb以外 → INBOX(ラベルなし)     : {len(other_ids)} 件")
    print(f"合計                              : {len(ezweb_ids)+len(ezweb_in_send)+len(other_ids)} 件")

    if DRY_RUN:
        print("\n[DRY] 変更なし。問題なければ --dry-run を外して実行。")
        return

    # 実行: ezweb → EZ受信ボックス（ne除去）
    for ch in chunks(ezweb_ids):
        svc.users().messages().batchModify(userId="me", body={
            "ids": ch, "addLabelIds": [ez_recv_id], "removeLabelIds": [ne_id]}).execute()
        print(f"  EZ受信ボックス化: {len(ch)} 件")
        time.sleep(0.3)
    # EZ送信ボックス在籍分は ne 除去のみ（受信化しない）
    for ch in chunks(ezweb_in_send):
        svc.users().messages().batchModify(userId="me", body={
            "ids": ch, "removeLabelIds": [ne_id]}).execute()
        print(f"  (送信箱在籍) ne除去のみ: {len(ch)} 件")
        time.sleep(0.3)
    # その他 → INBOX、ne除去
    for ch in chunks(other_ids):
        svc.users().messages().batchModify(userId="me", body={
            "ids": ch, "addLabelIds": ["INBOX"], "removeLabelIds": [ne_id]}).execute()
        print(f"  INBOX戻し: {len(ch)} 件")
        time.sleep(0.3)

    # ne が空なら削除
    left = svc.users().messages().list(userId="me", labelIds=[ne_id], maxResults=1).execute()
    if not left.get("messages"):
        svc.users().labels().delete(userId="me", id=ne_id).execute()
        print("\n✅ ne ラベルは空になったので削除しました。")
    else:
        n = svc.users().messages().list(userId="me", labelIds=[ne_id]).execute()
        print(f"\n⚠️ ne にまだ {len(n.get('messages', []))} 件残っています（要確認）。")
    print("✅ ne 処理完了")


if __name__ == "__main__":
    main()
