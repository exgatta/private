#!/usr/bin/env python3
"""
rename_to_kojin.py - 私信(個人)ラベルを「個人/○○」へリネームして集約。

リネーム(labels.patch)なのでメール移動なし・各人の区別を保持。
標準の「個人」親ラベルも作成してツリーに表示。

USE_LOCAL=1 python3 -u rename_to_kojin.py --dry-run
USE_LOCAL=1 python3 -u rename_to_kojin.py
"""
import json, os, sys, time
import google.auth.transport.requests
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

DRY = "--dry-run" in sys.argv
CR = os.path.expanduser("~/.gmail_local_credentials.json")

PERSONAL = [
    "片岡 秀一郎", "片岡秀一郎", "秀一郎片岡",          # ご自身
    "Kataoka hideaki", "Hideaki kataoka", "qjican@gmail.com",  # お父様
    "S Kataoka", "takayo kataoka", "長谷部友子", "須藤 亜紀子",  # ご家族
    "Tommy", "ishida", "ishiharaju", "kult koruku", "T.koyasu",
    "三浦 淳史", "カウンセラー伊藤", "さいか (Twitter)",
    "ぷりちぃなぁご", "恵那警察署", "Sakai", "坂井作",
]


def svc_():
    if os.getenv("USE_LOCAL", "0") != "1":
        print("❌ USE_LOCAL=1 が必要"); sys.exit(1)
    d = json.load(open(CR))
    c = Credentials(token=d.get("token"), refresh_token=d["refresh_token"],
        token_uri=d.get("token_uri", "https://oauth2.googleapis.com/token"),
        client_id=d["client_id"], client_secret=d["client_secret"])
    if not c.valid: c.refresh(google.auth.transport.requests.Request())
    return build("gmail", "v1", credentials=c, cache_discovery=False)


def main():
    print("🔍 DRY" if DRY else "🚀 本番", "（個人ラベルを 個人/ 配下へ集約）\n", flush=True)
    svc = svc_()
    n2i = {l["name"]: l["id"] for l in svc.users().labels().list(userId="me").execute().get("labels", [])}

    # 親「個人」を作成
    if "個人" not in n2i:
        if DRY:
            print("  [DRY] 作成: 個人", flush=True)
        else:
            r = svc.users().labels().create(userId="me", body={"name": "個人",
                "labelListVisibility": "labelShow", "messageListVisibility": "show"}).execute()
            n2i["個人"] = r["id"]; print("  ✅ 親作成: 個人", flush=True); time.sleep(0.2)

    done = 0
    for name in PERSONAL:
        if name not in n2i:
            print(f"  ・無し: {name}", flush=True); continue
        new = f"個人/{name}"
        if new in n2i:
            print(f"  ・既存衝突スキップ: {new}", flush=True); continue
        print(f"  {'[DRY] ' if DRY else ''}{name} → {new}", flush=True)
        if not DRY:
            svc.users().labels().patch(userId="me", id=n2i[name], body={"name": new}).execute()
            done += 1; time.sleep(0.2)

    print(f"\n{'[DRY] ' if DRY else ''}個人配下へ集約: {done if not DRY else len(PERSONAL)} ラベル", flush=True)


if __name__ == "__main__":
    main()
