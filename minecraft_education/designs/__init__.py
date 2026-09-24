# -*- coding: utf-8 -*-
"""設計の登録簿。新しい設計を作ったらここに1行追加する。"""

from . import house
from . import trap_pit

DESIGNS = {
    "house": house.build,
    "trap_pit": trap_pit.build,
}
