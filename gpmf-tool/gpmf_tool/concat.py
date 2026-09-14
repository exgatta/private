"""分割された動画ファイルの結合 (再エンコードなし)。

DJI / Insta360 / GoPro などは、撮影中に自動でファイルを分割する
(FAT32 の 4GB 制限やカメラ側の仕様)。このモジュールはそれらを
**再エンコードせずに** 1 本へ結合する。映像・音声データは 1 バイトも
変更しないので画質は劣化せず、処理はディスクコピー並みに速い。

仕組み:
  各入力の mdat (実データ) をそのまま順に連結し、moov のサンプルテーブル
  (stts/stsz/stsc/stco/stss/ctts) を足し合わせて作り直す。チャンクオフセットは
  連結後の位置にずらす。

前提: 全ファイルが同じコーデック・解像度・トラック構成であること
(同じカメラの連続撮影なら自動的に満たされる)。
"""

from __future__ import annotations

import os
import struct
from typing import BinaryIO, List, Optional, Tuple

from . import mp4
from .mp4 import Box, MP4Error, _box, _full


# ---------------------------------------------------------------------------
# 1 ファイル分の情報
# ---------------------------------------------------------------------------

class _Source:
    """結合元 1 ファイルの解析結果。"""

    def __init__(self, path: str):
        self.path = path
        self.f: Optional[BinaryIO] = None
        with open(path, "rb") as f:
            self.tops = mp4.scan_top_level(f)
            moov_top = next(b for b in self.tops if b.type == b"moov")
            self.moov = mp4.parse_box_tree(mp4.read_box_bytes(f, moov_top),
                                           b"moov")
        self.mvhd = mp4.parse_mvhd(self.moov.find(b"mvhd").payload)
        self.traks = list(self.moov.find_all(b"trak"))
        self.mdats = [b for b in self.tops if b.type == b"mdat"]
        if not self.mdats:
            raise MP4Error(f"{os.path.basename(path)}: mdat がありません")

    # --- トラックの素性 ---
    def handler(self, trak: Box) -> bytes:
        h = trak.find(b"mdia", b"hdlr")
        return mp4.parse_hdlr(h.payload)["handler"] if h else b"????"

    def stbl(self, trak: Box) -> Box:
        s = trak.find(b"mdia", b"minf", b"stbl")
        if s is None:
            raise MP4Error(f"{os.path.basename(self.path)}: stbl がありません")
        return s

    def stsd_payload(self, trak: Box) -> bytes:
        s = self.stbl(trak).find(b"stsd")
        return s.payload if s else b""

    def timescale(self, trak: Box) -> int:
        return mp4.parse_mdhd(trak.find(b"mdia", b"mdhd").payload)["timescale"]

    def duration(self, trak: Box) -> int:
        return mp4.parse_mdhd(trak.find(b"mdia", b"mdhd").payload)["duration"]


# ---------------------------------------------------------------------------
# 互換性チェック
# ---------------------------------------------------------------------------

def check_compatible(sources: List[_Source]) -> List[str]:
    """結合できない理由を日本語で列挙する (空なら結合可能)。"""
    problems: List[str] = []
    first = sources[0]
    n = len(first.traks)
    for s in sources[1:]:
        name = os.path.basename(s.path)
        if len(s.traks) != n:
            problems.append(
                f"{name}: トラック数が違います "
                f"({len(s.traks)} 本 / 先頭は {n} 本)")
            continue
        for i, (a, b) in enumerate(zip(first.traks, s.traks), 1):
            if first.handler(a) != s.handler(b):
                problems.append(
                    f"{name}: トラック#{i} の種類が違います")
            elif first.stsd_payload(a) != s.stsd_payload(b):
                problems.append(
                    f"{name}: トラック#{i} のコーデック/解像度が違います"
                    "（同じ設定で撮影されたファイルのみ結合できます）")
            elif first.timescale(a) != s.timescale(b):
                problems.append(
                    f"{name}: トラック#{i} の時間単位が違います")
    return problems


# ---------------------------------------------------------------------------
# サンプルテーブルの構築
# ---------------------------------------------------------------------------

def _build_stts(runs: List[Tuple[int, int]]) -> bytes:
    merged: List[Tuple[int, int]] = []
    for count, delta in runs:
        if merged and merged[-1][1] == delta:
            merged[-1] = (merged[-1][0] + count, delta)
        else:
            merged.append((count, delta))
    return _full(b"stts", 0, 0,
                 struct.pack(">I", len(merged))
                 + b"".join(struct.pack(">II", c, d) for c, d in merged))


def _build_stsz(sizes: List[int]) -> bytes:
    return _full(b"stsz", 0, 0,
                 struct.pack(">II", 0, len(sizes))
                 + b"".join(struct.pack(">I", s) for s in sizes))


def expand_stsc(stsc: List[Tuple[int, int, int]], n_chunks: int,
                n_samples: int) -> List[Tuple[int, int]]:
    """stsc を「チャンクごとの (サンプル数, desc)」に展開する。

    最後のチャンクは samples_per_chunk より少ないことがあるため、
    総サンプル数で頭打ちにする。ここを省くと結合時に境界がずれる。
    """
    out: List[Tuple[int, int]] = []
    assigned = 0
    for i, (first_chunk, spc, desc) in enumerate(stsc):
        last = (stsc[i + 1][0] - 1) if i + 1 < len(stsc) else n_chunks
        for _ in range(first_chunk, last + 1):
            take = max(0, min(spc, n_samples - assigned))
            out.append((take, desc))
            assigned += take
    # stsc が足りない場合の保険
    while len(out) < n_chunks:
        take = max(0, min(1, n_samples - assigned))
        out.append((take, 1))
        assigned += take
    return out[:n_chunks]


def _build_stsc(per_chunk: List[Tuple[int, int]]) -> bytes:
    """チャンクごとの (サンプル数, desc) から stsc を作り直す。"""
    entries: List[Tuple[int, int, int]] = []
    for idx, (count, desc) in enumerate(per_chunk, start=1):
        if entries and entries[-1][1] == count and entries[-1][2] == desc:
            continue  # 直前と同じなら区間が続くので省略
        entries.append((idx, count, desc))
    return _full(b"stsc", 0, 0,
                 struct.pack(">I", len(entries))
                 + b"".join(struct.pack(">III", *e) for e in entries))


def _build_chunk_offsets(offsets: List[int]) -> bytes:
    if offsets and max(offsets) > 0xFFFFFFFF:
        return _full(b"co64", 0, 0,
                     struct.pack(">I", len(offsets))
                     + b"".join(struct.pack(">Q", o) for o in offsets))
    return _full(b"stco", 0, 0,
                 struct.pack(">I", len(offsets))
                 + b"".join(struct.pack(">I", o) for o in offsets))


def _build_stss(nums: List[int]) -> bytes:
    return _full(b"stss", 0, 0,
                 struct.pack(">I", len(nums))
                 + b"".join(struct.pack(">I", n) for n in nums))


def _build_ctts(runs: List[Tuple[int, int]]) -> bytes:
    # version 1 (符号付き) で出力しておけば負のオフセットも表現できる
    return _full(b"ctts", 1, 0,
                 struct.pack(">I", len(runs))
                 + b"".join(struct.pack(">Ii", c, o) for c, o in runs))


def _set_duration(box: Box, which: bytes, new_duration: int) -> None:
    """mdhd / tkhd の duration を書き換える (必要なら 64bit 化)。"""
    p = box.payload
    version = p[0]
    if which == b"mdhd":
        if version == 1:
            box.payload = p[:24] + struct.pack(">Q", new_duration) + p[32:]
        elif new_duration <= 0xFFFFFFFF:
            box.payload = p[:16] + struct.pack(">I", new_duration) + p[20:]
        else:  # 32bit に収まらない → version 1 へ作り直す
            ct, mt = struct.unpack(">II", p[4:12])
            ts = struct.unpack(">I", p[12:16])[0]
            box.payload = (b"\x01" + p[1:4]
                           + struct.pack(">QQIQ", ct, mt, ts, new_duration)
                           + p[20:])
    else:  # tkhd
        if version == 1:
            box.payload = p[:28] + struct.pack(">Q", new_duration) + p[36:]
        elif new_duration <= 0xFFFFFFFF:
            box.payload = p[:20] + struct.pack(">I", new_duration) + p[24:]
        else:
            ct, mt, tid, _res = struct.unpack(">IIII", p[4:20])
            box.payload = (b"\x01" + p[1:4]
                           + struct.pack(">QQIIQ", ct, mt, tid, 0, new_duration)
                           + p[24:])


# ---------------------------------------------------------------------------
# 結合本体
# ---------------------------------------------------------------------------

def concat_files(inputs: List[str], output: str,
                 log=lambda m: None) -> dict:
    """複数の MP4 を再エンコードせずに 1 本へ結合する。

    Returns: 統計情報 dict
    """
    if len(inputs) < 2:
        raise MP4Error("結合には 2 本以上の動画が必要です")

    sources = [_Source(p) for p in inputs]

    problems = check_compatible(sources)
    if problems:
        raise MP4Error("結合できません:\n  - " + "\n  - ".join(problems))

    first = sources[0]
    n_traks = len(first.traks)

    # --- 空き容量チェック ---
    total_in = sum(os.path.getsize(p) for p in inputs)
    out_dir = os.path.dirname(os.path.abspath(output)) or "."
    try:
        import shutil
        free = shutil.disk_usage(out_dir).free
        if free < total_in * 1.02:
            import errno
            raise OSError(
                errno.ENOSPC,
                f"保存先の空き容量が不足しています "
                f"(必要 約{total_in / 1024**3:.1f}GB / "
                f"空き {free / 1024**3:.1f}GB)", output)
    except OSError:
        raise
    except Exception:
        pass

    # --- 出力レイアウトを決める ---
    # [ftyp(先頭ファイルのもの)] [mdat(全入力の mdat を連結)] [moov]
    ftyp_top = next((b for b in first.tops if b.type == b"ftyp"), None)
    with open(first.path, "rb") as f:
        ftyp_bytes = mp4.read_box_bytes(f, ftyp_top) if ftyp_top else b""

    mdat_payload_total = sum(m.payload_size for s in sources for m in s.mdats)
    # mdat が 4GB を超えるなら 64bit largesize ヘッダを使う
    if mdat_payload_total + 8 > 0xFFFFFFFF:
        mdat_header = struct.pack(">I", 1) + b"mdat" + struct.pack(
            ">Q", mdat_payload_total + 16)
    else:
        mdat_header = struct.pack(">I", mdat_payload_total + 8) + b"mdat"

    mdat_data_start = len(ftyp_bytes) + len(mdat_header)

    # 各入力の各 mdat が新ファイルのどこに来るかを記録し、
    # チャンクオフセットの変換表 (delta) を作る
    remaps: List[List[Tuple[int, int, int]]] = []  # [src][ (lo, hi, delta) ]
    cursor = mdat_data_start
    for s in sources:
        ranges = []
        for m in s.mdats:
            lo = m.payload_offset
            hi = lo + m.payload_size
            ranges.append((lo, hi, cursor - lo))
            cursor += m.payload_size
        remaps.append(ranges)

    def remap(src_idx: int, offset: int) -> int:
        for lo, hi, delta in remaps[src_idx]:
            if lo <= offset < hi:
                return offset + delta
        raise MP4Error(
            f"{os.path.basename(sources[src_idx].path)}: "
            "mdat の外を指すデータがあり結合できません")

    # --- トラックごとにサンプルテーブルを合成 ---
    merged_traks: List[bytes] = []
    total_media_durations: List[int] = []

    for ti in range(n_traks):
        stts_runs: List[Tuple[int, int]] = []
        stsz_sizes: List[int] = []
        per_chunk: List[Tuple[int, int]] = []   # (チャンク内サンプル数, desc)
        chunk_offsets: List[int] = []
        stss_nums: List[int] = []
        ctts_runs: List[Tuple[int, int]] = []
        any_stss = False
        any_ctts = False
        acc_samples = 0
        acc_chunks = 0
        media_duration = 0

        for si, s in enumerate(sources):
            trak = s.traks[ti]
            stbl = s.stbl(trak)
            media_duration += s.duration(trak)

            sizes = mp4.parse_stsz(stbl.find(b"stsz").payload)
            stsz_sizes.extend(sizes)
            stts_runs.extend(mp4.parse_stts(stbl.find(b"stts").payload))

            stco_box = stbl.find(b"stco")
            if stco_box is not None:
                offs = mp4.parse_stco(stco_box.payload, is_co64=False)
            else:
                offs = mp4.parse_stco(stbl.find(b"co64").payload, is_co64=True)
            chunk_offsets.extend(remap(si, o) for o in offs)

            # チャンク単位に展開してから足す (末尾チャンクのサンプル数対策)
            per_chunk.extend(expand_stsc(
                mp4.parse_stsc(stbl.find(b"stsc").payload),
                n_chunks=len(offs), n_samples=len(sizes)))

            stss_box = stbl.find(b"stss")
            if stss_box is not None:
                any_stss = True
                stss_nums.extend(x + acc_samples
                                 for x in mp4.parse_stss(stss_box.payload))
            elif si == 0:
                # 先頭に stss が無い = 全サンプルがキーフレーム扱い
                pass

            ctts_box = stbl.find(b"ctts")
            if ctts_box is not None:
                any_ctts = True
                ctts_runs.extend(mp4.parse_ctts(ctts_box.payload))
            elif any_ctts:
                # 途中のファイルに ctts が無い → オフセット 0 で埋める
                ctts_runs.append((len(sizes), 0))

            acc_samples += len(sizes)
            acc_chunks += len(offs)

        total_media_durations.append(media_duration)

        # 先頭ファイルの trak を雛形にして stbl を差し替える
        template = first.traks[ti]
        new_trak = Box(type=b"trak", is_container=True,
                       children=list(template.children))

        # mdia を複製して差し替え
        mdia_t = template.find(b"mdia")
        new_mdia = Box(type=b"mdia", is_container=True,
                       children=list(mdia_t.children))
        minf_t = mdia_t.find(b"minf")
        new_minf = Box(type=b"minf", is_container=True,
                       children=list(minf_t.children))
        stbl_t = minf_t.find(b"stbl")

        new_stbl_children: List[Box] = []
        for c in stbl_t.children:
            if c.type == b"stts":
                new_stbl_children.append(
                    mp4.parse_box_tree(_build_stts(stts_runs), b"stts"))
            elif c.type == b"stsz":
                new_stbl_children.append(
                    mp4.parse_box_tree(_build_stsz(stsz_sizes), b"stsz"))
            elif c.type == b"stsc":
                new_stbl_children.append(
                    mp4.parse_box_tree(_build_stsc(per_chunk), b"stsc"))
            elif c.type in (b"stco", b"co64"):
                blob = _build_chunk_offsets(chunk_offsets)
                new_stbl_children.append(
                    mp4.parse_box_tree(blob, blob[4:8]))
            elif c.type == b"stss":
                new_stbl_children.append(
                    mp4.parse_box_tree(_build_stss(stss_nums), b"stss"))
            elif c.type == b"ctts":
                new_stbl_children.append(
                    mp4.parse_box_tree(_build_ctts(ctts_runs), b"ctts"))
            else:
                new_stbl_children.append(c)
        # 先頭に stss が無いのに後続にあった場合は足す
        if any_stss and not any(c.type == b"stss" for c in new_stbl_children):
            new_stbl_children.append(
                mp4.parse_box_tree(_build_stss(stss_nums), b"stss"))

        new_stbl = Box(type=b"stbl", is_container=True,
                       children=new_stbl_children)
        new_minf.children = [new_stbl if c.type == b"stbl" else c
                             for c in new_minf.children]
        # mdhd の duration を合計に
        new_mdia_children = []
        for c in new_mdia.children:
            if c.type == b"mdhd":
                nb = Box(type=b"mdhd", payload=c.payload)
                _set_duration(nb, b"mdhd", media_duration)
                new_mdia_children.append(nb)
            elif c.type == b"minf":
                new_mdia_children.append(new_minf)
            else:
                new_mdia_children.append(c)
        new_mdia.children = new_mdia_children

        # tkhd の duration をムービー時間軸に換算して更新
        ts = first.timescale(template) or 1
        movie_ts = first.mvhd["timescale"] or 1
        track_movie_dur = int(media_duration * movie_ts / ts)
        new_children = []
        for c in new_trak.children:
            if c.type == b"tkhd":
                nb = Box(type=b"tkhd", payload=c.payload)
                _set_duration(nb, b"tkhd", track_movie_dur)
                new_children.append(nb)
            elif c.type == b"mdia":
                new_children.append(new_mdia)
            elif c.type == b"edts":
                continue  # 編集リストは破棄 (結合後は意味が変わるため)
            else:
                new_children.append(c)
        new_trak.children = new_children
        merged_traks.append(new_trak.serialize())

    # --- moov を組み立て ---
    movie_ts = first.mvhd["timescale"] or 1
    movie_duration = 0
    for ti in range(n_traks):
        ts = first.timescale(first.traks[ti]) or 1
        movie_duration = max(movie_duration,
                             int(total_media_durations[ti] * movie_ts / ts))

    new_moov_children: List[Box] = []
    for c in first.moov.children:
        if c.type == b"mvhd":
            nb = Box(type=b"mvhd", payload=c.payload)
            p = nb.payload
            if p[0] == 1:
                nb.payload = p[:24] + struct.pack(">Q", movie_duration) + p[32:]
            elif movie_duration <= 0xFFFFFFFF:
                nb.payload = p[:16] + struct.pack(">I", movie_duration) + p[20:]
            else:
                ct, mt = struct.unpack(">II", p[4:12])
                ts0 = struct.unpack(">I", p[12:16])[0]
                nb.payload = (b"\x01" + p[1:4]
                              + struct.pack(">QQIQ", ct, mt, ts0, movie_duration)
                              + p[20:])
            new_moov_children.append(nb)
        elif c.type == b"trak":
            continue  # 後でまとめて足す
        else:
            new_moov_children.append(c)

    moov_body = b"".join(
        c.serialize() for c in new_moov_children
        if c.type == b"mvhd") + b"".join(merged_traks) + b"".join(
        c.serialize() for c in new_moov_children if c.type != b"mvhd")
    moov_bytes = _box(b"moov", moov_body)

    # --- 書き出し ---
    log(f"結合: {len(inputs)} 本 → {os.path.basename(output)}")
    with open(output, "wb") as out:
        out.write(ftyp_bytes)
        out.write(mdat_header)
        for si, s in enumerate(sources):
            with open(s.path, "rb") as fin:
                for m in s.mdats:
                    _copy(fin, out, m.payload_offset, m.payload_size)
            log(f"  [{si + 1}/{len(sources)}] "
                f"{os.path.basename(s.path)} を追加")
        out.write(moov_bytes)

    return {
        "inputs": len(inputs),
        "output": output,
        "duration_sec": movie_duration / movie_ts if movie_ts else 0,
        "tracks": n_traks,
        "bytes": os.path.getsize(output),
    }


def _copy(src: BinaryIO, dst: BinaryIO, offset: int, size: int,
          chunk: int = 8 * 1024 * 1024) -> None:
    src.seek(offset)
    remaining = size
    while remaining > 0:
        data = src.read(min(chunk, remaining))
        if not data:
            raise MP4Error("コピー中に EOF")
        dst.write(data)
        remaining -= len(data)


# ---------------------------------------------------------------------------
# 分割ファイルの自動グループ化
# ---------------------------------------------------------------------------

def group_split_files(paths: List[str]) -> List[List[str]]:
    """分割された連番ファイルを、結合すべきグループにまとめる。

    ファイル名が似ていて連続するものを 1 グループとみなす。
    判定できないものは 1 本ずつ単独グループになる。
    """
    import re
    groups: dict = {}
    order: List[str] = []
    for p in sorted(paths):
        base = os.path.basename(p)
        stem, _ = os.path.splitext(base)
        # 末尾の連番らしき数字を取り除いた部分をキーにする
        key = re.sub(r"[_-]?\d+$", "", stem)
        key = re.sub(r"\d+", "#", key)
        if key not in groups:
            groups[key] = []
            order.append(key)
        groups[key].append(p)
    return [groups[k] for k in order]
