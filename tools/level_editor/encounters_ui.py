"""The v6 encounter authoring workspace.

    trigger  ->  wave definition  ->  movement program  ->  stages

That chain is the whole design, and the window is laid out as it: a stage
TIMELINE on the left showing where encounters happen, and on the right three
tabs following the references down -- the triggers, the reusable wave
definitions they name, and the reusable movement programs those name.

WHAT THE AUTHOR NEVER SEES. Byte offsets, definition indices, the six physical
trigger columns, the padding to 180 slots, `$ff` for a continued heading. Those
are the exporter's business (Phase 2/4) and appear nowhere here: a trigger names
a wave by ID, a wave names a program by ID, and an arc that continues from the
heading it already holds says "CONT".

WHERE THE RULES LIVE. Not here. `validation_v6` is the single rule set, and this
window shows what it says -- errors in red, warnings in amber, selectable
straight to the thing they are about. Widget code parses text (an integer entry
refuses letters) and nothing more; there is no second opinion about what is
legal, because two opinions is how an editor starts disagreeing with its engine.

THE TRAJECTORY PREVIEW (Phase 6A) lives in preview_ui.py and draws nothing it
computes itself: every position comes out of movement_sim, which is proved
frame-for-frame against the real 6502. This file only tells it WHAT is
selected and when the project changed underneath it. Previewing is read-only
-- playing and scrubbing never reach the undo stack.
"""
import tkinter as tk
from tkinter import messagebox, simpledialog, ttk

import contract_v2 as C
import movement_semantic as sem
from compass_ui import CompassDial
from controller_v6 import ControllerError
from preview_ui import PreviewPanel

# --- timeline geometry ------------------------------------------------------
TL_W = 170                  # canvas width: a ruler, not a panel -- every
                            # pixel it gives up goes to the authoring tabs
TL_PAD_TOP = 18             # room for the "0" label
TL_PAD_BOT = 24             # ...and the stage-end one
TL_AXIS_X = 58              # where the vertical rule sits
TL_MIN_H = 320

COL_AXIS = "#7a7a7a"
COL_TICK = "#555555"
COL_RING = "#38d0ff"
COL_DROPPER = "#ffd000"
COL_SQUARE = "#a060ff"      # the Square, violet: distinct from both at a glance
COL_SELECT = "#ffffff"
COL_NOSPAWN = "#ff40c0"
COL_QUIET = "#2a2a2a"
COL_ERROR = "#ff6060"
COL_WARN = "#e0a000"

SPECIES_COLOUR = {"RING": COL_RING, "DROPPER": COL_DROPPER,
                  "SQUARE": COL_SQUARE}
HEADINGS = ["CONT"] + [str(i) for i in range(C.WM_HEAD_LEN)]

# THE NAMED PIECES FIRST, because they are the vocabulary a designer reaches
# for; the bare angles after, because a turn is ultimately a number and
# refusing to let somebody type 135 would be arbitrary. Both set the same
# field -- a turn has one angle, however it was chosen.
ANGLE_CHOICES = ([f"{label} ({sem.degrees(n)}°)" for label, n in sem.NAMED_TURNS]
                 + [f"{d}°" for d, n in sem.TURN_PRESETS
                    if n not in [x for _l, x in sem.NAMED_TURNS]]
                 + ["custom"])
ANGLE_STEPS = {f"{label} ({sem.degrees(n)}°)": n for label, n in sem.NAMED_TURNS}
ANGLE_STEPS.update({f"{d}°": n for d, n in sem.TURN_PRESETS
                    if n not in [x for _l, x in sem.NAMED_TURNS]})

RADIUS_CHOICES = [name for name, _r in sem.RATE_PRESETS] + ["custom"]
RADIUS_RATE = {name: r for name, r in sem.RATE_PRESETS}

# How wide the movement-program status lines may ask to be. Any fixed bound
# works; what matters is that there IS one -- see the note in _build_programs.
# Diagnostics wrap here. Narrow enough that the authoring column can
# always honour it at the minimum window size, so a warning is never
# clipped -- a clipped diagnostic is worse than none.
PROG_TEXT_WRAP = 540


def _int_or(value, fallback):
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return fallback


def _put(entry, value):
    entry.delete(0, "end")
    entry.insert(0, str(value))


class EncounterWorkspace(tk.Toplevel):
    """One window over the host editor's live controller.

    It owns no project state. Every edit goes through `controller`, is wrapped
    in the host's undo snapshot, and then both windows redraw -- so an encounter
    edit is dirty, undoable and saved exactly like a terrain edit.
    """

    def __init__(self, host):
        super().__init__(host)
        self.host = host
        self.controller = host.controller
        self.title(f"Encounters — {self.controller.project.name}")
        # WIDER THAN THE SUM OF ITS PARTS ON PURPOSE. The notebook is the
        # only weighted column, so every pixel added here goes to the tab
        # the author is working in -- which for movement programs has to
        # hold a record list, a segment list and their diagnostics side by
        # side without truncating any of them.
        self.geometry("1800x840")
        self.minsize(1240, 660)
        self.protocol("WM_DELETE_WINDOW", self._close)

        self.sel_trigger = None
        self.sel_wave = None
        self.sel_prog = None
        self.sel_stage = None
        self._syncing = False          # suppress widget callbacks during refresh
        self._fire_vars = []

        self.sel_segment = None
        self.show_raw = False          # per-session view choice, never saved

        self.status_text = tk.StringVar()
        self.quiet_text = tk.StringVar()
        self.no_spawn_var = tk.StringVar()
        self.prog_mode_text = tk.StringVar()
        self.prog_cost_text = tk.StringVar()

        self._build()
        self.refresh()

    # =====================================================================
    # construction
    # =====================================================================
    def _build(self):
        strip = ttk.Frame(self, padding=(8, 6, 8, 2))
        strip.pack(fill="x")
        ttk.Label(strip, textvariable=self.status_text,
                  font=("TkDefaultFont", 10)).pack(side="left")

        body = ttk.Frame(self, padding=(8, 2, 8, 4))
        body.pack(fill="both", expand=True)
        body.columnconfigure(1, weight=1)
        body.rowconfigure(0, weight=1)

        # ---- the timeline --------------------------------------------
        tl = ttk.LabelFrame(body, text="Stage (worldProgress)", padding=4)
        tl.grid(row=0, column=0, sticky="ns", padx=(0, 8))
        tl.rowconfigure(0, weight=1)
        self.canvas = tk.Canvas(tl, width=TL_W, highlightthickness=0,
                                background=self.cget("background"))
        self.canvas.grid(row=0, column=0, sticky="ns")
        self.canvas.bind("<Button-1>", self._timeline_click)
        self.canvas.bind("<Configure>", lambda e: self._draw_timeline())

        ns = ttk.Frame(tl)
        ns.grid(row=1, column=0, sticky="ew", pady=(6, 0))
        ttk.Label(ns, text="noSpawnRow").pack(side="left")
        e = ttk.Entry(ns, textvariable=self.no_spawn_var, width=7)
        e.pack(side="left", padx=(4, 4))
        e.bind("<Return>", self._apply_no_spawn)
        e.bind("<FocusOut>", self._apply_no_spawn)
        ttk.Label(tl, textvariable=self.quiet_text,
                  font=("TkDefaultFont", 9)).grid(row=2, column=0, sticky="w")

        # ---- the three tabs -------------------------------------------
        self.tabs = ttk.Notebook(body)
        self.tabs.grid(row=0, column=1, sticky="nsew")
        self._build_triggers(self.tabs)
        self._build_waves(self.tabs)
        self._build_programs(self.tabs)
        self.tabs.bind("<<NotebookTabChanged>>",
                       lambda e: self._sync_preview_source())

        # ---- the preview (Phase 6A) ------------------------------------
        # A column of its own rather than a pane inside the notebook: the
        # point of a preview is to be visible WHILE the stage being edited is
        # visible, and a tab that hid the stage list would defeat it.
        self.preview = PreviewPanel(body, self)
        self.preview.grid(row=0, column=2, sticky="ns", padx=(8, 0))

        # ---- validation ------------------------------------------------
        vf = ttk.LabelFrame(self, text="Validation", padding=4)
        vf.pack(fill="x", padx=8, pady=(0, 8))
        self.issues = ttk.Treeview(vf, columns=("kind", "where", "message"),
                                   show="headings", height=4,
                                   selectmode="browse")
        for cid, txt, w in (("kind", "", 60), ("where", "field", 190),
                            ("message", "message", 700)):
            self.issues.heading(cid, text=txt)
            self.issues.column(cid, width=w, anchor="w",
                               stretch=(cid == "message"))
        self.issues.pack(fill="x")
        self.issues.tag_configure("error", foreground=COL_ERROR)
        self.issues.tag_configure("warn", foreground=COL_WARN)
        self.issues.bind("<<TreeviewSelect>>", self._issue_selected)

    # ---------------------------------------------------------------- triggers
    def _build_triggers(self, nb):
        f = ttk.Frame(nb, padding=6)
        nb.add(f, text="Triggers")
        f.columnconfigure(0, weight=1)
        f.rowconfigure(0, weight=1)

        self.trig_tree = ttk.Treeview(
            f, columns=("progress", "wave", "species", "fire", "side"),
            show="headings", selectmode="browse", height=10)
        for cid, txt, w in (("progress", "progress", 80), ("wave", "wave", 130),
                            ("species", "species", 90), ("fire", "fires", 110),
                            ("side", "side", 70)):
            self.trig_tree.heading(cid, text=txt)
            self.trig_tree.column(cid, width=w, anchor="w")
        self.trig_tree.grid(row=0, column=0, sticky="nsew")
        self.trig_tree.bind("<<TreeviewSelect>>", self._trigger_selected)

        btn = ttk.Frame(f)
        btn.grid(row=1, column=0, sticky="ew", pady=(4, 6))
        for txt, cmd in (("Add", self._trigger_add),
                         ("Duplicate", self._trigger_duplicate),
                         ("Delete", self._trigger_delete)):
            ttk.Button(btn, text=txt, width=10, command=cmd).pack(side="left", padx=1)

        d = ttk.LabelFrame(f, text="Selected trigger", padding=6)
        d.grid(row=2, column=0, sticky="ew")
        d.columnconfigure(1, weight=1)

        ttk.Label(d, text="worldProgress").grid(row=0, column=0, sticky="w")
        self.t_prog = ttk.Entry(d, width=8)
        self.t_prog.grid(row=0, column=1, sticky="w")
        self.t_prog.bind("<Return>", self._trigger_apply)
        self.t_prog.bind("<FocusOut>", self._trigger_apply)
        self.t_where = ttk.Label(d, text="", font=("TkDefaultFont", 9))
        self.t_where.grid(row=0, column=2, sticky="w", padx=(8, 0))

        ttk.Label(d, text="wave definition").grid(row=1, column=0, sticky="w")
        self.t_wave = ttk.Combobox(d, state="readonly", width=20)
        self.t_wave.grid(row=1, column=1, sticky="w")
        self.t_wave.bind("<<ComboboxSelected>>", self._trigger_apply)

        ttk.Label(d, text="species").grid(row=2, column=0, sticky="w")
        self.t_species = ttk.Combobox(d, state="readonly", width=12,
                                      values=sorted(C.SPECIES))
        self.t_species.grid(row=2, column=1, sticky="w")
        self.t_species.bind("<<ComboboxSelected>>", self._trigger_apply)

        ttk.Label(d, text="Dropper side").grid(row=3, column=0, sticky="w")
        self.t_side = ttk.Combobox(d, state="readonly", width=12,
                                   values=sorted(C.DROPPER_SIDES))
        self.t_side.grid(row=3, column=1, sticky="w")
        self.t_side.bind("<<ComboboxSelected>>", self._trigger_apply)

        ttk.Label(d, text="fires").grid(row=4, column=0, sticky="nw")
        self.t_fire = ttk.Frame(d)
        self.t_fire.grid(row=4, column=1, columnspan=2, sticky="w")
        self.t_fire_note = ttk.Label(d, text="", font=("TkDefaultFont", 9))
        self.t_fire_note.grid(row=5, column=1, columnspan=2, sticky="w")

    # ------------------------------------------------------------------ waves
    def _build_waves(self, nb):
        f = ttk.Frame(nb, padding=6)
        nb.add(f, text="Wave definitions (shared)")
        f.columnconfigure(1, weight=1)
        f.rowconfigure(0, weight=1)

        self.wave_list = tk.Listbox(f, width=22, exportselection=False)
        self.wave_list.grid(row=0, column=0, sticky="ns")
        self.wave_list.bind("<<ListboxSelect>>", self._wave_selected)

        wb = ttk.Frame(f)
        wb.grid(row=1, column=0, sticky="ew", pady=(4, 0))
        for txt, cmd in (("Add", self._wave_add), ("Dup", self._wave_duplicate),
                         ("Rename", self._wave_rename), ("Del", self._wave_delete)):
            ttk.Button(wb, text=txt, width=7, command=cmd).pack(side="left", padx=1)

        d = ttk.LabelFrame(f, text="Definition", padding=6)
        d.grid(row=0, column=1, rowspan=2, sticky="nsew", padx=(8, 0))
        self.w_fields = {}
        rows = (("count", "members sent"), ("interval", "frames between members"),
                ("start_x", "spawn X (0..%d)" % C.MAX_SPAWN_X),
                ("start_y", "spawn Y (0..%d)" % C.MAX_SPAWN_Y),
                ("x_step", "X step per member (signed)"),
                ("y_step", "Y step per member (signed)"),
                ("colour", "colour (0..%d)" % C.MAX_COLOUR),
                ("heading", "launch heading (0..%d)" % (C.WM_HEAD_LEN - 1)))
        for i, (key, hint) in enumerate(rows):
            ttk.Label(d, text=key.replace("_", " ")).grid(row=i, column=0, sticky="w")
            e = ttk.Entry(d, width=8)
            e.grid(row=i, column=1, sticky="w")
            e.bind("<Return>", self._wave_apply)
            e.bind("<FocusOut>", self._wave_apply)
            self.w_fields[key] = e
            if key == "heading":
                # THE COMPASS NAMES THE DIRECTION; THE ENTRY KEEPS THE EXACT
                # VALUE. The eight points land on headings 0, 8, 16 ... 56, but
                # a heading is any of 64 and the authored content really does
                # use 10 and 12 -- so the picker is a convenience over the
                # number rather than a replacement for it, and choosing a
                # point simply types the heading in.
                # THE SAME DIAL THE STRAIGHT SEGMENT USES. A launch direction
                # and an explicit straight direction are the same question, so
                # they get the same control rather than two vocabularies for
                # one idea.
                self.w_compass = CompassDial(d, command=self._wave_compass_picked)
                self.w_compass.grid(row=i, column=2, sticky="w", padx=(8, 0))
                self.w_head_text = tk.StringVar()
                ttk.Label(d, textvariable=self.w_head_text,
                          wraplength=PROG_TEXT_WRAP, justify="left",
                          font=("TkDefaultFont", 9)).grid(
                              row=i, column=3, sticky="w", padx=(8, 0))
                continue
            ttk.Label(d, text=hint, font=("TkDefaultFont", 9)).grid(
                row=i, column=2, sticky="w", padx=(8, 0))
        r = len(rows)
        ttk.Label(d, text="movement program").grid(row=r, column=0, sticky="w")
        self.w_prog = ttk.Combobox(d, state="readonly", width=18)
        self.w_prog.grid(row=r, column=1, columnspan=2, sticky="w")
        self.w_prog.bind("<<ComboboxSelected>>", self._wave_apply)
        # HOW THIS WAVE'S ENEMIES SHOOT. On the definition rather than the
        # trigger because it is a property of the wave's design, and because a
        # shared definition is exactly the unit an author wants to opt into
        # aimed fire. The default is the behaviour every existing wave already
        # has, so nothing changes by being opened.
        ttk.Label(d, text="firing").grid(row=r + 1, column=0, sticky="w")
        self.w_fire = ttk.Combobox(d, state="readonly", width=18,
                                   values=[C.FIRE_MODE_LABELS[m]
                                           for m in ("DOWN", "AIMED")])
        self.w_fire.grid(row=r + 1, column=1, columnspan=2, sticky="w")
        self.w_fire.bind("<<ComboboxSelected>>", self._wave_apply)
        ttk.Label(d, text="aimed shots sample the ship's position when they are "
                          "fired and do not follow it",
                  font=("TkDefaultFont", 9), wraplength=PROG_TEXT_WRAP,
                  justify="left").grid(row=r + 1, column=3, sticky="w",
                                       padx=(8, 0))
        self.w_used = ttk.Label(d, text="", font=("TkDefaultFont", 9))
        self.w_used.grid(row=r + 2, column=0, columnspan=4, sticky="w", pady=(6, 0))

    # --------------------------------------------------------------- programs
    def _build_programs(self, nb):
        f = ttk.Frame(nb, padding=6)
        nb.add(f, text="Movement programs (shared)")
        f.columnconfigure(1, weight=1)
        f.rowconfigure(0, weight=1)

        left = ttk.Frame(f)
        left.grid(row=0, column=0, rowspan=2, sticky="ns")
        left.rowconfigure(0, weight=1)
        self.prog_list = tk.Listbox(left, width=16, exportselection=False)
        self.prog_list.grid(row=0, column=0, sticky="ns")
        self.prog_list.bind("<<ListboxSelect>>", self._prog_selected)
        # TWO BY TWO. Four buttons on one line made this column demand 420px
        # of a 525px tab, leaving the authoring frame beside it 85 -- which is
        # why the movement controls vanished. The list itself needs far less.
        pb = ttk.Frame(left)
        pb.grid(row=1, column=0, sticky="ew", pady=(4, 0))
        for i, (txt, cmd) in enumerate(
                (("Add", self._prog_add), ("Dup", self._prog_duplicate),
                 ("Rename", self._prog_rename), ("Del", self._prog_delete))):
            ttk.Button(pb, text=txt, width=7, command=cmd).grid(
                row=i // 2, column=i % 2, sticky="w", padx=1, pady=1)

        right = ttk.Frame(f)
        right.grid(row=0, column=1, rowspan=2, sticky="nsew", padx=(8, 0))
        right.columnconfigure(0, weight=1)
        right.rowconfigure(2, weight=1)

        # ---- the mode strip: what this program IS, and what it costs ----
        # THE LABEL AND THE BUTTONS GET SEPARATE ROWS. Packed on one line the
        # three buttons alone wanted 606px and the status label another 620,
        # so at a 13-inch window the buttons were squeezed to a single pixel
        # and simply vanished. Two rows always fit.
        ttk.Label(right, textvariable=self.prog_mode_text,
                  wraplength=PROG_TEXT_WRAP, justify="left",
                  font=("TkDefaultFont", 10)).grid(row=0, column=0, sticky="w")
        head = ttk.Frame(right)
        head.grid(row=1, column=0, sticky="ew", pady=(2, 4))
        # SHORT LABELS, because these share one row. The mode strip above
        # already says whether the program is semantic or raw, so the buttons
        # do not have to repeat it.
        self.prog_convert_btn = ttk.Button(head, text="Convert…", width=9,
                                           command=self._prog_make_semantic)
        self.prog_convert_btn.pack(side="left", padx=(0, 3))
        self.prog_raw_btn = ttk.Button(head, text="Raw", width=9,
                                       command=self._prog_toggle_raw)
        self.prog_raw_btn.pack(side="left", padx=3)
        self.prog_mirror_btn = ttk.Button(head, text="Mirror", width=6,
                                          command=self._prog_mirror)
        self.prog_mirror_btn.pack(side="left", padx=3)
        ttk.Label(right, textvariable=self.prog_cost_text,
                  wraplength=PROG_TEXT_WRAP, justify="left",
                  font=("TkDefaultFont", 9)).grid(row=3, column=0, sticky="w")

        # SEMANTIC AND RAW ARE TWO VIEWS OF THE SAME PROGRAM, gridded into one
        # cell and raised as needed. Keeping the raw editor intact matters: a
        # program that cannot be said in segments has to stay editable, and so
        # does the ability to look at the four bytes when debugging.
        # EXACTLY ONE IS MAPPED AT A TIME, via grid_remove rather than
        # tkraise. Both mapped in the same cell means the cell has to satisfy
        # BOTH requested widths at once, and with a weighted column either
        # side of it the layout oscillates and Tk's update() never returns.
        # Showing one and removing the other makes the cell answer to the view
        # the author is actually looking at.
        self.sem_view = ttk.Frame(right)
        self.raw_view = ttk.Frame(right)
        for w in (self.sem_view, self.raw_view):
            w.grid(row=2, column=0, sticky="nsew")
            w.columnconfigure(0, weight=1)
            w.rowconfigure(0, weight=1)
            w.grid_remove()
        self._build_segments(self.sem_view)
        self._build_raw_stages(self.raw_view)

    # ------------------------------------------------- the semantic view
    def _build_segments(self, right):
        self.seg_tree = ttk.Treeview(right, columns=("n", "seg", "detail"),
                                     show="headings", selectmode="browse",
                                     height=8)
        for cid, txt, w in (("n", "#", 40), ("seg", "segment", 210),
                            ("detail", "what it does", 520)):
            self.seg_tree.heading(cid, text=txt)
            self.seg_tree.column(cid, width=w, anchor="w",
                                 stretch=(cid == "detail"))
        self.seg_tree.grid(row=0, column=0, sticky="nsew")
        self.seg_tree.bind("<<TreeviewSelect>>", self._seg_selected)

        # TWO ROWS, NOT ONE. Seven buttons on a line wanted 889px and the
        # column has 579 at a 13-inch window, so the last two -- Move up and
        # Move down -- were clipped to nothing. A grid wraps them and every
        # control stays readable at every supported size.
        bar = ttk.Frame(right)
        bar.grid(row=1, column=0, sticky="ew", pady=(4, 2))
        for i, (txt, cmd, bw) in enumerate((
                ("Add", lambda: self._seg_add(None), 6),
                ("Insert before", lambda: self._seg_add("before"), 13),
                ("Insert after", lambda: self._seg_add("after"), 12),
                ("Duplicate", self._seg_duplicate, 10),
                ("Delete", self._seg_delete, 7),
                ("▲ Move up", lambda: self._seg_move(-1), 11),
                ("▼ Move down", lambda: self._seg_move(1), 13))):
            ttk.Button(bar, text=txt, width=bw, command=cmd).grid(
                row=i // 4, column=i % 4, sticky="w", padx=1, pady=1)

        mac = ttk.Frame(right)
        mac.grid(row=2, column=0, sticky="ew", pady=(0, 4))
        ttk.Label(mac, text="manoeuvre").pack(side="left")
        self.macro_box = ttk.Combobox(mac, state="readonly", width=15,
                                      values=sorted(sem.MACROS))
        self.macro_box.pack(side="left", padx=(4, 2))
        ttk.Button(mac, text="Insert", width=7,
                   command=self._macro_insert).pack(side="left")
        ttk.Label(mac, text="— expands into segments, so its cost is "
                           "visible immediately", wraplength=320,
                  justify="left",
                  font=("TkDefaultFont", 8)).pack(side="left", padx=(6, 0))

        d = ttk.LabelFrame(right, text="Selected segment", padding=6)
        d.grid(row=3, column=0, sticky="ew")
        ttk.Label(d, text="segment").grid(row=0, column=0, sticky="w")
        self.g_kind = ttk.Combobox(d, state="readonly", width=12,
                                   values=list(sem.KINDS))
        self.g_kind.grid(row=0, column=1, sticky="w")
        self.g_kind.bind("<<ComboboxSelected>>", self._seg_kind_changed)

        # One payload form per kind, in the same cell. A segment shows only
        # what it actually means -- and NO ENTRY HEADING ANYWHERE, because a
        # relative turn does not have one.
        self.g_straight = ttk.Frame(d)
        self.g_turn = ttk.Frame(d)
        self.g_hold = ttk.Frame(d)
        self.g_none = ttk.Label(
            d, text="EXIT carries on out of the world on whatever heading and "
                    "speed it inherits.", wraplength=PROG_TEXT_WRAP,
            justify="left", font=("TkDefaultFont", 9))
        for w in (self.g_straight, self.g_turn, self.g_hold, self.g_none):
            w.grid(row=1, column=0, columnspan=6, sticky="w", pady=(4, 0))

        self.g_fields = {}

        ttk.Label(self.g_straight, text="frames").grid(row=0, column=0, sticky="w")
        e = ttk.Entry(self.g_straight, width=7)
        e.grid(row=0, column=1, sticky="w", padx=(2, 10))
        e.bind("<Return>", self._seg_apply)
        e.bind("<FocusOut>", self._seg_apply)
        self.g_fields["frames"] = e

        # CONTINUE IS THE DEFAULT AND SHOULD LOOK LIKE IT. The dial only comes
        # alive when the author chooses to establish a direction, so the
        # ordinary case stays a frame count and nothing else.
        self.g_dir_mode = tk.StringVar(value="Continue")
        for i, mode in enumerate(("Continue", "Set direction")):
            ttk.Radiobutton(self.g_straight, text=mode, value=mode,
                            variable=self.g_dir_mode,
                            command=self._seg_dir_mode).grid(
                                row=0, column=2 + i, sticky="w", padx=(0, 8))
        ttk.Label(self.g_straight,
                  text="Continue flies on along whatever the segment before "
                       "produced \u2014 or the wave's launch direction, if this "
                       "is the first segment",
                  wraplength=PROG_TEXT_WRAP, justify="left",
                  font=("TkDefaultFont", 8)).grid(row=1, column=0, columnspan=4,
                                                  sticky="w")
        self.g_compass = CompassDial(self.g_straight,
                                     command=self._seg_compass)
        self.g_compass.grid(row=2, column=0, columnspan=4, sticky="w",
                            pady=(4, 0))

        ttk.Label(self.g_turn, text="direction").grid(row=0, column=0, sticky="w")
        self.g_dir = ttk.Combobox(self.g_turn, state="readonly", width=7,
                                  values=list(sem.DIRECTIONS))
        self.g_dir.grid(row=0, column=1, sticky="w", padx=(2, 8))
        self.g_dir.bind("<<ComboboxSelected>>", self._seg_apply)
        ttk.Label(self.g_turn, text="turn").grid(row=0, column=2, sticky="w")
        self.g_angle = ttk.Combobox(self.g_turn, state="readonly", width=18,
                                    values=ANGLE_CHOICES)
        self.g_angle.grid(row=0, column=3, sticky="w", padx=(2, 8))
        self.g_angle.bind("<<ComboboxSelected>>", self._seg_angle_changed)
        ttk.Label(self.g_turn, text="radius").grid(row=0, column=4, sticky="w")
        self.g_radius = ttk.Combobox(self.g_turn, state="readonly", width=9,
                                     values=RADIUS_CHOICES)
        self.g_radius.grid(row=0, column=5, sticky="w", padx=(2, 8))
        self.g_radius.bind("<<ComboboxSelected>>", self._seg_apply)
        ttk.Label(self.g_turn, text="steps").grid(row=0, column=6, sticky="w")
        e = ttk.Entry(self.g_turn, width=5)
        e.grid(row=0, column=7, sticky="w", padx=(2, 0))
        e.bind("<Return>", self._seg_apply)
        e.bind("<FocusOut>", self._seg_apply)
        self.g_fields["steps"] = e
        ttk.Label(self.g_turn,
                  text="turns relative to the heading it arrives on; one step "
                       "is 5.625°", wraplength=PROG_TEXT_WRAP, justify="left",
                  font=("TkDefaultFont", 8)).grid(row=1, column=0, columnspan=8,
                                                  sticky="w")

        for i, (key, label) in enumerate((("frames", "frames"),
                                          ("drift", "drift"))):
            ttk.Label(self.g_hold, text=label).grid(row=0, column=i * 2, sticky="w")
            e = ttk.Entry(self.g_hold, width=6)
            e.grid(row=0, column=i * 2 + 1, sticky="w", padx=(2, 8))
            e.bind("<Return>", self._seg_apply)
            e.bind("<FocusOut>", self._seg_apply)
            self.g_fields["hold_" + key] = e
        ttk.Label(self.g_hold,
                  text="stay put for a while; a drift keeps it creeping "
                       "ALONG the heading it holds, in quarter pixels a frame",
                  wraplength=PROG_TEXT_WRAP,
                  justify="left",
                  font=("TkDefaultFont", 8)).grid(row=1, column=0, columnspan=6,
                                                  sticky="w")

    # ------------------------------------------------------- the raw view
    def _build_raw_stages(self, right):
        self.stage_tree = ttk.Treeview(right, columns=("n", "kind", "detail"),
                                       show="headings", selectmode="browse",
                                       height=8)
        for cid, txt, w in (("n", "#", 40), ("kind", "kind", 120),
                            ("detail", "payload", 560)):
            self.stage_tree.heading(cid, text=txt)
            self.stage_tree.column(cid, width=w, anchor="w",
                                   stretch=(cid == "detail"))
        self.stage_tree.grid(row=0, column=0, sticky="nsew")
        self.stage_tree.bind("<<TreeviewSelect>>", self._stage_selected)

        sb = ttk.Frame(right)
        sb.grid(row=1, column=0, sticky="ew", pady=(4, 6))
        for txt, cmd in (("Add stage", self._stage_add),
                         ("Delete", self._stage_delete),
                         ("Move up", lambda: self._stage_move(-1)),
                         ("Move down", lambda: self._stage_move(1))):
            ttk.Button(sb, text=txt, width=11, command=cmd).pack(side="left", padx=1)
        # THE ONE-BYTE FIX for a raw arc that snaps. Shown only when there is
        # something to fix, so it reads as an answer to a problem the row
        # above has already named rather than as another button.
        self.stage_fix_btn = ttk.Button(sb, text="Make continuous", width=16,
                                        command=self._stage_make_continuous)
        self.stage_kink_text = tk.StringVar()
        ttk.Label(right, textvariable=self.stage_kink_text, foreground=COL_WARN,
                  wraplength=PROG_TEXT_WRAP, justify="left",
                  font=("TkDefaultFont", 9)).grid(row=3, column=0, sticky="w")

        sd = ttk.LabelFrame(right, text="Selected stage", padding=6)
        sd.grid(row=2, column=0, sticky="ew")
        ttk.Label(sd, text="kind").grid(row=0, column=0, sticky="w")
        self.s_kind = ttk.Combobox(sd, state="readonly", width=13,
                                   values=sorted(C.MOVEMENT_KINDS))
        self.s_kind.grid(row=0, column=1, sticky="w")
        self.s_kind.bind("<<ComboboxSelected>>", self._stage_kind_changed)

        # Two payload forms, gridded into the same cells and raised as needed:
        # a stage shows only controls its opcode actually reads.
        self.s_timed = ttk.Frame(sd)
        self.s_arc = ttk.Frame(sd)
        self.s_none = ttk.Label(sd, text="EXIT is terminal and carries no payload.",
                                font=("TkDefaultFont", 9))
        for w in (self.s_timed, self.s_arc, self.s_none):
            w.grid(row=1, column=0, columnspan=4, sticky="w", pady=(4, 0))

        self.s_fields = {}
        for i, (key, label, hint) in enumerate(
                (("frames", "frames", ""),
                 ("vx", "vx", f"quarter px/frame, ±{C.MAX_ABS_VX}"),
                 ("vy", "vy", f"quarter px/frame, ±{C.MAX_ABS_VX}"))):
            ttk.Label(self.s_timed, text=label).grid(row=0, column=i * 3, sticky="w")
            e = ttk.Entry(self.s_timed, width=6)
            e.grid(row=0, column=i * 3 + 1, sticky="w", padx=(2, 2))
            e.bind("<Return>", self._stage_apply)
            e.bind("<FocusOut>", self._stage_apply)
            self.s_fields[key] = e
            if hint:
                ttk.Label(self.s_timed, text=hint, font=("TkDefaultFont", 8)).grid(
                    row=1, column=i * 3, columnspan=2, sticky="w")

        for i, (key, label) in enumerate((("steps", "heading steps"),
                                          ("frames_per_step", "frames/step"))):
            ttk.Label(self.s_arc, text=label).grid(row=0, column=i * 2, sticky="w")
            e = ttk.Entry(self.s_arc, width=6)
            e.grid(row=0, column=i * 2 + 1, sticky="w", padx=(2, 8))
            e.bind("<Return>", self._stage_apply)
            e.bind("<FocusOut>", self._stage_apply)
            self.s_fields[key] = e
        ttk.Label(self.s_arc, text="entry heading").grid(row=0, column=4, sticky="w")
        # CONT IS A REAL CHOICE IN THE LIST, not a magic 255 the author types.
        self.s_heading = ttk.Combobox(self.s_arc, state="readonly", width=7,
                                      values=HEADINGS)
        self.s_heading.grid(row=0, column=5, sticky="w", padx=(2, 0))
        self.s_heading.bind("<<ComboboxSelected>>", self._stage_apply)
        ttk.Label(self.s_arc,
                  text="CONT continues from the heading already held",
                  font=("TkDefaultFont", 8)).grid(row=1, column=0, columnspan=6,
                                                  sticky="w")

    # =====================================================================
    # edit plumbing -- every mutation goes through here
    # =====================================================================
    def _edit(self, fn, *a, **kw):
        """Run one model operation inside the host's undo/dirty machinery.

        The snapshot is taken BEFORE and pushed only if something changed, so
        selecting, opening and cancelling never mark the project dirty.
        """
        before = self.host._project_state()
        try:
            result = fn(*a, **kw)
        except ControllerError as exc:
            messagebox.showerror("Cannot do that", str(exc), parent=self)
            return None
        if self.host._project_state() != before:
            self.host._push_undo(before)
            self.host._after_encounter_edit()
        self.refresh()
        return result

    def adopt(self, controller):
        """Follow the host onto a different document."""
        self.controller = controller
        self.sel_trigger = self.sel_wave = self.sel_prog = self.sel_stage = None
        self.sel_segment = None
        self.title(f"Encounters — {controller.project.name}")
        # A preview left running would go on animating a wave belonging to the
        # document that was just closed.
        self.preview.pause()
        self.preview.set_source(None)
        self.refresh()

    def _close(self):
        self.preview.pause()        # never leave an after() job behind
        self.host._encounters = None
        self.destroy()

    # =====================================================================
    # refresh
    # =====================================================================
    def refresh(self):
        self._syncing = True
        try:
            self._refresh_status()
            self._refresh_triggers()
            self._refresh_waves()
            self._refresh_programs()
            self._refresh_issues()
            self._draw_timeline()
        finally:
            self._syncing = False
        # AFTER the sync flag is down, and last. The preview reads the live
        # project, so it must not run while half the widgets have been
        # repopulated -- and it re-flies the wave only if what it depends on
        # actually changed (see PreviewPanel._signature).
        self._sync_preview_source()

    def _sync_preview_source(self):
        """Point the preview at whatever tab and row the author is on.

        The TRIGGER is the most contextual, because it is the only selection
        that resolves the whole authored chain -- species included, which is
        what decides whether an ordinary-wave preview is honest at all.
        """
        if not hasattr(self, "preview") or not self.preview.winfo_exists():
            return
        try:
            tab = self.tabs.index(self.tabs.select())
        except tk.TclError:
            tab = 0
        proj = self.controller.project
        source = None
        if tab == 0 and self.sel_trigger is not None and (
                0 <= self.sel_trigger < len(proj.triggers)):
            source = ("trigger", self.sel_trigger)
        elif tab == 1 and self.sel_wave is not None and (
                0 <= self.sel_wave < len(proj.wave_definitions)):
            source = ("wave", proj.wave_definitions[self.sel_wave].id)
        elif tab == 2 and self.sel_prog is not None and (
                0 <= self.sel_prog < len(proj.movement_programs)):
            source = ("program", proj.movement_programs[self.sel_prog].id)
        self.preview.set_source(source)
        self.preview.refresh()

    def _refresh_status(self):
        cap = self.controller.capacity()
        def part(label, key):
            used, limit = cap[key]
            flag = "  ⚠" if used > limit * 0.9 else ""
            return f"{label} {used}/{limit}{flag}"
        self.status_text.set("   ·   ".join((
            part("triggers", "triggers"),
            part("wave defs", "waveDefinitions"),
            part("movement records", "movementRecords"),
            part("movement bytes", "movementBytes"))))
        q = self.controller.quiet_zone()
        self.quiet_text.set(
            f"quiet zone {q['rows']} rows ≈ {q['seconds']}s   "
            f"(stage ends {q['playableProgress']})")
        self.no_spawn_var.set(str(q["noSpawnRow"]))

    # ---- triggers --------------------------------------------------------
    def _refresh_triggers(self):
        tree = self.trig_tree
        tree.delete(*tree.get_children())
        for i, t in enumerate(self.controller.project.triggers):
            fires = ", ".join(str(m) for m in t.fire_mask) or "—"
            side = t.dropper_side if t.species == "DROPPER" else "—"
            tree.insert("", "end", iid=str(i),
                        values=(t.world_progress, t.wave_definition,
                                t.species, fires, side))
        if self.sel_trigger is not None and str(self.sel_trigger) in tree.get_children():
            tree.selection_set(str(self.sel_trigger))
        self._refresh_trigger_detail()

    def _refresh_trigger_detail(self):
        ts = self.controller.project.triggers
        ids = [d.id for d in self.controller.project.wave_definitions]
        self.t_wave["values"] = ids
        if self.sel_trigger is None or not (0 <= self.sel_trigger < len(ts)):
            for w in (self.t_prog,):
                w.delete(0, "end")
            self.t_wave.set(""); self.t_species.set(""); self.t_side.set("")
            self.t_where.configure(text="")
            self.t_fire_note.configure(text="")
            for child in self.t_fire.winfo_children():
                child.destroy()
            return
        t = ts[self.sel_trigger]
        self.t_prog.delete(0, "end"); self.t_prog.insert(0, str(t.world_progress))
        self.t_wave.set(t.wave_definition)
        self.t_species.set(t.species)
        self.t_side.set(t.dropper_side)
        # A RING carries a side and ignores it, so the control is disabled
        # rather than inviting a meaningless choice.
        self.t_side.configure(state="readonly" if t.species == "DROPPER" else "disabled")

        # Where the moment falls, in terrain terms -- DISPLAY ONLY. The authored
        # value is worldProgress; no converted coordinate is stored.
        st = self.controller.project.stage
        logical = st.logical_rows - 1 - t.world_progress
        self.t_where.configure(
            text=f"(logical row {logical}, metatile row ≈ {max(0, logical) // C.METATILE_H})"
            if 0 <= logical else "(past the start of the stage)")

        self._rebuild_fire_boxes(t)

    def _rebuild_fire_boxes(self, t):
        for child in self.t_fire.winfo_children():
            child.destroy()
        self._fire_vars = []
        count = self.controller.trigger_members(self.sel_trigger)
        for m in range(max(count, 0)):
            v = tk.IntVar(value=1 if m in t.fire_mask else 0)
            cb = ttk.Checkbutton(self.t_fire, text=str(m), variable=v,
                                 command=self._fire_changed)
            cb.pack(side="left")
            self._fire_vars.append((m, v))
        impossible = self.controller.impossible_fire_members(self.sel_trigger)
        if not count:
            self.t_fire_note.configure(
                text="the referenced wave definition does not exist", foreground=COL_ERROR)
        elif impossible:
            self.t_fire_note.configure(
                text=f"members {', '.join(map(str, impossible))} are not sent by this "
                     f"wave ({count} members) — use Trim to remove them",
                foreground=COL_ERROR)
            ttk.Button(self.t_fire, text="Trim", width=6,
                       command=self._fire_trim).pack(side="left", padx=(8, 0))
        else:
            self.t_fire_note.configure(
                text=f"wave sends {count} member(s)", foreground="")

    # ---- waves -----------------------------------------------------------
    def _refresh_waves(self):
        lb = self.wave_list
        lb.delete(0, "end")
        for d in self.controller.project.wave_definitions:
            lb.insert("end", f"{d.id}  ({d.count}×)")
        if self.sel_wave is not None and 0 <= self.sel_wave < lb.size():
            lb.selection_clear(0, "end"); lb.selection_set(self.sel_wave)
        self._refresh_wave_detail()

    def _refresh_wave_detail(self):
        ds = self.controller.project.wave_definitions
        self.w_prog["values"] = [p.id for p in self.controller.project.movement_programs]
        if self.sel_wave is None or not (0 <= self.sel_wave < len(ds)):
            for e in self.w_fields.values():
                e.delete(0, "end")
            self.w_head_text.set("")
            self.w_prog.set("")
            self.w_used.configure(text="")
            return
        d = ds[self.sel_wave]
        for key, e in self.w_fields.items():
            e.delete(0, "end"); e.insert(0, str(getattr(d, key)))
        self.w_compass.set_heading(d.heading)
        self.w_head_text.set(self._describe_heading(d.heading))
        self.w_prog.set(d.movement_program)
        self.w_fire.set(C.FIRE_MODE_LABELS.get(d.fire_mode, d.fire_mode))
        users = self.controller.triggers_using_definition(d.id)
        rows = ", ".join(str(self.controller.project.triggers[i].world_progress)
                         for i in users)
        self.w_used.configure(
            text=(f"used by {len(users)} trigger(s) at worldProgress {rows}"
                  if users else "used by no trigger yet"))

    # ---- programs --------------------------------------------------------
    def _refresh_programs(self):
        lb = self.prog_list
        lb.delete(0, "end")
        for p in self.controller.project.movement_programs:
            lb.insert("end", f"{p.id}  ({len(p.stages)})")
        if self.sel_prog is not None and 0 <= self.sel_prog < lb.size():
            lb.selection_clear(0, "end"); lb.selection_set(self.sel_prog)
        self._refresh_stages()

    def _refresh_stages(self):
        tree = self.stage_tree
        tree.delete(*tree.get_children())
        progs = self.controller.project.movement_programs
        if self.sel_prog is None or not (0 <= self.sel_prog < len(progs)):
            self._show_stage_form(None)
            self._refresh_program_mode()
            return
        for i, st in enumerate(progs[self.sel_prog].stages):
            tree.insert("", "end", iid=str(i),
                        values=(i, st.kind, self._stage_detail(st)))
        if self.sel_stage is not None and str(self.sel_stage) in tree.get_children():
            tree.selection_set(str(self.sel_stage))
        self._refresh_stage_detail()
        self._refresh_kinks()
        self._refresh_segments()
        self._refresh_program_mode()

    def _refresh_kinks(self):
        """Say where a raw program's path changes direction instantaneously.

        SAID OUT LOUD, because it is invisible in the records: the four bytes
        of an arc look perfectly ordinary and the kink only exists once the
        path is flown. The preview shows it faithfully -- this names it.
        """
        self.stage_fix_btn.pack_forget()
        self.stage_kink_text.set("")
        progs = self.controller.project.movement_programs
        if self.sel_prog is None or not (0 <= self.sel_prog < len(progs)):
            return
        breaks = {b["stage"]: b for b in
                  self.controller.program_continuity(self.sel_prog)}
        for iid in self.stage_tree.get_children():
            b = breaks.get(int(iid))
            if b:
                vals = list(self.stage_tree.item(iid, "values"))
                vals[2] = f"\u26a0 {vals[2]}"
                self.stage_tree.item(iid, values=vals)
        b = breaks.get(self.sel_stage)
        if b is None:
            return
        self.stage_kink_text.set(
            f"\u26a0 the path kinks {b['degrees']:.0f}\u00b0 here: the object "
            f"arrives travelling on heading {b['travel_heading']} but this "
            f"stage starts on heading {b['stored_heading']}. A STRAIGHT or "
            f"HOLD sets a velocity without updating the heading, so \u201cCONT"
            f"\u201d continues from a heading that has gone stale.")
        if b["to_kind"] in C.ARC_KINDS and b["travel_heading"] is not None:
            self.stage_fix_btn.pack(side="left", padx=(8, 1))

    def _stage_make_continuous(self):
        if self.sel_prog is None or self.sel_stage is None:
            return
        self._edit(self.controller.make_stage_continuous,
                   self.sel_prog, self.sel_stage)

    # ================================================================
    # the semantic view
    # ================================================================
    def _show_view(self, which):
        """Map exactly one of the two program views. See _build_programs."""
        for v in (self.sem_view, self.raw_view):
            if v is which:
                v.grid()
            else:
                v.grid_remove()

    def _refresh_program_mode(self):
        """The mode strip: what this program is, what it costs, which buttons
        make sense."""
        progs = self.controller.project.movement_programs
        if self.sel_prog is None or not (0 <= self.sel_prog < len(progs)):
            self.prog_mode_text.set("")
            self.prog_cost_text.set("")
            for b in (self.prog_convert_btn, self.prog_raw_btn,
                      self.prog_mirror_btn):
                b.state(["disabled"])
            self._show_view(self.raw_view)
            return
        prog = progs[self.sel_prog]
        cost = self.controller.program_cost(self.sel_prog)
        cap = self.controller.capacity()
        used_r, max_r = cap["movementRecords"]
        used_b, max_b = cap["movementBytes"]

        if prog.is_semantic:
            heading, note = self.controller.program_launch_heading(self.sel_prog)
            free = "" if sem.heading_dependent(prog.segments) else \
                "  · heading-free, so it serves any launch heading"
            self.prog_mode_text.set(
                f"{prog.id}  —  semantic, launched on heading {heading}{free}")
            # NEVER HIDE THE EXPANSION. Segments are what was written, records
            # are what the C64 pays for, and a macro makes them differ.
            self.prog_cost_text.set(
                f"{cost['segments']} semantic segments → "
                f"{cost['records']} engine records / {cost['bytes']} bytes"
                f"      project pool {used_r}/{max_r} records, "
                f"{used_b}/{max_b} bytes"
                + (f"      ⚠ {note}" if note else ""))
            self.prog_convert_btn.state(["disabled"])
            self.prog_mirror_btn.state(["!disabled"])
            self.prog_raw_btn.configure(
                text="Segments" if self.show_raw else "Raw")
            self.prog_raw_btn.state(["!disabled"])
            self._show_view(self.raw_view if self.show_raw else self.sem_view)
        else:
            self.prog_mode_text.set(
                f"{prog.id}  —  raw engine records")
            self.prog_cost_text.set(
                f"{cost['records']} engine records / {cost['bytes']} bytes"
                f"      project pool {used_r}/{max_r} records, "
                f"{used_b}/{max_b} bytes")
            self.prog_convert_btn.state(["!disabled"])
            self.prog_mirror_btn.state(["disabled"])
            self.prog_raw_btn.state(["disabled"])
            self._show_view(self.raw_view)

    def _refresh_segments(self):
        tree = self.seg_tree
        tree.delete(*tree.get_children())
        progs = self.controller.project.movement_programs
        if self.sel_prog is None or not (0 <= self.sel_prog < len(progs)):
            self._show_segment_form(None)
            return
        prog = progs[self.sel_prog]
        heading, _n = self.controller.program_launch_heading(self.sel_prog)
        for i, seg in enumerate(prog.segments):
            tree.insert("", "end", iid=str(i),
                        values=(i + 1, seg.describe(),
                                self._segment_detail(seg, prog.segments[:i],
                                                     heading)))
        if (self.sel_segment is not None
                and str(self.sel_segment) in tree.get_children()):
            tree.selection_set(str(self.sel_segment))
        self._refresh_segment_detail()

    @staticmethod
    def _segment_detail(seg, before, launch):
        """The plain-English consequence, including the state it inherits.

        SHOWING THE INHERITED HEADING IS THE POINT -- it is what the author no
        longer has to work out, so seeing it confirms the continuity rather
        than asking them to supply it. It is a readout, never an input.
        """
        h = sem.final_heading(before, launch)
        if seg.kind == "STRAIGHT":
            return f"fly on, on heading {h}, for {seg.frames} frames"
        if seg.kind == "TURN":
            end = sem.final_heading(list(before) + [seg], launch)
            return (f"from heading {h}, turn {seg.direction.lower()} "
                    f"{sem.degrees(seg.steps)}° to heading {end}")
        if seg.kind == "HOLD":
            drift = ("" if not seg.drift
                     else f", creeping on at {seg.drift} quarter-px/frame")
            return f"stay put for {seg.frames} frames{drift}"
        return f"leave the world on heading {h}"

    def _show_segment_form(self, kind):
        for w in (self.g_straight, self.g_turn, self.g_hold, self.g_none):
            w.grid_remove()
        if kind == "STRAIGHT":
            self.g_straight.grid()
        elif kind == "TURN":
            self.g_turn.grid()
        elif kind == "HOLD":
            self.g_hold.grid()
        elif kind == "EXIT":
            self.g_none.grid()

    def _refresh_segment_detail(self):
        progs = self.controller.project.movement_programs
        if (self.sel_prog is None or self.sel_segment is None
                or not (0 <= self.sel_prog < len(progs))
                or not (0 <= self.sel_segment < len(progs[self.sel_prog].segments))):
            self.g_kind.set("")
            self._show_segment_form(None)
            return
        seg = progs[self.sel_prog].segments[self.sel_segment]
        self.g_kind.set(seg.kind)
        self._show_segment_form(seg.kind)
        if seg.kind == "STRAIGHT":
            _put(self.g_fields["frames"], seg.frames)
            explicit = seg.heading is not None
            self.g_dir_mode.set("Set direction" if explicit else "Continue")
            self.g_compass.set_enabled(explicit)
            self.g_compass.set_heading(
                seg.heading if explicit
                else self.controller.segment_incoming_heading(
                    self.sel_prog, self.sel_segment))
        elif seg.kind == "TURN":
            self.g_dir.set(seg.direction)
            _put(self.g_fields["steps"], seg.steps)
            label = next((k for k, v in ANGLE_STEPS.items() if v == seg.steps),
                         "custom")
            self.g_angle.set(label)
            self.g_radius.set(next((n for n, r in sem.RATE_PRESETS
                                    if r == seg.rate), "custom"))
        elif seg.kind == "HOLD":
            _put(self.g_fields["hold_frames"], seg.frames)
            _put(self.g_fields["hold_drift"], seg.drift)

    # ---- segment commands ---------------------------------------------
    def _seg_selected(self, _e=None):
        if self._syncing:
            return
        sel = self.seg_tree.selection()
        self.sel_segment = int(sel[0]) if sel else None
        self._refresh_segment_detail()

    def _seg_add(self, where=None):
        if self.sel_prog is None:
            return
        at = None
        if where and self.sel_segment is not None:
            at = self.sel_segment + (1 if where == "after" else 0)
        i = self._edit(self.controller.add_segment, self.sel_prog, "STRAIGHT", at)
        if i is not None:
            self.sel_segment = i
            self.refresh()

    def _seg_duplicate(self):
        if self.sel_prog is None or self.sel_segment is None:
            return
        i = self._edit(self.controller.duplicate_segment, self.sel_prog,
                       self.sel_segment)
        if i is not None:
            self.sel_segment = i
            self.refresh()

    def _seg_delete(self):
        if self.sel_prog is None or self.sel_segment is None:
            return
        i = self._edit(self.controller.delete_segment, self.sel_prog,
                       self.sel_segment)
        if i is not None:
            self.sel_segment = i
            self.refresh()

    def _seg_move(self, delta):
        if self.sel_prog is None or self.sel_segment is None:
            return
        i = self._edit(self.controller.move_segment, self.sel_prog,
                       self.sel_segment, delta)
        if i is not None:
            self.sel_segment = i
            self.refresh()

    def _seg_kind_changed(self, _e=None):
        if self._syncing or self.sel_prog is None or self.sel_segment is None:
            return
        self._edit(self.controller.set_segment_kind, self.sel_prog,
                   self.sel_segment, self.g_kind.get())

    def _seg_angle_changed(self, _e=None):
        if self._syncing:
            return
        steps = ANGLE_STEPS.get(self.g_angle.get())
        if steps is not None:
            _put(self.g_fields["steps"], steps)
        self._seg_apply()

    def _seg_dir_mode(self):
        """Continue, or establish a direction. Nothing else changes."""
        if self._syncing or self.sel_prog is None or self.sel_segment is None:
            return
        progs = self.controller.project.movement_programs
        seg = progs[self.sel_prog].segments[self.sel_segment]
        if self.g_dir_mode.get() == "Continue":
            if seg.heading is None:
                return
            self._edit(self.controller.update_segment, self.sel_prog,
                       self.sel_segment, heading=None)
        else:
            if seg.heading is not None:
                return
            # Start from the direction it is ALREADY travelling, so turning
            # the modifier on does not move the path until the author drags.
            self._edit(self.controller.update_segment, self.sel_prog,
                       self.sel_segment,
                       heading=self.controller.segment_incoming_heading(
                           self.sel_prog, self.sel_segment))

    def _seg_compass(self, heading):
        if self._syncing or self.sel_prog is None or self.sel_segment is None:
            return
        self._edit(self.controller.update_segment, self.sel_prog,
                   self.sel_segment, heading=int(heading))

    def _seg_apply(self, _e=None):
        if self._syncing or self.sel_prog is None or self.sel_segment is None:
            return
        progs = self.controller.project.movement_programs
        if not (0 <= self.sel_segment < len(progs[self.sel_prog].segments)):
            return
        seg = progs[self.sel_prog].segments[self.sel_segment]
        if seg.kind == "STRAIGHT":
            fields = {"frames": _int_or(self.g_fields["frames"].get(), seg.frames)}
        elif seg.kind == "TURN":
            rate = RADIUS_RATE.get(self.g_radius.get(), seg.rate)
            fields = {"direction": self.g_dir.get() or seg.direction,
                      "steps": _int_or(self.g_fields["steps"].get(), seg.steps),
                      "rate": rate}
        elif seg.kind == "HOLD":
            fields = {"frames": _int_or(self.g_fields["hold_frames"].get(),
                                        seg.frames),
                      "drift": _int_or(self.g_fields["hold_drift"].get(),
                                       seg.drift)}
        else:
            return
        # AN APPLY THAT CHANGES NOTHING MUST DO NOTHING, and not only because
        # it is wasteful. These entries apply on <FocusOut>; refreshing
        # repopulates them, which moves focus, which fires <FocusOut> again --
        # so an unconditional edit here is an event loop that never settles.
        # Comparing first breaks it at the source.
        if all(getattr(seg, k) == v for k, v in fields.items()):
            return
        self._edit(self.controller.update_segment, self.sel_prog,
                   self.sel_segment, **fields)

    def _macro_insert(self):
        if self.sel_prog is None:
            return
        name = self.macro_box.get()
        if not name:
            return
        at = self.sel_segment + 1 if self.sel_segment is not None else None
        i = self._edit(self.controller.insert_macro, self.sel_prog, name, at)
        if i is not None:
            self.sel_segment = i
            self.refresh()

    # ---- program-level commands ---------------------------------------
    def _prog_toggle_raw(self):
        """Look at the four bytes, or go back to the segments.

        A VIEW, NOT A CONVERSION. Nothing is written either way -- which is
        why it does not go through _edit and cannot dirty the project.
        """
        self.show_raw = not self.show_raw
        self.refresh()

    def _prog_make_semantic(self):
        if self.sel_prog is None:
            return
        segs, why, same_bytes = self.controller.preview_make_semantic(self.sel_prog)
        prog = self.controller.project.movement_programs[self.sel_prog]
        if segs is None:
            # NOT A FAILURE, AND IT SHOULD NOT READ LIKE ONE. Some records
            # cannot be said as relative segments; staying raw is a supported
            # state, and the alternative on offer is destructive.
            if not messagebox.askyesno(
                    "Cannot convert without changing it",
                    f"{prog.id!r} cannot be expressed as semantic segments "
                    f"without changing what it does:\n\n{why}\n\n"
                    f"It can stay as raw engine records, which is perfectly "
                    f"valid and is how it is now.\n\n"
                    f"Start it again from scratch as segments instead? "
                    f"THIS DISCARDS the current records.",
                    parent=self, default="no"):
                return
            self._edit(self.controller.start_semantic, self.sel_prog)
            self.sel_segment = 0
            self.refresh()
            return
        lines = "\n".join(f"    {i + 1}. {s.describe()}"
                          for i, s in enumerate(segs))
        byte_note = (
            "The compiled bytes are unchanged."
            if same_bytes else
            "The flight is provably identical, but the compiled BYTES will "
            "change: this program's arcs name an absolute entry heading that "
            "happens to be the one already held, and a relative turn compiles "
            "to CONT instead. Nothing about how it flies changes.")
        if not messagebox.askyesno(
                "Convert to semantic segments",
                f"{prog.id!r} becomes:\n\n{lines}\n\n{byte_note}\n\nConvert?",
                parent=self):
            return
        self._edit(self.controller.make_semantic, self.sel_prog)
        self.sel_segment = 0
        self.refresh()

    def _prog_mirror(self):
        if self.sel_prog is None:
            return
        r = self._edit(self.controller.mirror_program, self.sel_prog)
        if r is None:
            return
        # THE OTHER HALF OF A MIRROR IS THE LAUNCH STATE, and it belongs to the
        # wave definition. Saying so is the whole point: silently rewriting a
        # wave the author did not select would be worse than not doing it.
        messagebox.showinfo(
            "Movement mirrored",
            f"Every turn now goes the other way.\n\n"
            f"That mirrors the MOVEMENT. For it to read as a reflection "
            f"across the screen, the wave that launches it also needs the "
            f"mirrored launch heading "
            f"{r['mirrored_launch_heading']} (it is currently "
            f"{r['current_launch_heading']}), and a spawn column mirrored "
            f"about the playfield.\n\n"
            f"Those live on the wave definition and have NOT been changed.",
            parent=self)
        self.refresh()

    @staticmethod
    def _stage_detail(st):
        if st.kind in C.TIMED_KINDS:
            return f"{st.frames} frames, vx {st.vx:+d}, vy {st.vy:+d}"
        if st.kind in C.ARC_KINDS:
            h = "CONT" if st.entry_heading == "CONT" else st.entry_heading
            return (f"{st.steps} steps, {st.frames_per_step} frames/step, "
                    f"entry {h}")
        return "terminal"

    def _refresh_stage_detail(self):
        progs = self.controller.project.movement_programs
        if (self.sel_prog is None or self.sel_stage is None
                or not (0 <= self.sel_prog < len(progs))
                or not (0 <= self.sel_stage < len(progs[self.sel_prog].stages))):
            self._show_stage_form(None)
            return
        st = progs[self.sel_prog].stages[self.sel_stage]
        self.s_kind.set(st.kind)
        if st.kind in C.TIMED_KINDS:
            for k in ("frames", "vx", "vy"):
                self.s_fields[k].delete(0, "end")
                self.s_fields[k].insert(0, str(getattr(st, k)))
        elif st.kind in C.ARC_KINDS:
            for k in ("steps", "frames_per_step"):
                self.s_fields[k].delete(0, "end")
                self.s_fields[k].insert(0, str(getattr(st, k)))
            self.s_heading.set("CONT" if st.entry_heading == "CONT"
                               else str(st.entry_heading))
        self._show_stage_form(st.kind)

    def _show_stage_form(self, kind):
        for w in (self.s_timed, self.s_arc, self.s_none):
            w.grid_remove()
        if kind in C.TIMED_KINDS:
            self.s_timed.grid()
        elif kind in C.ARC_KINDS:
            self.s_arc.grid()
        elif kind == "EXIT":
            self.s_none.grid()
        else:
            self.s_kind.set("")

    # ---- validation ------------------------------------------------------
    def _refresh_issues(self):
        tree = self.issues
        tree.delete(*tree.get_children())
        r = self.controller.validate()
        for kind, items, tag in (("ERROR", r.errors, "error"),
                                 ("warning", r.warnings, "warn")):
            for it in items:
                tree.insert("", "end", values=(kind, it.path or "", it.message),
                            tags=(tag,))
        if not r.errors and not r.warnings:
            tree.insert("", "end", values=("", "", "no validation issues"))

    def _issue_selected(self, _e=None):
        """Jump to whatever the selected issue is about."""
        sel = self.issues.selection()
        if not sel:
            return
        path = self.issues.item(sel[0], "values")[1] or ""
        idx = None
        if "[" in path:
            try:
                idx = int(path.split("[", 1)[1].split("]", 1)[0])
            except ValueError:
                idx = None
        if path.startswith("triggers") and idx is not None:
            self.sel_trigger = idx; self.tabs.select(0)
        elif path.startswith("waveDefinitions") and idx is not None:
            self.sel_wave = idx; self.tabs.select(1)
        elif path.startswith("movementPrograms"):
            if idx is not None:
                self.sel_prog = idx
                if ".stages[" in path:
                    try:
                        self.sel_stage = int(path.split(".stages[", 1)[1]
                                             .split("]", 1)[0])
                    except ValueError:
                        pass
            self.tabs.select(2)
        elif path.startswith("stage"):
            pass
        self.refresh()

    # =====================================================================
    # the timeline
    # =====================================================================
    def _tl_geometry(self):
        h = max(TL_MIN_H, int(self.canvas.winfo_height() or TL_MIN_H))
        playable = max(1, self.controller.project.stage.playable_progress)
        span = h - TL_PAD_TOP - TL_PAD_BOT
        return h, playable, span

    def _y_of(self, progress):
        _h, playable, span = self._tl_geometry()
        return TL_PAD_TOP + span * (progress / playable)

    def _progress_at(self, y):
        _h, playable, span = self._tl_geometry()
        return max(0, min(playable, round((y - TL_PAD_TOP) / span * playable)))

    def _draw_timeline(self):
        c = self.canvas
        c.delete("all")
        h, playable, _span = self._tl_geometry()
        st = self.controller.project.stage
        ns = st.no_spawn_row

        y0, y1 = self._y_of(0), self._y_of(playable)
        # the quiet zone, shaded, so "nothing may start here" is visible
        if 0 <= ns <= playable:
            c.create_rectangle(TL_AXIS_X - 6, self._y_of(ns), TL_W - 4, y1,
                               fill=COL_QUIET, outline="")
        c.create_line(TL_AXIS_X, y0, TL_AXIS_X, y1, fill=COL_AXIS, width=2)

        # ticks every 50 rows, labelled
        step = 50 if playable > 150 else 20
        p = 0
        while p <= playable:
            y = self._y_of(p)
            c.create_line(TL_AXIS_X - 4, y, TL_AXIS_X, y, fill=COL_TICK)
            c.create_text(TL_AXIS_X - 8, y, text=str(p), anchor="e",
                          fill=COL_TICK, font=("TkDefaultFont", 8))
            p += step
        c.create_text(TL_AXIS_X + 6, y0 - 10, text="stage start", anchor="w",
                      fill=COL_TICK, font=("TkDefaultFont", 8))
        c.create_text(TL_AXIS_X + 6, y1 + 12, text=f"boss / stage end  {playable}",
                      anchor="w", fill=COL_TICK, font=("TkDefaultFont", 8))

        if 0 <= ns <= playable:
            y = self._y_of(ns)
            c.create_line(TL_AXIS_X - 8, y, TL_W - 4, y, fill=COL_NOSPAWN,
                          width=2, dash=(4, 3))
            c.create_text(TL_W - 6, y - 8, text=f"noSpawn {ns}", anchor="e",
                          fill=COL_NOSPAWN, font=("TkDefaultFont", 8))

        for i, t in enumerate(self.controller.project.triggers):
            if not (0 <= t.world_progress <= playable):
                continue
            y = self._y_of(t.world_progress)
            colour = SPECIES_COLOUR.get(t.species, COL_TICK)
            selected = (i == self.sel_trigger)
            c.create_polygon(TL_AXIS_X, y, TL_AXIS_X + 9, y - 5, TL_AXIS_X + 9, y + 5,
                             fill=colour, outline=COL_SELECT if selected else "",
                             tags=("trig", f"trig{i}"))
            c.create_text(TL_AXIS_X + 13, y,
                          text=f"{t.world_progress}  {t.species}", anchor="w",
                          fill=COL_SELECT if selected else colour,
                          font=("TkDefaultFont", 8, "bold" if selected else "normal"),
                          tags=("trig", f"trig{i}"))
        c.configure(scrollregion=(0, 0, TL_W, h))

    def _timeline_click(self, event):
        """Select the nearest trigger marker; ignore empty space."""
        best, best_d = None, 1e9
        y = self.canvas.canvasy(event.y)
        for i, t in enumerate(self.controller.project.triggers):
            d = abs(self._y_of(t.world_progress) - y)
            if d < best_d:
                best, best_d = i, d
        if best is not None and best_d <= 8:
            self.sel_trigger = best
            self.tabs.select(0)
            self.refresh()

    # =====================================================================
    # callbacks
    # =====================================================================
    # ---- noSpawn ----------------------------------------------------------
    def _apply_no_spawn(self, _e=None):
        if self._syncing:
            return
        want = _int_or(self.no_spawn_var.get(),
                       self.controller.project.stage.no_spawn_row)
        if want == self.controller.project.stage.no_spawn_row:
            return
        self._edit(self.controller.set_no_spawn_row, want)

    # ---- trigger ----------------------------------------------------------
    def _trigger_selected(self, _e=None):
        if self._syncing:
            return
        sel = self.trig_tree.selection()
        self.sel_trigger = int(sel[0]) if sel else None
        self._refresh_trigger_detail()
        self._draw_timeline()
        self._sync_preview_source()

    def _trigger_add(self):
        n = len(self.controller.project.triggers)
        i = self._edit(self.controller.add_trigger)
        if i is not None and len(self.controller.project.triggers) > n:
            self.sel_trigger = i
            self.refresh()

    def _trigger_duplicate(self):
        if self.sel_trigger is None:
            return
        i = self._edit(self.controller.duplicate_trigger, self.sel_trigger)
        if i is not None:
            self.sel_trigger = i
            self.refresh()

    def _trigger_delete(self):
        if self.sel_trigger is None:
            return
        self._edit(self.controller.delete_trigger, self.sel_trigger)
        self.sel_trigger = None
        self.refresh()

    def _trigger_apply(self, _e=None):
        if self._syncing or self.sel_trigger is None:
            return
        t = self.controller.project.triggers[self.sel_trigger]
        fields = {
            "world_progress": _int_or(self.t_prog.get(), t.world_progress),
            "wave_definition": self.t_wave.get() or t.wave_definition,
            "species": self.t_species.get() or t.species,
        }
        if self.t_species.get() == "DROPPER" and self.t_side.get():
            fields["dropper_side"] = self.t_side.get()
        i = self._edit(self.controller.update_trigger, self.sel_trigger, **fields)
        if i is not None:
            self.sel_trigger = i
            self.refresh()

    def _fire_changed(self):
        if self._syncing or self.sel_trigger is None:
            return
        members = [m for m, v in self._fire_vars if v.get()]
        self._edit(self.controller.update_trigger, self.sel_trigger,
                   fire_mask=members)

    def _fire_trim(self):
        if self.sel_trigger is None:
            return
        gone = self.controller.impossible_fire_members(self.sel_trigger)
        if not gone or not messagebox.askyesno(
                "Trim fire mask",
                f"Remove member{'s' if len(gone) > 1 else ''} "
                f"{', '.join(map(str, gone))} from this trigger's fire mask?\n\n"
                "The referenced wave does not send them.", parent=self):
            return
        self._edit(self.controller.trim_fire_mask, self.sel_trigger)

    # ---- wave -------------------------------------------------------------
    def _wave_selected(self, _e=None):
        if self._syncing:
            return
        sel = self.wave_list.curselection()
        self.sel_wave = sel[0] if sel else None
        self._refresh_wave_detail()
        self._sync_preview_source()

    def _wave_compass_picked(self, heading):
        """Dragging the dial types its exact heading into the field.

        THE ENTRY REMAINS THE VALUE. The dial is a way of choosing a number,
        not a replacement for it -- the authored content uses headings 10 and
        12, which no eight-point picker would ever offer.
        """
        if self._syncing:
            return
        _put(self.w_fields["heading"], int(heading))
        self._wave_apply()

    def _describe_heading(self, h):
        """"Down (16)", or where an off-point heading sits between two."""
        h = int(h) % C.WM_HEAD_LEN
        name = sem.HEADING_COMPASS.get(h)
        if name:
            return f"launch heading: {name} ({h})"
        lo = (h // 8) * 8
        hi = (lo + 8) % C.WM_HEAD_LEN
        return (f"launch heading {h} \u2014 between "
                f"{sem.HEADING_COMPASS[lo]} and {sem.HEADING_COMPASS[hi]}")

    def _wave_add(self):
        i = self._edit(self.controller.add_wave_definition)
        if i is not None:
            self.sel_wave = i
            self.refresh()

    def _wave_duplicate(self):
        if self.sel_wave is None:
            return
        i = self._edit(self.controller.duplicate_wave_definition, self.sel_wave)
        if i is not None:
            self.sel_wave = i
            self.refresh()

    def _wave_rename(self):
        if self.sel_wave is None:
            return
        d = self.controller.project.wave_definitions[self.sel_wave]
        new = simpledialog.askstring("Rename wave definition",
                                     "New id:", initialvalue=d.id, parent=self)
        if not new or new == d.id:
            return
        moved = self._edit(self.controller.rename_wave_definition, self.sel_wave, new)
        if moved:
            self.host.status_text.set(
                f"renamed wave definition; {moved} trigger reference(s) updated")

    def _wave_delete(self):
        if self.sel_wave is None:
            return
        self._edit(self.controller.delete_wave_definition, self.sel_wave)
        self.sel_wave = None
        self.refresh()

    def _wave_apply(self, _e=None):
        if self._syncing or self.sel_wave is None:
            return
        d = self.controller.project.wave_definitions[self.sel_wave]
        fields = {k: _int_or(e.get(), getattr(d, k))
                  for k, e in self.w_fields.items()}
        if self.w_prog.get():
            fields["movement_program"] = self.w_prog.get()
        label = self.w_fire.get()
        for key, text in C.FIRE_MODE_LABELS.items():
            if text == label:
                fields["fire_mode"] = key
                break
        self._edit(self.controller.update_wave_definition, self.sel_wave, **fields)

    # ---- program / stage ---------------------------------------------------
    def _prog_selected(self, _e=None):
        if self._syncing:
            return
        sel = self.prog_list.curselection()
        self.sel_prog = sel[0] if sel else None
        self.sel_stage = None
        self.sel_segment = 0
        self._refresh_stages()
        self._sync_preview_source()

    def _prog_add(self):
        i = self._edit(self.controller.add_movement_program)
        if i is not None:
            self.sel_prog, self.sel_stage = i, 0
            self.refresh()

    def _prog_duplicate(self):
        if self.sel_prog is None:
            return
        i = self._edit(self.controller.duplicate_movement_program, self.sel_prog)
        if i is not None:
            self.sel_prog = i
            self.refresh()

    def _prog_rename(self):
        if self.sel_prog is None:
            return
        p = self.controller.project.movement_programs[self.sel_prog]
        new = simpledialog.askstring("Rename movement program",
                                     "New id:", initialvalue=p.id, parent=self)
        if not new or new == p.id:
            return
        moved = self._edit(self.controller.rename_movement_program,
                           self.sel_prog, new)
        if moved:
            self.host.status_text.set(
                f"renamed movement program; {moved} wave definition(s) updated")

    def _prog_delete(self):
        if self.sel_prog is None:
            return
        self._edit(self.controller.delete_movement_program, self.sel_prog)
        self.sel_prog = self.sel_stage = None
        self.refresh()

    def _stage_selected(self, _e=None):
        if self._syncing:
            return
        sel = self.stage_tree.selection()
        self.sel_stage = int(sel[0]) if sel else None
        self._refresh_stage_detail()
        self._refresh_kinks()

    def _stage_add(self):
        if self.sel_prog is None:
            return
        i = self._edit(self.controller.add_stage, self.sel_prog, "STRAIGHT")
        if i is not None:
            self.sel_stage = i
            self.refresh()

    def _stage_delete(self):
        if self.sel_prog is None or self.sel_stage is None:
            return
        self._edit(self.controller.delete_stage, self.sel_prog, self.sel_stage)
        self.sel_stage = None
        self.refresh()

    def _stage_move(self, delta):
        if self.sel_prog is None or self.sel_stage is None:
            return
        i = self._edit(self.controller.move_stage, self.sel_prog,
                       self.sel_stage, delta)
        if i is not None:
            self.sel_stage = i
            self.refresh()

    def _stage_kind_changed(self, _e=None):
        if self._syncing or self.sel_prog is None or self.sel_stage is None:
            return
        self._edit(self.controller.set_stage_kind, self.sel_prog,
                   self.sel_stage, self.s_kind.get())

    def _stage_apply(self, _e=None):
        if self._syncing or self.sel_prog is None or self.sel_stage is None:
            return
        st = self.controller.project.movement_programs[self.sel_prog].stages[self.sel_stage]
        fields = {}
        if st.kind in C.TIMED_KINDS:
            for k in ("frames", "vx", "vy"):
                fields[k] = _int_or(self.s_fields[k].get(), getattr(st, k))
        elif st.kind in C.ARC_KINDS:
            for k in ("steps", "frames_per_step"):
                fields[k] = _int_or(self.s_fields[k].get(), getattr(st, k))
            h = self.s_heading.get()
            fields["entry_heading"] = "CONT" if h == "CONT" else _int_or(
                h, st.entry_heading if st.entry_heading != "CONT" else 0)
        if fields:
            self._edit(self.controller.update_stage, self.sel_prog,
                       self.sel_stage, **fields)
