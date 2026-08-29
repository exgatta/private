# -*- coding: utf-8 -*-
"""向き（facing）を Bedrock のブロック状態へ変換する。

なぜ必要か:
  /setblock も /fill も、ブロック名だけ指定すると**既定の向き**で置かれる。
  階段もホッパーもディスペンサーも、向きを添えなければ設計図どおりにならず、
  仕掛けはまず動かない。以前はここが空だったので、コマンドで組むと
  向きが全部そろわないまま出来上がっていた。

出所と確からしさ:
  どのブロックがどの状態を持つかは Mojang 公式のブロック定義
  （reference/bedrock_blocks_states.json、Mojang/bedrock-samples 由来）と
  照合済み。tools/verify_block_ids.py が毎回突き合わせる。

  値の書き方は2種類ある:
    - 文字列で持つもの（minecraft:cardinal_direction 等）
      … 公式データに値そのものが載っているので、そのまま使える（確実）
    - 数値で持つもの（facing_direction, weirdo_direction, direction）
      … 公式データには 0〜5 / 0〜3 という範囲しか載っていない。
        並び順は同じファイルの minecraft:facing_direction が
        [down, up, north, south, west, east] の順で定義されているため、
        数値版もこの順（0=down … 5=east）とみなしている。
        階段の weirdo_direction と トラップドアの direction は
        Bedrock 共通の 0=east, 1=west, 2=south, 3=north を使う。
"""

# 面のインデックス。minecraft:facing_direction の定義順に対応する。
_FACE_INDEX = {"down": 0, "up": 1, "north": 2, "south": 3, "west": 4, "east": 5}

# 階段・トラップドアの回転インデックス（Bedrock共通）
_WEIRDO = {"east": 0, "west": 1, "south": 2, "north": 3}


def _cardinal(facing):
    """minecraft:cardinal_direction。文字列でそのまま入れる。"""
    if facing in ("up", "down"):
        return None  # 上下は指定できない（横向きのみ）
    return f'"minecraft:cardinal_direction"="{facing}"'


def _facing_direction(facing):
    """facing_direction（0〜5の数値）。ホッパー・ピストン・ディスペンサー等。"""
    return f'"facing_direction"={_FACE_INDEX[facing]}'


def _mc_facing_direction(facing):
    """minecraft:facing_direction（文字列）。オブザーバー。"""
    return f'"minecraft:facing_direction"="{facing}"'


def _weirdo(facing):
    """階段の weirdo_direction（0〜3）。"""
    if facing in ("up", "down"):
        return None
    return f'"weirdo_direction"={_WEIRDO[facing]}'


def _trapdoor(facing):
    """トラップドアの direction（0〜3）。"""
    if facing in ("up", "down"):
        return None
    return f'"direction"={_WEIRDO[facing]}'


def _facing_direction_opp(facing):
    """ピストン用: 水平は格納値の正反対、上下はそのまま（実機で確認）。"""
    if facing in ("down", "up"):
        return f'"facing_direction"={_FACE_INDEX[facing]}'
    return f'"facing_direction"={_FACE_INDEX[_OPP[facing]]}'


def _cardinal_opp(facing):
    """リピーター/コンパレーター用: 格納値は入力側＝矢印の逆（Nukkit・実機で確認）。"""
    if facing in ("up", "down"):
        return None
    return f'"minecraft:cardinal_direction"="{_OPP[facing]}"'


def _ground_sign(facing):
    """看板の ground_sign_direction（0〜15の16方向）。

    0が南で、時計回りに1目盛=22.5度。4方向ぶんだけ使う。
    """
    table = {"south": 0, "west": 4, "north": 8, "east": 12}
    if facing in ("up", "down"):
        return None
    return f'"ground_sign_direction"={table[facing]}'


# ブロックキー -> (状態プロパティ名, 変換関数)
# 状態プロパティ名は公式データとの照合に使う（実在しなければテストが落ちる）。
STATE_RULES = {
    "oak_stairs": ("weirdo_direction", _weirdo),
    "stone_brick_stairs": ("weirdo_direction", _weirdo),
    "cobblestone_stairs": ("weirdo_direction", _weirdo),
    "oak_fence_gate": ("minecraft:cardinal_direction", _cardinal),
    "oak_trapdoor": ("direction", _trapdoor),
    "ladder": ("facing_direction", _facing_direction),
    "chest": ("minecraft:cardinal_direction", _cardinal),
    "sticky_piston": ("facing_direction", _facing_direction_opp),
    "hopper": ("facing_direction", _facing_direction),
    "dispenser": ("facing_direction", _facing_direction),
    "dropper": ("facing_direction", _facing_direction),
    "comparator": ("minecraft:cardinal_direction", _cardinal_opp),
    "repeater": ("minecraft:cardinal_direction", _cardinal_opp),
    "observer": ("minecraft:facing_direction", _mc_facing_direction),
    "sign": ("ground_sign_direction", _ground_sign),
}


def state_suffix(key, facing):
    """コマンドに付ける状態指定を返す。付けられないときは空文字。

    例: state_suffix("hopper", "down") -> ' ["facing_direction"=0]'

    注意: この `["状態"=値]` 構文は Bedrock 1.19.70 以降のコマンドエンジン専用。
    **Minecraft Education（1.21.133 実機で確認）はこれを構文エラーにする**ため、
    Education 向けの出力には下の aux_value / command_suffix（データ値方式）を使う。
    """
    if not facing:
        return ""
    rule = STATE_RULES.get(key)
    if not rule:
        return ""
    s = rule[1](facing)
    return f" [{s}]" if s else ""


# ---------------------------------------------------------------------------
# データ値（aux）方式 — Minecraft Education 用
#
# Education のコマンドエンジンは 1.19.70 より古い世代で、ブロック状態構文
# `["facing_direction"=5]` を「構文エラー: "=" は無効です」と拒否する（実機確認）。
# 旧世代の書き方はデータ値: `/setblock ~ ~ ~ sticky_piston 5`。
#
# 対応表の出所（推測ではない）:
#   - pmmp/BedrockBlockUpgradeSchema id_meta_to_nbt/1.12.0.bin
#     … 公式ワールド変換用の「データ値 → ブロック状態」対応。ここから
#       「データ値の下位ビット = 向きの状態値そのまま」であることを確認
#   - 同 nbt_upgrade_schema 0221(1.20.30): repeater/comparator の direction は
#     0=south, 1=west, 2=north, 3=east（direction_00 表）
#   - 同 0231(1.20.40): chest の facing_direction は 2=north 3=south 4=west 5=east
#   - CloudburstMC/Nukkit（旧世代Bedrockサーバー実装）:
#     fence_gate は 0=south 1=west 2=north 3=east、
#     trapdoor は 0=east 1=west 2=south 3=north（階段の weirdo と同じ）
# ---------------------------------------------------------------------------

# repeater / comparator / fence_gate の direction（0=south 1=west 2=north 3=east）
_DIRECTION_SWNE = {"south": 0, "west": 1, "north": 2, "east": 3}

# 看板 ground_sign_direction は新旧共通（0=南、時計回り）
_SIGN_DIR = {"south": 0, "west": 4, "north": 8, "east": 12}

_OPP = {"north": "south", "south": "north", "east": "west", "west": "east",
        "down": "up", "up": "down"}

# 【重要】「格納値の数え方」と「見た目の向き」はブロックごとに別物。
# 実機テスト（Education 1.21.133）で「ピストンとリピーターが逆」と発覚し、
# Nukkit（旧世代Bedrockサーバー実装）の設置・動作コードで全ブロックを照合した:
#   - ピストン: 実効方向（頭・押す向き）は格納値の正反対。
#     Nukkit BlockPistonBase: getFacing() = fromIndex(damage).getOpposite()
#   - リピーター/コンパレーター: 格納値は「入力側（矢印の逆）」。
#     Nukkit BlockRedstoneDiode: 入力を getFacing() 側から読む
#   - 階段/トラップドア/フェンスゲート/はしご/チェスト(正面)/ホッパー(注ぎ口)/
#     ディスペンサー・ドロッパー(発射面)/オブザーバー(観察面)/看板(正面) は
#     格納値がそのまま見た目の向き（照合済み・反転しない）

# ブロックキー -> 見た目の向き -> データ値
AUX_RULES = {
    "oak_stairs": _WEIRDO,
    "stone_brick_stairs": _WEIRDO,
    "cobblestone_stairs": _WEIRDO,
    "oak_trapdoor": _WEIRDO,          # 閉・下付き（上位ビット0）
    "oak_fence_gate": _DIRECTION_SWNE,
    "ladder": {f: i for f, i in _FACE_INDEX.items() if i >= 2},
    "chest": {f: i for f, i in _FACE_INDEX.items() if i >= 2},
    # ピストンは「押す向き」を指定 → 水平は反対を格納、上下はそのまま
    # （実機 Education 1.21.133 で確認: 北向き=3 が北へ伸び、1 が上へ伸びた。
    #   水平だけ反転という非対称仕様。Nukkit の getOpposite() は水平にだけ正しい）
    "sticky_piston": {
        **{f: _FACE_INDEX[_OPP[f]] for f in ("north", "south", "east", "west")},
        "down": 0, "up": 1,
    },
    "hopper": {f: i for f, i in _FACE_INDEX.items() if f != "up"},
    "dispenser": _FACE_INDEX,
    "dropper": _FACE_INDEX,
    # リピーター/コンパレーターは「矢印（出力）の向き」を指定 → 格納値はその反対
    "comparator": {f: _DIRECTION_SWNE[_OPP[f]] for f in _DIRECTION_SWNE},
    "repeater": {f: _DIRECTION_SWNE[_OPP[f]] for f in _DIRECTION_SWNE},
    "observer": _FACE_INDEX,
    "sign": _SIGN_DIR,
}


def aux_value(key, facing):
    """Education 向けのデータ値を返す。向きが不要・指定不能なら None。"""
    if not facing:
        return None
    return AUX_RULES.get(key, {}).get(facing)


def command_suffix(key, facing):
    """Education のコマンドに付ける向き指定（データ値）。無ければ空文字。

    例: command_suffix("sticky_piston", "east") -> ' 5'
    """
    v = aux_value(key, facing)
    return f" {v}" if v is not None else ""
