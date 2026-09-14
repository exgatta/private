"""「1 本の撮影が強制分割されたもの」をカメラごとの命名規則で高精度に判定する。

DJI / GoPro などは分割した全セグメントに **同じ撮影時刻** (あるいは 0) を
書くことが多く、撮影時刻の連続性だけでは判定できない。逆に、ファイル名の
数字を全部伏せる粗い比較では、別の撮影まで 1 つにまとめてしまう。

そこでこのモジュールは次の順で判定する (上ほど強い):

  1. **絶対条件** — コーデック・解像度・トラック構成・時間単位が一致しない
     ものは決して結合しない。読めないファイル、macOS の "._" 付随ファイル、
     Insta360 の低解像度プロキシ (LRV_) はそれぞれ単独扱い。
  2. **メーカー固有の命名規則** (決定的)
       GoPro    GH010001.MP4 … 同一ファイル番号 + 連続チャプター
       DJI 新   DJI_20260914145635_0011_D.MP4 … 連番が連続 + ファイル名の
                日時が「前の開始 + 前の長さ」に一致 (Osmo Pocket/Action は
                セグメントごとに開始時刻を書く。全部同じ時刻を書く機種も可)
       Insta360 VID_20250915_125402_00_062.mp4 … 同一日時キー
     これらは名前だけで「同じ撮影」と言い切れるので confidence = "high"。
  3. **状況証拠が要るもの** — DJI 旧 (DJI_0001)、Sony (C0001)、一般的な
     連番 (xxx_001) は「新しい撮影でも番号が進む」ため、撮影時刻の連続性
     または分割サイズの揃い方 (4GB 等の上限で切られた痕跡) を要求する。
  4. 命名規則が不明でも撮影時刻が連続していれば結合候補にするが、
     confidence = "low" として UI で「要確認」にできるようにする。

矛盾 (時刻が明らかに離れている、命名規則が別の撮影を示す) があれば
決して結合しない。
"""

from __future__ import annotations

import datetime
import os
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from . import mp4

# 撮影時刻の連続とみなす許容差 (秒)。カメラの時計の丸めや、分割時の
# 数秒のオーバーラップ/ギャップを吸収する。
DEFAULT_TOLERANCE_SEC = 120.0

# 分割サイズの証拠: 末尾以外のファイルが全て 1GiB 以上で、互いに 5% 以内
SIZE_EVIDENCE_MIN_BYTES = 1 << 30
SIZE_EVIDENCE_RATIO = 0.05


@dataclass
class DetectedGroup:
    """判定結果の 1 グループ (単独の動画も 1 件のグループ)。"""
    files: List[str]            # 再生順 = 結合順
    vendor: str                 # "gopro" | "dji" | "insta360" | "sony" | "generic"
    confidence: str             # "high" | "medium" | "low"
    reason: str                 # 判定理由 (日本語)


# ---------------------------------------------------------------------------
# ファイル名の解釈
# ---------------------------------------------------------------------------

@dataclass
class _Name:
    """ファイル名から読み取った「どの撮影の何番目か」。

    key   … 同じ撮影なら一致する識別子 (メーカー + 撮影ID など)
    order … 撮影内での並び順 (チャプター / 連番)。連続していれば同じ撮影
    deterministic … key と order が一致・連続なら名前だけで同じ撮影と断定できる
    """
    vendor: str
    key: Tuple
    order: Tuple[int, ...]
    deterministic: bool
    label: str = ""             # 理由文に使う表示用 (例: "01", "0011", "C0001")
    extra: Dict[str, str] = field(default_factory=dict)


_RE_GOPRO = re.compile(r"^(G[HXPS])(\d{2})(\d{4})\.(MP4|mp4|360)$")
_RE_GOPRO_LEGACY = re.compile(r"^GOPR(\d{4})\.(MP4|mp4)$")
_RE_DJI_NEW = re.compile(r"^DJI_(\d{14})_(\d{4})_([DSWT])\.(MP4|mp4)$")
_RE_DJI_OLD = re.compile(r"^DJI_(\d{4})\.(MP4|mp4)$")
_RE_INSTA360 = re.compile(
    r"^(VID|LRV)_(\d{8})_(\d{6})_(\d{2})_(\d{3})((?:_\d{3})*)(?:_\d+)?"
    r"\.(mp4|MP4|insv)$")
_RE_SONY = re.compile(r"^([CM])(\d{4})\.(MP4|mp4)$")
_RE_GENERIC = re.compile(
    r"^(?P<stem>.+?)(?:[ _\-]?\((?P<paren>\d+)\)|[ _\-]?(?P<num>\d+))$")


def _parse_name(path: str) -> Optional[_Name]:
    """ファイル名を命名規則に照らす。どれにも当たらなければ None。"""
    name = os.path.basename(path)

    m = _RE_GOPRO.match(name)
    if m:
        prefix, chapter, num = m.group(1), int(m.group(2)), m.group(3)
        # GP01nnnn は HERO4/5 世代の 2 チャプター目以降 (GOPRnnnn の続き)
        return _Name("gopro", ("gopro", prefix[1], num), (chapter,), True,
                     label=f"{chapter:02d}", extra={"num": num})
    m = _RE_GOPRO_LEGACY.match(name)
    if m:
        return _Name("gopro", ("gopro", "P", m.group(1)), (0,), True,
                     label="GOPR", extra={"num": m.group(1)})

    m = _RE_DJI_NEW.match(name)
    if m:
        stamp, counter, suffix = m.group(1), int(m.group(2)), m.group(3)
        # 14 桁はそのファイルの開始時刻。分割の続きかどうかは連番の連続と
        # 時刻の連続 (_dji_time_relation) で判定するので key には含めない
        return _Name("dji", ("dji", suffix), (counter,), True,
                     label=f"{counter:04d}", extra={"stamp": stamp})
    m = _RE_DJI_OLD.match(name)
    if m:
        return _Name("dji", ("dji_old",), (int(m.group(1)),), False,
                     label=m.group(1))

    m = _RE_INSTA360.match(name)
    if m:
        kind, date, time_, lens, clip, segs = m.groups()[:6]
        seg_list = [int(s) for s in segs.split("_") if s]
        seg = seg_list[-1] if seg_list else 0
        return _Name("insta360", ("insta360", kind, date, time_, lens),
                     (int(clip), seg), True,
                     label=clip, extra={"shot": f"{date}_{time_}",
                                        "is_lrv": "1" if kind == "LRV" else ""})

    m = _RE_SONY.match(name)
    if m:
        return _Name("sony", ("sony", m.group(1)), (int(m.group(2)),), False,
                     label=m.group(1) + m.group(2))

    stem, _ = os.path.splitext(name)
    m = _RE_GENERIC.match(stem)
    if m:
        num = m.group("paren") or m.group("num")
        return _Name("generic", ("generic", m.group("stem").lower()),
                     (int(num),), False, label=stem)
    return None


def _consecutive(prev: _Name, cur: _Name) -> bool:
    """cur が prev の「次のセグメント」の番号か。"""
    if prev.vendor == "insta360":
        pc, ps = prev.order
        cc, cs = cur.order
        return (cc == pc and cs == ps + 1) or (cc == pc + 1)
    return cur.order[0] == prev.order[0] + 1


# ---------------------------------------------------------------------------
# 1 ファイルの解析結果
# ---------------------------------------------------------------------------

def _file_size(path: str) -> int:
    """テストで差し替えられるように関数にしておく。"""
    try:
        return os.path.getsize(path)
    except OSError:
        return 0


class _Info:
    """判定に必要な材料をまとめた 1 ファイル分の情報。"""

    def __init__(self, path: str):
        self.path = path
        self.basename = os.path.basename(path)
        self.size = _file_size(path)
        self.error: Optional[str] = None
        self.creation: Optional[datetime.datetime] = None
        self.duration = 0.0
        self.signature: Optional[Tuple] = None
        self.name: Optional[_Name] = None
        self.junk = self.basename.startswith(".")
        if self.junk:
            return
        self.name = _parse_name(path)
        try:
            self._probe()
        except Exception as e:  # 壊れている / MP4 でない / 開けない
            self.error = _explain(e)

    def _probe(self) -> None:
        from .concat import _Source  # 循環 import 回避のためここで
        src = _Source(self.path)
        self.creation = mp4.mp4_time_to_datetime(
            src.mvhd.get("creation_time", 0))
        ts = src.mvhd["timescale"] or 1
        self.duration = src.mvhd["duration"] / ts
        # 絶対条件: 種類・コーデック/解像度・時間単位が全トラックで一致
        self.signature = tuple(
            (src.handler(t), src.stsd_payload(t), src.timescale(t))
            for t in src.traks)

    @property
    def is_lrv(self) -> bool:
        return bool(self.name and self.name.extra.get("is_lrv"))


def _explain(e: Exception) -> str:
    try:
        from .__main__ import humanize_error
        return humanize_error(e)
    except Exception:
        return str(e) or e.__class__.__name__


# ---------------------------------------------------------------------------
# 時刻・サイズの証拠
# ---------------------------------------------------------------------------

def _time_relation(prev: _Info, cur: _Info, tol: float) -> str:
    """撮影時刻から見た 2 ファイルの関係。

    "continuous" … cur の開始 ≈ prev の開始 + prev の長さ (強制分割の続き)
                   (終了時刻を書くカメラのため cur の長さでも照合する)
    "identical"  … 同じ時刻 (全セグメントに同じ時刻を書くカメラ) → 中立
    "gap"        … 明らかに離れている → 別撮影の証拠
    "unknown"    … どちらかに時刻が無い → 証拠なし
    """
    if prev.creation is None or cur.creation is None:
        return "unknown"
    gap = (cur.creation - prev.creation).total_seconds()
    if gap == 0:
        return "identical"
    if (abs(gap - prev.duration) <= tol
            or abs(gap - cur.duration) <= tol):
        return "continuous"
    return "gap"


def _dji_stamp(info: _Info) -> Optional[datetime.datetime]:
    """DJI ファイル名の 14 桁 (YYYYMMDDHHMMSS) を datetime に。"""
    if not info.name or info.name.vendor != "dji":
        return None
    stamp = info.name.extra.get("stamp")
    if not stamp:
        return None
    try:
        return datetime.datetime.strptime(stamp, "%Y%m%d%H%M%S")
    except ValueError:
        return None


def _dji_time_relation(prev: _Info, cur: _Info, tol: float) -> str:
    """DJI ファイル名の時刻から見た 2 ファイルの関係 (_time_relation と同じ語彙)。

    Osmo Pocket / Osmo Action / 近年のドローンは分割セグメントごとに
    そのファイルの開始時刻を名前に書くので、cur の時刻 ≈ prev の時刻 +
    prev の長さ なら「強制分割の続き」。全セグメントに同じ時刻を書く
    機種もあるので gap == 0 は中立。長いセグメントほど丸め誤差が
    積もるので、許容差は tol と長さの 5% の大きい方。
    """
    a, b = _dji_stamp(prev), _dji_stamp(cur)
    if a is None or b is None:
        return "unknown"
    gap = (b - a).total_seconds()
    if gap == 0:
        return "identical"
    allow = max(tol, prev.duration * 0.05)
    if abs(gap - prev.duration) <= allow:
        return "continuous"
    return "gap"


def _fmt_stamp(info: _Info) -> str:
    d = _dji_stamp(info)
    return f"{d:%H:%M:%S}" if d else "--:--:--"


def _size_evidence(run: List[_Info]) -> bool:
    """run (末尾を除く全ファイル) が分割上限で切られた大きさに揃っているか。"""
    sizes = [i.size for i in run]
    if not sizes or min(sizes) < SIZE_EVIDENCE_MIN_BYTES:
        return False
    return (max(sizes) - min(sizes)) <= max(sizes) * SIZE_EVIDENCE_RATIO


def _fmt_time(info: _Info) -> str:
    if info.creation is None:
        return "--:--:--"
    # カメラの時計の値をそのまま (TZ 変換しない)
    return f"{mp4.camera_wall_time(info.creation):%H:%M:%S}"


def _fmt_size(n: int) -> str:
    return f"{n / 1024 ** 3:.2f} GB"


# ---------------------------------------------------------------------------
# 検出本体
# ---------------------------------------------------------------------------

def detect_groups(paths: List[str],
                  tolerance_sec: float = DEFAULT_TOLERANCE_SEC
                  ) -> List[DetectedGroup]:
    """入力ファイルを「同じ撮影の分割」ごとにまとめる。

    入力の各パスは必ずどれか 1 つのグループに含まれる。単独の動画は
    要素 1 個のグループ。グループ内は再生順、グループ同士は先頭ファイルの
    撮影時刻 (無ければ名前) 順。
    """
    infos = [_Info(p) for p in _dedupe(paths)]
    groups: List[DetectedGroup] = []
    usable: List[_Info] = []
    for info in infos:
        single = _single_if_unusable(info)
        if single:
            groups.append(single)
        else:
            usable.append(info)

    deterministic = [i for i in usable if i.name and i.name.deterministic]
    others = [i for i in usable if not (i.name and i.name.deterministic)]

    groups.extend(_group_by_vendor_key(deterministic, tolerance_sec))
    groups.extend(_group_by_evidence(others, tolerance_sec))

    by_path = {i.path: i for i in infos}
    groups.sort(key=lambda g: _group_sort_key(by_path[g.files[0]]))
    return groups


def _dedupe(paths: List[str]) -> List[str]:
    seen, out = set(), []
    for p in paths:
        if p not in seen:
            seen.add(p)
            out.append(p)
    return out


def _group_sort_key(first: _Info):
    return (first.creation is None,
            first.creation or datetime.datetime.min.replace(
                tzinfo=datetime.timezone.utc),
            first.basename)


def _single_if_unusable(info: _Info) -> Optional[DetectedGroup]:
    """結合の候補にできないファイルを単独グループにする。"""
    if info.junk:
        what = ("macOS の付随ファイル (._)" if info.basename.startswith("._")
                else "隠しファイル")
        return DetectedGroup([info.path], "generic", "low",
                             f"{what} のため結合対象外")
    if info.error:
        return DetectedGroup([info.path], "generic", "low",
                             f"読み取りに失敗したため結合対象外: {info.error}")
    if info.is_lrv:
        return DetectedGroup([info.path], "insta360", "low",
                             "Insta360 の低解像度プロキシ (LRV) のため結合対象外")
    return None


# --- 2) メーカー固有の決定的な命名規則 ----------------------------------

def _group_by_vendor_key(infos: List[_Info], tol: float
                         ) -> List[DetectedGroup]:
    """同じ撮影IDのファイルを集め、番号が連続する区間ごとにまとめる。"""
    buckets: Dict[Tuple, List[_Info]] = {}
    for info in infos:
        buckets.setdefault(info.name.key, []).append(info)

    out: List[DetectedGroup] = []
    for members in buckets.values():
        members.sort(key=lambda i: (i.name.order, i.basename))
        run: List[_Info] = []
        for info in members:
            if run and not _vendor_continues(run[-1], info, tol):
                out.append(_vendor_group(run))
                run = []
            run.append(info)
        if run:
            out.append(_vendor_group(run))
    return out


def _vendor_continues(prev: _Info, cur: _Info, tol: float) -> bool:
    """同じ命名系列でも、構成違い・番号飛び・時刻の矛盾があれば切る。"""
    if cur.signature != prev.signature:
        return False
    if not _consecutive(prev.name, cur.name):
        return False
    if prev.name.vendor == "dji":
        # DJI はファイル名の時刻が一次証拠。連番が続いていても時刻が
        # 「前の開始 + 前の長さ」から外れていれば別の撮影
        if _dji_time_relation(prev, cur, tol) == "gap":
            return False
    return _time_relation(prev, cur, tol) != "gap"


def _vendor_group(run: List[_Info]) -> DetectedGroup:
    first, last = run[0], run[-1]
    vendor = first.name.vendor
    paths = [i.path for i in run]
    if len(run) == 1:
        return DetectedGroup(paths, vendor, "high",
                             f"単独の動画 ({_vendor_single_label(first)})")

    confidence = "high"
    if vendor == "gopro":
        num = first.name.extra["num"]
        reason = (f"GoPro チャプター {first.name.label}→{last.name.label} "
                  f"(同一ファイル番号 {num})")
        if first.name.order[0] > (0 if first.name.key[1] == "P" else 1):
            reason += " ※先頭チャプターが見つかりません"
            confidence = "medium"
    elif vendor == "dji":
        reason = f"DJI 連番 {first.name.label}→{last.name.label}"
        rels = {_dji_time_relation(a, b, DEFAULT_TOLERANCE_SEC)
                for a, b in zip(run, run[1:])}
        if rels == {"identical"}:
            reason += f" / 全ファイル同一時刻 ({first.name.extra['stamp']})"
        elif "continuous" in rels:
            reason += (f" / ファイル名の時刻が連続 "
                       f"({_fmt_stamp(first)} → {_fmt_stamp(last)})")
    else:  # insta360
        reason = (f"Insta360 同一撮影 {first.name.extra['shot']} / "
                  f"クリップ {first.name.label}→{last.name.label}")
    return DetectedGroup(paths, vendor, confidence, reason)


def _vendor_single_label(info: _Info) -> str:
    n = info.name
    if n.vendor == "gopro":
        return f"GoPro ファイル番号 {n.extra['num']} チャプター {n.label}"
    if n.vendor == "dji":
        d = _dji_stamp(info)
        when = f" {d:%Y/%m/%d %H:%M:%S}" if d else ""
        return f"DJI 連番 {n.label}{when}"
    return f"Insta360 撮影 {n.extra['shot']}"


# --- 3)/4) 状況証拠 (時刻・サイズ) が要るもの ----------------------------

def _group_by_evidence(infos: List[_Info], tol: float) -> List[DetectedGroup]:
    """撮影時刻順に並べ、隣同士の証拠を見ながら区間を伸ばしていく。"""
    infos = sorted(infos, key=_evidence_sort_key)
    out: List[DetectedGroup] = []
    run: List[_Info] = []
    reasons: List[str] = []
    for info in infos:
        verdict = _evidence_verdict(run, info, tol) if run else None
        if verdict is None:
            if run:
                out.append(_evidence_group(run, reasons))
            run, reasons = [info], []
        else:
            run.append(info)
            reasons.append(verdict)
    if run:
        out.append(_evidence_group(run, reasons))
    return out


def _evidence_sort_key(info: _Info):
    order = info.name.order if info.name else ()
    return (info.creation is None,
            info.creation or datetime.datetime.min.replace(
                tzinfo=datetime.timezone.utc),
            order, info.basename)


def _evidence_verdict(run: List[_Info], cur: _Info, tol: float
                      ) -> Optional[str]:
    """cur を run に足せるなら、その根拠 ("high"/"medium"/"low") を返す。"""
    prev = run[-1]
    if cur.signature != prev.signature:
        return None
    time_rel = _time_relation(prev, cur, tol)
    if time_rel == "gap":
        return None                          # 明らかに別撮影

    name_ok, contradict = _name_support(prev.name, cur.name)
    if contradict:
        return None
    size_ok = _size_evidence(run)

    if name_ok and time_rel == "continuous":
        return "high" if prev.name.vendor != "generic" else "medium"
    if name_ok and size_ok:
        return "medium"
    if time_rel == "continuous":
        return "low"                         # 名前の規則なし、時刻だけ
    return None


def _name_support(prev: Optional[_Name], cur: Optional[_Name]
                  ) -> Tuple[bool, bool]:
    """(名前が同じ撮影を支持するか, 名前が別の撮影だと矛盾を示すか)。"""
    if prev is None or cur is None:
        return False, False
    if prev.vendor != cur.vendor:
        return False, prev.vendor != "generic" and cur.vendor != "generic"
    if prev.key != cur.key:
        # メーカー規則同士で別の種類 (C/M, D/S 等) → 別撮影
        return False, prev.vendor != "generic"
    if _consecutive(prev, cur):
        return True, False
    # 番号が飛んでいる: メーカー規則なら別撮影、一般連番なら証拠なし扱い
    return False, prev.vendor != "generic"


def _evidence_group(run: List[_Info], verdicts: List[str]) -> DetectedGroup:
    first, last = run[0], run[-1]
    vendor = first.name.vendor if first.name else "generic"
    paths = [i.path for i in run]
    if len(run) == 1:
        return DetectedGroup(paths, vendor, "high", "単独の動画")

    # 区間全体の確度は最も弱い根拠に合わせる
    rank = {"high": 0, "medium": 1, "low": 2}
    confidence = max(verdicts, key=lambda v: rank[v])

    parts: List[str] = []
    if all(v != "low" for v in verdicts):
        parts.append(_counter_text(first, last))
    times = [_time_relation(a, b, DEFAULT_TOLERANCE_SEC)
             for a, b in zip(run, run[1:])]
    if all(t == "continuous" for t in times):
        parts.append(f"撮影時刻が連続 ({_fmt_time(first)} → {_fmt_time(last)})")
    elif _size_evidence(run[:-1]):
        parts.append(f"分割サイズが揃っている ({_fmt_size(run[0].size)})")
    if confidence == "low":
        parts.append("命名規則は不明")
    return DetectedGroup(paths, vendor, confidence, " / ".join(parts))


def _counter_text(first: _Info, last: _Info) -> str:
    label = {"dji": "DJI", "sony": "Sony"}.get(first.name.vendor, "")
    return f"{label} 連番 {first.name.label}→{last.name.label}".strip()


# ---------------------------------------------------------------------------
# 表示
# ---------------------------------------------------------------------------

_CONFIDENCE_TEXT = {"high": "確度: 高", "medium": "確度: 中",
                    "low": "確度: 低 (要確認)", "": ""}


def describe_groups(groups: List[DetectedGroup]) -> str:
    """検出結果を人が読める日本語にする。"""
    lines = []
    for gi, g in enumerate(groups, 1):
        if len(g.files) == 1:
            line = f"[{gi}] 単独 (結合不要): {os.path.basename(g.files[0])}"
            if g.reason and not g.reason.startswith("単独"):
                line += f"  — {g.reason}"
            lines.append(line)
            continue
        head = f"[{gi}] 分割された1本の撮影 ({len(g.files)} 個)"
        tail = " / ".join(x for x in (g.reason,
                                      _CONFIDENCE_TEXT.get(g.confidence, ""))
                          if x)
        lines.append(f"{head}: {tail}" if tail else f"{head}:")
        for p in g.files:
            lines.append(f"      {os.path.basename(p)}")
    return "\n".join(lines)
