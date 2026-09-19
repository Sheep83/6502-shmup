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
from controller_v6 import ControllerError
from preview_ui import PreviewPanel

# --- timeline geometry ------------------------------------------------------
TL_W = 210                  # canvas width
TL_PAD_TOP = 18             # room for the "0" label
TL_PAD_BOT = 24             # ...and the stage-end one
TL_AXIS_X = 58              # where the vertical rule sits
TL_MIN_H = 320

COL_AXIS = "#7a7a7a"
COL_TICK = "#555555"
COL_RING = "#38d0ff"
COL_DROPPER = "#ffd000"
COL_SELECT = "#ffffff"
COL_NOSPAWN = "#ff40c0"
COL_QUIET = "#2a2a2a"
COL_ERROR = "#ff6060"
COL_WARN = "#e0a000"

SPECIES_COLOUR = {"RING": COL_RING, "DROPPER": COL_DROPPER}
HEADINGS = ["CONT"] + [str(i) for i in range(C.WM_HEAD_LEN)]


def _int_or(value, fallback):
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return fallback


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
        self.geometry("1620x800")
        self.minsize(1100, 640)
        self.protocol("WM_DELETE_WINDOW", self._close)

        self.sel_trigger = None
        self.sel_wave = None
        self.sel_prog = None
        self.sel_stage = None
        self._syncing = False          # suppress widget callbacks during refresh
        self._fire_vars = []

        self.status_text = tk.StringVar()
        self.quiet_text = tk.StringVar()
        self.no_spawn_var = tk.StringVar()

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
        nb.add(f, text="Wave definitions")
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
            ttk.Label(d, text=hint, font=("TkDefaultFont", 9)).grid(
                row=i, column=2, sticky="w", padx=(8, 0))
        r = len(rows)
        ttk.Label(d, text="movement program").grid(row=r, column=0, sticky="w")
        self.w_prog = ttk.Combobox(d, state="readonly", width=18)
        self.w_prog.grid(row=r, column=1, columnspan=2, sticky="w")
        self.w_prog.bind("<<ComboboxSelected>>", self._wave_apply)
        self.w_used = ttk.Label(d, text="", font=("TkDefaultFont", 9))
        self.w_used.grid(row=r + 1, column=0, columnspan=3, sticky="w", pady=(6, 0))

    # --------------------------------------------------------------- programs
    def _build_programs(self, nb):
        f = ttk.Frame(nb, padding=6)
        nb.add(f, text="Movement programs")
        f.columnconfigure(1, weight=1)
        f.rowconfigure(0, weight=1)

        left = ttk.Frame(f)
        left.grid(row=0, column=0, rowspan=2, sticky="ns")
        left.rowconfigure(0, weight=1)
        self.prog_list = tk.Listbox(left, width=20, exportselection=False)
        self.prog_list.grid(row=0, column=0, sticky="ns")
        self.prog_list.bind("<<ListboxSelect>>", self._prog_selected)
        pb = ttk.Frame(left)
        pb.grid(row=1, column=0, sticky="ew", pady=(4, 0))
        for txt, cmd in (("Add", self._prog_add), ("Dup", self._prog_duplicate),
                         ("Rename", self._prog_rename), ("Del", self._prog_delete)):
            ttk.Button(pb, text=txt, width=7, command=cmd).pack(side="left", padx=1)

        right = ttk.Frame(f)
        right.grid(row=0, column=1, rowspan=2, sticky="nsew", padx=(8, 0))
        right.columnconfigure(0, weight=1)
        right.rowconfigure(0, weight=1)

        self.stage_tree = ttk.Treeview(right, columns=("n", "kind", "detail"),
                                       show="headings", selectmode="browse",
                                       height=8)
        for cid, txt, w in (("n", "#", 36), ("kind", "kind", 110),
                            ("detail", "payload", 420)):
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
            self.w_prog.set("")
            self.w_used.configure(text="")
            return
        d = ds[self.sel_wave]
        for key, e in self.w_fields.items():
            e.delete(0, "end"); e.insert(0, str(getattr(d, key)))
        self.w_prog.set(d.movement_program)
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
            return
        for i, st in enumerate(progs[self.sel_prog].stages):
            tree.insert("", "end", iid=str(i),
                        values=(i, st.kind, self._stage_detail(st)))
        if self.sel_stage is not None and str(self.sel_stage) in tree.get_children():
            tree.selection_set(str(self.sel_stage))
        self._refresh_stage_detail()

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
        self._edit(self.controller.update_wave_definition, self.sel_wave, **fields)

    # ---- program / stage ---------------------------------------------------
    def _prog_selected(self, _e=None):
        if self._syncing:
            return
        sel = self.prog_list.curselection()
        self.sel_prog = sel[0] if sel else None
        self.sel_stage = None
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
