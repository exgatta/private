"""動画の内部メタデータを、人が読める (そして貼り付けられる) テキストにする。

「ファイル名と時刻以外で 1 本の撮影かどうかを判定する材料が動画の中に
無いか」を調べるための機能。映像・音声のデータは **一切出さない**。
出すのは次のものだけ:

- トップレベルの箱の並びと大きさ (ftyp / mdat / moov / …)
- ftyp のブランド
- mvhd の作成時刻・タイムスケール・長さ
- udta (メーカー独自の情報が入る所) の各箱の中身 (先頭 256 バイトの hex)
- トラックごとに: 種類・ハンドラ名・タイムスケール・長さ・作成時刻・
  編集リスト (elst)・サンプル記述 (stsd) の hex・サンプル数
- 映像/音声以外のトラック (DJI の djmd/dbgi、タイムコード tmcd、字幕
  など) は先頭と末尾の数サンプルの中身を hex + ASCII で出す。
  2 つのファイルの「末尾」と「先頭」を見比べれば、撮影を通して
  連続する番号や記録 ID があるかどうか分かる

出力は 1 ファイルあたり数 KB〜数十 KB に収まるよう上限を設けている。
"""

from __future__ import annotations

import datetime
import os
import struct
from typing import BinaryIO, List, Optional

from . import mp4

MEDIA_HANDLERS = {b"vide", b"soun"}


def hexdump(data: bytes, max_bytes: int = 256, width: int = 16,
            indent: str = "      ") -> List[str]:
    """hex + ASCII の行を作る (max_bytes で打ち切り)。"""
    lines = []
    shown = data[:max_bytes]
    for off in range(0, len(shown), width):
        chunk = shown[off:off + width]
        hx = " ".join(f"{b:02x}" for b in chunk)
        asc = "".join(chr(b) if 32 <= b < 127 else "." for b in chunk)
        lines.append(f"{indent}{off:06x}  {hx:<{width * 3}} {asc}")
    if len(data) > max_bytes:
        lines.append(f"{indent}... (全 {len(data)} バイト、先頭 {max_bytes} バイトのみ)")
    return lines


def _fmt_time(seconds_since_1904: int) -> str:
    d = mp4.mp4_time_to_datetime(seconds_since_1904)
    if d is None:
        return "なし (0)"
    return f"{mp4.camera_wall_time(d):%Y/%m/%d %H:%M:%S}"


def _parse_elst(payload: bytes) -> List[tuple]:
    version = payload[0]
    count = struct.unpack(">I", payload[4:8])[0]
    out = []
    pos = 8
    for _ in range(count):
        if version == 1:
            seg, media = struct.unpack(">Qq", payload[pos:pos + 16])
            pos += 16
        else:
            seg, media = struct.unpack(">Ii", payload[pos:pos + 8])
            pos += 8
        rate = struct.unpack(">i", payload[pos:pos + 4])[0] / 65536.0
        pos += 4
        out.append((seg, media, rate))
    return out


def _sample_list(stbl: mp4.Box) -> List[tuple]:
    """(オフセット, サイズ) の列。テーブルが欠けていれば空。"""
    stsz = stbl.find(b"stsz")
    stsc = stbl.find(b"stsc")
    stco = stbl.find(b"stco")
    co64 = stbl.find(b"co64")
    if stsz is None or stsc is None or (stco is None and co64 is None):
        return []
    sizes = mp4.parse_stsz(stsz.payload)
    chunks = mp4.parse_stsc(stsc.payload)
    offs = (mp4.parse_stco(stco.payload, False) if stco is not None
            else mp4.parse_stco(co64.payload, True))
    return mp4.sample_offsets(sizes, chunks, offs)


def _sample_times(stbl: mp4.Box, n: int) -> List[int]:
    """先頭 n サンプルの開始時刻 (トラック時間単位)。"""
    stts = stbl.find(b"stts")
    if stts is None:
        return []
    out, t = [], 0
    for count, delta in mp4.parse_stts(stts.payload):
        for _ in range(count):
            out.append(t)
            t += delta
            if len(out) >= n:
                return out
    return out


def dump_file(path: str, n_samples: int = 3, sample_bytes: int = 512,
              udta_bytes: int = 256) -> str:
    """1 ファイルの内部メタデータをテキストにする。"""
    lines: List[str] = [f"##### {os.path.basename(path)}"]
    try:
        size = os.path.getsize(path)
    except OSError as e:
        return "\n".join(lines + [f"開けません: {e}"])
    lines.append(f"サイズ: {size} バイト ({size / 1024 ** 3:.3f} GB)")
    with open(path, "rb") as f:
        try:
            tops = mp4.scan_top_level(f)
        except Exception as e:  # noqa: BLE001
            return "\n".join(lines + [f"MP4 として読めません: {e}"])
        lines.append("トップレベル: " + ", ".join(
            f"{b.type.decode('latin-1', 'replace')}@{b.offset}({b.size})"
            for b in tops))
        for b in tops:
            if b.type == b"ftyp":
                p = mp4.read_box_bytes(f, b)[b.header_size:]
                brands = [p[i:i + 4].decode("latin-1", "replace")
                          for i in range(8, len(p), 4)]
                lines.append(f"ftyp: major={p[:4].decode('latin-1', 'replace')} "
                             f"compatible={' '.join(brands)}")
        moov_top = next(b for b in tops if b.type == b"moov")
        moov = mp4.parse_box_tree(mp4.read_box_bytes(f, moov_top), b"moov")
        lines.append("moov 直下: " + ", ".join(
            c.type.decode("latin-1", "replace") for c in moov.children))

        mvhd_box = moov.find(b"mvhd")
        if mvhd_box is not None:
            mv = mp4.parse_mvhd(mvhd_box.payload)
            ts = mv["timescale"] or 1
            lines.append(f"mvhd: 作成 {_fmt_time(mv.get('creation_time', 0))} / "
                         f"timescale {mv['timescale']} / "
                         f"長さ {mv['duration']} ({mv['duration'] / ts:.3f} 秒)")

        udta = moov.find(b"udta")
        if udta is not None:
            lines.append("udta:")
            _dump_udta(udta, lines, udta_bytes, depth=1)
        else:
            lines.append("udta: なし")

        for ti, trak in enumerate(moov.find_all(b"trak"), 1):
            _dump_trak(f, trak, ti, lines, n_samples, sample_bytes)
    return "\n".join(lines)


def _dump_udta(box: mp4.Box, lines: List[str], max_bytes: int, depth: int) -> None:
    ind = "  " * depth
    for c in box.children:
        name = c.type.decode("latin-1", "replace")
        if c.is_container:
            lines.append(f"{ind}{name}/")
            _dump_udta(c, lines, max_bytes, depth + 1)
            continue
        lines.append(f"{ind}{name} ({len(c.payload)} バイト)")
        lines.extend(hexdump(c.payload, max_bytes, indent=ind + "    "))


def _dump_trak(f: BinaryIO, trak: mp4.Box, index: int, lines: List[str],
               n_samples: int, sample_bytes: int) -> None:
    hdlr = trak.find(b"mdia", b"hdlr")
    handler = mp4.parse_hdlr(hdlr.payload)["handler"] if hdlr else b"????"
    hname = ""
    if hdlr is not None and len(hdlr.payload) > 24:
        hname = hdlr.payload[24:].split(b"\x00", 1)[0].decode("utf-8", "replace")
    tkhd = trak.find(b"tkhd")
    track_id = "?"
    tk_created = ""
    if tkhd is not None:
        v = tkhd.payload[0]
        if v == 1:
            ct, _, tid = struct.unpack(">QQI", tkhd.payload[4:24])
        else:
            ct, _, tid = struct.unpack(">III", tkhd.payload[4:16])
        track_id = str(tid)
        tk_created = _fmt_time(ct)
    mdhd_box = trak.find(b"mdia", b"mdhd")
    md = mp4.parse_mdhd(mdhd_box.payload) if mdhd_box else {"timescale": 0, "duration": 0}
    ts = md["timescale"] or 1
    lines.append(
        f"--- トラック#{index} id={track_id} 種類={handler.decode('latin-1', 'replace')} "
        f"名前=\"{hname}\" timescale={md['timescale']} 長さ={md['duration']} "
        f"({md['duration'] / ts:.3f} 秒) 作成 {tk_created}")

    elst = trak.find(b"edts", b"elst")
    if elst is not None:
        try:
            lines.append("    elst: " + ", ".join(
                f"(seg={s} media={m} rate={r})" for s, m, r in _parse_elst(elst.payload)))
        except (struct.error, IndexError):
            lines.append("    elst: 解析不能")
    else:
        lines.append("    elst: なし")

    stbl = trak.find(b"mdia", b"minf", b"stbl")
    if stbl is None:
        lines.append("    stbl: なし")
        return
    stsd = stbl.find(b"stsd")
    if stsd is not None:
        entry = stsd.payload[12:16].decode("latin-1", "replace") if len(stsd.payload) >= 16 else "?"
        lines.append(f"    stsd: エントリ {entry} ({len(stsd.payload)} バイト)")
        lines.extend(hexdump(stsd.payload, 160, indent="        "))
    # 子ボックスの一覧 (どんなテーブルを持っているか)
    lines.append("    stbl 内: " + ", ".join(
        c.type.decode("latin-1", "replace") for c in stbl.children))

    samples = _sample_list(stbl)
    lines.append(f"    サンプル数: {len(samples)}")
    if not samples:
        return
    if handler in MEDIA_HANDLERS:
        # 映像・音声の中身は出さない。大きさの傾向だけ
        first = samples[0][1]
        lines.append(f"    (映像/音声のためデータは出力しない) 先頭サンプル {first} バイト、"
                     f"最終サンプル {samples[-1][1]} バイト")
        return
    times = _sample_times(stbl, len(samples))
    picks = list(range(min(n_samples, len(samples))))
    tail = list(range(max(len(samples) - n_samples, n_samples), len(samples)))
    for label, idxs in (("先頭", picks), ("末尾", tail)):
        for i in idxs:
            off, sz = samples[i]
            t = times[i] / ts if i < len(times) else 0.0
            f.seek(off)
            data = f.read(min(sz, sample_bytes))
            lines.append(f"    [{label}] サンプル#{i + 1} @{off} {sz} バイト t={t:.3f}s")
            lines.extend(hexdump(data, sample_bytes, indent="        "))


def dump_files(paths: List[str], **kw) -> str:
    parts = [f"== 内部メタデータ ({len(paths)} ファイル) =="]
    for p in paths:
        try:
            parts.append(dump_file(p, **kw))
        except Exception as e:  # noqa: BLE001
            parts.append(f"##### {os.path.basename(p)}\n書き出しに失敗: {e}")
        parts.append("")
    return "\n".join(parts)
