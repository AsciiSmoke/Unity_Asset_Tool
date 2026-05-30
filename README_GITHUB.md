# Unity Asset Tool

A Python desktop application for extracting, editing, and repacking Unity `.bundle` and `.assets` files. Built for game modding workflows, with a bulk search feature for locating specific fields across large numbers of bundle files without extracting them first.

---

## Features

- Extract `.bundle` and `.assets` files into organised folders by asset type
- Repack extracted folders back into their original file format, with automatic timestamped backups
- Search across an entire folder of bundles in memory for field names matching keywords — no extraction required
- Save search results to a text file
- Cancellable search with progress bar

---

## Requirements

- **Python 3.10 or newer** — [python.org/downloads](https://www.python.org/downloads/)
- **UnityPy** — Unity asset reading and writing library
- **Pillow** — Image handling (used when repacking textures)
- **PyInstaller** — Required only if you want to build the launcher executable

---

## Installation

### 1. Install Python

Download and install Python from [python.org](https://www.python.org/downloads/). During installation, make sure to check **"Add Python to PATH"**.

### 2. Install dependencies

Open a terminal or PowerShell window and run:

```
pip install UnityPy Pillow
```

To also install PyInstaller (needed to build the launcher exe):

```
pip install pyinstaller
```

---

## Running the Tool

To launch the tool directly from a terminal or PowerShell window, navigate to the folder containing the script and run:

```
python unity_asset_tool.py
```

For example, if the script is in `C:\Tools\UnityAssetTool`:

```
cd C:\Tools\UnityAssetTool
python unity_asset_tool.py
```

---

## Files

| File | Description |
|---|---|
| `unity_asset_tool.py` | The main application. Edit this file to make changes to the tool. |
| `launcher.py` | A small launcher script intended to be compiled into an exe. Finds the local Python installation and runs `unity_asset_tool.py` from the same folder. |

---

## Building the Launcher Executable

The launcher allows the tool to be run by double-clicking an `.exe` without opening a terminal, while keeping `unity_asset_tool.py` as a separate editable file. This means you can update the tool's behaviour by editing the `.py` file without needing to rebuild the executable.

### How the launcher works

`launcher.py` is a minimal script that:

1. Resolves its own location on disk using `sys.argv[0]`
2. Looks for `unity_asset_tool.py` in the same folder
3. Locates the system's `python.exe` via `PATH` or the Windows registry
4. Launches `unity_asset_tool.py` using that Python, with no console window

### Build steps

From the folder containing `launcher.py`, run:

```
python -m PyInstaller --onefile --windowed launcher.py
```

The compiled executable will be created at `dist\launcher.exe`. Rename it to whatever you prefer (e.g. `UnityAssetTool.exe`) and place it in the same folder as `unity_asset_tool.py`.

After building, the `build\` folder, `dist\` folder, and `launcher.spec` file can be deleted — only the `.exe` needs to be kept.

### Folder structure after building

```
UnityAssetTool\
  UnityAssetTool.exe    ← compiled launcher (rename from dist\launcher.exe)
  unity_asset_tool.py   ← main application (edit this to update the tool)
```

### Rebuilding

If you change `launcher.py` itself (not `unity_asset_tool.py`), delete the `build\`, `dist\` folders and `launcher.spec`, then run the PyInstaller command again.

Changes to `unity_asset_tool.py` do **not** require a rebuild — the exe will always pick up the latest version of the script at launch.

---

## Notes

- Repacking requires the original source file to be present alongside the `extract__` folder — it is used as the base into which modified objects are patched.
- Sprites are skipped during repacking as UnityPy does not support writing them back. The Texture2D objects in the same bundle hold the actual image data and are editable.
- The tool reads bundle files into memory before repacking to avoid Windows file locking issues when renaming the original for backup.
- The `CREATE_NO_WINDOW` flag is passed to `subprocess.run` in the launcher to prevent a console window from appearing when the exe starts.
