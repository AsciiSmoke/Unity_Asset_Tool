# Unity Asset Tool — User Guide

A desktop tool for extracting, inspecting, and repacking Unity `.bundle` and `.assets` files. Built for game modding workflows.

---

## Getting Started

Double-click **UnityAssetTool.exe** to launch the tool. No installation is required. The tool window is divided into three panels: **Extract**, **Repack**, and **Search Bundles**, with a log area at the bottom that shows progress and results for all operations.

---

## Extracting a File

The Extract panel unpacks a single `.bundle` or `.assets` file into a folder so you can inspect and edit its contents.

1. Click the **…** button next to the File field and select the `.bundle` or `.assets` file you want to extract.
2. Click **Extract**.

The tool will create a new folder in the same location as the source file, named with the prefix `extract__` followed by the original filename — for example:

```
level1.bundle  →  extract__level1.bundle\
```

Inside that folder, extracted objects are organised into subfolders by type:

| Folder | Contents |
|---|---|
| `Texture2D\` | Images saved as `.png` |
| `Sprite\` | Sprite images saved as `.png` |
| `AudioClip\` | Audio saved as `.wav` |
| `TextAsset\` | Text or data files saved as `.txt` or `.bin` |
| `MonoBehaviour\` | Gameplay data saved as `.json` |
| `Material\` | Material definitions saved as `.json` |
| `AnimationClip\` | Animation data saved as `.json` |
| `GameObject\` | Object definitions saved as `.json` |

A `_manifest.json` file is also written into the folder. This is used by the Repack function and should not be deleted or modified.

---

## Editing Files

Once extracted, files can be edited with any appropriate tool:

- **JSON files** (MonoBehaviour, Material, etc.) — open in any text editor such as Notepad, Notepad++, or VS Code. These typically contain gameplay data such as numeric values, flags, and object references.
- **PNG files** — open and edit in any image editor.
- **WAV files** — open and edit in any audio editor.
- **TXT files** — open in any text editor.

Only edit files you intend to change. Unmodified files are ignored during repacking.

---

## Repacking a Folder

The Repack panel packs a previously extracted folder back into its original bundle or assets file.

> **Important:** The original source file (e.g. `level1.bundle`) must still be present in the same location as the `extract__` folder. It is used as the base for repacking.

1. Click the **…** button next to the Folder field and select the `extract__` folder you want to repack.
2. Click **Repack**.

Before writing the new file, the tool automatically backs up the existing original. The backup is named using the original filename with a timestamp appended:

```
level1.bundle  →  level1.bundle.20260530.143022
```

This means every repack leaves the previous version safely preserved. Backups are sorted chronologically by filename, so you can always identify which version came first.

The repacked file is written with the original filename, ready to use as a direct replacement.

> **Note on Sprites:** Sprites are skipped during repacking as UnityPy does not support writing them back directly. The underlying Texture2D image in the same bundle is what holds the actual pixel data and can be edited instead.

---

## Searching Across Multiple Bundles

The Search Bundles panel scans an entire folder of `.bundle` and `.assets` files in memory — without extracting anything to disk — and reports any object fields whose names match your keywords. This is useful for locating gameplay data such as time limits, score values, or size parameters across a large number of files.

1. Click the **…** button next to the Folder field and select the folder containing your bundle files.
2. Enter one or more comma-separated keywords in the Keywords field. The search is case-insensitive. Example:
   ```
   time,limit,score,size
   ```
3. Click **Search**.

A progress bar shows how far through the files the scan has reached. You can click **Cancel** at any time to stop the search early.

### Reading Results

Matches are highlighted in the log in the following format:

```
[somebundle.bundle]  MonoBehaviour/StageData
    m_TimeLimit = 180
```

This tells you:
- Which bundle file the match was found in
- The object type and name within that bundle
- The exact field name and its current value

### Saving Results

Once a search completes, a **Save search results…** button appears at the top of the log. Click it to export all matches to a plain text file you can refer back to when deciding which bundle to extract and edit.

---

## Tips

- Run a broad search first (e.g. `time,limit,count,score,size,speed`) to get an overview of which bundles contain numeric gameplay data, then narrow down to the specific bundle you want to edit.
- After repacking, use your emulator's mod/LayeredFS feature to load the modified bundle alongside the original game rather than replacing files permanently. This makes it easy to toggle your changes on and off.
- If a repack produces no changes (the log says *"No objects were patched"*), check that the filenames inside your edited subfolders exactly match the originals — the tool matches by name.
