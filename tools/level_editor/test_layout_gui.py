#!/usr/bin/env python3
"""Phase 6B.1: the encounter workspace LAYOUT, at real window sizes.

WHY THIS IS A TEST AND NOT A JUDGEMENT CALL. The failures it guards against
were not ugliness, they were loss of function: Move Up and Move Down clipped
off the right edge, the Convert button truncated, payload text vanishing, and
-- worst -- validation warnings cut in half so the author could not read what
was wrong. A clipped diagnostic is worse than no diagnostic, because it looks
like information.

The sizes below are a 13-inch Mac window, a 15-inch one, and fullscreen on a
large display. "Make the window bigger" is not a fix, so the smallest of them
has to work.

Run with an interpreter that has a working Tk:
    /usr/local/bin/python3 test_layout_gui.py
"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

try:
    import tkinter as tk
    _r = tk.Tk()
    _r.destroy()
except Exception as exc:                                        # noqa: BLE001
    print(f"SKIP - Tk unavailable ({exc})")
    sys.exit(0)

import editor as ed                                             # noqa: E402
import encounters_ui                                            # noqa: E402
import movement_semantic as sem                                 # noqa: E402

for _m in (ed, encounters_ui):
    _m.messagebox.showerror = lambda *a, **k: None
    _m.messagebox.showinfo = lambda *a, **k: None
    _m.messagebox.askyesno = lambda *a, **k: True

PASS, FAIL = [], []

# A 13" Mac gives roughly this much usable window; the others are a 15" and a
# fullscreen large display.
SIZES = (("13-inch laptop", 1280, 760),
         ("15-inch laptop", 1440, 820),
         ("fullscreen", 1920, 1080))


def ok(m, x=""):
    PASS.append(m)
    print(f"ok  - {m}" + (f"  [{x}]" if x else ""))


def check(m, c, x=""):
    if c:
        ok(m, x)
    else:
        FAIL.append(m)
        print(f"FAIL- {m}" + (f"  [{x}]" if x else ""))


def settle(app, n=25):
    for _ in range(n):
        app.update()
        app.update_idletasks()
        time.sleep(0.008)


def clipped(widget):
    """A widget narrower than it asked to be is losing characters."""
    return widget.winfo_width() < widget.winfo_reqwidth()


def buttons_in(parent, found=None):
    found = [] if found is None else found
    for ch in parent.winfo_children():
        if ch.winfo_class() in ("TButton", "TRadiobutton", "TCheckbutton"):
            found.append(ch)
        buttons_in(ch, found)
    return found


app = ed.LevelEditor(ed.find_repo_root())
app.withdraw()
app._open_encounters()
w = app._encounters

try:
    # A semantic program with every control on screen: the segment list, the
    # direction dial, the macro row and the diagnostics.
    j = app.controller.add_movement_program("layout_probe")
    app.controller.start_semantic(j)
    app.controller.add_segment(j, "TURN", at=1)
    app.controller.update_segment(j, 0, heading=16)
    w.refresh()

    for label, ww, hh in SIZES:
        w.geometry(f"{ww}x{hh}")
        w.deiconify()
        settle(app)
        w.tabs.select(2)
        w.prog_list.selection_clear(0, "end")
        w.prog_list.selection_set(j)
        w._prog_selected()
        w.seg_tree.selection_set("0")
        w._seg_selected()
        settle(app)

        timeline = w.canvas.winfo_width()
        tabs = w.tabs.winfo_width()
        prev = w.preview.winfo_width()
        total = timeline + tabs + prev
        authoring = timeline + tabs

        print(f"\n  --- {label} {ww}x{hh}: timeline {timeline}  tabs {tabs}  "
              f"preview {prev} ---")

        # ---- the split -------------------------------------------------
        # The timeline IS part of the authoring area: it is where encounters
        # are placed. Only the preview is "the picture".
        check(f"{label}: the authoring area keeps at least 64% of the width",
              authoring / total >= 0.64, f"{100 * authoring / total:.0f}%")
        check(f"{label}: the preview stays within 36%",
              prev / total <= 0.36, f"{100 * prev / total:.0f}%")

        # ---- nothing that matters is clipped ---------------------------
        tab_frame = w.tabs.nametowidget(w.tabs.tabs()[2])
        # ONLY WHAT IS ON SCREEN. The raw-record editor and the semantic
        # editor share a cell and the hidden one is grid_remove'd, which
        # reports a width of 1 -- that is not a clipping fault.
        bad = [b for b in buttons_in(tab_frame)
               if b.winfo_ismapped() and clipped(b)]
        check(f"{label}: every movement-program control is fully readable",
              not bad,
              ", ".join(f"{b.cget('text')!r} {b.winfo_width()}<"
                        f"{b.winfo_reqwidth()}" for b in bad[:4]))

        for want in ("▲ Move up", "▼ Move down", "Convert…"):
            btn = next((b for b in buttons_in(tab_frame)
                        if str(b.cget("text")) == want), None)
            check(f"{label}: {want!r} is present and un-truncated",
                  btn is not None and btn.winfo_ismapped() and not clipped(btn),
                  "missing" if btn is None else
                  f"{btn.winfo_width()} of {btn.winfo_reqwidth()}")

        # ---- diagnostics can actually be read --------------------------
        check(f"{label}: diagnostics wrap inside the authoring column",
              tabs >= encounters_ui.PROG_TEXT_WRAP,
              f"column {tabs}, wrap {encounters_ui.PROG_TEXT_WRAP}")
        detail_w = w.seg_tree.column("detail", "width")
        check(f"{label}: the segment 'what it does' column has real room",
              detail_w >= 240, f"{detail_w}px")

        # ---- the preview is still useful -------------------------------
        import preview_ui
        check(f"{label}: the preview canvas is still big enough to read",
              w.preview.canvas.winfo_width() >= preview_ui.CANVAS_MIN_W
              and w.preview.canvas.winfo_height() >= preview_ui.CANVAS_MIN_H,
              f"{w.preview.canvas.winfo_width()}x"
              f"{w.preview.canvas.winfo_height()}")
        check(f"{label}: ...and it scales the world to the canvas it has",
              (lambda s: 0 < s[0] < 4)(w.preview._scale()),
              f"scale {w.preview._scale()[0]:.2f}")

    # ---- resizing keeps working, both ways -----------------------------
    w.geometry("1920x1080")
    settle(app)
    wide = w.tabs.winfo_width()
    w.geometry("1280x760")
    settle(app)
    narrow = w.tabs.winfo_width()
    check("shrinking the window shrinks the authoring column rather than "
          "clipping it", narrow < wide and narrow > 0, f"{wide} -> {narrow}")
    w.geometry("1920x1080")
    settle(app)
    check("...and growing it gives the room back to authoring, not the picture",
          w.tabs.winfo_width() == wide, f"{w.tabs.winfo_width()} vs {wide}")

    # ---- a long warning is readable, not cut in half -------------------
    w.geometry("1280x760")
    settle(app)
    app.controller.update_segment(j, 1, steps=0)
    w.refresh()
    w.tabs.select(2)
    settle(app)
    check("a long diagnostic wraps rather than running off the edge",
          w.preview.warning.get() == "" or
          w.preview.warn_label.cget("wraplength") > 0,
          f"wrap {w.preview.warn_label.cget('wraplength')}")

finally:
    if w.winfo_exists():
        w.withdraw()
        w.destroy()
    app.destroy()

print()
if FAIL:
    print(f"{len(FAIL)} FAILURE(S):")
    for f in FAIL:
        print(f"  - {f}")
    sys.exit(1)
print(f"All {len(PASS)} layout geometry checks passed.")
