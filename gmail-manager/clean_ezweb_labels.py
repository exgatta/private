#!/usr/bin/env python3
"""
clean_ezweb_labels.py - ezweb メールから「非EZラベルの重複」を剥がす。

方針:
  - ezweb メール(from: または to:)で、既に EZ送信ボックス or EZ受信ボックス に
    入っているものは、その箱はそのままにして、付いている非EZユーザーラベルだけ除去。
    → 送信メールは送信ボックス、受信メールは受信ボックスに、それぞれ「だけ」残る。
  - 須藤亜紀子ボックス / 下書き / どのEZ箱にも無いものは触らない。
  - batchModify(1000件一括)で高速処理。
  - 処理後、空(0件)になった非EZラベルを削除。

対象ラベルは前回の完全スキャンで判明した「ezwebメールを含む非EZラベル」35個。

使い方:
  USE_LOCAL=1 python3 -u clean_ezweb_labels.py --dry-run
  USE_LOCAL=1 python3 -u clean_ezweb_labels.py
"""

import json, os, sys, time

import google.auth.transport.requests
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

DRY_RUN = "--dry-run" in sys.argv
LOCAL_CREDS_PATH = os.path.expanduser("~/.gmail_local_credentials.json")
EZ_QUERY = "from:ezweb.ne.jp OR to:ezweb.ne.jp"
# EZ送信/受信/須藤亜紀子 のいずれかの箱に入っている ezweb メールが対象（下書きは除外）
# 須藤亜紀子ラベル自体は EZ系なので除去しない（重複の非EZラベルだけ剥がす）
BOXED = (f'({EZ_QUERY}) (label:"EZ送信ボックス" OR label:"EZ受信ボックス" '
         f'OR label:"EZ受信ボックス/須藤亜紀子") -in:draft')
SENT_Q = f'({EZ_QUERY}) label:"EZ送信ボックス" -in:draft'
RECV_Q = (f'({EZ_QUERY}) (label:"EZ受信ボックス" OR label:"EZ受信ボックス/須藤亜紀子") '
          f'-in:draft')

# 前回スキャンで判明: ezweb メールを含む非EZラベル
CANDIDATES = [
    "impulse-blue@auone.jp", "通信キャリア/au", "渋谷 携帯",
    "エンタメ配信/動画配信/niconico", "重要なお知らせメール", "旅行/予約/じゃらん",
    "info@aumypage.jp", "村野瑞葉", "片岡秀一郎", "タシロ", "chacaz",
    "Kataoka hideaki", "秀一郎片岡", "須藤 亜紀子", "通知",
    "転職/リクルートエージェント求人紹介", "片岡 秀一郎", "杉田 淳一", "岸 尚平",
    "テック・アプリ/Gmail チーム", "ショッピングニュース", "お知らせ",
    "stopsandglass@i.softbank.jp", "sendonly@docockin.net", "ozzio", "mdj",
    "info-lrxpfdsfsznmq@bornrich.org", "eznavi", "auto@connect.auone.jp", "ama",
    "Webメール利用登録", "SNS/mixi", "Hideaki Kataoka(sato)", "77777mbga", "4dusjc",
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


def count_in(svc, label_id, q=None):
    return len(ids_in(svc, label_id, q))


def main():
    print("🔍 DRY RUN" if DRY_RUN else "🚀 本番実行",
          "（ezweb重複ラベル剥がし）\n", flush=True)
    svc = get_service()
    name2id = {l["name"]: l["id"]
               for l in svc.users().labels().list(userId="me").execute().get("labels", [])}

    plan = []        # (name, boxed_ids, sent, recv, total)
    grand_sent = grand_recv = 0
    for name in CANDIDATES:
        lid = name2id.get(name)
        if not lid:
            continue
        boxed = ids_in(svc, lid, BOXED)
        if not boxed:
            continue
        sent = count_in(svc, lid, SENT_Q)
        recv = count_in(svc, lid, RECV_Q)
        total = count_in(svc, lid)
        plan.append((name, boxed, sent, recv, total))
        grand_sent += sent
        grand_recv += recv
        empties = "→ 空削除" if len(boxed) == total else f"(他{total-len(boxed)}件残す)"
        print(f"  {name}: 送信{sent}/受信{recv} = 箱内{len(boxed)} / 全{total} {empties}", flush=True)

    will_delete = [p[0] for p in plan if len(p[1]) == p[4]]
    uniq = len({m for p in plan for m in p[1]})
    print(f"\n=== サマリ ===", flush=True)
    print(f"  重複ラベルを剥がすezwebメール(ユニーク): {uniq} 件", flush=True)
    print(f"    送信ボックス内: {grand_sent} 件（送信ボックスに残す）", flush=True)
    print(f"    受信ボックス内: {grand_recv} 件（受信ボックスに残す）", flush=True)
    print(f"  空になり削除する非EZラベル: {len(will_delete)} 件", flush=True)
    for n in sorted(will_delete):
        print(f"      🗑 {n}", flush=True)
    keep = [p[0] for p in plan if len(p[1]) != p[4]]
    print(f"  非ezwebが残り保持する非EZラベル: {len(keep)} 件", flush=True)
    for p in plan:
        if p[0] in keep:
            print(f"      keep {p[0]} (箱内{len(p[1])}剥がす / 他{p[4]-len(p[1])}件残る)", flush=True)

    if DRY_RUN:
        print("\n[DRY] 変更なし。問題なければ --dry-run を外して実行。", flush=True)
        return

    # 本番: batchModify で非EZラベルを一括除去
    print("\n剥がし実行...", flush=True)
    for name, boxed, *_ in plan:
        lid = name2id[name]
        for i in range(0, len(boxed), 1000):
            chunk = boxed[i:i+1000]
            retry(lambda: svc.users().messages().batchModify(
                userId="me", body={"ids": chunk, "removeLabelIds": [lid]}).execute())
            print(f"  {name}: {min(i+1000, len(boxed))}/{len(boxed)} 剥がし", flush=True)
            time.sleep(0.1)

    # 空になった非EZラベルを削除
    print("\n空ラベル削除...", flush=True)
    deleted = 0
    for name in will_delete:
        lid = name2id.get(name)
        if not lid:
            continue
        remain = retry(lambda: svc.users().messages().list(
            userId="me", labelIds=[lid], maxResults=1).execute()).get("messages", [])
        if remain:
            print(f"  ・{name}: まだ残っているため保持", flush=True)
            continue
        retry(lambda: svc.users().labels().delete(userId="me", id=lid).execute())
        deleted += 1
        print(f"  🗑 {name}", flush=True)
        time.sleep(0.2)

    print(f"\n✅ 完了: {uniq}件の重複ラベルを除去 / {deleted}ラベル削除", flush=True)


if __name__ == "__main__":
    main()
