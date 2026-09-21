"""compass_ui.py — a draggable direction dial, in the engine's own headings.

ONE CONTROL, USED WHEREVER AN ABSOLUTE DIRECTION IS AUTHORED: a STRAIGHT
segment that establishes its own direction, and a wave definition's launch
direction. Both are the same question -- "which way?" -- and asking it twice in
two different ways is how an editor grows two vocabularies for one idea.

WHAT IT IS NOT FOR: relative turns. A turn is Left or Right by an angle, and
putting an absolute compass on one would invite the author to think in
directions where the whole point is that the manoeuvre is relative and
therefore reusable. Left/Right stays Left/Right.

QUANTISATION. The engine has sixty-four headings, so the dial has sixty-four
positions and the drag simply rounds to the nearest:

    heading = round(atan2(dy, dx) / 2pi * 64) mod 64

which is exact arithmetic on the angle the pointer is at -- screen y grows
downward and the engine measures clockwise from east with +y down, so the
canvas angle IS the engine angle with no correction. The eight named points
are drawn long and labelled so they are easy to hit, and holding SHIFT snaps
to them; nothing restricts the control to those eight, because the engine does
not.

The exact number is shown beside the dial for anyone who wants it, and is not
needed by anyone who does not.
"""
import math
import tkinter as tk
from tkinter import ttk

import contract_v2 as C
import movement_semantic as sem

DIAL = 92                       # pixels across
RIM = 6                         # inset from the edge

COL_FACE = "#2c2c2c"
COL_RIM = "#6a6a6a"
COL_TICK = "#585858"
COL_POINT = "#9a9a9a"
COL_NEEDLE = "#38d0ff"
COL_TEXT = "#c8c8c8"


def heading_from_point(dx, dy):
    """The engine heading a pointer offset from the centre is asking for.

    Screen y grows downward and src/movement_format.asm measures headings
    clockwise from east with +y down, so no sign correction is needed: the
    canvas angle is the engine angle.
    """
    if dx == 0 and dy == 0:
        return None
    step = 2 * math.pi / C.WM_HEAD_LEN
    return int(round(math.atan2(dy, dx) / step)) % C.WM_HEAD_LEN


def snap_to_point(heading):
    """The nearest of the eight named directions."""
    return int(round(heading / 8.0)) * 8 % C.WM_HEAD_LEN


class CompassDial(ttk.Frame):
    """A dial plus a readout. `command` is called with the new heading.

    The widget owns no project state: it is told a heading and reports the one
    the author dragged to, exactly like an Entry reports text.
    """

    def __init__(self, master, command=None, size=DIAL):
        super().__init__(master)
        self.command = command
        self.size = size
        self._heading = 0
        self._enabled = True

        self.canvas = tk.Canvas(self, width=size, height=size,
                                highlightthickness=0, background=COL_FACE)
        self.canvas.grid(row=0, column=0, rowspan=2)
        self.canvas.bind("<Button-1>", self._pointer)
        self.canvas.bind("<B1-Motion>", self._pointer)
        self.canvas.bind("<Shift-Button-1>", lambda e: self._pointer(e, True))
        self.canvas.bind("<Shift-B1-Motion>", lambda e: self._pointer(e, True))

        self.text = tk.StringVar()
        ttk.Label(self, textvariable=self.text, foreground=COL_TEXT,
                  width=16, justify="left",
                  font=("TkDefaultFont", 9)).grid(row=0, column=1, sticky="sw",
                                                  padx=(8, 0))
        ttk.Label(self, text="drag the needle · shift snaps to the eight",
                  wraplength=140, justify="left",
                  font=("TkDefaultFont", 8)).grid(row=1, column=1, sticky="nw",
                                                  padx=(8, 0))
        self._draw()

    # ---- value -------------------------------------------------------
    @property
    def heading(self):
        return self._heading

    def set_heading(self, heading, notify=False):
        h = int(heading) % C.WM_HEAD_LEN
        changed = h != self._heading
        self._heading = h
        self._draw()
        if changed and notify and self.command:
            self.command(h)

    def set_enabled(self, on):
        self._enabled = bool(on)
        self._draw()

    # ---- interaction -------------------------------------------------
    def _pointer(self, event, snap=False):
        if not self._enabled:
            return
        r = self.size / 2
        h = heading_from_point(event.x - r, event.y - r)
        if h is None:
            return                      # dead centre asks for no direction
        self.set_heading(snap_to_point(h) if snap else h, notify=True)

    # ---- drawing -----------------------------------------------------
    def _draw(self):
        c = self.canvas
        c.delete("all")
        r = self.size / 2
        rad = r - RIM
        c.create_oval(RIM, RIM, self.size - RIM, self.size - RIM,
                      outline=COL_RIM, fill=COL_FACE)

        step = 2 * math.pi / C.WM_HEAD_LEN
        for h in range(C.WM_HEAD_LEN):
            a = h * step
            named = h in sem.COMPASS_ARROW
            inner = rad * (0.74 if named else 0.88)
            col = COL_POINT if named else COL_TICK
            c.create_line(r + inner * math.cos(a), r + inner * math.sin(a),
                          r + rad * math.cos(a), r + rad * math.sin(a),
                          fill=col, width=2 if named else 1)
        for h, arrow in sem.COMPASS_ARROW.items():
            a = h * step
            c.create_text(r + rad * 0.56 * math.cos(a),
                          r + rad * 0.56 * math.sin(a),
                          text=arrow, fill=COL_POINT,
                          font=("TkDefaultFont", 9))

        a = self._heading * step
        tipx, tipy = r + rad * 0.92 * math.cos(a), r + rad * 0.92 * math.sin(a)
        colour = COL_NEEDLE if self._enabled else COL_TICK
        c.create_line(r, r, tipx, tipy, fill=colour, width=3,
                      arrow="last", arrowshape=(9, 11, 4))
        c.create_oval(r - 3, r - 3, r + 3, r + 3, fill=colour, outline="")
        self.text.set(sem.heading_name(self._heading))
