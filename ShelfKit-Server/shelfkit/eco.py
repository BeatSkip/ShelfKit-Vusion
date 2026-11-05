"""ECO image compression for the tag's e-paper planes.

Implements the ECO scheme of Kim, Kim & Cho, "Image Compression Using Chain Coding for
Electronic Shelf Labels (ESL) Systems", IEEE Access 9 (2021) 8497-8508
(Documentation/ECO-ESL-ImageCompression.pdf):

  1. binary move-to-front transform: a pixel becomes 1 where ink starts or stops
     (raster order), so solid areas turn into their outlines;
  2. downward-direction chain code (Algorithm 2): every 1 starts a chain that walks
     down (0), down-left (1) or down-right (2);
  3. the chain table is transformed: Δi between chain starts, item types
     A (no code), B (same code as an earlier item, Δn back), C (own code, Length);
  4. bitstream: α-sized VarInts (bijective base 2^α, Fig. 7 / Table 4), type codes
     (Table 2), and the concatenated C codes with the context code of Table 8,
     runs of more than Rmin = α + 3 zeros abbreviated as R + VarInt(run - Rmin).

Every plane is sent as its own monochrome ECO file (palette size 1): the tag then
needs to hold only one plane's compressed data at a time, and the black/white and
red planes need not be mutually exclusive.

Two limits of this implementation, both decided by the tag's 8 KB of XRAM:
  * a B item refers back at most RING items (the tag keeps a ring of that size);
  * the tag rebuilds the plane in bands of BAND_BYTES and re-runs the decoder per
    band, so it never holds the 5624-byte plane - see eco_rx.c.
decode() below follows the tag's algorithm exactly, so a round trip here is a test of
what the tag will do with the same bytes.
"""

from __future__ import annotations

W, H = 152, 296                 # the panel's RAM layout: 19 bytes per row, MSB first
PLANE_BYTES = W * H // 8        # 5624
RING = 32                       # B look-back, = ECO_RING in eco_rx.c
BAND_BYTES = 760                # = ECO_BAND_BYTES in eco_rx.c (40 rows)

_TYPE_ORDER = "ABC"


# ── bit I/O ──────────────────────────────────────────────────────────────────

class _BitWriter:
    def __init__(self) -> None:
        self.bits: list[int] = []

    def put(self, value: int, n: int) -> None:
        for k in range(n - 1, -1, -1):
            self.bits.append((value >> k) & 1)

    def code(self, s: str) -> None:
        self.bits.extend(1 if c == "1" else 0 for c in s)

    def varint(self, value: int, alpha: int) -> None:
        if value < 1:
            raise ValueError("ECO VarInts are 1 or more")
        base = 1 << alpha
        digits = []
        while value > 0:
            d = (value - 1) % base + 1
            digits.append(d)
            value = (value - d) // base
        for i, d in enumerate(reversed(digits)):
            self.bits.append(1 if i == len(digits) - 1 else 0)
            self.put(d - 1, alpha)

    def tobytes(self) -> bytes:
        bits = self.bits + [0] * (-len(self.bits) % 8)
        return bytes(int("".join(map(str, bits[i:i + 8])), 2) for i in range(0, len(bits), 8))


class _BitReader:
    def __init__(self, data: bytes, pos: int = 0) -> None:
        self.data, self.pos = data, pos

    def bit(self) -> int:
        byte = self.data[self.pos >> 3]       # IndexError = truncated stream
        b = (byte >> (7 - (self.pos & 7))) & 1
        self.pos += 1
        return b

    def get(self, n: int) -> int:
        v = 0
        for _ in range(n):
            v = (v << 1) | self.bit()
        return v

    def varint(self, alpha: int) -> int:
        v = 0
        while True:
            last = self.bit()
            v = (v << alpha) + self.get(alpha) + 1
            if last:
                return v


# ── compression ──────────────────────────────────────────────────────────────

def _membership(plane: bytes) -> list[int]:
    """1 = ink. The panel's planes use 0 = ink (black in BW, red in RED)."""
    out = []
    for byte in plane:
        for k in range(7, -1, -1):
            out.append(0 if (byte >> k) & 1 else 1)
    return out


def _mtf(m: list[int]) -> list[int]:
    prev, out = 0, []
    for v in m:
        out.append(v ^ prev)
        prev = v
    return out


def _chains(b: list[int]) -> list[tuple[int, str]]:
    """Algorithm 2, verbatim (index arithmetic included)."""
    b = list(b)
    n = len(b)
    table = []
    for i in range(n):
        if not b[i]:
            continue
        b[i] = 0
        code = []
        j = i
        while j < n:
            k = j + W
            if k < n and b[k]:
                b[k] = 0; code.append("0"); j = k
            elif k - 1 < n and b[k - 1]:
                b[k - 1] = 0; code.append("1"); j = k - 1
            elif k + 1 < n and b[k + 1]:
                b[k + 1] = 0; code.append("2"); j = k + 1
            else:
                break
        table.append((i, "".join(code)))
    return table


def _items(table):
    """Table 6/7: (type, Δi, Δn or Length or None) per chain, plus the C codes."""
    items, cc = [], []
    prev_i = None
    for n, (i, code) in enumerate(table):
        di = i + 1 if prev_i is None else i - prev_i
        prev_i = i
        if not code:
            items.append(("A", di, None))
            continue
        dn = next((d for d in range(1, min(RING, n) + 1) if table[n - d][1] == code), None)
        if dn is not None:
            items.append(("B", di, dn))
        else:
            items.append(("C", di, len(code)))
            cc.append(code)
    return items, "".join(cc)


def _type_codes(most: str) -> dict[str, str]:
    others = [t for t in _TYPE_ORDER if t != most]
    return {most: "0", others[0]: "10", others[1]: "11"}


def _encode_cc(w: _BitWriter, cc: str, alpha: int) -> None:
    """Table 8, with runs of more than Rmin zeros as R + VarInt(run - Rmin)."""
    rmin = alpha + 3
    prev = "other"
    i = 0
    while i < len(cc):
        s = cc[i]
        if s == "0" and prev == "other":
            run = len(cc) - i - len(cc[i:].lstrip("0"))
            if run > rmin:
                w.code("10")
                w.varint(run - rmin, alpha)
                prev = "R"
                i += run
                continue
        if prev == "0":
            w.code({"0": "0", "1": "10", "2": "11"}[s])
        elif prev == "R":
            w.code({"1": "0", "2": "1"}[s])      # a 0 cannot follow a maximal run
        else:
            w.code({"0": "0", "1": "110", "2": "111"}[s])
        prev = "0" if s == "0" else "other"
        i += 1


def _encode(items, cc: str, alpha: int) -> bytes:
    w = _BitWriter()
    w.put(alpha - 1, 2)                                  # Table 1
    w.varint(W, alpha)
    w.varint(H, alpha)
    counts = {t: sum(1 for it in items if it[0] == t) for t in _TYPE_ORDER}
    most = max(_TYPE_ORDER, key=lambda t: (counts[t], -_TYPE_ORDER.index(t)))
    w.code({"A": "0", "B": "10", "C": "11"}[most])       # Table 2
    w.varint(1, alpha)                                   # palette size: one colour
    w.varint(len(items) + 1, alpha)                      # table size + 1
    tc = _type_codes(most)
    for kind, di, extra in items:
        w.code(tc[kind])
        w.varint(di, alpha)
        if extra is not None:
            w.varint(extra, alpha)
    _encode_cc(w, cc, alpha)
    return w.tobytes()


def compress(plane: bytes) -> bytes:
    """One panel plane (PLANE_BYTES, 0 = ink) -> the smallest ECO file over α = 1..4."""
    if len(plane) != PLANE_BYTES:
        raise ValueError(f"a plane is {PLANE_BYTES} bytes, got {len(plane)}")
    items, cc = _items(_chains(_mtf(_membership(plane))))
    return min((_encode(items, cc, a) for a in (1, 2, 3, 4)), key=len)


# ── decompression: the tag's algorithm (eco_rx.c), kept line for line ─────────

class _CC:
    """Chain-code symbol reader with Table 8 context; state is copyable for B items."""

    def __init__(self, data, pos, alpha):
        self.r = _BitReader(data, pos)
        self.alpha, self.ctx, self.pending = alpha, "other", 0

    def state(self):
        return (self.r.pos, self.ctx, self.pending)

    def load(self, st):
        self.r.pos, self.ctx, self.pending = st

    def sym(self) -> int:
        if self.pending:
            self.pending -= 1
            return 0
        r = self.r
        if self.ctx == "R":
            s = 1 + r.bit()
        elif self.ctx == "0":
            s = 0 if not r.bit() else 1 + r.bit()
        else:
            if not r.bit():
                s = 0
            elif not r.bit():                            # "10" = R
                self.pending = r.varint(self.alpha) + self.alpha + 3 - 1
                self.ctx = "R"
                return 0
            else:
                s = 1 + r.bit()
        self.ctx = "0" if s == 0 else "other"
        return s


def _header(data: bytes):
    r = _BitReader(data)
    alpha = r.get(2) + 1
    if r.varint(alpha) != W or r.varint(alpha) != H:
        raise ValueError("not a 152x296 plane")
    most = "A" if not r.bit() else ("B" if not r.bit() else "C")
    if r.varint(alpha) != 1:
        raise ValueError("palette size must be 1")
    count = r.varint(alpha) - 1
    return alpha, most, count, r.pos


def _read_type(r, most):
    others = [t for t in _TYPE_ORDER if t != most]
    if not r.bit():
        return most
    return others[r.bit()]


def decode(data: bytes, band_bytes: int = BAND_BYTES) -> bytes:
    """ECO file -> panel plane (0 = ink), decoded band by band as the tag does."""
    alpha, most, count, items_pos = _header(data)
    # pre-pass: walk the item table once to find where the chain codes start
    r = _BitReader(data, items_pos)
    for _ in range(count):
        kind = _read_type(r, most)
        r.varint(alpha)
        if kind != "A":
            r.varint(alpha)
    cc_pos = r.pos

    out = bytearray()
    p = 0                                                # reverse-MTF state, carried
    total = W * H
    for band_start in range(0, total, band_bytes * 8):
        band_end = min(band_start + band_bytes * 8, total)
        band = [0] * (band_end - band_start)
        r = _BitReader(data, items_pos)
        cc = _CC(data, cc_pos, alpha)
        rep = _CC(data, cc_pos, alpha)
        ring = [None] * RING
        idx = -1
        for n in range(count):
            kind = _read_type(r, most)
            idx += r.varint(alpha)
            if idx >= band_end:
                break                                    # later chains start lower down
            if band_start <= idx:
                band[idx - band_start] = 1
            if kind == "A":
                ring[n % RING] = (None, 0)
                continue
            if kind == "B":
                st, length = ring[(n - r.varint(alpha)) % RING]
                ring[n % RING] = (st, length)
                rep.load(st)
                src = rep
            else:
                length = r.varint(alpha)
                ring[n % RING] = (cc.state(), length)
                src = cc
            c = idx
            for k in range(length):
                s = src.sym()
                c += W + (0, -1, 1)[s]
                if c >= band_end:
                    if src is cc:                        # the shared stream must stay in step
                        for _ in range(length - k - 1):
                            cc.sym()
                    break
                if c >= band_start:
                    band[c - band_start] = 1
        for i in range(0, len(band), 8):                 # reverse binary MTF, 0 = ink
            byte = 0
            for b in band[i:i + 8]:
                p ^= b
                byte = (byte << 1) | (p ^ 1)
            out.append(byte)
    return bytes(out)
