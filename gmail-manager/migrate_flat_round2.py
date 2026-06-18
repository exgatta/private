#!/usr/bin/env python3
"""
migrate_flat_round2.py - フラット精査ラウンド2。
前回見落とした「カテゴリ化できるもの」＋ co/gmail の中身別振り分け。

  - CLUSTER_MERGES: (宛先,[統合元]) スレッド移動→統合元ラベル削除
  - co: メッセージ単位で送信元ドメイン→宛先
  - gmail: 件名で振り分け（U-NEXT / それ以外=ISP）
EZ系・個人/家族・不明ラベルは対象外。

USE_LOCAL=1 python3 -u migrate_flat_round2.py --dry-run
USE_LOCAL=1 python3 -u migrate_flat_round2.py
"""
import json, os, re, sys, time
import google.auth.transport.requests
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

DRY = "--dry-run" in sys.argv
CR = os.path.expanduser("~/.gmail_local_credentials.json")
EXCL = ("EZ受信ボックス", "EZ送信ボックス")

CLUSTER_MERGES = [
    ("ショッピング/ファッション/L.L.Bean", ["L.L.Beanカスタマーサービスセンター"]),
    ("ヘルス・美容/フィットネス/メガロス", ["SS再送"]),
    ("子育て/メガロスアフタースクール", ["相模大野問合せ"]),
    ("エンタメ配信/GEO", ["geo-reply"]),
    ("ヘルス・美容/美容室/idea", ["idea 南守谷店"]),
    ("通信キャリア/docomo", ["message_r"]),
    ("テック・アプリ/写真整理協会", ["shikuminet"]),
    ("自動車・バイク/timy", ["timyサポートセンター", "timyサポート窓口", "timy.info1@mc-ene.com"]),
    ("ショッピング/家電EC/ヤマダ電機", ["tpgaw"]),
    ("ショッピング/ダンボールワン", ["【ダンボールワン】"]),
    ("レジャー・チケット/レジャー/コニカミノルタプラネタリウム", ["コニカミノルタプラネタリウム“満天”"]),
    ("子育て/ミキハウス", ["ミキハウスオフィシャルサイト"]),
    ("住まい/不動産/三興土地開発", ["ラクラ"]),
    ("住まい/家電/三菱電機", ["三菱電機 CLUB MITSUBISHI ELECTRIC事務局"]),
    ("住まい/タカラスタンダード", ["出野 宏喜"]),
    ("転職/エンエージェント", ["山田 祐揮"]),
    ("交通・移動/京成電鉄", ["info@keisei.co.jp"]),
    ("通信キャリア/au", ["au-hpcustomerservice@au-cs-mail.kddi.com",
                    "auto@connect.auone.jp", "support-info@portalmail.kddi.com",
                    "info@wallet.auone.jp"]),
    ("ショッピング/ハンコヤドットコム", ["2011shop@hankoya.co.jp"]),
]

CO_MAP = {  # 送信元ドメイン(サフィックス一致) -> 宛先
    "pcdepot.co.jp": "仕事/PCデポ",
    "sankou-tkh.co.jp": "住まい/不動産/三興土地開発",
    "ssnet.co.jp": "テック・アプリ/HP",
}


def svc_():
    if os.getenv("USE_LOCAL", "0") != "1":
        print("❌ USE_LOCAL=1 が必要"); sys.exit(1)
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
            time.sleep(1.3*(a+1))


def is_excl(n): return any(n.startswith(p) for p in EXCL)


def ensure(svc, n2i, name):
    if name in n2i: return n2i[name]
    if DRY:
        print(f"    [DRY] 作成: {name}", flush=True); n2i[name] = "DRY"; return "DRY"
    try:
        r = svc.users().labels().create(userId="me", body={"name": name,
            "labelListVisibility": "labelShow", "messageListVisibility": "show"}).execute()
        n2i[name] = r["id"]; time.sleep(0.25); return r["id"]
    except Exception as e:
        if "409" in str(e):
            for l in svc.users().labels().list(userId="me").execute().get("labels", []):
                n2i[l["name"]] = l["id"]
            if name in n2i: return n2i[name]
            for ln, li in n2i.items():
                if ln.lower() == name.lower(): return li
        raise


def thr(svc, lid):
    o, p = [], None
    while True:
        kw = {"userId": "me", "labelIds": [lid], "maxResults": 500}
        if p: kw["pageToken"] = p
        r = retry(lambda: svc.users().threads().list(**kw).execute())
        o += [t["id"] for t in r.get("threads", [])]; p = r.get("nextPageToken")
        if not p: break
    return o


def dom(f):
    m = re.search(r"[\w.\-+]+@([\w.\-]+)", f or ""); return m.group(1).lower() if m else "?"


def co_dest(d):
    for k, v in CO_MAP.items():
        if d == k or d.endswith("." + k): return v
    return None


def main():
    print("🔍 DRY" if DRY else "🚀 本番", "ラウンド2\n", flush=True)
    svc = svc_()
    n2i = {l["name"]: l["id"] for l in svc.users().labels().list(userId="me").execute().get("labels", [])}
    ml = mt = 0
    print("=== 統合 ===", flush=True)
    for dst, srcs in CLUSTER_MERGES:
        valid = [s for s in srcs if s in n2i and not is_excl(s)]
        if not valid: continue
        did = ensure(svc, n2i, dst)
        for s in valid:
            tids = thr(svc, n2i[s])
            print(f"  {'[DRY] ' if DRY else ''}{s} → {dst}: {len(tids)}", flush=True)
            ml += 1; mt += len(tids)
            if not DRY:
                for t in tids:
                    retry(lambda: svc.users().threads().modify(userId="me", id=t,
                        body={"addLabelIds": [did], "removeLabelIds": [n2i[s]]}).execute())
                    time.sleep(0.04)
                retry(lambda: svc.users().labels().delete(userId="me", id=n2i[s]).execute())
                del n2i[s]; time.sleep(0.12)

    # co: メッセージ単位
    print("\n=== co 振り分け ===", flush=True)
    if "co" in n2i:
        from collections import Counter
        ids, p = [], None
        while True:
            kw = {"userId": "me", "labelIds": [n2i["co"]], "maxResults": 500}
            if p: kw["pageToken"] = p
            r = retry(lambda: svc.users().messages().list(**kw).execute())
            ids += [m["id"] for m in r.get("messages", [])]; p = r.get("nextPageToken")
            if not p: break
        plan = Counter(); unresolved = 0
        ensure(svc, n2i, "仕事/PCデポ"); ensure(svc, n2i, "住まい/不動産/三興土地開発"); ensure(svc, n2i, "テック・アプリ/HP")
        for mid in ids:
            md = retry(lambda: svc.users().messages().get(userId="me", id=mid,
                format="metadata", metadataHeaders=["From"]).execute())
            hs = md.get("payload", {}).get("headers", [])
            dst = co_dest(dom(next((h["value"] for h in hs if h["name"] == "From"), "")))
            if not dst: unresolved += 1; continue
            plan[dst] += 1
            if not DRY:
                retry(lambda: svc.users().messages().modify(userId="me", id=mid,
                    body={"addLabelIds": [n2i[dst]], "removeLabelIds": [n2i["co"]]}).execute())
                time.sleep(0.04)
        for d, c in plan.items(): print(f"  {'[DRY] ' if DRY else ''}co→{d}: {c}", flush=True)
        if unresolved: print(f"  未解決(coに残す): {unresolved}", flush=True)
        if not DRY and unresolved == 0:
            retry(lambda: svc.users().labels().delete(userId="me", id=n2i["co"]).execute())
            print("  ✅ co 削除", flush=True)

    # gmail: 件名で
    print("\n=== gmail 振り分け ===", flush=True)
    if "gmail" in n2i:
        ensure(svc, n2i, "エンタメ配信/U-NEXT"); ensure(svc, n2i, "通信キャリア/ISP")
        r = retry(lambda: svc.users().messages().list(userId="me", labelIds=[n2i["gmail"]], maxResults=500).execute())
        for m in r.get("messages", []):
            md = retry(lambda: svc.users().messages().get(userId="me", id=m["id"],
                format="metadata", metadataHeaders=["Subject"]).execute())
            subj = next((h["value"] for h in md.get("payload", {}).get("headers", []) if h["name"] == "Subject"), "")
            dst = "エンタメ配信/U-NEXT" if "U-NEXT" in subj else "通信キャリア/ISP"
            print(f"  {'[DRY] ' if DRY else ''}gmail→{dst}: 「{subj[:30]}」", flush=True)
            if not DRY:
                retry(lambda: svc.users().messages().modify(userId="me", id=m["id"],
                    body={"addLabelIds": [n2i[dst]], "removeLabelIds": [n2i["gmail"]]}).execute())
                time.sleep(0.04)
        if not DRY:
            retry(lambda: svc.users().labels().delete(userId="me", id=n2i["gmail"]).execute())
            print("  ✅ gmail 削除", flush=True)

    print(f"\n統合 {ml}ラベル/{mt}スレッド", flush=True)
    if DRY: print("[DRY] 変更なし", flush=True)


if __name__ == "__main__":
    main()
