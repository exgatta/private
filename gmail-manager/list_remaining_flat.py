#!/usr/bin/env python3
"""
list_remaining_flat.py - 整理後に残っているフラットラベルを一覧化。
co / gmail は中身(送信元ドメイン＋件名)を全件表示して振り分け判断に使う。
"""
import json, os, re
import google.auth.transport.requests
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

CR = os.path.expanduser("~/.gmail_local_credentials.json")
SYS = {"INBOX","SENT","DRAFT","SPAM","TRASH","UNREAD","STARRED","IMPORTANT","CHAT"}
EZ = {"EZ受信ボックス","EZ送信ボックス"}


def svc_():
    d=json.load(open(CR))
    c=Credentials(token=d.get("token"),refresh_token=d["refresh_token"],
        token_uri=d.get("token_uri","https://oauth2.googleapis.com/token"),
        client_id=d["client_id"],client_secret=d["client_secret"])
    if not c.valid: c.refresh(google.auth.transport.requests.Request())
    return build("gmail","v1",credentials=c,cache_discovery=False)


def dom(f):
    m=re.search(r"[\w.\-+]+@([\w.\-]+)", f or ""); return m.group(1).lower() if m else "?"


def main():
    s=svc_()
    L=s.users().labels().list(userId="me").execute().get("labels",[])
    names=[l["name"] for l in L]; n2i={l["name"]:l["id"] for l in L}
    parent=lambda n: any(o.startswith(n+"/") for o in names)
    flats=[n for n in names if "/" not in n and n not in SYS and not n.startswith("CATEGORY_")
           and n not in EZ and not parent(n)]
    print(f"残フラットラベル: {len(flats)}\n")
    # 件数つき一覧
    for n in sorted(flats):
        t=s.users().labels().get(userId="me",id=n2i[n]).execute().get("messagesTotal","?")
        mark=" (@アドレス)" if "@" in n else ""
        print(f"  [{t:>4}] {n}{mark}")

    # co / gmail の中身詳細
    for tgt in ["co","gmail"]:
        if tgt not in n2i:
            print(f"\n##### {tgt}: なし"); continue
        print(f"\n##### 「{tgt}」全件 #####")
        ids,page=[],None
        while True:
            kw={"userId":"me","labelIds":[n2i[tgt]],"maxResults":500}
            if page: kw["pageToken"]=page
            r=s.users().messages().list(**kw).execute()
            ids+=[m["id"] for m in r.get("messages",[])]; page=r.get("nextPageToken")
            if not page: break
        for mid in ids:
            md=s.users().messages().get(userId="me",id=mid,format="metadata",
                metadataHeaders=["From","Subject"]).execute()
            hs={h["name"]:h["value"] for h in md.get("payload",{}).get("headers",[])}
            print(f"  {dom(hs.get('From','')):<26} | {hs.get('Subject','')[:48]}")


if __name__=="__main__":
    main()
