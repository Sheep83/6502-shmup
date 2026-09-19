"""Tkinter dialogs for the Terrain Asset Workshop and the source-spritesheet
importer. Kept out of editor.py so that file stays navigable; these use only the
existing Tkinter stack (no new framework) and the shared C64 colour table.

  NativeMetatileEditor  - a reusable zoomed 16x32 multicolour paint canvas with
                          4 project-palette swatches, click/drag paint, visible
                          4x4-char boundaries, mirror/flip, undo/redo and a live
                          glyph-cost readout. Logical pixels render at the VIC-II
                          multicolour 2:1 width:height ratio (a 16x32 logical
                          metatile therefore looks like a 32x32 physical tile).
  WorkshopDialog        - source preview (optional) beside the native editor;
                          Save writes back a native pixel grid + name (+ repo);
                          "Back to Source" returns to the import session.
  ImportDialog          - choose a PNG, set tile size, browse cached thumbnails,
                          pick one tile -> convert -> open the Workshop. Accepts
                          an already-sliced sheet so a persistent import session
                          can be re-shown without re-reading the file.
"""
from __future__ import annotations

import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from engine_data import C64_PALETTE_HEX
from native_metatile import (
    CHAR_H, CHAR_W, CHARS_PER_SIDE, NATIVE_H, NATIVE_W, blank_pixels,
    pixels_to_glyphs, validate_pixels,
)
from spritesheet import slice_sheet
from terrain_convert import source_tile_to_native

LOGICAL_KEYS = ("background", "multicolour1", "multicolour2", "character")
LOGICAL_LABELS = ("0 bg", "1 mc1", "2 mc2", "3 char")


def _logical_hex(project_palette):
    return [C64_PALETTE_HEX[int(project_palette[k]) & 0x0F] for k in LOGICAL_KEYS]


class NativeMetatileEditor(ttk.Frame):
    """Zoomed paint canvas for one native 16x32 metatile (values 0..3).

    Each logical multicolour pixel is a DOUBLE-WIDTH physical pixel, so it is
    drawn `2 * unit` wide by `unit` tall. The stored artwork is unchanged 16x32
    logical pixels; only the display coordinates carry the 2:1 correction, and
    all hit-testing / painting maps mouse coordinates back to the 16x32 cells."""

    def __init__(self, master, project_palette, pixels=None, unit=10,
                 on_change=None, cost_fn=None):
        super().__init__(master)
        self.palette = dict(project_palette)
        self.unit = unit
        self.zx = unit * 2                        # logical pixel width  (double-wide)
        self.zy = unit                            # logical pixel height
        self.pixels = validate_pixels(pixels) if pixels is not None else blank_pixels(0)
        self.on_change = on_change
        self.cost_fn = cost_fn                    # pixels -> dict(used,capacity,candidate_new,...)
        self.active = tk.IntVar(value=3)
        self._undo, self._redo = [], []

        swatches = ttk.Frame(self)
        swatches.grid(row=0, column=0, sticky="w", pady=(0, 4))
        self._swatch_widgets = []
        for i, label in enumerate(LOGICAL_LABELS):
            b = tk.Button(swatches, text=label, width=6,
                          command=lambda v=i: self.active.set(v))
            b.grid(row=0, column=i, padx=2)
            self._swatch_widgets.append(b)
        self._guides = tk.BooleanVar(value=True)
        ttk.Checkbutton(self, text="4x4 char guides", command=self._redraw,
                        variable=self._guides).grid(row=0, column=1, sticky="e")

        tools = ttk.Frame(self)
        tools.grid(row=1, column=0, columnspan=2, sticky="w", pady=(0, 4))
        ttk.Button(tools, text="Mirror H", width=9,
                   command=self.mirror_horizontal).pack(side="left", padx=(0, 3))
        ttk.Button(tools, text="Flip V", width=9,
                   command=self.flip_vertical).pack(side="left", padx=3)
        ttk.Button(tools, text="Undo", width=6, command=self.undo).pack(side="left", padx=(12, 3))
        ttk.Button(tools, text="Redo", width=6, command=self.redo).pack(side="left", padx=3)

        self.canvas = tk.Canvas(self, width=NATIVE_W * self.zx, height=NATIVE_H * self.zy,
                                highlightthickness=1, highlightbackground="#888",
                                background="#101010")
        self.canvas.grid(row=2, column=0, columnspan=2)
        self.canvas.bind("<Button-1>", self._paint_start)
        self.canvas.bind("<B1-Motion>", self._paint_drag)
        self.canvas.bind("<ButtonRelease-1>", lambda e: self._commit())

        self.cost_label = ttk.Label(self, text="")
        self.cost_label.grid(row=3, column=0, columnspan=2, sticky="w", pady=(4, 0))

        self._before = None
        self._apply_palette_to_swatches()
        self._redraw()

    # -- palette / redraw --------------------------------------------------
    def set_palette(self, project_palette):
        self.palette = dict(project_palette)
        self._apply_palette_to_swatches()
        self._redraw()

    def _apply_palette_to_swatches(self):
        for i, hexc in enumerate(_logical_hex(self.palette)):
            fg = "#000" if i in (1, 3) else "#fff"
            self._swatch_widgets[i].configure(background=hexc, activebackground=hexc,
                                              foreground=fg)

    def _redraw(self):
        self.canvas.delete("all")
        zx, zy = self.zx, self.zy
        hexes = _logical_hex(self.palette)
        for y in range(NATIVE_H):
            for x in range(NATIVE_W):
                self.canvas.create_rectangle(
                    x * zx, y * zy, x * zx + zx, y * zy + zy,
                    fill=hexes[self.pixels[y][x]], outline="#333")
        if self._guides.get():
            for c in range(1, CHARS_PER_SIDE):
                self.canvas.create_line(c * CHAR_W * zx, 0, c * CHAR_W * zx, NATIVE_H * zy,
                                        fill="#ffd000", width=2)
            for r in range(1, CHARS_PER_SIDE):
                self.canvas.create_line(0, r * CHAR_H * zy, NATIVE_W * zx, r * CHAR_H * zy,
                                        fill="#ffd000", width=2)
        self._update_cost()

    def _update_cost(self):
        if not self.cost_fn:
            self.cost_label.configure(text="")
            return
        info = self.cost_fn(self.pixels)
        self.cost_label.configure(
            text=(f"Terrain glyphs: {info['used']} / {info['capacity']}   |   "
                  f"this metatile: 16 cells, {info['candidate_reuse']} existing reused, "
                  f"{info['candidate_new']} new unique required"))

    # -- painting -------------------------------------------------------
    def _cell(self, event):
        """Map a mouse position back to a logical 16x32 cell (2:1 corrected)."""
        x = int(self.canvas.canvasx(event.x)) // self.zx
        y = int(self.canvas.canvasy(event.y)) // self.zy
        if 0 <= x < NATIVE_W and 0 <= y < NATIVE_H:
            return x, y
        return None

    def _paint_start(self, event):
        self._before = [row[:] for row in self.pixels]
        self._paint_drag(event)

    def _paint_drag(self, event):
        cell = self._cell(event)
        if not cell:
            return
        x, y = cell
        v = self.active.get()
        if self.pixels[y][x] != v:
            self.pixels[y][x] = v
            zx, zy = self.zx, self.zy
            self.canvas.create_rectangle(x * zx, y * zy, x * zx + zx, y * zy + zy,
                                         fill=_logical_hex(self.palette)[v], outline="#333")
            self._update_cost()

    def _commit(self):
        if self._before is not None and self._before != self.pixels:
            self._undo.append(self._before)
            self._redo.clear()
            if self.on_change:
                self.on_change()
        self._before = None

    # -- transforms (each is exactly ONE undoable edit) -----------------
    def _apply_transform(self, fn):
        before = [row[:] for row in self.pixels]
        new = fn(self.pixels)
        if new == self.pixels:
            return
        self._undo.append(before)
        self._redo.clear()
        self.pixels = new
        self._redraw()
        if self.on_change:
            self.on_change()

    def mirror_horizontal(self):
        """Reflect the logical artwork left<->right. Applied at the 16x32
        logical-pixel layer, before glyph decomposition. Twice == identity."""
        self._apply_transform(lambda px: [list(reversed(row)) for row in px])

    def flip_vertical(self):
        """Reflect the logical artwork top<->bottom. Twice == identity."""
        self._apply_transform(lambda px: [row[:] for row in reversed(px)])

    def undo(self):
        if self._undo:
            self._redo.append([r[:] for r in self.pixels])
            self.pixels = self._undo.pop()
            self._redraw()
            if self.on_change:
                self.on_change()

    def redo(self):
        if self._redo:
            self._undo.append([r[:] for r in self.pixels])
            self.pixels = self._redo.pop()
            self._redraw()
            if self.on_change:
                self.on_change()

    def get_pixels(self):
        return [row[:] for row in self.pixels]


class WorkshopDialog(tk.Toplevel):
    """Turn a source tile (or a blank canvas) into an editable native C64
    multicolour metatile. `on_save(name, pixels)` is called when the user saves;
    it should update the project and return None or an error string."""

    def __init__(self, master, project_palette, *, title="Terrain Asset Workshop",
                 name="metatile", pixels=None, source_rgb=None, cost_fn=None,
                 on_save=None, allow_repo_save=None, on_back=None):
        super().__init__(master)
        self.title(title)
        self.transient(master)
        self.on_save = on_save
        self.allow_repo_save = allow_repo_save          # callable(name, pixels) or None
        self.on_back = on_back                          # callable() -> re-open the import session
        self.result = None
        self.went_back = False

        top = ttk.Frame(self, padding=10)
        top.pack(fill="both", expand=True)

        if source_rgb is not None:
            src = ttk.LabelFrame(top, text="Source tile (image)", padding=6)
            src.grid(row=0, column=0, padx=(0, 12), sticky="n")
            h = len(source_rgb)
            w = len(source_rgb[0]) if h else 0
            zoom = max(1, 224 // max(w, 1))
            c = tk.Canvas(src, width=w * zoom, height=h * zoom, highlightthickness=0)
            c.pack()
            img = tk.PhotoImage(width=w * zoom, height=h * zoom)
            img.put(" ".join(
                "{" + " ".join("#%02x%02x%02x" % tuple(source_rgb[y][x]) for x in range(w)
                               for _ in range(zoom)) + "}"
                for y in range(h) for _ in range(zoom)))
            c.create_image(0, 0, anchor="nw", image=img)
            c._img = img                                # keep a ref

        edit = ttk.LabelFrame(top, text="Native C64 multicolour (16 x 32 logical pixels)", padding=6)
        edit.grid(row=0, column=1, sticky="n")
        namebar = ttk.Frame(edit)
        namebar.pack(fill="x", pady=(0, 6))
        ttk.Label(namebar, text="Name").pack(side="left")
        self.name_var = tk.StringVar(value=name)
        ttk.Entry(namebar, textvariable=self.name_var, width=26).pack(side="left", padx=6)

        self.editor = NativeMetatileEditor(edit, project_palette, pixels=pixels,
                                           cost_fn=cost_fn)
        self.editor.pack()
        self.bind("<Control-z>", lambda e: self.editor.undo())
        self.bind("<Control-Shift-Z>", lambda e: self.editor.redo())
        self.bind("<Control-m>", lambda e: self.editor.mirror_horizontal())
        self.bind("<Control-f>", lambda e: self.editor.flip_vertical())

        btns = ttk.Frame(top)
        btns.grid(row=1, column=0, columnspan=2, sticky="e", pady=(10, 0))
        if on_back:
            ttk.Button(btns, text="◄ Back to Source", command=self._back).pack(side="left", padx=4)
        if allow_repo_save:
            ttk.Button(btns, text="Save to repository…", command=self._save_repo).pack(side="left", padx=4)
        ttk.Button(btns, text="Cancel", command=self.destroy).pack(side="left", padx=4)
        ttk.Button(btns, text="Save to level", command=self._save_level).pack(side="left", padx=4)

        self.grab_set()

    def _back(self):
        """Close this Workshop and hand control back to the import session."""
        self.went_back = True
        cb = self.on_back
        self.destroy()
        if cb:
            cb()

    def _save_level(self):
        name = self.name_var.get().strip()
        if not name:
            messagebox.showerror("Name required", "Give the metatile a name.", parent=self)
            return
        err = self.on_save(name, self.editor.get_pixels()) if self.on_save else None
        if err:
            messagebox.showerror("Cannot save", err, parent=self)
            return
        self.result = (name, self.editor.get_pixels())
        self.destroy()

    def _save_repo(self):
        name = self.name_var.get().strip()
        if not name:
            messagebox.showerror("Name required", "Give the asset a name.", parent=self)
            return
        err = self.allow_repo_save(name, self.editor.get_pixels())
        if err:
            messagebox.showerror("Repository", err, parent=self)
        else:
            messagebox.showinfo("Repository", f"Saved '{name}' to the terrain repository.", parent=self)


class ImportDialog(tk.Toplevel):
    """Choose a source spritesheet, slice it, browse cached thumbnails, and pick
    one tile. `on_pick(rgb_rows, provenance, dialog)` is called with the chosen
    tile; the dialog is passed so the caller can stash it as a persistent import
    session and re-`show()` it later without re-reading the PNG.

    Pass `sheet=` (an already-sliced spritesheet.SpriteSheet) to restore a
    session; `select_index=` highlights a tile."""

    def __init__(self, master, *, on_pick=None, initial_dir=None,
                 sheet=None, select_index=None):
        super().__init__(master)
        self.title("Import source spritesheet")
        self.transient(master)
        self.on_pick = on_pick
        self.sheet = sheet
        self.last_index = select_index
        self._thumbs = []

        bar = ttk.Frame(self, padding=8)
        bar.pack(fill="x")
        ttk.Button(bar, text="Choose PNG…", command=self._choose).pack(side="left")
        ttk.Label(bar, text="  Tile W").pack(side="left")
        self.tw = tk.IntVar(value=sheet.tile_w if sheet else 32)
        ttk.Spinbox(bar, from_=1, to=256, width=5, textvariable=self.tw,
                    command=self._reslice).pack(side="left")
        ttk.Label(bar, text=" H").pack(side="left")
        self.th = tk.IntVar(value=sheet.tile_h if sheet else 32)
        ttk.Spinbox(bar, from_=1, to=256, width=5, textvariable=self.th,
                    command=self._reslice).pack(side="left")
        self.info = ttk.Label(bar, text="no sheet loaded")
        self.info.pack(side="left", padx=10)

        body = ttk.Frame(self, padding=(8, 0, 8, 8))
        body.pack(fill="both", expand=True)
        self.canvas = tk.Canvas(body, width=560, height=420, background="#181818",
                                highlightthickness=0)
        sb = ttk.Scrollbar(body, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=sb.set)
        self.canvas.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        self._initial_dir = initial_dir
        if sheet is not None:
            self._path = str(sheet.path)
            self._describe()
            self._render_thumbs()

    # -- shown/hidden so a session survives without re-reading the file --
    def show(self):
        self.deiconify()
        self.lift()
        self.grab_set()

    def hide(self):
        try:
            self.grab_release()
        except tk.TclError:
            pass
        self.withdraw()

    def _choose(self):
        path = filedialog.askopenfilename(
            title="Source spritesheet (PNG)", initialdir=self._initial_dir,
            filetypes=(("PNG image", "*.png"), ("All files", "*.*")), parent=self)
        if not path:
            return
        self._path = path
        self.last_index = None                            # a new PNG replaces the session
        self._reslice()

    def _reslice(self):
        if not getattr(self, "_path", None):
            return
        try:
            self.sheet = slice_sheet(self._path, self.tw.get(), self.th.get())
        except Exception as exc:                          # noqa: BLE001 - surface to user
            messagebox.showerror("Import", str(exc), parent=self)
            return
        self._describe()
        self._render_thumbs()

    def _describe(self):
        warn = ("  ⚠ " + "; ".join(self.sheet.warnings)) if self.sheet.warnings else ""
        self.info.configure(
            text=f"{self.sheet.path.name}  ·  {self.sheet.width}x{self.sheet.height}px → "
                 f"{self.sheet.cols_count}×{self.sheet.rows_count} tiles{warn}")

    def _render_thumbs(self):
        self.canvas.delete("all")
        self._thumbs.clear()
        s = self.sheet
        pad, cell = 6, 40
        per_row = max(1, 560 // (cell + pad))
        for idx in range(s.tile_count):
            r, c = divmod(idx, per_row)
            x, y = pad + c * (cell + pad), pad + r * (cell + pad)
            tile = s.tile(idx)
            step = max(1, s.tile_w // cell)
            img = tk.PhotoImage(width=cell, height=cell)
            rowspec = []
            for ty in range(0, cell):
                sy = min(s.tile_h - 1, ty * step)
                rowspec.append("{" + " ".join(
                    "#%02x%02x%02x" % tuple(tile[sy][min(s.tile_w - 1, tx * step)])
                    for tx in range(cell)) + "}")
            img.put(" ".join(rowspec))
            self._thumbs.append(img)
            tag = f"t{idx}"
            self.canvas.create_image(x, y, anchor="nw", image=img, tags=tag)
            self.canvas.tag_bind(tag, "<Button-1>", lambda e, i=idx: self._pick(i))
            if idx == self.last_index:
                self.canvas.create_rectangle(x - 2, y - 2, x + cell + 2, y + cell + 2,
                                             outline="#ffd000", width=3, tags="sel")
        rows = (s.tile_count + per_row - 1) // per_row
        self.canvas.configure(scrollregion=(0, 0, 560, pad + rows * (cell + pad)))

    def _pick(self, idx):
        self.last_index = idx
        col, row = self.sheet.tile_coords(idx)
        prov = {
            "sourcePack": "",
            "sourceTileIndex": idx,
            "sourceCoords": [col, row],
            "sourceTileSize": [self.sheet.tile_w, self.sheet.tile_h],
            "localSourcePath": str(self.sheet.path),
        }
        self._render_thumbs()                             # show the new selection
        if self.on_pick:
            self.on_pick(self.sheet.tile(idx), prov, self)
