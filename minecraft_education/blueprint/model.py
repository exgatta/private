# -*- coding: utf-8 -*-
"""ボクセルモデル。設計図の元になる「どの座標にどのブロックがあるか」を持つ。

座標系はMinecraftと同じ:
  x = 東西（図では左→右）、 y = 高さ（レイヤー番号、y=0が1段目）、
  z = 南北（図では上=北、下=南）
"""

from collections import Counter

from .palette import block


class VoxelModel:
    def __init__(self, name, description="", notes=None):
        self.name = name
        self.description = description
        self.notes = list(notes or [])  # つくるときのポイント（配線手順など）
        self.layer_notes = {}  # y -> そのレイヤー図に添える注記（設計図HTMLに表示）
        self.blocks = {}  # (x, y, z) -> block key
        self.facing = {}  # (x, y, z) -> "north"/"south"/"east"/"west"（階段等の向き）

    # --- 基本操作 -----------------------------------------------------

    # ホッパーやディスペンサーは真下・真上も向く。無いと自動装置が組めない。
    FACINGS = ("north", "south", "east", "west", "down", "up")

    def set(self, x, y, z, key, facing=None):
        """1マスにブロックを置く。

        facing は階段・トラップドア等の向き（north/south/east/west）。
        設計図では向きの矢印として描かれ、コマンド出力にも反映される。
        """
        if key is None or key == "air":
            self.blocks.pop((x, y, z), None)
            self.facing.pop((x, y, z), None)
            return
        block(key)  # パレットに無ければここでエラー
        self.blocks[(x, y, z)] = key
        if facing is None:
            self.facing.pop((x, y, z), None)
        else:
            if facing not in self.FACINGS:
                raise ValueError(
                    f"向きは {'/'.join(self.FACINGS)} のどれか。'{facing}' は使えません。"
                )
            self.facing[(x, y, z)] = facing

    def get(self, x, y, z):
        return self.blocks.get((x, y, z))

    def fill(self, x1, y1, z1, x2, y2, z2, key, facing=None):
        """直方体を埋める（両端含む）。"""
        for x in range(min(x1, x2), max(x1, x2) + 1):
            for y in range(min(y1, y2), max(y1, y2) + 1):
                for z in range(min(z1, z2), max(z1, z2) + 1):
                    self.set(x, y, z, key, facing)

    def hollow_box(self, x1, y1, z1, x2, y2, z2, key):
        """外周の壁だけの直方体（床・天井は作らない）。"""
        for x in range(min(x1, x2), max(x1, x2) + 1):
            for y in range(min(y1, y2), max(y1, y2) + 1):
                for z in range(min(z1, z2), max(z1, z2) + 1):
                    if x in (x1, x2) or z in (z1, z2):
                        self.set(x, y, z, key)

    # --- 集計 ---------------------------------------------------------

    def bounds(self):
        if not self.blocks:
            return (0, 0, 0, 0, 0, 0)
        xs, ys, zs = zip(*self.blocks.keys())
        return (min(xs), min(ys), min(zs), max(xs), max(ys), max(zs))

    def size(self):
        x1, y1, z1, x2, y2, z2 = self.bounds()
        return (x2 - x1 + 1, y2 - y1 + 1, z2 - z1 + 1)

    def normalize(self):
        """最小座標が(0,0,0)になるよう平行移動する。"""
        x1, y1, z1, _, _, _ = self.bounds()
        self.blocks = {
            (x - x1, y - y1, z - z1): k for (x, y, z), k in self.blocks.items()
        }
        if self.facing:
            self.facing = {
                (x - x1, y - y1, z - z1): f for (x, y, z), f in self.facing.items()
            }
        if self.layer_notes:
            self.layer_notes = {y - y1: t for y, t in self.layer_notes.items()}
        return self

    def layers(self):
        """y昇順に (y, {(x, z): key}) を返す。"""
        _, y1, _, _, y2, _ = self.bounds()
        for y in range(y1, y2 + 1):
            layer = {
                (x, z): k for (x, yy, z), k in self.blocks.items() if yy == y
            }
            yield y, layer

    def counts(self):
        """ブロック種別ごとの総数（多い順）。"""
        return Counter(self.blocks.values()).most_common()
