"""Render a contact sheet of poses from a (patched) ROM for visual checks."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import smw_player as P
from PIL import Image, ImageDraw

POSES = [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 0x0B, 0x0D, 0x0F, 0x24, 0x25, 0x3C]


def preview(rom_path, out_path, poses=POSES, scale=2):
    pl = P.Player(open(rom_path, "rb").read())
    cell = 64
    sheet = Image.new("RGBA", (len(poses) * cell, 2 * cell), (90, 140, 200, 255))
    d = ImageDraw.Draw(sheet)
    for row, pu in enumerate((1, 0)):
        for i, p in enumerate(poses):
            im = P.render_pose(pl, p, pu).crop((10, 4, 58, 60)).resize((48, 56))
            sheet.alpha_composite(im, (i * cell, row * cell))
            d.text((i * cell + 2, row * cell + 2), f"{p:02X}", fill=(255, 255, 255, 255))
    sheet.resize((sheet.width * scale, sheet.height * scale), Image.NEAREST).save(out_path)


if __name__ == "__main__":
    preview(sys.argv[1], sys.argv[2])
