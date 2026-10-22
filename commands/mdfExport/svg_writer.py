"""Exact line/arc/circle SVG export in millimetres; independent of Fusion."""
import math
import xml.etree.ElementTree as ET
from .core import EPS, validate_part

NS = 'http://www.w3.org/2000/svg'


# 全配置部品の外接範囲から、SVGの原点とmm単位の幅・高さを求める。
def dimensions(parts):
    if not parts:
        raise ValueError('出力する部品がありません')
    boxes = [p.bounds() for p in parts]
    x0, y0 = min(b[0] for b in boxes), min(b[1] for b in boxes)
    x1, y1 = max(b[2] for b in boxes), max(b[3] for b in boxes)
    if x1-x0 <= 0 or y1-y0 <= 0:
        raise ValueError('SVGの寸法が不正です')
    return x0, y1, x1-x0, y1-y0


# 輪郭をM/L/A/Z命令へ変換する。SVGの下向きY軸に合わせて座標と円弧方向を変える。
def path_tokens(loop, x0, y1):
    first = loop.curves[0].start
    tokens = ['M', first[0]-x0, y1-first[1]]
    for c in loop.curves:
        if c.kind == 'LINE':
            tokens.extend(['L', c.end[0]-x0, y1-c.end[1]])
        elif c.kind == 'ARC':
            # SVG Y grows downwards. Reflect coordinates AND reverse sweep sense.
            tokens.extend(['A', c.radius, c.radius, 0, int(abs(c.sweep) > math.pi),
                           int(c.sweep < 0), c.end[0]-x0, y1-c.end[1]])
        else:
            raise ValueError('円は独立したSVG要素で出力する必要があります')
    return tokens+['Z']


def number(v):
    if not math.isfinite(v):
        raise ValueError('SVGの数値が不正です')
    return f'{v:.9f}'


# 実寸mmのSVG文字列を生成する。各輪郭へ塗りなし・線色・表示線幅を明示する。
# 表示線幅は切りしろではなく、切断中心線の座標は変更しない。
def svg_text(parts):
    x0, y1, width, height = dimensions(parts)
    root = ET.Element('svg', {'xmlns': NS, 'version': '1.1',
                             'width': number(width)+'mm', 'height': number(height)+'mm',
                             'viewBox': f'0 0 {number(width)} {number(height)}'})
    for index, part in enumerate(parts):
        validate_part(part)
        group = ET.SubElement(root, 'g', {'id': f'part_{index+1}', 'fill': 'none'})
        for li, loop in enumerate(part.loops):
            attrs = {'id': f'part_{index+1}_loop_{li+1}',
                     'class': 'CUT_OUTER' if loop.outer else 'CUT_INNER',
                     'fill': 'none', 'stroke': '#000000', 'stroke-width': '0.1',
                     'style': 'fill:none;stroke:#000000;stroke-width:0.1;stroke-linejoin:round;stroke-linecap:round'}
            if len(loop.curves) == 1 and loop.curves[0].kind == 'CIRCLE':
                c = loop.curves[0]
                attrs.update(cx=number(c.center[0]-x0), cy=number(y1-c.center[1]), r=number(c.radius))
                ET.SubElement(group, 'circle', attrs)
            else:
                attrs['d'] = ' '.join(t if isinstance(t, str) else str(t) if isinstance(t, int) else number(t)
                                      for t in path_tokens(loop, x0, y1))
                ET.SubElement(group, 'path', attrs)
    return '<?xml version="1.0" encoding="UTF-8"?>\n'+ET.tostring(root, encoding='unicode')+'\n'


# XMLを読み戻し、寸法・外周内周・円・パス命令を元データと比較する。
def validate_svg(text, parts):
    """Parse saved XML and verify units, topology, radii and arc flags."""
    root = ET.fromstring(text)
    if root.tag != '{'+NS+'}svg':
        raise ValueError('SVGルートが不正です')
    x0, y1, width, height = dimensions(parts)
    for key, expected in (('width', width), ('height', height)):
        value = root.attrib.get(key, '')
        if not value.endswith('mm') or abs(float(value[:-2])-expected) > EPS:
            raise ValueError('SVGのmm寸法が一致しません')
    view = [float(v) for v in root.attrib.get('viewBox', '').split()]
    if len(view) != 4 or any(abs(a-b) > EPS for a, b in zip(view, (0., 0., width, height))):
        raise ValueError('SVG viewBoxが一致しません')
    groups = list(root)
    if len(groups) != len(parts):
        raise ValueError('SVG部品数が一致しません')
    for group, part in zip(groups, parts):
        if group.tag != '{'+NS+'}g' or group.attrib.get('fill') != 'none':
            raise ValueError('SVGグループが不正です')
        elements = list(group)
        if len(elements) != len(part.loops):
            raise ValueError('SVG輪郭数が一致しません')
        for element, loop in zip(elements, part.loops):
            if element.attrib.get('class') != ('CUT_OUTER' if loop.outer else 'CUT_INNER'):
                raise ValueError('SVG内外周が一致しません')
            if len(loop.curves) == 1 and loop.curves[0].kind == 'CIRCLE':
                c = loop.curves[0]
                if element.tag != '{'+NS+'}circle':
                    raise ValueError('SVG円がありません')
                for key, expected in (('cx', c.center[0]-x0), ('cy', y1-c.center[1]), ('r', c.radius)):
                    if abs(float(element.attrib[key])-expected) > EPS:
                        raise ValueError('SVG円の寸法が一致しません')
            else:
                if element.tag != '{'+NS+'}path':
                    raise ValueError('SVGパスがありません')
                actual = element.attrib['d'].split()
                expected = path_tokens(loop, x0, y1)
                if len(actual) != len(expected):
                    raise ValueError('SVGパス要素数が一致しません')
                for a, b in zip(actual, expected):
                    if isinstance(b, str):
                        if a != b:
                            raise ValueError('SVGパス命令が一致しません')
                    elif not math.isfinite(float(a)) or abs(float(a)-b) > 1e-8:
                        raise ValueError('SVGパス座標が一致しません')
