"""Offline model of SMW's player (Mario) sprite composition, from the US ROM.

Mirrors DrawMarioAndYoshi / CODE_00F636 (bank 00).  Used to find which tiles of
the decompressed GFX32 sheet make up each pose, and to render poses for checks.
"""
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import lz2_ref  # noqa: E402

# SNES (bank 00) labels from third_party/SMWDisX/SMW_U.sym
A_DCEC, A_DD32, A_DD4E, A_DE32 = 0xDCEC, 0xDD32, 0xDD4E, 0xDE32
A_E00C, A_E0CC = 0xE00C, 0xE0CC
A_TILE8, A_TILEEXP, A_TILESET = 0xDFDA, 0xDF1A, 0xDF16
A_PALPTR = 0xE2A2


def off(a):  # bank 00 LoROM -> file offset
    return a - 0x8000


class Player:
    def __init__(self, rom: bytes):
        self.rom = rom
        sheet, _ = lz2_ref.decompress(rom, 0x088000)
        self.sheet_len = len(sheet)  # exact decompressed size; GFX33 (Yoshi) follows at $7E:7D00
        self.sheet = sheet.ljust(0x8000, b"\0")

    def b(self, a, i=0):
        return self.rom[off(a) + i]

    def w(self, a, i=0):
        return struct.unpack_from("<h", self.rom, off(a) + i)[0]

    # -- composition -----------------------------------------------------
    def pose_tiles(self, pose, powerup, direction=1):
        """Return list of OAM pieces for a pose: dict(x,y,size,tile,flip,pieces).

        pieces = the dynamic 16x16 sheet pieces (A,B) selected for this pose."""
        x = pose
        if x == 0x29 and powerup == 0:
            x = 0x20
        y2 = self.b(A_DCEC, x) | direction
        s5 = self.b(A_DD32, y2)
        y = pose
        if pose < 0x3D:
            y = pose + self.b(A_TILESET, powerup)
        e6 = self.b(A_TILEEXP, y)
        pa, pb = self.b(A_E00C, y), self.b(A_E0CC, y)
        big = 0xE8 if pose == 0x43 else 0xC8
        out = []
        for k in range(4):
            t = self.b(A_TILE8, e6 + k)
            if t & 0x80:
                continue
            ox = self.w(A_DD4E, s5 + 2 * k)
            oy = self.w(A_DE32, s5 + 2 * k)
            large = (big >> (7 - k)) & 1
            out.append(dict(k=k, tile=t, x=ox, y=oy, large=large))
        return out, (pa, pb), (y, e6)

    @staticmethod
    def piece_base(v):
        """Sheet tile index of the 16x16 piece selected by table byte v."""
        row = (v >> 4) & 0xF
        col = v & 7
        half = (v >> 3) & 1
        return half * 512 + row * 32 + col * 2

    def vram_tile_source(self, tile, pieces):
        """Sheet tile index that VRAM sprite tile `tile` holds for this pose."""
        pa, pb = pieces
        a, b = self.piece_base(pa), self.piece_base(pb)
        slots = {0: a, 1: a + 1, 16: a + 16, 17: a + 17,
                 2: b, 3: b + 1, 18: b + 16, 19: b + 17}
        return slots.get(tile, tile)

    def tile_pixels(self, n):
        data = self.sheet
        o = n * 32
        px = [[0] * 8 for _ in range(8)]
        if o + 32 > len(data):
            return px
        for yy in range(8):
            b0, b1 = data[o + yy * 2], data[o + yy * 2 + 1]
            b2, b3 = data[o + 16 + yy * 2], data[o + 17 + yy * 2]
            for xx in range(8):
                bit = 7 - xx
                px[yy][xx] = ((b0 >> bit) & 1) | (((b1 >> bit) & 1) << 1) | \
                             (((b2 >> bit) & 1) << 2) | (((b3 >> bit) & 1) << 3)
        return px


# ---- rendering helpers -------------------------------------------------
def bgr555(v):
    return ((v & 31) * 255 // 31, ((v >> 5) & 31) * 255 // 31, ((v >> 10) & 31) * 255 // 31)


def mario_palette(rom, powerup, turn=0):
    """CGRAM sprite row 8, colours 6..15 from the pointer table at $00:E2A2."""
    y = ((powerup * 2) | turn) * 2
    ptr = struct.unpack_from("<H", rom, off(A_PALPTR) + y)[0]
    cols = [bgr555(struct.unpack_from("<H", rom, off(ptr) + 2 * i)[0]) for i in range(10)]
    return ptr, cols


def render_pose(pl, pose, powerup, direction=1, flip=None):
    from PIL import Image
    tiles, pieces, _ = pl.pose_tiles(pose, powerup, direction)
    _, cols = mario_palette(pl.rom, powerup)
    fixed = [(0, 0, 0), (248, 248, 248), (0, 0, 0), (200, 40, 40), (232, 176, 128), (248, 216, 0)]
    pal = fixed + cols
    W = H = 64
    ox, oy = 24, 8
    im = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    if flip is None:
        flip = direction == 1  # MarioPalIndex[1] = $40: hardware X-flip when facing right
    for t in tiles:
        n = 2 if t["large"] else 1
        for ty in range(n):
            for tx in range(n):
                src = pl.vram_tile_source(t["tile"] + tx + 16 * ty, pieces)
                px = pl.tile_pixels(src)
                for yy in range(8):
                    for xx in range(8):
                        v = px[yy][xx]
                        if v:
                            if flip:
                                X = ox + t["x"] + (n - 1 - tx) * 8 + (7 - xx)
                            else:
                                X = ox + t["x"] + tx * 8 + xx
                            Y = oy + t["y"] + ty * 8 + yy
                            if 0 <= X < W and 0 <= Y < H:
                                im.putpixel((X, Y), pal[v] + (255,))
    return im
