"""gpmf_tool — GPMF (GoPro Metadata Format) の完全パーサと注入ツール。

- GPMF KLV の完全なパース / 生成 (全データ型・複合型・ネスト対応)
- MP4 からの gpmd トラック抽出 (テキスト / JSON / GPX 出力)
- 他社カメラの MP4 への GPMF トラック + GoPro 識別メタデータ注入
"""

from . import gopro, klv, mp4, telemetry
from .klv import GPMFError, GPMFItem, dump, parse, to_dict
from .mp4 import MP4Error, extract_gpmf_samples, inject_gpmf_track

__version__ = "1.0.0"

__all__ = [
    "gopro", "klv", "mp4", "telemetry",
    "GPMFError", "GPMFItem", "MP4Error",
    "parse", "dump", "to_dict",
    "extract_gpmf_samples", "inject_gpmf_track",
    "__version__",
]
