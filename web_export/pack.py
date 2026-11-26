"""Packs the network export into network.bin.gz, the compact binary the Bikeable Radius page loads.

The layout is documented in network_format.js (the browser decoder, which ships next to the data). In short: a "NYCN"
header and a JSON metadata block (every non-column field of the export: multipliers, subs, sub_colors, sub_widths,
names, legend, ...), then the columns as LEB128 varints, delta/zigzag encoded, all gzipped.

pack() decodes what it wrote with decode() below, a line-for-line Python copy of the browser decoder, and checks that
every value comes back bit-identical, so a successful run means the page sees exactly the export.
"""
import json
import math
import struct
import zlib

MAGIC = b'NYCN'
VERSION = 1
COLUMNS = ('nf', 'nt', 'wf', 'wr', 'name', 'sub', 'coords')


def js_json(value):
    """JSON text exactly as JavaScript's JSON.stringify writes it (whole-number floats as 1, not 1.0), so the metadata
    block is the same no matter which language wrote it"""
    def norm(v):
        if isinstance(v, float):
            if not math.isfinite(v):
                raise ValueError(f'non-finite number in metadata: {v}')
            return int(v) if v.is_integer() and abs(v) < 1e21 else v
        if isinstance(v, dict):
            return {str(k): norm(x) for k, x in v.items()}
        if isinstance(v, (list, tuple)):
            return [norm(x) for x in v]
        return v
    return json.dumps(norm(value), separators=(',', ':'), ensure_ascii=False, allow_nan=False)


def _js_round(x):
    r = math.floor(x)
    return r + 1 if x - r >= 0.5 else r


def encode(export):
    """the export dict -> uncompressed bytes"""
    n = len(export['nf'])
    for k in COLUMNS:
        if k not in export or len(export[k]) != n:
            raise ValueError(f'column {k} missing or not {n} long')
    meta = {k: v for k, v in export.items() if k not in COLUMNS}

    out = bytearray()

    def uv(v):
        if not isinstance(v, int) or v < 0 or v >= 2 ** 31:
            raise ValueError(f'varint out of range: {v!r}')
        while v >= 128:
            out.append((v & 127) | 128)
            v >>= 7
        out.append(v)

    def sv(v):
        uv(-2 * v - 1 if v < 0 else 2 * v)

    def tenths(w, i):
        if w is None:
            return 0
        k = _js_round(w * 10)
        if k / 10 != w or k < 0:
            raise ValueError(f'weight {w} (segment {i}) is not a non-negative one-decimal number')
        return k + 1

    def fixed5(x):
        k = _js_round(x * 1e5)
        if k / 1e5 != x:
            raise ValueError(f'coordinate {x} has more than 5 decimals')
        return k

    nf, nt = export['nf'], export['nt']
    prev = 0
    for v in nf:
        sv(v - prev)
        prev = v
    for i, v in enumerate(nt):
        sv(v - nf[i])
    for i, w in enumerate(export['wf']):
        uv(tenths(w, i))
    for i, w in enumerate(export['wr']):
        uv(tenths(w, i))
    for v in export['name']:
        uv(v)
    for v in export['sub']:
        uv(v)
    for i, c in enumerate(export['coords']):
        if len(c) % 2:
            raise ValueError(f'segment {i} has an odd coordinate count')
        uv(len(c) // 2)
    sx = sy = 0
    for c in export['coords']:
        px, py = sx, sy
        for k in range(0, len(c), 2):
            x, y = fixed5(c[k]), fixed5(c[k + 1])
            sv(x - px); sv(y - py)
            px, py = x, y
            if k == 0:
                sx, sy = x, y

    meta_bytes = js_json(meta).encode('utf-8')
    return MAGIC + bytes([VERSION]) + struct.pack('<II', n, len(meta_bytes)) + meta_bytes + bytes(out)


def decode(raw):
    """uncompressed bytes -> {**meta, nf, nt, wf, wr (inf = can't travel), name, sub, coff, xy} (as network_format.js)"""
    if raw[:4] != MAGIC:
        raise ValueError('network data: bad magic')
    if raw[4] != VERSION:
        raise ValueError(f'network data: unsupported version {raw[4]}')
    n, meta_len = struct.unpack_from('<II', raw, 5)
    meta = json.loads(raw[13:13 + meta_len].decode('utf-8'))
    p = 13 + meta_len

    def uv():
        nonlocal p
        v, m = 0, 1
        while True:
            b = raw[p]
            p += 1
            v += (b & 127) * m
            m *= 128
            if not b & 128:
                return v

    def sv():
        u = uv()
        return -(u + 1) // 2 if u & 1 else u // 2

    nf, prev = [], 0
    for _ in range(n):
        prev += sv()
        nf.append(prev)
    nt = [nf[i] + sv() for i in range(n)]
    wf = [math.inf if w == 0 else (w - 1) / 10 for w in (uv() for _ in range(n))]
    wr = [math.inf if w == 0 else (w - 1) / 10 for w in (uv() for _ in range(n))]
    name = [uv() for _ in range(n)]
    sub = [uv() for _ in range(n)]
    coff = [0]
    for _ in range(n):
        coff.append(coff[-1] + 2 * uv())
    xy = [0.0] * coff[n]
    sx = sy = 0
    for i in range(n):
        x, y = sx, sy
        for k in range(coff[i], coff[i + 1], 2):
            x += sv()
            y += sv()
            xy[k], xy[k + 1] = x / 1e5, y / 1e5
            if k == coff[i]:
                sx, sy = x, y
    if p != len(raw):
        raise ValueError(f'network data: {len(raw) - p} trailing bytes')
    meta.update(nf=nf, nt=nt, wf=wf, wr=wr, name=name, sub=sub, coff=coff, xy=xy)
    return meta


def verify(export, raw):
    """decode raw and compare every value with the export; raises on the first difference"""
    dec = decode(raw)
    meta = {k: v for k, v in export.items() if k not in COLUMNS}
    if js_json({k: dec.get(k) for k in meta}) != js_json(meta):
        raise AssertionError('metadata differs after decoding')
    for i in range(len(export['nf'])):
        if dec['nf'][i] != export['nf'][i] or dec['nt'][i] != export['nt'][i]:
            raise AssertionError(f'node ids differ at {i}')
        for col in ('wf', 'wr'):
            w = export[col][i]
            if dec[col][i] != (math.inf if w is None else w):
                raise AssertionError(f'{col} differs at {i}')
        if dec['name'][i] != export['name'][i] or dec['sub'][i] != export['sub'][i]:
            raise AssertionError(f'name/sub differs at {i}')
        c, s = export['coords'][i], dec['coff'][i]
        if dec['coff'][i + 1] - s != len(c):
            raise AssertionError(f'point count differs at {i}')
        for k, v in enumerate(c):
            if dec['xy'][s + k] != v:
                raise AssertionError(f'coordinate differs at segment {i}, value {k}')
    return dec


def pack(export):
    """the export dict -> (gzipped bytes, uncompressed size). verifies the round trip before returning"""
    raw = encode(export)
    verify(export, raw)
    gz = zlib.compressobj(9, zlib.DEFLATED, 31)   # wbits 31 = gzip framing; zlib writes mtime 0, so output is stable
    return gz.compress(raw) + gz.flush(), len(raw)
