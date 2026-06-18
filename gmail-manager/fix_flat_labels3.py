#!/usr/bin/env python3
"""
fix_flat_labels3.py - 第3弾：残存フラットラベルを階層へ統合

構造（fix_all_labels2.py と同じ）:
  CLUSTER_MERGES = [(destination, [source1, source2, ...]), ...]
  - destination が存在しない → 自動作成
  - 各 source のスレッドを destination に移動後、source を削除
  - source が存在しない → スキップ（エラーにしない）

各 source は inspect_flat_labels.py で送信元ドメインをサンプリングし、
単一ブランドと確認済みのものだけを対象にしている。

絶対に変更しない（二重ガード）:
  - EZ受信ボックス / EZ送信ボックス 配下
  - 「重要なお知らせメール」(au-cs.ezweb.ne.jp 由来。EZ系と混在の恐れ)
  - 個人名・メールアドレス名ラベル（そもそもリストに入れない）

使い方:
  USE_LOCAL=1 python3 fix_flat_labels3.py --dry-run   # プレビュー
  USE_LOCAL=1 python3 fix_flat_labels3.py             # 本番実行
"""

import json, os, sys, time
import google.auth.transport.requests
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

DRY_RUN = "--dry-run" in sys.argv
LOCAL_CREDS_PATH = os.path.expanduser("~/.gmail_local_credentials.json")
EXCLUDE_PREFIXES = ("EZ受信ボックス", "EZ送信ボックス")
# EZ/au系と混在の恐れがあるため絶対に触らない
EXTRA_PROTECT = {"重要なお知らせメール"}

# =====================================================================
# CLUSTER_MERGES: (destination, [sources...])
# =====================================================================
CLUSTER_MERGES = [

    # ── テック・アプリ ──────────────────────────────────────────
    ("テック・アプリ/Acronis", ["com"]),                       # acronis.com.sg
    ("テック・アプリ/Panasonic", ["CustomerCare"]),            # panasonic.aero
    ("テック・アプリ/OtterBox", [
        "OtterBox", "Otterbox APAC", "Otterbox Customer Service"]),
    ("テック・アプリ/Box", ["Box"]),                            # box.com
    ("テック・アプリ/Epson", ["epson", "epsonconnect"]),
    ("テック・アプリ/goo", ["goo事務局", "マルシェル by goo"]),
    ("テック・アプリ/bizocean", ["bizocean事務局"]),
    ("テック・アプリ/UNiCASE", ["UNiCASE"]),                    # unicase.jp
    ("テック・アプリ/MobiSystems", ["MobiSystems"]),
    ("テック・アプリ/MapFan", ["mapfan"]),
    ("テック・アプリ/ExpanDrive", ["ExpanDrive"]),
    ("テック・アプリ/写真整理協会", ["写真整理協会"]),
    ("テック・アプリ/Plimus", ["Plimus Sales", "plimus"]),
    ("テック・アプリ/Revo Uninstaller", ["revouninstaller"]),
    ("テック・アプリ/NETGEAR", ["netgear"]),

    # ── ショッピング ────────────────────────────────────────────
    ("ショッピング/インフォトップ", ["インフォトップ", "株式会社インフォトップ"]),
    ("ショッピング/Giftpad", ["Giftpad"]),
    ("ショッピング/RIMOWA", ["RIMOWA"]),
    ("ショッピング/ニトリ", ["nitori"]),
    ("ショッピング/MATSUSHITA LUGGAGE", ["MATSUSHITA LUGGAGE Online Store"]),
    ("ショッピング/aucfan", ["aucfan"]),                        # aucfan.com
    ("ショッピング/トイザらス", ["Toys“R”Us Japan"]),
    ("ショッピング/TUMI", ["tumi", "Tumi e-Receipts"]),
    ("ショッピング/ポケモンセンターオンライン", ["pokemoncenter-online"]),
    ("ショッピング/三井ショッピングパーク", ["mitsui-shopping-park"]),
    ("ショッピング/ファッション/ヴァンドーム青山", [
        "ヴァンドーム青山オンラインショップ",
        "ヴァンドームジュエリーオンラインストア",
        "VendomeAoyama|ヴァンドーム青山 オンラインショップ"]),

    # ── グルメ ──────────────────────────────────────────────────
    ("グルメ/TableCheck", ["TableCheck"]),
    ("グルメ/ハウス食品", ["everyHOUSE ハウス食品公式オンラインショップ"]),
    ("グルメ/yoyakuru", ["yoyakuru"]),                         # yoyakuru.net

    # ── マネー・金融 ────────────────────────────────────────────
    ("マネー・金融/家計/PayB", ["PayBからのお知らせ"]),
    ("マネー・金融/家計/ARIGATO", ["ARIGATO ID"]),
    ("マネー・金融/仮想通貨/Zealy", ["Zealy"]),
    ("マネー・金融/クレジットカード/STOREE SAISON", ["STOREE SAISON（ストーリー セゾン）"]),

    # ── 保険 ────────────────────────────────────────────────────
    ("保険/SOMPOワランティ", ["SOMPOワランティ（延長保証運営会社）"]),
    ("保険/損保ジャパン", ["dga"]),                            # sjnk-form.dga.jp

    # ── 医療 ────────────────────────────────────────────────────
    ("医療/健診", ["apap"]),                                    # apap.jp
    ("医療/MRSO", ["mrso"]),                                    # mrso.jp

    # ── ゲーム ──────────────────────────────────────────────────
    ("ゲーム/GeForce NOW", ["whitecloud"]),                    # whitecloud.jp (au)
    ("ゲーム/FgGファンクラブ", ["FgGファンクラブ運営事務局"]),

    # ── エンタメ配信 ────────────────────────────────────────────
    ("エンタメ配信/音楽配信/Qobuz", ["Xandrie Japan"]),
    ("エンタメ配信/電子書籍/bookend", ["bookend サービス"]),

    # ── 旅行 ────────────────────────────────────────────────────
    ("旅行/じゃらん×ホットペッパー", [
        "[じゃらん×ホットペッパー]",
        "じゃらん×ホットペッパー新着ニュース",
        "じゃらん×ホットペッパー＆ファッション通販ERUCA"]),
    ("旅行/ホテル/SPG", ["Starwood Preferred Guest", "Starwood Prefered Guest"]),

    # ── レジャー・チケット ──────────────────────────────────────
    ("レジャー・チケット/チケット/JAM ID", ["jam-id"]),        # jam-id.jp
    ("レジャー・チケット/レジャー/steach", ["steach"]),         # steach.jp (スキーレッスン)

    # ── 自動車・バイク ──────────────────────────────────────────
    ("自動車・バイク/ユピテル", ["ユピテルity.クラブ", "Yupiteruダイレクト本店"]),
    ("自動車・バイク/カー用品/カーメイト", [
        "カーメイトくらぶ", "【カーメイト】保証登録", "【カーメイトくらぶ】"]),
    ("自動車・バイク/バイク/BAS", ["BAS SHOP"]),               # bas-bike.jp

    # ── 宅配・物流 ──────────────────────────────────────────────
    ("宅配・物流/フルタイムシステム", [
        "fulltimesystem", "フルタイムシステム", "宅配ロッカー フルタイムシステム"]),
    ("宅配・物流/日本郵便", ["yubin-info"]),                    # ml.post.japanpost.jp

    # ── 子育て ──────────────────────────────────────────────────
    ("子育て/クーカン", ["クーカンネットショップ", "クーカンネットショップ 本店"]),
    ("子育て/Niantic Kids", ["Niantic Kids Parent Portal"]),
    ("子育て/サンキュ！オンラインレッスン", ["サンキュ！オンラインレッスン事務局"]),

    # ── 行政 ────────────────────────────────────────────────────
    ("行政/オンライン手続き", ["go"]),                          # naltec.go.jp 車検 + e-survey.go.jp
]

# =====================================================================
# ユーティリティ（fix_all_labels2.py と同一）
# =====================================================================

def get_service():
    if os.getenv("USE_LOCAL", "0") != "1":
        print("❌ USE_LOCAL=1 が必要です。")
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


def load_labels(svc):
    resp = svc.users().labels().list(userId="me").execute()
    return {l["name"]: l["id"] for l in resp.get("labels", [])}


def is_excluded(name):
    if name in EXTRA_PROTECT:
        return True
    return any(name.startswith(p) for p in EXCLUDE_PREFIXES)


def ensure_label(svc, name2id, name):
    if name in name2id:
        return name2id[name]
    if DRY_RUN:
        print(f"    [DRY] 作成: 「{name}」")
        name2id[name] = f"DRY_{name}"
        return name2id[name]
    try:
        result = svc.users().labels().create(
            userId="me",
            body={"name": name,
                  "labelListVisibility": "labelShow",
                  "messageListVisibility": "show"}
        ).execute()
        name2id[name] = result["id"]
        print(f"    ✅ 作成: 「{name}」")
        time.sleep(0.3)
        return result["id"]
    except Exception as e:
        if "409" in str(e) or "exists" in str(e).lower():
            resp = svc.users().labels().list(userId="me").execute()
            for lbl in resp.get("labels", []):
                name2id[lbl["name"]] = lbl["id"]
            if name in name2id:
                print(f"    ✅ 既存: 「{name}」(ID再取得)")
                return name2id[name]
            name_lower = name.lower().strip()
            for lbl_name, lbl_id in name2id.items():
                if lbl_name.lower().strip() == name_lower:
                    print(f"    ✅ 既存(緩いマッチ): 「{lbl_name}」")
                    name2id[name] = lbl_id
                    return lbl_id
            print(f"    ⚠️  作成できず(409)、スキップ: 「{name}」")
            return None
        raise


def merge_label(svc, name2id, src_name, dst_id):
    src_id = name2id.get(src_name)
    if src_id is None:
        print(f"    ⚠️  NOT FOUND (スキップ): 「{src_name}」")
        return 0

    threads = []
    page_token = None
    while True:
        kwargs = {"userId": "me", "labelIds": [src_id], "maxResults": 500}
        if page_token:
            kwargs["pageToken"] = page_token
        try:
            resp = svc.users().threads().list(**kwargs).execute()
        except Exception as e:
            print(f"    ❌ threads.list error: {e}")
            break
        threads.extend(resp.get("threads", []))
        page_token = resp.get("nextPageToken")
        if not page_token:
            break

    print(f"    {'[DRY]' if DRY_RUN else '      '} 「{src_name}」→ {len(threads)}件移動 → 削除")
    if DRY_RUN:
        del name2id[src_name]
        return len(threads)

    for i, t in enumerate(threads):
        try:
            svc.users().threads().modify(
                userId="me", id=t["id"],
                body={"addLabelIds": [dst_id], "removeLabelIds": [src_id]}
            ).execute()
        except Exception as e:
            print(f"      ❌ thread修正エラー: {e}")
        if (i + 1) % 100 == 0:
            print(f"      ... {i+1}/{len(threads)}")
        time.sleep(0.05)

    try:
        svc.users().labels().delete(userId="me", id=src_id).execute()
        del name2id[src_name]
    except Exception as e:
        print(f"    ❌ ラベル削除エラー: {e}")

    return len(threads)


# =====================================================================
# メイン
# =====================================================================

def main():
    print("🔍 DRY RUN モード（変更なし）" if DRY_RUN else "🚀 本番実行モード")

    svc = get_service()
    name2id = load_labels(svc)
    print(f"  ラベル総数: {len(name2id)} 件\n")

    total_merged = 0
    total_threads = 0

    for dst_name, sources in CLUSTER_MERGES:
        if is_excluded(dst_name):
            print(f"  ⛔ 除外: {dst_name}")
            continue

        valid_sources = [s for s in sources if s in name2id and not is_excluded(s)]
        if not valid_sources:
            continue

        print(f"\n  ── {dst_name} ──")
        dst_id = ensure_label(svc, name2id, dst_name)
        if dst_id is None:
            print(f"    ❌ 宛先ラベル取得失敗、このクラスタをスキップ")
            continue

        for src_name in valid_sources:
            n = merge_label(svc, name2id, src_name, dst_id)
            total_threads += n
            total_merged += 1
        time.sleep(0.2)

    print(f"\n{'='*60}")
    if DRY_RUN:
        print(f"✅ DRY RUN 完了: {total_merged}ラベルを統合予定 / 約{total_threads}スレッド移動予定")
        print("問題なければ --dry-run を外して本番実行してください。")
    else:
        print(f"✅ 完了: {total_merged}ラベルを統合 / {total_threads}スレッド移動")
    print("="*60)


if __name__ == "__main__":
    main()
