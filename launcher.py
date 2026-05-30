"""
Launcher for Unity Asset Tool.
Compile this with PyInstaller — keep unity_asset_tool.py in the same folder as the exe.
"""

import sys
import os
import shutil
import subprocess
import tkinter as tk
from tkinter import messagebox


def find_python() -> str | None:
    """
    Locate the real python.exe on this machine.
    PyInstaller overwrites sys.executable with the bundle path, so we have
    to find Python independently via PATH or the Windows registry.
    """
    # Try PATH first (works if Python is on the user's PATH)
    found = shutil.which("python")
    if found:
        return found

    # Fall back to the Windows registry
    try:
        import winreg
        for root_key in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
            for sub in (
                r"SOFTWARE\Python\PythonCore",
                r"SOFTWARE\WOW6432Node\Python\PythonCore",
            ):
                try:
                    with winreg.OpenKey(root_key, sub) as core:
                        i = 0
                        while True:
                            try:
                                version = winreg.EnumKey(core, i)
                                install_path_key = rf"{sub}\{version}\InstallPath"
                                with winreg.OpenKey(root_key, install_path_key) as ip:
                                    path, _ = winreg.QueryValueEx(ip, "ExecutablePath")
                                    if os.path.isfile(path):
                                        return path
                                i += 1
                            except OSError:
                                break
                except OSError:
                    continue
    except Exception:
        pass

    return None


def main():
    exe_dir = os.path.dirname(os.path.abspath(sys.argv[0]))
    script  = os.path.join(exe_dir, "unity_asset_tool.py")

    root = tk.Tk()
    root.withdraw()

    if not os.path.exists(script):
        messagebox.showerror(
            "Script not found",
            f"Could not find unity_asset_tool.py next to this executable.\n\n"
            f"Expected it at:\n{script}"
        )
        sys.exit(1)

    python = find_python()
    if not python:
        messagebox.showerror(
            "Python not found",
            "Could not locate a Python installation on this machine.\n\n"
            "Please ensure Python is installed and added to your PATH."
        )
        sys.exit(1)

    CREATE_NO_WINDOW = 0x08000000
    subprocess.run([python, script], creationflags=CREATE_NO_WINDOW)


main()
