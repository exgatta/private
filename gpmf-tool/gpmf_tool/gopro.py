"""GoPro カメラ識別情報の生成。

GoPro の MP4 は gpmd トラックに加えて、moov/udta 直下に独自の 4CC ボックス
(FIRM / LENS / CAME / MUID / GPMF など) を持つ。テレメトリ抽出ツールや
GoPro 公式アプリ (Quik 等) の多くはこれらを見て「GoPro の動画」と判定する。

このモジュールは機種プリセットと udta ボックス列の生成を提供する。
"""

from __future__ import annotations

import hashlib
import struct
from dataclasses import dataclass
from typing import Optional

from . import klv


@dataclass(frozen=True)
class DevicePreset:
    key: str            # CLI 指定名
    device_name: str    # GPMF DVNM / udta GPMF の MINF に入るモデル名
    firmware: str       # udta FIRM
    lens_prefix: str    # LENS シリアルの接頭辞


# 実機のファームウェア命名規則 (HDx / H2x) に合わせたプリセット
DEVICE_PRESETS = {
    "hero5": DevicePreset("hero5", "HERO5 Black", "HD5.02.02.51.00", "LAJ"),
    "hero6": DevicePreset("hero6", "HERO6 Black", "HD6.01.02.61.00", "LAJ"),
    "hero7": DevicePreset("hero7", "HERO7 Black", "HD7.01.01.90.00", "LAJ"),
    "hero8": DevicePreset("hero8", "HERO8 Black", "HD8.01.02.51.00", "LAJ"),
    "hero9": DevicePreset("hero9", "HERO9 Black", "HD9.01.01.72.00", "LAJ"),
    "hero10": DevicePreset("hero10", "HERO10 Black", "H21.01.01.46.00", "LAJ"),
    "hero11": DevicePreset("hero11", "HERO11 Black", "H22.01.02.32.00", "LAJ"),
    "hero12": DevicePreset("hero12", "HERO12 Black", "H23.01.02.32.00", "LAJ"),
    "hero13": DevicePreset("hero13", "HERO13 Black", "H24.01.02.02.00", "LAJ"),
}

DEFAULT_PRESET = "hero9"


def _box(btype: bytes, body: bytes) -> bytes:
    return struct.pack(">I", 8 + len(body)) + btype + body


def _derive_serial(seed: str, prefix: str, length: int = 14) -> str:
    """入力シードから決定論的にシリアル番号風の文字列を作る。"""
    digest = hashlib.sha256(seed.encode("utf-8")).hexdigest().upper()
    return (prefix + digest)[:length]


def build_udta_boxes(preset: DevicePreset,
                     serial_seed: str,
                     firmware: Optional[str] = None,
                     device_name: Optional[str] = None) -> bytes:
    """moov/udta に追記する GoPro 識別ボックス列を生成する。

    実機と同様に FIRM / LENS / CAME / MUID と、デバイス情報入りの
    GPMF ボックスを並べる。
    """
    firmware = firmware or preset.firmware
    device_name = device_name or preset.device_name
    lens = _derive_serial("lens:" + serial_seed, preset.lens_prefix)
    came = _derive_serial("came:" + serial_seed, "C3", 14)

    out = b""
    out += _box(b"FIRM", firmware.encode("ascii"))
    out += _box(b"LENS", lens.encode("ascii"))
    out += _box(b"CAME", came.encode("ascii"))
    # MUID: 8 個の uint32 (メディアユニーク ID)
    muid_digest = hashlib.sha256(("muid:" + serial_seed).encode()).digest()
    out += _box(b"MUID", muid_digest[:32])

    # udta 直下の GPMF ボックス: デバイス情報のみの DEVC
    dev_body = klv.make_item("DVID", "L", 1)
    dev_body += klv.make_item("DVNM", "c", device_name)
    dev_body += klv.make_item("FIRM", "c", firmware)
    dev_body += klv.make_item("MINF", "c", device_name)
    dev_body += klv.make_item("CASN", "c", came)
    gpmf_payload = klv.make_nested("DEVC", dev_body)
    out += _box(b"GPMF", gpmf_payload)
    return out


# GoPro 実機の hdlr name (末尾スペース込みの慣例)
HANDLER_RENAMES = {
    b"vide": "GoPro AVC",
    b"soun": "GoPro AAC",
}
