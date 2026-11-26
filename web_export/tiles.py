"""Vector tiles for the Bikeable Radius map's bike network layer.

The page draws the street network from pre-built Mapbox Vector Tiles ({z}/{x}/{y}.pbf), so phones only fetch and parse
the streets in view instead of the whole ~180k-segment network.

The tiling below is a line-only Python port of geojson-vt 3.2.1 (https://github.com/mapbox/geojson-vt, ISC license),
and the encoding is a port of vt-pbf 3.1.3 (https://github.com/mapbox/vt-pbf, MIT license). geojson-vt is what MapLibre
itself uses to tile a GeoJSON source in the browser, so these are the tiles MapLibre would have made, just made ahead of
time. The port follows the JS step by step (same float operations in the same order, same rounding), so it produces the
same bytes as the JS libraries.

One deliberate step before tiling: connected segments of the same bike class are merged into longer lines (merge_class).
Every separate line gets two round end caps when drawn, and at city-wide zooms the overlapping caps of ~180k tiny
segments doubled up their anti-aliased edges and made lines look bolder than their set widths. Merging also gives 7.5x
fewer lines and 2.8x less tile data. Pass merge=False to keep every segment separate.
"""
import math
import os

LAYER = 'net'          # source-layer name the page's net-* layers use
MAXZOOM = 15
TILE_SIZE = 512        # MapLibre tile size in px
EXTENT = 8192
SCALE = EXTENT // TILE_SIZE
TOLERANCE = 0.5 * SCALE   # geojson-vt options MapLibre derives from source settings: tolerance 0.5 px, buffer 32 px
BUFFER = 32 * SCALE
INDEX_MAX_ZOOM = 5        # geojson-vt defaults
INDEX_MAX_POINTS = 100000

INF = math.inf


def js_round(x):
    """JavaScript Math.round: round half up (towards +infinity)."""
    r = math.floor(x)
    return r + 1 if x - r >= 0.5 else r


def v8_hypot(a, b):
    """Math.hypot exactly as V8 computes it (scale by the max, Kahan-summed squares), so the merge picks the same pairs."""
    a, b = abs(a), abs(b)
    m = max(a, b)
    if m == 0:
        return 0.0
    s = comp = 0.0
    for v in (a, b):
        n = v / m
        summand = n * n - comp
        prelim = s + summand
        comp = (prelim - s) - summand
        s = prelim
    return math.sqrt(s) * m


# ---------------------------------------------------------------------------------------------------------------------
# merge connected same-class segments into longer lines
# ---------------------------------------------------------------------------------------------------------------------
def merge_class(segs, nf, nt, coords):
    """at every node, pair up the segment ends of this class, straightest continuation first, then walk the pairs into
    chains. segs: segment indices; coords[i]: flat [lon, lat, lon, lat, ...]. returns a list of [[lon, lat], ...] lines"""
    def dir_away(i, side):   # unit vector from the node into the segment
        c = coords[i]
        if side == 0:
            x0, y0, x1, y1 = c[0], c[1], c[2], c[3]
        else:
            x0, y0, x1, y1 = c[-2], c[-1], c[-4], c[-3]
        dx, dy = x1 - x0, y1 - y0
        L = v8_hypot(dx, dy) or 1
        return (dx / L, dy / L)

    by_node = {}
    for i in segs:
        for side in (0, 1):
            node = nf[i] if side == 0 else nt[i]
            by_node.setdefault(node, []).append((2 * i + side, dir_away(i, side)))

    partner = {}   # end id (2*seg + side) -> paired end id; side 0 = from-node end (first point), 1 = to-node end
    for ends in by_node.values():
        while len(ends) >= 2:
            best, ba, bb = INF, 0, 1
            for a in range(len(ends)):
                ida, (dax, day) = ends[a]
                for b in range(a + 1, len(ends)):
                    idb, (dbx, dby) = ends[b]
                    if ida >> 1 == idb >> 1:
                        continue   # don't join a segment to itself
                    dot = dax * dbx + day * dby   # -1 = straight through
                    if dot < best:
                        best, ba, bb = dot, a, b
            if best == INF:
                break
            partner[ends[ba][0]] = ends[bb][0]
            partner[ends[bb][0]] = ends[ba][0]
            del ends[bb]
            del ends[ba]

    used = set()

    def walk(end):   # enter segment end>>1 at side end&1 and follow the pairing
        line = []
        while end is not None and (end >> 1) not in used:
            i = end >> 1
            used.add(i)
            c = coords[i]
            pts = [[c[k], c[k + 1]] for k in range(0, len(c), 2)]
            if end & 1:
                pts.reverse()
            if line and line[-1][0] == pts[0][0] and line[-1][1] == pts[0][1]:
                pts = pts[1:]   # shared node: don't repeat the point
            line.extend(pts)
            end = partner.get(end ^ 1)   # leave through the other end into whatever it's paired with
        return line

    lines = []
    for i in segs:
        for side in (0, 1):
            if i not in used and (2 * i + side) not in partner:
                lines.append(walk(2 * i + side))
    for i in segs:
        if i not in used:
            lines.append(walk(2 * i))   # what's left is closed loops
    return lines


def network_features(sub, nf, nt, coords, n_classes, merge=True):
    """one MultiLineString feature per bike class, properties {k: class index}. returns (features, number of lines)"""
    by_sub = [[] for _ in range(n_classes)]
    for i, k in enumerate(sub):
        if len(coords[i]) >= 4:   # same "drawable" rule the page uses: 2+ points
            by_sub[k].append(i)
    features, n_lines = [], 0
    for k, segs in enumerate(by_sub):
        if not segs:
            continue
        if merge:
            lines = merge_class(segs, nf, nt, coords)
        else:
            lines = [[[coords[i][j], coords[i][j + 1]] for j in range(0, len(coords[i]), 2)] for i in segs]
        n_lines += len(lines)
        features.append(({'k': k}, lines))
    return features, n_lines


# ---------------------------------------------------------------------------------------------------------------------
# geojson-vt (lines only)
# ---------------------------------------------------------------------------------------------------------------------
class Line(list):
    """flat [x, y, importance, x, y, importance, ...] in projected 0..1 space, plus the length of the original line"""
    __slots__ = ('size',)


class Feature:
    __slots__ = ('type', 'geometry', 'tags', 'min_x', 'min_y', 'max_x', 'max_y')

    def __init__(self, type_, geometry, tags):   # createFeature (id is always null here)
        self.type, self.geometry, self.tags = type_, geometry, tags
        min_x = min_y = INF
        max_x = max_y = -INF
        for g in (geometry if type_ == 'MultiLineString' else (geometry,)):
            for j in range(0, len(g), 3):
                x, y = g[j], g[j + 1]
                if x < min_x: min_x = x
                if y < min_y: min_y = y
                if x > max_x: max_x = x
                if y > max_y: max_y = y
        self.min_x, self.min_y, self.max_x, self.max_y = min_x, min_y, max_x, max_y


def project_x(x):
    return x / 360 + 0.5


def project_y(y):
    s = math.sin(y * math.pi / 180)
    y2 = 0.5 - 0.25 * math.log((1 + s) / (1 - s)) / math.pi
    return 0 if y2 < 0 else 1 if y2 > 1 else y2


def simplify(coords, first, last, sq_tolerance):
    """Douglas-Peucker importance per point (stored at index + 2). geojson-vt recurses; the halves are independent, so an
    explicit stack gives the same result without Python's recursion limit"""
    stack = [(first, last)]
    while stack:
        first, last = stack.pop()
        max_sq_dist = sq_tolerance
        mid = (last - first) >> 1
        min_pos_to_mid = last - first
        index = None
        ax, ay, bx, by = coords[first], coords[first + 1], coords[last], coords[last + 1]
        dx, dy = bx - ax, by - ay
        nonzero = dx != 0 or dy != 0
        len2 = dx * dx + dy * dy
        for i in range(first + 3, last, 3):
            px, py = coords[i], coords[i + 1]
            x, y = ax, ay
            if nonzero:   # getSqSegDist
                t = ((px - x) * dx + (py - y) * dy) / len2
                if t > 1:
                    x, y = bx, by
                elif t > 0:
                    x += dx * t
                    y += dy * t
            ex, ey = px - x, py - y
            d = ex * ex + ey * ey
            if d > max_sq_dist:
                index = i
                max_sq_dist = d
            elif d == max_sq_dist:   # prefer a pivot near the middle (geojson-vt issue #104)
                pos_to_mid = abs(i - mid)
                if pos_to_mid < min_pos_to_mid:
                    index = i
                    min_pos_to_mid = pos_to_mid
        if max_sq_dist > sq_tolerance:
            coords[index + 2] = max_sq_dist
            if last - index > 3: stack.append((index, last))
            if index - first > 3: stack.append((first, index))


def convert_line(ring, tolerance):
    out = Line()
    size = 0
    x0 = y0 = 0.0
    for j, (lon, lat) in enumerate(ring):
        x, y = project_x(lon), project_y(lat)
        out.append(x); out.append(y); out.append(0)
        if j > 0:
            size += math.sqrt((x - x0) ** 2 + (y - y0) ** 2)
        x0, y0 = x, y
    last = len(out) - 3
    out[2] = 1
    simplify(out, 0, last, tolerance)
    out[last + 2] = 1
    out.size = abs(size)
    return out


def convert(features):
    tolerance = (TOLERANCE / ((1 << MAXZOOM) * EXTENT)) ** 2
    return [Feature('MultiLineString', [convert_line(line, tolerance) for line in lines], tags) for tags, lines in features]


def _new_slice(line):
    s = Line()
    s.size = line.size
    return s


def clip_line(geom, new_geom, k1, k2, axis):
    sl = _new_slice(geom)
    n = len(geom)
    for i in range(0, n - 3, 3):
        ax, ay, az, bx, by = geom[i], geom[i + 1], geom[i + 2], geom[i + 3], geom[i + 4]
        a = ax if axis == 0 else ay
        b = bx if axis == 0 else by
        exited = False
        if a < k1:
            if b > k1:   # enters from the left
                _intersect(sl, ax, ay, bx, by, k1, axis)
        elif a > k2:
            if b < k2:   # enters from the right
                _intersect(sl, ax, ay, bx, by, k2, axis)
        else:
            sl.append(ax); sl.append(ay); sl.append(az)
        if b < k1 and a >= k1:   # exits on the left
            _intersect(sl, ax, ay, bx, by, k1, axis)
            exited = True
        if b > k2 and a <= k2:   # exits on the right
            _intersect(sl, ax, ay, bx, by, k2, axis)
            exited = True
        if exited:
            new_geom.append(sl)
            sl = _new_slice(geom)
    last = n - 3
    a = geom[last] if axis == 0 else geom[last + 1]
    if k1 <= a <= k2:
        sl.append(geom[last]); sl.append(geom[last + 1]); sl.append(geom[last + 2])
    if sl:
        new_geom.append(sl)


def _intersect(out, ax, ay, bx, by, v, axis):
    if axis == 0:
        t = (v - ax) / (bx - ax)
        out.append(v); out.append(ay + (by - ay) * t); out.append(1)
    else:
        t = (v - ay) / (by - ay)
        out.append(ax + (bx - ax) * t); out.append(v); out.append(1)


def clip(features, scale, k1, k2, axis, min_all, max_all):
    k1 /= scale
    k2 /= scale
    if min_all >= k1 and max_all < k2:
        return features   # trivial accept
    if max_all < k1 or min_all >= k2:
        return None       # trivial reject
    clipped = []
    for f in features:
        lo = f.min_x if axis == 0 else f.min_y
        hi = f.max_x if axis == 0 else f.max_y
        if lo >= k1 and hi < k2:
            clipped.append(f)
            continue
        if hi < k1 or lo >= k2:
            continue
        new_geom = []
        if f.type == 'LineString':
            clip_line(f.geometry, new_geom, k1, k2, axis)
        else:
            for g in f.geometry:
                clip_line(g, new_geom, k1, k2, axis)
        if new_geom:
            if len(new_geom) == 1:
                clipped.append(Feature('LineString', new_geom[0], f.tags))
            else:
                clipped.append(Feature('MultiLineString', new_geom, f.tags))
    return clipped or None


class Tile:
    __slots__ = ('features', 'num_points', 'source', 'x', 'y', 'z', 'transformed', 'min_x', 'min_y', 'max_x', 'max_y')


def create_tile(features, z, tx, ty):
    tolerance = 0 if z == MAXZOOM else TOLERANCE / ((1 << z) * EXTENT)
    sq_tolerance = tolerance * tolerance
    tile = Tile()
    tile.features, tile.num_points, tile.source = [], 0, None
    tile.x, tile.y, tile.z, tile.transformed = tx, ty, z, False
    tile.min_x, tile.min_y, tile.max_x, tile.max_y = 2, 1, -1, 0
    for f in features:
        simplified = []
        for g in ((f.geometry,) if f.type == 'LineString' else f.geometry):   # addLine
            if tolerance > 0 and g.size < tolerance:
                tile.num_points += len(g) // 3
                continue
            ring = []
            for i in range(0, len(g), 3):
                if tolerance == 0 or g[i + 2] > sq_tolerance:
                    ring.append(g[i]); ring.append(g[i + 1])
            tile.num_points += len(g) // 3
            simplified.append(ring)
        if simplified:
            tile.features.append((simplified, f.tags))
        if f.min_x < tile.min_x: tile.min_x = f.min_x
        if f.min_y < tile.min_y: tile.min_y = f.min_y
        if f.max_x > tile.max_x: tile.max_x = f.max_x
        if f.max_y > tile.max_y: tile.max_y = f.max_y
    return tile


def _to_id(z, x, y):
    return (((1 << z) * y + x) * 32) + z


class TileIndex:
    """geojson-vt's GeoJSONVT: tiles the top levels up front, then drills down on demand in get_tile"""

    def __init__(self, features):
        feats = convert(features)
        # geojson-vt's wrap() only changes features within a buffer of the antimeridian; NYC is nowhere near it
        b = BUFFER / EXTENT
        assert all(-b < f.min_x and f.max_x < 1 + b for f in feats), 'features cross the antimeridian'
        self.tiles = {}
        if feats:
            self.split_tile(feats, 0, 0, 0)

    def split_tile(self, features, z, x, y, cz=None, cx=None, cy=None):
        stack = [(features, z, x, y)]
        k1 = 0.5 * BUFFER / EXTENT
        k2, k3, k4 = 0.5 - k1, 0.5 + k1, 1 + k1
        while stack:
            features, z, x, y = stack.pop()
            z2 = 1 << z
            tid = _to_id(z, x, y)
            tile = self.tiles.get(tid)
            if tile is None:
                tile = self.tiles[tid] = create_tile(features, z, x, y)
            tile.source = features   # keep the source geometry so a later drill-down can start here
            if not cz:   # first-pass tiling (geojson-vt tests `!cz`, so a drill-down to z0 counts as first-pass too)
                if z == INDEX_MAX_ZOOM or tile.num_points <= INDEX_MAX_POINTS:
                    continue
            else:        # drill-down to a specific tile
                if z == MAXZOOM or z == cz:
                    continue
                m = 1 << (cz - z)
                if x != cx // m or y != cy // m:
                    continue   # not an ancestor of the target tile
            tile.source = None
            if not features:
                continue
            left = clip(features, z2, x - k1, x + k3, 0, tile.min_x, tile.max_x)
            right = clip(features, z2, x + k2, x + k4, 0, tile.min_x, tile.max_x)
            tl = bl = tr = br = None
            if left:
                tl = clip(left, z2, y - k1, y + k3, 1, tile.min_y, tile.max_y)
                bl = clip(left, z2, y + k2, y + k4, 1, tile.min_y, tile.max_y)
            if right:
                tr = clip(right, z2, y - k1, y + k3, 1, tile.min_y, tile.max_y)
                br = clip(right, z2, y + k2, y + k4, 1, tile.min_y, tile.max_y)
            stack.append((tl or [], z + 1, x * 2, y * 2))
            stack.append((bl or [], z + 1, x * 2, y * 2 + 1))
            stack.append((tr or [], z + 1, x * 2 + 1, y * 2))
            stack.append((br or [], z + 1, x * 2 + 1, y * 2 + 1))

    def get_tile(self, z, x, y):
        """the tile's features as ([ring of (x, y) ints in tile extent, ...], tags), or None if nothing is there"""
        z2 = 1 << z
        x = ((x % z2) + z2) % z2
        tid = _to_id(z, x, y)
        if tid not in self.tiles:
            z0, x0, y0, parent = z, x, y, None
            while parent is None and z0 > 0:
                z0 -= 1
                x0 //= 2
                y0 //= 2
                parent = self.tiles.get(_to_id(z0, x0, y0))
            if parent is None or parent.source is None:
                return None
            self.split_tile(parent.source, z0, x0, y0, z, x, y)
            if tid not in self.tiles:
                return None
        return _transform(self.tiles[tid])


def _transform(tile):
    if not tile.transformed:
        z2, tx, ty = 1 << tile.z, tile.x, tile.y
        tile.features = [([[(js_round(EXTENT * (r[k] * z2 - tx)), js_round(EXTENT * (r[k + 1] * z2 - ty)))
                            for k in range(0, len(r), 2)] for r in rings], tags) for rings, tags in tile.features]
        tile.transformed = True
    return tile


# ---------------------------------------------------------------------------------------------------------------------
# vt-pbf encoding (layer 'net', version 2, line features, integer properties)
# ---------------------------------------------------------------------------------------------------------------------
def _varint(out, v):
    if v < 0:
        raise ValueError(f'negative varint {v}')
    while v >= 0x80:
        out.append((v & 0x7f) | 0x80)
        v >>= 7
    out.append(v)


def _bytes_field(out, tag, payload):
    _varint(out, (tag << 3) | 2)
    _varint(out, len(payload))
    out += payload


def _zigzag(n):
    return (n << 1) ^ (n >> 31)


def encode_tile(features):
    """features: [(rings, tags)] from TileIndex.get_tile. returns the .pbf bytes"""
    layer = bytearray()
    _varint(layer, (15 << 3) | 0); _varint(layer, 2)        # version
    _bytes_field(layer, 1, LAYER.encode('utf-8'))           # name
    _varint(layer, (5 << 3) | 0); _varint(layer, EXTENT)    # extent
    keys, values, keycache, valuecache = [], [], {}, {}
    for rings, tags in features:
        props = bytearray()
        for key, value in tags.items():
            if value is None:
                continue
            if key not in keycache:
                keycache[key] = len(keys)
                keys.append(key)
            _varint(props, keycache[key])
            if not (isinstance(value, int) and not isinstance(value, bool) and value >= 0):
                raise TypeError(f'only non-negative integer properties are supported, got {key}={value!r}')
            if value not in valuecache:
                valuecache[value] = len(values)
                values.append(value)
            _varint(props, valuecache[value])
        geom = bytearray()
        x = y = 0
        for ring in rings:
            _varint(geom, (1 << 3) + 1)   # moveto, 1 point
            n = len(ring)
            for i, (px, py) in enumerate(ring):
                if i == 1:
                    _varint(geom, ((n - 1) << 3) + 2)   # lineto, n - 1 points
                _varint(geom, _zigzag(px - x))
                _varint(geom, _zigzag(py - y))
                x, y = px, py
        feat = bytearray()
        _bytes_field(feat, 2, props)                        # tags
        _varint(feat, (3 << 3) | 0); _varint(feat, 2)      # type: LineString
        _bytes_field(feat, 4, geom)                         # geometry
        _bytes_field(layer, 2, feat)
    for key in keys:
        _bytes_field(layer, 3, key.encode('utf-8'))
    for value in values:
        v = bytearray()
        _varint(v, (5 << 3) | 0); _varint(v, value)        # uint_value
        _bytes_field(layer, 4, v)
    tile = bytearray()
    _bytes_field(tile, 3, layer)
    return bytes(tile)


def write_tiles(features, out_dir):
    """tile `features` ([(tags, [[[lon, lat], ...], ...])]) and write {z}/{x}/{y}.pbf under out_dir.
    tiles with nothing to draw are not written (the page's host serves an empty tile for those).
    returns (number of tiles, total bytes)"""
    index = TileIndex(features)
    n_tiles = n_bytes = 0

    def visit(z, x, y):
        nonlocal n_tiles, n_bytes
        tile = index.get_tile(z, x, y)
        if tile is None:
            return   # no streets anywhere in this tile (or below it)
        # a tile can exist with nothing left to draw: at low zooms short lines are simplified away. its children can
        # still have streets, so keep descending; just don't write an empty file
        if tile.features:
            buf = encode_tile(tile.features)
            d = os.path.join(out_dir, str(z), str(x))
            os.makedirs(d, exist_ok=True)
            with open(os.path.join(d, f'{y}.pbf'), 'wb') as f:
                f.write(buf)
            n_tiles += 1
            n_bytes += len(buf)
        if z < MAXZOOM:
            for dx, dy in ((0, 0), (1, 0), (0, 1), (1, 1)):
                visit(z + 1, 2 * x + dx, 2 * y + dy)

    visit(0, 0, 0)
    return n_tiles, n_bytes
