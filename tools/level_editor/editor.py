#!/usr/bin/env python3
"""19656 standalone Tkinter level editor -- the v6 GUI.

A level is a PACKAGE saved as levels/<name>/level.v6.json: terrain map,
palette, charset, metatile definitions, authored turrets, AND the encounter
data -- movement programs, wave definitions, absolute triggers and the no-spawn
boundary. The editor also shows an editor-only overlay of the real C64 gameplay
terrain aperture (40 chars x 23 logical rows, bottom-origin) so turret density
can be authored against true world coordinates.

THE DOCUMENT IS A ProjectV6, NOT A v5 LevelProject. `controller_v6` owns it and
every operation that has to preserve something goes through there; this file
owns widgets. See that module for why unexposed encounter data survives an edit
the GUI does not know how to make.

ENCOUNTERS ARE READ-ONLY HERE. The v5 attack-catalogue wave editor has been
removed rather than disabled: its twelve-id catalogue does not exist in the
engine any more, and pointing it at real movement programs, ten-byte wave
definitions and six-column triggers could only corrupt them. The panel is
replaced by a one-line summary so the author can see what the project carries.
Authoring them is Phase 5B.
"""
import json
import sys
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog, ttk

from engine_data import (
    C64_PALETTE_HEX,
    DEFAULT_PALETTE,
    METATILE_CAPACITY,
    METATILE_H,
    METATILE_NAMES,
    METATILE_W,
    METATILES_PER_ROW,
    TERRAIN_GLYPH_BASE,
    TERRAIN_GLYPH_NAMESPACE,
    VIEWPORT_ROWS,
)
import contract_v2 as C
import project_v6
import export_v6
from controller_v6 import ControllerError, EditorController, GENERATED_NAMES
from encounters_ui import EncounterWorkspace
from native_metatile import GlyphBudgetExceeded, blank_pixels
from recover_generated_terrain import recover_generated_set
from terrain_repository import TerrainRepository, default_repo_path
from workshop_ui import ImportDialog, WorkshopDialog
from project import (
    OBJECT_TYPE_TURRET,
    ProjectValidationError,
    TURRET_POOL,
    clamp_viewport_top,
    default_viewport_top,
    duplicate_metatile,
    MetatileInUseError,
    ensure_level_metatile_set,
    metatile_id_usage,
    remove_metatile,
    max_viewport_top,
    metatile_set_entry_from_native,
    metatile_set_glyph_cost,
    repack_tileset_from_metatile_set,
    stage_logical_rows,
    turret_world_row,
    turret_screen_peak,
)

# THE CURRENT ENGINE LIMITS, read from contract_v2 rather than the v5 module.
# The old editor carried MIN/MAX_STAGE_ROWS of 1..768; the package caps the map
# at LEVELPKG_MAP_MAX/10 = 440 metatile rows and the scroller needs more than a
# screenful, so the legal range is 7..440.
MIN_STAGE_ROWS = C.MIN_METATILE_ROWS
MAX_STAGE_ROWS = C.MAX_METATILE_ROWS
DEFAULT_STAGE_ROWS = 105
MAX_TURRETS = C.MAX_TURRETS

CHAR_SIZE = 8
METATILE_PIXELS = METATILE_W * CHAR_SIZE
LEVEL_WIDTH = METATILES_PER_ROW * METATILE_PIXELS
# Approximate C64 palette for editor preview. Project data stores indices, not
# RGB. The table itself lives in engine_data so non-GUI modules share it.
C64_COLOURS = C64_PALETTE_HEX
GRID = "#555555"
SELECTED = "#ffffff"
VIEWPORT_EDGE = "#38d0ff"
VIEWPORT_ACTIVATION = "#ffd000"


def _next_id(prefix, existing):
    n = 1
    used = {str(x.get("id")) for x in existing}
    while f"{prefix}{n}" in used:
        n += 1
    return f"{prefix}{n}"


class LevelEditor(tk.Tk):
    def __init__(self, repo_root):
        super().__init__()
        self.repo_root = Path(repo_root)
        self.editor_dir = self.repo_root / "tools" / "level_editor"
        self.levels_dir = self.editor_dir / "levels"
        self.legacy_dir = self.editor_dir / "projects"
        self.levels_dir.mkdir(parents=True, exist_ok=True)

        # THE DEFAULT DOCUMENT IS THE CANONICAL v6 PROJECT, not a project
        # reconstructed from the generated assembler. The old editor seeded
        # itself by parsing src/level1/*.asm through engine_data, which made the
        # DERIVED files the source of truth and could not represent encounters
        # at all. levels/level1/level.v6.json is now authoritative and the ASM
        # is what the exporter writes out of it.
        self.controller = EditorController.canonical(self.editor_dir)
        self.project = self.controller.view
        self.repo_path = default_repo_path(self.editor_dir)
        try:
            self.repository = TerrainRepository.load(self.repo_path)
        except Exception:                                 # noqa: BLE001 - start empty on a bad file
            self.repository = TerrainRepository(path=self.repo_path)
        # THE WAVE REPOSITORY IS NOT LOADED. It stores v5 attack-catalogue
        # snapshots (attackId/enemyType/composition) and there is nothing in a
        # v6 project for them to be pasted into. The file is left on disk
        # untouched; Phase 5B decides whether a v6 encounter library replaces it.
        # Persistent PNG import session: the ImportDialog is kept alive (hidden
        # between uses) so the user can return to an already-open spritesheet and
        # pick another tile without reopening/re-reading the file. Editor/runtime
        # state only - never persisted into level/project files.
        self._import_dialog = None
        # The encounter workspace is a second window over the SAME controller,
        # opened on demand and kept in step with the document (see _adopt_project).
        self._encounters = None
        self.project_path = self.controller.path
        self.viewport_top = default_viewport_top(self.project)

        self.selected_tile = 0
        self.metatile_image_cache = {}
        self.last_painted_cell = None
        self.edit_mode = tk.StringVar(value="terrain")   # terrain | turret
        self.selected_turret = None
        self.show_grid = tk.BooleanVar(value=True)
        self.stage_row_count = tk.IntVar(value=self.project.height)
        self.viewport_var = tk.IntVar(value=self.viewport_top)
        self.duration_text = tk.StringVar()
        self.viewport_text = tk.StringVar()
        self.status_text = tk.StringVar()
        self.encounter_text = tk.StringVar()
        self.palette_vars = {
            key: tk.IntVar(value=self.project.palette[key])
            for key in ("background", "multicolour1", "multicolour2", "character")
        }
        self.saved_state = self._project_state()
        self.undo_stack = []
        self.redo_stack = []
        self.paint_gesture_before = None

        self.geometry("1120x920")
        self.minsize(900, 640)
        self.protocol("WM_DELETE_WINDOW", self._on_close)

        self._build_menu()
        self._build_ui()
        self._refresh_all()

    # ---- project construction ------------------------------------------
    def _seed_v6_project(self, name, rows):
        """A new, empty v6 level that carries the current graphics.

        The map is blank and there are no turrets and no encounters, but the
        charset, the metatile definitions and the native metatile set are copied
        from the document that is open, because a level with no tiles to paint
        with cannot be edited. noSpawnRow is derived the way migration derives
        it, so a new project validates immediately rather than starting broken.
        """
        source = self.controller.project
        rows = max(MIN_STAGE_ROWS, min(MAX_STAGE_ROWS, int(rows)))
        return project_v6.ProjectV6(
            name=name,
            stage=project_v6.Stage(metatile_rows=rows,
                                   no_spawn_row=C.default_no_spawn_row(rows)),
            palette=project_v6.Palette(**DEFAULT_PALETTE),
            glyphs=[list(g) for g in source.glyphs],
            metatile_defs=[list(d) for d in source.metatile_defs],
            level_metatile_set=json.loads(json.dumps(source.level_metatile_set))
            if source.level_metatile_set is not None else None,
            map_rows=[[0] * METATILES_PER_ROW for _ in range(rows)],
            turrets=[], movement_programs=[], wave_definitions=[], triggers=[],
        )

    @property
    def stage_rows(self):
        return self.project.metatile_rows

    @property
    def level_height(self):
        return self.project.height * METATILE_PIXELS

    # ---- undo/dirty state --------------------------------------------------
    def _project_state(self):
        """A comparable snapshot of the WHOLE v6 document.

        THE CANONICAL JSON IS THE SNAPSHOT, which is the point. The v5 version
        listed the fields it knew about, so a change to anything else -- an
        encounter, the no-spawn row -- was invisible to undo and to the dirty
        marker. Hashing the serialised project means a field the GUI cannot yet
        edit is still covered, and restoring one restores it exactly.
        """
        return self.controller.to_json()

    def _is_dirty(self):
        return self._project_state() != self.saved_state

    # ---- menu -----------------------------------------------------------
    def _build_menu(self):
        menu_bar = tk.Menu(self)
        file_menu = tk.Menu(menu_bar, tearoff=False)
        file_menu.add_command(label="New Level…", accelerator="Ctrl+N", command=self._new_level)
        file_menu.add_command(label="Open Level…", accelerator="Ctrl+O", command=self._open_level)
        file_menu.add_separator()
        file_menu.add_command(label="Save", accelerator="Ctrl+S", command=self._save_project)
        file_menu.add_command(label="Save As…", accelerator="Ctrl+Shift+S", command=self._save_project_as)
        file_menu.add_separator()
        file_menu.add_command(label="Export level package…", command=self._export_kickassembler)
        file_menu.add_separator()
        file_menu.add_command(label="Encounters…", accelerator="Ctrl+E",
                              command=self._open_encounters)
        file_menu.add_separator()
        file_menu.add_command(label="Quit", accelerator="Ctrl+Q", command=self._on_close)
        menu_bar.add_cascade(label="File", menu=file_menu)

        self.edit_menu = tk.Menu(menu_bar, tearoff=False)
        self.edit_menu.add_command(label="Undo", accelerator="Ctrl+Z", command=self._undo)
        self.edit_menu.add_command(label="Redo", accelerator="Ctrl+Shift+Z", command=self._redo)
        menu_bar.add_cascade(label="Edit", menu=self.edit_menu)
        self.config(menu=menu_bar)

        for seq, fn in (("<Control-n>", self._new_level), ("<Control-o>", self._open_level),
                        ("<Control-s>", self._save_project), ("<Control-Shift-S>", self._save_project_as),
                        ("<Control-e>", self._open_encounters),
                        ("<Control-z>", self._undo), ("<Control-Shift-Z>", self._redo),
                        ("<Control-q>", self._on_close)):
            self.bind_all(seq, lambda e, f=fn: f())
            if sys.platform == "darwin":
                self.bind_all(seq.replace("Control", "Command"), lambda e, f=fn: f())

    # ---- UI -----------------------------------------------------------
    def _build_ui(self):
        toolbar = ttk.Frame(self, padding=(8, 8, 8, 4))
        toolbar.pack(fill="x")
        ttk.Label(toolbar, text="19656 Level Editor", font=("TkDefaultFont", 12, "bold")).pack(side="left")
        ttk.Checkbutton(toolbar, text="Metatile grid", variable=self.show_grid,
                        command=self._draw_level).pack(side="right")
        ttk.Label(toolbar, text="   Mode:").pack(side="left", padx=(16, 2))
        for text, value in (("Terrain", "terrain"), ("Turrets", "turret")):
            ttk.Radiobutton(toolbar, text=text, value=value, variable=self.edit_mode,
                            command=self._on_mode_change).pack(side="left")
        self.delete_turret_button = ttk.Button(toolbar, text="Delete turret",
                                               command=self._delete_selected_turret, state="disabled")
        self.delete_turret_button.pack(side="left", padx=(8, 0))
        ttk.Button(toolbar, text="Encounters…",
                   command=self._open_encounters).pack(side="left", padx=(8, 0))

        stage_controls = ttk.Frame(self, padding=(8, 0, 8, 4))
        stage_controls.pack(fill="x")
        ttk.Label(stage_controls, text="Stage rows:").pack(side="left")
        self.stage_rows_spinbox = ttk.Spinbox(stage_controls, from_=MIN_STAGE_ROWS, to=MAX_STAGE_ROWS,
                                              width=6, textvariable=self.stage_row_count,
                                              command=self._apply_stage_row_count)
        self.stage_rows_spinbox.pack(side="left", padx=(5, 8))
        self.stage_rows_spinbox.bind("<Return>", self._apply_stage_row_count)
        self.stage_rows_spinbox.bind("<FocusOut>", self._apply_stage_row_count)
        ttk.Label(stage_controls, textvariable=self.duration_text).pack(side="left")

        # Gameplay viewport overlay controls (editor-only; never saved/exported).
        vp = ttk.Frame(self, padding=(8, 0, 8, 4))
        vp.pack(fill="x")
        ttk.Label(vp, text="Gameplay view:").pack(side="left")
        self.viewport_scale = ttk.Scale(vp, from_=0, to=max(1, max_viewport_top(self.project)),
                                        orient="horizontal", command=self._on_viewport_scrub)
        self.viewport_scale.pack(side="left", fill="x", expand=True, padx=(6, 8))
        ttk.Label(vp, textvariable=self.viewport_text).pack(side="left")

        level_settings = ttk.Frame(self, padding=(8, 0, 8, 4))
        level_settings.pack(fill="x")
        ttk.Label(level_settings, text="Palette:").pack(side="left")
        for label, key, maximum in (("BG", "background", 15), ("MC1", "multicolour1", 15),
                                    ("MC2", "multicolour2", 15), ("CHAR", "character", 7)):
            ttk.Label(level_settings, text=label).pack(side="left", padx=(8, 2))
            spin = ttk.Spinbox(level_settings, from_=0, to=maximum, width=3,
                               textvariable=self.palette_vars[key], command=self._apply_level_settings)
            spin.pack(side="left")
            spin.bind("<Return>", self._apply_level_settings)
            spin.bind("<FocusOut>", self._apply_level_settings)
        # NO SCROLL-DIVIDER CONTROL. The engine scrolls 1 px/frame
        # unconditionally, v6 stores no such field, and the constant it used to
        # write into stage_config.asm was read by nothing. Instead this row now
        # reports what the project carries that this phase cannot edit.
        ttk.Label(level_settings, text="   Encounters:").pack(side="left", padx=(14, 2))
        ttk.Label(level_settings, textvariable=self.encounter_text).pack(side="left")

        body = ttk.Frame(self, padding=8)
        body.pack(fill="both", expand=True)
        body.columnconfigure(1, weight=1)
        body.rowconfigure(0, weight=1)

        palette_frame = ttk.LabelFrame(body, text="Level metatile set (up to 64)", padding=6)
        palette_frame.grid(row=0, column=0, sticky="ns", padx=(0, 8))
        palette_frame.rowconfigure(1, weight=1)
        self.glyph_budget_text = tk.StringVar(value="")
        ttk.Label(palette_frame, textvariable=self.glyph_budget_text,
                  font=("TkDefaultFont", 9)).grid(row=0, column=0, columnspan=2, sticky="w")
        self.palette_canvas = tk.Canvas(palette_frame, width=210, highlightthickness=0,
                                        background=self.cget("background"))
        pscroll = ttk.Scrollbar(palette_frame, orient="vertical", command=self.palette_canvas.yview)
        self.palette_canvas.configure(yscrollcommand=pscroll.set)
        self.palette_canvas.grid(row=1, column=0, sticky="nsew")
        pscroll.grid(row=1, column=0, sticky="nse")
        self.palette_canvas.bind("<Button-1>", self._palette_click)
        self._bind_mousewheel(self.palette_canvas)
        mt_btns = ttk.Frame(palette_frame)
        mt_btns.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(4, 0))
        for txt, cmd in (("Edit Selected", self._metatile_edit_workshop),
                         ("Duplicate", self._metatile_duplicate_selected),
                         ("New Tile", self._metatile_new_blank)):
            ttk.Button(mt_btns, text=txt, width=11, command=cmd).pack(side="left", padx=1)
        mt_btns2 = ttk.Frame(palette_frame)
        mt_btns2.grid(row=3, column=0, columnspan=2, sticky="ew")
        for txt, cmd in (("Import PNG…", self._metatile_import_png),
                         ("Save to Repo", self._metatile_save_to_repository),
                         ("Rename…", self._metatile_rename)):
            ttk.Button(mt_btns2, text=txt, width=11, command=cmd).pack(side="left", padx=1)
        mt_btns3 = ttk.Frame(palette_frame)
        mt_btns3.grid(row=4, column=0, columnspan=2, sticky="ew")
        for txt, cmd in (("Repository…", self._metatile_from_repo),
                         ("Delete", self._metatile_delete_selected),
                         ("Trim unused", self._metatile_remove_unused)):
            ttk.Button(mt_btns3, text=txt, width=11, command=cmd).pack(side="left", padx=1)

        self.level_frame = ttk.LabelFrame(body, text="Working stage", padding=6)
        self.level_frame.grid(row=0, column=1, sticky="nsew")
        self.level_frame.columnconfigure(0, weight=1)
        self.level_frame.rowconfigure(0, weight=1)
        self.level_canvas = tk.Canvas(self.level_frame, width=LEVEL_WIDTH, height=700,
                                      background=C64_COLOURS[self.project.palette["background"]],
                                      scrollregion=(0, 0, LEVEL_WIDTH, self.level_height),
                                      highlightthickness=0)
        yscroll = ttk.Scrollbar(self.level_frame, orient="vertical", command=self.level_canvas.yview)
        self.level_canvas.configure(yscrollcommand=yscroll.set)
        self.level_canvas.grid(row=0, column=0, sticky="nsew")
        yscroll.grid(row=0, column=1, sticky="ns")
        self.level_canvas.bind("<Button-1>", self._level_click_start)
        self.level_canvas.bind("<B1-Motion>", self._level_drag)
        self.level_canvas.bind("<ButtonRelease-1>", self._level_click_end)
        self.level_canvas.bind("<Button-3>", self._level_right_click)
        self.level_canvas.bind("<Control-Button-1>", self._level_right_click)
        self.level_canvas.bind("<Shift-MouseWheel>", self._viewport_wheel)
        self.level_canvas.bind("<Up>", lambda e: self._nudge_viewport(-1))
        self.level_canvas.bind("<Down>", lambda e: self._nudge_viewport(1))
        self.bind_all("<Delete>", self._delete_selected)
        self.bind_all("<BackSpace>", self._delete_selected)
        self._bind_mousewheel(self.level_canvas)

        status = ttk.Frame(self, padding=(8, 2, 8, 8))
        status.pack(fill="x")
        ttk.Label(status, textvariable=self.status_text).pack(side="left")

    def _bind_mousewheel(self, canvas):
        canvas.bind("<MouseWheel>", lambda e, t=canvas: self._mousewheel(e, t))
        canvas.bind("<Button-4>", lambda e, t=canvas: (t.yview_scroll(-1, "units"), "break")[1])
        canvas.bind("<Button-5>", lambda e, t=canvas: (t.yview_scroll(1, "units"), "break")[1])

    def _mousewheel(self, event, canvas):
        units = -int(event.delta) if sys.platform == "darwin" else -int(event.delta / 120) if event.delta else 0
        if units:
            canvas.yview_scroll(units, "units")
        return "break"

    def _viewport_wheel(self, event):
        step = -1 if (event.delta > 0 if sys.platform != "darwin" else event.delta < 0) else 1
        self._nudge_viewport(step)
        return "break"

    # ---- gameplay viewport overlay -----------------------------------
    def _clamp_viewport(self):
        self.viewport_top = clamp_viewport_top(self.viewport_top, self.project)
        try:
            self.viewport_scale.configure(to=max(1, max_viewport_top(self.project)))
            self.viewport_var.set(self.viewport_top)
            self.viewport_scale.set(self.viewport_top)
        except AttributeError:
            pass

    def _set_viewport(self, top, push_undo=False):
        self.viewport_top = clamp_viewport_top(top, self.project)
        self.viewport_var.set(self.viewport_top)
        try:
            if abs(self.viewport_scale.get() - self.viewport_top) > 0.5:
                self.viewport_scale.set(self.viewport_top)
        except (AttributeError, tk.TclError):
            pass
        self._draw_viewport_overlay()
        self._update_viewport_text()

    def _on_viewport_scrub(self, value):
        top = int(round(float(value)))
        if top != self.viewport_top:
            self.viewport_top = clamp_viewport_top(top, self.project)
            self.viewport_var.set(self.viewport_top)
            self._draw_viewport_overlay()
            self._update_viewport_text()

    def _nudge_viewport(self, delta):
        self._set_viewport(self.viewport_top + delta)
        return "break"

    def _update_viewport_text(self):
        lo = self.viewport_top
        hi = lo + VIEWPORT_ROWS - 1
        slr = stage_logical_rows(self.project)
        self.viewport_text.set(f"logical rows {lo}–{hi}  (start row {slr - 1}; {VIEWPORT_ROWS}×40)")

    def _draw_viewport_overlay(self):
        c = self.level_canvas
        c.delete("viewport")
        y0 = self.viewport_top * CHAR_SIZE
        y1 = (self.viewport_top + VIEWPORT_ROWS) * CHAR_SIZE
        # Outline ONLY - a transparent aperture so the terrain underneath stays
        # readable. Blue rectangle around the exact 23-logical-row gameplay
        # aperture (geometry unchanged); no fill / tint.
        c.create_rectangle(0, y0, LEVEL_WIDTH - 1, y1, outline=VIEWPORT_EDGE,
                           fill="", width=2, tags="viewport")
        # top edge = the wave activation line (SCROLL_ROW == worldRow)
        c.create_line(0, y0, LEVEL_WIDTH, y0, fill=VIEWPORT_ACTIVATION, width=2, tags="viewport")
        c.create_text(3, y0 + 2, anchor="nw", fill=VIEWPORT_ACTIVATION,
                      font=("TkDefaultFont", 7),
                      text=f"gameplay view  rows {self.viewport_top}–"
                           f"{self.viewport_top + VIEWPORT_ROWS - 1}", tags="viewport")

    def _viewport_range(self):
        return self.viewport_top, self.viewport_top + VIEWPORT_ROWS - 1

    # ---- rendering ---------------------------------------------------
    def _pixel_colour(self, pair):
        p = self.project.palette
        return C64_COLOURS[(p["background"], p["multicolour1"], p["multicolour2"], p["character"])[pair]]

    def _glyph_bitmap(self, code):
        glyphs = self.project.tileset["glyphs"]
        idx = code - TERRAIN_GLYPH_BASE
        if 0 <= idx < len(glyphs):
            return glyphs[idx]
        raise ValueError(f"No terrain glyph bitmap for character {code} in this level's tileset")

    def _get_metatile_image(self, tile_id):
        palette_key = tuple(self.project.palette[k] for k in
                            ("background", "multicolour1", "multicolour2", "character"))
        cache_key = (tile_id, palette_key, id(self.project.tileset))
        image = self.metatile_image_cache.get(cache_key)
        if image is not None:
            return image
        tile = self.project.tileset["metatileDefs"][tile_id]
        pixel_rows = []
        for char_row in range(METATILE_H):
            for glyph_y in range(CHAR_SIZE):
                row_colours = []
                for char_col in range(METATILE_W):
                    byte = self._glyph_bitmap(tile[char_row * METATILE_W + char_col])[glyph_y]
                    for shift in (6, 4, 2, 0):
                        colour = self._pixel_colour((byte >> shift) & 0x03)
                        row_colours.extend((colour, colour))
                pixel_rows.append(row_colours)
        image = tk.PhotoImage(width=METATILE_PIXELS, height=METATILE_PIXELS)
        image.put(" ".join("{" + " ".join(row) + "}" for row in pixel_rows))
        self.metatile_image_cache[cache_key] = image
        return image

    def _draw_metatile(self, canvas, tile_id, x, y, tags=()):
        canvas.create_image(x, y, anchor="nw", image=self._get_metatile_image(tile_id), tags=tags)

    # ---- level metatile set (up to 64) ----------------------------------
    def _metatile_count(self):
        s = self.project.level_metatile_set
        if s:
            return len(s)
        if self.project.tileset:
            return len(self.project.tileset["metatileDefs"])
        return len(METATILE_NAMES)

    def _metatile_name(self, tile_id):
        s = self.project.level_metatile_set
        if s and 0 <= tile_id < len(s):
            return s[tile_id].get("name") or f"M{tile_id}"
        return METATILE_NAMES[tile_id] if tile_id < len(METATILE_NAMES) else f"M{tile_id}"

    def _draw_palette(self):
        self.palette_canvas.delete("all")
        item_height = 46
        count = self._metatile_count()
        for tile_id in range(count):
            name = self._metatile_name(tile_id)
            y = tile_id * item_height + 4
            tags = (f"tile_{tile_id}",)
            self.palette_canvas.create_rectangle(4, y, 39, y + 35,
                                                 fill=C64_COLOURS[self.project.palette["background"]],
                                                 outline="#888888", tags=tags)
            self._draw_metatile(self.palette_canvas, tile_id, 6, y + 2, tags=tags)
            self.palette_canvas.create_text(48, y + 17, anchor="w", text=f"{tile_id:2d}  {name}", tags=tags)
            if tile_id == self.selected_tile:
                self.palette_canvas.create_rectangle(1, y - 2, 205, y + 38, outline=SELECTED, width=2, tags=tags)
        self.palette_canvas.configure(scrollregion=(0, 0, 210, count * item_height + 4))
        if hasattr(self, "glyph_budget_text"):
            info = metatile_set_glyph_cost(self.project)
            self.glyph_budget_text.set(
                f"Metatiles: {count} / 64      Terrain glyphs: {info['used']} / {info['capacity']}")

    def _draw_level(self):
        self.level_canvas.delete("all")
        self.level_canvas.configure(scrollregion=(0, 0, LEVEL_WIDTH, self.level_height))
        for row, tiles in enumerate(self.stage_rows):
            for col, tile_id in enumerate(tiles):
                self._draw_metatile(self.level_canvas, tile_id, col * METATILE_PIXELS, row * METATILE_PIXELS)
        if self.show_grid.get():
            for x in range(0, LEVEL_WIDTH + 1, METATILE_PIXELS):
                self.level_canvas.create_line(x, 0, x, self.level_height, fill=GRID, tags="grid")
            for y in range(0, self.level_height + 1, METATILE_PIXELS):
                self.level_canvas.create_line(0, y, LEVEL_WIDTH, y, fill=GRID, tags="grid")
        self._draw_turret_markers()
        self._draw_viewport_overlay()

    def _draw_turret_markers(self):
        self.level_canvas.delete("turret_marker")
        lo, hi = self._viewport_range()
        active = self.edit_mode.get() == "turret"
        for index, obj in enumerate(self.project.objects):
            if not (isinstance(obj, dict) and obj.get("type") == OBJECT_TYPE_TURRET):
                continue
            row, col = obj.get("metatileRow", 0), obj.get("metatileCol", 0)
            x0, y0 = col * METATILE_PIXELS, row * METATILE_PIXELS
            x1, y1 = x0 + METATILE_PIXELS, y0 + METATILE_PIXELS
            wr = turret_world_row(row)
            in_view = lo <= wr <= hi
            selected = active and index == self.selected_turret
            outline = SELECTED if selected else ("#ff5030" if in_view else "#7a4a44")
            width = 3 if selected else (2 if in_view else 1)
            self.level_canvas.create_rectangle(x0 + 2, y0 + 2, x1 - 2, y1 - 2, outline=outline,
                                               width=width, tags="turret_marker")
            bx, by = x0 + CHAR_SIZE, y0 + CHAR_SIZE
            self.level_canvas.create_rectangle(bx, by, bx + 2 * CHAR_SIZE, by + 2 * CHAR_SIZE,
                                               outline=outline, fill="", width=1, tags="turret_marker")
            self.level_canvas.create_text(x0 + METATILE_PIXELS / 2, y0 + METATILE_PIXELS / 2,
                                          text="T", fill=outline,
                                          font=("TkDefaultFont", 10, "bold"), tags="turret_marker")

    def _palette_click(self, event):
        tile_id = int((self.palette_canvas.canvasy(event.y) - 4) // 46)
        if 0 <= tile_id < self._metatile_count():
            self.selected_tile = tile_id
            self._draw_palette()
            self._update_status()

    # ---- metatile-set operations -------------------------------------------
    def _repack_after_metatile_edit(self):
        try:
            repack_tileset_from_metatile_set(self.project)
        except GlyphBudgetExceeded as exc:
            messagebox.showerror("Terrain glyph budget", str(exc), parent=self)
            return False
        self.metatile_image_cache.clear()
        return True

    def _metatile_new_blank(self):
        if self._metatile_count() >= 64:
            self.bell()
            self.status_text.set("This level already has 64 metatiles (the live maximum).")
            return
        before = self._project_state()
        ensure_level_metatile_set(self.project)
        idx = len(self.project.level_metatile_set)
        self.project.level_metatile_set.append(
            metatile_set_entry_from_native(blank_pixels(0), name=f"M{idx}"))
        if not self._repack_after_metatile_edit():
            self.project.level_metatile_set.pop()
            return
        self.selected_tile = idx
        self._push_undo(before)
        self._refresh_all()

    def _metatile_duplicate_selected(self):
        """Deep-copy the selected level metatile as a new, independent metatile
        (NAME_COPY / NAME_COPY_2 ...). Existing metatile IDs and every painted
        map cell are unchanged; the copy takes the next free ID and is selected.
        Repacks through the normal path and enforces the 128-glyph budget."""
        ensure_level_metatile_set(self.project)
        idx = self.selected_tile
        if not 0 <= idx < len(self.project.level_metatile_set):
            return
        if self._metatile_count() >= METATILE_CAPACITY:
            self.bell()
            self.status_text.set(
                f"This level already has {METATILE_CAPACITY} metatiles (the vocabulary limit).")
            return
        before = self._project_state()
        try:
            new_idx = duplicate_metatile(self.project, idx)
        except ProjectValidationError as exc:
            messagebox.showerror("Duplicate metatile", str(exc), parent=self)
            return
        if not self._repack_after_metatile_edit():
            self.project.level_metatile_set.pop()
            return
        self.selected_tile = new_idx
        self._push_undo(before)
        self._refresh_all()
        self.status_text.set(
            f"Duplicated metatile {idx} -> {new_idx} "
            f"'{self.project.level_metatile_set[new_idx]['name']}' (independent copy).")

    def _metatile_save_to_repository(self):
        """Snapshot the selected level metatile into the Terrain Asset
        Repository. The repository copy and the level copy are independent
        thereafter - editing/renaming/deleting either never touches the other."""
        ensure_level_metatile_set(self.project)
        idx = self.selected_tile
        if not 0 <= idx < len(self.project.level_metatile_set):
            return
        entry = self.project.level_metatile_set[idx]
        default = entry.get("name") or f"M{idx}"
        name = simpledialog.askstring(
            "Save to Terrain Repository",
            f"Repository asset name for level metatile {idx}:",
            initialvalue=default, parent=self)
        if name is None:
            return
        name = name.strip()
        if not name:
            messagebox.showerror("Save to Repository", "Name cannot be empty.", parent=self)
            return
        clash = [a for a in self.repository.list() if a["name"] == name]
        if clash and not messagebox.askyesno(
                "Duplicate name",
                f"The repository already has an asset called '{name}' ({clash[0]['id']}).\n\n"
                f"Names are labels only - a new, independent asset with its own id "
                f"will be created. Continue?", parent=self):
            return
        prov = {"sourcePack": f"promoted from level '{self.project.name}' metatile {idx} ({default})"}
        src = entry.get("source") or {}
        src_prov = src.get("provenance") or {}
        if src_prov.get("sourcePack"):
            prov["licenceNote"] = f"original artwork source: {src_prov['sourcePack']}"
        try:
            asset = self.repository.add_asset(
                name, [row[:] for row in entry["native"]["pixels"]],
                provenance=prov, tags=["from-level"])
            self.repository.save()
        except Exception as exc:                          # noqa: BLE001
            messagebox.showerror("Save to Repository", str(exc), parent=self)
            return
        self.status_text.set(
            f"Saved metatile {idx} '{default}' to the terrain repository as "
            f"{asset['id']} '{name}' (independent snapshot).")

    def _metatile_edit_workshop(self):
        idx = self.selected_tile
        ensure_level_metatile_set(self.project)
        if not 0 <= idx < len(self.project.level_metatile_set):
            return
        entry = self.project.level_metatile_set[idx]
        before = self._project_state()

        def on_save(name, pixels):
            self.project.level_metatile_set[idx] = metatile_set_entry_from_native(
                pixels, name=name, source=entry.get("source"))
            if not self._repack_after_metatile_edit():
                return (f"This metatile would push the level past {TERRAIN_GLYPH_NAMESPACE} "
                        f"unique terrain glyphs.")
            self._push_undo(before)
            self._refresh_all()
            return None

        WorkshopDialog(
            self, self.project.palette, title=f"Workshop — metatile {idx} ({entry['name']})",
            name=entry["name"], pixels=entry["native"]["pixels"],
            cost_fn=lambda px: metatile_set_glyph_cost(self.project, candidate_pixels=px),
            on_save=on_save)

    def _import_session_pick(self, rgb_rows, provenance, dialog):
        """One tile chosen from the persistent import session -> open the
        Workshop. The import dialog is hidden (not destroyed) so 'Back to
        Source' can return to it without re-reading the PNG."""
        from terrain_convert import source_tile_to_native
        native = source_tile_to_native(rgb_rows, self.project.palette)
        before = self._project_state()
        dialog.hide()

        def on_save(name, pixels):
            if self._metatile_count() >= 64:
                return "This level already has 64 metatiles."
            ensure_level_metatile_set(self.project)
            self.project.level_metatile_set.append(metatile_set_entry_from_native(
                pixels, name=name, source={"provenance": provenance}))
            if not self._repack_after_metatile_edit():
                self.project.level_metatile_set.pop()
                return (f"Adding this metatile would exceed the {TERRAIN_GLYPH_NAMESPACE}-glyph "
                        f"terrain budget.")
            self.selected_tile = self._metatile_count() - 1
            self._push_undo(before)
            self._refresh_all()
            return None

        def repo_save(name, pixels):
            try:
                self.repository.add_asset(name, pixels, provenance=provenance)
                self.repository.save()
            except Exception as exc:                       # noqa: BLE001
                return str(exc)
            return None

        WorkshopDialog(
            self, self.project.palette, title="Workshop — imported source tile",
            name="imported", pixels=native, source_rgb=rgb_rows,
            cost_fn=lambda px: metatile_set_glyph_cost(self.project, candidate_pixels=px),
            on_save=on_save, allow_repo_save=repo_save,
            on_back=self._reopen_import_session)

    def _reopen_import_session(self):
        if self._import_dialog is not None and self._import_dialog.winfo_exists():
            self._import_dialog.show()
        else:
            self._metatile_import_png()

    def _close_import_session(self):
        if self._import_dialog is not None:
            try:
                self._import_dialog.destroy()
            except Exception:                              # noqa: BLE001
                pass
        self._import_dialog = None

    def _metatile_import_png(self):
        # Reuse the live session if one is already open (Back to Source / re-invoke).
        if self._import_dialog is not None and self._import_dialog.winfo_exists():
            self._import_dialog.show()
            return
        prev = self._import_dialog
        sheet = prev.sheet if prev is not None else None
        select_index = prev.last_index if prev is not None else None
        self._import_dialog = ImportDialog(
            self, on_pick=self._import_session_pick, initial_dir=str(self.repo_root),
            sheet=sheet, select_index=select_index)
        self._import_dialog.protocol("WM_DELETE_WINDOW", self._close_import_session)
        self._import_dialog.show()

    def _metatile_from_repo(self):
        """Terrain Asset Repository manager: add a snapshot to the level, and
        rename / delete individual repository assets. Repository assets and
        level metatiles are separate snapshot-based concepts: renaming or
        deleting a repository asset never touches metatiles already copied into
        any level package."""
        picker = tk.Toplevel(self)
        picker.title("Terrain Asset Repository")
        picker.transient(self)
        picker.grab_set()
        ttk.Label(picker, text="Repository assets (snapshots; independent of level metatiles)",
                  padding=(8, 8, 8, 2)).pack(anchor="w")
        lb = tk.Listbox(picker, width=48, height=14, exportselection=False)
        lb.pack(fill="both", expand=True, padx=8, pady=(0, 6))

        state = {"assets": []}

        def refresh(select_id=None):
            state["assets"] = self.repository.list()
            lb.delete(0, "end")
            for a in state["assets"]:
                used = sum(1 for e in (self.project.level_metatile_set or [])
                           if (e.get("source") or {}).get("repositoryAssetId") == a["id"])
                tag = f"  · in this level x{used}" if used else ""
                lb.insert("end", f"{a['id']}  {a['name']}{tag}")
            if select_id is not None:
                for i, a in enumerate(state["assets"]):
                    if a["id"] == select_id:
                        lb.selection_set(i)
                        lb.see(i)
                        break

        def selected():
            sel = lb.curselection()
            return state["assets"][sel[0]] if sel else None

        def add():
            asset = selected()
            if asset is None:
                return
            if self._metatile_count() >= 64:
                messagebox.showerror("Full", "This level already has 64 metatiles.", parent=picker)
                return
            snap = self.repository.snapshot(asset["id"])
            before = self._project_state()
            ensure_level_metatile_set(self.project)
            self.project.level_metatile_set.append(metatile_set_entry_from_native(
                snap["pixels"], name=snap["name"],
                source={"repositoryAssetId": snap["repositoryAssetId"],
                        "provenance": snap["provenance"]}))
            if not self._repack_after_metatile_edit():
                self.project.level_metatile_set.pop()
                return
            self.selected_tile = self._metatile_count() - 1
            self._push_undo(before)
            self._refresh_all()
            picker.destroy()

        def rename():
            asset = selected()
            if asset is None:
                return
            new = simpledialog.askstring("Rename repository asset",
                                         f"New name for {asset['id']}:",
                                         initialvalue=asset["name"], parent=picker)
            if new is None:
                return
            new = new.strip()
            if not new:
                messagebox.showerror("Rename", "Name cannot be empty.", parent=picker)
                return
            if new == asset["name"]:
                return
            dupes = [a["name"] for a in state["assets"] if a["id"] != asset["id"]]
            if new in dupes and not messagebox.askyesno(
                    "Duplicate name",
                    f"Another repository asset is already called '{new}'. "
                    f"Names are labels only ({asset['id']} stays the identity). Use it anyway?",
                    parent=picker):
                return
            try:
                self.repository.update_asset(asset["id"], name=new)   # artwork/id unchanged
                self.repository.save()
            except Exception as exc:                       # noqa: BLE001
                messagebox.showerror("Rename", str(exc), parent=picker)
                return
            refresh(select_id=asset["id"])

        def delete():
            asset = selected()
            if asset is None:
                return
            used = sum(1 for e in (self.project.level_metatile_set or [])
                       if (e.get("source") or {}).get("repositoryAssetId") == asset["id"])
            msg = (f"Delete repository asset {asset['id']} ('{asset['name']}')?\n\n"
                   "The reusable repository copy is removed. Metatiles already "
                   "copied into level packages are independent snapshots and are "
                   "NOT changed.")
            if used:
                msg += f"\n\n(This level currently uses {used} snapshot(s) of it - unaffected.)"
            if not messagebox.askyesno("Delete repository asset", msg, parent=picker):
                return
            row = lb.curselection()[0]
            self.repository.remove(asset["id"])
            self.repository.save()
            refresh()
            n = lb.size()
            if n:
                lb.selection_set(min(row, n - 1))

        def edit_asset():
            asset = selected()
            if asset is None:
                return

            def on_save(name, pixels):
                try:
                    self.repository.update_asset(asset["id"], name=name, native_pixels=pixels)
                    self.repository.save()
                except Exception as exc:                   # noqa: BLE001
                    return str(exc)
                refresh(select_id=asset["id"])
                return None

            WorkshopDialog(
                picker, self.project.palette,
                title=f"Edit repository asset {asset['id']} ({asset['name']})",
                name=asset["name"], pixels=asset["native"]["pixels"],
                cost_fn=None, on_save=on_save)

        def import_from_project():
            path = filedialog.askopenfilename(
                title="Import metatiles from another project (any version)",
                initialdir=self.levels_dir, parent=picker,
                filetypes=(("Level JSON", "*.json"), ("All files", "*.*")))
            if not path:
                return
            try:
                # The same one-loader rule as Open: a v6 project reads directly
                # and an older one migrates, so metatiles can be lifted out of
                # either without a second, v5-only reader.
                src = EditorController.load(path).view
            except Exception as exc:                      # noqa: BLE001
                messagebox.showerror("Import from project", f"Cannot read that project:\n{exc}",
                                     parent=picker)
                return
            entries = ensure_level_metatile_set(src)
            if not entries:
                messagebox.showinfo("Import from project",
                                    "That project defines no metatiles.", parent=picker)
                return
            self._import_project_metatiles_dialog(picker, src, entries, refresh)

        def recover_generated():
            before = len(self.repository)
            res = recover_generated_set(self.repository)
            if res["added"]:
                self.repository.save()
            refresh()
            messagebox.showinfo(
                "Recover generated terrain set",
                f"Generated set: {res['generated']} native metatiles.\n"
                f"Repository: {before} -> {len(self.repository)} assets.\n"
                f"Added {len(res['added'])}; {len(res['existing'])} identical asset(s) "
                f"already present were left untouched.", parent=picker)

        btns = ttk.Frame(picker)
        btns.pack(fill="x", padx=8, pady=(0, 8))
        ttk.Button(btns, text="Add snapshot to level", command=add).pack(side="left")
        ttk.Button(btns, text="Edit asset…", command=edit_asset).pack(side="left", padx=(8, 0))
        ttk.Button(btns, text="Rename…", command=rename).pack(side="left", padx=(8, 0))
        ttk.Button(btns, text="Delete", command=delete).pack(side="left", padx=(8, 0))
        ttk.Button(btns, text="Close", command=picker.destroy).pack(side="right")
        btns2 = ttk.Frame(picker)
        btns2.pack(fill="x", padx=8, pady=(0, 8))
        ttk.Button(btns2, text="Import from Project…", command=import_from_project).pack(side="left")
        ttk.Button(btns2, text="Recover generated set", command=recover_generated).pack(
            side="left", padx=(8, 0))
        refresh()

    def _import_project_metatiles_dialog(self, parent, src_project, entries, on_done):
        """Pick metatiles from another project's levelMetatileSet and import them
        into the Terrain Asset Repository as independent snapshots. The source
        project is never modified."""
        dlg = tk.Toplevel(parent)
        dlg.title(f"Import from '{src_project.name}' ({len(entries)} metatiles)")
        dlg.transient(parent)
        dlg.grab_set()
        ttk.Label(dlg, text=f"{src_project.name}: select metatiles to snapshot into the repository",
                  padding=(8, 8, 8, 2)).pack(anchor="w")
        lb = tk.Listbox(dlg, width=44, height=16, selectmode="extended", exportselection=False)
        lb.pack(fill="both", expand=True, padx=8, pady=(0, 6))
        for i, e in enumerate(entries):
            lb.insert("end", f"{i:2d}  {e.get('name') or f'M{i}'}")

        def do_import():
            picks = list(lb.curselection())
            if not picks:
                messagebox.showinfo("Import", "Select one or more metatiles first.", parent=dlg)
                return
            added = []
            try:
                for i in picks:
                    e = entries[i]
                    prov = {"sourcePack": f"imported from project '{src_project.name}' "
                                          f"metatile {i} ({e.get('name') or f'M{i}'})"}
                    added.append(self.repository.add_asset(
                        e.get("name") or f"M{i}",
                        [row[:] for row in e["native"]["pixels"]],
                        provenance=prov, tags=["imported"])["id"])
                self.repository.save()
            except Exception as exc:                        # noqa: BLE001
                messagebox.showerror("Import failed", str(exc), parent=dlg)
                return
            on_done()
            messagebox.showinfo("Import from project",
                                f"Imported {len(added)} metatile(s) as new repository assets "
                                f"({', '.join(added)}).", parent=dlg)
            dlg.destroy()

        bar = ttk.Frame(dlg)
        bar.pack(fill="x", padx=8, pady=(0, 8))
        ttk.Button(bar, text="Select All",
                   command=lambda: lb.selection_set(0, "end")).pack(side="left")
        ttk.Button(bar, text="Import selected", command=do_import).pack(side="left", padx=(8, 0))
        ttk.Button(bar, text="Cancel", command=dlg.destroy).pack(side="right")

    def _metatile_rename(self):
        idx = self.selected_tile
        ensure_level_metatile_set(self.project)
        if not 0 <= idx < len(self.project.level_metatile_set):
            return
        cur = self.project.level_metatile_set[idx]["name"]
        new = simpledialog.askstring("Rename metatile", f"New name for metatile {idx}:",
                                     initialvalue=cur, parent=self)
        if not new or new.strip() == cur:
            return
        before = self._project_state()
        self.project.level_metatile_set[idx]["name"] = new.strip()
        self._push_undo(before)
        self._draw_palette()
        self._update_status()

    def _metatile_delete_selected(self):
        """Delete the SELECTED metatile if the map does not reference it,
        renumbering later definitions and map cells so the painted stage stays
        visually identical. Rejects deletion of a metatile still in use."""
        ensure_level_metatile_set(self.project)
        idx = self.selected_tile
        if not 0 <= idx < self._metatile_count():
            return
        if self._metatile_count() <= 1:
            messagebox.showinfo("Delete metatile", "A level must keep at least one metatile.",
                                parent=self)
            return
        name = self._metatile_name(idx)
        used = metatile_id_usage(self.project).get(idx, 0)
        if used:
            messagebox.showerror(
                "Metatile in use",
                f"Metatile {idx} ('{name}') is used by {used} map cell(s). "
                f"Repaint those cells onto another metatile first, then delete it.",
                parent=self)
            return
        if not messagebox.askyesno(
                "Delete metatile",
                f"Delete metatile {idx} ('{name}')?\n\n"
                f"It is unused. Metatiles above it shift down by one and the "
                f"painted map is renumbered to match (no visible change).",
                parent=self):
            return
        before = self._project_state()
        try:
            remove_metatile(self.project, idx)
        except MetatileInUseError as exc:
            messagebox.showerror("Metatile in use", str(exc), parent=self)
            return
        self._repack_after_metatile_edit()
        self.selected_tile = max(0, min(idx, self._metatile_count() - 1))
        self._push_undo(before)
        self._refresh_all()

    def _metatile_remove_unused(self):
        """Delete every metatile the map does not reference, from the highest ID
        down so the renumbering stays stable. Built on remove_metatile()."""
        ensure_level_metatile_set(self.project)
        unused = [i for i in range(self._metatile_count())
                  if not metatile_id_usage(self.project).get(i, 0)]
        if not unused:
            messagebox.showinfo("Trim unused", "Every metatile is used by the map.", parent=self)
            return
        if self._metatile_count() - len(unused) < 1:
            unused = unused[1:]                       # always keep at least one
        if not messagebox.askyesno(
                "Trim unused",
                f"Delete {len(unused)} unused metatile(s) (IDs "
                f"{', '.join(map(str, unused))}) and renumber the map to match?",
                parent=self):
            return
        before = self._project_state()
        for i in sorted(unused, reverse=True):
            try:
                remove_metatile(self.project, i)
            except (MetatileInUseError, ProjectValidationError):
                pass
        self._repack_after_metatile_edit()
        self.selected_tile = min(self.selected_tile, self._metatile_count() - 1)
        self._push_undo(before)
        self._refresh_all()

    # ---- canvas input dispatch -----------------------------------------
    def _cell_from_event(self, event):
        x = int(self.level_canvas.canvasx(event.x))
        y = int(self.level_canvas.canvasy(event.y))
        col, row = x // METATILE_PIXELS, y // METATILE_PIXELS
        if 0 <= row < self.project.height and 0 <= col < METATILES_PER_ROW:
            return row, col
        return None

    def _on_mode_change(self):
        self.selected_turret = None
        self._draw_level()
        self._update_turret_ui()
        self._update_status()

    def _level_click_start(self, event):
        self.level_canvas.focus_set()
        mode = self.edit_mode.get()
        if mode == "turret":
            self._turret_click(event)
            return "break"
        self._paint_start(event)

    def _level_drag(self, event):
        if self.edit_mode.get() == "turret":
            return "break"
        self._paint_event(event)

    def _level_click_end(self, event=None):
        if self.edit_mode.get() == "turret":
            return "break"
        self._paint_end(event)

    def _level_right_click(self, event):
        if self.edit_mode.get() == "turret":
            cell = self._cell_from_event(event)
            if cell:
                self._remove_turret_at(*cell)
            return "break"

    def _delete_selected(self, event=None):
        if self.edit_mode.get() == "turret":
            return self._delete_selected_turret()
        return "break"

    # ---- turret placement -------------------------------------------------
    def _turret_index_at(self, row, col):
        for i, o in enumerate(self.project.objects):
            if (isinstance(o, dict) and o.get("type") == OBJECT_TYPE_TURRET
                    and o.get("metatileRow") == row and o.get("metatileCol") == col):
                return i
        return None

    def _turret_count(self):
        return sum(1 for o in self.project.objects
                   if isinstance(o, dict) and o.get("type") == OBJECT_TYPE_TURRET)

    def _turret_click(self, event):
        cell = self._cell_from_event(event)
        if cell is None:
            return
        row, col = cell
        existing = self._turret_index_at(row, col)
        if existing is not None:
            self.selected_turret = existing
            self._draw_level()
            self._update_turret_ui()
            return
        before = self._project_state()
        try:
            # THE CONTROLLER OWNS THE LIMITS, so the one-per-row rule and the
            # eight-turret cap are enforced in one place and tested headlessly.
            self.selected_turret = self.controller.add_turret(row, col)
        except ControllerError as exc:
            self.bell()
            self.status_text.set(str(exc))
            return
        self._push_undo(before)
        self._draw_level()
        self._update_turret_ui()
        self._update_document_ui()

    def _remove_turret_at(self, row, col):
        idx = self._turret_index_at(row, col)
        if idx is None:
            return
        before = self._project_state()
        self.controller.remove_turret(idx)
        self.selected_turret = None
        self._push_undo(before)
        self._draw_level()
        self._update_turret_ui()
        self._update_document_ui()

    def _delete_selected_turret(self):
        if self.edit_mode.get() != "turret" or self.selected_turret is None:
            return "break"
        if not 0 <= self.selected_turret < len(self.project.objects):
            self.selected_turret = None
            return "break"
        before = self._project_state()
        self.controller.remove_turret(self.selected_turret)
        self.selected_turret = None
        self._push_undo(before)
        self._draw_level()
        self._update_turret_ui()
        self._update_document_ui()
        return "break"

    def _update_turret_ui(self):
        # `self.selected_turret or -1` MADE TURRET ZERO UNDELETABLE. Index 0 is
        # falsy, so `or -1` turned the perfectly good selection 0 into -1 and the
        # button disabled itself. Turrets are canonically ordered by metatile row,
        # so index 0 is ALWAYS the top-most turret in the level -- the one nearest
        # the boss, because play starts at the bottom of the map. It looked like a
        # boss/no-spawn interaction and it was `or`.
        #
        # The None case is already handled by the test in front of it, so the
        # index is used as it is.
        index = self.selected_turret
        has = (self.edit_mode.get() == "turret" and index is not None
               and 0 <= index < len(self.project.objects))
        self.delete_turret_button.configure(state="normal" if has else "disabled")

    # ---- terrain painting ------------------------------------------------
    def _paint_start(self, event):
        self.paint_gesture_before = self._project_state()
        self.last_painted_cell = None
        self._paint_event(event)

    def _paint_event(self, event):
        x = int(self.level_canvas.canvasx(event.x))
        y = int(self.level_canvas.canvasy(event.y))
        col, row = x // METATILE_PIXELS, y // METATILE_PIXELS
        if not (0 <= row < self.project.height and 0 <= col < METATILES_PER_ROW):
            return
        if (row, col) == self.last_painted_cell:
            return
        self.last_painted_cell = (row, col)
        if self.stage_rows[row][col] == self.selected_tile:
            return
        self.stage_rows[row][col] = self.selected_tile
        self._redraw_cell(row, col)
        self._update_document_ui()

    def _paint_end(self, event=None):
        self.last_painted_cell = None
        if self.paint_gesture_before is not None and self.paint_gesture_before != self._project_state():
            self._push_undo(self.paint_gesture_before)
        self.paint_gesture_before = None
        self._update_document_ui()

    def _redraw_cell(self, row, col):
        x0, y0 = col * METATILE_PIXELS, row * METATILE_PIXELS
        x1, y1 = x0 + METATILE_PIXELS, y0 + METATILE_PIXELS
        self.level_canvas.delete(f"cell_{row}_{col}")
        tag = (f"cell_{row}_{col}",)
        self.level_canvas.create_rectangle(x0, y0, x1, y1,
                                           fill=C64_COLOURS[self.project.palette["background"]],
                                           outline="", tags=tag)
        self._draw_metatile(self.level_canvas, self.stage_rows[row][col], x0, y0, tags=tag)
        if self.show_grid.get():
            self.level_canvas.create_rectangle(x0, y0, x1, y1, outline=GRID, tags=tag)
        self._draw_turret_markers()
        self._draw_viewport_overlay()

    # ---- stage/level settings ---------------------------------------
    def _apply_stage_row_count(self, event=None):
        """Resize the stage, refusing a shrink that would destroy data.

        THE CONTROLLER DECIDES. It refuses a height that would strand a turret,
        push the no-spawn row past the end of the stage, or leave a trigger with
        nowhere to happen -- and says which. The v5 version offered to discard
        turrets and wave triggers for you; with real encounters in the project
        that is no longer an acceptable default, so the unsafe cases are
        declined and the author resolves them explicitly.

        Losing only BLANK terrain off the end is still allowed silently; losing
        painted terrain still asks.
        """
        try:
            requested = int(self.stage_row_count.get())
        except (tk.TclError, ValueError):
            self.stage_row_count.set(self.project.height)
            return "break" if event else None
        requested = max(MIN_STAGE_ROWS, min(MAX_STAGE_ROWS, requested))
        current = self.project.height
        if requested == current:
            self.stage_row_count.set(current)
            return "break" if event else None

        before = self._project_state()
        if requested < current:
            has_terrain = any(t != 0 for r in self.stage_rows[requested:] for t in r)
            if has_terrain and not messagebox.askyesno(
                    "Reduce stage height?",
                    f"Rows {requested}..{current - 1} carry painted terrain and "
                    f"will be discarded.\n\nReduce the stage height anyway?",
                    parent=self):
                self.stage_row_count.set(current)
                return "break" if event else None
        try:
            self.controller.resize(requested)
        except ControllerError as exc:
            messagebox.showerror("Cannot resize stage", str(exc), parent=self)
            self.stage_row_count.set(current)
            return "break" if event else None

        self.selected_turret = None
        self._push_undo(before)
        self.stage_row_count.set(self.project.height)
        self._clamp_viewport()
        self._draw_level()
        self._update_stage_info()
        self._update_document_ui()
        return "break" if event else None

    def _apply_level_settings(self, event=None):
        try:
            new_palette = {k: int(v.get()) for k, v in self.palette_vars.items()}
        except (tk.TclError, ValueError):
            self._sync_level_settings_controls()
            return "break" if event else None
        # The C64 palette is 0..15 and a character colour is 0..7, because the
        # engine ORs it with the multicolour bit (TERRAIN_COLOUR_RAM = 8 | col).
        ranges = {"background": C.MAX_COLOUR, "multicolour1": C.MAX_COLOUR,
                  "multicolour2": C.MAX_COLOUR, "character": C.MAX_CHARACTER_COLOUR}
        if any(not 0 <= new_palette[k] <= m for k, m in ranges.items()):
            self._sync_level_settings_controls()
            return "break" if event else None
        if new_palette == self.project.palette:
            return "break" if event else None
        before = self._project_state()
        self.project.palette = new_palette
        self.metatile_image_cache.clear()
        self._push_undo(before)
        self.level_canvas.configure(background=C64_COLOURS[self.project.palette["background"]])
        self._draw_palette()
        self._draw_level()
        self._update_stage_info()
        self._update_document_ui()
        if self._encounters is not None and self._encounters.winfo_exists():
            self._encounters.refresh()
        return "break" if event else None

    def _sync_level_settings_controls(self):
        for k, v in self.palette_vars.items():
            v.set(self.project.palette[k])

    def _update_stage_info(self):
        """Duration under the CURRENT contract, derived by contract_v2.

            logicalRows    = metatileRows * 4
            playableRows   = logicalRows - 25      (a screenful never plays)
            playableFrames = playableRows * 8      (1 px/frame, 8 px a row)
            seconds        = playableFrames / 50   (PAL)

        The old formula multiplied total pixels by a scroll divider that the
        engine does not read, and counted the 25 rows the player never scrolls
        through, so it over-reported every stage.
        """
        d = self.controller.duration()
        seconds = d["seconds"]
        minutes = int(seconds // 60)
        rem = int(round(seconds - minutes * 60))
        if rem == 60:
            minutes, rem = minutes + 1, 0
        self.duration_text.set(
            f"\u2248 {minutes}:{rem:02d} at 1 px/frame PAL  "
            f"({d['playableRows']} playable of {d['logicalRows']} logical rows, "
            f"{d['playableFrames']} frames)")
        self.encounter_text.set(self.controller.encounter_summary_text())
        self._update_viewport_text()
        self._update_status()

    def _screen_peak_turrets(self):
        return turret_screen_peak(self.project)

    def _update_status(self):
        mode = self.edit_mode.get()
        if mode == "turret":
            self.status_text.set(
                f"Turret mode: {self._turret_count()} authored, up to {self._screen_peak_turrets()} on "
                f"one gameplay screen (pool {TURRET_POOL})  |  click to place/select, right-click/Delete to remove")
            return
        info = metatile_set_glyph_cost(self.project)
        self.status_text.set(
            f"Selected: {self.selected_tile} {self._metatile_name(self.selected_tile)}  |  "
            f"Level: {self.project.name}  {METATILES_PER_ROW} x {self.project.height}  |  "
            f"Metatiles {self._metatile_count()}/64  ·  Terrain glyphs {info['used']}/{info['capacity']}  |  "
            f"Palette {self.project.palette['background']}/{self.project.palette['multicolour1']}/"
            f"{self.project.palette['multicolour2']}/{self.project.palette['character']}  |  "
            f"v6  \u00b7  {self.controller.encounter_summary_text()}")

    def _update_document_ui(self):
        mark = " *" if self._is_dirty() else ""
        self.title(f"19656 Level Editor - {self.project.name}{mark}")
        path_text = self.project_path.name if self.project_path else "unsaved"
        parent = self.project_path.parent.name if self.project_path else "-"
        self.level_frame.configure(text=f"Working stage: {self.project.name}  ({parent}/{path_text})")
        self.edit_menu.entryconfigure("Undo", state="normal" if self.undo_stack else "disabled")
        self.edit_menu.entryconfigure("Redo", state="normal" if self.redo_stack else "disabled")
        self._update_turret_ui()
        self._update_status()

    # ---- the encounter workspace ----------------------------------------
    def _open_encounters(self):
        """Open (or raise) the encounter authoring window."""
        if self._encounters is not None and self._encounters.winfo_exists():
            self._encounters.deiconify()
            self._encounters.lift()
            self._encounters.focus_set()
            return "break"
        self._encounters = EncounterWorkspace(self)
        return "break"

    def _after_encounter_edit(self):
        """The workspace changed the project: the main window must catch up.

        Encounter edits are ordinary project edits -- the same undo stack, the
        same dirty marker, the same deterministic save -- so the only thing that
        differs is which widgets need redrawing.
        """
        self._update_stage_info()
        self._update_document_ui()

    def _refresh_all(self):
        self.metatile_image_cache.clear()
        self._clamp_viewport()
        self.level_canvas.configure(background=C64_COLOURS[self.project.palette["background"]])
        self._sync_level_settings_controls()
        self.stage_row_count.set(self.project.height)
        self._draw_palette()
        self._draw_level()
        self._update_stage_info()
        self._update_document_ui()
        # THE ENCOUNTER WORKSPACE IS PART OF THE DOCUMENT, and this is the one
        # path every whole-document redraw goes through -- undo and redo
        # included, via _restore_state. Phase 5B refreshed it only from the
        # level-settings path, so undoing an encounter edit restored the model
        # and left the other window showing the state before it.
        if self._encounters is not None and self._encounters.winfo_exists():
            self._encounters.refresh()

    # ---- undo/redo --------------------------------------------------
    def _push_undo(self, state):
        self.undo_stack.append(state)
        self.redo_stack.clear()

    def _restore_state(self, state):
        """Rebuild the document from a snapshot, encounters and all.

        A whole-project restore rather than a field-by-field one: the snapshot
        IS the project's JSON, so anything the GUI cannot edit is restored with
        the same fidelity as the terrain, and undo can never quietly drop it.
        """
        self.controller.restore_json(state)
        self.project = self.controller.view
        self.selected_turret = None
        self.selected_tile = min(self.selected_tile, max(0, self._metatile_count() - 1))
        self.metatile_image_cache.clear()
        self._refresh_all()

    def _undo(self):
        if not self.undo_stack:
            return "break"
        self.redo_stack.append(self._project_state())
        self._restore_state(self.undo_stack.pop())
        return "break"

    def _redo(self):
        if not self.redo_stack:
            return "break"
        self.undo_stack.append(self._project_state())
        self._restore_state(self.redo_stack.pop())
        return "break"

    # ---- file ops -------------------------------------------------
    def _confirm_discard(self):
        if not self._is_dirty():
            return True
        answer = messagebox.askyesnocancel("Unsaved changes",
                                           f"Save changes to {self.project.name} first?", parent=self)
        if answer is None:
            return False
        return self._save_project() if answer else True

    def _adopt_project(self, controller, path):
        """Switch to a level package, resetting ALL editor state (no stale data).

        Takes a CONTROLLER, not a project: the controller is what holds the live
        v6 document, its path and any migration notices, and swapping the whole
        thing is what guarantees no field of the previous document survives.
        """
        self.controller = controller
        self.project = controller.view
        if self._encounters is not None and self._encounters.winfo_exists():
            self._encounters.adopt(controller)      # follow onto the new document
        self.project_path = Path(path) if path else None
        self.metatile_image_cache.clear()
        self.undo_stack.clear()
        self.redo_stack.clear()
        self.selected_turret = None
        self.selected_tile = min(self.selected_tile, max(0, self._metatile_count() - 1))
        self.paint_gesture_before = None
        self.edit_mode.set("terrain")
        self.viewport_top = default_viewport_top(self.project)
        self.saved_state = None if path is None else self._project_state()
        self.level_canvas.yview_moveto(0)
        self._refresh_all()

    def _new_level(self):
        if not self._confirm_discard():
            return "break"
        name = simpledialog.askstring("New Level", "Level name:", initialvalue="new_level", parent=self)
        if not name or not name.strip():
            return "break"
        name = name.strip()
        rows = simpledialog.askinteger("New Level", "Stage rows:", initialvalue=DEFAULT_STAGE_ROWS,
                                       minvalue=MIN_STAGE_ROWS, maxvalue=MAX_STAGE_ROWS, parent=self)
        if rows is None:
            return "break"
        controller = EditorController(self._seed_v6_project(name, rows))
        self._adopt_project(controller, None)   # unsaved; Save writes level.v6.json
        return "break"

    def _open_level(self):
        if not self._confirm_discard():
            return "break"
        initial = self.levels_dir if self.levels_dir.exists() else self.legacy_dir
        path = filedialog.askopenfilename(
            title="Open level package (levels/<name>/level.v6.json) or an older project",
            initialdir=initial,
            filetypes=(("v6 level packages", "level.v6.json"),
                       ("Level JSON", "*.json"), ("All files", "*.*")),
            parent=self)
        if not path:
            return "break"
        try:
            # ONE LOADER FOR EVERY VERSION. v6 opens directly; v1..v5 go through
            # the Phase 1 migration and keep their notices, so an author is told
            # what could not be carried rather than discovering it later.
            controller = EditorController.load(path)
        except Exception as exc:                          # noqa: BLE001
            messagebox.showerror("Open Level", str(exc), parent=self)
            return "break"
        self._adopt_project(controller, path)
        self._report_migration(controller)
        return "break"

    def _report_migration(self, controller):
        """Say what a migration discarded -- concisely, and only when it did."""
        if not controller.migrated:
            return
        dropped = controller.discard_notices()
        head = (f"Opened a formatVersion {controller.from_version} project and "
                f"migrated it to v6.\n\nSaving will write v6.")
        if dropped:
            head += ("\n\nData that could NOT be carried forward:\n"
                     + "\n".join(f"\u2022 {d.message}" for d in dropped))
        messagebox.showinfo("Project migrated", head, parent=self)

    def _validate_before_write(self):
        """v6 validation. Errors block the write and are shown in full."""
        result = self.controller.validate()
        if not result.ok:
            messagebox.showerror(
                "Project validation failed",
                "\n".join(f"\u2022 {i.message}" for i in result.errors),
                parent=self)
            return False
        # THE WRAP-SEAM PROMPT IS GONE, and it was not a matter of taste. It
        # asked whether the first and last stage rows matched "because the stage
        # wraps vertically" -- which stopped being true when stages got a real
        # end. src/scroll.asm sets stageComplete the moment worldProgress reaches
        # STAGE_FINAL_VIEW_PROGRESS and src/boss.asm takes over from there, so a
        # production stage never reaches the row that would fold back to its own
        # beginning. A level now has a beginning and an end, and its last row is
        # the one under the boss.
        return True

    def _default_level_path(self):
        return self.levels_dir / self.project.name / "level.v6.json"

    def _save_project(self):
        if self.project_path is None:
            return self._write_project(self._default_level_path())
        return self._write_project(self.project_path)

    def _save_project_as(self):
        if not self._validate_before_write():
            return False
        path = filedialog.asksaveasfilename(
            title="Save level package", initialdir=self._default_level_path().parent,
            initialfile="level.v6.json", defaultextension=".json",
            filetypes=(("v6 level package", "*.json"), ("All files", "*.*")), parent=self)
        if not path:
            return False
        return self._write_project(Path(path), already_validated=True)

    def _write_project(self, path, already_validated=False):
        """Write deterministic v6 through the controller.

        THE WHOLE PROJECT IS WRITTEN, including the movement programs, wave
        definitions, triggers and no-spawn row this phase cannot edit. Nothing
        is reassembled from what the GUI happens to know about -- see
        controller_v6 -- so opening and saving without an edit reproduces the
        file byte for byte.
        """
        if not already_validated and not self._validate_before_write():
            return False
        try:
            self.controller.save(path)
        except (OSError, ControllerError) as exc:
            messagebox.showerror("Save Project", str(exc), parent=self)
            return False
        self.project_path = self.controller.path
        self.saved_state = self._project_state()
        self._update_document_ui()
        return True

    def _export_kickassembler(self):
        """Generate the six level files with the Phase 4 v6 exporter."""
        if not self._validate_before_write():
            return "break"
        # src/<level>/ is the current layout and the Makefile's LEVELDIR default.
        # src/generated/<level>/ has not existed for a long time.
        default_dir = self.repo_root / "src" / self.project.name
        out = filedialog.askdirectory(
            title=f"Export level '{self.project.name}' package "
                  f"({len(GENERATED_NAMES)} .asm files)",
            initialdir=default_dir if default_dir.parent.exists() else self.repo_root,
            parent=self)
        if not out:
            return "break"
        try:
            # carry_enemies_from is the destination itself: stage_enemies.asm is
            # level-owned but hand-authored, and a level directory without it
            # does not assemble.
            written = self.controller.export(out, carry_enemies_from=out)
        except (OSError, ControllerError, export_v6.ExportRefused) as exc:
            # ExportRefused IS CAUGHT HERE TOO. The controller validates first and
            # normally catches everything, but the exporter keeps its own refusals
            # for anything the model cannot express -- and one of them, a wave id
            # that cannot become an assembler symbol, reached a user as a raw Tk
            # callback traceback. A refusal is an ordinary outcome of pressing
            # Export and it gets an ordinary dialog.
            messagebox.showerror("Export failed", str(exc), parent=self)
            return "break"
        gameplay = ("  (imported by main.asm; rebuild to play)"
                    if self.project.name == "level1"
                    else "  (coexists on disk; not imported by gameplay)")
        messagebox.showinfo(
            "Level package exported",
            "Generated:\n" + "\n".join(str(written[k]) for k in sorted(written))
            + "\n" + gameplay, parent=self)
        return "break"

    def _on_close(self):
        if self._confirm_discard():
            if self._encounters is not None and self._encounters.winfo_exists():
                self._encounters.destroy()
            self._close_import_session()
            self.destroy()
        return "break"


def find_repo_root():
    here = Path(__file__).resolve()
    for parent in (here.parent, *here.parents):
        # The production level lives in src/level1/, which is the Makefile's own
        # LEVELDIR default. The old probe looked for src/generated/level1/
        # stage_test.asm, a path and a filename that no longer exist.
        if (parent / "src" / "main.asm").is_file() and (
            (parent / "src" / "level1" / "stage_map.asm").is_file()
        ):
            return parent
    raise FileNotFoundError(
        "Could not find repo root containing src/main.asm and src/level1/stage_map.asm")


def main():
    try:
        editor = LevelEditor(find_repo_root())
    except Exception as exc:  # noqa: BLE001
        root = tk.Tk()
        root.withdraw()
        messagebox.showerror("19656 Level Editor", str(exc))
        root.destroy()
        return 1
    editor.mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
