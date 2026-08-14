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
    "sticky_piston": ("facing_direction", _facing_direction),
    "hopper": ("facing_direction", _facing_direction),
    "dispenser": ("facing_direction", _facing_direction),
    "dropper": ("facing_direction", _facing_direction),
    "comparator": ("minecraft:cardinal_direction", _cardinal),
    "repeater": ("minecraft:cardinal_direction", _cardinal),
    "observer": ("minecraft:facing_direction", _mc_facing_direction),
    "sign": ("ground_sign_direction", _ground_sign),
}


def state_suffix(key, facing):
    """コマンドに付ける状態指定を返す。付けられないときは空文字。

    例: state_suffix("hopper", "down") -> ' ["facing_direction"=0]'
    """
    if not facing:
        return ""
    rule = STATE_RULES.get(key)
    if not rule:
        return ""
    s = rule[1](facing)
    return f" [{s}]" if s else ""
