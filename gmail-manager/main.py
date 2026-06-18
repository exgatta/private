"""
Gmail自動管理 - Google Cloud Run Jobs
- 受信トレイ全件（既読・未読）処理
- メルマガはList-Unsubscribeで配信停止してから削除
- 既存ラベルも全件チェックして同様に処理
- ラベル削除時はGmail側の自動仕分けフィルターも削除
- SSL切断時に自動再接続
- Cloud Run Jobs: 時間制限なし（最大24時間）
"""

import email
import email.mime.text
from email.header import decode_header
from google.cloud import secretmanager
from imapclient import IMAPClient
import json
import os
import re
import smtplib
import time
import urllib.request
import urllib.parse

EMAIL                    = "exgatta@gmail.com"
PROJECT_ID               = os.environ.get("GCP_PROJECT", "")
SECRET_NAME              = "gmail-app-password"
OAUTH_CREDENTIALS_SECRET = "gmail-oauth-credentials"
BATCH_SIZE               = 100
RECONNECT_EVERY          = 20  # N バッチごとに再接続（= 2000件ごと）

# DRY-RUN: 真のとき削除・移動などの破壊的操作を実行せず、ログ出力のみ行う。
# Cloud Run 実行時に環境変数 DRY_RUN=1 で有効化し、削除のブラスト半径を事前確認する用途。
DRY_RUN = os.environ.get("DRY_RUN", "0").strip().lower() in ("1", "true", "yes", "on")


# ===== 絶対に削除しないホワイトリスト =====
WHITELIST_DOMAINS = [
    "google.com", "gmail.com", "googlemail.com",
    "apple.com", "icloud.com",
]

# ===== 削除対象（メルマガ・営業メール）=====
DELETE_SENDERS = [
    "career-info@nikkeihr.co.jp",
    "noreply@bizreach.co.jp",
    "noreply.news@e-mail.hoyoverse.com",
    "news@montbell.com",
    "point-notice-w@pointcard.rakuten.co.jp",
    "member@jalan.net",
    "noreply@kabuand.com",
    "infoc@emails.povo.jp",
]

# ===== ラベル振り分けルール =====
LABEL_RULES = [
    ("転職",                                ["bizreach.co.jp", "nikkeihr.co.jp", "doda.jp", "rikunabi", "mynavi",
                                           "r-agent.com"]),
    # 旅行
    ("旅行/ANA",                            ["ana.co.jp"]),
    ("旅行/JAL",                            ["jal.co.jp", "jal.com"]),
    ("旅行/SKYMARK",                        ["skymark.co.jp"]),
    ("旅行/Jetstar",                        ["jetstar.com"]),
    ("旅行/予約/じゃらん",                   ["jalan.net"]),
    ("旅行/JTB",                            ["jtb.co.jp"]),
    ("旅行/マリオット",                     ["marriott.com"]),
    ("旅行/Hilton",                         ["hilton.com"]),
    ("旅行/IHG",                            ["ihg.com", "points-mail.com"]),
    ("旅行/Skyscanner",                     ["skyscanner.com", "sender.skyscanner.com"]),
    ("旅行/ニッポンレンタカー",             ["nipponrentacar"]),
    ("旅行/オリックスレンタカー",           ["orix-rentacar"]),
    # 交通・移動
    ("交通・移動/えきねっと",               ["eki-net.com"]),
    ("交通・移動/小田急",                   ["odakyu.jp"]),
    ("交通・移動/ETC",                      ["etc-meisai", "highway.co.jp"]),
    # レジャー・チケット
    ("レジャー・チケット/チケットぴあ",     ["pia.co.jp"]),
    ("レジャー・チケット/asoview",          ["asoview.com"]),
    # グルメ
    ("グルメ/HOT PEPPER Beauty",            ["hotpepper.jp"]),
    ("グルメ/EPARK",                        ["justpass.epark.jp", "epark.jp"]),
    ("グルメ/KFC",                          ["ml.club.kfc.co.jp", "kfc.co.jp"]),
    # マネー・金融 - 銀行
    ("マネー・金融/三菱UFJ銀行",            ["mufg.jp", "bk.mufg.jp"]),
    ("マネー・金融/みずほ銀行",             ["mizuhobank.co.jp"]),
    ("マネー・金融/銀行/三井住友銀行",      ["smbc.co.jp", "dn.smbc.co.jp"]),
    ("マネー・金融/銀行/楽天銀行",          ["rakuten-bank.co.jp"]),
    # マネー・金融 - 証券
    ("マネー・金融/野村証券",               ["nomura.co.jp"]),
    ("マネー・金融/楽天証券",               ["rakuten-sec.co.jp"]),
    ("マネー・金融/bitflyer",               ["bitflyer.com", "bitflyer.jp"]),
    ("マネー・金融/仮想通貨/コインチェック",["coincheck.com"]),
    # マネー・金融 - 家計・管理
    ("マネー・金融/MoneyForward",           ["moneyforward.com"]),
    ("マネー・金融/MoneySense",             ["moneysense"]),
    # マネー・金融 - クレジットカード
    ("マネー・金融/クレジットカード/アメックス",    ["americanexpress.com", "amex.co.jp"]),
    ("マネー・金融/クレジットカード/JCB",           ["jcb.co.jp"]),
    ("マネー・金融/クレジットカード/三井住友カード", ["smbc-card.com", "vpass.ne.jp"]),
    ("マネー・金融/クレジットカード/UCカード",       ["uccard.co.jp", "mail.uccard.co.jp"]),
    ("マネー・金融/クレジットカード/日産カード",     ["nissan-fs.co.jp"]),
    ("マネー・金融/クレジットカード/paypal",         ["paypal.com", "paypal.co.jp", "service.paypal.com"]),
    # マネー・金融 - その他
    ("マネー・金融/カブアンド",             ["kabuand.com"]),
    # ショッピング
    ("ショッピング/Amazon",                 ["amazon.co.jp", "amazon.com"]),
    ("ショッピング/ヤフオク",               ["yahoo.co.jp"]),
    ("ショッピング/RIMOWA",                 ["rimowa.com"]),
    ("ショッピング/ファッション",           ["united-arrows", "beams.co.jp"]),
    ("ショッピング/ファッション/タカキュー", ["taka-q.jp", "taka-q.com"]),
    ("ショッピング/ファッション/L.L.Bean",  ["llbi.co.jp", "llbean.co.jp"]),
    ("ショッピング/楽天リーベイツ",          ["emails.rebates.jp"]),
    ("ショッピング/Shipito",                ["shipito.com"]),
    ("ショッピング/DFS",                    ["email.dfs.com"]),
    # テック・アプリ
    ("テック・アプリ/Apple",                ["apple.com"]),
    ("テック・アプリ/Dropbox",              ["dropbox.com"]),
    ("テック・アプリ/GitHub",               ["github.com", "no-reply@github.com"]),
    ("テック・アプリ/CapCut",               ["capcut.com", "mail.capcut.com"]),
    ("テック・アプリ/Satechi",              ["satechi.com"]),
    ("ショッピング/カメラのキタムラ",        ["kitamura.co.jp"]),
    ("テック・アプリ/カメラ/Insta360",      ["insta360-news.com", "insta360.com"]),
    # ゲーム
    ("ゲーム/PlayStation",                  ["playstation.com"]),
    ("ゲーム/Nintendo",                     ["nintendo.co.jp", "nintendo.com"]),
    ("ゲーム/HoYoverse",                    ["hoyoverse.com", "e-mail.hoyoverse.com"]),
    # 自動車・バイク
    ("自動車・バイク/Kawasaki",             ["kawasaki.co.jp", "kawasaki-motors",
                                           "kawasaki-onlineshop.jp"]),
    ("自動車・バイク/みんカラ",             ["carview.co.jp", "minkara"]),
    ("自動車・バイク/ウェビック",           ["webike.net"]),
    ("自動車・バイク/JAF",                  ["jaf.or.jp"]),
    ("自動車・バイク/ユピテル",             ["yupiteru.co.jp", "my.yupiteru.co.jp"]),
    ("自動車・バイク/洗車用品",             ["whiteseed.co.jp"]),
    # 宅配・物流
    ("宅配・物流/ヤマト運輸",              ["kuronekoyamato.co.jp"]),
    # 通信キャリア
    ("通信キャリア/IIJmio",                ["iijmio.jp", "iij.ad.jp"]),
    # 子育て
    ("子育て/ベネッセ",                    ["benesse.co.jp"]),
    ("子育て/リベルタ",                    ["liberta.net", "liberta.co.jp"]),
    # エンタメ配信
    ("エンタメ配信/電子書籍/Renta!",       ["sfmc.papy.co.jp", "papy.co.jp"]),
    # レジャー・チケット
    ("レジャー・チケット/アウトドア/モンベル", ["montbell.com", "montbell.co.jp"]),
    ("レジャー・チケット/チケット/ART PASS",  ["passes.jp"]),
    # AI・クラウド
    ("AI・クラウド/Mapbox",                ["mapbox.com"]),
    # エネルギー
    ("エネルギー/東京電力",                 ["tepco.co.jp"]),
    # 行政
    ("行政/相模原市",                       ["city.sagamihara"]),
    # 住まい
    ("住まい/マンション",                   ["mansion", "suumo", "major7"]),
    # 保険
    ("保険/アイペット",                     ["ipet.co.jp"]),

    # ===== 精査(2026-05-24)で追加: ドメイン→ラベル =====
    # ショッピング
    ("ショッピング/イオン",                 ["aeon.com"]),
    ("ショッピング/ニトリ",                 ["nitori-net.jp"]),
    ("ショッピング/ティファニー",           ["tiffany.com"]),
    ("ショッピング/ONESTOP",                ["onestop-ex.jp"]),
    ("ショッピング/Honya Club",             ["honyaclub.com"]),
    ("ショッピング/カラメル",               ["calamel.jp"]),
    ("ショッピング/お宝創庫",               ["otakarasouko.com"]),
    ("ショッピング/ハーモニック",           ["harmonick.co.jp"]),
    ("ショッピング/ファッション/ジーフット", ["g-foot.jp"]),
    ("ショッピング/グラフィック",           ["graphic.jp"]),
    ("ショッピング/ハンコヤドットコム",     ["hankoya.co.jp"]),
    ("ショッピング/ダンボールワン",         ["notosiki.co.jp"]),
    ("ショッピング/家電EC/ヤマダ電機",      ["tpgaw.jp"]),
    # グルメ
    ("グルメ/menu",                         ["menu.inc"]),
    ("グルメ/菊家",                         ["kikuya-oita.net"]),
    ("グルメ/すかいらーく",                 ["i-skylark.com"]),
    # テック・アプリ / セキュリティ
    ("テック・アプリ/NETGEAR",              ["netgear.com"]),
    ("テック・アプリ/ExpanDrive",           ["expandrive.com"]),
    ("テック・アプリ/OtterBox",             ["otterbox.com"]),
    ("テック・アプリ/Broadcom",             ["broadcom.com"]),
    ("テック・アプリ/codoc",                ["codoc.jp"]),
    ("テック・アプリ/eNom",                 ["enom.com"]),
    ("テック・アプリ/iMobie",               ["imobie.com"]),
    ("テック・アプリ/GSM Unlock",           ["freeunlockusa.com"]),
    ("テック・アプリ/風見鶏",               ["flashmemory.jp"]),
    ("テック・アプリ/がうがう",             ["gaugau.jp"]),
    ("テック・アプリ/音響機器/amulech",     ["amulech.com"]),
    ("テック・アプリ/ピクチャン",           ["pic-chan.net"]),
    ("テック・アプリ/xID",                  ["x-id.app"]),
    ("テック・アプリ/Box",                  ["box.com"]),
    ("テック・アプリ/Epson",                ["epson.jp", "epsonconnect.com"]),
    ("テック・アプリ/HP",                   ["hpj.ssnet.co.jp"]),
    ("セキュリティ/ESET",                   ["canon-its.co.jp"]),
    # 自動車・バイク
    ("自動車・バイク/宇佐美",               ["usamart.shop"]),
    ("自動車・バイク/カー用品/BeautifulCars", ["beautifulcars.biz"]),
    ("自動車・バイク/Raku-P",               ["raku-p.jp"]),
    ("自動車・バイク/バイク/カワサキプラザ", ["kawasaki-plaza.net"]),
    ("自動車・バイク/バイク/MotoJP",        ["motojp.main.jp"]),
    ("自動車・バイク/バイク用品/ヒロチー商事", ["hirochi.co.jp"]),
    ("自動車・バイク/ビッグモーター",       ["bigmotor.jp"]),
    ("自動車・バイク/パーツ/partsfan",      ["partsfan.com"]),
    ("自動車・バイク/バイク用品/Motostorm", ["motostorm.it"]),
    ("自動車・バイク/トータルリペア",       ["tr-ipy.com", "tr-esan.com"]),
    ("自動車・バイク/車検",                 ["carchs.com"]),
    ("自動車・バイク/バイク/BAS",           ["bas-bike.jp"]),
    ("自動車・バイク/timy",                 ["timy.jp"]),
    # 旅行 / レジャー
    ("旅行/ホテル/Relux",                   ["rlx.jp"]),
    ("旅行/Trip.com",                       ["trip.com"]),
    ("旅行/レンタカー/沖縄たびんふぉ",      ["car489.info"]),
    ("旅行/立山黒部アルペンルート",         ["tateyama-kurobe-webservice.jp"]),
    ("レジャー・チケット/レジャー/軽井沢スノーパーク", ["presidentresort.jp"]),
    ("レジャー・チケット/チケット/三栄チケットサービス", ["moala.fun"]),
    ("レジャー・チケット/カラオケDAM",      ["clubdam.com"]),
    ("レジャー・チケット/GENDA",            ["genda-apis.com"]),
    # 住まい（家電・家具・不動産）
    ("住まい/家電/ダイニチ工業",            ["dainichi-net.co.jp"]),
    ("住まい/引越し/アート引越センター",    ["the0123.com"]),
    ("住まい/家具/NOYES",                   ["ny-k.co.jp"]),
    ("住まい/家具/かねたや",                ["roomdeco.co.jp"]),
    ("住まい/リンテックコマース",           ["lintec-c.com"]),
    ("住まい/スマートホーム/Qrio",          ["qrioinc.com"]),
    ("住まい/タカラスタンダード",           ["takara-standard.co.jp"]),
    ("住まい/家電/三菱電機",                ["mitsubishielectric.co.jp"]),
    ("住まい/不動産/三興土地開発",          ["sankou-tkh.co.jp"]),
    ("住まい/不動産/東宝ハウス町田",        ["toho-machida.co.jp"]),
    ("住まい/不動産/大東建託",              ["kentaku.co.jp"]),
    ("住まい/不動産/東建コーポレーション",  ["token.co.jp"]),
    ("住まい/不動産/住友林業ホームサービス", ["sumirin-hs.co.jp"]),
    ("住まい/不動産/住まいの広場TOWNS",     ["sumainohiroba.com"]),
    ("住まい/不動産/サンクルー",            ["suncrew.co.jp"]),
    ("住まい/不動産/Renosy",                ["ga-tech.co.jp"]),
    # 保険 / 法律
    ("保険/損保ジャパン",                   ["anshinmy.com"]),
    ("保険/ウインストン",                   ["win-stone.jp"]),
    ("法律/カヤヌマ国際法律事務所",         ["kaya-law.jp"]),
    ("法律/サンク総合法律事務所",           ["thank-lawoffices.com"]),
    ("法律/宮下総合法律事務所",             ["m-lof.jp"]),
    # 子育て
    ("子育て/ハグノート",                   ["hugmo.net"]),
    ("子育て/ヒューマンアカデミー",         ["athuman.com"]),
    ("子育て/スナップスナップ",             ["photocreate.co.jp"]),
    ("子育て/まあむキッズ",                 ["mom2.jp"]),
    ("子育て/ミキハウス",                   ["mikihouse.co.jp"]),
    ("子育て/メガロスアフタースクール",     ["nomura-ls.jp"]),
    # 医療
    ("医療/489map",                         ["489map.com"]),
    ("医療/shujii",                         ["shujii.com"]),
    # 宅配 / 行政 / 交通
    ("宅配・物流/日本郵便",                 ["japanpost.jp"]),
    ("行政/防火防災協会",                   ["n-bouka.or.jp"]),
    ("行政/自治体マイページ",               ["mypg.jp"]),
    ("行政/LoGoフォーム",                   ["logoform.jp"]),
    ("交通・移動/高速道路/NEXCO東日本",     ["driveplaza.com"]),
    ("交通・移動/京成電鉄",                 ["keisei.co.jp"]),
    # 通信キャリア
    ("通信キャリア/au",                     ["auone-mail.com", "au-anshin.com"]),
    ("通信キャリア/t-mobile",               ["t-mobile.net"]),
    ("通信キャリア/Wi2",                    ["wi2.co.jp"]),
    ("通信キャリア/FON",                    ["fon.com"]),
    # ヘルス・美容 / エンタメ / 転職 / 仕事
    ("ヘルス・美容/フィットネス/メガロス",  ["megalos.co.jp"]),
    ("エンタメ配信/GEO",                    ["geo-reply.com"]),
    ("転職/エンエージェント",               ["en-japan.com"]),
    ("仕事/PCデポ",                         ["pcdepot.co.jp"]),

    # ===== 受信トレイ精査(2026-06-10)で追加: 既存ラベルへの対応付け =====
    ("AI・クラウド/Anthropic",              ["anthropic.com"]),
    ("マネー・金融/後払い/Paidy",           ["paidy.com"]),
    ("子育て/コドモン運営事務局",           ["codmon.com"]),
    ("通信キャリア/ISP/ネットフォレスト",   ["isp-support.jp"]),
    ("ショッピング/フリマ/メルカリ",        ["mercari-shops.com", "mercari.jp"]),
    ("医療/健診",                           ["health-check.jp"]),
    ("テック・アプリ/Ameba",                ["amebame.com"]),
    # ロボット教室相模大野(ヒューマンアカデミー系)。ymail.ne.jpはYahoo汎用ドメインのため
    # ドメインではなくフルアドレスで対応付ける
    ("子育て/ヒューマンアカデミー",         ["sagamiono3@ymail.ne.jp"]),
    # auのezweb宛サービス通知。「ezweb宛メールはEZ受信ボックスへ」の方針に従い、
    # 受信トレイから EZ受信ボックス へ送る（既ラベル付きなら実質アーカイブになる）
    ("EZ受信ボックス",                      ["au-cs.ezweb.ne.jp"]),
    # 写真整理協会メルマガ。List-Unsubscribeヘッダーが無く自動削除されないため、
    # 既存ラベルへ移動して受信トレイから片付ける
    ("テック・アプリ/写真整理協会",         ["shikuminet.jp"]),
]

# ===== 送信者ドメイン → 親ラベルマッピング =====
# 新規ラベル作成時に "トピック/送信者名" の入れ子構造で作る
LABEL_PARENT_MAP = [
    # ── テック・アプリ ──────────────────────────────────────────────
    ("テック・アプリ",   ["google.com", "googlemail.com",
                          "googleapis.com", "googleblog.com",
                          "apple.com", "icloud.com", "itunes.com",
                          "microsoft.com", "live.com", "outlook.com",
                          "xbox.com", "microsoftonline.com",
                          "adobe.com",
                          "sony.co.jp", "sony.com", "sonymusic.co.jp",
                          "dji.com",
                          "logicool.co.jp", "logitech.com",
                          "parallels.com",
                          "teamviewer.com",
                          "sourcenext.com", "sourcenext.co.jp",
                          "dropbox.com"]),
    # ── ゲーム ──────────────────────────────────────────────────────
    ("ゲーム",           ["steampowered.com", "steamcommunity.com",
                          "valvesoftware.com", "steam.com",
                          "square-enix.com", "squareenix.com", "ff14.com",
                          "nintendo.co.jp", "nintendo.com",
                          "sega.co.jp", "sega.com",
                          "dmm.com", "dmm.co.jp", "dlsite.com",
                          "playstation.com",
                          "sonyentertainmentnetwork.com"]),
    # ── エンタメ配信 ─────────────────────────────────────────────────
    ("エンタメ配信",     ["youtube.com",
                          "nicovideo.jp", "dwango.co.jp", "niconico.jp",
                          "mora.jp", "mora-qualitas.com", "e-onkyo.com",
                          "ototoy.jp",
                          "recochoku.jp"]),
    # ── SNS ─────────────────────────────────────────────────────────
    ("SNS",              ["ameba.jp", "ameblo.jp", "cyberagent.co.jp"]),
    # ── ショッピング ─────────────────────────────────────────────────
    ("ショッピング",     ["amazon.co.jp", "amazon.com", "amazonaws.com",
                          "rakuten.co.jp", "rakuten.com",
                          "zozo.jp", "zozotown.com",
                          "uniqlo.com", "fastretailing.com", "gu-global.com",
                          "nano-universe.jp",
                          "alpen-group.jp", "alpen.co.jp", "alpen.ne.jp",
                          "nojima.co.jp",
                          "biccamera.com", "biccamera.co.jp",
                          "monotaro.com"]),
    # ── マネー・金融 ─────────────────────────────────────────────────
    ("マネー・金融",     ["nomura-re.co.jp", "nomura-fh.co.jp",
                          "boy.co.jp", "hamagin.co.jp",
                          "ponta.jp", "loyalty.co.jp", "recruit-point",
                          "orix.co.jp",
                          "pay.rakuten.co.jp"]),      # 楽天ペイ
    # ── 通信キャリア ─────────────────────────────────────────────────
    ("通信キャリア",     ["au.com", "kddi.com", "povo.jp", "au.kddi.com",
                          "auone.jp", "au-cs-mail",
                          "docomo.ne.jp", "nttdocomo.co.jp", "nttdocomo.com",
                          "softbank.co.jp", "softbank.ne.jp", "y-mobile.ne.jp",
                          "mb.softbank.jp",
                          "ntt-east.co.jp", "ntt.com", "nttpc.ne.jp",
                          "plala.or.jp", "ocn.ne.jp"]),
    # ── 旅行 ─────────────────────────────────────────────────────────
    ("旅行",             ["ana.co.jp", "anahd.co.jp", "ana.com",
                          "apahotel.com", "apa-hotel.com",
                          "hotels.com", "expediamail.com",
                          "trip.com", "ctrip.com", "trip.co.jp"]),
    # ── グルメ ───────────────────────────────────────────────────────
    ("グルメ",           ["gyukaku.ne.jp", "yakiniku-king",
                          "demae-can.com", "demaecan.co.jp"]),
    # ── 自動車・バイク ───────────────────────────────────────────────
    ("自動車・バイク",   ["nissan.co.jp", "nissan.com", "nissan-finance",
                          "magazine.nissan.co.jp"]),
    # ── ヘルス・美容 ─────────────────────────────────────────────────
    ("ヘルス・美容",     ["euglena.jp", "euglena.co.jp"]),
    # ── 保険 ─────────────────────────────────────────────────────────
    ("保険",             ["sompo-japan.co.jp", "sompo.co.jp", "sjnk.co.jp",
                          "ms-ins.com", "aioi-ms.co.jp"]),
    # ── セキュリティ ─────────────────────────────────────────────────
    ("セキュリティ",     ["adguard.com",
                          "kaspersky.co.jp", "kaspersky.com"]),
    # ── 宅配・物流 ───────────────────────────────────────────────────
    ("宅配・物流",       ["sagawa-exp.co.jp", "sagawa.co.jp",
                          "kuronekoyamato.co.jp", "yamato-hd.co.jp",
                          "fedex.com"]),
    # ── 新カテゴリ（2026-05-24 追加）──
    ("法律",             ["kaya-law.jp", "thank-lawoffices.com", "m-lof.jp"]),
    ("仕事",             ["pcdepot.co.jp"]),
]

SYSTEM_LABELS = {
    "INBOX", "SENT", "TRASH", "SPAM", "DRAFT", "STARRED", "IMPORTANT",
    "[Gmail]/All Mail", "[Gmail]/Sent Mail", "[Gmail]/Trash",
    "[Gmail]/Spam", "[Gmail]/Drafts", "[Gmail]/Starred",
    "[Gmail]/Important", "[Imap]/Drafts",
}


# ─────────────────────────────────────────────
# Secret Manager
# ─────────────────────────────────────────────

def get_secret(project_id, secret_name):
    client = secretmanager.SecretManagerServiceClient()
    name = f"projects/{project_id}/secrets/{secret_name}/versions/latest"
    response = client.access_secret_version(request={"name": name})
    return response.payload.data.decode("UTF-8").strip()


# ─────────────────────────────────────────────
# IMAP 接続管理
# ─────────────────────────────────────────────

def create_imap_client(password):
    client = IMAPClient("imap.gmail.com", ssl=True)
    client.login(EMAIL, password)
    return client


def find_trash_folder(client):
    for flags, delimiter, name in client.list_folders():
        if b'\\Trash' in flags:
            return name
    return "[Gmail]/ゴミ箱"


def ensure_folder(client, folder_name, known_folders: set):
    if folder_name not in known_folders:
        try:
            client.create_folder(folder_name)
            known_folders.add(folder_name)
            time.sleep(1)
            print(f"  📁 ラベル新規作成: {folder_name}")
        except Exception:
            known_folders.add(folder_name)
            time.sleep(0.5)


# ─────────────────────────────────────────────
# Gmail API（フィルター管理用）
# ─────────────────────────────────────────────

def get_gmail_service(project_id):
    try:
        from google.oauth2.credentials import Credentials
        import google.auth.transport.requests
        from googleapiclient.discovery import build

        creds_json = get_secret(project_id, OAUTH_CREDENTIALS_SECRET)
        creds_data = json.loads(creds_json)
        creds = Credentials(
            token=None,
            refresh_token=creds_data["refresh_token"],
            token_uri="https://oauth2.googleapis.com/token",
            client_id=creds_data["client_id"],
            client_secret=creds_data["client_secret"],
        )
        creds.refresh(google.auth.transport.requests.Request())
        return build("gmail", "v1", credentials=creds, cache_discovery=False)
    except Exception as e:
        print(f"⚠️ Gmail API未設定（フィルター削除はスキップ）: {e}")
        return None


def build_label_id_map(gmail_service):
    if not gmail_service:
        return {}
    try:
        result = gmail_service.users().labels().list(userId="me").execute()
        return {lbl["name"]: lbl["id"] for lbl in result.get("labels", [])}
    except Exception as e:
        print(f"⚠️ ラベルIDマップ取得失敗: {e}")
        return {}


def delete_gmail_filters_for_label(gmail_service, label_id, label_name):
    if not gmail_service or not label_id:
        return 0
    try:
        resp = gmail_service.users().settings().filters().list(userId="me").execute()
        count = 0
        for f in resp.get("filter", []):
            if label_id in f.get("action", {}).get("addLabelIds", []):
                gmail_service.users().settings().filters().delete(
                    userId="me", id=f["id"]
                ).execute()
                print(f"  🔧 Gmailフィルター削除 [{label_name}]: {f['id']}")
                count += 1
        return count
    except Exception as e:
        print(f"  ⚠️ Gmailフィルター削除失敗 [{label_name}]: {e}")
        return 0


# ─────────────────────────────────────────────
# メール処理ユーティリティ
# ─────────────────────────────────────────────

def decode_str(s):
    if s is None:
        return ""
    parts = decode_header(s)
    result = []
    for part, charset in parts:
        if isinstance(part, bytes):
            result.append(part.decode(charset or "utf-8", errors="ignore"))
        else:
            result.append(str(part))
    return "".join(result)


def is_whitelisted(sender):
    return any(d in sender.lower() for d in WHITELIST_DOMAINS)


def is_our_unsubscribe_bounce(sender, subject, header_dict, unsubscribe_targets):
    sender_lower = sender.lower()
    subject_lower = subject.lower()

    # バウンス通知の送信者パターン
    bounce_senders = ["mailer-daemon", "postmaster", "mail delivery", "mail-daemon"]
    is_bounce_sender = any(p in sender_lower for p in bounce_senders)

    # 失敗した宛先に bounce- パターンが含まれる（メルマガ解除アドレスの典型形式）
    failed = header_dict.get("x-failed-recipients", "").lower()
    has_bounce_recipient = "bounce-" in failed or "bounces." in failed or "bounce@" in failed

    # 件名パターン（日英）
    bounce_subjects = [
        "unsubscribe",
        "アドレス不明", "配信できませんでした", "配信に失敗",
        "delivery status", "undeliverable", "mail delivery failed",
    ]
    has_bounce_subject = any(p in subject_lower for p in bounce_subjects)

    if is_bounce_sender and (has_bounce_recipient or has_bounce_subject):
        return True

    # unsubscribe_targetsに一致する宛先へのバウンス
    if is_bounce_sender and failed and any(t in failed for t in unsubscribe_targets):
        return True

    return False


def is_delete_target(sender, headers):
    sender_lower = sender.lower()
    for s in DELETE_SENDERS:
        if s.lower() in sender_lower:
            return True, "削除対象送信者"
    if "list-unsubscribe" in headers:
        return True, "List-Unsubscribeヘッダーあり"
    return False, ""


def get_label_for(sender, subject):
    text = (sender + " " + subject).lower()
    for label, keywords in LABEL_RULES:
        for kw in keywords:
            if kw in text:
                return label
    return None


def sanitize_label_name(name):
    """IMAPで問題になる文字をラベル名から除去・置換"""
    if not name:
        return None
    # 全角カッコ → 半角
    name = name.replace('（', '(').replace('）', ')')
    # IMAP的に問題になる文字を除去
    name = re.sub(r'[/\\*"<>|&]', '', name)
    name = name.strip()
    return name if len(name) >= 1 else None


# 日本の属性型/地域型 第2レベルドメイン（組織名はこの"手前"に来る）
_JP_SLD = {"co", "ne", "or", "go", "ac", "ad", "ed", "gr", "lg",
           "com", "net", "org", "gov", "edu"}


def _org_from_domain(domain):
    """ドメインから組織名ラベルを抽出。複合TLD(co.jp/ne.jp等)に対応。
    例: docomo.ne.jp→docomo / example.co.jp→example / example.com→example
    バグ修正: 旧実装は parts[-2] で .ne.jp を 'ne' にしていた。"""
    parts = [p for p in domain.split(".") if p]
    if len(parts) < 2:
        return parts[0] if parts else None
    # 末尾が jp で、その手前が属性型SLD(co/ne/or/go…)なら、さらに手前が組織名
    if parts[-1] == "jp" and len(parts) >= 3 and parts[-2] in _JP_SLD:
        return parts[-3]
    return parts[-2]


def extract_sender_name(sender):
    m = re.match(r'^"?([^"<]+)"?\s*<', sender)
    if m:
        name = m.group(1).strip()
        if len(name) >= 2:
            return sanitize_label_name(name)
    m = re.search(r'@([\w.-]+)', sender)
    if m:
        org = _org_from_domain(m.group(1).lower())
        # 万一 SLD断片だけになったら採用しない（co/ne 等の暴発防止）
        if org and org not in _JP_SLD:
            return sanitize_label_name(org)
    return None


def get_parent_for_sender(sender):
    """送信者のドメインから親ラベルを返す。なければ None。"""
    sender_lower = sender.lower()
    for parent, domains in LABEL_PARENT_MAP:
        for domain in domains:
            if domain in sender_lower:
                return parent
    return None


def build_nested_label_index(known_folders):
    """
    既存の入れ子ラベルのインデックスを作成。
    "子ラベル名" → "親/子ラベル名" のマッピング。
    同じ子名が複数あれば最初のものを使用。
    """
    index = {}
    for folder in known_folders:
        if "/" in folder:
            child_part = folder.rsplit("/", 1)[-1]
            if child_part not in index:
                index[child_part] = folder
    return index


def resolve_label_for_sender(sender, subject, known_folders, nested_index):
    """
    メールの振り分け先ラベルを決定する。
    優先順位:
      1. LABEL_RULES に一致 → そのまま使用
      2. 送信者名が既存の入れ子ラベルの子に一致 → 入れ子ラベルを使用
         （例: "YouTube" → 既存 "Google/YouTube" を使用）
      3. 送信者名が LABEL_PARENT_MAP のドメインに一致 → "親/送信者名" で作成
      4. フラットな送信者名（従来通り）
    """
    # 1. LABEL_RULES
    label = get_label_for(sender, subject)
    if label:
        return label

    # 送信者名を抽出
    sender_name = extract_sender_name(sender)
    if not sender_name:
        return None

    # 2. 既存の入れ子ラベルを優先（整理済みラベルを尊重）
    existing_nested = nested_index.get(sender_name)
    if existing_nested:
        return existing_nested

    # 3. LABEL_PARENT_MAP で親を決定 → "親/送信者名" で新規作成
    parent = get_parent_for_sender(sender)
    if parent:
        return f"{parent}/{sender_name}"

    # 4. 未登録の送信者は受信トレイに残す（フラットラベルを自動作成しない）
    #    ※ 旧実装は flat な sender_name を返して co/ne 等の乱立を招いていた
    return None


def try_unsubscribe(msg_obj, password, unsubscribed_set, unsubscribe_targets):
    header = msg_obj.get("List-Unsubscribe", "")
    if not header:
        return
    m = re.search(r'[\w.+-]+@[\w.-]+', msg_obj.get("From", ""))
    sender_key = m.group(0).lower() if m else msg_obj.get("From", "").lower()
    if sender_key in unsubscribed_set:
        return
    unsubscribed_set.add(sender_key)

    post_header = msg_obj.get("List-Unsubscribe-Post", "")
    urls    = re.findall(r'<(https?://[^>]+)>', header)
    mailtos = re.findall(r'<mailto:([^>]+)>', header, re.IGNORECASE)

    if urls and "List-Unsubscribe=One-Click" in post_header:
        try:
            req = urllib.request.Request(
                urls[0], data=b"List-Unsubscribe=One-Click",
                headers={"Content-Type": "application/x-www-form-urlencoded",
                         "User-Agent": "Mozilla/5.0"},
                method="POST")
            urllib.request.urlopen(req, timeout=10)
            print(f"  📧 配信停止(POST): {urls[0][:60]}")
            return
        except Exception as e:
            print(f"  ⚠️ POST失敗: {e}")

    if mailtos:
        try:
            mailto = mailtos[0]
            addr = mailto.split("?", 1)[0] if "?" in mailto else mailto
            subject = ""
            if "?" in mailto:
                for p in mailto.split("?", 1)[1].split("&"):
                    if p.lower().startswith("subject="):
                        subject = urllib.parse.unquote(p[8:])
            addr = addr.strip()
            if "@" in addr:
                msg_out = email.mime.text.MIMEText("")
                msg_out["Subject"] = subject or "unsubscribe"
                msg_out["From"] = EMAIL
                msg_out["To"] = addr
                with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=10) as smtp:
                    smtp.login(EMAIL, password)
                    smtp.sendmail(EMAIL, addr, msg_out.as_string())
                unsubscribe_targets.add(addr.lower())
                print(f"  📧 配信停止メール: {addr}")
                return
        except Exception as e:
            print(f"  ⚠️ mailto失敗: {e}")

    if urls:
        try:
            urllib.request.urlopen(
                urllib.request.Request(urls[0], headers={"User-Agent": "Mozilla/5.0"}),
                timeout=10)
            print(f"  📧 配信停止(GET): {urls[0][:60]}")
        except Exception as e:
            print(f"  ⚠️ GET失敗: {e}")


# ─────────────────────────────────────────────
# バッチ処理（再接続対応）
# ─────────────────────────────────────────────

def process_folder(password, folder_name, TRASH, known_folders, nested_index,
                   unsubscribed_set, unsubscribe_targets,
                   deleted, moved, skipped, protected,
                   is_inbox=True):
    client = create_imap_client(password)
    try:
        client.select_folder(folder_name)
        all_uids = client.search(["ALL"])
    except Exception as e:
        print(f"  ⚠️ フォルダ選択失敗 [{folder_name}]: {e}")
        try: client.logout()
        except: pass
        return 0

    total = len(all_uids)
    print(f"  📂 {folder_name}: {total}件")

    batch_count = 0
    for batch_start in range(0, total, BATCH_SIZE):
        batch = all_uids[batch_start:batch_start + BATCH_SIZE]

        if batch_count > 0 and batch_count % RECONNECT_EVERY == 0:
            print(f"  🔄 再接続中... ({batch_start}/{total}件処理済)")
            try: client.logout()
            except: pass
            time.sleep(2)
            client = create_imap_client(password)
            client.select_folder(folder_name)

        batch_count += 1

        for attempt in range(2):
            try:
                messages = client.fetch(batch, ["RFC822.HEADER"])
                break
            except Exception as e:
                if attempt == 0:
                    print(f"  🔄 バッチ取得失敗→再接続: {e}")
                    try: client.logout()
                    except: pass
                    time.sleep(3)
                    client = create_imap_client(password)
                    client.select_folder(folder_name)
                else:
                    print(f"  ⚠️ バッチ取得スキップ: {e}")
                    messages = {}

        delete_batch = []
        for uid, data in messages.items():
            subject = "（不明）"
            try:
                raw     = data.get(b"RFC822.HEADER", b"")
                msg_obj = email.message_from_bytes(raw)
                sender  = decode_str(msg_obj.get("From", ""))
                subject = decode_str(msg_obj.get("Subject", "（件名なし）"))
                headers = {k.lower() for k in msg_obj.keys()}

                # バウンス検出はホワイトリストより先（Googleのmailer-daemonも対象）
                header_dict = {k.lower(): msg_obj.get(k, "") for k in msg_obj.keys()}
                if is_our_unsubscribe_bounce(sender, subject, header_dict, unsubscribe_targets):
                    delete_batch.append(uid)
                    deleted.append(subject)
                    print(f"  🗑  配信停止バウンス削除: {subject[:50]}")
                    continue

                whitelisted = is_whitelisted(sender)

                # ホワイトリスト以外は削除判定
                if not whitelisted:
                    should_delete, reason = is_delete_target(sender, headers)
                    if should_delete:
                        if not DRY_RUN:
                            try_unsubscribe(msg_obj, password, unsubscribed_set, unsubscribe_targets)
                        delete_batch.append(uid)
                        deleted.append(subject)
                        tag = "🔬[DRY-RUN]削除予定" if DRY_RUN else "🗑  削除"
                        print(f"  {tag}[{reason}]: {subject[:50]}")
                        continue

                if not is_inbox:
                    if whitelisted:
                        protected.append(subject)
                    continue

                # ラベル振り分け（ホワイトリストも対象）
                label = resolve_label_for_sender(sender, subject, known_folders, nested_index)
                if label:
                    if DRY_RUN:
                        moved.append((subject, label))
                        print(f"  🔬[DRY-RUN]移動予定[{label}]: {subject[:50]}")
                        continue
                    ensure_folder(client, label, known_folders)
                    try:
                        client.copy([uid], label)
                        client.delete_messages([uid])
                        client.expunge()
                        moved.append((subject, label))
                        print(f"  📁 移動[{label}]: {subject[:50]}")
                    except Exception as e:
                        if "TRYCREATE" in str(e):
                            time.sleep(2)
                            known_folders.discard(label)
                            ensure_folder(client, label, known_folders)
                            try:
                                client.copy([uid], label)
                                client.delete_messages([uid])
                                client.expunge()
                                moved.append((subject, label))
                                print(f"  📁 移動(リトライ)[{label}]: {subject[:50]}")
                            except Exception as e2:
                                print(f"  ⚠️ 移動リトライ失敗: {e2}")
                                skipped.append(subject)
                        else:
                            print(f"  ⚠️ 移動エラー: {e}")
                            skipped.append(subject)
                else:
                    if whitelisted:
                        protected.append(subject)
                        print(f"  🛡  保護(受信トレイ残留): {subject[:50]}")
                    else:
                        skipped.append(subject)

            except Exception as e:
                print(f"  ⚠️ 処理エラー: {e} / {subject[:40]}")
                skipped.append(subject)

        if delete_batch:
            if DRY_RUN:
                print(f"  🔬[DRY-RUN] このバッチで {len(delete_batch)}件 削除予定（実行しない）")
            else:
                try:
                    client.copy(delete_batch, TRASH)
                    client.delete_messages(delete_batch)
                    client.expunge()
                except Exception as e:
                    print(f"  ⚠️ バッチ削除エラー: {e}")

    try: client.logout()
    except: pass
    return total


# ─────────────────────────────────────────────
# メインエントリポイント（Cloud Run Jobs用）
# ─────────────────────────────────────────────

def main():
    print("📬 Gmail自動管理 開始")

    password = get_secret(PROJECT_ID, SECRET_NAME)
    unsubscribed_set    = set()
    unsubscribe_targets = set()

    gmail_service = get_gmail_service(PROJECT_ID)
    label_id_map  = build_label_id_map(gmail_service)
    if gmail_service:
        print(f"✅ Gmail API接続成功（ラベル数: {len(label_id_map)}）")
    filter_deleted_count = 0

    tmp_client = create_imap_client(password)
    TRASH = find_trash_folder(tmp_client)
    known_folders = {f[2] for f in tmp_client.list_folders()}
    all_user_folders = [
        f[2] for f in tmp_client.list_folders()
        if f[2] not in SYSTEM_LABELS and not f[2].startswith("[Gmail]")
    ]
    tmp_client.logout()
    print(f"🗑  ゴミ箱: {TRASH}")
    print(f"📂 ユーザーラベル数: {len(all_user_folders)}件")

    # 入れ子ラベルインデックスを作成（"子名" → "親/子名" の高速検索用）
    nested_index = build_nested_label_index(known_folders)
    print(f"🗂  入れ子ラベル数: {len(nested_index)}件")

    deleted, moved, skipped, protected = [], [], [], []

    # ===== Step 1: 受信トレイ全件 =====
    print(f"\n📥 受信トレイ処理開始")
    inbox_total = process_folder(
        password, "INBOX", TRASH, known_folders, nested_index,
        unsubscribed_set, unsubscribe_targets,
        deleted, moved, skipped, protected,
        is_inbox=True
    )
    print(f"✅ 受信トレイ完了: {inbox_total}件処理")

    # ===== Step 2: 既存ラベル内のメルマガ削除（移動・ラベル変更はしない）=====
    # 方針（2026-05-31 ユーザー指示「削除は行なってラベル移動しないでいこうか」）:
    #   既存ラベルを巡回し、メルマガ(List-Unsubscribe)／削除対象送信者のメールだけを削除する。
    #   process_folder(is_inbox=False) は「削除のみ」を実施し、ラベル移動・再振り分け・
    #   ラベル新規作成は一切しない（移動処理は is_inbox=False のとき手前で continue される）。
    #   ラベルそのものの削除や Gmail フィルター削除もしない（手動整理を保護するため）。
    #   EZ受信ボックス / EZ送信ボックス（およびその配下）はユーザー保護対象のため除外する。
    EZ_PROTECTED = ("EZ受信ボックス", "EZ送信ボックス")
    step2_folders = [
        f for f in all_user_folders
        if not any(f == p or f.startswith(p + "/") for p in EZ_PROTECTED)
    ]
    deleted_before_step2 = len(deleted)
    print(f"\n🗂  既存ラベルのメルマガ削除を開始"
          f"（移動なし／ラベル保護／対象 {len(step2_folders)}ラベル）"
          + ("　🔬DRY-RUN" if DRY_RUN else ""))
    for folder_name in step2_folders:
        before = len(deleted)
        process_folder(
            password, folder_name, TRASH, known_folders, nested_index,
            unsubscribed_set, unsubscribe_targets,
            deleted, moved, skipped, protected,
            is_inbox=False
        )
        n = len(deleted) - before
        if n:
            print(f"    🗑 {folder_name}: {n}件 {'削除予定' if DRY_RUN else '削除'}")
    step2_deleted = len(deleted) - deleted_before_step2
    print(f"🗂  既存ラベル処理完了: {step2_deleted}件 {'削除予定' if DRY_RUN else '削除'}")
    _ = label_id_map  # 後方互換のため参照だけ保持

    mode = "🔬 DRY-RUN（実際には変更していません）" if DRY_RUN else "本番"
    print(f"""
✅ 全処理完了（{mode}）
   受信トレイ処理: {inbox_total}件
   削除: {len(deleted)}件（うち既存ラベル: {step2_deleted}件）
   配信停止: {len(unsubscribed_set)}件
   移動: {len(moved)}件
   保護: {len(protected)}件
   スキップ: {len(skipped)}件
   フィルター削除: {filter_deleted_count}件
""")


if __name__ == "__main__":
    main()
