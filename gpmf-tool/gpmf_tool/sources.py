"""GoPro 以外の機種が動画に埋め込むテレメトリを読み取る。

対応:
- iPhone / Android / Sony: MP4 の ``©xyz`` / QuickTime ISO6709 = 撮影地点 1 点
- DJI (ドローン / Osmo): SRT 字幕 (別ファイル or 動画内の字幕トラック)
  に埋まった GPS 軌跡。複数の DJI SRT 方言に対応
- Insta360 / Sony 等: Studio で書き出した SRT / GPX があればそれを使う

いずれも ``telemetry.GPSPoint`` のリストに正規化して返すので、その後は
GoPro と同じ GPMF 生成パイプラインに載せられる。
"""

from __future__ import annotations

import datetime
import os
import re
import struct
from typing import BinaryIO, List, Optional, Tuple

from . import klv, mp4, telemetry
from .telemetry import GPSPoint


# ---------------------------------------------------------------------------
# SRT (DJI 等) の解析
# ---------------------------------------------------------------------------

_SRT_TIME = re.compile(
    r"(\d{2}):(\d{2}):(\d{2})[,.](\d{3})\s*-->\s*"
    r"(\d{2}):(\d{2}):(\d{2})[,.](\d{3})")

# ラベル付き: [latitude: 35.6] [longitude: 139.7] [abs_alt: 12.3]
_LAT_LABEL = re.compile(r"latitude\s*[:\s]\s*([+-]?\d+\.?\d*)", re.I)
_LON_LABEL = re.compile(r"longitude\s*[:\s]\s*([+-]?\d+\.?\d*)", re.I)
_ABS_ALT = re.compile(r"abs_alt\s*[:\s]\s*([+-]?\d+\.?\d*)", re.I)
_REL_ALT = re.compile(r"rel_alt\s*[:\s]\s*([+-]?\d+\.?\d*)", re.I)
_ALT_LABEL = re.compile(r"\baltitude\s*[:\s]\s*([+-]?\d+\.?\d*)", re.I)
# 括弧形式: GPS(139.7,35.6,14) / GPS (139.7,35.6,14)
_GPS_PAREN = re.compile(
    r"GPS\s*\(\s*([+-]?\d+\.?\d*)\s*,\s*([+-]?\d+\.?\d*)\s*"
    r"(?:,\s*([+-]?\d+\.?\d*)\s*)?\)", re.I)
# 日時: 2024-06-01 09:00:00.000 / 2024.06.01 09:00:00
_DATETIME = re.compile(
    r"(\d{4})[-.](\d{2})[-.](\d{2})\s+(\d{2}):(\d{2}):(\d{2})(?:\.(\d+))?")


def _srt_time_to_sec(h, m, s, ms) -> float:
    return int(h) * 3600 + int(m) * 60 + int(s) + int(ms) / 1000.0


def _extract_latlon(text: str) -> Optional[Tuple[float, float, Optional[float]]]:
    """1 つの字幕テキストから (緯度, 経度, 高度) を取り出す。"""
    lat = lon = None
    alt: Optional[float] = None

    mlat, mlon = _LAT_LABEL.search(text), _LON_LABEL.search(text)
    if mlat and mlon:
        lat, lon = float(mlat.group(1)), float(mlon.group(1))
    else:
        mp_ = _GPS_PAREN.search(text)
        if mp_:
            a, b = float(mp_.group(1)), float(mp_.group(2))
            # DJI は GPS(経度, 緯度, ...) の順。|値|>90 は経度、で判定
            if abs(a) > 90 >= abs(b):
                lon, lat = a, b
            elif abs(b) > 90 >= abs(a):
                lat, lon = a, b
            else:
                lon, lat = a, b  # 既定は DJI 順 (経度, 緯度)
            if mp_.group(3):
                alt = float(mp_.group(3))

    if lat is None or lon is None:
        return None

    for rx in (_ABS_ALT, _ALT_LABEL, _REL_ALT):
        m = rx.search(text)
        if m:
            alt = float(m.group(1))
            break
    return lat, lon, alt if alt is not None else 0.0


def _extract_datetime(text: str) -> Optional[datetime.datetime]:
    m = _DATETIME.search(text)
    if not m:
        return None
    y, mo, d, hh, mm, ss, frac = m.groups()
    micro = int((frac or "0").ljust(6, "0")[:6])
    try:
        return datetime.datetime(int(y), int(mo), int(d), int(hh), int(mm),
                                 int(ss), micro, tzinfo=datetime.timezone.utc)
    except ValueError:
        return None


def parse_telemetry_entries(entries: List[Tuple[float, str]]
                            ) -> Tuple[List[GPSPoint], Optional[datetime.datetime]]:
    """(時刻秒, テキスト) の列から GPS 点列と先頭 UTC 時刻を得る。"""
    points: List[GPSPoint] = []
    start_dt: Optional[datetime.datetime] = None
    for t, text in entries:
        if start_dt is None:
            start_dt = _extract_datetime(text)
        ll = _extract_latlon(text)
        if ll is None:
            continue
        lat, lon, alt = ll
        points.append(GPSPoint(time=t, lat=lat, lon=lon, ele=alt))
    # 速度は resample 時に計算されるのでここでは 0
    return points, start_dt


def parse_srt(srt_text: str) -> Tuple[List[GPSPoint], Optional[datetime.datetime]]:
    """SRT 字幕全体を解析する。"""
    entries: List[Tuple[float, str]] = []
    blocks = re.split(r"\n\s*\n", srt_text.replace("\r\n", "\n"))
    for block in blocks:
        mt = _SRT_TIME.search(block)
        if not mt:
            continue
        t = _srt_time_to_sec(*mt.groups()[:4])
        # 時間行より後ろをテキストとして扱う
        text = block[mt.end():].strip()
        # HTML タグ除去
        text = re.sub(r"<[^>]+>", " ", text)
        entries.append((t, text))
    return parse_telemetry_entries(entries)


# ---------------------------------------------------------------------------
# 動画内の字幕トラック (tx3g / mov_text) からテキストを取り出す
# ---------------------------------------------------------------------------

def _decode_tx3g_sample(data: bytes) -> str:
    """tx3g/mov_text サンプル: 先頭 2byte が文字列長。"""
    if len(data) < 2:
        return ""
    n = struct.unpack(">H", data[:2])[0]
    return data[2:2 + n].decode("utf-8", "replace")


def _find_text_trak(moov) -> Optional[object]:
    for trak in moov.find_all(b"trak"):
        hdlr = trak.find(b"mdia", b"hdlr")
        handler = mp4.parse_hdlr(hdlr.payload)["handler"] if hdlr else b""
        stsd = trak.find(b"mdia", b"minf", b"stbl", b"stsd")
        sd = stsd.payload if stsd else b""
        if handler in (b"sbtl", b"text") or b"tx3g" in sd or b"text" in sd:
            return trak
    return None


def extract_subtitle_entries(f: BinaryIO) -> List[Tuple[float, str]]:
    """動画内の字幕トラックから (時刻秒, テキスト) を取り出す。"""
    tops = mp4.scan_top_level(f)
    moov_top = next(b for b in tops if b.type == b"moov")
    moov = mp4.parse_box_tree(mp4.read_box_bytes(f, moov_top), b"moov")
    trak = _find_text_trak(moov)
    if trak is None:
        return []

    stbl = trak.find(b"mdia", b"minf", b"stbl")
    mdhd = mp4.parse_mdhd(trak.find(b"mdia", b"mdhd").payload)
    timescale = mdhd["timescale"] or 1000
    stsz = mp4.parse_stsz(stbl.find(b"stsz").payload)
    stsc = mp4.parse_stsc(stbl.find(b"stsc").payload)
    stco_box = stbl.find(b"stco")
    if stco_box is not None:
        chunks = mp4.parse_stco(stco_box.payload, is_co64=False)
    else:
        chunks = mp4.parse_stco(stbl.find(b"co64").payload, is_co64=True)
    stts = mp4.parse_stts(stbl.find(b"stts").payload)

    times: List[float] = []
    t = 0
    for count, delta in stts:
        for _ in range(count):
            times.append(t / timescale)
            t += delta

    entries: List[Tuple[float, str]] = []
    is_tx3g = b"tx3g" in stbl.find(b"stsd").payload or \
        b"text" in stbl.find(b"stsd").payload
    for i, (off, size) in enumerate(
            mp4.sample_offsets(stsz, stsc, chunks)):
        f.seek(off)
        data = f.read(size)
        text = _decode_tx3g_sample(data) if is_tx3g else \
            data.decode("utf-8", "replace")
        tt = times[i] if i < len(times) else 0.0
        if text.strip():
            entries.append((tt, text))
    return entries


# ---------------------------------------------------------------------------
# 統合ローダ
# ---------------------------------------------------------------------------

def _sidecar_srt(path: str) -> Optional[str]:
    stem = os.path.splitext(path)[0]
    for cand in (stem + ".srt", stem + ".SRT", path + ".srt"):
        if os.path.isfile(cand):
            return cand
    return None


def load_video_telemetry(path: str) -> Optional[
        Tuple[List[GPSPoint], Optional[datetime.datetime], str]]:
    """動画から使えるテレメトリを自動判定して取り出す。

    優先順: GoPro GPMF → 動画内字幕(DJI等) → 外部SRT → 撮影地点1点(スマホ等)
    Returns (点列, 先頭UTC時刻, 形式ラベル) / 見つからなければ None
    """
    # 1) GoPro GPMF
    with open(path, "rb") as f:
        try:
            samples = mp4.extract_gpmf_samples(f)
            parsed = [(s.time_sec, klv.parse(s.data, strict=False))
                      for s in samples]
            pts = telemetry.extract_gps_points(parsed)
            if pts:
                start = next((w for w, _ in pts if w is not None), None)
                return [p for _, p in pts], start, "GoPro GPMF"
        except mp4.MP4Error:
            pass

    # 2) 動画内の字幕トラック (DJI 等)
    with open(path, "rb") as f:
        try:
            entries = extract_subtitle_entries(f)
        except mp4.MP4Error:
            entries = []
    if entries:
        points, start = parse_telemetry_entries(entries)
        if points:
            return points, start, "動画内SRT字幕 (DJI等)"

    # 3) 外部 SRT (別ファイル)
    srt = _sidecar_srt(path)
    if srt:
        with open(srt, "r", encoding="utf-8", errors="replace") as sf:
            points, start = parse_srt(sf.read())
        if points:
            return points, start, f"外部SRT ({os.path.basename(srt)})"

    # 4) 撮影地点 1 点 (iPhone / Android / Sony)
    with open(path, "rb") as f:
        tele = mp4.detect_telemetry(f)
    if tele["location_iso6709"]:
        lat, lon, ele = tele["location_iso6709"]
        # 静止 1 点 → 動画全体に同じ座標 (2 点で span を作る)
        pts = [GPSPoint(time=0.0, lat=lat, lon=lon, ele=ele or 0.0),
               GPSPoint(time=1.0, lat=lat, lon=lon, ele=ele or 0.0)]
        return pts, None, "撮影地点1点 (スマホ/Sony等)"

    return None
