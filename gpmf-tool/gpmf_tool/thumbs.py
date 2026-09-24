"""動画のサムネイル取得。

外部ライブラリ無しでは動画フレームをデコードできないため、
次の順に「取れるものを取る」方式にしている:

1. MP4 に埋め込まれたサムネイル画像 (udta 内の JPEG)
   … 多くのカメラ/スマホが撮影時に入れている
2. 同名のサイドカー画像 (.thm / .jpg / .png)
   … GoPro は .THM、DJI も機種により書き出す
3. ffmpeg が入っていればそれで 1 フレーム抜き出す
4. どれも無ければ None (呼び出し側でプレースホルダを描く)

Pillow があれば実画像を表示でき、無くても 4 の代替表示で動く。
"""

from __future__ import annotations

import os
import shutil
import struct
import subprocess
from typing import Optional, Tuple

from . import mp4

# JPEG のマーカー
_SOI = b"\xff\xd8\xff"
_EOI = b"\xff\xd9"

_CACHE: dict = {}


def _find_jpeg(blob: bytes) -> Optional[bytes]:
    """バイト列から最初の JPEG を切り出す。"""
    start = blob.find(_SOI)
    if start < 0:
        return None
    end = blob.find(_EOI, start + 3)
    if end < 0:
        return None
    data = blob[start:end + 2]
    # 小さすぎるものはノイズとみなす
    return data if len(data) > 1024 else None


def embedded_thumbnail(path: str) -> Optional[bytes]:
    """MP4 の udta などに埋め込まれたサムネイル JPEG を取り出す。"""
    try:
        with open(path, "rb") as f:
            tops = mp4.scan_top_level(f)
            moov_top = next(b for b in tops if b.type == b"moov")
            # moov 全体は巨大なことがあるので、まず udta だけ見る
            moov = mp4.parse_box_tree(mp4.read_box_bytes(f, moov_top), b"moov")
            udta = moov.find(b"udta")
            if udta is not None:
                blob = b"".join(c.serialize() for c in udta.children)
                jpg = _find_jpeg(blob)
                if jpg:
                    return jpg
            # 一部カメラは moov 直下や free に置く
            for t in tops:
                if t.type in (b"free", b"skip", b"uuid") and t.size < 4 * 1024 * 1024:
                    jpg = _find_jpeg(mp4.read_box_bytes(f, t))
                    if jpg:
                        return jpg
    except Exception:
        pass
    return None


def sidecar_thumbnail(path: str) -> Optional[bytes]:
    """同名の .thm / .jpg / .png を探す (GoPro の .THM など)。"""
    stem = os.path.splitext(path)[0]
    for ext in (".thm", ".THM", ".jpg", ".JPG", ".jpeg", ".png", ".PNG"):
        cand = stem + ext
        if os.path.isfile(cand) and os.path.getsize(cand) < 16 * 1024 * 1024:
            try:
                with open(cand, "rb") as f:
                    return f.read()
            except OSError:
                pass
    return None


def ffmpeg_thumbnail(path: str, width: int = 160,
                     at_sec: float = 1.0) -> Optional[bytes]:
    """ffmpeg があれば 1 フレーム抜き出す (無ければ None)。"""
    exe = shutil.which("ffmpeg")
    if not exe:
        return None
    try:
        proc = subprocess.run(
            [exe, "-v", "error", "-ss", str(at_sec), "-i", path,
             "-frames:v", "1", "-vf", f"scale={width}:-1",
             "-f", "image2", "-vcodec", "mjpeg", "-"],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=20)
        if proc.returncode == 0 and proc.stdout[:3] == _SOI:
            return proc.stdout
    except Exception:
        pass
    return None


def get_thumbnail(path: str, use_ffmpeg: bool = True) -> Optional[bytes]:
    """サムネイル画像のバイト列を返す (取れなければ None)。"""
    if path in _CACHE:
        return _CACHE[path]
    data = embedded_thumbnail(path) or sidecar_thumbnail(path)
    if data is None and use_ffmpeg:
        data = ffmpeg_thumbnail(path)
    _CACHE[path] = data
    return data


def has_pillow() -> bool:
    try:
        import PIL.Image  # noqa: F401
        return True
    except Exception:
        return False


def make_photo_image(data: bytes, size: Tuple[int, int] = (128, 72)):
    """画像バイト列を Tkinter で表示できる PhotoImage にする。

    Pillow があれば JPEG/PNG を縮小して返す。無ければ PNG のみ
    Tk 8.6 の機能で表示を試み、それも無理なら None。
    """
    try:
        from PIL import Image, ImageTk
        import io
        img = Image.open(io.BytesIO(data))
        img.thumbnail(size)
        return ImageTk.PhotoImage(img)
    except Exception:
        pass
    # Pillow 無し: PNG なら Tk が直接読める
    try:
        import base64
        import tkinter as tk
        if data[:8] == b"\x89PNG\r\n\x1a\n":
            return tk.PhotoImage(data=base64.b64encode(data))
    except Exception:
        pass
    return None


def clear_cache() -> None:
    _CACHE.clear()
