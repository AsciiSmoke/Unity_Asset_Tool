"""
Unity Asset Tool
Extract .bundle / .assets files into folders, repack folders back,
and search across all bundles in a folder for matching field names/values.
Requires: pip install UnityPy
"""

import os
import sys
import json
import shutil
import struct
import threading
import tkinter as tk
from datetime import datetime
from tkinter import filedialog, messagebox, ttk
from pathlib import Path

try:
    import UnityPy
    from UnityPy.enums import ClassIDType
except ImportError:
    messagebox.showerror(
        "Missing dependency",
        "UnityPy is not installed.\n\nRun:  pip install UnityPy\n\nthen restart this tool."
    )
    sys.exit(1)


# ── Extraction helpers ────────────────────────────────────────────────────────

EXPORT_TYPES = {
    ClassIDType.Texture2D,
    ClassIDType.Sprite,
    ClassIDType.AudioClip,
    ClassIDType.TextAsset,
    ClassIDType.Font,
    ClassIDType.Mesh,
    ClassIDType.Shader,
    ClassIDType.MonoBehaviour,
    ClassIDType.AnimationClip,
    ClassIDType.GameObject,
    ClassIDType.Material,
}

EXTENSION_MAP = {
    ClassIDType.Texture2D:      ".png",
    ClassIDType.Sprite:         ".png",
    ClassIDType.AudioClip:      ".wav",
    ClassIDType.TextAsset:      ".txt",
    ClassIDType.Font:           ".ttf",
    ClassIDType.Mesh:           ".obj",
    ClassIDType.Shader:         ".shader",
    ClassIDType.MonoBehaviour:  ".json",
    ClassIDType.AnimationClip:  ".anim.json",
    ClassIDType.GameObject:     ".go.json",
    ClassIDType.Material:       ".mat.json",
}

EXTRACT_PREFIX = "extract__"

# Types that are worth scanning for gameplay data
SEARCH_TYPES = {
    ClassIDType.MonoBehaviour,
    ClassIDType.TextAsset,
    ClassIDType.GameObject,
    ClassIDType.Material,
    ClassIDType.AnimationClip,
}


def safe_name(name: str) -> str:
    """Strip characters that are invalid in file/folder names."""
    keep = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"
               "0123456789._- ()")
    cleaned = "".join(c if c in keep else "_" for c in name)
    return cleaned.strip("_") or "unnamed"


def export_object(obj, out_dir: Path, log) -> bool:
    """Export a single Unity object to the appropriate format. Returns True on success."""
    try:
        type_name = obj.type.name
        type_dir = out_dir / type_name
        type_dir.mkdir(parents=True, exist_ok=True)

        data = obj.read()
        name = safe_name(getattr(data, "m_Name", None) or f"object_{obj.path_id}")
        ext = EXTENSION_MAP.get(obj.type, ".bin")

        # ── Texture2D / Sprite ────────────────────────────────────────────────
        if obj.type in (ClassIDType.Texture2D, ClassIDType.Sprite):
            img = data.image
            if img is None:
                log(f"  [skip] {type_name}/{name} — no image data")
                return False
            dest = type_dir / f"{name}.png"
            img.save(str(dest))

        # ── AudioClip ─────────────────────────────────────────────────────────
        elif obj.type == ClassIDType.AudioClip:
            samples = data.samples
            if not samples:
                log(f"  [skip] {type_name}/{name} — no audio samples")
                return False
            for clip_name, clip_data in samples.items():
                dest = type_dir / f"{safe_name(clip_name)}.wav"
                with open(dest, "wb") as f:
                    f.write(clip_data)

        # ── TextAsset ─────────────────────────────────────────────────────────
        elif obj.type == ClassIDType.TextAsset:
            raw = data.m_Script
            # Detect binary vs text
            try:
                text = raw.decode("utf-8") if isinstance(raw, (bytes, bytearray)) else raw
                dest = type_dir / f"{name}.txt"
                with open(dest, "w", encoding="utf-8") as f:
                    f.write(text)
            except (UnicodeDecodeError, AttributeError):
                dest = type_dir / f"{name}.bin"
                with open(dest, "wb") as f:
                    f.write(raw if isinstance(raw, (bytes, bytearray)) else bytes(raw))

        # ── Everything else — try typetree -> JSON, else raw bytes ────────────
        else:
            try:
                tree = obj.read_typetree()
                dest = type_dir / f"{name}{ext}"
                with open(dest, "w", encoding="utf-8") as f:
                    json.dump(tree, f, indent=2, default=str)
            except Exception:
                raw = bytes(obj.get_raw_data())
                dest = type_dir / f"{name}.bin"
                with open(dest, "wb") as f:
                    f.write(raw)

        log(f"  [ok]   {type_name}/{dest.name}")
        return True

    except Exception as exc:
        log(f"  [err]  path_id={obj.path_id} type={obj.type.name} — {exc}")
        return False


def extract_file(src: Path, log) -> tuple[int, int]:
    """
    Extract a .bundle or .assets file into a prefixed folder beside it.
    e.g.  level1.bundle  ->  extract__level1.bundle/
    Returns (exported_count, skipped_count).
    """
    out_dir = src.parent / f"{EXTRACT_PREFIX}{src.name}"
    out_dir.mkdir(exist_ok=True)

    # Write a manifest so we can re-pack later
    manifest = {
        "source_file": src.name,
        "source_ext": src.suffix.lower(),
    }
    with open(out_dir / "_manifest.json", "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)

    env = UnityPy.load(str(src))
    ok = skip = 0

    for obj in env.objects:
        if obj.type in EXPORT_TYPES:
            if export_object(obj, out_dir, log):
                ok += 1
            else:
                skip += 1
        else:
            skip += 1

    return ok, skip


# ── Search helpers ────────────────────────────────────────────────────────────

class SearchMatch:
    """One matched field found during a bundle scan."""

    def __init__(self, bundle: str, obj_type: str, obj_name: str,
                 field_path: str, value):
        self.bundle     = bundle
        self.obj_type   = obj_type
        self.obj_name   = obj_name
        self.field_path = field_path
        self.value      = value


    def __str__(self) -> str:
        return (
            f"[{self.bundle}]  {self.obj_type}/{self.obj_name}\n"
            f"    {self.field_path} = {self.value!r}"
        )


def _walk_tree(node, keywords: list[str], path: str, results: list,
               bundle: str, obj_type: str, obj_name: str):
    """
    Recursively walk a typetree dict/list and collect any key whose name
    (case-insensitive) contains one of the keywords.
    """
    if isinstance(node, dict):
        for key, val in node.items():
            child_path = f"{path}.{key}" if path else key
            key_lower = key.lower()
            if any(kw in key_lower for kw in keywords):
                results.append(SearchMatch(bundle, obj_type, obj_name,
                                           child_path, val))
            # Always recurse, even on a matched key, in case it's a nested obj
            _walk_tree(val, keywords, child_path, results,
                       bundle, obj_type, obj_name)

    elif isinstance(node, list):
        for i, item in enumerate(node):
            _walk_tree(item, keywords, f"{path}[{i}]", results,
                       bundle, obj_type, obj_name)


def search_bundles(
    folder: Path,
    keywords: list[str],
    log,
    progress_cb=None,
    cancel_flag: list = None,
) -> list[SearchMatch]:
    """
    Scan every .bundle and .assets file in folder for fields whose names
    contain any of the given keywords (case-insensitive).

    progress_cb(current, total) is called after each file is processed.
    cancel_flag is a list containing one bool; set cancel_flag[0] = True
    from another thread to abort early.
    """
    extensions = {".bundle", ".assets"}
    files = [
        f for f in folder.iterdir()
        if f.is_file() and f.suffix.lower() in extensions
    ]
    files.sort(key=lambda f: f.name.lower())

    total   = len(files)
    matches = []
    kw_lower = [k.lower().strip() for k in keywords if k.strip()]

    if not kw_lower:
        log("  [warn] No keywords supplied — nothing to search for")
        return matches

    log(f"Scanning {total} file(s) for keywords: {', '.join(kw_lower)}")

    for idx, bundle_path in enumerate(files):
        if cancel_flag and cancel_flag[0]:
            log("  [warn] Search cancelled")
            break

        log(f"  [{idx + 1}/{total}]  {bundle_path.name}")

        try:
            env = UnityPy.load(str(bundle_path))
            for obj in env.objects:
                if obj.type not in SEARCH_TYPES:
                    continue
                try:
                    if obj.type == ClassIDType.TextAsset:
                        data = obj.read()
                        raw  = data.m_Script
                        try:
                            text = (
                                raw.decode("utf-8")
                                if isinstance(raw, (bytes, bytearray))
                                else str(raw)
                            )
                            # Search TextAsset content as a flat string
                            for kw in kw_lower:
                                if kw in text.lower():
                                    matches.append(SearchMatch(
                                        bundle_path.name,
                                        "TextAsset",
                                        safe_name(getattr(data, "m_Name", "") or "unnamed"),
                                        "(text content)",
                                        f"<contains '{kw}'>",
                                    ))
                                    break
                        except (UnicodeDecodeError, AttributeError):
                            pass
                    else:
                        tree = obj.read_typetree()
                        data = obj.read()
                        obj_name = safe_name(
                            getattr(data, "m_Name", None) or f"object_{obj.path_id}"
                        )
                        _walk_tree(tree, kw_lower, "", matches,
                                   bundle_path.name, obj.type.name, obj_name)
                except Exception:
                    pass

        except Exception as exc:
            log(f"  [err]  {bundle_path.name} — {exc}")

        if progress_cb:
            progress_cb(idx + 1, total)

    return matches


# ── Repack helpers ────────────────────────────────────────────────────────────

def repack_folder(src_dir: Path, log) -> Path:
    """
    Repack a previously extracted folder back into its original bundle/assets file.
    The manifest is used to determine the output extension and original filename.
    Any existing output file is backed up as  <name>.<ext>.YYYYMMDD.HHmmss  first.
    Returns the path to the written output file.
    """
    manifest_path = src_dir / "_manifest.json"
    if not manifest_path.exists():
        raise FileNotFoundError(
            f"No _manifest.json found in {src_dir}.\n"
            "Only folders extracted by this tool can be repacked."
        )

    with open(manifest_path, encoding="utf-8") as f:
        manifest = json.load(f)

    original_name = manifest.get("source_file", src_dir.name)
    original_ext  = manifest.get("source_ext", ".bundle")

    # Strip the extract__ prefix from the folder name if the manifest name
    # still somehow carries it (shouldn't, but be defensive).
    if original_name.startswith(EXTRACT_PREFIX):
        original_name = original_name[len(EXTRACT_PREFIX):]

    out_path = src_dir.parent / original_name

    # Locate the original bundle/assets file to use as base
    if not out_path.exists():
        raise FileNotFoundError(
            f"Original source file '{original_name}' not found next to the folder.\n"
            "The original file must be present to repack (it acts as the base)."
        )

    log(f"Loading original: {original_name}")

    # Read the entire bundle into memory so the file handle is closed before
    # we attempt to rename it — UnityPy uses lazy I/O which keeps the file
    # locked until we do this explicitly.
    with open(out_path, "rb") as fh:
        bundle_bytes = fh.read()

    env = UnityPy.load(bundle_bytes)

    # Build a lookup of modified files by type + name
    modified: dict[tuple[str, str], Path] = {}
    for type_dir in src_dir.iterdir():
        if not type_dir.is_dir() or type_dir.name.startswith("_"):
            continue
        for item in type_dir.iterdir():
            key = (type_dir.name, item.stem.split(".")[0])
            modified[key] = item

    patched = 0
    for obj in env.objects:
        # Sprites cannot be written back via UnityPy — skip silently
        if obj.type == ClassIDType.Sprite:
            continue

        name = None
        try:
            data = obj.read()
            name = safe_name(getattr(data, "m_Name", None) or f"object_{obj.path_id}")
        except Exception:
            continue

        key = (obj.type.name, name)
        if key not in modified:
            continue

        file_path = modified[key]
        try:
            if file_path.suffix == ".json":
                with open(file_path, encoding="utf-8") as f:
                    tree = json.load(f)
                obj.save_typetree(tree)
                log(f"  [patched] {obj.type.name}/{name}")
                patched += 1
            elif file_path.suffix == ".png":
                from PIL import Image
                img = Image.open(file_path)
                data.image = img
                data.save()
                log(f"  [patched] {obj.type.name}/{name}")
                patched += 1
            elif file_path.suffix in (".wav", ".bin", ".txt"):
                with open(file_path, "rb") as f:
                    raw = f.read()
                obj.set_raw_data(raw)
                log(f"  [patched] {obj.type.name}/{name}")
                patched += 1
        except Exception as exc:
            log(f"  [err]  {obj.type.name}/{name} — {exc}")

    if patched == 0:
        log("  [warn] No objects were patched — output will match original")

    # File handle is already closed, so the rename is safe now
    timestamp   = datetime.now().strftime("%Y%m%d.%H%M%S")
    backup_path = out_path.with_name(f"{out_path.name}.{timestamp}")
    out_path.rename(backup_path)
    log(f"Backed up original  ->  {backup_path.name}")

    with open(out_path, "wb") as f:
        f.write(env.file.save())

    log(f"Saved: {out_path.name}  ({patched} object(s) patched)")
    return out_path


# ── GUI ───────────────────────────────────────────────────────────────────────

class App(tk.Tk):

    PAD      = 10
    BG       = "#1a1a2e"
    BG2      = "#16213e"
    ACCENT   = "#0f3460"
    BUTTON   = "#e94560"
    BUTTON_H = "#c73652"
    FG       = "#eaeaea"
    FG_DIM   = "#8888aa"
    MONO     = ("Consolas", 9)
    HEADING  = ("Segoe UI", 11, "bold")

    def __init__(self):
        super().__init__()
        self.title("Unity Asset Tool")
        self.configure(bg=self.BG)
        self.resizable(True, True)
        self.minsize(800, 560)

        self._search_results: list[SearchMatch] = []
        self._cancel_flag = [False]

        self._build_ui()
        self._center()


    def _center(self):
        self.update_idletasks()
        w, h = 900, 640
        sw = self.winfo_screenwidth()
        sh = self.winfo_screenheight()
        self.geometry(f"{w}x{h}+{(sw - w)//2}+{(sh - h)//2}")


    def _build_ui(self):
        p = self.PAD

        # ── Title bar ─────────────────────────────────────────────────────────
        title_frame = tk.Frame(self, bg=self.ACCENT, pady=p)
        title_frame.pack(fill="x")

        tk.Label(
            title_frame,
            text="⬡  Unity Asset Tool",
            font=("Segoe UI", 14, "bold"),
            bg=self.ACCENT,
            fg=self.FG,
        ).pack(side="left", padx=p * 2)

        try:
            ver = UnityPy.__version__
        except AttributeError:
            ver = "?"

        tk.Label(
            title_frame,
            text=f"UnityPy {ver}",
            font=("Segoe UI", 9),
            bg=self.ACCENT,
            fg=self.FG_DIM,
        ).pack(side="right", padx=p * 2)

        # ── Three action panels side by side ──────────────────────────────────
        panels = tk.Frame(self, bg=self.BG)
        panels.pack(fill="x", padx=p, pady=p)

        self._build_extract_panel(panels)
        self._build_repack_panel(panels)
        self._build_search_panel(panels)

        # ── Log output ────────────────────────────────────────────────────────
        log_frame = tk.Frame(self, bg=self.BG)
        log_frame.pack(fill="both", expand=True, padx=p, pady=(0, p))

        header_row = tk.Frame(log_frame, bg=self.BG)
        header_row.pack(fill="x")

        tk.Label(
            header_row,
            text="Log",
            font=self.HEADING,
            bg=self.BG,
            fg=self.FG_DIM,
            anchor="w",
        ).pack(side="left")

        self._save_results_btn = tk.Button(
            header_row,
            text="Save search results…",
            command=self._save_results,
            bg=self.ACCENT,
            fg=self.FG_DIM,
            activebackground=self.BG2,
            activeforeground=self.FG,
            relief="flat",
            padx=8,
            pady=2,
            font=("Segoe UI", 8),
            cursor="hand2",
            state="disabled",
        )
        self._save_results_btn.pack(side="right", padx=(p, 0))

        tk.Button(
            header_row,
            text="Clear log",
            command=self._clear_log,
            bg=self.ACCENT,
            fg=self.FG_DIM,
            activebackground=self.BG2,
            activeforeground=self.FG,
            relief="flat",
            padx=8,
            pady=2,
            font=("Segoe UI", 8),
            cursor="hand2",
        ).pack(side="right")

        scroll = tk.Scrollbar(log_frame, bg=self.BG2)
        scroll.pack(side="right", fill="y")

        self.log_box = tk.Text(
            log_frame,
            wrap="word",
            yscrollcommand=scroll.set,
            state="disabled",
            bg=self.BG2,
            fg=self.FG,
            insertbackground=self.FG,
            font=self.MONO,
            relief="flat",
            padx=6,
            pady=6,
        )
        self.log_box.pack(fill="both", expand=True)
        scroll.config(command=self.log_box.yview)

        # Colour tags
        self.log_box.tag_config("ok",     foreground="#4ec94e")
        self.log_box.tag_config("err",    foreground="#e94560")
        self.log_box.tag_config("warn",   foreground="#f0b429")
        self.log_box.tag_config("info",   foreground="#64b5f6")
        self.log_box.tag_config("dim",    foreground=self.FG_DIM)
        self.log_box.tag_config("match",  foreground="#f0b429")
        self.log_box.tag_config("match2", foreground="#eaeaea")


    def _panel(self, parent, title):
        frame = tk.Frame(parent, bg=self.BG2, padx=self.PAD, pady=self.PAD)
        frame.pack(side="left", fill="both", expand=True,
                   padx=(0, self.PAD // 2))

        tk.Label(
            frame,
            text=title,
            font=self.HEADING,
            bg=self.BG2,
            fg=self.FG,
            anchor="w",
        ).pack(fill="x", pady=(0, self.PAD // 2))

        return frame


    def _btn(self, parent, text, command):
        b = tk.Button(
            parent,
            text=text,
            command=command,
            bg=self.BUTTON,
            fg=self.FG,
            activebackground=self.BUTTON_H,
            activeforeground=self.FG,
            relief="flat",
            padx=12,
            pady=6,
            font=("Segoe UI", 10, "bold"),
            cursor="hand2",
        )
        b.pack(fill="x", pady=(self.PAD // 2, 0))
        return b


    def _file_row(self, parent, label_text, var, browse_cmd):
        row = tk.Frame(parent, bg=self.BG2)
        row.pack(fill="x", pady=2)

        tk.Label(
            row,
            text=label_text,
            bg=self.BG2,
            fg=self.FG_DIM,
            font=("Segoe UI", 9),
            width=8,
            anchor="w",
        ).pack(side="left")

        entry = tk.Entry(
            row,
            textvariable=var,
            bg=self.ACCENT,
            fg=self.FG,
            insertbackground=self.FG,
            relief="flat",
            font=("Segoe UI", 9),
        )
        entry.pack(side="left", fill="x", expand=True, padx=(4, 4))

        tk.Button(
            row,
            text="…",
            command=browse_cmd,
            bg=self.ACCENT,
            fg=self.FG,
            activebackground=self.BUTTON,
            relief="flat",
            padx=6,
            cursor="hand2",
        ).pack(side="right")


    def _build_extract_panel(self, parent):
        frame = self._panel(parent, "📦  Extract")

        self.extract_file_var = tk.StringVar()
        self._file_row(
            frame,
            "File:",
            self.extract_file_var,
            self._browse_extract_file,
        )

        tk.Label(
            frame,
            text="Output folder created next to the source file,\n"
                 "prefixed with extract__  (e.g. extract__level1.bundle/)",
            bg=self.BG2,
            fg=self.FG_DIM,
            font=("Segoe UI", 8),
            justify="left",
        ).pack(anchor="w", pady=(6, 0))

        self.extract_btn = self._btn(frame, "Extract", self._do_extract)


    def _build_repack_panel(self, parent):
        frame = self._panel(parent, "🔧  Repack")

        self.repack_folder_var = tk.StringVar()
        self._file_row(
            frame,
            "Folder:",
            self.repack_folder_var,
            self._browse_repack_folder,
        )

        tk.Label(
            frame,
            text="Select an extract__ folder from this tool.\n"
                 "The original file is backed up with a timestamp before saving.",
            bg=self.BG2,
            fg=self.FG_DIM,
            font=("Segoe UI", 8),
            justify="left",
        ).pack(anchor="w", pady=(6, 0))

        self.repack_btn = self._btn(frame, "Repack", self._do_repack)


    def _build_search_panel(self, parent):
        frame = self._panel(parent, "🔍  Search Bundles")

        self.search_folder_var = tk.StringVar()
        self._file_row(
            frame,
            "Folder:",
            self.search_folder_var,
            self._browse_search_folder,
        )

        kw_row = tk.Frame(frame, bg=self.BG2)
        kw_row.pack(fill="x", pady=(6, 0))

        tk.Label(
            kw_row,
            text="Keywords:",
            bg=self.BG2,
            fg=self.FG_DIM,
            font=("Segoe UI", 9),
            width=8,
            anchor="w",
        ).pack(side="left")

        self.search_keywords_var = tk.StringVar(value="time,limit,score,size")
        tk.Entry(
            kw_row,
            textvariable=self.search_keywords_var,
            bg=self.ACCENT,
            fg=self.FG,
            insertbackground=self.FG,
            relief="flat",
            font=("Segoe UI", 9),
        ).pack(side="left", fill="x", expand=True, padx=(4, 0))

        tk.Label(
            frame,
            text="Comma-separated — matches any field name containing a keyword.\n"
                 "Results shown in log and saveable to a text file.",
            bg=self.BG2,
            fg=self.FG_DIM,
            font=("Segoe UI", 8),
            justify="left",
        ).pack(anchor="w", pady=(4, 0))

        btn_row = tk.Frame(frame, bg=self.BG2)
        btn_row.pack(fill="x", pady=(self.PAD // 2, 0))

        self.search_btn = tk.Button(
            btn_row,
            text="Search",
            command=self._do_search,
            bg=self.BUTTON,
            fg=self.FG,
            activebackground=self.BUTTON_H,
            activeforeground=self.FG,
            relief="flat",
            padx=12,
            pady=6,
            font=("Segoe UI", 10, "bold"),
            cursor="hand2",
        )
        self.search_btn.pack(side="left", fill="x", expand=True)

        self.cancel_btn = tk.Button(
            btn_row,
            text="Cancel",
            command=self._cancel_search,
            bg=self.ACCENT,
            fg=self.FG_DIM,
            activebackground=self.BG2,
            activeforeground=self.FG,
            relief="flat",
            padx=8,
            pady=6,
            font=("Segoe UI", 9),
            cursor="hand2",
            state="disabled",
        )
        self.cancel_btn.pack(side="right", padx=(self.PAD // 2, 0))

        # Progress bar
        self.search_progress = ttk.Progressbar(
            frame, orient="horizontal", mode="determinate"
        )
        self.search_progress.pack(fill="x", pady=(6, 0))


    # ── Browse callbacks ──────────────────────────────────────────────────────

    def _browse_extract_file(self):
        path = filedialog.askopenfilename(
            title="Select .bundle or .assets file",
            filetypes=[
                ("Unity files", "*.bundle *.assets"),
                ("Bundle files", "*.bundle"),
                ("Assets files", "*.assets"),
                ("All files", "*.*"),
            ],
        )
        if path:
            self.extract_file_var.set(path)


    def _browse_repack_folder(self):
        path = filedialog.askdirectory(title="Select extracted folder to repack")
        if path:
            self.repack_folder_var.set(path)


    def _browse_search_folder(self):
        path = filedialog.askdirectory(
            title="Select folder containing .bundle / .assets files"
        )
        if path:
            self.search_folder_var.set(path)


    # ── Action callbacks ──────────────────────────────────────────────────────

    def _do_extract(self):
        raw = self.extract_file_var.get().strip()
        if not raw:
            messagebox.showwarning("No file",
                                   "Please select a .bundle or .assets file first.")
            return

        src = Path(raw)
        if not src.is_file():
            messagebox.showerror("Not found", f"File not found:\n{src}")
            return

        self._set_busy(True)
        self._log(f"Extracting: {src.name}", "info")

        def run():
            try:
                ok, skip = extract_file(src, self._log)
                self._log(
                    f"Done — {ok} exported, {skip} skipped  ->  "
                    f"{EXTRACT_PREFIX}{src.name}/",
                    "ok",
                )
            except Exception as exc:
                self._log(f"Error: {exc}", "err")
            finally:
                self.after(0, lambda: self._set_busy(False))

        threading.Thread(target=run, daemon=True).start()


    def _do_repack(self):
        raw = self.repack_folder_var.get().strip()
        if not raw:
            messagebox.showwarning("No folder",
                                   "Please select an extracted folder first.")
            return

        src_dir = Path(raw)
        if not src_dir.is_dir():
            messagebox.showerror("Not found", f"Folder not found:\n{src_dir}")
            return

        self._set_busy(True)
        self._log(f"Repacking: {src_dir.name}", "info")

        def run():
            try:
                out = repack_folder(src_dir, self._log)
                self._log(f"Repack complete  ->  {out.name}", "ok")
            except Exception as exc:
                self._log(f"Error: {exc}", "err")
            finally:
                self.after(0, lambda: self._set_busy(False))

        threading.Thread(target=run, daemon=True).start()


    def _do_search(self):
        raw = self.search_folder_var.get().strip()
        if not raw:
            messagebox.showwarning("No folder",
                                   "Please select a folder of .bundle / .assets files.")
            return

        folder = Path(raw)
        if not folder.is_dir():
            messagebox.showerror("Not found", f"Folder not found:\n{folder}")
            return

        kw_raw   = self.search_keywords_var.get()
        keywords = [k.strip() for k in kw_raw.split(",") if k.strip()]
        if not keywords:
            messagebox.showwarning("No keywords",
                                   "Please enter at least one keyword to search for.")
            return

        self._search_results = []
        self._cancel_flag[0] = False
        self._set_busy(True)
        self.cancel_btn.config(state="normal")
        self.search_progress["value"] = 0
        self._save_results_btn.config(state="disabled")
        self._log(f"Starting search in: {folder.name}", "info")

        def progress_cb(current, total):
            pct = int(current / total * 100) if total else 0
            self.after(0, lambda: self.search_progress.config(value=pct))


        def run():
            try:
                results = search_bundles(
                    folder,
                    keywords,
                    self._log,
                    progress_cb=progress_cb,
                    cancel_flag=self._cancel_flag,
                )
                self._search_results = results

                if results:
                    self._log(
                        f"\n{len(results)} match(es) found:", "info"
                    )
                    for m in results:
                        self._log(
                            f"  [{m.bundle}]  {m.obj_type}/{m.obj_name}",
                            "match",
                        )
                        self._log(
                            f"    {m.field_path} = {m.value!r}",
                            "match2",
                        )
                    self.after(0, lambda: self._save_results_btn.config(
                        state="normal"
                    ))
                else:
                    self._log("No matches found.", "warn")

            except Exception as exc:
                self._log(f"Search error: {exc}", "err")
            finally:
                self.after(0, lambda: self._set_busy(False))
                self.after(0, lambda: self.cancel_btn.config(state="disabled"))
                self.after(0, lambda: self.search_progress.config(value=0))

        threading.Thread(target=run, daemon=True).start()


    def _cancel_search(self):
        self._cancel_flag[0] = True
        self.cancel_btn.config(state="disabled")


    def _save_results(self):
        if not self._search_results:
            messagebox.showinfo("Nothing to save", "Run a search first.")
            return

        path = filedialog.asksaveasfilename(
            title="Save search results",
            defaultextension=".txt",
            filetypes=[("Text file", "*.txt"), ("All files", "*.*")],
            initialfile="search_results.txt",
        )
        if not path:
            return

        with open(path, "w", encoding="utf-8") as f:
            f.write(f"Unity Asset Tool — search results\n")
            f.write(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write(f"Matches: {len(self._search_results)}\n")
            f.write("=" * 72 + "\n\n")
            for m in self._search_results:
                f.write(str(m) + "\n\n")

        self._log(f"Results saved to: {Path(path).name}", "ok")


    # ── Log helpers ───────────────────────────────────────────────────────────

    def _log(self, message: str, tag: str = ""):
        def _append():
            self.log_box.config(state="normal")

            t = tag
            if not t:
                if "[ok]" in message:
                    t = "ok"
                elif "[err]" in message:
                    t = "err"
                elif "[warn]" in message:
                    t = "warn"
                elif "[skip]" in message:
                    t = "dim"

            self.log_box.insert("end", message + "\n", t)
            self.log_box.see("end")
            self.log_box.config(state="disabled")

        self.after(0, _append)


    def _clear_log(self):
        self.log_box.config(state="normal")
        self.log_box.delete("1.0", "end")
        self.log_box.config(state="disabled")


    def _set_busy(self, busy: bool):
        state = "disabled" if busy else "normal"
        self.extract_btn.config(state=state)
        self.repack_btn.config(state=state)
        self.search_btn.config(state=state)


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    app = App()
    app.mainloop()