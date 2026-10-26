"""Fusion-independent, millimetre geometry, shelf layout and DXF serialization."""
from dataclasses import dataclass, replace
from math import atan2, cos, sin, pi, hypot, isfinite, sqrt
from pathlib import Path
import os
import shutil
import uuid

EPS = 0.001
TAU = 2 * pi


# 直線・円弧・円を共通のデータ型で保持する。座標・半径はmm、角度はラジアン。
# 変更は元データへ代入せずreplaceで新しい値を作り、解析結果を保護する。
@dataclass(frozen=True)
class Curve:
    kind: str
    start: tuple = (0., 0.)
    end: tuple = (0., 0.)
    center: tuple = (0., 0.)
    radius: float = 0.
    angle: float = 0.
    sweep: float = 0.

    # 曲線上の位置を返す。t=0が始点、t=1が終点。円は1周する。
    def point(self, t):
        if self.kind == 'LINE':
            return tuple(a + (b-a)*t for a, b in zip(self.start, self.end))
        a = self.angle + (TAU if self.kind == 'CIRCLE' else self.sweep) * t
        return (self.center[0]+self.radius*cos(a), self.center[1]+self.radius*sin(a))

    # 辺を逆向きにする。形状は変えず、接続順と円弧の掃引方向を反転する。
    def reversed(self):
        return replace(self, start=self.end, end=self.start,
                       angle=self.angle+self.sweep, sweep=-self.sweep)

    # 始点・終点・中心へ同じ移動量を加える。半径や角度は変更しない。
    def moved(self, x, y):
        def move(p):
            return (p[0]+x, p[1]+y)
        return replace(self, start=move(self.start), end=move(self.end), center=move(self.center))

    def rotated(self, angle):
        """Rigid rotation about the projection origin; preserve analytic curves."""
        co, si = cos(angle), sin(angle)
        def rotate(p):
            return (co*p[0]-si*p[1], si*p[0]+co*p[1])
        return replace(self, start=rotate(self.start), end=rotate(self.end),
                       center=rotate(self.center), angle=self.angle+angle)

    # 指定角度が円弧の範囲内か判定する。0度をまたぐ区間にも対応する。
    def contains_angle(self, a, tolerance=1e-10):
        if self.kind == 'CIRCLE':
            return True
        delta = ((a-self.angle) if self.sweep > 0 else (self.angle-a)) % TAU
        return delta <= abs(self.sweep)+tolerance or TAU-delta <= tolerance

    # 外接矩形を求める。円弧は端点だけでは不十分なので上下左右の極値も含める。
    def bounds(self):
        if self.kind == 'LINE':
            pts = [self.start, self.end]
        else:
            pts = [self.point(0), self.point(1)]
            pts += [(self.center[0]+self.radius*cos(a), self.center[1]+self.radius*sin(a))
                    for a in (0, pi/2, pi, 3*pi/2) if self.contains_angle(a)]
        return (min(p[0] for p in pts), min(p[1] for p in pts),
                max(p[0] for p in pts), max(p[1] for p in pts))

    # 輪郭の符号付き面積への寄与を計算する。各辺の値の合計で周回方向を判断する。
    def area(self):
        if self.kind == 'LINE':
            return (self.start[0]*self.end[1]-self.end[0]*self.start[1])/2
        sweep = TAU if self.kind == 'CIRCLE' else self.sweep
        a, b = self.angle, self.angle+sweep
        x, y = self.center
        r = self.radius
        return (r*x*(sin(b)-sin(a))+r*y*(cos(a)-cos(b))+r*r*sweep)/2


# 閉じた輪郭を保持する。outer=Trueは外周、Falseは穴の内周を表す。
@dataclass(frozen=True)
class Loop:
    outer: bool
    curves: tuple


# 1部品分の識別情報、実測板厚、外周と穴をまとめる。Fusionの参照は持たない。
@dataclass(frozen=True)
class Part:
    id: str
    name: str
    thickness: float
    loops: tuple

    # 全輪郭の矩形をまとめ、部品全体の左下・右上を返す。
    def bounds(self):
        b = [c.bounds() for loop in self.loops for c in loop.curves]
        if not b:
            raise ValueError('輪郭がありません')
        return min(x[0] for x in b), min(x[1] for x in b), max(x[2] for x in b), max(x[3] for x in b)

    # 部品の全輪郭をまとめて移動し、配置後の新しい部品データを返す。
    def moved(self, x, y):
        return replace(self, loops=tuple(Loop(l.outer, tuple(c.moved(x, y) for c in l.curves)) for l in self.loops))

    def aligned(self):
        """Snap the longest straight edge to the nearest horizontal/vertical axis."""
        longest, length = None, 0.
        for loop in self.loops:
            for curve in loop.curves:
                if curve.kind == 'LINE':
                    candidate = distance(curve.start, curve.end)
                    # Keep the first edge on numerical ties (in millimetres).
                    if candidate > length+1e-9:
                        longest, length = curve, candidate
        if longest is None:
            return self
        dx = longest.end[0]-longest.start[0]
        dy = longest.end[1]-longest.start[1]
        angle = atan2(dy, dx)
        # Undirected edge angle in [-90, 90); exact 45-degree ties go vertical.
        angle = (angle+pi/2) % pi-pi/2
        target = 0. if abs(angle) < pi/4-1e-12 else (pi/2 if angle >= 0 else -pi/2)
        rotation = target-angle
        return replace(self, loops=tuple(
            Loop(loop.outer, tuple(c.rotated(rotation) for c in loop.curves))
            for loop in self.loops))


# 2点間の距離をmmで計算する。端点の接続確認などで使う。
def distance(a, b):
    return hypot(a[0]-b[0], a[1]-b[1])


# 取得順が不定の辺を端点のつながりで並べ直す。
# 接続先が一意でない場合は推測せず失敗にする。外周は反時計回り、穴は時計回りにそろえる。
# 公差以内の一致は認めるが、端点座標を補正して隙間を埋める処理はしない。
def ordered_loop(curves, outer):
    """Connect unordered edge geometry; never heal gaps or approximate curves."""
    if not curves:
        raise ValueError('空の輪郭')
    if any(c.kind == 'CIRCLE' for c in curves):
        if len(curves) != 1:
            raise ValueError('円と他の辺が同じループにあります')
        return Loop(outer, tuple(curves))
    todo = list(curves)
    chain = [todo.pop(0)]
    while todo:
        matches = [(i, c if distance(chain[-1].end, c.start) <= EPS else c.reversed())
                   for i, c in enumerate(todo)
                   if min(distance(chain[-1].end, c.start), distance(chain[-1].end, c.end)) <= EPS]
        if len(matches) != 1:
            raise ValueError('輪郭が閉じない、または接続が曖昧です')
        i, c = matches[0]
        chain.append(c)
        todo.pop(i)
    if distance(chain[-1].end, chain[0].start) > EPS:
        raise ValueError('輪郭が閉じていません')
    area = sum(c.area() for c in chain)
    if abs(area) <= EPS*EPS:
        raise ValueError('面積がゼロの輪郭')
    if (area > 0) != outer:
        chain = [c.reversed() for c in reversed(chain)]
    return Loop(outer, tuple(chain))


# 点が有限長の直線・円弧・円の上にあるか調べる。延長線上だけの点は除く。
def on_curve(c, p):
    if c.kind == 'LINE':
        return abs(distance(c.start, p)+distance(p, c.end)-distance(c.start, c.end)) <= 1e-7
    return abs(distance(c.center, p)-c.radius) <= EPS and c.contains_angle(
        atan2(p[1]-c.center[1], p[0]-c.center[0]), EPS/max(c.radius, EPS))


# 直線同士、直線と円、円同士を解析的に交差判定する。
# 戻り値は交点のリスト。空リストは交差なし、Noneは区間が重なっていることを表す。
# 円弧の場合は円全体で求めた交点を実際の角度範囲で絞り込む。
def intersections(a, b):
    """Return intersection points; None means overlapping segments."""
    def cross(u, v):
        return u[0]*v[1]-u[1]*v[0]
    def sub(u, v):
        return (u[0]-v[0], u[1]-v[1])
    if a.kind == b.kind == 'LINE':
        r, s, d = sub(a.end, a.start), sub(b.end, b.start), sub(b.start, a.start)
        den = cross(r, s)
        if abs(den) < 1e-12:
            if abs(cross(d, r)) > 1e-8:
                return []
            rr = r[0]**2+r[1]**2
            t0 = (d[0]*r[0]+d[1]*r[1])/rr
            e = sub(b.end, a.start)
            t1 = (e[0]*r[0]+e[1]*r[1])/rr
            lo, hi = max(0., min(t0, t1)), min(1., max(t0, t1))
            if hi < lo-1e-10:
                return []
            if (hi-lo)*sqrt(rr) > EPS:
                return None
            return [a.point((lo+hi)/2)]
        t, u = cross(d, s)/den, cross(d, r)/den
        return [a.point(t)] if -1e-10 <= t <= 1+1e-10 and -1e-10 <= u <= 1+1e-10 else []
    if b.kind == 'LINE':
        return intersections(b, a)
    if a.kind == 'LINE':
        d, f = sub(a.end, a.start), sub(a.start, b.center)
        aa = d[0]**2+d[1]**2
        bb = 2*(d[0]*f[0]+d[1]*f[1])
        cc = f[0]**2+f[1]**2-b.radius**2
        disc = bb*bb-4*aa*cc
        if disc < -1e-8:
            return []
        pts = [a.point(t) for t in ((-bb+sqrt(max(0., disc)))/(2*aa), (-bb-sqrt(max(0., disc)))/(2*aa))
               if -1e-10 <= t <= 1+1e-10]
        return [p for p in pts if on_curve(b, p)]
    d = distance(a.center, b.center)
    if d <= 1e-8:
        if abs(a.radius-b.radius) > EPS:
            return []
        if a.kind == 'CIRCLE' or b.kind == 'CIRCLE':
            return None
        # Partition angular intervals at all endpoints to detect coincident overlap.
        angles = sorted({0., TAU, a.angle % TAU, (a.angle+a.sweep) % TAU,
                         b.angle % TAU, (b.angle+b.sweep) % TAU})
        if any(a.contains_angle((u+v)/2) and b.contains_angle((u+v)/2)
               for u, v in zip(angles, angles[1:]) if v-u > 1e-10):
            return None
        return [p for p in (a.start, a.end) if on_curve(b, p)]
    if d > a.radius+b.radius+1e-8 or d < abs(a.radius-b.radius)-1e-8:
        return []
    x = (a.radius*a.radius-b.radius*b.radius+d*d)/(2*d)
    h = sqrt(max(0., a.radius*a.radius-x*x))
    ux, uy = (b.center[0]-a.center[0])/d, (b.center[1]-a.center[1])/d
    pts = [(a.center[0]+x*ux-k*h*uy, a.center[1]+x*uy+k*h*ux) for k in (-1, 1)]
    return [p for p in pts if on_curve(a, p) and on_curve(b, p)]


# 出力前の形状検査。外周数、数値、短すぎる辺、閉鎖性、自己交差、重複を確認する。
# 同じループの隣り合う辺が共有する端点だけは、正常な接続として許可する。
def validate_part(part):
    if sum(l.outer for l in part.loops) != 1:
        raise ValueError('外周は1本である必要があります')
    all_curves = []
    for li, loop in enumerate(part.loops):
        if not loop.curves:
            raise ValueError('空の輪郭')
        for i, c in enumerate(loop.curves):
            if not all(isfinite(x) for x in (*c.start, *c.end, *c.center, c.radius, c.angle, c.sweep)):
                raise ValueError('不正な数値')
            if c.kind not in ('LINE', 'ARC', 'CIRCLE'):
                raise ValueError('未対応の曲線')
            if c.kind == 'LINE' and distance(c.start, c.end) <= EPS:
                raise ValueError('短すぎる辺')
            if c.kind != 'LINE' and c.radius <= EPS:
                raise ValueError('小さすぎる円')
            if c.kind == 'ARC':
                if not 0 < abs(c.sweep) < TAU or distance(c.point(0), c.start) > EPS or distance(c.point(1), c.end) > EPS:
                    raise ValueError('不正な円弧')
            if c.kind != 'CIRCLE' and distance(c.end, loop.curves[(i+1) % len(loop.curves)].start) > EPS:
                raise ValueError('開いた輪郭')
            all_curves.append((li, i, c))
    for ai, (li, i, a) in enumerate(all_curves):
        for lj, j, b in all_curves[ai+1:]:
            hits = intersections(a, b)
            if hits is None:
                raise ValueError('重複する輪郭')
            allowed = []
            if li == lj:
                n = len(part.loops[li].curves)
                if (i+1) % n == j:
                    allowed.append(a.end)
                if (j+1) % n == i:
                    allowed.append(b.end)
            if any(not any(distance(p, q) <= EPS for q in allowed) for p in hits):
                raise ValueError('輪郭の自己交差・接触があります')


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


# 保存先と同じフォルダに一時ファイルを作り、検証後に本来の名前へ置き換える。
# 途中で失敗した場合は既存の出力を維持し、自分の一時ファイルだけを片付ける。
# 現実装の出力バックアップ名は「(バックアップ)」方式。今回のコメント追加では動作を変更しない。
def safe_write(path, text, validator=None):
    path = Path(path)
    if not path.parent.is_dir():
        raise OSError('保存先フォルダがありません')
    # Windows tempfile may retry permission failures many times. Fail immediately
    # on access errors while retaining exclusive creation and same-volume replace.
    tmp = str(path.parent/('.mdf_'+uuid.uuid4().hex+'.tmp'))
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8', newline='\n') as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        if validator:
            validator(Path(tmp).read_text(encoding='utf-8'))
        if path.exists():
            backup = path.with_name(path.stem+'(バックアップ)'+path.suffix)
            shutil.copy2(path, backup)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)
