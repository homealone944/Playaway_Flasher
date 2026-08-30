#!/usr/bin/env python3
"""
fetch_encoder.py - 3GPP AMR-WB+ Encoder Locator & Setup Helper
Locates or downloads encoder.exe and er-libisomedia.dll required for Playaway audio conversion.
"""

import os
import sys
import urllib.request
import zipfile
import io
from pathlib import Path

def get_tools_dir():
    """Return a safe, writable directory for encoder binaries that works in Calibre and standalone."""
    try:
        p = Path(__file__).parent.resolve()
        # If running from normal folder outside of a zip
        if p.is_dir() and not str(p).lower().endswith(".zip"):
            return p / "tools"
    except Exception:
        pass

    app_data = os.environ.get("APPDATA")
    if app_data:
        return Path(app_data) / "calibre" / "plugins" / "playaway_tools"
    return Path.home() / ".playaway" / "tools"


def extract_bundled_tools(target_dir):
    """Extract encoder.exe and er-libisomedia.dll if running inside Calibre plugin zip."""
    exe_target = target_dir / "encoder.exe"
    dll_target = target_dir / "er-libisomedia.dll"
    if exe_target.is_file() and dll_target.is_file():
        return exe_target, dll_target

    # Search for containing zip file
    try:
        p = Path(__file__).resolve()
        for parent_candidate in [p, p.parent, p.parent.parent]:
            candidate_str = str(parent_candidate)
            if ".zip" in candidate_str.lower():
                # Extract zip path up to .zip
                idx = candidate_str.lower().find(".zip") + 4
                actual_zip = Path(candidate_str[:idx])
                if actual_zip.is_file() and zipfile.is_zipfile(actual_zip):
                    target_dir.mkdir(parents=True, exist_ok=True)
                    with zipfile.ZipFile(actual_zip, "r") as zf:
                        for name in zf.namelist():
                            if name.endswith("encoder.exe"):
                                with open(exe_target, "wb") as f:
                                    f.write(zf.read(name))
                            elif name.endswith("er-libisomedia.dll"):
                                with open(dll_target, "wb") as f:
                                    f.write(zf.read(name))
                    if exe_target.is_file() and dll_target.is_file():
                        return exe_target, dll_target
    except Exception:
        pass

    return None, None


def find_encoder():
    """
    Search for encoder executable in safe tools directory, APP_DIR, or PATH.
    Returns tuple (encoder_path, dll_path) or (None, None).
    """
    tools_dir = get_tools_dir()
    
    # Try extracting bundled tools if available
    extracted_exe, extracted_dll = extract_bundled_tools(tools_dir)
    if extracted_exe and extracted_dll:
        return extracted_exe, extracted_dll

    search_paths = [tools_dir]
    
    try:
        curr_dir = Path(__file__).parent.resolve()
        if curr_dir.is_dir() and not str(curr_dir).lower().endswith(".zip"):
            search_paths.append(curr_dir)
            search_paths.append(curr_dir / "tools")
    except Exception:
        pass

    # Include user's project workspace directory
    search_paths.append(Path(r"C:\Users\risin\Documents\In_Progress\Coding\Playaway_Installer\tools"))
    search_paths.append(Path(r"C:\Users\risin\Documents\In_Progress\Coding\Playaway_Installer"))

    path_dirs = [Path(p) for p in os.environ.get("PATH", "").split(os.pathsep) if p]
    search_paths.extend(path_dirs)

    encoder_name = "encoder.exe" if sys.platform == "win32" or os.name == "nt" else "encoder"
    alt_encoder_name = "encoder-new"

    found_encoder = None
    found_dll = None

    for p in search_paths:
        try:
            if not p.exists():
                continue
        except Exception:
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
            elif (tools_dir / "er-libisomedia.dll").is_file():
                found_dll = tools_dir / "er-libisomedia.dll"
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
    enc, dll = find_encoder()

    if enc and dll and not force_redownload:
        return enc, dll

    tools_dir = get_tools_dir()
    tools_dir.mkdir(parents=True, exist_ok=True)
    return download_and_extract_3gpp_encoder(tools_dir)



if __name__ == "__main__":
    enc, dll = setup_encoder()
    if enc and dll:
        print(f"\nSUCCESS: Encoder ready at {enc}")
    else:
        print("\nERROR: Encoder setup incomplete.")
