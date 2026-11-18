"""2D部品からDXFを生成し、読み戻して検証する。"""
from pathlib import Path
from math import pi
from .geometry import EPS, TAU, distance, validate_part


# 共通2DデータからDXF文字列を生成する。ここではファイルへ保存しない。
# 同梱テンプレートがCADの管理情報を担当し、ここでLINE/ARC/CIRCLEを追加する。
# ハンドル17はテンプレートのモデル空間を指すため、テンプレートとの整合を保つ。
def dxf_text(parts):
    lines = []
    def emit(*pairs):
        for code, value in pairs:
            lines.extend((str(code), f'{value:.9f}' if isinstance(value, float) else str(value)))
    # Complete R2000 document skeleton (tables, block records, model/paper space,
    # dictionaries and layouts). Its model-space block record has handle 17.
    template = Path(__file__).with_name('dxf_template.txt').read_text(encoding='ascii')
    handle = 0x100
    for p in parts:
        validate_part(p)
        for loop in p.loops:
            for c in loop.curves:
                emit((0, c.kind), (5, format(handle, 'X')), (330, '17'), (100, 'AcDbEntity'), (8, 'CUT_OUTER' if loop.outer else 'CUT_INNER'))
                handle += 1
                if c.kind == 'LINE':
                    emit((100, 'AcDbLine'), (10, c.start[0]), (20, c.start[1]), (30, 0.),
                         (11, c.end[0]), (21, c.end[1]), (31, 0.))
                else:
                    emit((100, 'AcDbCircle'), (10, c.center[0]), (20, c.center[1]), (30, 0.), (40, c.radius))
                    if c.kind == 'ARC':
                        start = c.angle if c.sweep > 0 else c.angle+c.sweep
                        emit((100, 'AcDbArc'), (50, (start*180/pi) % 360),
                             (51, ((start+abs(c.sweep))*180/pi) % 360))
    return template.replace('@@ENTITIES@@', '\n'.join(lines)).replace('@@HANDSEED@@', format(handle, 'X'))


# 保存前にDXFを読み戻し、mm単位・管理情報・要素数・座標・円弧を照合する。
# この照合はFusionの実際の読み込み試験を代替するものではない。
def validate_dxf(text, parts):
    """Read serialized numbers back, checking entities and physical mm geometry."""
    rows = text.splitlines()
    if len(rows) % 2 or rows[-2:] != ['0', 'EOF']:
        raise ValueError('不完全なDXF')
    pairs = [(int(rows[i]), rows[i+1]) for i in range(0, len(rows), 2)]
    sections = {pairs[i+1][1] for i, p in enumerate(pairs[:-1]) if p == (0, 'SECTION')}
    if not {'HEADER', 'TABLES', 'BLOCKS', 'ENTITIES', 'OBJECTS'}.issubset(sections):
        raise ValueError('DXFの管理セクションが不足しています')
    pos = pairs.index((9, '$INSUNITS'))
    if pairs[pos+1] != (70, '4'):
        raise ValueError('DXFの単位がmmではありません')
    entities, current = [], None
    for code, value in pairs:
        if code == 0:
            if current is not None:
                entities.append(current)
            current = {0: value} if value in ('LINE', 'ARC', 'CIRCLE') else None
        elif current is not None:
            current[code] = value
    expected = [(l, c) for p in parts for l in p.loops for c in l.curves]
    if len(entities) != len(expected):
        raise ValueError('DXF要素数が一致しません')
    for e, (loop, c) in zip(entities, expected):
        if e.get(330) != '17':
            raise ValueError('DXFのモデル空間への参照がありません')
        if e[0] != c.kind or e[8] != ('CUT_OUTER' if loop.outer else 'CUT_INNER'):
            raise ValueError('DXFの輪郭種類が一致しません')
        origin = c.start if c.kind == 'LINE' else c.center
        if distance((float(e[10]), float(e[20])), origin) > EPS or float(e[30]) != 0:
            raise ValueError('DXF座標が一致しません')
        if c.kind == 'LINE':
            if distance((float(e[11]), float(e[21])), c.end) > EPS:
                raise ValueError('DXF端点が一致しません')
        else:
            if abs(float(e[40])-c.radius) > EPS:
                raise ValueError('DXF半径が一致しません')
            if c.kind == 'ARC':
                sweep = ((float(e[51])-float(e[50])) % 360)*pi/180
                start = c.angle if c.sweep > 0 else c.angle+c.sweep
                delta = ((float(e[50])*pi/180-start+pi) % TAU)-pi
                if abs(delta)*c.radius > EPS or abs(sweep-abs(c.sweep))*c.radius > EPS:
                    raise ValueError('DXF円弧が一致しません')


