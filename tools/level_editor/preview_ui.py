"""The trajectory preview panel.

DRAWS ONLY. Every number on this canvas comes out of movement_sim, which is
GUI-independent and proved frame-for-frame against the real 6502 (see
test_movement_sim_engine.py). Nothing here computes a position, an interval or
a lifetime; if it did, the preview would be a second opinion about movement and
the editor would start disagreeing with the engine.

READ-ONLY WITH RESPECT TO PROJECT DATA. Playing, scrubbing and selecting touch
no model object and never reach the host's undo stack. Preview state -- which
frame, playing or paused, which member is selected -- is not authored state and
is deliberately not saved.

THE COORDINATE SYSTEM IS THE VIC'S. src/renderer.asm copies logX/logXHi and
logY straight into the sprite registers, so the simulator's X and Y ARE sprite
coordinates: X is nine bits with the visible display window at 24..343, and Y
is a raster line with the aperture at 55..247. A sprite is 24x21, so its
top-left corner is what the engine stores and its CENTRE is what reads
correctly as "where the enemy is" -- which is what the markers are drawn at.
Everything outside that window is real, simulated space where waves spawn and
leave, and it is drawn dimmed rather than cropped.
"""
import tkinter as tk
from tkinter import ttk

import movement_sim as ms

# The world the preview shows. Wide enough for the whole nine-bit despawn
# region on the right (344) and the spawn column at 0, with a little air.
WORLD_X0, WORLD_X1 = -8, 400
WORLD_Y0, WORLD_Y1 = 0, 256

SPRITE_W, SPRITE_H = 24, 21

CANVAS_W, CANVAS_H = 430, 276

COL_VOID = "#1b1b1b"            # simulated space outside the display window
COL_FIELD = "#2c2c2c"           # the visible playfield
COL_FIELD_EDGE = "#6a6a6a"
COL_CLEAR = "#4a3030"           # despawn margins
COL_TEXT = "#b0b0b0"
COL_START = "#909090"

# One colour per member, so a formation reads as several objects rather than
# one scribble. Deliberately the workspace's own accents plus neutrals.
MEMBER_COLOURS = ("#38d0ff", "#ffd000", "#7ef08a", "#ff8ad0",
                  "#c0a0ff", "#ffa060", "#80e0d0", "#d0d0d0")

SPEEDS = (("0.25x", 0.25), ("0.5x", 0.5), ("1x", 1.0), ("2x", 2.0), ("4x", 4.0))
PAL_FRAME_MS = 20               # 50 Hz


class PreviewPanel(ttk.LabelFrame):
    """The preview, over whatever the workspace currently has selected.

    `set_source` is told WHAT to preview, never the simulation itself: the
    panel resolves it against the live project each time it recomputes, so an
    unsaved edit to a stage is picked up by invalidate() + the next redraw.
    """

    def __init__(self, master, workspace):
        super().__init__(master, text="Preview", padding=4)
        self.ws = workspace
        self.source = None          # ("trigger", i) | ("wave", id) | ("program", id)
        self.sim = None
        self.error = None
        self.frame = 0
        self.playing = False
        self._job = None
        self._sig = None            # what the current sim was built from
        self._markers = {}
        self._member = 0

        self.headline = tk.StringVar(value="nothing selected")
        self.diag = tk.StringVar(value="")
        self.detail = tk.StringVar(value="")
        self.frame_text = tk.StringVar(value="frame 0 / 0")
        self.speed = tk.StringVar(value="1x")
        self.show_paths = tk.BooleanVar(value=True)

        self._build()

    # =====================================================================
    # construction
    # =====================================================================
    def _build(self):
        ttk.Label(self, textvariable=self.headline, wraplength=CANVAS_W,
                  justify="left", font=("TkDefaultFont", 9)).pack(
                      anchor="w", pady=(0, 3))

        self.canvas = tk.Canvas(self, width=CANVAS_W, height=CANVAS_H,
                                highlightthickness=0, background=COL_VOID)
        self.canvas.pack(fill="both", expand=True)
        self.canvas.bind("<Configure>", lambda e: self.redraw())

        bar = ttk.Frame(self)
        bar.pack(fill="x", pady=(5, 0))
        self.play_btn = ttk.Button(bar, text="Play", width=7,
                                   command=self.toggle_play)
        self.play_btn.pack(side="left")
        ttk.Button(bar, text="Restart", width=8,
                   command=self.restart).pack(side="left", padx=2)
        ttk.Button(bar, text="◀", width=3,
                   command=lambda: self.step(-1)).pack(side="left", padx=(6, 1))
        ttk.Button(bar, text="▶", width=3,
                   command=lambda: self.step(1)).pack(side="left")
        ttk.Label(bar, text="speed").pack(side="left", padx=(8, 2))
        self.speed_box = ttk.Combobox(bar, textvariable=self.speed, width=5,
                                      state="readonly",
                                      values=[n for n, _ in SPEEDS])
        self.speed_box.pack(side="left")
        ttk.Checkbutton(bar, text="paths", variable=self.show_paths,
                        command=self.redraw).pack(side="left", padx=(8, 0))

        sc = ttk.Frame(self)
        sc.pack(fill="x", pady=(4, 0))
        self.scrub = ttk.Scale(sc, from_=0, to=0, orient="horizontal",
                               command=self._scrubbed)
        self.scrub.pack(side="left", fill="x", expand=True)
        ttk.Label(sc, textvariable=self.frame_text, width=16,
                  font=("TkDefaultFont", 9)).pack(side="left", padx=(6, 0))

        mem = ttk.Frame(self)
        mem.pack(fill="x", pady=(4, 0))
        ttk.Label(mem, text="member").pack(side="left")
        self.member_box = ttk.Combobox(mem, width=4, state="readonly", values=())
        self.member_box.pack(side="left", padx=(4, 0))
        self.member_box.bind("<<ComboboxSelected>>", self._member_picked)
        ttk.Label(mem, textvariable=self.diag,
                  font=("TkDefaultFont", 9)).pack(side="left", padx=(10, 0))
        ttk.Label(self, textvariable=self.detail, foreground=COL_TEXT,
                  font=("TkFixedFont", 9)).pack(anchor="w", pady=(2, 0))

    # =====================================================================
    # what is being previewed
    # =====================================================================
    def set_source(self, source):
        """Point the preview at a trigger, a wave definition or a program.

        DOES NOT START PLAYING. A selection change that began an animation
        would make the workspace jitter every time the author clicked a row.
        """
        if source == self.source:
            return
        self.source = source
        self._member = 0
        self.pause()
        self.frame = 0
        self.invalidate()

    def invalidate(self):
        """The project may have changed: rebuild before the next draw."""
        self._sig = None
        self.refresh()

    def _signature(self):
        """What the current simulation depends on.

        Cheap to compute and cheap to compare, so an ordinary refresh does not
        re-fly a 360-frame wave for nothing -- but ANY authored change to the
        wave or its program changes it, which is what makes the preview follow
        unsaved edits.
        """
        proj = self.ws.controller.project
        if self.source is None:
            return None
        kind, ref = self.source
        try:
            if kind == "trigger":
                if not 0 <= ref < len(proj.triggers):
                    return ("gone",)
                t = proj.triggers[ref]
                wave = next((w for w in proj.wave_definitions
                             if w.id == t.wave_definition), None)
                key = (t.species, t.wave_definition)
            elif kind == "wave":
                wave = next((w for w in proj.wave_definitions if w.id == ref),
                            None)
                key = ("wave", ref)
            else:
                wave = None
                key = ("program", ref)
            prog_id = wave.movement_program if wave is not None else ref
            prog = next((p for p in proj.movement_programs if p.id == prog_id),
                        None)
            return (kind, key,
                    None if wave is None else tuple(sorted(wave.to_dict().items())),
                    None if prog is None else
                    tuple(tuple(sorted(s.to_dict().items())) for s in prog.stages))
        except Exception:                                   # noqa: BLE001
            return ("broken",)

    def _rebuild(self):
        proj = self.ws.controller.project
        self.sim, self.error = None, None
        if self.source is None:
            self.headline.set("select a trigger, wave definition or movement "
                              "program to preview it")
            return
        kind, ref = self.source
        try:
            if kind == "trigger":
                if not 0 <= ref < len(proj.triggers):
                    raise ms.SimulationError("no trigger selected")
                t = proj.triggers[ref]
                self.sim = ms.simulate_trigger(proj, ref)
                self.headline.set(
                    f"trigger at worldProgress {t.world_progress} → wave "
                    f"{self.sim.wave_id!r} → program "
                    f"{self.sim.program_id!r}   ({self.sim.count} members, "
                    f"{self.sim.interval}-frame interval)")
            elif kind == "wave":
                wave = ms.wave_by_id(proj, ref)
                self.sim = ms.simulate_wave(proj, wave)
                self.headline.set(
                    f"wave {ref!r} → program {self.sim.program_id!r}   "
                    f"({self.sim.count} members, {self.sim.interval}-frame "
                    f"interval)")
            else:
                prog = next((p for p in proj.movement_programs if p.id == ref),
                            None)
                if prog is None:
                    raise ms.SimulationError(
                        f"movement program {ref!r} does not exist")
                head, start = self._program_context(proj, prog)
                self.sim = ms.preview_program(proj, prog, heading=head,
                                              start=start)
                self.headline.set(
                    f"movement program {ref!r}, flown on its own from "
                    f"({start[0]}, {start[1]}) on launch heading {head}"
                    + ("" if self._ctx is None else
                       f"   — borrowed from wave {self._ctx!r}"))
        except ms.SimulationError as exc:
            self.error = str(exc)
            self.headline.set("preview unavailable")
        except Exception as exc:                            # noqa: BLE001
            # A malformed project must never take the window down with it.
            self.error = f"{type(exc).__name__}: {exc}"
            self.headline.set("preview unavailable")

    def _program_context(self, proj, prog):
        """A launch heading and a start position for a bare program.

        A movement program is self-contained -- that is what the entry-heading
        byte is for -- but it still has to be flown from SOMEWHERE, and a
        program whose first arc says CONT inherits a launch heading it does not
        name. So the first wave that actually uses this program lends its own,
        and the panel says whose they are rather than pretending the numbers
        came from the program.
        """
        for w in proj.wave_definitions:
            if w.movement_program == prog.id:
                lo, hi, y = ms.member_start(w, 0)
                self._ctx = w.id
                return w.heading, (lo | (hi << 8), y)
        self._ctx = None
        return 0, (160, 40)

    # =====================================================================
    # transport
    # =====================================================================
    def _last(self):
        return max(0, (self.sim.frame_count - 1) if self.sim else 0)

    def toggle_play(self):
        self.pause() if self.playing else self.play()

    def play(self):
        if not self.sim:
            return
        if self.frame >= self._last():
            self.frame = 0
        self.playing = True
        self.play_btn.configure(text="Pause")
        self._schedule()

    def pause(self):
        self.playing = False
        if self._job is not None:
            try:
                self.after_cancel(self._job)
            except Exception:                               # noqa: BLE001
                pass
            self._job = None
        if self.winfo_exists():
            self.play_btn.configure(text="Play")

    def restart(self):
        self.frame = 0
        self._sync_transport()
        self._draw_markers()

    def step(self, delta):
        """One frame either way. DETERMINISTIC: the frame is looked up in the
        precomputed simulation, never integrated from where the marker
        happens to be, so stepping back is exact rather than approximate."""
        self.pause()
        self.frame = max(0, min(self._last(), self.frame + delta))
        self._sync_transport()
        self._draw_markers()

    def _schedule(self):
        mult = dict(SPEEDS).get(self.speed.get(), 1.0)
        self._job = self.after(max(1, int(PAL_FRAME_MS / mult)), self._advance)

    def _advance(self):
        self._job = None
        if not self.playing or not self.sim:
            return
        if self.frame >= self._last():
            self.pause()
            return
        self.frame += 1
        self._sync_transport()
        self._draw_markers()        # markers only: the field and paths stand
        self._schedule()

    def _scrubbed(self, value):
        if self._syncing_scrub:
            return
        want = int(float(value))
        if want != self.frame:
            self.pause()
            self.frame = max(0, min(self._last(), want))
            self._sync_transport(move_scrub=False)
            self._draw_markers()

    _syncing_scrub = False

    def _sync_transport(self, move_scrub=True):
        last = self._last()
        self._syncing_scrub = True
        try:
            self.scrub.configure(to=max(last, 1))
            if move_scrub:
                self.scrub.set(self.frame)
        finally:
            self._syncing_scrub = False
        self.frame_text.set(f"frame {self.frame} / {last}")

    def _member_picked(self, _evt=None):
        try:
            self._member = int(self.member_box.get())
        except ValueError:
            self._member = 0
        self._draw_diagnostics()

    # =====================================================================
    # drawing
    # =====================================================================
    def refresh(self):
        """Rebuild if the project changed under us, then draw."""
        sig = self._signature()
        if sig != self._sig:
            self._sig = sig
            was = self.frame
            self._rebuild()
            self.frame = min(was, self._last())
            n = self.sim.count if self.sim else 0
            self.member_box.configure(values=[str(i) for i in range(n)])
            if n:
                self._member = min(self._member, n - 1)
                self.member_box.set(str(self._member))
            else:
                self.member_box.set("")
        self.redraw()

    def redraw(self):
        self._draw_field()
        self._draw_paths()
        self._draw_markers()
        self._sync_transport()

    # ---- the world -> canvas mapping ------------------------------------
    def _scale(self):
        w = max(self.canvas.winfo_width(), 40)
        h = max(self.canvas.winfo_height(), 40)
        sx = w / (WORLD_X1 - WORLD_X0)
        sy = h / (WORLD_Y1 - WORLD_Y0)
        s = min(sx, sy)
        ox = (w - s * (WORLD_X1 - WORLD_X0)) / 2
        oy = (h - s * (WORLD_Y1 - WORLD_Y0)) / 2
        return s, ox, oy

    def _pt(self, x, y):
        s, ox, oy = self._scale()
        return ox + (x - WORLD_X0) * s, oy + (y - WORLD_Y0) * s

    def _centre(self, f):
        """A sprite's centre. The engine stores the TOP-LEFT corner."""
        return self._pt(f.x + SPRITE_W / 2, f.y + SPRITE_H / 2)

    def _draw_field(self):
        c = self.canvas
        c.delete("field")
        x0, y0 = self._pt(WORLD_X0, WORLD_Y0)
        x1, y1 = self._pt(WORLD_X1, WORLD_Y1)
        c.create_rectangle(x0, y0, x1, y1, fill=COL_VOID, outline="",
                           tags="field")

        # The despawn margins, so an author can see WHY a path ends where it
        # does rather than just that it stopped.
        lx0, ly0 = self._pt(WORLD_X0, WORLD_Y0)
        lx1, ly1 = self._pt(ms.ENEMY_CLEAR_X_LEFT, WORLD_Y1)
        c.create_rectangle(lx0, ly0, lx1, ly1, fill=COL_CLEAR, outline="",
                           tags="field")
        rx0, _ = self._pt(ms.ENEMY_CLEAR_X_RIGHT, WORLD_Y0)
        c.create_rectangle(rx0, ly0, x1, ly1, fill=COL_CLEAR, outline="",
                           tags="field")
        by0 = self._pt(WORLD_X0, ms.ENEMY_CLEAR_Y)[1]
        c.create_rectangle(x0, by0, x1, y1, fill=COL_CLEAR, outline="",
                           tags="field")

        # The visible playfield: sprite X 24..343, rasters 55..247.
        fx0, fy0 = self._pt(24, ms.MIN_SPRITE_Y)
        fx1, fy1 = self._pt(ms.DISPLAY_X_LAST + 1, ms.APERTURE_BOT_RASTER + 1)
        c.create_rectangle(fx0, fy0, fx1, fy1, fill=COL_FIELD,
                           outline=COL_FIELD_EDGE, tags="field")
        c.create_text(fx0 + 4, fy0 + 2, text="visible playfield", anchor="nw",
                      fill=COL_TEXT, font=("TkDefaultFont", 8), tags="field")
        c.tag_lower("field")

    def _draw_paths(self):
        c = self.canvas
        c.delete("path")
        if not self.sim or not self.show_paths.get():
            return
        for m, path in enumerate(self.sim.paths):
            col = MEMBER_COLOURS[m % len(MEMBER_COLOURS)]
            pts = []
            for f in path:
                pts.extend(self._centre(f))
            if len(pts) >= 4:
                c.create_line(*pts, fill=col, width=1, tags="path")
            sx, sy = self._centre(path[0])
            c.create_rectangle(sx - 2, sy - 2, sx + 2, sy + 2, outline=COL_START,
                               fill="", tags="path")
            ex, ey = self._centre(path[-1])
            c.create_line(ex - 3, ey - 3, ex + 3, ey + 3, fill=col, tags="path")
            c.create_line(ex - 3, ey + 3, ex + 3, ey - 3, fill=col, tags="path")

    def _draw_markers(self):
        """Only the live positions. Called every playback frame, so it moves
        existing items instead of rebuilding the canvas."""
        c = self.canvas
        c.delete("marker")
        self._draw_diagnostics()
        if not self.sim:
            if self.error:
                c.delete("why")
                w = max(self.canvas.winfo_width(), 40)
                c.create_text(w / 2, 40, text=self.error, width=w - 30,
                              fill=COL_TEXT, justify="center", tags="why",
                              font=("TkDefaultFont", 10))
            return
        c.delete("why")
        for f in self.sim.at(self.frame):
            col = MEMBER_COLOURS[f.member % len(MEMBER_COLOURS)]
            cx, cy = self._centre(f)
            s, _, _ = self._scale()
            r = max(2.5, 3.5 * s / 1.0) if s < 1 else 4
            c.create_oval(cx - r, cy - r, cx + r, cy + r, fill=col,
                          outline="", tags="marker")
            if f.member == self._member:
                # the sprite's real footprint, so "is it on screen yet" is
                # answerable by eye rather than by arithmetic
                px0, py0 = self._pt(f.x, f.y)
                px1, py1 = self._pt(f.x + SPRITE_W, f.y + SPRITE_H)
                c.create_rectangle(px0, py0, px1, py1, outline=col, fill="",
                                   dash=(2, 2), tags="marker")

    def _draw_diagnostics(self):
        if not self.sim:
            self.diag.set("")
            self.detail.set(self.error or "")
            return
        here = {f.member: f for f in self.sim.at(self.frame)}
        f = here.get(self._member)
        if f is None:
            spawn = (self.sim.spawn_frames[self._member]
                     if self._member < len(self.sim.spawn_frames) else None)
            if spawn is not None and self.frame < spawn:
                self.diag.set(f"member {self._member}: not spawned yet "
                              f"(frame {spawn})")
            else:
                self.diag.set(f"member {self._member}: despawned")
            self.detail.set("")
            return
        self.diag.set(f"X {f.x}  Y {f.y}  stage {f.stage_index} "
                      f"{f.stage_kind}  heading {f.heading}"
                      + ("  • on screen" if f.visible else "  • off screen"))
        self.detail.set(
            f"vx {f.vx:+d} vy {f.vy:+d} quarter-px   "
            f"sub-pixel {f.acc_x}/{f.acc_y}   timer {f.timer}  steps {f.steps}")

    def destroy(self):
        self.pause()
        super().destroy()
