#!/usr/bin/env python3
"""
Gmailラベル分類の精度監査スクリプト（読み取り専用・破壊的操作なし）

実ラベル一覧（list_labels の JSON）と、main.py / label_consolidation.py の
ルール表（LABEL_RULES, LABEL_PARENT_MAP, RULES）を突き合わせ、
分類・統合の問題点を機械的に洗い出す。
"""

import ast
import json
import re
import sys
from collections import Counter, defaultdict

LABELS_JSON = sys.argv[1] if len(sys.argv) > 1 else "labels.json"
MAIN_PY = "main.py"
CONSOL_PY = "label_consolidation.py"


def extract_assign(path, name):
    """ソースから name = <literal> を ast で安全に取り出す。"""
    tree = ast.parse(open(path, encoding="utf-8").read())
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name) and t.id == name:
                    return ast.literal_eval(node.value)
    raise KeyError(f"{name} not found in {path}")


# ---- データ読み込み ----
labels = [l["name"] for l in json.load(open(LABELS_JSON, encoding="utf-8"))["labels"]]
label_set = set(labels)
LABEL_RULES = extract_assign(MAIN_PY, "LABEL_RULES")           # [(label, [kw,...]), ...]
LABEL_PARENT_MAP = extract_assign(MAIN_PY, "LABEL_PARENT_MAP") # [(parent, [domain,...]), ...]
RULES = extract_assign(CONSOL_PY, "RULES")                     # {parent: [child,...]}

rule_labels = {lbl for lbl, _ in LABEL_RULES}
parent_map_parents = {p for p, _ in LABEL_PARENT_MAP}
consol_parents = set(RULES.keys())
consol_children = {c for kids in RULES.values() for c in kids}


def header(n, t):
    print(f"\n{'='*70}\n[{n}] {t}\n{'='*70}")


findings = []  # (id, title, count, samples)


def record(fid, title, items, show=12):
    findings.append((fid, title, len(items)))
    header(fid, f"{title}  —  {len(items)}件")
    for x in items[:show]:
        print("   -", x)
    if len(items) > show:
        print(f"   … 他 {len(items)-show} 件")


# ===== 構造的問題 =====
# 1. 親なしフラット（未分類）ラベル
flat = sorted(x for x in labels if "/" not in x)
record(1, "親なしフラット（未分類）ラベル＝最大の取りこぼし", flat, show=30)

# 2. 親名に "/" を含む → 意図しない多段ネスト（美容/健康/… など）
slash_parents = {p for p in consol_parents if "/" in p}
depth2 = sorted(x for x in labels if x.count("/") >= 2)
record(2, "親名に'/'を含み3階層化するバグ（RULES側）", sorted(slash_parents))
record(3, "実ラベルで3階層以上になっているもの", depth2, show=20)

# 4. 子名が生メールアドレス
addr_children = sorted(x for x in labels if "@" in x)
record(4, "子/ラベル名が生メールアドレス（不可読）", addr_children, show=20)

# 5. 子名にノイズ（[送信専用]・括弧・引用符・全角空白の羅列など）
def noisy(name):
    leaf = name.split("/")[-1]
    return bool(re.search(r"\[|\]|【|】|（.*事務局|送信専用|no-?reply|noreply|support|事務局|お知らせ|株式会社|窓口", leaf, re.I))
noise_children = sorted(x for x in labels if "/" in x and noisy(x))
record(5, "子ラベル名にノイズ（事務局/送信専用/株式会社/no-reply等）", noise_children, show=25)

# ===== ブランド vs トピック 衝突 =====
BRAND_PARENTS = {"Google","Apple","Amazon","楽天","au","ドコモ","SoftBank","NTT","Sony",
    "Microsoft","Adobe","Steam","SQUARE ENIX","ニコニコ","DMM","Ameba","野村グループ",
    "焼肉きんぐ","アパホテル","Hotels.com","損保ジャパン","佐川急便","ヤマト運輸","FedEx",
    "日産","レコチョク","mora","DJI","Trip.com","AdGuard","Logicool","アイペット","カスペルスキー",
    "Ponta","ユーグレナ","モノタロウ","出前館","ソースネクスト","TeamViewer","オリックス",
    "三井住友","横浜銀行","ANA","ユニクロ","NANO universe","アルペングループ","ノジマ",
    "ビックカメラ","ZOZOTOWN","Parallels","Nintendo","SEGA","Paidy","コニカミノルタプラネタリウム"}
TOPIC_PARENTS = consol_parents - BRAND_PARENTS

# 6. ブランド親とトピック親の両方に出現しうるサービス（内容ミスマッチの温床）
#    例: 楽天/楽天証券（ブランド親）だが「銀行/証券」が妥当
brand_under_should_be_topic = []
SUSPECT = {
    "楽天/楽天証券": "金融(証券)が妥当だがブランド親 楽天 配下",
    "Sony/PlayStation": "ゲーム が妥当だがブランド親 Sony 配下",
    "Sony/PlayStation Network": "ゲーム が妥当だがブランド親 Sony 配下",
    "Google/YouTube": "動画 が妥当だがブランド親 Google 配下",
    "Google/YouTube Music": "音楽 が妥当だがブランド親 Google 配下",
    "Google/Google Play": "アプリ/ゲーム が妥当だがブランド親 Google 配下",
    "Amazon/Prime Video": "動画 が妥当だがブランド親 Amazon 配下",
    "au/GeForce NOW Powered by au": "ゲーム が妥当だが通信ブランド au 配下",
}
suspect_present = sorted(k for k in SUSPECT if k in label_set)
record(6, "ブランド親に押し込まれた“内容ミスマッチ”ラベル", [f"{k}  ← {SUSPECT[k]}" for k in suspect_present])

# 7. 同一サービスが複数の親に分散（親またぎ重複）— 葉の名前で集計
leaf_to_parents = defaultdict(set)
for x in labels:
    if "/" in x:
        parent, leaf = x.split("/", 1)
        leaf_to_parents[leaf.split("/")[0]].add(parent)
dup_leaf = sorted((leaf, sorted(ps)) for leaf, ps in leaf_to_parents.items() if len(ps) > 1)
record(7, "同じ子名が複数の親にぶら下がる（分散）", [f"{leaf}: {ps}" for leaf, ps in dup_leaf], show=20)

# ===== ルールと実体の乖離 =====
# 8. RULES の子が実ラベルに存在しない（デッドルール）
def child_exists(parent, child):
    return f"{parent}/{child}" in label_set or child in label_set
dead = sorted(f"{p}/{c}" for p, kids in RULES.items() for c in kids if not child_exists(p, c))
record(8, "RULESに定義済みだが実ラベルに無い（デッド/未到来）", dead, show=20)

# 9. RULES の親が実ラベルに存在しない（親ラベル未作成）
missing_parents = sorted(p for p in consol_parents if p not in label_set)
record(9, "RULESの親ラベルが実在しない", missing_parents, show=20)

# 10. 実フラットラベルのうち、どのルール表にも載っていない（恒久的に未分類）
covered = rule_labels | parent_map_parents | consol_parents | consol_children
uncovered_flat = sorted(x for x in flat if x not in covered)
record(10, "どのルールにも載らず永久に未分類なフラットラベル", uncovered_flat, show=40)

# 11. 単一子の親（ネストの意味が薄い）
single_child = sorted(p for p in consol_parents if len(RULES[p]) == 1)
record(11, "子が1つだけの親（ネスト不要の可能性）", single_child)

# 12. main.py と consolidation の不整合（同概念が別表記）
#     LABEL_RULES のラベル名 と RULES の親/子 の食い違い例
overlap_examples = []
for lbl in sorted(rule_labels):
    base = lbl.split("/")[-1]
    if base in consol_parents and lbl != base:
        overlap_examples.append(f"main:LABEL_RULES '{lbl}' vs consolidation親 '{base}'")
record(12, "main.pyルールと統合RULESの表記揺れ・二重定義", overlap_examples, show=20)

# ===== サマリ =====
header(0, "サマリ（findings 件数）")
print(f"  実ユーザーラベル総数: {len(labels)}")
print(f"  フラット未分類: {len(flat)}  / ルール被覆あり: {len(flat)-len(uncovered_flat)} / 永久未分類: {len(uncovered_flat)}")
print(f"  RULES親: {len(consol_parents)}（ブランド系 {len(BRAND_PARENTS & consol_parents)} / トピック系 {len(TOPIC_PARENTS)}）")
print()
for fid, title, n in findings:
    print(f"  [{fid:>2}] {n:>4}件  {title}")
