#!/usr/bin/env python3
"""
build_plugin.py - Calibre Plugin Bundler & Installer
Packages all plugin scripts and shared core files into a ready-to-install 'Calibre_Playaway_Flasher.zip'.
"""

import os
import sys
import zipfile
import subprocess
import shutil
import struct
import zlib
from pathlib import Path

ROOT_DIR = Path(__file__).parent.parent.resolve()
PLUGIN_DIR = ROOT_DIR / "calibre_plugin"
DIST_DIR = ROOT_DIR / "dist"
OUTPUT_ZIP = DIST_DIR / "Calibre_Playaway_Flasher.zip"


def create_default_icon(icon_path):
    """Generate a clean 32x32 RGBA PNG icon if one doesn't exist."""
    icon_path.parent.mkdir(parents=True, exist_ok=True)
    if icon_path.exists():
        return

    # Generate a simple 32x32 PNG with a golden lightning bolt & dark blue badge
    width = 32
    height = 32
    raw_data = bytearray()

    for y in range(height):
        raw_data.append(0)  # Filter byte (None)
        for x in range(width):
            # Calculate distance from center for circular badge
            dx = x - 16
            dy = y - 16
            dist_sq = dx * dx + dy * dy

            # Lightning bolt coordinates
            is_bolt = False
            # Upper segment: from (17, 4) down-left to (12, 16)
            if 4 <= y <= 16:
                slope_x = 18 - (y - 4) * 0.5
                if abs(x - slope_x) <= 2:
                    is_bolt = True
            # Horizontal jog: around y=15, 16
            if y in (15, 16) and 10 <= x <= 22:
                is_bolt = True
            # Lower segment: from (20, 16) down-left to (13, 28)
            if 16 <= y <= 28:
                slope_x = 20 - (y - 16) * 0.6
                if abs(x - slope_x) <= 2:
                    is_bolt = True

            if is_bolt:
                # Golden yellow bolt
                raw_data.extend([0xFA, 0xB3, 0x87, 0xFF])
            elif dist_sq <= 14 * 14:
                # Dark cyan / slate badge background
                raw_data.extend([0x1E, 0x1E, 0x2E, 0xFF])
            else:
                # Transparent outside circle
                raw_data.extend([0, 0, 0, 0])

    # Construct PNG binary chunks
    png_signature = b"\x89PNG\r\n\x1a\n"
    ihdr_data = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    ihdr_crc = zlib.crc32(b"IHDR" + ihdr_data)
    ihdr_chunk = struct.pack(">I", 13) + b"IHDR" + ihdr_data + struct.pack(">I", ihdr_crc)

    compressed_idat = zlib.compress(bytes(raw_data), level=9)
    idat_crc = zlib.crc32(b"IDAT" + compressed_idat)
    idat_chunk = struct.pack(">I", len(compressed_idat)) + b"IDAT" + compressed_idat + struct.pack(">I", idat_crc)

    iend_crc = zlib.crc32(b"IEND")
    iend_chunk = struct.pack(">I", 0) + b"IEND" + struct.pack(">I", iend_crc)

    with open(icon_path, "wb") as f:
        f.write(png_signature + ihdr_chunk + idat_chunk + iend_chunk)


def build_plugin_zip():
    """Package Calibre plugin files into Calibre_Playaway_Flasher.zip."""
    DIST_DIR.mkdir(parents=True, exist_ok=True)
    icon_path = PLUGIN_DIR / "images" / "icon.png"
    create_default_icon(icon_path)

    print("Building Calibre Plugin: Calibre_Playaway_Flasher.zip...")
    
    files_to_pack = [
        (PLUGIN_DIR / "__init__.py", "__init__.py"),
        (PLUGIN_DIR / "action.py", "action.py"),
        (PLUGIN_DIR / "dialog.py", "dialog.py"),
        (PLUGIN_DIR / "core_bridge.py", "core_bridge.py"),
        (ROOT_DIR / "playaway_core.py", "playaway_core.py"),
        (ROOT_DIR / "fetch_encoder.py", "fetch_encoder.py"),
        (icon_path, "images/icon.png")
    ]

    with zipfile.ZipFile(OUTPUT_ZIP, "w", zipfile.ZIP_DEFLATED) as zf:
        # Namespace identifier for Calibre dynamic plugin importer
        zf.writestr("plugin-import-name.txt", "playaway_flasher\n")
        zf.writestr("plugin-import-name-playaway_flasher.txt", "playaway_flasher\n")

        for src, arcname in files_to_pack:
            if not src.exists():
                print(f"[!] Warning: Missing source file: {src}")
                continue
            print(f"  + Added: {arcname}")
            zf.write(src, arcname)

    print(f"\n[+] SUCCESS: Plugin built successfully!")
    print(f"    Package location: {OUTPUT_ZIP.resolve()}")
    print("\nHow to Install in Calibre:")
    print("  1. Open Calibre")
    print("  2. Go to Preferences -> Plugins -> 'Load plugin from file'")
    print(f"  3. Select '{OUTPUT_ZIP.name}'")
    print("  4. Restart Calibre - 'Send to Playaway' will appear on your toolbar!\n")


def install_plugin():
    """Automatically install the plugin into Calibre using calibre-customize CLI if available."""
    build_plugin_zip()

    calibre_cmd = shutil.which("calibre-customize")
    if not calibre_cmd and sys.platform == "win32":
        for default_p in [
            Path("C:/Program Files/Calibre2/calibre-customize.exe"),
            Path("C:/Program Files (x86)/Calibre2/calibre-customize.exe")
        ]:
            if default_p.exists():
                calibre_cmd = str(default_p)
                break

    if calibre_cmd:
        print(f"Found Calibre CLI at: {calibre_cmd}")
        print("Installing plugin into local Calibre installation...")
        res = subprocess.run([calibre_cmd, "-a", str(OUTPUT_ZIP)], capture_output=True, text=True)
        if res.returncode == 0:
            print("[+] Successfully installed into Calibre! Restart Calibre to use.")
        else:
            print(f"[!] Calibre installation output:\n{res.stderr or res.stdout}")
    else:
        print("[i] 'calibre-customize' not found on PATH. Please load the zip file manually inside Calibre Preferences -> Plugins.")


if __name__ == "__main__":
    if "--install" in sys.argv or "-i" in sys.argv:
        install_plugin()
    else:
        build_plugin_zip()
