#!/usr/bin/env python3
"""
fetch_encoder.py - 3GPP AMR-WB+ Encoder Locator & Setup Helper
Locates or downloads encoder.exe and er-libisomedia.dll required for Playaway audio conversion.
"""

import os
import sys
import shutil
import urllib.request
import zipfile
import io
from pathlib import Path

APP_DIR = Path(__file__).parent.resolve()
TOOLS_DIR = APP_DIR / "tools"

OFFICIAL_3GPP_ZIP_URL = "https://www.3gpp.org/ftp/Specs/archive/26_series/26.304/26304-f00.zip"


def find_encoder():
    """
    Search for encoder executable in APP_DIR, TOOLS_DIR, or PATH.
    Returns tuple (encoder_path, dll_path) or (None, None).
    """
    search_paths = [APP_DIR, TOOLS_DIR]
    
    path_dirs = [Path(p) for p in os.environ.get("PATH", "").split(os.pathsep) if p]
    search_paths.extend(path_dirs)

    encoder_name = "encoder.exe" if sys.platform == "win32" or os.name == "nt" else "encoder"
    alt_encoder_name = "encoder-new"

    found_encoder = None
    found_dll = None

    for p in search_paths:
        if not p.exists():
            continue
        
        exe_path = p / "encoder.exe"
        if not exe_path.exists():
            exe_path = p / encoder_name
        if not exe_path.exists():
            exe_path = p / alt_encoder_name
            
        if exe_path.is_file():
            found_encoder = exe_path
            dll_path = exe_path.parent / "er-libisomedia.dll"
            if dll_path.is_file():
                found_dll = dll_path
            elif (TOOLS_DIR / "er-libisomedia.dll").is_file():
                found_dll = TOOLS_DIR / "er-libisomedia.dll"
            elif (APP_DIR / "er-libisomedia.dll").is_file():
                found_dll = APP_DIR / "er-libisomedia.dll"
            break

    return found_encoder, found_dll


def download_and_extract_3gpp_encoder(target_dir):
    """
    Download official 3GPP TS 26.304 specification zip and extract precompiled encoder.exe & er-libisomedia.dll.
    """
    target_dir.mkdir(parents=True, exist_ok=True)
    exe_target = target_dir / "encoder.exe"
    dll_target = target_dir / "er-libisomedia.dll"

    if exe_target.exists() and dll_target.exists():
        return exe_target, dll_target

    print(f"Downloading official 3GPP reference archive from {OFFICIAL_3GPP_ZIP_URL}...")
    req = urllib.request.Request(
        OFFICIAL_3GPP_ZIP_URL,
        headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
    )

    with urllib.request.urlopen(req) as resp:
        outer_zip_data = resp.read()

    print("Extracting 3GPP AMR-WB+ encoder binaries...")
    with zipfile.ZipFile(io.BytesIO(outer_zip_data)) as outer_zip:
        inner_zip_name = [n for n in outer_zip.namelist() if n.endswith(".zip")][0]
        inner_zip_data = outer_zip.read(inner_zip_name)

    with zipfile.ZipFile(io.BytesIO(inner_zip_data)) as inner_zip:
        for name in inner_zip.namelist():
            if name.endswith("encoder.exe"):
                with open(exe_target, "wb") as f:
                    f.write(inner_zip.read(name))
            elif name.endswith("er-libisomedia.dll"):
                with open(dll_target, "wb") as f:
                    f.write(inner_zip.read(name))

    if exe_target.exists() and dll_target.exists():
        print(f"Successfully installed 3GPP encoder to {target_dir}")
        return exe_target, dll_target
    else:
        raise RuntimeError("Failed to extract encoder.exe and er-libisomedia.dll from 3GPP archive.")


def setup_encoder(force_redownload=False):
    """
    Ensure the 3GPP encoder is present. Downloads binaries if missing.
    Returns (encoder_path, dll_path).
    """
    TOOLS_DIR.mkdir(parents=True, exist_ok=True)
    enc, dll = find_encoder()

    if enc and dll and not force_redownload:
        print(f"Found existing 3GPP encoder: {enc}")
        return enc, dll

    print("\n=== Playaway 3GPP AMR-WB+ Encoder Downloader ===")
    try:
        return download_and_extract_3gpp_encoder(TOOLS_DIR)
    except Exception as e:
        print(f"\n[!] Automatic download failed: {e}")
        print(f"Please manually place 'encoder.exe' and 'er-libisomedia.dll' into:\n    {TOOLS_DIR}")
        return None, None



if __name__ == "__main__":
    enc, dll = setup_encoder()
    if enc and dll:
        print(f"\nSUCCESS: Encoder ready at {enc}")
    else:
        print("\nERROR: Encoder setup incomplete.")
