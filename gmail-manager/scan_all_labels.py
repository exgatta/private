#!/usr/bin/env python3
"""
scan_all_labels.py - 全ラベル内のメール送信者・件名・スニペットをスキャン

出力:
  - scan_results.json  : 全ラベル × 送信者ドメインのマッピング
  - scan_report.txt    : 人間が読みやすいレポート

使い方:
  USE_LOCAL=1 python3 scan_all_labels.py
"""

import json, os, sys, time, re, base64
from collections import defaultdict

import google.auth.transport.requests
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

LOCAL_CREDS_PATH = os.path.expanduser("~/.gmail_local_credentials.json")
EXCLUDE_PREFIXES = ("EZ受信ボックス", "EZ送信ボックス")
MAX_THREADS_PER_LABEL = 30   # 1ラベルあたり最大取得スレッド数
OUTPUT_JSON = "/Users/macuser/gmail_function/scan_results.json"
OUTPUT_TXT  = "/Users/macuser/gmail_function/scan_report.txt"

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

def extract_domain(email_str):
    """メールアドレスからドメインを抽出"""
    m = re.search(r'<(.+?)>', email_str)
    addr = m.group(1) if m else email_str.strip()
    if '@' in addr:
        return addr.split('@')[-1].lower().strip('>')
    return addr.lower()

def get_threads_for_label(svc, label_id, max_threads=MAX_THREADS_PER_LABEL):
    threads = []
    page_token = None
    while len(threads) < max_threads:
        kwargs = {"userId": "me", "labelIds": [label_id],
                  "maxResults": min(50, max_threads - len(threads))}
        if page_token:
            kwargs["pageToken"] = page_token
        try:
            resp = svc.users().threads().list(**kwargs).execute()
        except Exception as e:
            print(f"    ⚠️  threads.list error: {e}")
            break
        threads.extend(resp.get("threads", []))
        page_token = resp.get("nextPageToken")
        if not page_token:
            break
    return threads

def get_message_headers(svc, msg_id):
    """メッセージのヘッダー(From, Subject)とスニペットを取得"""
    try:
        msg = svc.users().messages().get(
            userId="me", id=msg_id,
            format="metadata",
            metadataHeaders=["From", "Subject"]
        ).execute()
        headers = {h["name"]: h["value"] for h in msg.get("payload", {}).get("headers", [])}
        return {
            "from": headers.get("From", ""),
            "subject": headers.get("Subject", ""),
            "snippet": msg.get("snippet", "")
        }
    except Exception:
        return None

def main():
    svc = get_service()

    # 全ラベル取得
    resp = svc.users().labels().list(userId="me").execute()
    all_labels = resp.get("labels", [])
    user_labels = [l for l in all_labels
                   if l.get("type") == "user"
                   and not any(l["name"].startswith(p) for p in EXCLUDE_PREFIXES)]

    print(f"スキャン対象ラベル: {len(user_labels)} 件")

    results = {}   # label_name -> { "id": ..., "threads_total": ..., "senders": [...] }
    domain_to_labels = defaultdict(set)  # domain -> set of label names

    for i, label in enumerate(user_labels):
        name = label["name"]
        lid  = label["id"]
        depth = name.count("/")
        sys.stdout.write(f"\r  [{i+1}/{len(user_labels)}] {name[:60]:<60}")
        sys.stdout.flush()

        # フラットかつ個人連絡先っぽいもの（英数字のみ短いもの）はスキップしてもよいが
        # ユーザー要求なので全部スキャン

        threads = get_threads_for_label(svc, lid, MAX_THREADS_PER_LABEL)
        if not threads:
            results[name] = {"id": lid, "depth": depth, "thread_count": 0, "senders": []}
            continue

        senders = []
        for t in threads[:MAX_THREADS_PER_LABEL]:
            # スレッドの最初のメッセージIDを使う
            thread_id = t["id"]
            try:
                t_detail = svc.users().threads().get(
                    userId="me", id=thread_id,
                    format="metadata",
                    metadataHeaders=["From", "Subject"]
                ).execute()
                msgs = t_detail.get("messages", [])
                if msgs:
                    hdrs = {h["name"]: h["value"]
                            for h in msgs[0].get("payload", {}).get("headers", [])}
                    frm = hdrs.get("From", "")
                    subj = hdrs.get("Subject", "")[:80]
                    snippet = msgs[0].get("snippet", "")[:120]
                    domain = extract_domain(frm)
                    senders.append({
                        "from": frm[:80],
                        "domain": domain,
                        "subject": subj,
                        "snippet": snippet
                    })
                    domain_to_labels[domain].add(name)
            except Exception:
                pass
            time.sleep(0.05)

        results[name] = {
            "id": lid,
            "depth": depth,
            "thread_count": len(threads),
            "senders": senders
        }
        time.sleep(0.1)

    print()
    print("JSON保存中...")
    with open(OUTPUT_JSON, "w", encoding="utf-8") as f:
        json.dump({
            "labels": results,
            "domain_to_labels": {k: sorted(v) for k, v in domain_to_labels.items()}
        }, f, ensure_ascii=False, indent=2)

    # ── レポート生成 ──
    print("レポート生成中...")
    lines = []
    lines.append("="*70)
    lines.append("Gmail全ラベル スキャンレポート")
    lines.append("="*70)
    lines.append("")

    # 1) 同一ドメインが複数ラベルにまたがる → マージ候補
    lines.append("【A】同一ドメインが複数ラベルに存在（マージ候補）")
    lines.append("-"*60)
    multi = {d: labs for d, labs in domain_to_labels.items()
             if len(labs) > 1
             and not any("EZ" in l for l in labs)}
    for domain in sorted(multi.keys()):
        labs = sorted(multi[domain])
        lines.append(f"  {domain}")
        for l in labs:
            lines.append(f"    → {l}")
    lines.append("")

    # 2) スレッド数0のラベル（空ラベル）
    lines.append("【B】スレッド数0の空ラベル")
    lines.append("-"*60)
    empty = [n for n, v in results.items() if v["thread_count"] == 0]
    for n in sorted(empty):
        lines.append(f"  {n}")
    lines.append("")

    # 3) フラットラベル(depth=0)のスキャン結果
    lines.append("【C】フラットラベル内の送信者ドメイン（階層化候補）")
    lines.append("-"*60)
    flat_results = {n: v for n, v in results.items() if v["depth"] == 0 and v["thread_count"] > 0}
    for n in sorted(flat_results.keys()):
        v = flat_results[n]
        domains = sorted(set(s["domain"] for s in v["senders"]))
        lines.append(f"  [{v['thread_count']}件] {n}")
        for s in v["senders"][:3]:
            lines.append(f"    From: {s['from'][:60]}")
            lines.append(f"    件名: {s['subject'][:60]}")
            lines.append(f"    ---")
    lines.append("")

    # 4) 2階層ラベルの詳細（主要カテゴリ）
    lines.append("【D】2階層ラベル ドメイン詳細")
    lines.append("-"*60)
    two_results = {n: v for n, v in results.items() if v["depth"] == 1 and v["thread_count"] > 0}
    for n in sorted(two_results.keys()):
        v = two_results[n]
        domains = sorted(set(s["domain"] for s in v["senders"]))
        lines.append(f"  [{v['thread_count']}件] {n}")
        for d in domains:
            lines.append(f"    domain: {d}")

    with open(OUTPUT_TXT, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    print(f"\n✅ 完了")
    print(f"  JSON: {OUTPUT_JSON}")
    print(f"  TXT:  {OUTPUT_TXT}")

if __name__ == "__main__":
    main()
