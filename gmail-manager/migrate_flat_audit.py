#!/usr/bin/env python3
"""
migrate_flat_audit.py - フラットラベル精査結果を一括適用。

本文(snippet)＋件名＋送信元を確認した結果に基づく。
  - CLUSTER_MERGES: (宛先, [統合元...]) スレッドを宛先へ移動し統合元ラベル削除
  - DELETE_LABELS : メールごとTRASHへ移動してからラベル削除（スパ/詐欺/大量マーケ）
  - 個人・家族・混在ラベルは対象外（リストに入れない）

EZ系は一切触らない。

使い方:
  USE_LOCAL=1 python3 -u migrate_flat_audit.py --dry-run
  USE_LOCAL=1 python3 -u migrate_flat_audit.py
"""

import json, os, sys, time
import google.auth.transport.requests
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

DRY_RUN = "--dry-run" in sys.argv
LOCAL_CREDS_PATH = os.path.expanduser("~/.gmail_local_credentials.json")
EXCLUDE_PREFIXES = ("EZ受信ボックス", "EZ送信ボックス")

# =====================================================================
# (宛先, [統合元...])  ※統合元は監査の本文確認に基づく
# =====================================================================
CLUSTER_MERGES = [
    # ── ショッピング ──
    ("ショッピング/イオン", ["aeon"]),
    ("ショッピング/ニトリ", ["Customer Services Team", "From Website"]),
    ("ショッピング/ティファニー", ["Japan, cc_hoten_br"]),
    ("ショッピング/ONESTOP", ["ONESTOP"]),
    ("ショッピング/ルミナスクラブ", ["(株)ドウシシャ運営のルミナスラック直販サイト[Luminous-CLUB]"]),
    ("ショッピング/Honya Club", ["honyaclub"]),
    ("ショッピング/カラメル", ["カラメル"]),
    ("ショッピング/お宝創庫", ["お宝創庫オンラインショップお問合せ"]),
    ("ショッピング/ハーモニック", ["カタログギフトのハーモニック[公式サイト]"]),
    ("ショッピング/グリーンコンシューマー", ["グリンコンシューマー ヤフーショッピング店"]),
    ("ショッピング/ファッション/ジーフット", ["ジーフットアプリ"]),
    ("ショッピング/ファッション/BEAMS", ["ファッション"]),
    ("ショッピング/カメラのキタムラ", ["ktg-dontreply"]),
    ("ショッピング/グラフィック", ["かんたんアプリ"]),

    # ── グルメ ──
    ("グルメ/EPARK", ["epark"]),
    ("グルメ/すかいらーく", ["i-skylark"]),
    ("グルメ/menu", ["menu"]),
    ("グルメ/菊家", ["お菓子の菊家オンラインショップ", "kikuya-oita"]),

    # ── テック・アプリ ──
    ("テック・アプリ/Google Maps", ["Google マップ"]),
    ("テック・アプリ/NETGEAR", ["Insight"]),
    ("テック・アプリ/ExpanDrive", ["Jeff Mancuso"]),
    ("テック・アプリ/OtterBox", ["OtterBox APAC"]),
    ("テック・アプリ/Plus Docs", ["Plus Docs Inc."]),
    ("テック・アプリ/Broadcom", ["broadcom"]),
    ("テック・アプリ/codoc", ["codoc Support"]),
    ("テック・アプリ/eNom", ["enom"]),
    ("テック・アプリ/iMobie", ["iMobie"]),
    ("テック・アプリ/GSM Unlock", ["GSM Unlock USA"]),
    ("テック・アプリ/風見鶏", ["風見鶏"]),
    ("テック・アプリ/がうがう", ["モバイルガジェットショップ がうがう！"]),
    ("テック・アプリ/音響機器/AMULECH", ["商品等についての問い合わせ"]),
    ("テック・アプリ/ピクチャン", ["ピクチャン「コンビニ証明写真」運営事務局"]),
    ("テック・アプリ/xID", ["xID"]),

    # ── セキュリティ ──
    ("セキュリティ/ESET", ["ess-info"]),

    # ── 自動車・バイク ──
    ("自動車・バイク/宇佐美", ["'うさマート'"]),
    ("自動車・バイク/カー用品/BeautifulCars", ["BeautifulCars(ビューティフルカーズ)"]),
    ("自動車・バイク/Raku-P", ["Raku-P"]),
    ("自動車・バイク/バイク/カワサキプラザ", ["kawasaki-plaza", "カワサキプラザ相模原"]),
    ("自動車・バイク/バイク/MotoJP", ["main"]),
    ("自動車・バイク/バイク用品/ヒロチー商事", ["株式会社ヒロチー商事 PayPay店"]),
    ("自動車・バイク/ビッグモーター", ["ビッグモーター 成田営業"]),
    ("自動車・バイク/パーツ/partsfan", ["partsfan"]),
    ("自動車・バイク/バイク用品/Motostorm", ["motostorm"]),
    ("自動車・バイク/トータルリペア", [
        "トータルリペア アクティブ", "トータルリペア イーサン",
        "トータルリペアIPY", "tr-ipy"]),
    ("自動車・バイク/車検", ["金子 友一"]),
    ("自動車・バイク/バイク/BAS", ["ＢＡＳコールセンター"]),
    ("自動車・バイク/パーツ/BEN'S SHOP", ["BEN’S SHOP"]),

    # ── 旅行 / レジャー ──
    ("旅行/予約/じゃらん", ["Go To トラベルじゃらん事後還付サポートデスク"]),
    ("旅行/ジェットスター", ["Jetstar Survey", "kessai"]),
    ("旅行/ホテル/Relux", ["Reluxコンシェルジュデスク"]),
    ("旅行/Trip.com", ["trip"]),
    ("旅行/レンタカー/沖縄たびんふぉ", ["沖縄たびんふぉ"]),
    ("旅行/立山黒部アルペンルート", ["自動送信用アドレス"]),
    ("レジャー・チケット/レジャー/軽井沢スノーパーク", ["presidentresort"]),
    ("レジャー・チケット/チケット/三栄チケットサービス", ["moala"]),
    ("レジャー・チケット/カラオケDAM", ["clubdam"]),
    ("レジャー・チケット/GENDA", ["genda-apis"]),

    # ── 住まい ──
    ("住まい/家電/ダイニチ工業", ["Root User", "ダイニチ工業 技術サポートセンター"]),
    ("住まい/家電/デロンギ", ["custhelp"]),
    ("住まい/引越し/アート引越センター", ["the0123"]),
    ("住まい/家具/NOYES", ["ソファ専門店 NOYES", "【ソファ専門店 NOYES】 お問い合わせ窓口"]),
    ("住まい/家具/かねたや", ["かねたやルームデコ"]),
    ("住まい/リンテックコマース", ["リンテックコマース株式会社"]),
    ("住まい/スマートホーム/Qrio", ["qrioinc", "no-reply"]),
    # 不動産（人名ラベルだが本文は業者）
    ("住まい/不動産/東宝ハウス町田", ["奥田晃太朗", "廣部裕次郎"]),
    ("住まい/不動産/大東建託", ["中川 雅之"]),
    ("住まい/不動産/東建コーポレーション", ["根本 恭輔", "守谷支店代表"]),
    ("住まい/不動産/住友林業ホームサービス", ["柳澤 一範", "藤本 南"]),
    ("住まい/不動産/住まいの広場TOWNS", ["営業岸田"]),
    ("住まい/不動産/サンクルー", ["尾崎北斗"]),
    ("住まい/不動産/Renosy", ["高畑有里"]),

    # ── 保険（人名ラベルだが本文は代理店）──
    ("保険/損保ジャパン", ["anshinmy", "anshinmy.com"]),
    ("保険/ウインストン", ["ウインストン 小澄 太祐", "ウインストン小澄", "ウインストン小澄G-mail"]),
    ("保険/エス・ケイ・ティ", ["株式会社エス・ケイ・ティ"]),

    # ── 法律（新設）──
    ("法律/カヤヌマ国際法律事務所", ["kaya-law"]),
    ("法律/サンク総合法律事務所", ["サンク総合法律事務所"]),
    ("法律/宮下総合法律事務所", ["横井翔太"]),

    # ── 子育て ──
    ("子育て/ハグノート", ["ハグノート hugnote"]),
    ("子育て/ヒューマンアカデミー", ["ヒューマンアカデミー Lynx事務局", "向原奈穂"]),
    ("子育て/スナップスナップ", ["スナップスナップ"]),
    ("子育て/まあむキッズ", ["mom2"]),

    # ── 医療 ──
    ("医療/489map", ["489map"]),
    ("医療/shujii", ["shujii"]),
    ("医療/山岸クリニック", ["airrsv"]),

    # ── 行政 / 宅配 ──
    ("宅配・物流/日本郵便", ["japanpost"]),
    ("行政/防火防災協会", ["or"]),
    ("行政/自治体マイページ", ["mypg"]),
    ("行政/LoGoフォーム", ["logoform"]),
    ("行政/首都圏デジタル産業健康保険組合", ["ibss"]),
    ("交通・移動/高速道路/NEXCO東日本", ["ドラ割事務局(NEXCO東日本)"]),

    # ── 通信キャリア ──
    ("通信キャリア/au", ["auone-mail", "安心ケータイサポートセンター"]),
    ("通信キャリア/t-mobile", ["t-mobile"]),
    ("通信キャリア/Wi2", ["株式会社ワイヤ・アンド・ワイヤレス"]),
    ("通信キャリア/FON", ["ＦＯＮコミュニティ"]),

    # ── 仕事/PCデポ（旧勤務先 社内メール・新設）──
    ("仕事/PCデポ", [
        "小関 絵里香", "石田 さやか", "福田 真弓", "渡辺 典男", "松尾 裕子",
        "山崎 未貴", "松原 実", "自社株売買事前相談窓口", "杉田 淳一", "杉田淳一",
        "はぜのき"]),
]

# メールごとTRASHへ → ラベル削除（スパム/詐欺/大量マーケ）
DELETE_LABELS = [
    "C.L.C BOARD",
    "C.L.C COMMITTEE",
    "Info",
    "Million Lynelle",
    "松本浩典",
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


def retry(fn, t=4):
    for a in range(t):
        try:
            return fn()
        except Exception as e:
            if a == t-1:
                raise
            time.sleep(1.3*(a+1))


def is_excluded(name):
    return any(name.startswith(p) for p in EXCLUDE_PREFIXES)


def ensure_label(svc, name2id, name):
    if name in name2id:
        return name2id[name]
    if DRY_RUN:
        print(f"    [DRY] 作成: 「{name}」", flush=True)
        name2id[name] = f"DRY_{name}"
        return name2id[name]
    try:
        r = svc.users().labels().create(userId="me", body={
            "name": name, "labelListVisibility": "labelShow",
            "messageListVisibility": "show"}).execute()
        name2id[name] = r["id"]
        time.sleep(0.25)
        return r["id"]
    except Exception as e:
        if "409" in str(e):
            for l in svc.users().labels().list(userId="me").execute().get("labels", []):
                name2id[l["name"]] = l["id"]
            return name2id.get(name)
        raise


def thread_ids(svc, lid):
    out, page = [], None
    while True:
        kw = {"userId": "me", "labelIds": [lid], "maxResults": 500}
        if page:
            kw["pageToken"] = page
        r = retry(lambda: svc.users().threads().list(**kw).execute())
        out += [t["id"] for t in r.get("threads", [])]
        page = r.get("nextPageToken")
        if not page:
            break
    return out


def msg_ids(svc, lid):
    out, page = [], None
    while True:
        kw = {"userId": "me", "labelIds": [lid], "maxResults": 500}
        if page:
            kw["pageToken"] = page
        r = retry(lambda: svc.users().messages().list(**kw).execute())
        out += [m["id"] for m in r.get("messages", [])]
        page = r.get("nextPageToken")
        if not page:
            break
    return out


def main():
    print("🔍 DRY RUN" if DRY_RUN else "🚀 本番実行", "（フラット精査の一括適用）\n", flush=True)
    svc = get_service()
    name2id = {l["name"]: l["id"]
               for l in svc.users().labels().list(userId="me").execute().get("labels", [])}

    merged_labels = merged_threads = 0
    print("===== カテゴリ統合 =====", flush=True)
    for dst, sources in CLUSTER_MERGES:
        valid = [s for s in sources if s in name2id and not is_excluded(s)]
        if not valid:
            continue
        dst_id = ensure_label(svc, name2id, dst)
        if dst_id is None:
            print(f"  ❌ 宛先不可: {dst}", flush=True); continue
        for s in valid:
            tids = thread_ids(svc, name2id[s])
            print(f"  {('[DRY] ' if DRY_RUN else '')}{s} → {dst} : {len(tids)}件", flush=True)
            merged_labels += 1
            merged_threads += len(tids)
            if not DRY_RUN:
                for tid in tids:
                    retry(lambda: svc.users().threads().modify(
                        userId="me", id=tid,
                        body={"addLabelIds": [dst_id], "removeLabelIds": [name2id[s]]}).execute())
                    time.sleep(0.04)
                retry(lambda: svc.users().labels().delete(userId="me", id=name2id[s]).execute())
                del name2id[s]
                time.sleep(0.15)

    print("\n===== メールごと削除(TRASH) =====", flush=True)
    del_labels = del_msgs = 0
    for name in DELETE_LABELS:
        lid = name2id.get(name)
        if not lid or is_excluded(name):
            continue
        mids = msg_ids(svc, lid)
        print(f"  {('[DRY] ' if DRY_RUN else '')}🗑 {name} : {len(mids)}件をTRASHへ → ラベル削除", flush=True)
        del_labels += 1
        del_msgs += len(mids)
        if not DRY_RUN:
            for i in range(0, len(mids), 1000):
                chunk = mids[i:i+1000]
                retry(lambda: svc.users().messages().batchModify(
                    userId="me", body={"ids": chunk, "addLabelIds": ["TRASH"]}).execute())
                time.sleep(0.1)
            retry(lambda: svc.users().labels().delete(userId="me", id=lid).execute())
            time.sleep(0.15)

    print(f"\n{'='*56}", flush=True)
    print(f"統合: {merged_labels}ラベル / {merged_threads}スレッド", flush=True)
    print(f"削除: {del_labels}ラベル / {del_msgs}メールをTRASH", flush=True)
    if DRY_RUN:
        print("[DRY] 変更なし。--dry-run を外すと実行。", flush=True)


if __name__ == "__main__":
    main()
