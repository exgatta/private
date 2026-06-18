#!/usr/bin/env python3
"""
label_healthcheck.py - ラベル構造の総点検。
  1) 欠けている親ラベル（ツリー崩れ）
  2) 大文字小文字違いの重複
  3) 正規化(空白除去)で衝突するラベル
  4) 空(0件)のリーフラベル ※親は除外
  5) 名前の異常（前後空白・制御文字・スラッシュ多用）
  6) サマリ（総数・トップレベル別・フラット数）

USE_LOCAL=1 python3 -u label_healthcheck.py
"""
import json, os, re, unicodedata
from collections import defaultdict
import google.auth.transport.requests
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

CR = os.path.expanduser("~/.gmail_local_credentials.json")
SYS = {"INBOX","SENT","DRAFT","SPAM","TRASH","UNREAD","STARRED","IMPORTANT","CHAT"}


def svc_():
    d = json.load(open(CR))
    c = Credentials(token=d.get("token"), refresh_token=d["refresh_token"],
        token_uri=d.get("token_uri", "https://oauth2.googleapis.com/token"),
        client_id=d["client_id"], client_secret=d["client_secret"])
    if not c.valid: c.refresh(google.auth.transport.requests.Request())
    return build("gmail", "v1", credentials=c, cache_discovery=False)


def retry(fn, t=4):
    import time
    for a in range(t):
        try: return fn()
        except Exception as e:
            if a == t-1: raise
            time.sleep(1.2*(a+1))


def main():
    s = svc_()
    L = s.users().labels().list(userId="me").execute().get("labels", [])
    user = [l for l in L if l["name"] not in SYS and not l["name"].startswith("CATEGORY_")]
    names = [l["name"] for l in user]
    nameset = set(names)
    n2i = {l["name"]: l["id"] for l in user}
    print(f"ユーザーラベル総数: {len(user)}\n", flush=True)

    # 1) 欠け親
    missing = set()
    for n in names:
        p = n.split("/")
        for i in range(1, len(p)):
            anc = "/".join(p[:i])
            if anc not in nameset:
                missing.add(anc)
    print(f"【1】欠けている親ラベル: {len(missing)}", flush=True)
    for m in sorted(missing): print(f"    ✗ {m}", flush=True)
    if not missing: print("    → なし（ツリー完全）", flush=True)

    # 2) 大文字小文字違い重複
    low = defaultdict(list)
    for n in names: low[n.lower()].append(n)
    dup = {k: v for k, v in low.items() if len(v) > 1}
    print(f"\n【2】大文字小文字違いの重複: {len(dup)}", flush=True)
    for k, v in dup.items(): print(f"    ⚠ {v}", flush=True)
    if not dup: print("    → なし", flush=True)

    # 3) 正規化衝突（空白・全半角除去, lower）
    norm = defaultdict(list)
    for n in names:
        key = unicodedata.normalize("NFKC", n).replace(" ", "").replace("　", "").lower()
        norm[key].append(n)
    ncol = {k: v for k, v in norm.items() if len(v) > 1 and v not in dup.values()}
    print(f"\n【3】正規化で衝突する紛らわしいラベル: {len(ncol)}", flush=True)
    for k, v in ncol.items(): print(f"    ⚠ {v}", flush=True)
    if not ncol: print("    → なし", flush=True)

    # 4) 名前異常
    odd = []
    for n in names:
        if n != n.strip(): odd.append((n, "前後に空白"))
        elif re.search(r"[\x00-\x1f]", n): odd.append((n, "制御文字"))
        elif n.endswith("/") or "//" in n: odd.append((n, "スラッシュ異常"))
    print(f"\n【4】名前の異常: {len(odd)}", flush=True)
    for n, why in odd: print(f"    ⚠ 「{n}」({why})", flush=True)
    if not odd: print("    → なし", flush=True)

    # 5) 空リーフ（親でない & messagesTotal==0）
    is_parent = lambda n: any(o.startswith(n + "/") for o in names)
    print(f"\n【5】空(0件)のリーフラベルを確認中...", flush=True)
    empties = []
    leaves = [n for n in names if not is_parent(n)]
    for i, n in enumerate(leaves, 1):
        tot = retry(lambda: s.users().labels().get(userId="me", id=n2i[n]).execute()).get("messagesTotal", 0)
        if tot == 0:
            empties.append(n)
        if i % 200 == 0:
            print(f"    ...{i}/{len(leaves)}", flush=True)
    print(f"【5】空リーフ: {len(empties)}", flush=True)
    for n in sorted(empties): print(f"    ○ {n}", flush=True)
    if not empties: print("    → なし", flush=True)

    # 6) サマリ
    tops = defaultdict(int)
    for n in names: tops[n.split("/")[0]] += 1
    flats = [n for n in names if "/" not in n and not is_parent(n)]
    print(f"\n【6】サマリ", flush=True)
    print(f"    トップレベルカテゴリ: {len([t for t in tops if '/' not in t])}", flush=True)
    print(f"    まだ階層化されていないフラットラベル: {len(flats)}", flush=True)
    for t, c in sorted(tops.items(), key=lambda x: -x[1])[:30]:
        print(f"      {c:>4}  {t}", flush=True)


if __name__ == "__main__":
    main()
