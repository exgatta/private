#!/usr/bin/env python3
"""
Gmail ラベル整理スクリプト
サービス提供元ごとにラベルを入れ子（ネスト）構造に統合します。

使い方:
  python label_consolidation.py           # 実際に実行
  python label_consolidation.py --dry-run # 変更内容のプレビューのみ（変更しない）
"""

import json
import os
import sys
import time

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from google.cloud import secretmanager

# ─── 設定 ─────────────────────────────────────────────────────────────────────
PROJECT_ID = "gmail-manager-auto"
DRY_RUN = "--dry-run" in sys.argv
# ──────────────────────────────────────────────────────────────────────────────


LOCAL_CREDS_PATH = os.path.expanduser("~/.gmail_local_credentials.json")


def get_gmail_service():
    import google.auth.transport.requests

    # USE_LOCAL=1 の場合はローカル認証ファイルを使用（get_local_token.py で生成）
    if os.getenv("USE_LOCAL", "0") == "1":
        if not os.path.exists(LOCAL_CREDS_PATH):
            print(f"❌ ローカル認証ファイルが見つかりません: {LOCAL_CREDS_PATH}")
            print("   先に get_local_token.py を実行してください。")
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

    # デフォルト: Secret Manager からトークンを取得（Cloud Run 用）
    client = secretmanager.SecretManagerServiceClient()
    name = f"projects/{PROJECT_ID}/secrets/gmail-oauth-credentials/versions/latest"
    resp = client.access_secret_version(request={"name": name})
    d = json.loads(resp.payload.data.decode())
    creds = Credentials(
        token=None,
        refresh_token=d["refresh_token"],
        token_uri=d.get("token_uri", "https://oauth2.googleapis.com/token"),
        client_id=d["client_id"],
        client_secret=d["client_secret"],
    )
    creds.refresh(google.auth.transport.requests.Request())
    return build("gmail", "v1", credentials=creds, cache_discovery=False)


def fetch_all_labels(svc):
    """全ユーザーラベルを {name: id} のdictで返す"""
    result = svc.users().labels().list(userId="me").execute()
    return {lbl["name"]: lbl["id"] for lbl in result.get("labels", [])}


def rename_label(svc, label_id, new_name, old_name):
    """ラベルをリネームする（DRY_RUNの場合は出力のみ）"""
    if DRY_RUN:
        print(f"  [DRY-RUN] '{old_name}'  →  '{new_name}'")
        return True
    try:
        svc.users().labels().patch(
            userId="me",
            id=label_id,
            body={"name": new_name}
        ).execute()
        print(f"  ✅ '{old_name}'  →  '{new_name}'")
        time.sleep(0.3)  # レートリミット対策
        return True
    except Exception as e:
        print(f"  ❌ '{old_name}' リネーム失敗: {e}")
        return False


# ─── 統合ルール（トピックベース）────────────────────────────────────────────
# 形式: "親ラベル名": ["子ラベル名1", "子ラベル名2", ...]
# 子ラベル "X" は "親/X" にリネームされます（フラットラベルのみ対象）。
# 親ラベル名と同名の子はスキップ。存在しないラベルは自動的にスキップ。
#
# 22 トピック親:
#   テック・アプリ / ゲーム / エンタメ配信 / SNS /
#   ショッピング / マネー・金融 / 通信キャリア / 旅行 /
#   グルメ / 交通・移動 / 自動車・バイク / ヘルス・美容 /
#   医療 / 保険 / 住まい / 子育て /
#   レジャー・チケット / ニュース・メディア / AI・クラウド /
#   セキュリティ / 行政 / 宅配・物流
# + 転職 / エネルギー（小規模のため独立維持）

RULES = {

    # ── テック・アプリ ────────────────────────────────────────────────────────
    "テック・アプリ": [
        # Google（汎用・アカウント系）
        "Gmail", "Gmail チーム", "Inbox by Gmail",
        "Google カレンダー", "Google Calendar",
        "Google Photos", "Google Home", "Google Home Mini",
        "Google Chromecast", "Google アシスタント",
        "Google News", "Google Gemini", "Google One",
        "Google フォーム",
        "Google+", "Google+ Team", "Google Cloud",
        "Google Account", "Google Antigravity", "Google Location History",
        "Bard", "Bard - Google による試験運用中の AI サービス",
        "NotebookLM", "ファミリー リンク",
        "デバイスを探す", "Google の「デバイスを探す」",
        "The Google team", "The Google Workspace Team",
        "Google Workspace チーム", "The G Suite Team",
        "The Google Cloud Team", "The Google Account Team",
        "The Google Play Team", "サポート自動化マクロ",
        "はせとも さん(Google フォト経由)",
        # Apple
        "iCloud", "iTunes", "iTunes Store", "Find My iPhone",
        # Microsoft
        "Microsoft アカウント チーム", "Microsoft account team",
        "Microsoft Cashback", "Microsoft Family Safety",
        "Microsoft OneDrive", "OneDrive",
        "Microsoft Outlook", "Microsoft Rewards", "outlook",
        # Adobe
        "Adobe Creative Cloud", "Adobe Document Cloud",
        "Adobe Support Community Mailer", "'Adobe'", "acrobat",
        # Sony（ハードウェア・ストア系。ゲーム系は「ゲーム」へ）
        "My Sony", "My Sony Club", "ソニーストア", "sonycreativesoftware",
        # Logicool
        "Logitech", "Logi Support",
        # DJI
        "DJI JAPAN (DJI Support)", "DJI Support",
        # Parallels
        "Parallels - Cleverbridge Payment Processing",
        # TeamViewer
        "teamviewer", "TeamViewer Info", "TeamViewer Sign In Confirmation",
        # ソースネクスト
        "ソースネクスト・インフォメーションセンター", "SOURCENEXT",
        # Dropbox
        "The Dropbox Team", "Dropbox",
        # GMO
        "GMOとくとくショッピング", "GMOとくとくポイント", "GMOとくとく通信",
        "gmo-pg", "gmo-ps",
        # FC2
        "FC2 Information", "FC2,inc", "fc2",
        # 音響機器
        "パイオニア ID", "パイオニア（株）", "Pioneer COCCHi info",
        "ポータブルアンプ専門店 ケイズアンプ", "amulech", "プロケーブル", "ProCable",
        # カメラ・ジンバル
        "Pilotflyジンバルネットショップ", "ReelSteady", "ReelSteady Purchases", "ceeniu",
    ],

    # ── ゲーム ────────────────────────────────────────────────────────────────
    "ゲーム": [
        # Sony PlayStation 系
        "PlayStation Network", "PlayStation",
        "ソニー・コンピュータエンタテインメント", "sonyentertainmentnetwork",
        "SCE インフォメーションセンター", "SCEJ オンライン受付サービス",
        "SIEJA 延長保証受付サービス",
        # Steam
        "Steam Support", "Steam Team", "Steam Store", "Steam サポート",
        # SQUARE ENIX
        "SQUARE ENIX BRIDGE", "FINAL FANTASY XIV", "Square Enix Account",
        # Nintendo
        "nintendo",
        # SEGA
        "SEGA ID", "SEGA IDサポート",
        # DMM / DLsite
        "dmm", "DMM.com", "DMM.com証券カスタマーサポート",
        "DLsite", "DLsite サポート係", "XFLAG ID",
        # Google Play（アプリ・ゲームストア）
        "Google Play",
        # GeForce NOW
        "GeForce NOW Powered by au",
        "GeForce NOW Powered by SoftBank 送信専用",
        # Niantic
        "Pokémon GO", "Team GO Rocket Grunt",
        # HoYoverse
        "hoyoverse", "mihoyo",
        # Capcom
        "Capcom Online Games", "カプコンオンラインゲームズ",
        # 海外メーカー
        "NCSOFT", "Paradox Interactive", "rockstargames",
        "Kakao Games", "Ubisoft", "Gaijin.Net Team",
        # 日本スマホゲーム
        "kingdom-conquest", "dragonquest",
        "Ateam Inc.", "AteamID",
        "株式会社エイチームエンターテインメント", "株式会社エイチーム",
        "『リネージュ2 レボリューション』運営チーム",
        "『CARAVANSTORIES』運営チーム",
        "【三国大戦スマッシュ！】運営チーム",
        "蒼焔の艦隊", "Dark War Survival",
        # プラットフォーム
        "Roblox", "Roblox no-reply",
        "pso2admin@isao.net",
    ],

    # ── エンタメ配信 ──────────────────────────────────────────────────────────
    "エンタメ配信": [
        # YouTube
        "YouTube", "YouTube Music", "YouTube Kids", "YouTube Premium",
        "Google Play Music",
        # Amazon
        "Prime Video",
        # ニコニコ
        "niconico", "nicovideo",
        "【ニコニコ動画】", "【ニコニコ動画】ニコレポメール",
        "【niconico】ニコレポメール", "【niconico】",
        # mora / e-onkyo（音楽ダウンロード）
        "mora[モーラ]", "mora qualitas",
        "mora qualitas News", "mora qualitasお知らせ",
        "e-onkyo", "e-onkyo music", "OTOTOY MUSIC STORE",
        # レコチョク
        "【レコチョク】", "＜レコチョク＞", "recochoku",
        "レコチョク Bestおすすめ", "レコチョク 日刊レコチョク通信",
        "レコチョク 新着情報", "レコチョク ランキング",
        # 動画配信サービス
        "U-NEXT", "Hulu", "TVer", "b-ch",
        # 音楽ストリーミング
        "Spotify", "Deezer", "Deezer Support", "Qobuz Japan",
        # 電子書籍・マンガ
        "BookLive!事務局", "まんが王国", "piccoma",
        "cmoa", "lezhin", "ヤングマガジン",
        "タダ読みお知らせ便", "マガジン☆WALKER",
        "support-mangabang",
    ],

    # ── SNS ───────────────────────────────────────────────────────────────────
    "SNS": [
        "Facebook", "Twitter", "Instagram",
        "LINE", "LINE Creators Market",
        "Discord", "mixi", "TikTok",
        # Ameba（ブログ・SNS）
        "アメーバ", "Ameba（アメーバ）", "アメブロ",
        "アメーバ最新ニュース", "アメーバ事業本部", "アメマガ",
    ],

    # ── ショッピング ──────────────────────────────────────────────────────────
    "ショッピング": [
        # Amazon（EC本体）
        "Amazon.jp", "AMAZON", "Android Market",
        # 楽天（EC・ポイント系）
        "楽天市場", "楽天市場からのお知らせ",
        "楽天ペイからの重要なお知らせ", "楽天でんわ",
        "岩手県花巻市ふるさと納税",
        # ZOZOTOWN
        "zozo",
        # ファッション
        "＜ユニクロ＞", "＜ユニクロ オンラインストア＞",
        "＜ユニクロ・ジーユー＞", "fastretailing",
        "nano・universe", "nano-u",
        "アルペングループ オンラインストア",
        # 家電量販
        "ノジマ：お得情報配信局",
        "support@cc.biccamera.com",
        "ソフマップ・ドットコム", "ビックカメラ.com", "ヨドバシ・ドット・コム",
        "エディオンネットショップ", "edion",
        "ひかりTVショッピング", "hikaritv",
        "PCボンバー", "pcbomber",
        "PREMOA.co.jp", "premoa本店", "総合通販PREMOA（プレモア）", "総合通販プレモア",
        "kaden119-shop", "カデンの救急社",
        "パソコン純正パーツ販売 PC-SUPPLY", "pcdunion", "ピーシーデポグループユニオン連合会",
        # モノタロウ（工具・業務用品）
        "株式会社MonotaRO", "MonotaRO.com", "MonotaROサポートセンター",
        # フリマ・C2C
        "メルカリ", "メルペイ",
        "ラクマ", "ラクマカスタマーサポート",
        "新ラクマカスタマーサポート（旧フリル）",
        "ヤフオク", "AliExpress", "Qoo10",
        # セブン&アイ
        "セブン＆アイ・ホールディングス", "セブンマイルプログラム", "オムニ7",
        # ANA ショッピング
        "ANAショッピングA-style",
    ],

    # ── マネー・金融 ──────────────────────────────────────────────────────────
    "マネー・金融": [
        # 野村グループ（証券・資産運用）
        "野村証券", "野村證券", "野村證券確定拠出年金部",
        "野村メール交付", "nomura",
        # 楽天証券
        "楽天証券",
        # 三井住友（銀行・カード）
        "三井住友銀行", "三井住友カード",
        # 横浜銀行
        "横浜銀行コンタクトセンター", "横浜銀行セミナー事務局", "株式会社 横浜銀行",
        # オリックス銀行
        "オリックス銀行", "オリックス銀行株式会社",
        "オリックス銀行 キャンペーンデスク",
        # その他銀行
        "三菱UFJ銀行", "みずほ銀行",
        "関西アーバン銀行",
        "静岡中央銀行 ダイレクトセンター",
        "〈はまぎん〉マイダイレクト",
        "オリコ事務センター",
        "SMBCファイナンスサービス株式会社",
        # クレジットカード・後払い
        "PayPayカード",
        "ライフカードからのお知らせ",
        "American Express", "American Express Network", "American Express SafeKey",
        "paypal",
        "NP後払い", "NP後払い[送信専用]",
        "UC永久不滅ポイント",
        "OMC Plus", "「OMC Plus」Mail Magazine",
        "【セディナ】OMC Plusメールマガジン",
        "株式会社セディナ", "セディナビ",
        "Vポイントサイト",
        "J.Score", "株式会社J.Score(ジェイスコア)",
        # Paidy（後払い）
        "ペイディ", "ペイディカスタマーサポート",
        # ポイント・マイレージ
        "Pontaからのお知らせ", "【PontaWeb】", "ponta",
        "PontaWeb（旧リクルートポイントサイト）",
        "Ponta Web（旧リクルートポイントサイト）",
        "【みんなのPontaナビ】",
        # 仮想通貨
        "Coincheck", "GMOコイン", "bitflyer", "Bybit",
        "brilliantcrypto", "CROWDLOAN 事務局", "crowdloan",
        # 家計管理・ポイ活
        "MoneyForward", "Moneytree",
        "ハピタス",
        "ためる事務局", "ポイントためる事務局",
        "JRE POINT事務局", "jrepoint",
        "Miles Japan", "Miles Japan Rewards",
        # Google ウォレット・決済
        "Google Wallet", "Google Pay", "Google Payments",
    ],

    # ── 通信キャリア ──────────────────────────────────────────────────────────
    "通信キャリア": [
        # au / KDDI
        "auサポート情報", "auからの重要なお知らせ",
        "auマイプレミアショップ", "マイプレミアショップ",
        "auメルマガ", "auone", "au one メールからのお知らせ",
        "au STAR", "au WALLET ポイントプログラム 貯める",
        "au WALLETポイント貯める", "auでんき申し込み受付",
        "povo.jp", "povo2.0からの重要なお知らせ",
        "【povo2.0運営事務局】", "povo2.0からの重要なご案内",
        "IIJmio", "kddi", "kddi-fs",
        # ドコモ
        "(株)NTTドコモ", "docomo-de", "mydocomo",
        "dポイントクラブアンケート", "dPOINT CLUB", "dpoint", "d払い",
        # SoftBank
        "softbank", "ソフトバンク／ワイモバイル",
        "ソフトバンクオンラインショップ",
        # NTT
        "ＮＴＴ東日本", "NTTコミュニケーションズ株式会社",
        "NTT Communications", "NTTぷらら",
        # ISP
        "OCN モバイル ONE お友達紹介キャンペーン",
        "OCN 重要なお知らせ",
        "【OCN・goo dポイントがたまる！つかえる！】おトクなポイント情報",
        "ネットフォレスト ISPサポートセンター（マイページ）",
        "（株）ネットフォレスト ISP サポートセンター",
        "ISPサポートセンター", "isp-support", "wifi-cloud",
        "ぷららサポートセンター", "accessnet",
        "OCEANweb（オーシャンウェブ）公式通販サイト", "オーシャンウェブ",
    ],

    # ── 旅行 ──────────────────────────────────────────────────────────────────
    "旅行": [
        # ANA
        "ANAマイレージモール運営事務局", "ＡＮＡインターネットツアーデスク",
        # ホテル
        "アパホテル株式会社",
        "アパホテル〈富山駅前南〉", "アパホテル〈富山駅前〉",
        "アパヴィラホテル〈富山駅前〉",
        "アパホテル〈大垣駅前〉",
        "アパホテル〈金沢片町〉EXCELLENT",
        "メールマガジン・アパホテル",
        "Hotels.com Rewards", "ホテルズドットコム ジャパン", "Hotels.com ジャパン",
        "ANAインターコンチネンタルホテル東京",
        # OTA・旅行予約
        "Trip.com Rewards", "jp_hotel@trip.com", "携程旅行网酒店预订部（海外）",
        "オリックスレンタカー",
        "じゃらんnet",
        "一休.com", "一休.comレストラン",
        "Expedia.co.jp",
        "Agoda", "Agoda Customer Care",
        "SKYTICKET", "'skyticket [スカイチケット]'",
        "スカイチケットレンタカー",
        "HoteLux", "HoteLuxJP",
        "Travy", "STAYNAVI",
        "近畿日本ツーリスト", "日本旅行",
        # ホテルチェーン会員
        "ALL - Accor Live Limitless", "ALL Accor",
        "World of Hyatt", "hoshinoresort",
        "東横INN", "東横INN予約システム", "toyoko-inn",
        "杉乃井ホテル",
        "Hilton Grand Vacations",
        "Grand Mercure Lake Hamana Resort & Spa",
        "Grand Mercure Okinawa Cape Zanpa Resort",
        "Grand Mercure Yatsugatake Resort & Spa",
        "courtyard",
        "SEIBU PRINCE CLUB",
        "インターネット予約センター／ホテルニューアワジグループ",
        "ホテル ウェルシーズン浜名湖",
        "リゾートホテル蓼科",
        # 空港・ラウンジ
        "Priority Pass",
        "DFS", "ロイヤルT by DFS", "LOYAL T by DFS",
        # 高速道路
        "速旅システム", "速旅ーNEXCO中日本",
        "ドラ割事務局（NEXCO東日本）",
    ],

    # ── グルメ ────────────────────────────────────────────────────────────────
    "グルメ": [
        # 焼肉きんぐ
        "焼肉きんぐ 町田店", "焼肉きんぐ つきみ野店",
        "焼肉きんぐ 横浜青葉台店", "焼肉きんぐ 三ツ境店",
        "焼肉きんぐ 佐久平店",
        # 出前館
        "no-reply@demae-can.com", "出前館サポート",
        "出前館カスタマーセンター", "出前館カスタマーセンター(PC)",
        "support@demae-can.com", "demae-can",
        # 楽天グルメ
        "楽天ぐるなび",
        # 飲食店・グルメ予約
        "日本マクドナルド",
        "ドミノ・ピザ ジャパン",
        "noreply@reservation.kurasushi.co.jp",
        "牛角アプリ事務局",
        "reserve@yoyaku.buffet.gyukaku.ne.jp",
        "【スシローお持ち帰りネット注文】",
        "ぐるなびネット予約",
        "ホットペッパーグルメ",
    ],

    # ── 交通・移動 ────────────────────────────────────────────────────────────
    "交通・移動": [
        # Google Maps
        "Google Maps", "Google Maps Timeline",
        # 公共交通・ナビ
        "モバイルSuica", "mobilesuica", "えきねっと",
        "maasjapan", "ETC", "ringopass", "navitime",
        "JALABC自動通知", "JALショッピング",
        # レンタカー
        "ニッポンレンタカー 沖縄（予約システム）",
        "(株)トヨタレンタリ−ス京都 info",
        "トヨタレンタリース新大阪 予約センター",
        "GOサポート",
        "沖楽 - 沖縄レンタカー予約 -",
        "フリーダムレンタカー",
        # 駐車場
        "タイムズのB", "タイムズクラブ",
        "P2P3駐車場予約システム",
        "akippa", "akippa（あきっぱ）",
        "軒先パーキング", "成田空港パーキング",
        "timescar",
    ],

    # ── 自動車・バイク ────────────────────────────────────────────────────────
    "自動車・バイク": [
        # 日産
        "日産自動車", "nissan", "NISSAN ONLINE SHOP",
        "[日産] N-Link OWNERS", "日産フィナンシャルサービス",
        "日産カード リボ宣言Web受付",
        "日産レンタカー 沖縄（予約システム）",
        "日産サティオ千葉 成田店",
        "日産：車検／点検ご案内事務局",
        "日産プリンス福島 関根 祥太",
        "日産プリンス神奈川 木島 亜悠",
        "【いつも笑顔の日産レンタカー】",
        "postoffice@nissan.co.jp",
        # オリックス自動車
        "オリックス自動車",
        # 車査定・カーディーラー
        "カーセンサーnet",
        "グーネット買取", "【グーネット買取】",
        "かんたん車査定ガイド", "みんカラ",
        "lexus.jp",
        "Volvo Car Japan", "volvocars",
        "ボルボ・カーつくば 高野 英明", "ボルボ・カー つくば",
        "net-shaken", "MEGAWEB",
        # タイヤ
        "タイヤフィッティングサービス株式会社", "タイヤフィッティングサービス株式会社 本社",
        "タイヤフィッター横浜町田店", "タイヤフィッタ－",
        "タイヤセンターJEI", "タイヤセンターJEI 相模原店",
        "ダンロップファルケンタイヤ お客様相談室窓口",
        # バイク
        "ウェビック", "ウェビックキャンペーン",
        "バイク比較ドットコム",
        "アップスバイク編集部", "バイク売買サイト【アップス】", "アップス", "ups-bike",
        "MotoJP", "モトスポット", "MotoSpot",
        "MotorFanTECHメルマガ[モーターファン]", "Motor-Fan",
        "RENTAL819", "Rental819 Web Reservation",
        "モトメガネ 楽天市場店",
        "ナップスメンバーズカードサービス",
    ],

    # ── ヘルス・美容 ──────────────────────────────────────────────────────────
    "ヘルス・美容": [
        # ユーグレナ
        "ユーグレナ・オンラインショップ", "ユーグレナ ヘルスケア・ラボ",
        "euglena", "ユーグレナ・オンライン",
        # 美容・コスメ
        "FANCL", "ファンケルオンライン",
        "株式会社MTG お客様相談室",
        "CLINICS運営事務局",
        # フィットネス
        "メガロス相模大野", "megalos-kids-app",
        "ネイス体操教室",
        "SuperSportsXEBIO", "XEBIO OnlineStore事務局",
    ],

    # ── 医療 ──────────────────────────────────────────────────────────────────
    "医療": [
        "WEB問診システム", "h-p-m-monshin", "dent-ys",
        "（一社）専門医ヘルスケアネットワーク",
        "ＭＳＡケアＷｅｂサービス",
    ],

    # ── 保険 ──────────────────────────────────────────────────────────────────
    "保険": [
        # 損保ジャパン
        "損保ジャパン日本興亜",
        "損保ジャパン日本興亜カスタマーセンター",
        "損害保険ジャパン株式会社 損保ジャパン 共通ID（送信専用）",
        "sompo-swt",
        # アイペット
        "アイペット損害保険", "アイペット損害保険株式会社",
        "アイペット損保│うちの子フォトコンテスト2022事務局",
        "お申込み手続きが完了｜アイペット損保",
        "ワンにゃんかるた事務局｜アイペット損保",
        # 三井住友海上
        "三井住友海上あいおい生命",
        # その他保険
        "フコク生命", "フコク生命／資料請求受付担当", "フコク生命／資料受付係",
        "SBI損保",
        "チューリッヒ生命保険株式会社",
        "明治安田生命",
        "no-reply-aiuinsurance@aig.com", "aig",
        "スマホでピタッと充実保険",
        "全国共済神奈川県生活協同組合",
        "全国共済 (no-reply@zenkokukyosai.or.jp)",
        "セゾン自動車火災保険株式会社",
        "AIほけん",
        "弁護士費用保険担当", "弁護士費用保険",
        "アイエフクリエイト生命保険 連絡窓口",
        "株式会社アイ・エフ・クリエイト",
    ],

    # ── 住まい ────────────────────────────────────────────────────────────────
    "住まい": [
        # 野村不動産
        "野村不動産「プラウド中野島」販売準備室",
        "野村不動産「プラウドつくば」販売準備室",
        "野村不動産「プラウド水戸三の丸」販売準備室",
        "野村不動産「プラウド水戸桜川」販売準備室",
        "野村不動産「周年記念お客様感謝イベント事務局」",
        # 不動産・マンション
        "RENOSY（株式会社GA technologies運営）",
        "【Renosy】マンション探し",
        "三菱地所レジデンスからのお知らせ",
        "住友不動産販売株式会社 末永 健二",
        "大東建託株式会社 柏支店", "大東建託株式会社 野田店",
        "三興土地開発", "HOME4U運営事務局",
        "ザ・パークハウス 相模大野",
        "株式会社住まいの広場ＴＯＷＮＳ",
        "株式会社住まいの広場ＴＯＷＮＳ ㈱住まいの広場",
        "株式会社住まいの広場ＴＯＷＮＳ 小野",
        "株式会社住まいの広場ＴＯＷＮＳ 松岡",
        "SUENAGAマンションギャラリー",
        "ieshil", "sumainohiroba", "マンション",
        "長谷工の住まい",
        "不動産ジャパンサポートセンター",
        "一誠商事（株） みらい平支店",
        "五十嵐悟［一誠商事株式会社］",
        "住宅本舗",
        # リフォーム
        "リフォマサポート", "リフォームのことなら家仲間コム", "家仲間コム",
        "reform-market", "Benry東林間店", "benry",
        # スマートホーム
        "SwitchBot", "omronconnect", "Orbi", "TP-Link", "NETGEAR",
        # 引越し
        "アート引越センター", "サカイ引越センター",
        "サカイ引越センター インターネット課",
        "リロケーション情報センター", "リロネットサポートデスク",
        "relo", "relonet",
    ],

    # ── 子育て ────────────────────────────────────────────────────────────────
    "子育て": [
        "コドモン運営事務局", "まあむキッズ相模大野南口",
        "WEL-KIDS PHOTOお知らせ", "谷口台児童クラブ",
        "木下の保育園相模大野", "GakkenID事務局", "ベネッセ",
        "フレーベル館オンラインショップ つばめのおうち",
        "学校用品.net",
    ],

    # ── レジャー・チケット ────────────────────────────────────────────────────
    "レジャー・チケット": [
        # プラネタリウム
        'コニカミノルタプラネタリウム "満天"',
        "コニカミノルタプラネタリウム 満天",
        "コニカミノルタプラネタリウム 満天 (池袋サンシャインシティ)",
        # チケット
        "セブンチケット", "三栄チケットサービス",
        "三栄IDからのご案内［三栄ID事務局］", "三栄ID事務局",
        "eplus", "l-tike", "Etix",
        "TOHOシネマズ（株）", "ＵＳシネマＷＥＢ購入",
        "東京モーターサイクルショー オンラインチケット",
        # レジャー施設
        "ユニバーサル・スタジオ・ジャパン",
        "さがみ湖リゾートプレジャーフォレスト前売り券",
        "サンリオピューロランド",
        "GiGOアプリ",
        "アソビュー株式会社", "asoview",
        "富士芝桜まつり WEB予約",
        "グランスノー奥伊吹WEB予約システム",
        "ファンタジーキッズリゾート",
        "KoizumiAfrica・Lion・Safari",
        "奥道後 壱湯の守WEB会員",
        "ビュッフェレストラン「シーフォレスト」",
        "デジキューBBQCAFE デックス東京ビーチ店予約センター",
        "バーベキュー予約センター",
    ],

    # ── ニュース・メディア ────────────────────────────────────────────────────
    "ニュース・メディア": [
        "NewsPicks サポート窓口",
        "日経IDからのお知らせ", "日経ID事務局",
        "日経からのお知らせ", "日経電子版からのご案内",
        "BizHint 運営事務局",
        "クーリエ・ジャポン",
        "note 事務局", "note運営事務局",
        "アイティメディアID事務局",
        "／~＼Fujisan.co.jp",
    ],

    # ── AI・クラウド ──────────────────────────────────────────────────────────
    "AI・クラウド": [
        "Anthropic", "Anthropic, PBC",
        "Stability AI Japan",
        "天秤AI byGMO",
        "リートン", "Wrtn",
    ],

    # ── セキュリティ ──────────────────────────────────────────────────────────
    "セキュリティ": [
        # AdGuard
        "AdGuard VPN", "Adguard (via Paddle.com)",
        # カスペルスキー
        "カスペルスキー月額サービス", "カスペルスキーストア", "kasperskystore",
        # その他
        "Lookout Mobile Security", "norton",
        "Doctor Web", "Nord Account", "MasterUnlockCode",
    ],

    # ── 行政 ──────────────────────────────────────────────────────────────────
    "行政": [
        "マイナポータル",
        "個人番号カード交付申請書受付センター",
        "相模原市マイナンバーカード交付予約システム",
        "相模原市",
        "e-Tax（国税電子申告・納税システム）",
        "eLTAX 地方税お支払サイト",
        "日本年金機構",
        "F-REGI 公金支払い",
        "[no-reply]自治体マイページ事務局送信者",
        "kanagawa-pref",
        "首都圏デジタル産業健康保険組合",
        "CTCグループ健康保険組合",
    ],

    # ── 宅配・物流 ────────────────────────────────────────────────────────────
    "宅配・物流": [
        # 佐川急便
        "佐川急便株式会社", "佐川急便スマートクラブ",
        "佐川急便（株）メルマガ事務局",
        # ヤマト運輸
        "ヤマト運輸株式会社",
        # FedEx
        "TrackingUpdates@fedex.com", "FedEx Delivery Manager",
        "FedEx.com Online Services", "FedEx Tracking",
        # その他
        "DHL EXPRESS", "日本郵便",
    ],

    # ═══════════════════════════════════════════════════════════════════════════
    # 小規模・独立カテゴリ（22トピックに統合しない）
    # ═══════════════════════════════════════════════════════════════════════════

    # ── 転職 ──────────────────────────────────────────────────────────────────
    "転職": [
        "エン転職",
        "リクルートエージェント求人紹介",
        "株式会社リクルート", "RECRUIT AGENT_2",
        "R-AGENT求人紹介窓口",
        "help@support-rls.recruit.jp",
        "【リクルートID】",
        "air-agent", "PCD人事・採用担当",
    ],

    # ── エネルギー ────────────────────────────────────────────────────────────
    "エネルギー": [
        "出光興産 My idemitsu ID",
        "cosmo-thecard",
        "東京電力",
        "Tesla",
    ],

}

# ─── メイン処理 ────────────────────────────────────────────────────────────────

def main():
    mode = "【DRY-RUN プレビュー】" if DRY_RUN else "【本番実行】"
    print(f"\n{'='*60}")
    print(f"  Gmail ラベル統合スクリプト {mode}")
    print(f"{'='*60}\n")

    svc = get_gmail_service()
    print("✅ Gmail API 接続完了")

    # 現在の全ラベルを取得
    label_map = fetch_all_labels(svc)
    print(f"📋 現在のラベル数: {len(label_map)}\n")

    renamed = 0
    skipped_notfound = 0
    skipped_already = 0
    errors = 0

    for parent, children in RULES.items():
        hits = []
        for child in children:
            if child == parent:
                continue  # 親と同名はスキップ
            if child not in label_map:
                skipped_notfound += 1
                continue
            new_name = f"{parent}/{child}"
            if label_map.get(child, "").startswith(parent + "/") or child.startswith(parent + "/"):
                skipped_already += 1
                continue
            # 既に正しい名前になっていたらスキップ
            if child == new_name:
                skipped_already += 1
                continue
            # すでに "何か/child" という形ならスキップ（他の親の下にある）
            # ただし "/" なしのラベルのみ対象
            if "/" in child:
                skipped_already += 1
                continue
            hits.append((child, new_name, label_map[child]))

        if hits:
            print(f"📁 {parent}/ ({len(hits)}件)")
            for old_name, new_name, label_id in hits:
                ok = rename_label(svc, label_id, new_name, old_name)
                if ok:
                    renamed += 1
                    # label_map を更新（後続ルールで参照される場合のため）
                    del label_map[old_name]
                    label_map[new_name] = label_id
                else:
                    errors += 1
            print()

    print(f"\n{'='*60}")
    print(f"  完了サマリー")
    print(f"{'='*60}")
    print(f"  ✅ リネーム成功:     {renamed} 件")
    print(f"  ⏭️  存在せずスキップ: {skipped_notfound} 件")
    print(f"  ⏭️  既に整理済み:     {skipped_already} 件")
    if errors:
        print(f"  ❌ エラー:          {errors} 件")
    print(f"{'='*60}\n")

    if DRY_RUN:
        print("💡 実際に変更するには --dry-run を外して実行してください。\n")


if __name__ == "__main__":
    main()
