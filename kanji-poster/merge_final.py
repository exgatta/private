# -*- coding: utf-8 -*-
"""検証済み読みデータをマージして final.json を確定する"""
import json, os, sys

BASE = "/tmp/claude-0/-home-user-gmail-manager/eb1b9397-4683-592b-9396-426fb1eb64d7/scratchpad"
rows = json.load(open(f"{BASE}/data/grade2_clean.json"))
order = [r["kanji"] for r in rows]

a_path = f"{BASE}/data/verify_A_checked.json"
if not os.path.exists(a_path):
    sys.exit("verify_A_checked.json がまだ無い")
A = json.load(open(a_path))
B = json.load(open(f"{BASE}/data/verify_B.json"))
merged = {**{k: v for k, v in A.items() if k != "＿issues"},
          **{k: v for k, v in B.items() if k != "＿issues"}}

assert set(merged.keys()) == set(order), (set(order) ^ set(merged.keys()))

final = []
kd = {r["kanji"]: r for r in rows}  # KANJIDIC2 (整形済み)
warn = []
for k in order:
    v = merged[k]
    # 画数はKanjiVG/KANJIDIC2と照合(第三の照合)
    if v["strokes"] != kd[k]["strokes"]:
        warn.append(f"画数不一致 {k}: verified={v['strokes']} kanjidic={kd[k]['strokes']}")
    # 検証済み読みがKANJIDIC2に存在するか(ゆるい照合: 新規追加読みの検出)
    kd_on = set(kd[k]["on"])
    kd_kun = {x.replace('.','') for x in kd[k]["kun"]}
    import unicodedata
    def hira(s):  # カタカナ→ひらがな
        return ''.join(chr(ord(c)-0x60) if 'ァ'<=c<='ヶ' else c for c in s)
    for r_, lv in v["on"]:
        if hira(r_) not in kd_on:
            warn.append(f"音読み要確認 {k}: {r_}({lv}) はKANJIDIC2に無い")
    for r_, lv in v["kun"]:
        if r_.replace('.','') not in kd_kun:
            warn.append(f"訓読み要確認 {k}: {r_}({lv}) はKANJIDIC2に無い")
    final.append({"kanji": k, "strokes": v["strokes"], "on": v["on"], "kun": v["kun"]})

json.dump(final, open(f"{BASE}/data/final.json", "w"), ensure_ascii=False, indent=1)
print("final.json written:", len(final), "kanji")
print("cross-check warnings:", len(warn))
for w in warn: print(" ", w)
