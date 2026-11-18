"""部品の向き補正と棚配置。Fusionには依存しない。"""
from math import isfinite
from .geometry import validate_part


# 棚配置：背の高い部品から左詰めし、指定幅を超える手前で次の行へ進める。
# 最長直線辺を水平・垂直に補正後、縮尺変更や穴への入れ子配置なしで配置する。
# 最後に矩形同士の間隔を再検査し、配置済み部品・警告・全体寸法を返す。
def layout(parts, width=600., gap=3.):
    if not all(isfinite(v) for v in (width, gap)) or width <= 0 or gap < 0:
        raise ValueError('配置設定が不正です')
    sizes = []
    warnings = []
    for p in parts:
        validate_part(p)
        p = p.aligned()
        a, b, c, d = p.bounds()
        w, h = c-a, d-b
        if w > width+1e-8:
            warnings.append(f'{p.name}: PART_TOO_WIDE 幅{w:.3f}mmが配置幅{width:g}mmを超えます')
        else:
            sizes.append((p, a, b, w, h))
    sizes.sort(key=lambda v: (-v[4], -v[3], v[0].id))
    result, boxes = [], []
    x = y = row_h = 0.
    for p, a, b, w, h in sizes:
        if x and x+w > width+1e-8:
            x, y, row_h = 0., y+row_h+gap, 0.
        result.append(p.moved(x-a, y-b))
        boxes.append((x, y, x+w, y+h))
        x += w+gap
        row_h = max(row_h, h)
    for i, a in enumerate(boxes):
        if a[2] > width+1e-8:
            raise ValueError('配置幅の検証に失敗')
        for b in boxes[i+1:]:
            if not (a[2]+gap <= b[0]+1e-8 or b[2]+gap <= a[0]+1e-8 or
                    a[3]+gap <= b[1]+1e-8 or b[3]+gap <= a[1]+1e-8):
                raise ValueError('部品間隔の検証に失敗')
    size = (max((b[2] for b in boxes), default=0.), max((b[3] for b in boxes), default=0.))
    return result, warnings, size


