#!/usr/bin/env python3
"""
fix_all_labels.py - ラベル一括修正スクリプト

タスク:
  1. ラベルリネーム（フラット→階層化、名前修正、分類修正）
  2. 三井住友銀行の重複ラベル統合
  3. 新規中間ラベル作成（後払い、アウトドア系）

使い方:
  USE_LOCAL=1 python3 fix_all_labels.py --dry-run   # プレビューのみ
  USE_LOCAL=1 python3 fix_all_labels.py             # 本番実行

除外（絶対に変更しない）:
  EZ受信ボックス・EZ送信ボックス 配下のラベルは一切触れない。
"""

import json
import os
import sys
import time

import google.auth.transport.requests
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

DRY_RUN = "--dry-run" in sys.argv
LOCAL_CREDS_PATH = os.path.expanduser("~/.gmail_local_credentials.json")
EXCLUDE_PREFIXES = ("EZ受信ボックス", "EZ送信ボックス")

# =====================================================================
# 1) 単純リネーム  (old_name, new_name)
# =====================================================================
RENAMES = [
    # ── 宅配 ─────────────────────────────────────────
    ("宅配・物流/佐川急便株式会社",                   "宅配・物流/佐川急便"),
    # ── ショッピング ──────────────────────────────────
    ("ショッピング/AMAZON",                           "ショッピング/Amazon"),
    ("ショッピング/楽天ペイからの重要なお知らせ",       "ショッピング/楽天ペイ"),
    ("ショッピング/楽天市場からのお知らせ",             "ショッピング/楽天市場"),
    # ── 通信 ─────────────────────────────────────────
    ("通信キャリア/povo.jp",                          "通信キャリア/povo"),
    # ── ヘルス・美容 ──────────────────────────────────
    ("ヘルス・美容/株式会社MTG お客様相談室",           "ヘルス・美容/MTG"),
    # ── AI・クラウド ──────────────────────────────────
    ("AI・クラウド/Anthropic, PBC",                   "AI・クラウド/Anthropic"),
    # ── テック・アプリ ────────────────────────────────
    ("CapCut",                                        "テック・アプリ/CapCut"),
    ("Team Mapbox",                                   "AI・クラウド/Mapbox"),
    # ── ゲーム ───────────────────────────────────────
    ("ゲーム/Google Play",                            "テック・アプリ/Google Play"),
    ("IQ Booster",                                    "テック・アプリ/IQブースター"),
    ("WW IQ Test",                                    "テック・アプリ/WW IQテスト"),
    # ── 住まい ───────────────────────────────────────
    ("住設プロ 楽天市場店",                           "住まい/住設プロ"),
    # ── 子育て ───────────────────────────────────────
    ("Liberta ONLINE STORE",                          "子育て/リベルタ"),
    # ── ショッピング（海外転送） ─────────────────────
    ("Shipito",                                       "ショッピング/Shipito"),
    # ── マネー・金融 ──────────────────────────────────
    ("アットユーネット",                              "マネー・金融/クレジットカード/UCカード"),
    ("自動車・バイク/日産フィナンシャルサービス",       "マネー・金融/クレジットカード/日産カード"),
    ("マネー・金融/ペイディ",                          "マネー・金融/後払い/Paidy"),
    # 三井住友銀行（2階層版）→ 3階層へ ※重複解消はSTEP2で行う
    ("マネー・金融/三井住友銀行",                      "マネー・金融/銀行/三井住友銀行"),
]

# =====================================================================
# 2) 重複マージ  (src_label_name, dst_label_name)
#    src の全スレッドを dst に移動し、src を削除する
# =====================================================================
MERGES = [
    # フラット「三井住友銀行」→「マネー・金融/銀行/三井住友銀行」へ統合
    # ※ dst は RENAMES で先にリネームされている前提
    ("三井住友銀行",  "マネー・金融/銀行/三井住友銀行"),
]

# =====================================================================
# 3) 新規中間ラベル作成
# =====================================================================
NEW_PARENTS = [
    "マネー・金融/後払い",
    "ショッピング/アウトドア",
    "レジャー・チケット/アウトドア",
    "自動車・バイク/カー用品",
]

# =====================================================================
# ユーティリティ
# =====================================================================

def get_service():
    if os.getenv("USE_LOCAL", "0") != "1":
        print("❌ USE_LOCAL=1 が必要です。")
        sys.exit(1)
    if not os.path.exists(LOCAL_CREDS_PATH):
        print(f"❌ {LOCAL_CREDS_PATH} が見つかりません。get_local_token.py を先に実行してください。")
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
    """全ラベルを name→id と id→name の辞書で返す"""
    resp = svc.users().labels().list(userId="me").execute()
    all_labels = resp.get("labels", [])
    name2id = {l["name"]: l["id"] for l in all_labels}
    id2name = {l["id"]: l["name"] for l in all_labels}
    return name2id, id2name


def is_excluded(name):
    return any(name.startswith(p) for p in EXCLUDE_PREFIXES)


# =====================================================================
# STEP 1: リネーム
# =====================================================================

def step1_renames(svc, name2id):
    print("\n" + "="*60)
    print("STEP 1: ラベルリネーム")
    print("="*60)
    ok = err = skip = 0
    for old, new in RENAMES:
        if is_excluded(old) or is_excluded(new):
            print(f"  ⛔ SKIP (除外): {old}")
            skip += 1
            continue
        lid = name2id.get(old)
        if lid is None:
            print(f"  ⚠️  NOT FOUND: 「{old}」（スキップ）")
            skip += 1
            continue
        if new in name2id:
            print(f"  ⚠️  ALREADY EXISTS: 「{new}」（スキップ）")
            skip += 1
            continue
        print(f"  {'[DRY]' if DRY_RUN else '      '}  {old!r:55s} → {new!r}")
        if not DRY_RUN:
            try:
                svc.users().labels().patch(
                    userId="me", id=lid, body={"name": new}
                ).execute()
                name2id[new] = lid          # ローカル辞書も更新
                del name2id[old]
                ok += 1
                time.sleep(0.3)
            except Exception as e:
                print(f"    ❌ エラー: {e}")
                err += 1
        else:
            ok += 1
    print(f"\n  結果: {ok}件リネーム / {skip}件スキップ / {err}件エラー")
    return name2id


# =====================================================================
# STEP 2: 重複マージ（src → dst に全スレッドを移動 → src 削除）
# =====================================================================

def step2_merges(svc, name2id):
    print("\n" + "="*60)
    print("STEP 2: 重複ラベルマージ")
    print("="*60)
    for src_name, dst_name in MERGES:
        if is_excluded(src_name):
            print(f"  ⛔ SKIP (除外): {src_name}")
            continue
        src_id = name2id.get(src_name)
        dst_id = name2id.get(dst_name)
        if src_id is None:
            print(f"  ⚠️  src NOT FOUND: 「{src_name}」（スキップ）")
            continue
        if dst_id is None:
            print(f"  ⚠️  dst NOT FOUND: 「{dst_name}」（スキップ）")
            continue
        print(f"\n  マージ: 「{src_name}」→「{dst_name}」")

        # src ラベルのついた全スレッドを取得
        threads = []
        page_token = None
        while True:
            kwargs = {"userId": "me", "labelIds": [src_id], "maxResults": 500}
            if page_token:
                kwargs["pageToken"] = page_token
            resp = svc.users().threads().list(**kwargs).execute()
            threads.extend(resp.get("threads", []))
            page_token = resp.get("nextPageToken")
            if not page_token:
                break

        print(f"    対象スレッド: {len(threads)} 件")
        if DRY_RUN:
            print(f"    [DRY] {len(threads)}件を再ラベルし、src削除する")
            continue

        # バッチで再ラベル（add dst, remove src）
        for i, t in enumerate(threads):
            svc.users().threads().modify(
                userId="me", id=t["id"],
                body={"addLabelIds": [dst_id], "removeLabelIds": [src_id]}
            ).execute()
            if (i + 1) % 50 == 0:
                print(f"    ... {i+1}/{len(threads)}")
            time.sleep(0.1)

        # src ラベル削除
        svc.users().labels().delete(userId="me", id=src_id).execute()
        del name2id[src_name]
        print(f"    ✅ マージ完了・src削除")

    return name2id


# =====================================================================
# STEP 3: 新規中間ラベル作成
# =====================================================================

def step3_create_parents(svc, name2id):
    print("\n" + "="*60)
    print("STEP 3: 新規中間ラベル作成")
    print("="*60)
    ok = skip = err = 0
    for name in NEW_PARENTS:
        if is_excluded(name):
            print(f"  ⛔ SKIP (除外): {name}")
            skip += 1
            continue
        if name in name2id:
            print(f"  ✅ 既存: 「{name}」")
            skip += 1
            continue
        print(f"  {'[DRY]' if DRY_RUN else '      '}  作成: 「{name}」")
        if not DRY_RUN:
            try:
                result = svc.users().labels().create(
                    userId="me",
                    body={"name": name, "labelListVisibility": "labelShow",
                          "messageListVisibility": "show"}
                ).execute()
                name2id[name] = result["id"]
                ok += 1
                time.sleep(0.3)
            except Exception as e:
                print(f"    ❌ エラー: {e}")
                err += 1
        else:
            ok += 1
    print(f"\n  結果: {ok}件作成 / {skip}件スキップ / {err}件エラー")


# =====================================================================
# メイン
# =====================================================================

def main():
    if DRY_RUN:
        print("🔍 DRY RUN モード（変更なし）")
    else:
        print("🚀 本番実行モード")

    svc = get_service()
    name2id, _ = load_labels(svc)
    print(f"  ラベル総数: {len(name2id)} 件")

    name2id = step1_renames(svc, name2id)
    name2id = step2_merges(svc, name2id)
    step3_create_parents(svc, name2id)

    print("\n" + "="*60)
    if DRY_RUN:
        print("✅ DRY RUN 完了。問題なければ --dry-run を外して本番実行してください。")
    else:
        print("✅ 全処理完了。")
    print("="*60)


if __name__ == "__main__":
    main()
