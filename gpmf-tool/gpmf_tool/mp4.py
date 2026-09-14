"""MP4 (ISO BMFF) コンテナの読み書き。

GPMF ツールに必要な範囲の実装:

- トップレベルボックスの列挙 (ftyp / moov / mdat / free ...)
- moov ツリーの解析・再構築 (サイズ再計算つき)
- `gpmd` タイムドメタデータトラックのサンプル抽出 (stsd/stsz/stsc/stco/stts)
- `gpmd` トラックの新規作成と注入 (GoPro HERO シリーズと同じ構造)
- チャンクオフセット (stco/co64) の自動補正

フラグメント化 MP4 (moof) は非対応。
"""

from __future__ import annotations

import io
import re
import struct
from dataclasses import dataclass, field
from typing import BinaryIO, Callable, Iterator, List, Optional, Tuple

from .klv import GPMFError


# moov 内で再帰的に解析するコンテナボックス
_CONTAINER_BOXES = {
    b"moov", b"trak", b"mdia", b"minf", b"stbl", b"edts", b"udta",
    b"gmhd", b"dinf", b"mvex",
}


class MP4Error(ValueError):
    """MP4 の解析・生成エラー。"""


# ---------------------------------------------------------------------------
# ボックスツリー
# ---------------------------------------------------------------------------

@dataclass
class Box:
    """メモリ上のボックス。コンテナなら children、リーフなら payload を持つ。"""

    type: bytes
    payload: bytes = b""
    children: List["Box"] = field(default_factory=list)
    is_container: bool = False

    def find(self, *path: bytes) -> Optional["Box"]:
        """パス指定で子孫ボックスを 1 つ探す。"""
        node = self
        for name in path:
            node = next((c for c in node.children if c.type == name), None)
            if node is None:
                return None
        return node

    def find_all(self, name: bytes) -> Iterator["Box"]:
        for c in self.children:
            if c.type == name:
                yield c

    def serialize(self) -> bytes:
        body = (b"".join(c.serialize() for c in self.children)
                if self.is_container else self.payload)
        size = 8 + len(body)
        if size <= 0xFFFFFFFF:
            return struct.pack(">I", size) + self.type + body
        return struct.pack(">I", 1) + self.type + struct.pack(">Q", size + 8) + body


def parse_box_tree(data: bytes, box_type: bytes) -> Box:
    """バイト列 (ヘッダ含む) からボックスツリーを構築する。"""
    boxes = _parse_children(data, 0, len(data))
    if len(boxes) != 1 or boxes[0].type != box_type:
        raise MP4Error(f"{box_type!r} ボックスの解析に失敗")
    return boxes[0]


def _parse_children(data: bytes, start: int, end: int) -> List[Box]:
    out: List[Box] = []
    pos = start
    while pos + 8 <= end:
        size = struct.unpack(">I", data[pos:pos + 4])[0]
        btype = data[pos + 4:pos + 8]
        header = 8
        if size == 1:
            size = struct.unpack(">Q", data[pos + 8:pos + 16])[0]
            header = 16
        elif size == 0:
            size = end - pos
        if size < header or pos + size > end:
            raise MP4Error(f"不正なボックスサイズ {size} @ {pos} ({btype!r})")
        body = data[pos + header:pos + size]
        if btype in _CONTAINER_BOXES:
            box = Box(type=btype, is_container=True,
                      children=_parse_children(data, pos + header, pos + size))
        else:
            box = Box(type=btype, payload=body)
        out.append(box)
        pos += size
    return out


# ---------------------------------------------------------------------------
# トップレベル走査
# ---------------------------------------------------------------------------

@dataclass
class TopLevelBox:
    type: bytes
    offset: int      # ファイル内オフセット (ヘッダ先頭)
    size: int        # ヘッダ込みの全長
    header_size: int = 8  # 8、64bit largesize の場合は 16

    @property
    def payload_offset(self) -> int:
        """中身 (ヘッダを除いたデータ) の開始オフセット。"""
        return self.offset + self.header_size

    @property
    def payload_size(self) -> int:
        return self.size - self.header_size


def scan_top_level(f: BinaryIO) -> List[TopLevelBox]:
    """ファイルのトップレベルボックスを列挙する。"""
    f.seek(0, io.SEEK_END)
    file_size = f.tell()
    f.seek(0)
    out: List[TopLevelBox] = []
    pos = 0
    while pos + 8 <= file_size:
        f.seek(pos)
        head = f.read(16)
        size = struct.unpack(">I", head[:4])[0]
        btype = head[4:8]
        header_size = 8
        if size == 1:
            size = struct.unpack(">Q", head[8:16])[0]
            header_size = 16
        elif size == 0:
            size = file_size - pos
        if size < header_size or pos + size > file_size:
            raise MP4Error(f"不正なトップレベルボックス @ {pos}: {btype!r} size={size}")
        out.append(TopLevelBox(type=btype, offset=pos, size=size,
                               header_size=header_size))
        pos += size
    if not any(b.type == b"moov" for b in out):
        raise MP4Error("moov ボックスが見つかりません (MP4 ではない?)")
    if any(b.type == b"moof" for b in out):
        raise MP4Error("フラグメント化 MP4 (moof) は非対応です")
    return out


def read_box_bytes(f: BinaryIO, box: TopLevelBox) -> bytes:
    f.seek(box.offset)
    return f.read(box.size)


# ---------------------------------------------------------------------------
# フルボックス/サンプルテーブルの読み取りヘルパ
# ---------------------------------------------------------------------------

def _u32s(data: bytes, offset: int, count: int) -> List[int]:
    return list(struct.unpack(f">{count}I", data[offset:offset + 4 * count]))


def parse_mvhd(payload: bytes) -> dict:
    version = payload[0]
    if version == 1:
        creation_time = struct.unpack(">Q", payload[4:12])[0]
        timescale, duration = struct.unpack(">IQ", payload[20:32])
    else:
        creation_time = struct.unpack(">I", payload[4:8])[0]
        timescale, duration = struct.unpack(">II", payload[12:20])
    next_track_id = struct.unpack(">I", payload[-4:])[0]
    return {"version": version, "timescale": timescale,
            "duration": duration, "next_track_id": next_track_id,
            "creation_time": creation_time}


# MP4/QuickTime のエポックは 1904-01-01 UTC
_MP4_EPOCH = None  # 遅延生成 (datetime を上で import 済み)


def mp4_time_to_datetime(seconds_since_1904: int):
    """mvhd/tkhd の creation_time (1904 起点秒) を datetime に。0 は None。

    返り値は tz=UTC 付きだが、**中身はカメラが書いた時計の値そのもの**。
    規格上は UTC のはずが、DJI / GoPro / Insta360 / Sony など大半のカメラは
    ローカル時刻 (カメラの時計) をそのまま書く。したがって表示するときに
    astimezone() で変換してはいけない (日本なら 9 時間ずれる)。
    差分計算 (連続性の判定) には同じ基準同士なので問題なく使える。
    表示には camera_wall_time() を使うこと。
    """
    import datetime
    if not seconds_since_1904:
        return None
    epoch = datetime.datetime(1904, 1, 1, tzinfo=datetime.timezone.utc)
    try:
        return epoch + datetime.timedelta(seconds=seconds_since_1904)
    except OverflowError:
        return None


def camera_wall_time(dt):
    """mp4_time_to_datetime() の値を「カメラの時計の値」(naive) にする。

    タイムゾーン変換をせず、記録された時分秒をそのまま返す。
    """
    if dt is None:
        return None
    return dt.replace(tzinfo=None)


_QT_CREATIONDATE_KEY = b"com.apple.quicktime.creationdate"
_ISO8601_TZ = re.compile(
    rb"(\d{4}-\d{2}-\d{2})T(\d{2}:\d{2}:\d{2})(?:\.\d+)?([+-]\d{2}):?(\d{2})")


def parse_quicktime_creationdate(moov_bytes: bytes):
    """iPhone 等が書く com.apple.quicktime.creationdate を読む。

    こちらは "2025-09-15T12:54:02+0900" のようにタイムゾーン付きで正確。
    見つかれば (tz付き datetime, その土地の壁時計 naive) を返す。
    """
    import datetime
    if _QT_CREATIONDATE_KEY not in moov_bytes:
        return None
    m = _ISO8601_TZ.search(moov_bytes)
    if not m:
        return None
    try:
        date_s, time_s, tzh, tzm = (x.decode("ascii") for x in m.groups())
        wall = datetime.datetime.strptime(f"{date_s}T{time_s}",
                                          "%Y-%m-%dT%H:%M:%S")
        sign = -1 if tzh.startswith("-") else 1
        offset = datetime.timedelta(hours=abs(int(tzh)), minutes=int(tzm)) * sign
        aware = wall.replace(tzinfo=datetime.timezone(offset))
        return aware, wall
    except (ValueError, OverflowError):
        return None


# コーデック 4CC → 人が読める名前
_CODEC_NAMES = {
    "avc1": "H.264 (AVC)", "avc3": "H.264 (AVC)",
    "hvc1": "H.265 (HEVC)", "hev1": "H.265 (HEVC)",
    "av01": "AV1", "vp09": "VP9", "mp4v": "MPEG-4",
    "mp4a": "AAC", "ac-3": "AC-3", "Opus": "Opus",
}


def media_summary(f: BinaryIO) -> dict:
    """動画の基本情報 (撮影日時・解像度・コーデック・fps 等) をまとめる。"""
    tops = scan_top_level(f)
    moov_top = next(b for b in tops if b.type == b"moov")
    moov_bytes = read_box_bytes(f, moov_top)
    moov = parse_box_tree(moov_bytes, b"moov")
    mvhd = parse_mvhd(moov.find(b"mvhd").payload)

    creation = mp4_time_to_datetime(mvhd["creation_time"])
    # 表示用の撮影日時 (壁時計)。iPhone 等はタイムゾーン付きの正確な値を
    # 別途持っているのでそれを優先し、無ければ mvhd の値をそのまま使う
    # (大半のカメラはローカル時刻を書くので変換しない)。
    qt = parse_quicktime_creationdate(moov_bytes)
    if qt is not None:
        creation_local, creation_source = qt[1], "quicktime"
    else:
        creation_local = camera_wall_time(creation)
        creation_source = "camera" if creation_local else None

    out = {
        "duration_sec": (mvhd["duration"] / mvhd["timescale"]
                         if mvhd["timescale"] else 0),
        "creation_time": creation,            # 差分計算用 (tz=UTC 扱い)
        "creation_local": creation_local,     # 表示用の壁時計 (naive)
        "creation_source": creation_source,   # "quicktime" | "camera" | None
        "width": None, "height": None, "video_codec": None,
        "fps": None, "audio_codec": None, "n_tracks": 0,
    }

    for trak in moov.find_all(b"trak"):
        hdlr = trak.find(b"mdia", b"hdlr")
        handler = parse_hdlr(hdlr.payload)["handler"] if hdlr else b""
        out["n_tracks"] += 1
        # mvhd の duration を 0 や短めに書く機種があるので、トラックの
        # 長さの方が長ければそちらを採用する
        mdhd_box = trak.find(b"mdia", b"mdhd")
        if mdhd_box is not None:
            md = parse_mdhd(mdhd_box.payload)
            if md["timescale"]:
                out["duration_sec"] = max(out["duration_sec"],
                                          md["duration"] / md["timescale"])
        stsd = trak.find(b"mdia", b"minf", b"stbl", b"stsd")
        if not stsd:
            continue
        codec = stsd.payload[12:16].decode("latin-1", "replace") \
            if len(stsd.payload) >= 16 else ""

        if handler == b"vide":
            out["video_codec"] = _CODEC_NAMES.get(codec, codec)
            # VisualSampleEntry: width/height は stsd payload の 40/42 バイト目
            if len(stsd.payload) >= 44:
                w, h = struct.unpack(">HH", stsd.payload[40:44])
                out["width"], out["height"] = w, h
            # fps = 総フレーム数 / 尺
            mdhd = parse_mdhd(trak.find(b"mdia", b"mdhd").payload)
            stts_box = trak.find(b"mdia", b"minf", b"stbl", b"stts")
            if stts_box and mdhd["timescale"] and mdhd["duration"]:
                frames = sum(c for c, _ in parse_stts(stts_box.payload))
                secs = mdhd["duration"] / mdhd["timescale"]
                if secs > 0:
                    out["fps"] = frames / secs
        elif handler == b"soun":
            out["audio_codec"] = _CODEC_NAMES.get(codec, codec)

    return out


def bump_next_track_id(mvhd: Box, new_id: int) -> None:
    mvhd.payload = mvhd.payload[:-4] + struct.pack(">I", new_id)


def parse_mdhd(payload: bytes) -> dict:
    version = payload[0]
    if version == 1:
        timescale, duration = struct.unpack(">IQ", payload[20:32])
    else:
        timescale, duration = struct.unpack(">II", payload[12:20])
    return {"timescale": timescale, "duration": duration}


# ---------------------------------------------------------------------------
# stsd (サンプル記述) の比較用正規化
# ---------------------------------------------------------------------------

# 映像系サンプルエントリ (VisualSampleEntry: 固定部 78 バイト)
_VISUAL_ENTRIES = {
    b"avc1", b"avc2", b"avc3", b"avc4", b"hvc1", b"hev1", b"hvt1",
    b"dvh1", b"dvhe", b"dvav", b"dva1", b"av01", b"vp08", b"vp09",
    b"mp4v", b"s263", b"apch", b"apcn", b"apcs", b"apco", b"ap4h",
    b"mjpa", b"mjpb", b"jpeg", b"png ", b"encv",
}
# 音声系サンプルエントリ (AudioSampleEntry: 固定部 28 バイト + QT 版拡張)
_AUDIO_ENTRIES = {
    b"mp4a", b"ac-3", b"ec-3", b"ac-4", b"alac", b"Opus", b"fLaC",
    b"twos", b"sowt", b"lpcm", b"samr", b"sawb", b"in24", b"in32",
    b"raw ", b"ulaw", b"alaw", b"enca", b"mlpa", b"dtsc", b"dtsh",
    b"dtsl", b"dtse",
}


def normalize_stsd(payload: bytes) -> bytes:
    """stsd の中身から「同じ設定でも毎ファイル変わる値」を取り除く。

    強制分割の判定と結合の互換チェックは stsd をそのまま比較していたが、
    サンプルエントリの中には **ファイルごとに変わって当然の値** がある:

    - ``btrt`` (映像/音声): バッファサイズ・最大/平均ビットレート
    - ``esds`` (AAC 等) の DecoderConfigDescriptor: bufferSizeDB・
      maxBitrate・avgBitrate

    DJI などはこれらを各ファイルの実測値で書くため、最後の短い
    セグメントだけ avgBitrate が違い、「音声のコーデックが違う」として
    結合されない事故が起きていた (実例: Osmo Pocket の 0008 だけ単独)。
    ここではそれらをゼロ埋め/除去し、コーデック・解像度・チャンネル数・
    サンプルレート・デコーダ設定 (avcC/hvcC/DecSpecificInfo) だけを
    比較対象に残す。解析できない部分はそのまま返す (厳しめに倒す)。
    """
    if len(payload) < 8:
        return payload
    try:
        count = struct.unpack(">I", payload[4:8])[0]
        out = bytearray(payload[:8])
        pos = 8
        for _ in range(count):
            if pos + 8 > len(payload):
                break
            size, typ = struct.unpack(">I4s", payload[pos:pos + 8])
            if size == 0:
                size = len(payload) - pos
            if size < 8 or pos + size > len(payload):
                return payload
            out += _normalize_sample_entry(payload[pos:pos + size], typ)
            pos += size
        out += payload[pos:]
        return bytes(out)
    except Exception:
        return payload


def _normalize_sample_entry(entry: bytes, typ: bytes) -> bytes:
    """1 つのサンプルエントリ (size+type 付き) を正規化する。"""
    if typ in _VISUAL_ENTRIES:
        fixed = 8 + 78
    elif typ in _AUDIO_ENTRIES:
        fixed = 8 + 28
        if len(entry) >= 8 + 10:
            qt_version = struct.unpack(">H", entry[16:18])[0]
            if qt_version == 1:
                fixed += 16
            elif qt_version == 2:
                fixed += 36
    else:
        return entry
    if len(entry) < fixed:
        return entry
    head, children = entry[:fixed], entry[fixed:]
    kept = bytearray()
    pos = 0
    while pos + 8 <= len(children):
        size, ctyp = struct.unpack(">I4s", children[pos:pos + 8])
        if size == 0:
            size = len(children) - pos
        if size < 8 or pos + size > len(children):
            kept += children[pos:]       # 壊れている: 残りはそのまま
            break
        child = children[pos:pos + size]
        if ctyp == b"btrt":
            pass                          # ビットレート情報は捨てる
        elif ctyp == b"esds":
            kept += child[:8] + _normalize_esds(child[8:])
        else:
            kept += child
        pos += size
    # サイズ欄は比較にしか使わないので、正規化後の長さに合わせて書き直す
    body = head[8:] + bytes(kept)
    return struct.pack(">I", 8 + len(body)) + typ + body


def _read_desc_size(data: bytes, pos: int) -> Tuple[int, int]:
    """MPEG-4 の可変長サイズ (最大 4 バイト、上位ビットが継続) を読む。"""
    size = 0
    for _ in range(4):
        b = data[pos]
        pos += 1
        size = (size << 7) | (b & 0x7F)
        if not b & 0x80:
            break
    return size, pos


def _normalize_esds(payload: bytes) -> bytes:
    """esds の DecoderConfigDescriptor からビットレート系の値を消す。"""
    try:
        data = bytearray(payload)
        pos = 4                                     # version/flags
        if data[pos] != 0x03:                       # ES_Descriptor
            return payload
        _, pos = _read_desc_size(data, pos + 1)
        pos += 2                                    # ES_ID
        flags = data[pos]
        pos += 1
        if flags & 0x80:
            pos += 2                                # dependsOn_ES_ID
        if flags & 0x40:
            pos += 1 + data[pos]                    # URL
        if flags & 0x20:
            pos += 2                                # OCR_ES_ID
        if data[pos] != 0x04:                       # DecoderConfigDescriptor
            return payload
        _, pos = _read_desc_size(data, pos + 1)
        pos += 2                                    # objectTypeIndication, streamType
        # bufferSizeDB(3) maxBitrate(4) avgBitrate(4)
        data[pos:pos + 11] = b"\x00" * 11
        return bytes(data)
    except (IndexError, struct.error):
        return payload


def parse_hdlr(payload: bytes) -> dict:
    handler = payload[8:12]
    name = payload[24:].split(b"\x00")[0].decode("utf-8", "replace")
    return {"handler": handler, "name": name}


def parse_stts(payload: bytes) -> List[Tuple[int, int]]:
    """(sample_count, sample_delta) のリスト。"""
    count = struct.unpack(">I", payload[4:8])[0]
    vals = _u32s(payload, 8, count * 2)
    return [(vals[i * 2], vals[i * 2 + 1]) for i in range(count)]


def parse_stsz(payload: bytes) -> List[int]:
    sample_size, count = struct.unpack(">II", payload[4:12])
    if sample_size != 0:
        return [sample_size] * count
    return _u32s(payload, 12, count)


def parse_stsc(payload: bytes) -> List[Tuple[int, int, int]]:
    """(first_chunk, samples_per_chunk, sample_desc_index) のリスト。"""
    count = struct.unpack(">I", payload[4:8])[0]
    vals = _u32s(payload, 8, count * 3)
    return [tuple(vals[i * 3:i * 3 + 3]) for i in range(count)]


def parse_stco(payload: bytes, is_co64: bool) -> List[int]:
    count = struct.unpack(">I", payload[4:8])[0]
    if is_co64:
        return list(struct.unpack(f">{count}Q", payload[8:8 + 8 * count]))
    return _u32s(payload, 8, count)


def parse_stss(payload: bytes) -> List[int]:
    """キーフレーム (同期サンプル) の番号リスト。1 始まり。"""
    count = struct.unpack(">I", payload[4:8])[0]
    return _u32s(payload, 8, count)


def parse_ctts(payload: bytes) -> List[Tuple[int, int]]:
    """(sample_count, composition_offset) のリスト。B フレーム用。

    version 1 ではオフセットが符号付き 32bit。
    """
    version = payload[0]
    count = struct.unpack(">I", payload[4:8])[0]
    fmt = ">i" if version == 1 else ">I"
    out = []
    for i in range(count):
        base = 8 + i * 8
        n = struct.unpack(">I", payload[base:base + 4])[0]
        off = struct.unpack(fmt, payload[base + 4:base + 8])[0]
        out.append((n, off))
    return out


# ---------------------------------------------------------------------------
# 位置情報・テレメトリ形式の検出 (GoPro 以外も含む)
# ---------------------------------------------------------------------------

def _parse_iso6709(text: str) -> Optional[Tuple[float, float, Optional[float]]]:
    """ISO 6709 文字列 "+35.6586+139.7454+12.3/" を (緯度,経度,高度) に。"""
    import re
    nums = re.findall(r"[+-]\d+(?:\.\d+)?", text)
    if len(nums) < 2:
        return None
    lat, lon = float(nums[0]), float(nums[1])
    ele = float(nums[2]) if len(nums) >= 3 else None
    return lat, lon, ele


# 360 度動画マーカー (Spherical Video V1) の UUID
_SPHERICAL_V1_UUID = bytes.fromhex("ffcc8263f8554a938814587a02521fdd")


def detect_spherical(f: BinaryIO) -> dict:
    """360 度動画マーカー (Spherical Metadata) を検出する。

    - V1: trak 内の uuid ボックス (XML)。YouTube 等が読む従来方式
    - V2: 映像サンプルエントリ内の sv3d / st3d ボックス (Google 提唱の新方式)

    Returns:
        {"v1": bool, "v2": bool, "projection": "equirectangular"|"cubemap"|None,
         "stereo": bool, "is_360": bool}
    """
    tops = scan_top_level(f)
    moov_top = next(b for b in tops if b.type == b"moov")
    data = read_box_bytes(f, moov_top)

    result = {"v1": False, "v2": False, "projection": None,
              "stereo": False, "is_360": False}

    if _SPHERICAL_V1_UUID in data:
        result["v1"] = True
    # XML 本文でも判定 (uuid が壊れていても拾えるように)
    if b"GSpherical:Spherical" in data or b"<GSpherical:" in data:
        result["v1"] = True

    if b"sv3d" in data:
        result["v2"] = True
    if b"st3d" in data:
        result["stereo"] = True

    # 投影方式
    if b"equirectangular" in data or b"equi" in data:
        result["projection"] = "equirectangular"
    elif b"cubemap" in data or b"cbmp" in data:
        result["projection"] = "cubemap"
    elif b"EquirectangularProjection" in data:
        result["projection"] = "equirectangular"

    result["is_360"] = result["v1"] or result["v2"]
    return result


def detect_telemetry(f: BinaryIO) -> dict:
    """MP4 に含まれる位置情報/テレメトリ形式を検出する。

    Returns 例:
        {"gpmd": True, "location_iso6709": (35.6, 139.7, 12.0),
         "quicktime_location": True, "camm": False, "tracks": [...],
         "formats": ["GoPro GPMF (gpmd)", "スマホ位置情報 (©xyz)"]}
    """
    tops = scan_top_level(f)
    moov_top = next(b for b in tops if b.type == b"moov")
    moov_bytes = read_box_bytes(f, moov_top)
    moov = parse_box_tree(moov_bytes, b"moov")

    result = {
        "gpmd": find_gpmd_trak(moov) is not None,
        "camm": False,
        "location_iso6709": None,
        "quicktime_location": False,
        "gopro_udta": [],
        "formats": [],
    }

    # camm (Camera Motion Metadata: Google/Street View 系, 一部360カメラ)
    for trak in moov.find_all(b"trak"):
        stsd = trak.find(b"mdia", b"minf", b"stbl", b"stsd")
        if stsd and b"camm" in stsd.payload:
            result["camm"] = True

    # udta/©xyz (スマホ等の撮影地点。ISO6709 1 点)
    udta = moov.find(b"udta")
    if udta:
        for c in udta.children:
            if c.type == b"\xa9xyz":
                # 2byte size + 2byte lang + 文字列
                try:
                    slen = struct.unpack(">H", c.payload[:2])[0]
                    text = c.payload[4:4 + slen].decode("ascii", "replace")
                except Exception:
                    text = c.payload[4:].decode("ascii", "replace")
                result["location_iso6709"] = _parse_iso6709(text)
        result["gopro_udta"] = [c.type.decode("latin-1") for c in udta.children
                                if c.type in (b"FIRM", b"LENS", b"CAME",
                                              b"MUID", b"GPMF", b"HMMT", b"SETT")]

    # QuickTime メタデータキー (iPhone: com.apple.quicktime.location.ISO6709)
    if b"com.apple.quicktime.location" in moov_bytes:
        result["quicktime_location"] = True
        if result["location_iso6709"] is None:
            # ilst 内の ISO6709 文字列を拾う
            import re
            m = re.search(rb"([+-]\d+\.\d+[+-]\d+\.\d+[+\-\d./]*)", moov_bytes)
            if m:
                result["location_iso6709"] = _parse_iso6709(
                    m.group(1).decode("ascii", "replace"))

    # DJI / Insta360 等のヒント (トラック名やブランド)
    if b"DJI" in moov_bytes:
        result["formats"].append("DJI 系メタデータの可能性 (SRT字幕も確認)")
    if b"Insta360" in moov_bytes or b"insta360" in moov_bytes:
        result["formats"].append("Insta360 系メタデータの可能性")

    # 形式ラベルを組み立て
    if result["gpmd"]:
        result["formats"].insert(0, "GoPro GPMF (gpmd トラック)")
    if result["camm"]:
        result["formats"].append("Camera Motion Metadata (camm)")
    if result["location_iso6709"]:
        result["formats"].append("撮影地点の GPS 座標 (ISO6709)")
    elif result["quicktime_location"]:
        result["formats"].append("QuickTime 位置情報")

    return result


def sample_offsets(stsz: List[int], stsc: List[Tuple[int, int, int]],
                   chunk_offsets: List[int]) -> List[Tuple[int, int]]:
    """各サンプルの (ファイルオフセット, サイズ) を計算する。"""
    out: List[Tuple[int, int]] = []
    sample_idx = 0
    n_chunks = len(chunk_offsets)
    for i, (first_chunk, per_chunk, _) in enumerate(stsc):
        last_chunk = (stsc[i + 1][0] - 1) if i + 1 < len(stsc) else n_chunks
        for chunk in range(first_chunk, last_chunk + 1):
            pos = chunk_offsets[chunk - 1]
            for _ in range(per_chunk):
                if sample_idx >= len(stsz):
                    return out
                out.append((pos, stsz[sample_idx]))
                pos += stsz[sample_idx]
                sample_idx += 1
    return out


# ---------------------------------------------------------------------------
# gpmd トラック抽出
# ---------------------------------------------------------------------------

@dataclass
class GPMFSample:
    data: bytes
    time_sec: float       # トラック先頭からの提示時刻 (秒)
    duration_sec: float


def find_gpmd_trak(moov: Box) -> Optional[Box]:
    """gpmd サンプルエントリを持つトラックを探す。"""
    for trak in moov.find_all(b"trak"):
        stsd = trak.find(b"mdia", b"minf", b"stbl", b"stsd")
        if stsd and b"gpmd" in stsd.payload:
            return trak
    return None


def extract_gpmf_samples(f: BinaryIO) -> List[GPMFSample]:
    """MP4 から GPMF ペイロード (gpmd サンプル) を取り出す。"""
    tops = scan_top_level(f)
    moov_top = next(b for b in tops if b.type == b"moov")
    moov = parse_box_tree(read_box_bytes(f, moov_top), b"moov")

    trak = find_gpmd_trak(moov)
    if trak is None:
        raise MP4Error("gpmd トラックが見つかりません (GPMF メタデータなし)")

    stbl = trak.find(b"mdia", b"minf", b"stbl")
    mdhd = parse_mdhd(trak.find(b"mdia", b"mdhd").payload)
    stsz = parse_stsz(stbl.find(b"stsz").payload)
    stsc = parse_stsc(stbl.find(b"stsc").payload)
    stco_box = stbl.find(b"stco")
    if stco_box is not None:
        chunk_offsets = parse_stco(stco_box.payload, is_co64=False)
    else:
        chunk_offsets = parse_stco(stbl.find(b"co64").payload, is_co64=True)
    stts = parse_stts(stbl.find(b"stts").payload)

    # サンプル時刻を展開
    times: List[Tuple[float, float]] = []
    t = 0
    for count, delta in stts:
        for _ in range(count):
            times.append((t / mdhd["timescale"], delta / mdhd["timescale"]))
            t += delta

    samples: List[GPMFSample] = []
    for i, (off, size) in enumerate(sample_offsets(stsz, stsc, chunk_offsets)):
        f.seek(off)
        data = f.read(size)
        if len(data) != size:
            raise MP4Error(f"サンプル {i} の読み取りに失敗 (offset={off}, size={size})")
        time_sec, dur = times[i] if i < len(times) else (0.0, 0.0)
        samples.append(GPMFSample(data=data, time_sec=time_sec, duration_sec=dur))
    return samples


# ---------------------------------------------------------------------------
# フルボックス生成ヘルパ
# ---------------------------------------------------------------------------

def _box(btype: bytes, body: bytes) -> bytes:
    return struct.pack(">I", 8 + len(body)) + btype + body


def _full(btype: bytes, version: int, flags: int, body: bytes) -> bytes:
    return _box(btype, struct.pack(">B", version) + flags.to_bytes(3, "big") + body)


_MATRIX_IDENTITY = struct.pack(">9i", 0x10000, 0, 0, 0, 0x10000, 0, 0, 0, 0x40000000)


def build_gpmd_trak(track_id: int, movie_timescale: int, movie_duration: int,
                    sample_sizes: List[int], sample_durations_ms: List[int],
                    chunk_offset: int, creation_time: int = 0,
                    handler_name: str = "GoPro MET  ") -> bytes:
    """GoPro 形式の gpmd メタデータトラック (trak ボックス) を生成する。

    - mdhd タイムスケール 1000 (ミリ秒)
    - 全サンプルを 1 チャンクに連続配置 (chunk_offset が先頭)
    """
    media_timescale = 1000
    media_duration = sum(sample_durations_ms)

    # 長尺動画 (マイクロ秒 timescale で約 71.6 分超など) では duration が
    # 32bit に収まらないため、その場合は version 1 (64bit) の
    # tkhd / mdhd を出力する
    _MAX32 = 0xFFFFFFFF
    need64 = (movie_duration > _MAX32 or media_duration > _MAX32
              or creation_time > _MAX32)

    # --- tkhd (enabled) ---
    if need64:
        tkhd_body = (struct.pack(">QQIIQ", creation_time, creation_time,
                                 track_id, 0, movie_duration))
        tkhd_ver = 1
    else:
        tkhd_body = struct.pack(">IIIII", creation_time, creation_time,
                                track_id, 0, movie_duration)
        tkhd_ver = 0
    tkhd = _full(b"tkhd", tkhd_ver, 0x000001,
                 tkhd_body
                 + b"\x00" * 8            # reserved
                 + struct.pack(">hhhh", 0, 0, 0, 0)  # layer, alt_group, volume, reserved
                 + _MATRIX_IDENTITY
                 + struct.pack(">II", 0, 0))  # width, height

    # --- mdhd ---
    if need64:
        mdhd_body = struct.pack(">QQIQ", creation_time, creation_time,
                                media_timescale, media_duration)
        mdhd_ver = 1
    else:
        mdhd_body = struct.pack(">IIII", creation_time, creation_time,
                                media_timescale, media_duration)
        mdhd_ver = 0
    mdhd = _full(b"mdhd", mdhd_ver, 0,
                 mdhd_body
                 + struct.pack(">Hh", 0x55C4, 0))  # language 'und'

    # --- hdlr ---
    name_b = handler_name.encode("utf-8") + b"\x00"
    hdlr = _full(b"hdlr", 0, 0,
                 b"\x00" * 4 + b"meta" + b"\x00" * 12 + name_b)

    # --- minf: gmhd(gmin) + dinf(dref/url) + stbl ---
    gmin = _full(b"gmin", 0, 0,
                 struct.pack(">H", 0)         # graphicsmode
                 + struct.pack(">HHH", 0, 0, 0)  # opcolor
                 + struct.pack(">hH", 0, 0))  # balance, reserved
    gmhd = _box(b"gmhd", gmin)

    url = _full(b"url ", 0, 1, b"")  # self-contained
    dref = _full(b"dref", 0, 0, struct.pack(">I", 1) + url)
    dinf = _box(b"dinf", dref)

    # --- stsd: gpmd サンプルエントリ ---
    gpmd_entry = _box(b"gpmd", b"\x00" * 6 + struct.pack(">H", 1))
    stsd = _full(b"stsd", 0, 0, struct.pack(">I", 1) + gpmd_entry)

    # --- stts: 連続する同一 duration をラン圧縮 ---
    runs: List[Tuple[int, int]] = []
    for d in sample_durations_ms:
        if runs and runs[-1][1] == d:
            runs[-1] = (runs[-1][0] + 1, d)
        else:
            runs.append((1, d))
    stts = _full(b"stts", 0, 0,
                 struct.pack(">I", len(runs))
                 + b"".join(struct.pack(">II", c, d) for c, d in runs))

    # --- stsc: 1 チャンクに全サンプル ---
    stsc = _full(b"stsc", 0, 0,
                 struct.pack(">I", 1) + struct.pack(">III", 1, len(sample_sizes), 1))

    stsz = _full(b"stsz", 0, 0,
                 struct.pack(">II", 0, len(sample_sizes))
                 + b"".join(struct.pack(">I", s) for s in sample_sizes))

    if chunk_offset <= 0xFFFFFFFF:
        stco = _full(b"stco", 0, 0,
                     struct.pack(">I", 1) + struct.pack(">I", chunk_offset))
    else:
        stco = _full(b"co64", 0, 0,
                     struct.pack(">I", 1) + struct.pack(">Q", chunk_offset))

    stbl = _box(b"stbl", stsd + stts + stsc + stsz + stco)
    minf = _box(b"minf", gmhd + dinf + stbl)
    mdia = _box(b"mdia", mdhd + hdlr + minf)
    return _box(b"trak", tkhd + mdia)


# ---------------------------------------------------------------------------
# チャンクオフセット補正
# ---------------------------------------------------------------------------

def patch_chunk_offsets(moov: Box, remap: Callable[[int], int]) -> None:
    """moov 内の全 stco/co64 のオフセットを remap 関数で変換する。"""
    for trak in moov.find_all(b"trak"):
        stbl = trak.find(b"mdia", b"minf", b"stbl")
        if stbl is None:
            continue
        for name, fmt, width in ((b"stco", ">I", 4), (b"co64", ">Q", 8)):
            box = stbl.find(name)
            if box is None:
                continue
            count = struct.unpack(">I", box.payload[4:8])[0]
            head = box.payload[:8]
            body = box.payload[8:8 + width * count]
            new_vals = []
            for i in range(count):
                old = struct.unpack(fmt, body[i * width:(i + 1) * width])[0]
                new = remap(old)
                if name == b"stco" and new > 0xFFFFFFFF:
                    raise MP4Error(
                        "補正後のチャンクオフセットが 32bit を超えます "
                        "(co64 変換が必要な大容量ファイル)")
                new_vals.append(struct.pack(fmt, new))
            box.payload = head + b"".join(new_vals)


# ---------------------------------------------------------------------------
# 注入 (ファイル再構築)
# ---------------------------------------------------------------------------

def inject_gpmf_track(
    src: BinaryIO,
    dst: BinaryIO,
    payloads: List[bytes],
    payload_durations_ms: List[int],
    udta_extra: bytes = b"",
    new_ftyp: Optional[bytes] = None,
    handler_renames: Optional[dict] = None,
) -> dict:
    """MP4 に gpmd トラックを注入して dst に書き出す。

    出力レイアウト:
        [moov 以外の元ボックス (元の順序)] + [新 mdat (GPMF)] + [新 moov]

    既存データのオフセットずれは stco/co64 を書き換えて補正する。

    Args:
        payloads: GPMF ペイロード (通常 1 秒ごと 1 個)
        payload_durations_ms: 各ペイロードの継続時間 (ms)
        udta_extra: moov/udta に追記する GoPro 識別ボックス列
        new_ftyp: 置換する ftyp ボックス全体 (None なら元のまま)
        handler_renames: {b"vide": "GoPro AVC  ", ...} 既存トラックの hdlr 名変更
    Returns:
        統計情報 dict
    """
    if len(payloads) != len(payload_durations_ms):
        raise GPMFError("payloads と durations の数が一致しません")
    if not payloads:
        raise GPMFError("注入する GPMF ペイロードがありません")

    tops = scan_top_level(src)
    moov_top = next(b for b in tops if b.type == b"moov")
    moov = parse_box_tree(read_box_bytes(src, moov_top), b"moov")

    mvhd_box = moov.find(b"mvhd")
    if mvhd_box is None:
        raise MP4Error("mvhd がありません")
    mvhd = parse_mvhd(mvhd_box.payload)

    if find_gpmd_trak(moov) is not None:
        raise MP4Error("既に gpmd トラックがあります (二重注入を防止)")

    # --- 既存トラックの hdlr 名変更 (任意) ---
    renamed = []
    if handler_renames:
        for trak in moov.find_all(b"trak"):
            hdlr = trak.find(b"mdia", b"hdlr")
            if hdlr is None:
                continue
            info = parse_hdlr(hdlr.payload)
            new_name = handler_renames.get(info["handler"])
            if new_name:
                head = hdlr.payload[:24]
                hdlr.payload = head + new_name.encode("utf-8") + b"\x00"
                renamed.append((info["handler"].decode(), new_name))

    # --- 出力レイアウト計画: moov 以外を元順で配置 ---
    plan: List[Tuple[TopLevelBox, int]] = []  # (元ボックス, 新オフセット)
    cursor = 0
    for b in tops:
        if b.type == b"moov":
            continue
        new_size = b.size
        if b.type == b"ftyp" and new_ftyp is not None:
            new_size = len(new_ftyp)
        plan.append((b, cursor))
        cursor += new_size

    # 新 mdat (GPMF ペイロード連結)
    gpmf_blob = b"".join(payloads)
    new_mdat_offset = cursor
    payload_start = new_mdat_offset + 8  # mdat ヘッダの直後
    cursor += 8 + len(gpmf_blob)

    # --- チャンクオフセット remap ---
    ranges = []
    for b, new_off in plan:
        if b.type == b"ftyp" and new_ftyp is not None:
            continue  # ftyp にチャンクは無い
        ranges.append((b.offset, b.offset + b.size, new_off - b.offset))

    def remap(old: int) -> int:
        for lo, hi, delta in ranges:
            if lo <= old < hi:
                return old + delta
        # mdat 範囲外を指すオフセット (壊れたファイル) はそのまま
        return old

    patch_chunk_offsets(moov, remap)

    # --- 新 gpmd トラック ---
    new_track_id = mvhd["next_track_id"]
    bump_next_track_id(mvhd_box, new_track_id + 1)
    trak_bytes = build_gpmd_trak(
        track_id=new_track_id,
        movie_timescale=mvhd["timescale"],
        movie_duration=mvhd["duration"],
        sample_sizes=[len(p) for p in payloads],
        sample_durations_ms=payload_durations_ms,
        chunk_offset=payload_start,
    )
    moov.children.append(parse_box_tree(trak_bytes, b"trak"))

    # --- udta へ GoPro 識別ボックスを追記 ---
    if udta_extra:
        udta = moov.find(b"udta")
        if udta is None:
            udta = Box(type=b"udta", is_container=True)
            moov.children.append(udta)
        udta.children.extend(_parse_children(udta_extra, 0, len(udta_extra)))

    # --- 書き出し ---
    for b, new_off in plan:
        assert dst.tell() == new_off, (dst.tell(), new_off)
        if b.type == b"ftyp" and new_ftyp is not None:
            dst.write(new_ftyp)
        else:
            _copy_range(src, dst, b.offset, b.size)

    dst.write(struct.pack(">I", 8 + len(gpmf_blob)) + b"mdat" + gpmf_blob)
    moov_bytes = moov.serialize()
    dst.write(moov_bytes)

    return {
        "track_id": new_track_id,
        "payload_count": len(payloads),
        "gpmf_bytes": len(gpmf_blob),
        "renamed_handlers": renamed,
        "moov_size": len(moov_bytes),
    }


def _copy_range(src: BinaryIO, dst: BinaryIO, offset: int, size: int,
                chunk: int = 8 * 1024 * 1024) -> None:
    src.seek(offset)
    remaining = size
    while remaining > 0:
        data = src.read(min(chunk, remaining))
        if not data:
            raise MP4Error("コピー中に EOF")
        dst.write(data)
        remaining -= len(data)


def build_ftyp_gopro() -> bytes:
    """GoPro カメラと同じ ftyp (major brand mp41)。"""
    return _box(b"ftyp", b"mp41" + struct.pack(">I", 0x20130101)
                + b"mp41" + b"mp42" + b"isom")


def movie_duration_seconds(f: BinaryIO) -> float:
    """mvhd から動画の長さ (秒) を取得する。"""
    tops = scan_top_level(f)
    moov_top = next(b for b in tops if b.type == b"moov")
    moov = parse_box_tree(read_box_bytes(f, moov_top), b"moov")
    mvhd = parse_mvhd(moov.find(b"mvhd").payload)
    if mvhd["timescale"] == 0:
        raise MP4Error("mvhd の timescale が 0")
    return mvhd["duration"] / mvhd["timescale"]
