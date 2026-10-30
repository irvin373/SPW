"""Slice the Peach (Mario Worlds Delta, by WizToad and GatetcVerde) sheet into frames."""
import collections
import json
import sys
from PIL import Image

# (name, y0, y1) row bands that hold sprites on the supplied sheet
BANDS = {"small1": (14, 42), "small2": (44, 74), "big1": (120, 160), "big2": (165, 205),
         "big3": (210, 252), "big4": (256, 306)}


def components(im, y0, y1, bg):
    px = im.load()
    W = im.width
    seen = set()
    boxes = []
    for y in range(y0, y1):
        for x in range(W):
            if (x, y) in seen or px[x, y][:3] == bg:
                continue
            q = collections.deque([(x, y)]); seen.add((x, y))
            mnx = mxx = x; mny = mxy = y; n = 0
            while q:
                cx, cy = q.popleft(); n += 1
                mnx = min(mnx, cx); mxx = max(mxx, cx); mny = min(mny, cy); mxy = max(mxy, cy)
                for dx in range(-2, 3):
                    for dy in range(-2, 3):
                        nx, ny = cx + dx, cy + dy
                        if y0 <= ny < y1 and 0 <= nx < W and (nx, ny) not in seen and px[nx, ny][:3] != bg:
                            seen.add((nx, ny)); q.append((nx, ny))
            if n > 60:
                boxes.append((mnx, mny, mxx + 1, mxy + 1))
    return sorted(boxes)


def slice_sheet(path):
    im = Image.open(path).convert("RGBA")
    bg = im.getpixel((2, 2))[:3]
    frames = []
    for band, (y0, y1) in BANDS.items():
        for i, box in enumerate(components(im, y0, y1, bg)):
            frames.append({"name": f"{band}_{i:02d}", "box": box})
    return im, bg, frames


if __name__ == "__main__":
    im, bg, frames = slice_sheet(sys.argv[1])
    print(len(frames), "frames; bg", bg)
    json.dump(frames, open(sys.argv[2], "w"), indent=1)
