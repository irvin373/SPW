#!/usr/bin/env python3
"""Match every SMW player pose to the best Peach frame by silhouette, and report gaps.

Writes <out>/mapping.json, coverage_<big|small>.png (Mario reference | chosen Peach |
score) and missing_<big|small>.png (poses still needing a sprite).
Manual choices in build_peach.BIG / SMALL always win over automatic ones.
"""
import argparse
import json
import sys
from pathlib import Path

from PIL import Image, ImageDraw

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import build_peach as B  # noqa: E402
import smw_player as P  # noqa: E402

ACCEPT = 0.58
NORM = (24, 40)
LAST_POSE = 0x46


def mask(im):
    a = im.split()[3].point(lambda v: 255 if v else 0)
    box = a.getbbox()
    if not box:
        return None, 0
    crop = a.crop(box)
    return crop.resize(NORM, Image.NEAREST), crop.width / crop.height


def iou(m1, a1, m2, a2):
    p1, p2 = m1.load(), m2.load()
    inter = union = 0
    for y in range(NORM[1]):
        for x in range(NORM[0]):
            u, v = p1[x, y] > 0, p2[x, y] > 0
            inter += u and v
            union += u or v
    if not union:
        return 0.0
    return inter / union * (min(a1, a2) / max(a1, a2))


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--rom", required=True)
    ap.add_argument("--sheet", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    pl = P.Player(Path(a.rom).read_bytes())
    imgs = B.frame_images(a.sheet)
    pools = {1: {k: v for k, v in imgs.items() if k.startswith("big")},
             0: {k: v for k, v in imgs.items() if k.startswith("small") and k != "small1_00"}}
    pmask = {pu: {k: mask(v) for k, v in pool.items()} for pu, pool in pools.items()}
    manual = {1: dict(B.BIG), 0: dict(B.SMALL)}
    result = {}
    for pu, label in ((1, "big"), (0, "small")):
        rows = []
        for pose in range(LAST_POSE):
            ref = P.render_pose(pl, pose, pu, 1)
            rm, ra = mask(ref)
            if rm is None:
                rows.append(dict(pose=pose, status="blank"))
                continue
            best, score = None, 0.0
            for name, (m, asp) in pmask[pu].items():
                if m is None:
                    continue
                s = iou(rm, ra, m, asp)
                if s > score:
                    best, score = name, s
            if pose in manual[pu]:
                rows.append(dict(pose=pose, status="manual", frame=manual[pu][pose], score=round(score, 2)))
            elif score >= ACCEPT:
                rows.append(dict(pose=pose, status="auto", frame=best, score=round(score, 2)))
            else:
                rows.append(dict(pose=pose, status="missing", frame=best, score=round(score, 2)))
        result[label] = rows
        # contact sheets
        cell = (150, 64)
        cols = 5
        shown = [r for r in rows if r["status"] != "blank"]
        for kind, subset in (("coverage", shown), ("missing", [r for r in shown if r["status"] == "missing"])):
            rws = (len(subset) + cols - 1) // cols
            sheet = Image.new("RGBA", (cols * cell[0], max(1, rws) * cell[1]), (36, 44, 66, 255))
            d = ImageDraw.Draw(sheet)
            for i, r in enumerate(subset):
                ox, oy = (i % cols) * cell[0], (i // cols) * cell[1]
                ref = P.render_pose(pl, r["pose"], pu, 1).crop((10, 4, 58, 60))
                sheet.alpha_composite(ref, (ox + 2, oy + 4))
                color = {"manual": (120, 220, 120), "auto": (230, 220, 100), "missing": (240, 110, 110)}[r["status"]]
                d.text((ox + 54, oy + 4), f"pose {r['pose']:02X}", fill=(255, 255, 255, 255))
                d.text((ox + 54, oy + 18), r["status"], fill=color + (255,))
                if kind == "coverage" and r["status"] != "missing":
                    fr = imgs[r["frame"]]
                    fr = fr.resize((fr.width, fr.height))
                    sheet.alpha_composite(fr.crop((0, 0, min(fr.width, 44), min(fr.height, 44))), (ox + 100, oy + 4))
                    d.text((ox + 54, oy + 32), f"{r['frame']}", fill=(200, 200, 200, 255))
                    d.text((ox + 54, oy + 46), f"{r['score']}", fill=(160, 160, 160, 255))
            sheet.resize((sheet.width * 2, sheet.height * 2), Image.NEAREST).save(out / f"{kind}_{label}.png")
        miss = [r["pose"] for r in rows if r["status"] == "missing"]
        print(label, "manual", sum(r["status"] == "manual" for r in rows),
              "auto", sum(r["status"] == "auto" for r in rows), "missing", len(miss))
    json.dump(result, open(out / "mapping.json", "w"), indent=1)


if __name__ == "__main__":
    main()
