#!/usr/bin/env python3
"""
fix_all_labels2.py - 第2弾ラベル一括整理

構造:
  CLUSTER_MERGES = [(destination, [source1, source2, ...]), ...]
  - destination が存在しない場合は自動作成
  - 各 source のスレッドを destination に移動後、source を削除
  - source が存在しない場合はスキップ（エラーにしない）

除外（絶対に変更しない）:
  EZ受信ボックス・EZ送信ボックス 配下

使い方:
  USE_LOCAL=1 python3 fix_all_labels2.py --dry-run   # プレビュー
  USE_LOCAL=1 python3 fix_all_labels2.py             # 本番実行
"""

import json, os, sys, time
import google.auth.transport.requests
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

DRY_RUN = "--dry-run" in sys.argv
LOCAL_CREDS_PATH = os.path.expanduser("~/.gmail_local_credentials.json")
EXCLUDE_PREFIXES = ("EZ受信ボックス", "EZ送信ボックス")

# =====================================================================
# CLUSTER_MERGES: (destination, [sources...])
#   destination が存在しない → 新規作成
#   sources の各ラベル → destination にスレッド移動後削除
#   source が存在しない → スキップ
# =====================================================================
CLUSTER_MERGES = [

    # ──────────────────────────────────────────────────────────
    # AI・クラウド
    # ──────────────────────────────────────────────────────────
    ("AI・クラウド/Anthropic", [
        "AI・クラウド/Anthropic, PBC",
    ]),
    ("AI・クラウド/Wrtn", [
        "AI・クラウド/リートン",
        "wrtn",
    ]),

    # ──────────────────────────────────────────────────────────
    # テック・アプリ
    # ──────────────────────────────────────────────────────────
    ("テック・アプリ/Adobe", [
        "テック・アプリ/'Adobe'",
        "テック・アプリ/adobe",
        "テック・アプリ/acrobat",
        "テック・アプリ/Adobe Creative Cloud",
        "テック・アプリ/Adobe Document Cloud",
        "テック・アプリ/Adobe Support Community Mailer",
    ]),
    ("テック・アプリ/Google Gemini", [
        "テック・アプリ/Bard",
        "テック・アプリ/Bard - Google による試験運用中の AI サービス",
    ]),
    ("テック・アプリ/Ameba", [
        "テック・アプリ/Ameba（アメーバ）",
        "テック・アプリ/アメーバ",
        "テック・アプリ/アメブロ",
        "テック・アプリ/アメマガ",
        "テック・アプリ/アメーバ事業本部",
        "テック・アプリ/アメーバ最新ニュース",
    ]),
    ("テック・アプリ/FC2", [
        "テック・アプリ/FC2,inc",
        "テック・アプリ/FC2 Information",
        "テック・アプリ/fc2",
    ]),
    ("テック・アプリ/Sony", [
        "テック・アプリ/sony",
        "テック・アプリ/My Sony",
        "テック・アプリ/My Sony Club",
        "テック・アプリ/ソニーストア",
        "テック・アプリ/sonycreativesoftware",
        "PlayMemories Online",
    ]),
    ("テック・アプリ/DJI", [
        "テック・アプリ/DJI JAPAN (DJI Support)",
    ]),
    # TeamViewer Info が既存のため統合先にする
    ("テック・アプリ/TeamViewer Info", [
        "テック・アプリ/TeamViewer Sign In Confirmation",
        "テック・アプリ/teamviewer",
    ]),
    ("テック・アプリ/GMO", [
        "テック・アプリ/GMOとくとくショッピング",
        "テック・アプリ/GMOとくとくポイント",
        "テック・アプリ/GMOとくとく通信",
        "テック・アプリ/gmo-pg",
        "テック・アプリ/gmo-ps",
    ]),
    ("テック・アプリ/Dropbox", [
        "Dropbox",
        "テック・アプリ/The Dropbox Team",
    ]),
    ("テック・アプリ/iTunes", [
        "テック・アプリ/iTunes Store",
        "itunes",
    ]),
    ("テック・アプリ/Microsoft OneDrive", [
        "テック・アプリ/OneDrive",
    ]),
    ("テック・アプリ/Microsoft Outlook", [
        "テック・アプリ/outlook",
    ]),
    ("テック・アプリ/Microsoft account team", [
        "テック・アプリ/Microsoft アカウント チーム",
        "テック・アプリ/microsoft",
    ]),
    ("テック・アプリ/NVIDIA", [
        "NVIDIA Accounts",
    ]),
    ("テック・アプリ/Canva", [
        "Canva",
    ]),
    ("テック・アプリ/Zoom", [
        "Zoom",
    ]),
    ("テック・アプリ/Evernote", [
        "Evernote",
    ]),
    ("テック・アプリ/Lenovo", [
        "ファミリー販売",
    ]),
    ("テック・アプリ/ジャングル", [
        "JUNGLE",
        "株式会社ジャングル",
    ]),
    ("テック・アプリ/価格.com", [
        "kakaku",
        "価格.com 自動車保険一括見積もり",
        "株式会社カカクコム",
    ]),
    ("テック・アプリ/SOURCENEXT", [
        "テック・アプリ/ソースネクスト・インフォメーションセンター",
    ]),

    # ──────────────────────────────────────────────────────────
    # SNS
    # ──────────────────────────────────────────────────────────
    ("SNS/Twitter", [
        "x",           # x.com = Twitter
    ]),

    # ──────────────────────────────────────────────────────────
    # エンタメ配信
    # ──────────────────────────────────────────────────────────
    ("エンタメ配信/動画配信/niconico", [
        "エンタメ配信/niconico",
        "エンタメ配信/nicovideo",
        "エンタメ配信/【niconico】",
        "エンタメ配信/【niconico】ニコレポメール",
        "エンタメ配信/【ニコニコ動画】",
        "エンタメ配信/【ニコニコ動画】ニコレポメール",
    ]),
    ("エンタメ配信/音楽配信/レコチョク", [
        "エンタメ配信/recochoku",
        "エンタメ配信/【レコチョク】",
        "エンタメ配信/レコチョク Bestおすすめ",
        "エンタメ配信/レコチョク ランキング",
        "エンタメ配信/レコチョク 新着情報",
        "エンタメ配信/レコチョク 日刊レコチョク通信",
        "エンタメ配信/＜レコチョク＞",
    ]),
    ("エンタメ配信/音楽配信/mora", [
        "エンタメ配信/mora qualitas",
        "エンタメ配信/mora qualitas News",
        "エンタメ配信/mora qualitasお知らせ",
        "エンタメ配信/mora[モーラ]",
    ]),
    ("エンタメ配信/音楽配信/e-onkyo", [
        "エンタメ配信/e-onkyo",
        "エンタメ配信/e-onkyo music",
    ]),
    ("エンタメ配信/音楽配信/OTOTOY", [
        "エンタメ配信/OTOTOY MUSIC STORE",
        "ototoy",
    ]),
    ("エンタメ配信/動画配信/Prime Video", [
        "エンタメ配信/Prime Video",
    ]),
    ("エンタメ配信/動画配信/YouTube", [
        "エンタメ配信/YouTube",
        "エンタメ配信/YouTube Kids",
        "エンタメ配信/YouTube Music",
        "エンタメ配信/YouTube Premium",
    ]),
    ("エンタメ配信/電子書籍/DLsite", [
        "エンタメ配信/DLsite comipo",
    ]),
    ("エンタメ配信/TSUTAYA", [
        "TSUTAYA通販メール",
    ]),
    ("エンタメ配信/GEO", [
        "geonet",
    ]),
    ("エンタメ配信/pixiv", [
        "pixiv事務局",
    ]),

    # ──────────────────────────────────────────────────────────
    # ゲーム
    # ──────────────────────────────────────────────────────────
    ("ゲーム/PlayStation", [
        "ゲーム/PlayStation Network",
        "ゲーム/SCE インフォメーションセンター",
        "ゲーム/SCEJ オンライン受付サービス",
        "ゲーム/SIEJA 延長保証受付サービス",
        "ゲーム/Sony Entertainment Network",
        "ゲーム/ソニー・コンピュータエンタテインメント",
        "playstation",
    ]),
    ("ゲーム/Steam", [
        "ゲーム/Steam Store",
        "ゲーム/Steam Support",
        "ゲーム/Steam Team",
        "ゲーム/Steam サポート",
    ]),
    ("ゲーム/Ateam", [
        "ゲーム/Ateam Inc.",
        "ゲーム/AteamID",
        "ゲーム/株式会社エイチーム",
        "ゲーム/株式会社エイチームエンターテインメント",
        "ゲーム/【三国大戦スマッシュ！】運営チーム",
    ]),
    ("ゲーム/Square Enix", [
        "ゲーム/Square Enix Account",
        "ゲーム/SQUARE ENIX BRIDGE",
        "ゲーム/square-enix",
        "ゲーム/dragonquest",
    ]),
    ("ゲーム/SEGA", [
        "ゲーム/SEGA ID",
        "ゲーム/SEGA IDサポート",
        "ゲーム/pso2admin@isao.net",
        "isao",
    ]),
    ("ゲーム/DMM", [
        "ゲーム/DMM.com",
        "ゲーム/DMM.com証券カスタマーサポート",
        "ゲーム/dmm",
    ]),
    ("ゲーム/HoYoverse", [
        "ゲーム/hoyoverse",
        "ゲーム/mihoyo",
    ]),
    ("ゲーム/DLsite", [
        "ゲーム/DLsite サポート係",
    ]),
    ("ゲーム/Roblox", [
        "ゲーム/Roblox no-reply",
    ]),
    ("ゲーム/モバゲー", [
        "mbga",
    ]),
    ("ゲーム/Capcom", [
        "ゲーム/Capcom Online Games",
        "ゲーム/カプコンオンラインゲームズ",
    ]),

    # ──────────────────────────────────────────────────────────
    # ショッピング
    # ──────────────────────────────────────────────────────────
    ("ショッピング/Amazon", [
        "ショッピング/Amazon.jp",
    ]),
    ("ショッピング/楽天市場", [
        "ショッピング/楽天市場からのお知らせ",
    ]),
    ("ショッピング/MonotaRO", [
        "ショッピング/MonotaRO.com",
        "ショッピング/株式会社MonotaRO",
        "ショッピング/MonotaROサポートセンター",
    ]),
    ("ショッピング/家電EC/ビックカメラ.com", [
        "ショッピング/support@cc.biccamera.com",
    ]),
    ("ショッピング/家電EC/Kaago", [
        "Kaago運営事務局",
        "@Next Select【Kaago店】",
        "@Next Select【Kaago店】【No Reply】",
        "@Next Select【No Reply】",
    ]),
    ("ショッピング/ファッション/nano・universe", [
        "ショッピング/nano-u",
        "ショッピング/nano・universe",
    ]),
    ("ショッピング/ファッション/ユニクロ", [
        "ショッピング/＜ユニクロ＞",
        "ショッピング/＜ユニクロ オンラインストア＞",
        "ショッピング/＜ユニクロ・ジーユー＞",
        "ショッピング/fastretailing",
    ]),
    ("ショッピング/ファッション/DIFFERENCE", [
        "DIFFERENCE",
        "ディファレンス海老名ビナウォーク店",
    ]),
    ("ショッピング/ファッション/コーチ", [
        "コーチ アウトレット",
    ]),
    ("ショッピング/MOUMANTAI", [
        "MOUMANTAI-無問題オンラインショップ-",
    ]),

    # ──────────────────────────────────────────────────────────
    # グルメ
    # ──────────────────────────────────────────────────────────
    ("グルメ/出前館", [
        "グルメ/demae-can",
        "グルメ/no-reply@demae-can.com",
        "グルメ/support@demae-can.com",
        "グルメ/出前館カスタマーセンター",
        "グルメ/出前館カスタマーセンター(PC)",
        "グルメ/出前館サポート",
    ]),
    ("グルメ/くら寿司", [
        "グルメ/noreply@reservation.kurasushi.co.jp",
        "くら寿司名古屋栄店",
    ]),
    ("グルメ/牛角", [
        "グルメ/reserve@yoyaku.buffet.gyukaku.ne.jp",
        "グルメ/牛角アプリ事務局",
    ]),
    ("グルメ/スシロー", [
        "グルメ/【スシローお持ち帰りネット注文】",
        "NoReply",     # akindo-sushiro.co.jp
    ]),
    ("グルメ/ぐるなび", [
        "グルメ/ぐるなびネット予約",
        "グルメ/楽天ぐるなび",
    ]),
    ("グルメ/Oisix", [
        "【Oisix】",
        "【Oisix × Pontaポイント】",
    ]),
    ("グルメ/かっぱ寿司", [
        "かっぱ寿司",
    ]),
    ("グルメ/やっちゃばマルシェ", [
        "やっちゃばマルシェ",
    ]),
    ("グルメ/EPARK", [
        "EPARK",
        "EPARKおでかけ",
    ]),

    # ──────────────────────────────────────────────────────────
    # マネー・金融
    # ──────────────────────────────────────────────────────────
    ("マネー・金融/証券/野村証券", [
        "マネー・金融/野村証券",
        "マネー・金融/野村證券",
        "マネー・金融/nomura",
        "マネー・金融/野村メール交付",
        "マネー・金融/野村證券確定拠出年金部",
        "野村證券株式会社",
    ]),
    ("マネー・金融/銀行/横浜銀行", [
        "マネー・金融/横浜銀行コンタクトセンター",
        "マネー・金融/横浜銀行セミナー事務局",
        "マネー・金融/株式会社 横浜銀行",
        "マネー・金融/銀行/〈はまぎん〉マイダイレクト",
    ]),
    ("マネー・金融/銀行/オリックス銀行", [
        "マネー・金融/オリックス銀行",
        "マネー・金融/オリックス銀行 キャンペーンデスク",
        "マネー・金融/オリックス/オリックス銀行株式会社",
    ]),
    ("マネー・金融/クレジットカード/三井住友カード", [
        "マネー・金融/三井住友カード",     # 2階層の重複を3階層へ
    ]),
    ("マネー・金融/家計/Ponta", [
        "マネー・金融/Ponta Web（旧リクルートポイントサイト）",
        "マネー・金融/PontaWeb（旧リクルートポイントサイト）",
        "マネー・金融/Pontaからのお知らせ",
        "マネー・金融/ponta",
        "マネー・金融/【PontaWeb】",
        "マネー・金融/【みんなのPontaナビ】",
    ]),
    ("マネー・金融/家計/Google Pay", [
        "マネー・金融/Google Pay",
        "マネー・金融/Google Payments",
        "マネー・金融/Google Wallet",
    ]),
    ("マネー・金融/家計/MoneySense", [
        "MoneySense",
    ]),
    ("マネー・金融/仮想通貨/Bybit", [
        "bybit",
    ]),
    ("マネー・金融/仮想通貨/CROWDLOAN 事務局", [
        "マネー・金融/仮想通貨/crowdloan",
    ]),
    ("マネー・金融/仮想通貨/MZDAO", [
        "MZDAO",
    ]),
    ("マネー・金融/クレジットカード/クレファン", [
        "クレファン",
    ]),

    # ──────────────────────────────────────────────────────────
    # 保険
    # ──────────────────────────────────────────────────────────
    ("保険/アイペット損保", [
        "ipet-ins",
        "保険/アイペット損害保険",
        "保険/アイペット損害保険株式会社",
        "保険/お申込み手続きが完了｜アイペット損保",
        "保険/アイペット損保│うちの子フォトコンテスト2022事務局",
        "保険/ワンにゃんかるた事務局｜アイペット損保",
    ]),
    ("保険/フコク生命", [
        "保険/フコク生命／資料受付係",
        "保険/フコク生命／資料請求受付担当",
    ]),
    ("保険/全国共済", [
        "保険/全国共済 (no-reply@zenkokukyosai.or.jp)",
        "保険/全国共済神奈川県生活協同組合",
    ]),
    ("保険/損保ジャパン", [
        "保険/損保ジャパン日本興亜",
        "保険/損保ジャパン日本興亜カスタマーセンター",
        "保険/損害保険ジャパン株式会社 損保ジャパン 共通ID（送信専用）",
    ]),
    ("保険/弁護士費用保険", [
        "保険/弁護士費用保険担当",
    ]),
    ("保険/AIG", [
        "保険/aig",
        "保険/no-reply-aiuinsurance@aig.com",
    ]),

    # ──────────────────────────────────────────────────────────
    # 宅配・物流
    # ──────────────────────────────────────────────────────────
    ("宅配・物流/FedEx", [
        "宅配・物流/FedEx Delivery Manager",
        "宅配・物流/FedEx Tracking",
        "宅配・物流/FedEx.com Online Services",
        "宅配・物流/TrackingUpdates@fedex.com",
    ]),
    ("宅配・物流/佐川急便", [
        "宅配・物流/佐川急便スマートクラブ",
        "宅配・物流/佐川急便（株）メルマガ事務局",
    ]),

    # ──────────────────────────────────────────────────────────
    # ヘルス・美容
    # ──────────────────────────────────────────────────────────
    ("ヘルス・美容/ユーグレナ", [
        "ヘルス・美容/euglena",
        "ヘルス・美容/ユーグレナ ヘルスケア・ラボ",
        "ヘルス・美容/ユーグレナ・オンライン",
        "ヘルス・美容/ユーグレナ・オンラインショップ",
    ]),
    ("ヘルス・美容/FANCL", [
        "ヘルス・美容/ファンケルオンライン",
    ]),
    ("ヘルス・美容/IQOS", [
        "IQOS",
        "IQOSチーム",
    ]),
    ("ヘルス・美容/フィットネス/メガロス", [
        "ヘルス・美容/フィットネス/メガロス相模大野",
        "mymegalos",
    ]),

    # ──────────────────────────────────────────────────────────
    # 旅行
    # ──────────────────────────────────────────────────────────
    ("旅行/ホテル/アパホテル", [
        "旅行/アパホテル〈大垣駅前〉",
        "旅行/アパホテル〈富山駅前〉",
        "旅行/アパホテル〈富山駅前南〉",
        "旅行/アパホテル〈金沢片町〉EXCELLENT",
        "旅行/アパホテル株式会社",
        "旅行/アパヴィラホテル〈富山駅前〉",
        "旅行/メールマガジン・アパホテル",
    ]),
    ("旅行/ホテル/Grand Mercure", [
        "旅行/Grand Mercure Lake Hamana Resort & Spa",
        "旅行/Grand Mercure Okinawa Cape Zanpa Resort",
        "旅行/Grand Mercure Yatsugatake Resort & Spa",
    ]),
    ("旅行/Hotels.com", [
        "旅行/Hotels.com Rewards",
        "旅行/Hotels.com ジャパン",
        "旅行/ホテルズドットコム ジャパン",
    ]),
    ("旅行/ALL Accor", [
        "旅行/ALL - Accor Live Limitless",
    ]),
    ("旅行/SKYTICKET", [
        "旅行/'skyticket [スカイチケット]'",
        "旅行/スカイチケットレンタカー",
    ]),
    ("旅行/DFS", [
        "旅行/LOYAL T by DFS",
        "旅行/ロイヤルT by DFS",
    ]),
    ("旅行/Agoda", [
        "旅行/Agoda Customer Care",
    ]),
    ("旅行/東横INN", [
        "旅行/toyoko-inn",
        "旅行/東横INN予約システム",
    ]),
    ("旅行/HoteLux", [
        "旅行/HoteLuxJP",
    ]),
    ("旅行/Trip.com", [
        "旅行/jp_hotel@trip.com",
        "旅行/携程旅行网酒店预订部（海外）",
        "旅行/Trip.com Rewards",
    ]),
    ("旅行/ANAインターコンチネンタルホテル東京", [
        "Restaurant-Reservation",
    ]),
    # えきねっとはJR予約サービス → 旅行/予約/JR へ
    ("旅行/予約/JR", [
        "交通・移動/交通/えきねっと",
    ]),

    # ──────────────────────────────────────────────────────────
    # セキュリティ
    # ──────────────────────────────────────────────────────────
    ("セキュリティ/カスペルスキー", [
        "セキュリティ/kasperskystore",
        "セキュリティ/カスペルスキーストア",
        "セキュリティ/カスペルスキー月額サービス",
    ]),

    # ──────────────────────────────────────────────────────────
    # 通信キャリア
    # ──────────────────────────────────────────────────────────
    ("通信キャリア/au", [
        "通信キャリア/au STAR",
        "通信キャリア/au WALLET ポイントプログラム 貯める",
        "通信キャリア/au WALLETポイント貯める",
        "通信キャリア/au one メールからのお知らせ",
        "通信キャリア/auone",
        "通信キャリア/auからの重要なお知らせ",
        "通信キャリア/auでんき申し込み受付",
        "通信キャリア/auサポート情報",
        "通信キャリア/auマイプレミアショップ",
        "通信キャリア/auメルマガ",
        "通信キャリア/kddi",
        "通信キャリア/kddi-fs",
        "通信キャリア/マイプレミアショップ",
        "プラスポイントアンケート",
        "ホットインフォ",
    ]),
    ("通信キャリア/povo", [
        "通信キャリア/povo2.0からの重要なお知らせ",
        "通信キャリア/povo2.0からの重要なご案内",
        "通信キャリア/【povo2.0運営事務局】",
    ]),
    ("通信キャリア/docomo", [
        "通信キャリア/(株)NTTドコモ",
        "通信キャリア/docomo-de",
        "通信キャリア/mydocomo",
        "通信キャリア/dPOINT CLUB",
        "通信キャリア/dpoint",
        "通信キャリア/dポイントクラブアンケート",
        "通信キャリア/d払い",
    ]),
    ("通信キャリア/SoftBank", [
        "通信キャリア/softbank",
        "通信キャリア/ソフトバンクオンラインショップ",
        "通信キャリア/ソフトバンク／ワイモバイル",
    ]),
    ("通信キャリア/NTT", [
        "通信キャリア/NTT Communications",
        "通信キャリア/NTTコミュニケーションズ株式会社",
        "通信キャリア/NTTぷらら",
        "通信キャリア/ＮＴＴ東日本",
    ]),
    ("通信キャリア/ISP/ネットフォレスト", [
        "通信キャリア/ISP/ISPサポートセンター",
        "通信キャリア/ISP/isp-support",
        "通信キャリア/ISP/ネットフォレスト ISPサポートセンター（マイページ）",
        "通信キャリア/ISP/（株）ネットフォレスト ISP サポートセンター",
    ]),

    # ──────────────────────────────────────────────────────────
    # 住まい
    # ──────────────────────────────────────────────────────────
    ("住まい/不動産/野村不動産", [
        "住まい/野村不動産(プラウドつくば)",
        "住まい/野村不動産(プラウド中野島)",
        "住まい/野村不動産(プラウド水戸三の丸)",
        "住まい/野村不動産(プラウド水戸桜川)",
        "住まい/野村不動産(周年記念)",
    ]),
    ("住まい/不動産/住まいの広場TOWNS", [
        "住まい/不動産/sumainohiroba",
        "住まい/不動産/株式会社住まいの広場ＴＯＷＮＳ",
        "住まい/不動産/株式会社住まいの広場ＴＯＷＮＳ ㈱住まいの広場",
        "住まい/不動産/株式会社住まいの広場ＴＯＷＮＳ 小野",
        "住まい/不動産/株式会社住まいの広場ＴＯＷＮＳ 松岡",
    ]),
    ("住まい/不動産/カウル", [
        "カウル運営事務局",
    ]),
    ("住まい/不動産/タブルーム", [
        "タブルーム編集部",
    ]),
    ("住まい/リフォーム/Benry", [
        "住まい/リフォーム/Benry東林間店",
        "住まい/リフォーム/benry",
    ]),
    ("住まい/白洋舍", [
        "白洋舍",
    ]),

    # ──────────────────────────────────────────────────────────
    # 自動車・バイク
    # ──────────────────────────────────────────────────────────
    ("自動車・バイク/カー用品/アトラス", [
        "アトラスダイレクトショップ",
    ]),
    ("自動車・バイク/バイク/アップス", [
        "自動車・バイク/バイク/ups-bike",
        "自動車・バイク/バイク/アップスバイク編集部",
        "自動車・バイク/バイク/バイク売買サイト【アップス】",
    ]),
    ("自動車・バイク/バイク/RENTAL819", [
        "自動車・バイク/バイク/Rental819 Web Reservation",
    ]),
    ("自動車・バイク/バイク/MotoSpot", [
        "自動車・バイク/バイク/モトスポット",
    ]),
    ("自動車・バイク/自動車/グーネット買取", [
        "自動車・バイク/自動車/【グーネット買取】",
    ]),
    ("自動車・バイク/自動車/Volvo Car Japan", [
        "自動車・バイク/自動車/volvocars",
    ]),
    ("自動車・バイク/日産レンタカー 沖縄（予約システム）", [
        "【日産レンタカー】",
    ]),
    ("自動車・バイク/自動車/タイヤフィッティングサービス株式会社", [
        "自動車・バイク/自動車/タイヤフィッター横浜町田店",
        "自動車・バイク/自動車/タイヤフィッティングサービス株式会社 本社",
    ]),

    # ──────────────────────────────────────────────────────────
    # 交通・移動
    # ──────────────────────────────────────────────────────────
    ("交通・移動/駐車場/akippa", [
        "交通・移動/駐車場/akippa（あきっぱ）",
    ]),
    ("交通・移動/交通/モバイルSuica", [
        "交通・移動/交通/mobilesuica",
    ]),

    # ──────────────────────────────────────────────────────────
    # レジャー・チケット
    # ──────────────────────────────────────────────────────────
    ("レジャー・チケット/レジャー/コニカミノルタプラネタリウム", [
        "レジャー・チケット/コニカミノルタプラネタリウム 満天",
        "レジャー・チケット/コニカミノルタプラネタリウム 満天 (池袋サンシャインシティ)",
        "コニカミノルタプラネタリウム\"満天\"",
    ]),
    ("レジャー・チケット/チケット/三栄チケットサービス", [
        "レジャー・チケット/チケット/三栄IDからのご案内［三栄ID事務局］",
        "レジャー・チケット/チケット/三栄ID事務局",
    ]),
    ("レジャー・チケット/レジャー/デジキューBBQ", [
        "レジャー・チケット/レジャー/バーベキュー予約センター",
    ]),
    ("レジャー・チケット/チケット/Etix", [
        "etix",
    ]),

    # ──────────────────────────────────────────────────────────
    # 転職（フラットの重複を既存階層へ）
    # ──────────────────────────────────────────────────────────
    ("転職/リクルートエージェント求人紹介", [
        "転職",      # フラット「転職」は bizreach等が入っており既存ラベルと重複
        "転職/RECRUIT AGENT_2",
    ]),
]

# =====================================================================
# ユーティリティ
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
    all_labels = resp.get("labels", [])
    name2id = {l["name"]: l["id"] for l in all_labels}
    return name2id


def is_excluded(name):
    return any(name.startswith(p) for p in EXCLUDE_PREFIXES)


def ensure_label(svc, name2id, name):
    """ラベルが存在しなければ作成してIDを返す"""
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
            # 既存ラベルを再取得
            resp = svc.users().labels().list(userId="me").execute()
            for lbl in resp.get("labels", []):
                name2id[lbl["name"]] = lbl["id"]
            if name in name2id:
                print(f"    ✅ 既存: 「{name}」(ID再取得)")
                return name2id[name]
            # 大文字小文字などを無視した緩いマッチ
            name_lower = name.lower().strip()
            for lbl_name, lbl_id in name2id.items():
                if lbl_name.lower().strip() == name_lower:
                    print(f"    ✅ 既存(緩いマッチ): 「{lbl_name}」")
                    name2id[name] = lbl_id
                    return lbl_id
            # それでも見つからない場合はスキップ（Gmail側の制約）
            print(f"    ⚠️  作成できず(409)、スキップ: 「{name}」")
            print(f"       類似ラベル: {[n for n in name2id if name.split('/')[-1].lower() in n.lower()][:5]}")
            # dummy IDを返しても移動失敗するので None を返し呼び出し元でスキップ
            return None
        raise


def merge_label(svc, name2id, src_name, dst_id):
    """src の全スレッドを dst に移動し src を削除"""
    src_id = name2id.get(src_name)
    if src_id is None:
        print(f"    ⚠️  NOT FOUND (スキップ): 「{src_name}」")
        return 0

    # スレッド取得
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
    if DRY_RUN:
        print("🔍 DRY RUN モード（変更なし）")
    else:
        print("🚀 本番実行モード")

    svc = get_service()
    name2id = load_labels(svc)
    print(f"  ラベル総数: {len(name2id)} 件\n")

    total_merged = 0
    total_threads = 0

    for dst_name, sources in CLUSTER_MERGES:
        if is_excluded(dst_name):
            print(f"  ⛔ 除外: {dst_name}")
            continue

        # 実際に存在するsourceだけを対象に
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
