"""LZ2 encoder compatible with SMW's decompressor (see lz2_ref.py).

Commands: 0 direct copy, 1 byte fill, 2 word fill, 3 incrementing fill,
4 back-reference into the output (absolute 16-bit offset, high byte first).
Length 1..32 uses a 1-byte header, 33..1024 the extended 2-byte header.
Optimal parse by dynamic programming over those commands.
"""
from collections import defaultdict


def _hdr(length):
    return 1 if length <= 32 else 2


def _emit_hdr(out, cmd, length):
    if length <= 32:
        out.append((cmd << 5) | (length - 1))
    else:
        n = length - 1
        out.append(0xE0 | (cmd << 2) | (n >> 8))
        out.append(n & 0xFF)


def encode(data: bytes) -> bytes:
    n = len(data)
    INF = 1 << 60
    cost = [INF] * (n + 1)
    choice = [None] * (n + 1)
    cost[n] = 0
    # hash of 3-byte prefixes -> earlier positions
    index = defaultdict(list)
    cands = [None] * n
    for i in range(n):
        best = []
        if i + 3 <= n:
            key = data[i:i + 3]
            seen = 0
            for j in reversed(index[key]):
                if j > 0xFFFF:
                    continue
                m = 0
                while i + m < n and m < 1024 and data[j + m] == data[i + m]:
                    m += 1
                best.append((m, j))
                seen += 1
                if seen >= 48:
                    break
            index[key].append(i)
        best.sort(reverse=True)
        cands[i] = best[:3]
    for i in range(n - 1, -1, -1):
        c = INF
        ch = None
        # direct copy
        for L in list(range(1, min(32, n - i) + 1)) + [min(1024, n - i)]:
            v = _hdr(L) + L + cost[i + L]
            if v < c:
                c, ch = v, ("d", L)
        for L in range(33, min(1024, n - i) + 1, 1):
            v = 2 + L + cost[i + L]
            if v < c:
                c, ch = v, ("d", L)
        # byte fill
        r = 1
        while i + r < n and r < 1024 and data[i + r] == data[i]:
            r += 1
        for L in {r, min(r, 32)} | set(range(max(2, r - 3), r + 1)):
            if L >= 2:
                v = _hdr(L) + 1 + cost[i + L]
                if v < c:
                    c, ch = v, ("b", L)
        # word fill
        if i + 1 < n:
            r = 2
            while i + r < n and r < 1024 and data[i + r] == data[i + (r & 1)]:
                r += 1
            for L in {r, min(r, 32)}:
                if L >= 3:
                    v = _hdr(L) + 2 + cost[i + L]
                    if v < c:
                        c, ch = v, ("w", L)
        # incrementing fill
        r = 1
        while i + r < n and r < 1024 and data[i + r] == (data[i] + r) & 0xFF:
            r += 1
        for L in {r, min(r, 32)}:
            if L >= 3:
                v = _hdr(L) + 1 + cost[i + L]
                if v < c:
                    c, ch = v, ("i", L)
        # back-reference
        for m, j in cands[i]:
            if m < 3:
                continue
            for L in {m, min(m, 32), max(3, m - 1), max(3, m - 2)}:
                if 3 <= L <= m:
                    v = _hdr(L) + 2 + cost[i + L]
                    if v < c:
                        c, ch = v, ("r", L, j)
        cost[i], choice[i] = c, ch
    out = bytearray()
    i = 0
    while i < n:
        ch = choice[i]
        kind, L = ch[0], ch[1]
        if kind == "d":
            _emit_hdr(out, 0, L)
            out += data[i:i + L]
        elif kind == "b":
            _emit_hdr(out, 1, L)
            out.append(data[i])
        elif kind == "w":
            _emit_hdr(out, 2, L)
            out += bytes((data[i], data[i + 1]))
        elif kind == "i":
            _emit_hdr(out, 3, L)
            out.append(data[i])
        else:
            _emit_hdr(out, 4, L)
            out += bytes((ch[2] >> 8, ch[2] & 0xFF))
        i += L
    out.append(0xFF)
    return bytes(out)
