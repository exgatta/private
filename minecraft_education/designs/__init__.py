# -*- coding: utf-8 -*-
"""設計の登録簿。新しい設計を作ったらここに1行追加する。"""

from . import house

DESIGNS = {
    "house": house.build,
}
