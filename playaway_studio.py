#!/usr/bin/env python3
"""
playaway_studio.py - Command Line Interface (CLI) & Main Entry Point
Supports both CLI subcommands (for Linux/terminal users) and GUI window mode (for Windows/basic users).
"""

import sys
import os
import argparse
import tempfile
from pathlib import Path

from playaway_core import (
    detect_playaway_drives,
    inspect_audio_source,
    plan_chapters,
    convert_segment_to_awb,
    convert_all_segments_parallel,
    generate_patweaks_content,
    flash_playaway,
    backup_playaway_drive,
    estimate_bitrate_size,
    load_config
)
from fetch_encoder import setup_encoder, find_encoder


def log_cli(msg):
    print(msg)


def cmd_detect(args):
    """CLI handler to list connected Playaway USB drives."""
    print("Scanning for connected Playaway USB drives...\n")
    drives = detect_playaway_drives()
    
    if not drives:
        print("No removable USB drives found.")
        return

    print(f"{'Path':<8} {'Label':<18} {'Filesystem':<12} {'Free MB':<10} {'Total MB':<10} {'Playaway?'}")
    print("-" * 70)
    for d in drives:
        is_pa = "Yes ✓" if d["is_playaway"] else "No"
        print(f"{d['path']:<8} {d['label']:<18} {d['fs']:<12} {d['free_mb']:<10} {d['total_mb']:<10} {is_pa}")
    print("-" * 70)


def cmd_backup(args):
    """CLI handler to backup an existing Playaway drive."""
    drive_path = args.drive
    backup_dir = Path(args.output)

    print(f"Backing up Playaway drive {drive_path} to {backup_dir}...\n")
    try:
        backup_playaway_drive(drive_path, backup_dir, log_callback=log_cli)
        print(f"\n[+] Backup completed successfully! Saved to: {backup_dir.resolve()}")
    except Exception as e:
        print(f"\n[!] Backup error: {e}")
        sys.exit(1)


def cmd_convert(args):
    """CLI handler to convert audiobook to AMR-WB+ files without flashing."""
    cfg = load_config(getattr(args, "config", None))
    input_path = args.input
    output_dir = Path(args.output)
    
    split_mode = args.split_mode if args.split_mode != "duration" else cfg.get("split_mode", "duration")
    split_mins = args.split_mins if args.split_mins != 15 else cfg.get("split_mins", 15)
    bitrate = args.bitrate if args.bitrate != 10 else cfg.get("bitrate_kbps", 10)
    speed = args.speed if args.speed != 1.0 else cfg.get("playback_speed", 1.0)
    subchapters = args.subchapters or cfg.get("subchapter_mode", False)
    preserve_pitch = cfg.get("preserve_pitch", True)

    enc_exe, _ = setup_encoder()
    if not enc_exe:
        print("[!] Error: 3GPP encoder missing. Cannot convert.")
        sys.exit(1)

    print(f"Analyzing input audio: {input_path}...")
    info = inspect_audio_source(input_path)

    print(f"Book Title: {info['title']}")
    print(f"Total Duration: {info['total_duration_formatted']}")

    segments = plan_chapters(
        input_path=input_path,
        split_mode=split_mode,
        split_mins=split_mins,
        title=args.title or info["title"],
        subchapter_mode=subchapters
    )

    print(f"\nPlanned Tracks ({len(segments)}):")
    for s in segments[:5]:
        print(f"  - {s['out_name']} ({round(s['duration']/60, 1)} mins)")
    if len(segments) > 5:
        print(f"  ... and {len(segments) - 5} more tracks.")

    est_mb = estimate_bitrate_size(info["total_duration_sec"], bitrate, speed=speed)
    print(f"\nEstimated Output Size: ~{est_mb} MB (at {bitrate} kbps, {speed}x speed)")

    print("\nStarting AMR-WB+ audio conversion in parallel...")
    convert_all_segments_parallel(
        segments=segments,
        output_dir=output_dir,
        bitrate_kbps=bitrate,
        speed=speed,
        preserve_pitch=preserve_pitch,
        encoder_exe=enc_exe,
        log_callback=log_cli
    )

    # Write PATWEAKS.DAT
    pat_file = output_dir / "PATWEAKS.DAT"
    pat_content = generate_patweaks_content(len(segments), subchapters)
    with open(pat_file, "wb") as f:
        f.write(pat_content.encode("ascii"))

    print(f"\n[+] Conversion finished! Files written to: {output_dir.resolve()}")


def cmd_flash(args):
    """CLI handler to convert audiobook and flash directly to target Playaway drive."""
    cfg = load_config(getattr(args, "config", None))
    drive_path = args.drive
    input_path = args.input
    
    split_mode = args.split_mode if args.split_mode != "duration" else cfg.get("split_mode", "duration")
    split_mins = args.split_mins if args.split_mins != 15 else cfg.get("split_mins", 15)
    bitrate = args.bitrate if args.bitrate != 10 else cfg.get("bitrate_kbps", 10)
    speed = args.speed if args.speed != 1.0 else cfg.get("playback_speed", 1.0)
    subchapters = args.subchapters or cfg.get("subchapter_mode", False)
    preserve_pitch = cfg.get("preserve_pitch", True)

    if not args.yes:
        confirm = input(f"WARNING: All existing files on drive {drive_path} will be ERASED. Continue? [y/N]: ")
        if confirm.lower() not in ("y", "yes"):
            print("Aborted.")
            return

    enc_exe, _ = setup_encoder()
    if not enc_exe:
        print("[!] Error: 3GPP encoder missing. Cannot convert.")
        sys.exit(1)

    info = inspect_audio_source(input_path)
    segments = plan_chapters(
        input_path=input_path,
        split_mode=split_mode,
        split_mins=split_mins,
        title=args.title or info["title"],
        subchapter_mode=subchapters
    )

    with tempfile.TemporaryDirectory(prefix="playaway_cli_staging_") as temp_dir:
        print(f"\nConverting {len(segments)} tracks to temporary staging in parallel (Speed: {speed}x)...")
        convert_all_segments_parallel(
            segments=segments,
            output_dir=temp_dir,
            bitrate_kbps=bitrate,
            speed=speed,
            preserve_pitch=preserve_pitch,
            encoder_exe=enc_exe,
            log_callback=log_cli
        )

        print(f"\nFlashing to drive {drive_path}...")
        flash_playaway(
            drive_path=drive_path,
            awb_dir=temp_dir,
            track_count=len(segments),
            subchapter_mode=subchapters,
            log_callback=log_cli
        )

    print(f"\n[+] Flash completed successfully! Safe to disconnect drive {drive_path}.")


def cmd_fetch_encoder(args):
    """CLI handler to fetch 3GPP encoder binaries."""
    setup_encoder(force_redownload=True)


def main():
    # If run without arguments, launch GUI mode!
    if len(sys.argv) == 1:
        from playaway_gui import main as launch_gui
        launch_gui()
        return

    parser = argparse.ArgumentParser(description="Playaway Audiobook Studio & Flasher CLI")
    parser.add_argument("--gui", action="store_true", help="Launch Graphical User Interface window")

    subparsers = parser.add_subparsers(dest="command", help="Available subcommands")

    # Subcommand: detect
    p_detect = subparsers.add_parser("detect", help="Scan for connected Playaway USB drives")
    p_detect.set_defaults(func=cmd_detect)

    # Subcommand: backup
    p_backup = subparsers.add_parser("backup", help="Backup files from connected Playaway drive to local folder")
    p_backup.add_argument("-d", "--drive", required=True, help="Target Playaway USB drive letter or path (e.g. E:\\)")
    p_backup.add_argument("-o", "--output", required=True, help="Output directory to save backed-up files")
    p_backup.set_defaults(func=cmd_backup)

    # Subcommand: convert
    p_conv = subparsers.add_parser("convert", help="Convert audiobook to .awb and PATWEAKS.DAT in output folder")
    p_conv.add_argument("-i", "--input", required=True, help="Input audiobook file (.m4b, .mp3, etc.) or folder")
    p_conv.add_argument("-o", "--output", required=True, help="Output folder to store .awb tracks and PATWEAKS.DAT")
    p_conv.add_argument("-c", "--config", help="Path to custom JSON settings file (default: playaway_config.json)")
    p_conv.add_argument("--title", help="Custom audiobook title")
    p_conv.add_argument("--split-mode", choices=["duration", "chapters", "none"], default="duration", help="Chapter split method")
    p_conv.add_argument("--split-mins", type=int, default=15, help="Minutes per track if split-mode=duration")
    p_conv.add_argument("--bitrate", type=int, default=10, help="AMR-WB+ bitrate in kbps (10 to 36)")
    p_conv.add_argument("--speed", type=float, default=1.0, help="Playback speed factor (e.g. 1.25 for 1.25x speed)")
    p_conv.add_argument("--subchapters", action="store_true", help="Enable subchapter mode (AF* header)")
    p_conv.set_defaults(func=cmd_convert)

    # Subcommand: flash
    p_flash = subparsers.add_parser("flash", help="Convert audiobook and flash directly to Playaway drive")
    p_flash.add_argument("-i", "--input", required=True, help="Input audiobook file (.m4b, .mp3, etc.) or folder")
    p_flash.add_argument("-d", "--drive", required=True, help="Target Playaway USB drive letter or path (e.g. E:\\ or /media/playaway)")
    p_flash.add_argument("-c", "--config", help="Path to custom JSON settings file (default: playaway_config.json)")
    p_flash.add_argument("--title", help="Custom audiobook title")
    p_flash.add_argument("--split-mode", choices=["duration", "chapters", "none"], default="duration", help="Chapter split method")
    p_flash.add_argument("--split-mins", type=int, default=15, help="Minutes per track if split-mode=duration")
    p_flash.add_argument("--bitrate", type=int, default=10, help="AMR-WB+ bitrate in kbps (10 to 36)")
    p_flash.add_argument("--speed", type=float, default=1.0, help="Playback speed factor (e.g. 1.25 for 1.25x speed)")
    p_flash.add_argument("--subchapters", action="store_true", help="Enable subchapter mode (AF* header)")
    p_flash.add_argument("-y", "--yes", action="store_true", help="Skip confirmation prompt before wiping drive")
    p_flash.set_defaults(func=cmd_flash)

    # Subcommand: fetch-encoder
    p_enc = subparsers.add_parser("fetch-encoder", help="Download 3GPP AMR-WB+ encoder binaries")
    p_enc.set_defaults(func=cmd_fetch_encoder)

    args = parser.parse_args()

    if args.gui:
        from playaway_gui import main as launch_gui
        launch_gui()
    elif hasattr(args, "func"):
        args.func(args)
    else:
        parser.print_help()
        parser.print_help()


if __name__ == "__main__":
    main()
