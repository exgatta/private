"""GPMF (GoPro Metadata Format) KLV パーサ / ライタ。

GPMF は 32bit アラインの KLV (Key-Length-Value) 形式:

    +--------+--------+--------+--------+
    |            4CC キー               |  4 bytes
    +--------+--------+--------+--------+
    |  型    |構造サイズ|   繰り返し数    |  1 + 1 + 2 bytes (big-endian)
    +--------+--------+--------+--------+
    |  データ (構造サイズ × 繰り返し数,   |
    |   4 バイト境界にゼロパディング)     |
    +-----------------------------------+

型 0x00 はネストコンテナ (DEVC / STRM など)。
複合型 '?' は直前の TYPE 要素で構造が定義される。

仕様: https://github.com/gopro/gpmf-parser
"""

from __future__ import annotations

import datetime
import struct
import uuid
from dataclasses import dataclass, field
from typing import Any, Iterator, List, Optional, Union

# ---------------------------------------------------------------------------
# 型定義
# ---------------------------------------------------------------------------

# GPMF 型文字 -> (struct フォーマット文字, 1要素のバイト数)
_SIMPLE_TYPES = {
    "b": ("b", 1),   # int8
    "B": ("B", 1),   # uint8
    "s": ("h", 2),   # int16
    "S": ("H", 2),   # uint16
    "l": ("i", 4),   # int32
    "L": ("I", 4),   # uint32
    "j": ("q", 8),   # int64
    "J": ("Q", 8),   # uint64
    "f": ("f", 4),   # float32
    "d": ("d", 8),   # float64
}

# 特殊型（struct では直接扱えないもの）
_SPECIAL_SIZES = {
    "c": 1,    # ASCII 文字
    "F": 4,    # 4CC
    "G": 16,   # GUID
    "q": 4,    # Q15.16 固定小数点
    "Q": 8,    # Q31.32 固定小数点
    "U": 16,   # UTC 日時文字列 "yymmddhhmmss.sss"
}

NESTED_TYPE = 0x00  # ネストコンテナ

KNOWN_TYPE_CHARS = set(_SIMPLE_TYPES) | set(_SPECIAL_SIZES) | {"?"}


def type_size(type_char: str) -> int:
    """GPMF 型文字 1 つ分のバイト数を返す。"""
    if type_char in _SIMPLE_TYPES:
        return _SIMPLE_TYPES[type_char][1]
    if type_char in _SPECIAL_SIZES:
        return _SPECIAL_SIZES[type_char]
    raise GPMFError(f"未知の GPMF 型: {type_char!r}")


class GPMFError(ValueError):
    """GPMF の解析・生成エラー。"""


# ---------------------------------------------------------------------------
# 要素
# ---------------------------------------------------------------------------

@dataclass
class GPMFItem:
    """GPMF の 1 要素。

    ネストコンテナの場合 ``children`` に子要素、それ以外は ``values`` に
    デコード済みサンプルのリストを持つ。``raw`` は元データ (パディング除く)。
    """

    key: str                       # 4CC キー ("DEVC" など)
    type_char: str                 # 型文字 ("" = ネスト)
    struct_size: int               # 1 サンプルのバイト数
    repeat: int                    # サンプル数
    raw: bytes = b""               # 生データ
    values: List[Any] = field(default_factory=list)
    children: List["GPMFItem"] = field(default_factory=list)

    @property
    def is_nested(self) -> bool:
        return self.type_char == ""

    # -- 探索ヘルパ ---------------------------------------------------------

    def find_all(self, key: str, recursive: bool = True) -> Iterator["GPMFItem"]:
        """キーが一致する子孫要素を列挙する。"""
        for child in self.children:
            if child.key == key:
                yield child
            if recursive and child.is_nested:
                yield from child.find_all(key, recursive=True)

    def find_first(self, key: str, recursive: bool = True) -> Optional["GPMFItem"]:
        return next(self.find_all(key, recursive), None)

    def value(self) -> Any:
        """サンプルが 1 つならスカラで、複数ならリストで返す。"""
        if len(self.values) == 1:
            return self.values[0]
        return self.values

    def __repr__(self) -> str:  # pragma: no cover - デバッグ用
        if self.is_nested:
            return f"<GPMF {self.key} nested x{len(self.children)}>"
        return f"<GPMF {self.key} {self.type_char!r} x{self.repeat}>"


# ---------------------------------------------------------------------------
# デコード
# ---------------------------------------------------------------------------

def _decode_scalar(type_char: str, data: bytes) -> Any:
    """単一要素 (type_size バイト) をデコードする。"""
    if type_char in _SIMPLE_TYPES:
        fmt, _ = _SIMPLE_TYPES[type_char]
        return struct.unpack(">" + fmt, data)[0]
    if type_char == "F":
        return data.decode("ascii", "replace")
    if type_char == "G":
        return str(uuid.UUID(bytes=data))
    if type_char == "q":  # Q15.16
        return struct.unpack(">i", data)[0] / 65536.0
    if type_char == "Q":  # Q31.32
        return struct.unpack(">q", data)[0] / 4294967296.0
    if type_char == "U":
        return data.decode("ascii", "replace").rstrip("\x00")
    if type_char == "c":
        return data.decode("latin-1")
    raise GPMFError(f"デコード不能な型: {type_char!r}")


def _decode_samples(type_char: str, struct_size: int, repeat: int,
                    data: bytes, type_def: str = "") -> List[Any]:
    """データ本体をサンプルのリストにデコードする。"""
    if type_char == "c":
        # 文字列: struct_size バイトの文字列 × repeat 個
        out = []
        for i in range(repeat):
            chunk = data[i * struct_size:(i + 1) * struct_size]
            out.append(chunk.decode("latin-1").rstrip("\x00"))
        return out

    if type_char == "?":
        if not type_def:
            raise GPMFError("複合型 '?' に TYPE 定義がありません")
        return [_decode_complex(type_def, data[i * struct_size:(i + 1) * struct_size])
                for i in range(repeat)]

    base = type_size(type_char)
    if struct_size % base != 0:
        raise GPMFError(
            f"構造サイズ {struct_size} が型 {type_char!r} のサイズ {base} の倍数でない")
    per_sample = struct_size // base

    out = []
    for i in range(repeat):
        sample = data[i * struct_size:(i + 1) * struct_size]
        vals = tuple(_decode_scalar(type_char, sample[j * base:(j + 1) * base])
                     for j in range(per_sample))
        out.append(vals if per_sample > 1 else vals[0])
    return out


def expand_type_def(type_def: str) -> List[str]:
    """複合 TYPE 文字列を型文字のリストに展開する。

    "lL" -> ["l", "L"] / "f[4]" -> ["f", "f", "f", "f"]
    """
    chars: List[str] = []
    i = 0
    while i < len(type_def):
        ch = type_def[i]
        if ch == "\x00":
            break
        if ch not in KNOWN_TYPE_CHARS:
            raise GPMFError(f"TYPE 定義に未知の型文字: {ch!r} ({type_def!r})")
        if i + 1 < len(type_def) and type_def[i + 1] == "[":
            end = type_def.index("]", i + 1)
            count = int(type_def[i + 2:end])
            chars.extend([ch] * count)
            i = end + 1
        else:
            chars.append(ch)
            i += 1
    return chars


def complex_struct_size(type_def: str) -> int:
    return sum(type_size(c) for c in expand_type_def(type_def))


def _decode_complex(type_def: str, sample: bytes) -> tuple:
    """複合型の 1 サンプルをデコードする。"""
    out = []
    pos = 0
    for ch in expand_type_def(type_def):
        size = type_size(ch)
        out.append(_decode_scalar(ch, sample[pos:pos + size]))
        pos += size
    return tuple(out)


def parse(data: bytes, offset: int = 0, end: Optional[int] = None,
          strict: bool = True) -> List[GPMFItem]:
    """GPMF バイト列を要素リストにパースする。

    ネスト内の TYPE 要素を追跡して複合型 '?' を完全にデコードする。
    strict=False の場合、壊れた要素はスキップして継続する。
    """
    if end is None:
        end = len(data)
    items: List[GPMFItem] = []
    type_def = ""  # 同一ネストレベル内で有効な TYPE 定義
    pos = offset

    while pos + 8 <= end:
        key_raw = data[pos:pos + 4]
        if key_raw == b"\x00\x00\x00\x00":
            break  # パディング/終端
        type_byte = data[pos + 4]
        struct_size = data[pos + 5]
        repeat = struct.unpack(">H", data[pos + 6:pos + 8])[0]
        payload_len = struct_size * repeat
        padded_len = (payload_len + 3) & ~3
        payload_end = pos + 8 + payload_len

        if pos + 8 + padded_len > end:
            if strict:
                raise GPMFError(
                    f"要素 {key_raw!r} @ {pos}: データが範囲外 "
                    f"(必要 {padded_len}, 残り {end - pos - 8})")
            break

        try:
            key = key_raw.decode("ascii")
        except UnicodeDecodeError:
            if strict:
                raise GPMFError(f"不正な 4CC キー @ {pos}: {key_raw!r}")
            pos += 8 + padded_len
            continue

        payload = data[pos + 8:payload_end]

        try:
            if type_byte == NESTED_TYPE:
                item = GPMFItem(key=key, type_char="", struct_size=struct_size,
                                repeat=repeat, raw=payload)
                item.children = parse(data, pos + 8, payload_end, strict=strict)
            else:
                type_char = chr(type_byte)
                if type_char not in KNOWN_TYPE_CHARS:
                    raise GPMFError(
                        f"要素 {key}: 未知の型 0x{type_byte:02x}")
                item = GPMFItem(key=key, type_char=type_char,
                                struct_size=struct_size, repeat=repeat,
                                raw=payload)
                item.values = _decode_samples(type_char, struct_size, repeat,
                                              payload, type_def)
                if key == "TYPE":
                    type_def = item.values[0] if item.values else ""
        except GPMFError:
            if strict:
                raise
            pos += 8 + padded_len
            continue

        items.append(item)
        pos += 8 + padded_len

    return items


# ---------------------------------------------------------------------------
# エンコード
# ---------------------------------------------------------------------------

def _encode_scalar(type_char: str, value: Any) -> bytes:
    if type_char in _SIMPLE_TYPES:
        fmt, _ = _SIMPLE_TYPES[type_char]
        return struct.pack(">" + fmt, value)
    if type_char == "F":
        b = value.encode("ascii") if isinstance(value, str) else bytes(value)
        if len(b) != 4:
            raise GPMFError(f"4CC は 4 バイト必要: {value!r}")
        return b
    if type_char == "G":
        return uuid.UUID(value).bytes if isinstance(value, str) else bytes(value)
    if type_char == "q":
        return struct.pack(">i", round(value * 65536))
    if type_char == "Q":
        return struct.pack(">q", round(value * 4294967296))
    if type_char == "U":
        b = value.encode("ascii")
        return b.ljust(16, b"\x00")[:16]
    raise GPMFError(f"エンコード不能な型: {type_char!r}")


def _pad4(data: bytes) -> bytes:
    rem = len(data) % 4
    return data + b"\x00" * (4 - rem) if rem else data


def make_item(key: str, type_char: str, values: Any,
              struct_count: int = 1) -> bytes:
    """単純型の GPMF 要素をエンコードする。

    values: スカラ / リスト / タプルのリスト。
    struct_count: 1 サンプルあたりの要素数 (GPS5 なら 5)。
    """
    key_b = key.encode("ascii")
    if len(key_b) != 4:
        raise GPMFError(f"キーは 4 文字必要: {key!r}")

    if type_char == "c":
        if isinstance(values, str):
            values = [values]
        max_len = max(len(v) for v in values)
        struct_size = max_len
        repeat = len(values)
        body = b"".join(v.encode("latin-1").ljust(max_len, b"\x00")
                        for v in values)
    else:
        base = type_size(type_char)
        struct_size = base * struct_count
        if not isinstance(values, (list, tuple)):
            values = [values]
        # サンプルのリストへ正規化
        samples: List[tuple] = []
        for v in values:
            if isinstance(v, (list, tuple)):
                if len(v) != struct_count:
                    raise GPMFError(
                        f"{key}: サンプル要素数 {len(v)} != struct_count {struct_count}")
                samples.append(tuple(v))
            else:
                if struct_count != 1:
                    raise GPMFError(f"{key}: タプルのサンプルが必要")
                samples.append((v,))
        repeat = len(samples)
        body = b"".join(_encode_scalar(type_char, x)
                        for s in samples for x in s)

    if struct_size > 255:
        raise GPMFError(f"{key}: 構造サイズ {struct_size} が 255 を超過")
    if repeat > 65535:
        raise GPMFError(f"{key}: 繰り返し数 {repeat} が 65535 を超過")

    header = key_b + bytes([ord(type_char), struct_size]) + struct.pack(">H", repeat)
    return header + _pad4(body)


def make_nested(key: str, payload: bytes) -> bytes:
    """ネストコンテナ要素 (DEVC / STRM など) をエンコードする。"""
    key_b = key.encode("ascii")
    if len(key_b) != 4:
        raise GPMFError(f"キーは 4 文字必要: {key!r}")
    payload = _pad4(payload)
    if len(payload) // 1 > 0xFFFFFFF:
        raise GPMFError("ネストペイロードが大きすぎます")
    # ネストは structure size = 1, repeat = バイト数 が慣例
    size = len(payload)
    if size <= 65535:
        header = key_b + bytes([NESTED_TYPE, 1]) + struct.pack(">H", size)
    else:
        # 大きい場合 struct_size を 4 にして繰り返し数を byte/4 に
        if size % 4 or size // 4 > 65535:
            raise GPMFError(f"{key}: ネストサイズ {size} を表現できません")
        header = key_b + bytes([NESTED_TYPE, 4]) + struct.pack(">H", size // 4)
    return header + payload


# ---------------------------------------------------------------------------
# 表示 / エクスポート
# ---------------------------------------------------------------------------

# 主要キーの説明 (人間可読ダンプ用)
KEY_DESCRIPTIONS = {
    "DEVC": "デバイスコンテナ",
    "DVID": "デバイスID",
    "DVNM": "デバイス名",
    "STRM": "ストリームコンテナ",
    "STNM": "ストリーム名",
    "TYPE": "複合型定義",
    "SCAL": "スケール係数(除数)",
    "SIUN": "SI単位",
    "UNIT": "表示単位",
    "TSMP": "累計サンプル数",
    "STMP": "タイムスタンプ(µs)",
    "TIMO": "時間オフセット",
    "TICK": "開始チック",
    "TOCK": "終了チック",
    "EMPT": "空ペイロード数",
    "ACCL": "加速度 (m/s²)",
    "GYRO": "ジャイロ (rad/s)",
    "MAGN": "磁気センサ (µT)",
    "GPS5": "GPS (緯度,経度,高度,2D速度,3D速度)",
    "GPS9": "GPS9 (緯度,経度,高度,2D,3D,日,秒,DOP,fix)",
    "GPSU": "GPS UTC 時刻",
    "GPSF": "GPS Fix (0=なし,2=2D,3=3D)",
    "GPSP": "GPS 精度 (DOP×100)",
    "GPSA": "GPS 高度系",
    "SHUT": "シャッター速度 (s)",
    "ISOG": "ISOゲイン",
    "ISOE": "ISO感度",
    "WBAL": "色温度 (K)",
    "WRGB": "ホワイトバランスRGBゲイン",
    "YAVG": "平均輝度",
    "UNIF": "画像均一性",
    "FACE": "顔検出",
    "CORI": "カメラ姿勢 (クォータニオン)",
    "IORI": "イメージ姿勢 (クォータニオン)",
    "GRAV": "重力ベクトル",
    "WNDM": "風切り音処理",
    "MWET": "水没検出",
    "AALP": "音声レベル (dBFS)",
    "MSKP": "メインストリームスキップフレーム",
    "LSKP": "LRVスキップフレーム",
    "FIRM": "ファームウェアバージョン",
    "LENS": "レンズシリアル",
    "CAME": "カメラシリアル",
    "MINF": "モデル名",
    "MUID": "メディアユニークID",
    "SROT": "センサ読み出し時間",
    "CASN": "カメラシリアル番号",
    "MTRX": "変換行列",
    "ORIN": "入力方位",
    "ORIO": "出力方位",
    "RMRK": "備考",
}


def dump(items: List[GPMFItem], indent: int = 0, max_values: int = 6) -> str:
    """要素ツリーを人間可読テキストにダンプする。"""
    lines = []
    pad = "  " * indent
    for item in items:
        desc = KEY_DESCRIPTIONS.get(item.key, "")
        desc_s = f"  # {desc}" if desc else ""
        if item.is_nested:
            lines.append(f"{pad}{item.key} (nested, {len(item.children)} 子要素){desc_s}")
            lines.append(dump(item.children, indent + 1, max_values))
        else:
            vals = item.values
            shown = vals[:max_values]
            more = f" ... 他{len(vals) - max_values}件" if len(vals) > max_values else ""
            val_s = ", ".join(repr(v) for v in shown)
            lines.append(
                f"{pad}{item.key} [{item.type_char} x{item.repeat}"
                f"@{item.struct_size}B] {val_s}{more}{desc_s}")
    return "\n".join(l for l in lines if l)


def to_dict(items: List[GPMFItem]) -> List[dict]:
    """JSON 化可能な構造に変換する。"""
    out = []
    for item in items:
        d: dict = {"key": item.key, "type": item.type_char or "nested",
                   "struct_size": item.struct_size, "repeat": item.repeat}
        if item.is_nested:
            d["children"] = to_dict(item.children)
        else:
            d["values"] = item.values
        out.append(d)
    return out


def gpsu_to_datetime(value: str) -> datetime.datetime:
    """GPSU 文字列 "yymmddhhmmss.sss" を datetime (UTC) に変換する。"""
    v = value.strip().rstrip("\x00")
    return datetime.datetime.strptime(v, "%y%m%d%H%M%S.%f").replace(
        tzinfo=datetime.timezone.utc)


def datetime_to_gpsu(dt: datetime.datetime) -> str:
    """datetime を GPSU 文字列に変換する。"""
    return dt.astimezone(datetime.timezone.utc).strftime("%y%m%d%H%M%S.%f")[:16]
