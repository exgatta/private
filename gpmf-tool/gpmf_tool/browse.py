"""フォルダを精査して「結合すべき一群」を組み立てる。

GUI のエクスプローラー風一覧に必要な情報 (名前・サイズ・長さ・解像度・
撮影日時・GPS 有無・360度か) をまとめて返す。
"""

from __future__ import annotations

import datetime
import os
from dataclasses import dataclass, field
from typing import List, Optional

from . import mp4, split_detect


@dataclass
class FileEntry:
    """一覧の 1 行分。"""
    path: str
    size: int = 0
    duration: float = 0.0
    width: int = 0
    height: int = 0
    fps: float = 0.0
    codec: str = ""
    created: Optional[datetime.datetime] = None        # 差分計算用
    created_local: Optional[datetime.datetime] = None  # 表示用の壁時計 (naive)
    created_source: str = ""       # "filename" | "quicktime" | "camera" | ""
    has_gpmd: bool = False
    has_gps: bool = False
    is_360: bool = False
    error: Optional[str] = None    # MP4 として読めなかった理由
    warning: Optional[str] = None  # 付加情報の取得だけ失敗した理由
    selected: bool = True          # 取捨選択用

    @property
    def name(self) -> str:
        return os.path.basename(self.path)

    @property
    def size_text(self) -> str:
        return format_size(self.size)

    @property
    def duration_text(self) -> str:
        return format_duration(self.duration)

    @property
    def resolution_text(self) -> str:
        if not self.width:
            return "-"
        return f"{self.width} x {self.height}"

    @property
    def created_text(self) -> str:
        """撮影日時の表示。カメラの時計の値 (ローカル時刻) をそのまま出す。

        ファイル名に時刻がある DJI / Insta360 はそれを使う (動画内の mvhd が
        UTC の機種でも正しい時刻になる)。無ければ動画内の値を TZ 変換せずに。
        """
        wall = self.created_local or mp4.camera_wall_time(self.created)
        if wall is None:
            return "-"
        return f"{wall:%Y/%m/%d %H:%M}"

    @property
    def created_note(self) -> str:
        """撮影日時の出典 (詳細ペイン用)。ファイル名優先のときだけ補足する。"""
        if self.created_source != "filename":
            return ""
        inner = mp4.camera_wall_time(self.created)
        if inner is None or self.created_local is None:
            return "ファイル名の時刻"
        diff = (inner - self.created_local).total_seconds()
        if abs(diff) < 60:
            return "ファイル名の時刻"
        sign = "+" if diff > 0 else "-"
        h, m = divmod(int(round(abs(diff) / 60)), 60)   # 分単位に丸める
        return (f"ファイル名の時刻。動画内の記録 {inner:%H:%M} は "
                f"{sign}{h}:{m:02d} ずれている (UTC 記録の機種)")

    @property
    def kind_text(self) -> str:
        marks = []
        if self.is_360:
            marks.append("360度")
        if self.has_gpmd:
            marks.append("GoPro")
        elif self.has_gps:
            marks.append("GPS")
        return " ".join(marks) if marks else "動画"


@dataclass
class Group:
    """結合すべき一群 (単独動画も 1 件のグループとして表れる)。

    reason / confidence / vendor は判定ロジック (split_detect) が埋める。
    """
    entries: List[FileEntry] = field(default_factory=list)
    reason: str = ""        # なぜ一群と判定したか (日本語、UI に表示)
    confidence: str = ""    # "high" | "medium" | "low"
    vendor: str = ""        # "gopro" | "dji" | "insta360" | "sony" | "generic"

    @property
    def is_split(self) -> bool:
        """強制分割された一連の撮影か。"""
        return len(self.entries) >= 2

    @property
    def selected_entries(self) -> List[FileEntry]:
        return [e for e in self.entries if e.selected and e.error is None]

    @property
    def total_size(self) -> int:
        return sum(e.size for e in self.selected_entries)

    @property
    def total_duration(self) -> float:
        return sum(e.duration for e in self.selected_entries)

    @property
    def title(self) -> str:
        n = len(self.selected_entries)
        if not self.is_split:
            return f"単独の動画 ({format_duration(self.total_duration)})"
        return (f"分割された1本の撮影 — {n}個 / "
                f"{format_duration(self.total_duration)} / "
                f"{format_size(self.total_size)}")

    @property
    def first_created(self) -> Optional[datetime.datetime]:
        for e in self.entries:
            if e.created:
                return e.created
        return None


# ---------------------------------------------------------------------------
# 表示用の整形
# ---------------------------------------------------------------------------

def format_size(n: int) -> str:
    if n >= 1024 ** 3:
        return f"{n / 1024 ** 3:.2f} GB"
    if n >= 1024 ** 2:
        return f"{n / 1024 ** 2:.0f} MB"
    if n >= 1024:
        return f"{n / 1024:.0f} KB"
    return f"{n} B"


def format_duration(sec: float) -> str:
    if sec <= 0:
        return "-"
    total = int(round(sec))
    h, rem = divmod(total, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m}:{s:02d}"


# ---------------------------------------------------------------------------
# 精査
# ---------------------------------------------------------------------------

def analyze_file(path: str) -> FileEntry:
    """1 ファイルを解析して一覧用の情報にする。

    解析は段階ごとに切り分けてあり、付加情報 (GPS/360度など) の取得に
    失敗しても、動画自体が読めていれば一覧には出す。
    「読めません」になるのは MP4 として開けなかった場合だけ。
    """
    entry = FileEntry(path=path)
    try:
        entry.size = os.path.getsize(path)
    except OSError as e:
        entry.error = f"ファイルを開けません: {e}"
        return entry

    try:
        f = open(path, "rb")
    except OSError as e:
        entry.error = f"ファイルを開けません: {e}"
        return entry

    warnings: List[str] = []
    try:
        # --- 1) 基本情報 (これが失敗したら結合対象にできない) ---
        try:
            m = mp4.media_summary(f)
            entry.duration = m["duration_sec"]
            entry.width = m["width"] or 0
            entry.height = m["height"] or 0
            entry.fps = m["fps"] or 0.0
            entry.codec = m["video_codec"] or ""
            entry.created = m["creation_time"]
            # 表示用: ファイル名の時刻 (カメラの時計) > 動画内の値
            name_wall = mp4.wall_time_from_name(path)
            if name_wall is not None:
                entry.created_local = name_wall
                entry.created_source = "filename"
            else:
                entry.created_local = m.get("creation_local")
                entry.created_source = m.get("creation_source") or ""
        except Exception as e:
            entry.error = _explain(e)
            return entry

        # --- 2) 付加情報 (失敗しても致命的ではない) ---
        try:
            f.seek(0)
            tele = mp4.detect_telemetry(f)
            entry.has_gpmd = tele["gpmd"]
            entry.has_gps = bool(tele["formats"])
        except Exception as e:
            warnings.append(f"GPS情報の判定に失敗: {_explain(e)}")

        try:
            f.seek(0)
            entry.is_360 = mp4.detect_spherical(f)["is_360"]
        except Exception as e:
            warnings.append(f"360度判定に失敗: {_explain(e)}")
    finally:
        f.close()

    entry.warning = " / ".join(warnings) if warnings else None
    return entry


def _explain(e: Exception) -> str:
    """例外を短い日本語にする (UI に出す用)。"""
    try:
        from .__main__ import humanize_error
        return humanize_error(e)
    except Exception:
        return str(e) or e.__class__.__name__


def scan_folder(paths, recursive: bool = True,
                progress=None) -> List[Group]:
    """フォルダ/ファイル群を精査し、結合すべき一群にまとめて返す。

    progress(done, total, name) が指定されていれば進捗を通知する。
    """
    from .__main__ import collect_videos

    files = collect_videos(list(paths), recursive=recursive)
    if not files:
        return []

    entries = {}
    for i, p in enumerate(files, 1):
        if progress:
            progress(i, len(files), os.path.basename(p))
        entries[os.path.realpath(p)] = analyze_file(p)

    groups: List[Group] = []
    for dg in split_detect.detect_groups(files):
        g = Group(entries=[entries[os.path.realpath(p)] for p in dg.files
                           if os.path.realpath(p) in entries],
                  reason=dg.reason, confidence=dg.confidence,
                  vendor=dg.vendor)
        if g.entries:
            groups.append(g)
    return groups


def summarize(groups: List[Group]) -> str:
    """全体の要約 (日本語)。"""
    n_split = sum(1 for g in groups if g.is_split)
    n_solo = sum(1 for g in groups if not g.is_split)
    n_files = sum(len(g.entries) for g in groups)
    parts = [f"動画 {n_files} 個"]
    if n_split:
        parts.append(f"結合対象 {n_split} 件")
    if n_solo:
        parts.append(f"単独 {n_solo} 個")
    return " / ".join(parts)
