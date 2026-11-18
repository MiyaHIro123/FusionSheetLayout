"""旧import向けの互換窓口。新しいコードは各担当モジュールを参照する。"""
from .geometry import (EPS, TAU, Curve, Loop, Part, distance, ordered_loop,
                       on_curve, intersections, validate_part)
from .layout import layout
from .dxf_writer import dxf_text, validate_dxf
from .file_io import safe_write
