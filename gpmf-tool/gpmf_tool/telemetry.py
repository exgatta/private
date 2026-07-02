"""テレメトリの高レベル処理。

- GPX ファイルの読み込みと動画長へのリサンプリング
- GoPro HERO 互換の GPS5 ストリームを含む GPMF ペイロード生成 (1 秒 = 1 ペイロード)
- 既存 GPMF からの GPS 抽出と GPX 書き出し
"""

from __future__ import annotations

import datetime
import math
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from typing import List, Optional, Tuple

from . import klv
from .klv import GPMFError, GPMFItem


@dataclass
class GPSPoint:
    time: float          # 先頭からの秒
    lat: float           # 度
    lon: float           # 度
    ele: float           # m
    speed2d: float = 0.0  # m/s
    speed3d: float = 0.0  # m/s


# ---------------------------------------------------------------------------
# GPX 読み込み
# ---------------------------------------------------------------------------

def _strip_ns(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _parse_gpx_time(text: str) -> datetime.datetime:
    t = text.strip().replace("Z", "+00:00")
    dt = datetime.datetime.fromisoformat(t)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=datetime.timezone.utc)
    return dt


def load_gpx(path: str) -> Tuple[List[GPSPoint], Optional[datetime.datetime]]:
    """GPX ファイルからトラックポイントを読み込む。

    Returns:
        (先頭を 0 秒とした GPSPoint リスト, 先頭ポイントの UTC 時刻)
    """
    root = ET.parse(path).getroot()
    raw: List[Tuple[Optional[datetime.datetime], float, float, float]] = []
    for elem in root.iter():
        if _strip_ns(elem.tag) not in ("trkpt", "rtept", "wpt"):
            continue
        lat = float(elem.get("lat"))
        lon = float(elem.get("lon"))
        ele = 0.0
        when: Optional[datetime.datetime] = None
        for child in elem:
            name = _strip_ns(child.tag)
            if name == "ele" and child.text:
                ele = float(child.text)
            elif name == "time" and child.text:
                when = _parse_gpx_time(child.text)
        raw.append((when, lat, lon, ele))

    if len(raw) < 2:
        raise GPMFError(f"GPX にトラックポイントが不足しています ({len(raw)} 点)")

    start_time = raw[0][0]
    points: List[GPSPoint] = []
    if all(r[0] is not None for r in raw):
        t0 = raw[0][0]
        for when, lat, lon, ele in raw:
            points.append(GPSPoint(time=(when - t0).total_seconds(),
                                   lat=lat, lon=lon, ele=ele))
        # 時刻が逆行/重複している点を除去
        cleaned = [points[0]]
        for p in points[1:]:
            if p.time > cleaned[-1].time:
                cleaned.append(p)
        points = cleaned
    else:
        # 時刻なし GPX: 等間隔 (1 秒) とみなす
        for i, (_, lat, lon, ele) in enumerate(raw):
            points.append(GPSPoint(time=float(i), lat=lat, lon=lon, ele=ele))

    if len(points) < 2:
        raise GPMFError("有効なトラックポイントが不足しています")
    return points, start_time


# ---------------------------------------------------------------------------
# リサンプリングと速度計算
# ---------------------------------------------------------------------------

_EARTH_R = 6371008.8  # m


def _haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = p2 - p1
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * _EARTH_R * math.asin(min(1.0, math.sqrt(a)))


def resample_track(points: List[GPSPoint], duration_sec: float,
                   rate_hz: float = 10.0,
                   fit_duration: bool = True) -> List[GPSPoint]:
    """トラックを rate_hz で等間隔リサンプリングする。

    fit_duration=True の場合、GPX の全体時間を動画長に合わせて伸縮する
    (GPX と動画の長さが違ってもテレメトリが動画全体をカバーする)。
    """
    src_duration = points[-1].time - points[0].time
    if src_duration <= 0:
        raise GPMFError("GPX の時間長が 0 です")
    scale = (src_duration / duration_sec) if fit_duration else 1.0

    n = max(2, int(round(duration_sec * rate_hz)))
    dt = duration_sec / n
    out: List[GPSPoint] = []
    idx = 0
    t0 = points[0].time
    for i in range(n):
        t_video = i * dt
        t_src = t0 + t_video * scale
        # t_src を挟む区間を探す
        while idx + 1 < len(points) - 1 and points[idx + 1].time <= t_src:
            idx += 1
        a, b = points[idx], points[min(idx + 1, len(points) - 1)]
        span = b.time - a.time
        f = 0.0 if span <= 0 else max(0.0, min(1.0, (t_src - a.time) / span))
        out.append(GPSPoint(
            time=t_video,
            lat=a.lat + (b.lat - a.lat) * f,
            lon=a.lon + (b.lon - a.lon) * f,
            ele=a.ele + (b.ele - a.ele) * f,
        ))

    # 速度 (前進差分、先頭は次点と同じ)
    for i in range(1, len(out)):
        p, q = out[i - 1], out[i]
        dist2d = _haversine(p.lat, p.lon, q.lat, q.lon)
        dz = q.ele - p.ele
        q.speed2d = dist2d / dt
        q.speed3d = math.sqrt(dist2d ** 2 + dz ** 2) / dt
    if len(out) > 1:
        out[0].speed2d = out[1].speed2d
        out[0].speed3d = out[1].speed3d
    return out


# ---------------------------------------------------------------------------
# GPMF ペイロード生成 (GoPro HERO 互換)
# ---------------------------------------------------------------------------

GPS5_SCALE = (10000000, 10000000, 1000, 1000, 100)
GPS5_STREAM_NAME = "GPS (Lat., Long., Alt., 2D speed, 3D speed)"


def build_gps5_stream(points: List[GPSPoint], total_samples: int,
                      utc_time: Optional[datetime.datetime],
                      gps_fix: int = 3, gps_precision: int = 150) -> bytes:
    """1 ペイロード分の GPS5 STRM を生成する。"""
    body = b""
    body += klv.make_item("STNM", "c", GPS5_STREAM_NAME)
    body += klv.make_item("TSMP", "L", total_samples)
    body += klv.make_item("GPSF", "L", gps_fix)
    if utc_time is not None:
        body += klv.make_item("GPSU", "U", klv.datetime_to_gpsu(utc_time))
    body += klv.make_item("GPSP", "S", gps_precision)
    body += klv.make_item("GPSA", "F", "MSLV")  # 高度基準: 平均海面
    body += klv.make_item("UNIT", "c", ["deg", "deg", "m", "m/s", "m/s"])
    body += klv.make_item("SCAL", "l", [(s,) for s in GPS5_SCALE], struct_count=1)
    samples = [
        (round(p.lat * GPS5_SCALE[0]),
         round(p.lon * GPS5_SCALE[1]),
         round(p.ele * GPS5_SCALE[2]),
         round(p.speed2d * GPS5_SCALE[3]),
         round(p.speed3d * GPS5_SCALE[4]))
        for p in points
    ]
    body += klv.make_item("GPS5", "l", samples, struct_count=5)
    return klv.make_nested("STRM", body)


def build_payloads(points: List[GPSPoint], duration_sec: float,
                   device_name: str,
                   start_time: Optional[datetime.datetime],
                   device_id: int = 1) -> Tuple[List[bytes], List[int]]:
    """1 秒ごとの DEVC ペイロード列を生成する。

    Returns:
        (ペイロードのリスト, 各ペイロードの継続時間 ms のリスト)
    """
    n_seconds = max(1, math.ceil(duration_sec))
    payloads: List[bytes] = []
    durations: List[int] = []
    consumed = 0
    for sec in range(n_seconds):
        sec_end = min((sec + 1), duration_sec)
        dur_ms = int(round((sec_end - sec) * 1000))
        if dur_ms <= 0:
            break
        chunk = [p for p in points
                 if sec <= p.time < sec_end] if points else []
        consumed += len(chunk)

        dev_body = klv.make_item("DVID", "L", device_id)
        dev_body += klv.make_item("DVNM", "c", device_name)
        if chunk:
            utc = (start_time + datetime.timedelta(seconds=chunk[0].time)
                   if start_time else None)
            dev_body += build_gps5_stream(chunk, total_samples=consumed,
                                          utc_time=utc)
        payloads.append(klv.make_nested("DEVC", dev_body))
        durations.append(dur_ms)
    return payloads, durations


def build_device_only_payloads(duration_sec: float, device_name: str,
                               device_id: int = 1) -> Tuple[List[bytes], List[int]]:
    """GPS なし (デバイス情報のみ) のペイロード列。"""
    n_seconds = max(1, math.ceil(duration_sec))
    payloads, durations = [], []
    for sec in range(n_seconds):
        sec_end = min(sec + 1, duration_sec)
        dur_ms = int(round((sec_end - sec) * 1000))
        if dur_ms <= 0:
            break
        body = klv.make_item("DVID", "L", device_id)
        body += klv.make_item("DVNM", "c", device_name)
        payloads.append(klv.make_nested("DEVC", body))
        durations.append(dur_ms)
    return payloads, durations


# ---------------------------------------------------------------------------
# 抽出: GPMF -> GPS ポイント / GPX
# ---------------------------------------------------------------------------

def extract_gps_points(parsed_payloads: List[Tuple[float, List[GPMFItem]]]
                       ) -> List[Tuple[Optional[datetime.datetime], GPSPoint]]:
    """パース済みペイロード列から GPS5/GPS9 サンプルを取り出す。

    Args:
        parsed_payloads: (ペイロード開始秒, パース済み要素) のリスト
    """
    out: List[Tuple[Optional[datetime.datetime], GPSPoint]] = []
    for payload_time, items in parsed_payloads:
        root = GPMFItem(key="ROOT", type_char="", struct_size=0, repeat=0,
                        children=items)
        for strm in root.find_all("STRM"):
            gps5 = strm.find_first("GPS5", recursive=False)
            gps9 = strm.find_first("GPS9", recursive=False)
            if gps5 is None and gps9 is None:
                continue
            scal_item = strm.find_first("SCAL", recursive=False)
            scal = _scal_values(scal_item)
            gpsu_item = strm.find_first("GPSU", recursive=False)
            base_dt = (klv.gpsu_to_datetime(gpsu_item.values[0])
                       if gpsu_item and gpsu_item.values else None)

            target = gps5 if gps5 is not None else gps9
            n = max(1, len(target.values))
            for i, sample in enumerate(target.values):
                vals = list(sample) if isinstance(sample, (list, tuple)) else [sample]
                sc = (scal + [1] * len(vals))[:len(vals)]
                scaled = [v / s if s else v for v, s in zip(vals, sc)]
                t = payload_time + i / n  # 1 ペイロード ≒ 1 秒として補間
                pt = GPSPoint(time=t, lat=scaled[0], lon=scaled[1],
                              ele=scaled[2],
                              speed2d=scaled[3] if len(scaled) > 3 else 0.0,
                              speed3d=scaled[4] if len(scaled) > 4 else 0.0)
                when = (base_dt + datetime.timedelta(seconds=i / n)
                        if base_dt else None)
                out.append((when, pt))
    return out


def _scal_values(item: Optional[GPMFItem]) -> List[float]:
    if item is None:
        return []
    out: List[float] = []
    for v in item.values:
        if isinstance(v, (list, tuple)):
            out.extend(v)
        else:
            out.append(v)
    return out


def write_gpx(path: str,
              points: List[Tuple[Optional[datetime.datetime], GPSPoint]],
              name: str = "GPMF extracted track") -> None:
    """GPS ポイント列を GPX 1.1 で書き出す。"""
    gpx = ET.Element("gpx", {
        "version": "1.1",
        "creator": "gpmf_tool",
        "xmlns": "http://www.topografix.com/GPX/1/1",
    })
    trk = ET.SubElement(gpx, "trk")
    ET.SubElement(trk, "name").text = name
    seg = ET.SubElement(trk, "trkseg")
    for when, p in points:
        pt = ET.SubElement(seg, "trkpt",
                           {"lat": f"{p.lat:.7f}", "lon": f"{p.lon:.7f}"})
        ET.SubElement(pt, "ele").text = f"{p.ele:.3f}"
        if when is not None:
            ET.SubElement(pt, "time").text = when.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
    tree = ET.ElementTree(gpx)
    ET.indent(tree)
    tree.write(path, encoding="utf-8", xml_declaration=True)
