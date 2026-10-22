"""Read-only Fusion BRep adapter. No model edits, sketches or temporary documents."""
from math import sqrt, sin, pi, atan2
import adsk.core
import adsk.fusion
from .core import Curve, Part, EPS, TAU, ordered_loop, validate_part, distance, layout

ANGLE = sin(0.01*pi/180)
CM_EPS = EPS/10


class Skip(ValueError):
    def __init__(self, code, message):
        self.code = code
        super().__init__(f'{code} {message}')


def items(collection):
    return [collection.item(i) for i in range(collection.count)]


def xyz(v):
    return (v.x, v.y, v.z)


def sub(a, b):
    return tuple(x-y for x, y in zip(a, b))


def dot(a, b):
    return sum(x*y for x, y in zip(a, b))


def cross(a, b):
    return (a[1]*b[2]-a[2]*b[1], a[2]*b[0]-a[0]*b[2], a[0]*b[1]-a[1]*b[0])


def unit(v):
    d = sqrt(dot(v, v))
    if d < 1e-12:
        raise Skip('EXTRACTION_FAILED', 'ゼロ方向ベクトル')
    return tuple(x/d for x in v)


def parallel(a, b):
    c = cross(unit(a), unit(b))
    return sqrt(dot(c, c)) <= ANGLE


def basis(normal):
    n = unit(normal)
    index = max(range(3), key=lambda i: abs(n[i]))
    if n[index] < 0:
        n = tuple(-v for v in n)
    axis = min(range(3), key=lambda i: abs(n[i]))
    ref = tuple(1. if i == axis else 0. for i in range(3))
    x = unit(sub(ref, tuple(dot(ref, n)*v for v in n)))
    return n, x, cross(n, x)


def checked(result):
    if not result[0]:
        raise Skip('EXTRACTION_FAILED', 'Fusionの幾何評価に失敗')
    return result[1:]


# Fusionの辺をmm単位の共通2D曲線へ変換する。
# 端面から外れる辺や未対応曲線は除外し、円弧の向き・半径・掃引角を保持する。
def edge_curve(edge, origin, n, x, y, height):
    geometry = edge.geometry
    evaluator = edge.evaluator
    lo, hi = checked(evaluator.getParameterExtents())
    p0, = checked(evaluator.getPointAtParameter(lo))
    p1, = checked(evaluator.getPointAtParameter(hi))

    def project(p):
        v = sub(xyz(p), origin)
        if abs(dot(v, n)-height) > CM_EPS:
            raise Skip('NON_PRISMATIC', '端面の辺が同一平面にありません')
        return dot(v, x)*10, dot(v, y)*10

    a, b = project(p0), project(p1)
    if adsk.core.Line3D.cast(geometry):
        if distance(a, b) <= EPS:
            raise Skip('INVALID_LOOP', 'ゼロ長または短すぎる辺')
        return Curve('LINE', a, b)
    circle = adsk.core.Circle3D.cast(geometry)
    arc = adsk.core.Arc3D.cast(geometry)
    g = circle or arc
    if not g:
        raise Skip('UNSUPPORTED_CURVE', '直線・円・円弧以外の輪郭は未対応です')
    if not parallel(xyz(g.normal), n):
        raise Skip('NON_PRISMATIC', '円弧の平面が端面と一致しません')
    center = project(g.center)
    radius = g.radius*10
    length, = checked(evaluator.getLengthAtParameter(lo, hi))
    sweep_size = length/g.radius
    if abs(sweep_size-TAU)*radius <= EPS and distance(a, b) <= EPS:
        return Curve('CIRCLE', center=center, radius=radius)
    if not 0 < sweep_size < TAU:
        raise Skip('INVALID_LOOP', '円弧の範囲が不正です')
    tangent, = checked(evaluator.getFirstDerivative(lo))
    radial = sub(xyz(p0), xyz(g.center))
    sign = 1 if dot(cross(radial, xyz(tangent)), n) > 0 else -1
    angle = atan2(a[1]-center[1], a[0]-center[0])
    curve = Curve('ARC', a, b, center, radius, angle, sign*sweep_size)
    if distance(curve.point(1), b) > EPS:
        raise Skip('INVALID_LOOP', '円弧の向きと端点が一致しません')
    return curve


def same_curve(a, b):
    if a.kind != b.kind:
        return False
    if a.kind == 'CIRCLE':
        return distance(a.center, b.center) <= EPS and abs(a.radius-b.radius) <= EPS
    endpoints = (distance(a.start, b.start) <= EPS and distance(a.end, b.end) <= EPS or
                 distance(a.start, b.end) <= EPS and distance(a.end, b.start) <= EPS)
    if not endpoints:
        return False
    return a.kind == 'LINE' or (distance(a.center, b.center) <= EPS and abs(a.radius-b.radius) <= EPS
                               and distance(a.point(.5), b.point(.5)) <= EPS)


# 端面の外周・全内周を取り出す。辺IDの対応表は表裏と側面の照合に使う。
def cap_loops(face, origin, n, x, y, height):
    loops = []
    edge_map = {}
    for loop in items(face.loops):
        curves = []
        for edge in items(loop.edges):
            curve = edge_curve(edge, origin, n, x, y, height)
            edge_map[edge.tempId] = curve
            curves.append(curve)
        try:
            loops.append(ordered_loop(curves, loop.isOuter))
        except ValueError as exc:
            raise Skip('INVALID_LOOP', str(exc)) from exc
    return tuple(loops), edge_map


# 候補の表裏輪郭と全側面・側辺を検査し、一定断面の板であることを確認する。
# 単なる外接寸法や体積一致だけで採用せず、段差・途中の切り込みを排除する。
def prove_prism(body, cap_a, cap_b, normal, thickness, part_id, name):
    n, x, y = basis(normal)
    origin = xyz(cap_a.geometry.origin)
    h = dot(sub(xyz(cap_b.geometry.origin), origin), n)
    if h < 0:
        cap_a, cap_b = cap_b, cap_a
        origin = xyz(cap_a.geometry.origin)
        h = -h
    loops, low = cap_loops(cap_a, origin, n, x, y, 0.)
    other_loops, high = cap_loops(cap_b, origin, n, x, y, h)
    if len(loops) != len(other_loops) or len(low) != len(high):
        raise Skip('NON_PRISMATIC', '表裏の穴・辺の数が一致しません')
    unmatched = list(other_loops)
    for loop in loops:
        candidates = [l for l in unmatched if l.outer == loop.outer and len(l.curves) == len(loop.curves)
                      and all(sum(same_curve(a, b) for b in l.curves) == 1 for a in loop.curves)]
        if len(candidates) != 1:
            raise Skip('NON_PRISMATIC', '表裏の輪郭が一致しません')
        unmatched.remove(candidates[0])
    caps = {cap_a.tempId, cap_b.tempId}
    seen_low, seen_high = set(), set()
    for face in items(body.faces):
        if face.tempId in caps:
            continue
        geom = face.geometry
        plane = adsk.core.Plane.cast(geom)
        cylinder = adsk.core.Cylinder.cast(geom)
        if plane:
            if abs(dot(unit(xyz(plane.normal)), n)) > ANGLE:
                raise Skip('NON_PRISMATIC', '側面に傾斜・段差があります')
        elif cylinder:
            if not parallel(xyz(cylinder.axis), n):
                raise Skip('NON_PRISMATIC', '穴または円弧側面が板厚方向と一致しません')
        else:
            raise Skip('NON_PRISMATIC', '側面に自由曲面・面取り・丸みがあります')
        edges = items(face.edges)
        lows = [e for e in edges if e.tempId in low]
        highs = [e for e in edges if e.tempId in high]
        if len(lows) != 1 or len(highs) != 1:
            raise Skip('NON_PRISMATIC', '側面が表裏を一様につないでいません（面分割も未対応）')
        le, he = lows[0], highs[0]
        if not same_curve(low[le.tempId], high[he.tempId]):
            raise Skip('NON_PRISMATIC', '側面の表裏形状が一致しません')
        if le.tempId in seen_low or he.tempId in seen_high:
            raise Skip('NON_PRISMATIC', '側面の接続が重複しています')
        seen_low.add(le.tempId)
        seen_high.add(he.tempId)
        for edge in edges:
            if edge.tempId in low or edge.tempId in high:
                if edge.faces.count != 2:
                    raise Skip('NON_PRISMATIC', '非多様体の辺')
                continue
            if not adsk.core.Line3D.cast(edge.geometry):
                raise Skip('NON_PRISMATIC', '側面に途中の切り込みがあります')
            if edge.startVertex is None or edge.endVertex is None:
                raise Skip('NON_PRISMATIC', '側辺の頂点を取得できません')
            a, b = xyz(edge.startVertex.geometry), xyz(edge.endVertex.geometry)
            if not parallel(sub(b, a), n):
                raise Skip('NON_PRISMATIC', '側辺が板厚方向と一致しません')
            za, zb = sorted((dot(sub(a, origin), n), dot(sub(b, origin), n)))
            if abs(za) > CM_EPS or abs(zb-h) > CM_EPS:
                raise Skip('NON_PRISMATIC', '側辺が全厚を通過していません')
    if seen_low != set(low) or seen_high != set(high):
        raise Skip('NON_PRISMATIC', '接続されていない端面の辺があります')
    # Volume is supplemental; the full face/edge checks above establish the prism.
    expected = cap_a.area*h
    if abs(body.volume-expected) > max(cap_a.area*CM_EPS, expected*1e-6):
        raise Skip('NON_PRISMATIC', '端面面積と体積が一致しません')
    part = Part(part_id, name, thickness, loops)
    try:
        validate_part(part)
    except ValueError as exc:
        raise Skip('INVALID_LOOP', str(exc)) from exc
    return part


# 平行な端面の組から板厚候補を探し、一様な板形状として検証する。
# 候補が複数ある場合、設定OFFなら除外、ONなら面積最大候補を警告付きで返す。
def extract(body, part_id, name, tolerance, allow_ambiguous=False, notices=None):
    if not body.isValid or not body.isSolid or body.lumps.count != 1 or body.shells.count != 1:
        raise Skip('NOT_SOLID', '単一の閉じたソリッドではありません')
    planes = [f for f in items(body.faces) if adsk.core.Plane.cast(f.geometry)]
    successes, errors, distances = [], [], []
    for i, a in enumerate(planes):
        for b in planes[i+1:]:
            n = unit(xyz(a.geometry.normal))
            if not parallel(n, xyz(b.geometry.normal)):
                continue
            t = abs(dot(sub(xyz(b.geometry.origin), xyz(a.geometry.origin)), n))*10
            if t <= EPS:
                continue
            distances.append(t)
            if abs(t-2.5) > tolerance+1e-8:
                continue
            try:
                part = prove_prism(body, a, b, n, t, part_id, name)
                successes.append((part, a.area, basis(n)[0]))
            except Skip as exc:
                errors.append(exc)
    if len(successes) > 1:
        if not allow_ambiguous or notices is None:
            raise Skip('AMBIGUOUS_FACE', '板厚方向の候補が複数あります。設定で警告付き出力を有効にできます')
        # Prefer the largest verified cap. Equal areas use X/Y/Z normal order,
        # then the normal components, so repeated analysis makes the same choice.
        successes.sort(key=lambda item: (-item[1], max(range(3), key=lambda i: abs(item[2][i])), item[2]))
        selected, area, normal = successes[0]
        x0, y0, x1, y1 = selected.bounds()
        direction = ', '.join(f'{0. if abs(v) < 0.0000005 else v:.6f}' for v in normal)
        notices.append(f'{name}: [警告付き出力候補] AMBIGUOUS_FACE 板厚方向が{len(successes)}候補あります。'
                       f'板面積最大（同面積は法線X/Y/Z順）の候補を選択: '
                       f'厚さ{selected.thickness:.4f}mm、輪郭{x1-x0:.3f}×{y1-y0:.3f}mm、'
                       f'法線({direction})。「無視」でこの候補も出力します（配置幅を超える場合は除外）。')
        return selected
    if successes:
        return successes[0][0]
    if errors:
        preferred = next((e for e in errors if e.code == 'UNSUPPORTED_CURVE'), errors[0])
        raise preferred
    detail = ', '.join(f'{v:.4f}' for v in sorted(set(round(d, 6) for d in distances))[:8])
    raise Skip('THICKNESS_OUT_OF_RANGE', f'2.5±{tolerance:g}mmの端面がありません。平面間距離(mm): {detail or "取得不可"}')


# ルートと各オカレンスのボディを列挙し、表示設定・形状判定・配置を順に行う。
# 同一部品の別オカレンスは別数量。プロキシの座標へ変換を二重に適用しない。
# ボディ単位の失敗は警告へまとめ、配置など全体処理の失敗は呼び出し元へ伝える。
def analyze(design, settings):
    parts, warnings, hidden = [], [], 0
    root = design.rootComponent
    seq = 0

    def collect(collection, prefix, visible=True):
        nonlocal seq, hidden
        for body in items(collection):
            seq += 1
            name = f'{prefix} / {body.name}'
            try:
                if not settings['hidden'] and (not visible or not body.isVisible):
                    hidden += 1
                    continue
                parts.append(extract(body, f'{seq:06d}', name, settings['tolerance'],
                                     settings.get('allow_ambiguous', False), warnings))
            except Skip as exc:
                warnings.append(f'{name}: {exc}')
            except Exception as exc:
                warnings.append(f'{name}: EXTRACTION_FAILED {type(exc).__name__}: {exc}')

    def meshes(component, prefix, occurrence=None):
        nonlocal hidden
        for body in items(component.meshBodies):
            proxy = body.createForAssemblyContext(occurrence) if occurrence else body
            if not settings['hidden'] and (not proxy.isVisible or (occurrence and not occurrence.isVisible)):
                hidden += 1
            else:
                warnings.append(f'{prefix} / {body.name}: NOT_SOLID メッシュは対象外です')

    collect(root.bRepBodies, root.name)
    meshes(root, root.name)
    for occ in items(root.allOccurrences):
        name = occ.fullPathName
        try:
            # bRepBodies are proxies in this occurrence context. Do not apply transform2 again.
            if not occ.isValid:
                raise Skip('UNRESOLVED_INSTANCE', 'オカレンスが無効です')
            matrix = occ.transform2
            axes = [tuple(matrix.getCell(r, c) for r in range(3)) for c in range(3)]
            if any(abs(dot(a, b)-(1. if i == j else 0.)) > 1e-6
                   for i, a in enumerate(axes) for j, b in enumerate(axes)):
                raise Skip('UNRESOLVED_INSTANCE', '非剛体変換は未対応です')
            collect(occ.bRepBodies, name, occ.isVisible)
            meshes(occ.component, name, occ)
        except Exception as exc:
            warnings.append(f'{name}: UNRESOLVED_INSTANCE {exc}')
    placed, layout_warnings, size = layout(parts, settings['width'], settings['gap'])
    warnings.extend(layout_warnings)
    return placed, warnings, size, hidden
