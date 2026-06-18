#!/usr/bin/env python3
"""
route_co.py - 「co」ラベル(.co.jp 由来の混在ラベル)をメッセージ単位で
              送信元ドメイン→既存カテゴリへ個別振り分けする。

- ドメインは「サフィックス一致」: credit.sjnk.co.jp は sjnk.co.jp の規則に従う
- DOMAIN_MAP に無いドメインは触らず「co」に残す
- 全部振り分け終わって co が空になったらラベル削除、残れば保持
- メッセージ単位で modify（スレッド全体ではない）

使い方:
  USE_LOCAL=1 python3 route_co.py --dry-run
  USE_LOCAL=1 python3 route_co.py
"""

import json, os, re, sys, time
from collections import Counter, defaultdict

import google.auth.transport.requests
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

DRY_RUN = "--dry-run" in sys.argv
LOCAL_CREDS_PATH = os.path.expanduser("~/.gmail_local_credentials.json")
TARGET = "co"

# base-domain → 宛先ラベル（サフィックス一致）
DOMAIN_MAP = {
    # マネー・金融
    "lifecard.co.jp":      "マネー・金融/クレジットカード/ライフカード",
    "cedyna.co.jp":        "マネー・金融/クレジットカード/セディナ",
    "orico.co.jp":         "マネー・金融/クレジットカード/オリコ",
    "cardservice.co.jp":   "マネー・金融/クレジットカード/ZEUS",
    "jscore.co.jp":        "マネー・金融/J.Score",
    "boy.co.jp":           "マネー・金融/銀行/横浜銀行",
    "chibabank.co.jp":     "マネー・金融/銀行/千葉銀行",
    # 保険
    "sjnk.co.jp":          "保険/損保ジャパン",
    "sompo-japan.co.jp":   "保険/損保ジャパン",
    "meijiyasuda.co.jp":   "保険/明治安田生命",
    "fukoku-life.co.jp":   "保険/フコク生命",
    "msa-life.co.jp":      "保険/三井住友海上あいおい生命",
    "axa-direct.co.jp":    "保険/アクサダイレクト",
    # ヘルス・美容
    "megalos.co.jp":       "ヘルス・美容/フィットネス/メガロス",
    "orbis.co.jp":         "ヘルス・美容/ORBIS",
    # 住まい
    "nomura-re.co.jp":     "住まい/不動産/野村不動産",
    "takara-standard.co.jp":"住まい/タカラスタンダード",
    "homes.co.jp":         "住まい/不動産/LIFULL HOME'S",
    "token.co.jp":         "住まい/不動産/東建コーポレーション",
    "lifecoordinator.co.jp":"住まい/不動産/ライフコーディネーター",
    "hikkoshi-sakai.co.jp":"住まい/引越し/サカイ引越センター",
    # ショッピング
    "premoa.co.jp":        "ショッピング/家電EC/XPRICE",
    "soundhouse.co.jp":    "ショッピング/サウンドハウス",
    "llbean.co.jp":        "ショッピング/ファッション/L.L.Bean",
    "toysrusonline.co.jp": "ショッピング/トイザらス",
    "hankoya.co.jp":       "ショッピング/ハンコヤドットコム",
    "wonder.co.jp":        "ショッピング/WonderGOO",
    # グルメ
    "chateraise.co.jp":    "グルメ/シャトレーゼ",
    "gnavi.co.jp":         "グルメ/ぐるなび",
    "skylark.co.jp":       "グルメ/すかいらーく",
    # 旅行
    "mwt.co.jp":           "旅行/名鉄観光",
    "knt.co.jp":           "旅行/近畿日本ツーリスト",
    "jrtours.co.jp":       "旅行/JR東海ツアーズ",
    "fujikyu-travel.co.jp":"旅行/富士急トラベル",
    "tokyuhotels.co.jp":   "旅行/ホテル/東急ホテルズ",
    "ana-x.co.jp":         "旅行/ANA",
    # 交通・移動
    "meitetsu.co.jp":      "交通・移動/名鉄",
    "e-nexco.co.jp":       "交通・移動/高速道路/NEXCO東日本",
    "j-bus.co.jp":         "交通・移動/バス/発車オーライネット",
    "times24.co.jp":       "交通・移動/駐車場/タイムズ",
    "keisei.co.jp":        "交通・移動/京成電鉄",
    # 自動車・バイク
    "axisinc.co.jp":       "自動車・バイク/自動車/日産",
    "nissan.co.jp":        "自動車・バイク/自動車/日産",
    "nissan-fs.co.jp":     "自動車・バイク/自動車/日産",
    "dunlop.co.jp":        "自動車・バイク/カー用品/ダンロップ",
    # レジャー・チケット
    "usj.co.jp":           "レジャー・チケット/レジャー/USJ",
    "fujisafari.co.jp":    "レジャー・チケット/レジャー/富士サファリパーク",
    "gigo.co.jp":          "レジャー・チケット/レジャー/GiGO",
    # エンタメ配信
    "papy.co.jp":          "エンタメ配信/電子書籍/Renta!",
    "fujisan.co.jp":       "エンタメ配信/電子書籍/Fujisan.co.jp",
    # 子育て
    "mikihouse.co.jp":     "子育て/ミキハウス",
    # 通信キャリア
    "fusioncom.co.jp":     "通信キャリア/楽天でんわ",
    # テック・アプリ
    "sony.co.jp":          "テック・アプリ/Sony",
    "vector.co.jp":        "テック・アプリ/Vector",
    # 宅配・物流
    "sagawa-exp.co.jp":    "宅配・物流/佐川急便",
}

# あえて残す（判定不能・社内メールの恐れ）: sankou-tkh / pcdepot / hpj.ssnet など


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


def domain_of(frm):
    m = re.search(r"[\w.\-+]+@([\w.\-]+)", frm or "")
    return m.group(1).lower() if m else ""


def match_label(domain):
    best = None
    for k in DOMAIN_MAP:
        if domain == k or domain.endswith("." + k):
            if best is None or len(k) > len(best):
                best = k
    return DOMAIN_MAP[best] if best else None


def ensure_label(svc, name2id, name):
    if name in name2id:
        return name2id[name]
    if DRY_RUN:
        name2id[name] = f"DRY_{name}"
        return name2id[name]
    try:
        res = svc.users().labels().create(
            userId="me",
            body={"name": name, "labelListVisibility": "labelShow",
                  "messageListVisibility": "show"}).execute()
        name2id[name] = res["id"]
        print(f"    ✅ ラベル作成: 「{name}」")
        time.sleep(0.3)
        return res["id"]
    except Exception as e:
        if "409" in str(e):
            for l in svc.users().labels().list(userId="me").execute().get("labels", []):
                name2id[l["name"]] = l["id"]
            return name2id.get(name)
        raise


def main():
    print("🔍 DRY RUN" if DRY_RUN else "🚀 本番実行", "（co 個別振り分け）\n")
    svc = get_service()
    name2id = {l["name"]: l["id"]
               for l in svc.users().labels().list(userId="me").execute().get("labels", [])}
    co_id = name2id.get(TARGET)
    if not co_id:
        print("co ラベルが見つかりません。"); return

    # co 全メッセージ取得
    msgs, page = [], None
    while True:
        kw = {"userId": "me", "labelIds": [co_id], "maxResults": 500}
        if page:
            kw["pageToken"] = page
        r = svc.users().messages().list(**kw).execute()
        msgs.extend(m["id"] for m in r.get("messages", []))
        page = r.get("nextPageToken")
        if not page:
            break
    print(f"co 総メッセージ: {len(msgs)}\n")

    # 各メッセージの宛先を決定
    plan = defaultdict(list)   # label -> [msg_id]
    unmapped = Counter()
    for mid in msgs:
        md = svc.users().messages().get(
            userId="me", id=mid, format="metadata", metadataHeaders=["From"]).execute()
        hs = md.get("payload", {}).get("headers", [])
        dom = domain_of(next((h["value"] for h in hs if h["name"] == "From"), ""))
        lbl = match_label(dom)
        if lbl:
            plan[lbl].append(mid)
        else:
            unmapped[dom] += 1

    print("=== 振り分け予定 ===")
    for lbl in sorted(plan, key=lambda x: -len(plan[x])):
        print(f"  {len(plan[lbl]):>3}  → {lbl}")
    moved_total = sum(len(v) for v in plan.values())
    print(f"\n  振り分け: {moved_total} 件 / {len(DOMAIN_MAP)} ドメイン規則")
    if unmapped:
        print(f"\n=== co に残す(未マップ) {sum(unmapped.values())} 件 ===")
        for dom, c in unmapped.most_common():
            print(f"  {c:>3}  {dom}")

    if DRY_RUN:
        print("\n[DRY] 変更なし。問題なければ --dry-run を外して実行。")
        return

    # 宛先ラベルを用意
    for lbl in plan:
        ensure_label(svc, name2id, lbl)

    # メッセージ単位で移動
    done = 0
    for lbl, ids in plan.items():
        dst = name2id[lbl]
        for mid in ids:
            try:
                svc.users().messages().modify(
                    userId="me", id=mid,
                    body={"addLabelIds": [dst], "removeLabelIds": [co_id]}).execute()
                done += 1
            except Exception as e:
                print(f"    ❌ {e}")
            if done % 50 == 0:
                print(f"    ... {done}/{moved_total}")
            time.sleep(0.05)

    # co が空になったら削除
    left = svc.users().messages().list(userId="me", labelIds=[co_id], maxResults=1).execute()
    if not left.get("messages"):
        svc.users().labels().delete(userId="me", id=co_id).execute()
        print("\n✅ co ラベルは空になったので削除しました。")
    else:
        print(f"\n✅ 振り分け完了。未マップ分が残るため co ラベルは保持します。")
    print(f"   移動: {done} 件")


if __name__ == "__main__":
    main()
