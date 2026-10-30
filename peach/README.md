# Peach reskin (graphics-only ROM patch)

`build_peach.py` turns an owner SMW (USA) ROM plus an SMW-style Peach sprite sheet into a
Peach-skinned ROM. It repaints Mario's compressed GFX32 tiles (core poses, small and big)
and rewrites Mario's 10-colour palette at `$00:B2C8`. Code is untouched.

    python tools/peach/build_peach.py --rom smw.sfc --sheet peach_sheet.png --out smw_peach.sfc
    python tools/peach/preview.py smw_peach.sfc preview.png   # offline pose contact sheet

Needs Pillow. The output is a separate ROM: mod packages pin the stock ROM hash, so the game
now starts without mods when given it (see `src/main.c`).

Sprites: Princess Peach, SMW-style, by WizToad and GatetcVerde (made for Mario Worlds Delta,
Green Baron Games). Please give credit if used.
