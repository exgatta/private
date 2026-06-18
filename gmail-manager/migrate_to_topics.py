#!/usr/bin/env python3
"""
Gmail ラベルをブランド親 → トピック親に一括移行（一回限りの移行スクリプト）

使い方:
  USE_LOCAL=1 python3 migrate_to_topics.py --dry-run   # プレビューのみ（変更なし）
  USE_LOCAL=1 python3 migrate_to_topics.py             # 本番実行（不可逆！）

除外（絶対に変更しない）:
  EZ受信ボックス・EZ送信ボックス 配下のラベルは一切触れない。
"""

import json
import os
import sys
import time

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

DRY_RUN = "--dry-run" in sys.argv
LOCAL_CREDS_PATH = os.path.expanduser("~/.gmail_local_credentials.json")

# 変更禁止プレフィックス
EXCLUDE_PREFIXES = ("EZ受信ボックス", "EZ送信ボックス")


# ─── 個別マッピング（ブランド内で内容がはみ出るもの） ─────────────────────────────
# 優先度: EXACT_REMAP > PARENT_DEFAULT
# キー: 現在の完全ラベル名  値: 移行後の完全ラベル名
EXACT_REMAP = {
    # ── バグ修正: 3階層の親名自体をリネーム（子ラベルより先に処理してはいけない） ──
    # 子ラベルは DEEP_PARENT_FIX で先に処理し、最後に親ラベルをリネームする
    "ニュース/メディア":  "ニュース・メディア",    # 親ラベル自体
    "美容/健康":          "ヘルス・美容",          # 親ラベル自体

    # ── Google ────────────────────────────────────────────────────────────────
    "Google/YouTube":           "エンタメ配信/YouTube",
    "Google/YouTube Music":     "エンタメ配信/YouTube Music",
    "Google/YouTube Kids":      "エンタメ配信/YouTube Kids",
    "Google/YouTube Premium":   "エンタメ配信/YouTube Premium",
    "Google/Google Play":       "ゲーム/Google Play",
    "Google/Google Play Music": "エンタメ配信/Google Play Music",
    "Google/Google Maps":       "交通・移動/Google Maps",
    "Google/Google Maps Timeline": "交通・移動/Google Maps Timeline",
    "Google/Google Wallet":     "マネー・金融/Google Wallet",
    "Google/Google Pay":        "マネー・金融/Google Pay",
    "Google/Google Payments":   "マネー・金融/Google Payments",

    # ── Amazon ────────────────────────────────────────────────────────────────
    "Amazon/Prime Video": "エンタメ配信/Prime Video",

    # ── Sony（ゲーム系のみ抽出）────────────────────────────────────────────────
    "Sony/PlayStation":                         "ゲーム/PlayStation",
    "Sony/PlayStation Network":                 "ゲーム/PlayStation Network",
    "Sony/sonyentertainmentnetwork":            "ゲーム/Sony Entertainment Network",
    "Sony/ソニー・コンピュータエンタテインメント": "ゲーム/ソニー・コンピュータエンタテインメント",
    "Sony/SCE インフォメーションセンター":       "ゲーム/SCE インフォメーションセンター",
    "Sony/SCEJ オンライン受付サービス":          "ゲーム/SCEJ オンライン受付サービス",
    "Sony/SIEJA 延長保証受付サービス":           "ゲーム/SIEJA 延長保証受付サービス",

    # ── au（ゲーム系のみ抽出）─────────────────────────────────────────────────
    "au/GeForce NOW Powered by au": "ゲーム/GeForce NOW(au)",

    # ── SoftBank（ゲーム系のみ抽出）───────────────────────────────────────────
    "SoftBank/GeForce NOW Powered by SoftBank 送信専用": "ゲーム/GeForce NOW(SoftBank)",

    # ── 楽天（金融・グルメ系を抽出）───────────────────────────────────────────
    "楽天/楽天証券":     "マネー・金融/楽天証券",
    "楽天/楽天ぐるなび": "グルメ/楽天ぐるなび",

    # ── 野村グループ（不動産系を住まいへ）────────────────────────────────────
    "野村グループ/野村不動産「プラウド中野島」販売準備室":        "住まい/野村不動産(プラウド中野島)",
    "野村グループ/野村不動産「プラウドつくば」販売準備室":        "住まい/野村不動産(プラウドつくば)",
    "野村グループ/野村不動産「プラウド水戸三の丸」販売準備室":    "住まい/野村不動産(プラウド水戸三の丸)",
    "野村グループ/野村不動産「プラウド水戸桜川」販売準備室":      "住まい/野村不動産(プラウド水戸桜川)",
    "野村グループ/野村不動産「周年記念お客様感謝イベント事務局」": "住まい/野村不動産(周年記念)",

    # ── オリックス（業種別に分類）─────────────────────────────────────────────
    "オリックス/オリックスレンタカー":           "旅行/オリックスレンタカー",
    "オリックス/オリックス自動車":               "自動車/オリックス自動車",
    "オリックス/オリックス銀行":                 "マネー・金融/オリックス銀行",
    "オリックス/オリックス銀行株式会社":         "マネー・金融/オリックス銀行",
    "オリックス/オリックス銀行 キャンペーンデスク": "マネー・金融/オリックス銀行 キャンペーンデスク",

    # ── 三井住友（銀行/カードは金融、保険は保険へ）────────────────────────────
    "三井住友/三井住友銀行":           "マネー・金融/三井住友銀行",
    "三井住友/三井住友カード":         "マネー・金融/三井住友カード",
    "三井住友/三井住友海上あいおい生命": "保険/三井住友海上あいおい生命",

    # ── ANA（ホテルは旅行、ショッピングはショッピングへ）─────────────────────
    "ANA/ANAインターコンチネンタルホテル東京": "旅行/ANAインターコンチネンタルホテル東京",
    "ANA/ANAショッピングA-style":            "ショッピング/ANAショッピングA-style",

    # ── 損保ジャパン（全て保険）────────────────────────────────────────────────
    # ※ PARENT_DEFAULT で "損保ジャパン" → "保険" にまとめて処理するので
    #   ここに個別指定は不要。保険グループとして一括移行。

    # ── 横浜銀行（全てマネー・金融）───────────────────────────────────────────
    # ※ PARENT_DEFAULT で処理。

    # ── DMM 内の DLsite 3階層バグ ──────────────────────────────────────────────
    "DMM/DLsite/DLsiteがるまに/DLsite comipo":  "エンタメ配信/DLsite comipo",
    # 実際のラベル名は "DLsite/DLsiteがるまに/DLsite comipo" (DMM 配下ではない場合も)
    "DLsite/DLsiteがるまに/DLsite comipo":      "エンタメ配信/DLsite comipo",
}

# 3階層バグの修正: "ニュース/メディア/X" → "ニュース・メディア/X"
# "美容/健康/X" → "ヘルス・美容/X"
# これらはコードで自動生成する（EXACT_REMAP では親ラベル名の変更のみ記載）
DEEP_PARENT_FIX = {
    "ニュース/メディア/": "ニュース・メディア/",
    "美容/健康/":         "ヘルス・美容/",
}


# ─── ブランド親 → トピック親の一括マッピング ──────────────────────────────────
# EXACT_REMAP で指定したものは上書きされるのでここはデフォルト
PARENT_DEFAULT = {
    # テック・アプリ
    "Google":        "テック・アプリ",
    "Apple":         "テック・アプリ",
    "Microsoft":     "テック・アプリ",
    "Adobe":         "テック・アプリ",
    "Logicool":      "テック・アプリ",
    "DJI":           "テック・アプリ",
    "Sony":          "テック・アプリ",     # PlayStation 系は EXACT_REMAP で ゲーム へ
    "Ameba":         "テック・アプリ",
    "Parallels":     "テック・アプリ",
    "ソースネクスト": "テック・アプリ",
    "TeamViewer":    "テック・アプリ",
    "Dropbox":       "テック・アプリ",
    "GMO":           "テック・アプリ",
    "FC2":           "テック・アプリ",

    # ゲーム
    "Steam":        "ゲーム",
    "SQUARE ENIX":  "ゲーム",
    "Nintendo":     "ゲーム",
    "SEGA":         "ゲーム",
    "DMM":          "ゲーム",             # DLsite も含む

    # エンタメ配信
    "ニコニコ":   "エンタメ配信",
    "mora":       "エンタメ配信",
    "レコチョク": "エンタメ配信",

    # ショッピング
    "Amazon":          "ショッピング",    # Prime Video は EXACT_REMAP で エンタメ配信 へ
    "楽天":            "ショッピング",    # 楽天証券・楽天ぐるなびは EXACT_REMAP で個別処理
    "ZOZOTOWN":        "ショッピング",
    "ユニクロ":        "ショッピング",
    "NANO universe":   "ショッピング",
    "アルペングループ": "ショッピング",
    "ノジマ":          "ショッピング",
    "ビックカメラ":    "ショッピング",
    "モノタロウ":      "ショッピング",

    # マネー・金融
    "野村グループ": "マネー・金融",    # 不動産系は EXACT_REMAP で 住まい へ
    "三井住友":     "マネー・金融",    # 個別は EXACT_REMAP で処理済み
    "横浜銀行":     "マネー・金融",
    "Ponta":        "マネー・金融",
    "Paidy":        "マネー・金融",
    "オリックス":   "マネー・金融",    # レンタカー・自動車は EXACT_REMAP で個別処理

    # 保険
    "損保ジャパン": "保険",
    "アイペット":   "保険",

    # 通信キャリア
    "au":       "通信キャリア",    # GeForce NOW は EXACT_REMAP で ゲーム へ
    "ドコモ":   "通信キャリア",
    "SoftBank": "通信キャリア",    # GeForce NOW は EXACT_REMAP で ゲーム へ
    "NTT":      "通信キャリア",

    # 旅行
    "ANA":          "旅行",    # ショッピング・ホテルは EXACT_REMAP で個別処理
    "アパホテル":   "旅行",
    "Hotels.com":   "旅行",
    "Trip.com":     "旅行",

    # グルメ
    "焼肉きんぐ": "グルメ",
    "出前館":     "グルメ",

    # セキュリティ
    "AdGuard":    "セキュリティ",
    "カスペルスキー": "セキュリティ",

    # ヘルス・美容
    "ユーグレナ": "ヘルス・美容",

    # レジャー・チケット
    "コニカミノルタプラネタリウム": "レジャー・チケット",

    # 宅配・物流
    "佐川急便":  "宅配・物流",
    "ヤマト運輸": "宅配・物流",
    "FedEx":     "宅配・物流",

    # 自動車・バイク
    "日産": "自動車・バイク",
}

# 既存トピック親のリネーム（親ラベル自体を改名する場合）
# 「ニュース/メディア」「美容/健康」は EXACT_REMAP + DEEP_PARENT_FIX で処理
# それ以外で既存トピック親の名称を統一したいもの
TOPIC_PARENT_RENAME = {
    # 旧名                  → 新名
    "ニュース/メディア":    "ニュース・メディア",
    "美容/健康":            "ヘルス・美容",
}


def get_gmail_service():
    import google.auth.transport.requests

    if os.getenv("USE_LOCAL", "0") == "1":
        if not os.path.exists(LOCAL_CREDS_PATH):
            print(f"❌ ローカル認証ファイルが見つかりません: {LOCAL_CREDS_PATH}")
            print("   先に get_local_token.py を実行してください。")
            sys.exit(1)
        with open(LOCAL_CREDS_PATH) as f:
            d = json.load(f)
        creds = Credentials(
            token=d.get("token"),
            refresh_token=d["refresh_token"],
            token_uri=d.get("token_uri", "https://oauth2.googleapis.com/token"),
            client_id=d["client_id"],
            client_secret=d["client_secret"],
        )
        if not creds.valid:
            creds.refresh(google.auth.transport.requests.Request())
        return build("gmail", "v1", credentials=creds, cache_discovery=False)

    print("❌ USE_LOCAL=1 が必要です。")
    sys.exit(1)


def fetch_all_labels(svc):
    result = svc.users().labels().list(userId="me").execute()
    return {lbl["name"]: lbl["id"] for lbl in result.get("labels", [])}


def rename_label(svc, label_id, old_name, new_name):
    if DRY_RUN:
        print(f"  [DRY-RUN] '{old_name}'  →  '{new_name}'")
        return True
    try:
        svc.users().labels().patch(
            userId="me", id=label_id, body={"name": new_name}
        ).execute()
        print(f"  ✅ '{old_name}'  →  '{new_name}'")
        time.sleep(0.3)
        return True
    except Exception as e:
        print(f"  ❌ '{old_name}' → '{new_name}' 失敗: {e}")
        return False


def is_excluded(name):
    return any(name == p or name.startswith(p + "/") for p in EXCLUDE_PREFIXES)


def compute_renames(label_map):
    """
    現在のラベル一覧から、実行すべきリネーム操作のリストを計算する。
    戻り値: [(old_name, new_name, label_id), ...]
    処理順序:
      1. 3階層バグ修正（子ラベルを先に）
      2. EXACT_REMAP（個別指定）
      3. PARENT_DEFAULT（ブランド親の残りの子を一括）
      4. EXACT_REMAP に含まれる親ラベル自体のリネーム（最後）
    """
    renames = []
    seen_new = {}  # new_name → old_name (重複チェック)
    label_names = set(label_map.keys())

    def add(old, new):
        if old not in label_map:
            return
        if is_excluded(old):
            print(f"  ⚠️  除外対象のためスキップ: '{old}'")
            return
        if old == new:
            return
        if new in seen_new:
            print(f"  ⚠️  移行先重複: '{new}' ← '{old}' と '{seen_new[new]}' が衝突 → スキップ")
            return
        if new in label_names and new != old:
            print(f"  ⚠️  移行先が既存ラベルと衝突: '{new}' は既に存在 → スキップ: '{old}'")
            return
        seen_new[new] = old
        renames.append((old, new, label_map[old]))

    # ── Step 1: 3階層バグ修正（深い方から処理）──────────────────────────────
    print("\n[Step 1] 3階層バグ修正（ニュース/メディア・美容/健康 の子ラベル）")
    for prefix, new_prefix in DEEP_PARENT_FIX.items():
        children = sorted(
            [n for n in label_map if n.startswith(prefix)],
            key=lambda x: -x.count("/"),  # 深い方から
        )
        for old in children:
            leaf = old[len(prefix):]
            new = new_prefix + leaf
            add(old, new)

    # ── Step 2: EXACT_REMAP（個別指定。ただし親ラベル自体は後回し）────────────
    print("\n[Step 2] 個別マッピング（EXACT_REMAP）")
    deferred_parents = set(TOPIC_PARENT_RENAME.keys())
    for old, new in EXACT_REMAP.items():
        if old in deferred_parents:
            continue  # 親ラベル自体は Step 4 で処理
        add(old, new)

    # ── Step 3: PARENT_DEFAULT（ブランド親の残り子を一括）────────────────────
    print("\n[Step 3] ブランド親 → トピック親 一括移行（PARENT_DEFAULT）")
    for brand_parent, topic_parent in sorted(PARENT_DEFAULT.items()):
        prefix = brand_parent + "/"
        children = [n for n in label_map if n.startswith(prefix)]
        if not children:
            continue
        print(f"  📁 {brand_parent} → {topic_parent} ({len(children)}件)")
        for old in sorted(children):
            leaf = old[len(prefix):]
            new = f"{topic_parent}/{leaf}"
            if old in EXACT_REMAP:
                continue  # 既に Step 2 で処理済み
            add(old, new)

    # ── Step 4: 親ラベル自体のリネーム（最後） ────────────────────────────────
    print("\n[Step 4] バグのある親ラベル自体のリネーム")
    for old, new in TOPIC_PARENT_RENAME.items():
        add(old, new)

    return renames


def main():
    mode = "【DRY-RUN プレビュー】" if DRY_RUN else "【本番実行】⚠️  不可逆！"
    print(f"\n{'='*65}")
    print(f"  Gmail ラベル移行スクリプト（ブランド親 → トピック親）{mode}")
    print(f"{'='*65}")

    svc = get_gmail_service()
    print("✅ Gmail API 接続完了")

    label_map = fetch_all_labels(svc)
    print(f"📋 現在のラベル数: {len(label_map)}")

    renames = compute_renames(label_map)

    print(f"\n{'='*65}")
    print(f"  対象リネーム件数: {len(renames)} 件")
    print(f"{'='*65}\n")

    if not renames:
        print("移行対象ラベルが見つかりませんでした。")
        return

    if not DRY_RUN:
        confirm = input("本番実行します。よろしいですか？ (yes/no): ").strip()
        if confirm.lower() != "yes":
            print("中断しました。")
            return

    renamed = 0
    errors = 0
    for old, new, label_id in renames:
        ok = rename_label(svc, label_id, old, new)
        if ok:
            renamed += 1
        else:
            errors += 1

    print(f"\n{'='*65}")
    if DRY_RUN:
        print(f"  [DRY-RUN] 変更予定: {renamed} 件")
        print(f"  実際に変更するには --dry-run を外して実行してください。")
    else:
        print(f"  ✅ リネーム完了: {renamed} 件 / ❌ エラー: {errors} 件")
    print(f"{'='*65}\n")


if __name__ == "__main__":
    main()
