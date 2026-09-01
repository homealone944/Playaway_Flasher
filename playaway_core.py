#!/usr/bin/env python3
"""
playaway_core.py - Core Engine for Playaway Audiobook Installer & Flasher
Handles audio analysis, chapter splitting, AMR-WB+ conversion, PATWEAKS.DAT generation,
drive detection, and Playaway flash/wipe operations.
"""

import os
import sys
import shutil
import json
import subprocess
import tempfile
import time
import re
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

try:
    from calibre_plugins.playaway_flasher.fetch_encoder import setup_encoder
except (ImportError, ValueError):
    try:
        from .fetch_encoder import setup_encoder
    except (ImportError, ValueError):
        from fetch_encoder import setup_encoder


def run_command(cmd, log_callback=None):
    """Run a shell command and capture stdout/stderr."""
    if log_callback:
        log_callback(f"Executing: {' '.join(str(c) for c in cmd)}")
    
    # On Windows, hide command prompt window for GUI calls
    startupinfo = None
    if sys.platform == "win32":
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW

    process = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        universal_newlines=True,
        startupinfo=startupinfo
    )
    stdout, stderr = process.communicate()
    return process.returncode, stdout, stderr


# ==============================================================================
# Drive Detection & Safety Management
# ==============================================================================

def is_system_drive(drive_path):
    """Check if drive is the OS system drive (e.g. C:\\ on Windows or / on Linux)."""
    dp = str(drive_path).upper()
    sys_drive = os.getenv("SystemDrive", "C:").upper()
    if dp.startswith("C:") or dp.startswith(sys_drive):
        return True
    if sys.platform != "win32" and dp in ("/", "/BOOT", "/SYSTEM"):
        return True
    return False


def detect_playaway_drives(allow_large_drives=False):
    """
    Detect removable drives formatted as FAT/FAT32 or containing Playaway structures.
    Strictly filters out C: system drive and drives > 2048 MB (2 GB) unless override requested.
    """
    drives = []

    if sys.platform == "win32":
        import ctypes
        bitmask = ctypes.windll.kernel32.GetLogicalDrives()
        for letter_idx in range(26):
            if bitmask & (1 << letter_idx):
                drive_letter = f"{chr(65 + letter_idx)}:\\"
                
                # SAFETY CHECK 1: Never expose C: or OS system drive
                if is_system_drive(drive_letter):
                    continue

                drive_type = ctypes.windll.kernel32.GetDriveTypeW(drive_letter)
                # Drive types: 2 = REMOVABLE, 3 = FIXED
                if drive_type in (2, 3):
                    try:
                        usage = shutil.disk_usage(drive_letter)
                        total_mb = round(usage.total / (1024 * 1024), 1)
                        free_mb = round(usage.free / (1024 * 1024), 1)

                        # SAFETY CHECK 2: Real Playaway devices are <= 2GB (128MB, 256MB, 512MB, 1GB).
                        # Block large internal hard drives, external HDDs/SSDs (> 2048 MB) from accidental wiping.
                        is_safe_size = total_mb <= 2048.0 or allow_large_drives

                        # Check volume label & file indicators
                        vol_name_buf = ctypes.create_unicode_buffer(261)
                        fs_name_buf = ctypes.create_unicode_buffer(261)
                        ctypes.windll.kernel32.GetVolumeInformationW(
                            drive_letter, vol_name_buf, 261, None, None, None, fs_name_buf, 261
                        )
                        vol_name = vol_name_buf.value
                        fs_name = fs_name_buf.value

                        # Identify if Playaway indicators exist
                        has_patweaks = (Path(drive_letter) / "PATWEAKS.DAT").exists()
                        has_awb = any(Path(drive_letter).glob("*.awb"))
                        is_likely_playaway = has_patweaks or has_awb or ("PLAYAWAY" in vol_name.upper()) or (total_mb <= 600 and "FAT" in fs_name.upper())

                        if is_safe_size:
                            drives.append({
                                "path": drive_letter,
                                "label": vol_name if vol_name else "Removable Disk",
                                "fs": fs_name,
                                "total_mb": total_mb,
                                "free_mb": free_mb,
                                "is_playaway": is_likely_playaway,
                                "has_patweaks": has_patweaks,
                                "is_removable": drive_type == 2
                            })
                    except Exception:
                        pass

    else:
        # Linux / macOS drive scanning
        search_dirs = [Path("/media"), Path("/run/media"), Path(f"/run/media/{os.environ.get('USER', '')}"), Path("/Volumes")]
        for sdir in search_dirs:
            if sdir.exists():
                for p in sdir.rglob("*"):
                    if is_system_drive(p):
                        continue
                    if p.is_mount() or (p.is_dir() and (p / "PATWEAKS.DAT").exists()):
                        try:
                            usage = shutil.disk_usage(p)
                            total_mb = round(usage.total / (1024 * 1024), 1)
                            free_mb = round(usage.free / (1024 * 1024), 1)

                            if total_mb <= 2048.0 or allow_large_drives:
                                has_patweaks = (p / "PATWEAKS.DAT").exists()
                                has_awb = any(p.glob("*.awb"))

                                drives.append({
                                    "path": str(p),
                                    "label": p.name,
                                    "fs": "FAT/FAT32",
                                    "total_mb": total_mb,
                                    "free_mb": free_mb,
                                    "is_playaway": has_patweaks or has_awb or (total_mb <= 600),
                                    "has_patweaks": has_patweaks,
                                    "is_removable": True
                                })
                        except Exception:
                            pass

    return drives


def generate_copy_instructions(book_title, track_count):
    """
    Generate text for README_HOW_TO_COPY.txt when exporting to a local folder.
    """
    return f"""===================================================================
PLAYAWAY AUDIOBOOK MANUAL COPY INSTRUCTIONS
===================================================================
Book Title : {book_title}
Total Tracks: {track_count}

To manually load this audiobook onto your Playaway player:

1. Connect your Playaway device to your computer via USB.
2. Open the Playaway drive in File Explorer (e.g. E:\\).
3. ERASE / DELETE ALL existing files on the Playaway drive (including
   old .awb audio tracks, PATWEAKS.DAT, CMI_CRC.DAT, and hidden OS files).
4. COPY ALL files from inside this folder directly into the ROOT 
   directory of your Playaway drive:
   - All {track_count} .awb track files
   - PATWEAKS.DAT
5. CRITICAL: DO NOT create a subfolder on the Playaway player! 
   All .awb files and PATWEAKS.DAT must sit directly in the top-level 
   root directory (e.g., E:\\PATWEAKS.DAT and E:\\0001 {book_title} 0000.awb).
6. Safely Eject / Sync the USB drive before unplugging.
===================================================================
"""


def sync_drive(drive_path):
    """Ensure all file buffers are committed to disk before unplugging."""
    if sys.platform == "win32":
        try:
            import ctypes
            drive_letter = drive_path.rstrip("\\/")
            if len(drive_letter) == 2 and drive_letter[1] == ":":
                handle = ctypes.windll.kernel32.CreateFileW(
                    f"\\\\.\\{drive_letter}",
                    0x80000000 | 0x40000000, # GENERIC_READ | GENERIC_WRITE
                    0x00000001 | 0x00000002, # FILE_SHARE_READ | FILE_SHARE_WRITE
                    None,
                    3, # OPEN_EXISTING
                    0,
                    None
                )
                if handle != -1:
                    ctypes.windll.kernel32.FlushFileBuffers(handle)
                    ctypes.windll.kernel32.CloseHandle(handle)
        except Exception:
            pass
    else:
        try:
            os.sync()
        except Exception:
            pass


# ==============================================================================
# Audio Probe & Analysis Engine
# ==============================================================================

def inspect_audio_source(input_path):
    """
    Inspect input audio file or folder using ffprobe.
    Returns dict with duration_sec, channels, chapters, and format details.
    """
    p = Path(input_path)
    if not p.exists():
        raise FileNotFoundError(f"Input path does not exist: {input_path}")

    files = []
    if p.is_dir():
        supported_exts = {".mp3", ".m4b", ".m4a", ".wav", ".flac", ".aac", ".ogg", ".wma"}
        files = sorted([f for f in p.rglob("*") if f.suffix.lower() in supported_exts])
        if not files:
            raise ValueError(f"No supported audio files found in directory: {input_path}")
    else:
        files = [p]

    total_duration = 0.0
    file_details = []

    for f in files:
        cmd = [
            "ffprobe", "-v", "quiet", "-print_format", "json",
            "-show_format", "-show_chapters", "-show_streams", str(f)
        ]
        ret, out, err = run_command(cmd)
        if ret == 0 and out:
            data = json.loads(out)
            fmt = data.get("format", {})
            dur = float(fmt.get("duration", 0.0))
            chapters = data.get("chapters", [])
            
            total_duration += dur
            file_details.append({
                "path": str(f),
                "duration": dur,
                "chapters": [
                    {
                        "start": float(c.get("start_time", 0)),
                        "end": float(c.get("end_time", 0)),
                        "title": c.get("tags", {}).get("title", f"Chapter {idx+1}")
                    }
                    for idx, c in enumerate(chapters)
                ]
            })
        else:
            file_details.append({"path": str(f), "duration": 0.0, "chapters": []})

    return {
        "title": p.stem if p.is_file() else p.name,
        "is_dir": p.is_dir(),
        "files": file_details,
        "total_duration_sec": total_duration,
        "total_duration_formatted": format_duration(total_duration)
    }


def format_duration(seconds):
    """Format duration in H:MM:SS."""
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    if h > 0:
        return f"{h}h {m:02d}m {s:02d}s"
    return f"{m}m {s:02d}s"


def estimate_bitrate_size(duration_sec, bitrate_kbps=10, speed=1.0):
    """Calculate total expected size in Megabytes for encoded AMR-WB+ audio, accounting for playback speed."""
    effective_duration = duration_sec / max(0.25, speed)
    total_bits = effective_duration * (bitrate_kbps * 1000)
    total_bytes = total_bits / 8
    mb = total_bytes / (1024 * 1024)
    # Add 5% overhead for headers/padding
    return round(mb * 1.05, 2)


def calculate_autofit_bitrate(duration_sec, target_capacity_mb=105.0, speed=1.0, target_free_mb=None):
    """
    Calculate maximum safe bitrate (between 10 and 36 kbps) to fill target Playaway storage.
    """
    effective_dur = duration_sec / max(0.25, speed)
    if effective_dur <= 0:
        return 10
    
    capacity = target_free_mb if target_free_mb is not None else target_capacity_mb
    
    # Reserve 5% safety margin for FAT table overhead & PATWEAKS.DAT
    usable_bytes = (capacity * 1024 * 1024) * 0.95
    usable_bits = usable_bytes * 8
    
    calc_bitrate_bps = usable_bits / effective_dur
    calc_bitrate_kbps = calc_bitrate_bps / 1000.0
    
    # Clamp between 10 and 36 kbps
    fit_bitrate = int(min(36, max(10, calc_bitrate_kbps)))
    return fit_bitrate


def build_speed_filter(speed, preserve_pitch=True):
    """
    Build FFmpeg audio filter string for playback speed adjustment.
    If preserve_pitch=True, uses pitch-preserving atempo filter chain.
    If preserve_pitch=False, uses asetrate + aresample filter string for pitch-shifting speed change.
    """
    if abs(speed - 1.0) < 0.01:
        return None

    if preserve_pitch:
        filters = []
        curr = speed
        while curr > 2.0:
            filters.append("atempo=2.0")
            curr /= 2.0
        while curr < 0.5:
            filters.append("atempo=0.5")
            curr /= 0.5
        filters.append(f"atempo={curr:.4f}")
        return ",".join(filters)
    else:
        sample_rate = int(44100 * speed)
        return f"asetrate={sample_rate},aresample=44100"


# Alias for backward compatibility
build_atempo_filter = build_speed_filter


# ==============================================================================
# Chapter Splitting & Segment Planner
# ==============================================================================

def plan_chapters(input_path, split_mode="duration", split_mins=15, title="Audiobook", subchapter_mode=False, final_chapter_silence=True):
    """
    Plan chapter segments based on split_mode ('none', 'duration', 'chapters').
    Returns a list of segment dicts:
    [{'file': path, 'start': sec, 'end': sec, 'out_name': '0001 Book Title 0000.awb'}, ...]
    """
    info = inspect_audio_source(input_path)
    clean_title = re.sub(r'[^\w\s-]', '', title).strip() or "Audiobook"
    
    segments = []

    if split_mode == "chapters" and not info["is_dir"] and info["files"][0]["chapters"]:
        # Split by embedded chapter markers in single file (e.g. M4B)
        f_path = info["files"][0]["path"]
        for idx, ch in enumerate(info["files"][0]["chapters"]):
            start = ch["start"]
            end = ch["end"]
            if end > start:
                track_num = f"{idx + 1:04d}"
                out_name = f"{track_num} {clean_title} 0000.awb"
                if subchapter_mode:
                    out_name = f"001{idx+1:03d} {clean_title} 0000.awb"
                segments.append({
                    "file": f_path,
                    "start": start,
                    "end": end,
                    "duration": end - start,
                    "out_name": out_name,
                    "title": ch["title"]
                })

    elif split_mode == "duration" or (split_mode == "chapters" and not segments):
        # Split into fixed duration blocks (e.g. 15 mins)
        target_dur = max(60, int(split_mins * 60))
        track_idx = 1

        for f_item in info["files"]:
            f_path = f_item["path"]
            f_dur = f_item["duration"]
            if f_dur <= 0:
                continue

            curr = 0.0
            while curr < f_dur:
                seg_end = min(curr + target_dur, f_dur)
                track_num = f"{track_idx:04d}"
                out_name = f"{track_num} {clean_title} 0000.awb"
                if subchapter_mode:
                    out_name = f"001{track_idx:03d} {clean_title} 0000.awb"

                segments.append({
                    "file": f_path,
                    "start": curr,
                    "end": seg_end,
                    "duration": seg_end - curr,
                    "out_name": out_name,
                    "title": f"Part {track_idx}"
                })
                track_idx += 1
                curr = seg_end

    else:
        # 'none' mode: Each input file becomes one chapter track
        for idx, f_item in enumerate(info["files"]):
            f_path = f_item["path"]
            f_dur = f_item["duration"]
            track_num = f"{idx + 1:04d}"
            out_name = f"{track_num} {clean_title} 0000.awb"
            if subchapter_mode:
                out_name = f"001{idx+1:03d} {clean_title} 0000.awb"

            segments.append({
                "file": f_path,
                "start": 0.0,
                "end": f_dur,
                "duration": f_dur,
                "out_name": out_name,
                "title": Path(f_path).stem
            })

    if segments and final_chapter_silence:
        # Append dedicated 5-second silent track (end_silence) to guarantee clean hardware auto-stop
        silence_idx = len(segments) + 1
        track_num = f"{silence_idx:04d}"
        out_name = f"{track_num} {clean_title} 0000.awb"
        if subchapter_mode:
            out_name = f"001{silence_idx:03d} {clean_title} 0000.awb"

        segments.append({
            "file": "__SILENCE__",
            "start": 0.0,
            "end": 5.0,
            "duration": 5.0,
            "out_name": out_name,
            "title": "end_silence",
            "is_silence": True
        })

    if segments:
        segments[-1]["is_last"] = True

    return segments


MAX_SAFE_TRACK_MINS = 88.0  # Firmware 01:03 freeze limit (~1 hour 28 minutes)


def check_track_duration_warnings(segments, speed=1.0, max_mins=MAX_SAFE_TRACK_MINS):
    """
    Inspect planned segments and return a list of warning dicts for any
    active track whose speed-adjusted duration exceeds max_mins (88 mins).
    Returns: [{'index': 1, 'title': '...', 'raw_mins': 95.0, 'effective_mins': 95.0, 'out_name': '...'}]
    """
    warnings = []
    eff_speed = max(0.25, float(speed))
    for idx, seg in enumerate(segments, 1):
        if seg.get("excluded", False) or seg.get("is_silence", False) or seg.get("file") == "__SILENCE__":
            continue
        raw_dur_sec = float(seg.get("duration", 0.0))
        eff_dur_sec = raw_dur_sec / eff_speed
        eff_dur_mins = round(eff_dur_sec / 60.0, 1)
        if eff_dur_mins > max_mins:
            warnings.append({
                "index": idx,
                "title": seg.get("title", f"Track {idx}"),
                "raw_mins": round(raw_dur_sec / 60.0, 1),
                "effective_mins": eff_dur_mins,
                "out_name": seg.get("out_name", "")
            })
    return warnings



# ==============================================================================
# Audio Encoding Engine (FFmpeg -> 3GPP AMR-WB+)
# ==============================================================================

def convert_segment_to_awb(segment, output_dir, bitrate_kbps=10, speed=1.0, preserve_pitch=True, encoder_exe=None, log_callback=None, cancel_event=None):
    """
    Convert a single planned segment to intermediate WAV via FFmpeg, applying speed adjustment (atempo / asetrate),
    then encode to .awb via 3GPP encoder. Generates 5s end_silence track for hardware auto-stop if requested.
    Returns (out_awb_path, single_encoding_duration_sec).
    """
    if cancel_event and cancel_event.is_set():
        raise InterruptedError("Operation stopped by user.")

    if not encoder_exe:
        encoder_exe, _ = setup_encoder()

    if not encoder_exe or not Path(encoder_exe).exists():
        raise RuntimeError("3GPP AMR-WB+ encoder binary is missing!")

    t_start = time.time()
    Path(output_dir).mkdir(parents=True, exist_ok=True)
    out_awb_path = Path(output_dir) / segment["out_name"]
    temp_wav = Path(tempfile.gettempdir()) / f"temp_playaway_{os.getpid()}_{time.time_ns()}.wav"

    try:
        if cancel_event and cancel_event.is_set():
            raise InterruptedError("Operation stopped by user.")

        # Step 1: Export clean mono 44.1kHz 16-bit PCM WAV using FFmpeg
        ff_cmd = ["ffmpeg", "-y"]

        if segment.get("is_silence", False) or segment.get("file") == "__SILENCE__":
            # Generate 5.0 seconds of pure mono silence for dedicated end_silence track
            ff_cmd.extend([
                "-f", "lavfi",
                "-i", "anullsrc=channel_layout=mono:sample_rate=44100",
                "-t", "5.0"
            ])
        else:
            if segment["start"] > 0:
                ff_cmd.extend(["-ss", str(segment["start"])])
            if segment["end"] > 0 and segment["end"] > segment["start"]:
                ff_cmd.extend(["-to", str(segment["end"])])

            ff_cmd.extend([
                "-i", segment["file"]
            ])

            # Apply speed adjustment filter (atempo vs asetrate)
            filters = []
            speed_filter = build_speed_filter(speed, preserve_pitch=preserve_pitch)
            if speed_filter:
                filters.append(speed_filter)

            if filters:
                ff_cmd.extend(["-af", ",".join(filters)])

        ff_cmd.extend([
            "-f", "wav",
            "-c:a", "pcm_s16le",
            "-ar", "44100",
            "-ac", "1",  # STRICT MONO FOR PLAYAWAY
            "-empty_hdlr_name", "1",
            "-fflags", "+bitexact",
            "-flags:v", "+bitexact",
            "-flags:a", "+bitexact",
            "-map_metadata", "-1",
            str(temp_wav)
        ])

        ret, out, err = run_command(ff_cmd, log_callback)
        if cancel_event and cancel_event.is_set():
            raise InterruptedError("Operation stopped by user.")

        if ret != 0 or not temp_wav.exists() or temp_wav.stat().st_size == 0:
            raise RuntimeError(f"FFmpeg WAV conversion failed for {segment['out_name']}: {err}")

        # Step 2: Encode WAV to AMR-WB+ .awb via 3GPP encoder
        enc_cmd = []
        if sys.platform != "win32" and encoder_exe.name.endswith(".exe"):
            enc_cmd.append("wine")

        enc_cmd.extend([
            str(encoder_exe),
            "-rate", str(bitrate_kbps),
            "-mono",
            "-ff", "raw",
            "-if", str(temp_wav),
            "-of", str(out_awb_path)
        ])

        ret, out, err = run_command(enc_cmd, log_callback)
        if cancel_event and cancel_event.is_set():
            raise InterruptedError("Operation stopped by user.")

        if ret != 0 or not out_awb_path.exists() or out_awb_path.stat().st_size == 0:
            raise RuntimeError(f"3GPP AMR-WB+ encoding failed for {segment['out_name']}: {err}\n{out}")

        duration_sec = time.time() - t_start
        if log_callback:
            log_callback(f"Successfully encoded: {segment['out_name']} ({out_awb_path.stat().st_size} bytes, speed: {speed}x, time: {duration_sec:.1f}s)")

        return out_awb_path, duration_sec

    finally:
        if temp_wav.exists():
            try:
                temp_wav.unlink()
            except Exception:
                pass


def format_eta(seconds):
    """Format ETA seconds into human-readable duration string."""
    if seconds <= 0:
        return "0s"
    m, s = divmod(int(seconds), 60)
    h, m = divmod(m, 60)
    if h > 0:
        return f"{h}h {m:02d}m {s:02d}s"
    if m > 0:
        return f"{m}m {s:02d}s"
    return f"{s}s"


def convert_all_segments_parallel(segments, output_dir, bitrate_kbps=10, speed=1.0, preserve_pitch=True, encoder_exe=None, max_workers=None, log_callback=None, progress_callback=None, cancel_event=None):
    """
    Convert all planned segments in parallel using multi-threading (4x-8x speedup) with cancellation & live ETA tracking.
    """
    if not encoder_exe:
        encoder_exe, _ = setup_encoder()

    if not max_workers:
        max_workers = min(os.cpu_count() or 4, 8)

    if log_callback:
        log_callback(f"Encoding {len(segments)} tracks in parallel using {max_workers} CPU threads...")

    completed = 0
    total = len(segments)
    start_time = time.time()

    if progress_callback:
        progress_callback(0, total, "Starting...", "")

    def process_task(item):
        idx, seg = item
        if cancel_event and cancel_event.is_set():
            raise InterruptedError("Operation stopped by user.")
        path, dur = convert_segment_to_awb(
            segment=seg,
            output_dir=output_dir,
            bitrate_kbps=bitrate_kbps,
            speed=speed,
            preserve_pitch=preserve_pitch,
            encoder_exe=encoder_exe,
            log_callback=None,
            cancel_event=cancel_event
        )
        return idx, path, dur

    results = [None] * total
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(process_task, (i, seg)): i for i, seg in enumerate(segments)}
        for future in as_completed(futures):
            if cancel_event and cancel_event.is_set():
                executor.shutdown(wait=False, cancel_futures=True)
                raise InterruptedError("Operation stopped by user.")
            idx = futures[future]
            try:
                _, awb_path, track_dur = future.result()
                results[idx] = awb_path
                completed += 1
                
                # Calculate rolling ETA based on elapsed wall-clock time and completed track rate
                elapsed = time.time() - start_time
                rate = completed / max(0.001, elapsed)  # tracks / sec
                remaining_tracks = total - completed
                eta_sec = remaining_tracks / rate if rate > 0 else 0
                eta_str = f"~{format_eta(eta_sec)}" if completed >= 2 else "Calculating..."
                track_time_str = f"{track_dur:.1f}s" if track_dur < 60 else format_duration(track_dur)

                if progress_callback:
                    progress_callback(completed, total, eta_str, track_time_str)
            except Exception as e:
                if cancel_event and cancel_event.is_set():
                    executor.shutdown(wait=False, cancel_futures=True)
                    raise InterruptedError("Operation stopped by user.")
                raise RuntimeError(f"Error encoding track {segments[idx]['out_name']}: {e}")

    return results


# ==============================================================================
# PATWEAKS.DAT Generator
# ==============================================================================

def generate_patweaks_content(track_count, subchapter_mode=False):
    """
    Generate valid PATWEAKS.DAT content with mandatory header, NMDxxx track count, and CRLF line endings.
    """
    # Header format: AWBVOL + flags + NMDxxx + CRLF
    nmd_str = f"NMD{track_count:03d}"
    
    lines = []
    lines.append(f"AWBVOL082002SLD090080PUP003{nmd_str}")
    if subchapter_mode:
        lines.append("AF*")
        
    content = "\r\n".join(lines) + "\r\n"
    return content


# ==============================================================================
# Playaway Drive Cleaner & Flasher
# ==============================================================================

def wipe_playaway_drive(drive_path, log_callback=None):
    """
    Purge all existing files, hidden system files (CMI_CRC.DAT, .SAV, .DS_Store, desktop.ini), old .awb tracks, and directories.
    """
    target = Path(drive_path)
    if not target.exists():
        raise FileNotFoundError(f"Drive path not found: {drive_path}")

    if log_callback:
        log_callback(f"Wiping existing files on Playaway drive: {drive_path}...")

    # Iterate over items in root directory (including hidden files)
    for item in target.iterdir():
        try:
            # Clear read-only / hidden file attributes on Windows
            if sys.platform == "win32":
                try:
                    os.chmod(item, 0o777)
                except Exception:
                    pass

            if item.is_file() or item.is_symlink():
                item.unlink()
                if log_callback:
                    log_callback(f"Deleted file: {item.name}")
            elif item.is_dir():
                shutil.rmtree(item, ignore_errors=True)
                if log_callback:
                    log_callback(f"Deleted directory: {item.name}")
        except Exception as e:
            if log_callback:
                log_callback(f"Warning: Could not remove {item.name}: {e}")

    sync_drive(str(target))


def flash_playaway(drive_path, awb_dir, track_count, subchapter_mode=False, log_callback=None, progress_callback=None):
    """
    Wipe target drive, copy newly encoded .awb files, write PATWEAKS.DAT, and flush buffers.
    """
    drive_p = Path(drive_path)
    awb_p = Path(awb_dir)

    if not drive_p.exists():
        raise FileNotFoundError(f"Target Playaway drive not accessible: {drive_path}")

    # 1. Clean drive
    wipe_playaway_drive(str(drive_p), log_callback)

    # 2. Copy .awb files
    awb_files = sorted(list(awb_p.glob("*.awb")))
    if not awb_files:
        raise ValueError(f"No .awb files found in staging directory: {awb_dir}")

    total_files = len(awb_files)
    for idx, src_file in enumerate(awb_files):
        dest_file = drive_p / src_file.name
        if log_callback:
            log_callback(f"Flashing track [{idx+1}/{total_files}]: {src_file.name}...")
        
        shutil.copy2(src_file, dest_file)
        
        if progress_callback:
            progress_callback(idx + 1, total_files, f"Flashing track {idx+1}/{total_files}")

    # 3. Write PATWEAKS.DAT
    patweaks_file = drive_p / "PATWEAKS.DAT"
    pat_content = generate_patweaks_content(len(awb_files), subchapter_mode)
    
    with open(patweaks_file, "wb") as f:
        f.write(pat_content.encode("ascii"))

    if log_callback:
        log_callback(f"Wrote PATWEAKS.DAT with NMD{len(awb_files):03d}")

    # 4. Flush OS disk buffers
    if log_callback:
        log_callback("Flushing storage buffers & syncing drive...")
    sync_drive(str(drive_p))

    if log_callback:
        log_callback("\n=== FLASH COMPLETED SUCCESSFULLY! Safe to disconnect USB. ===")


def backup_playaway_drive(drive_path, backup_dir, log_callback=None, progress_callback=None):
    """
    Backup all existing files from Playaway drive to a local backup directory.
    """
    src = Path(drive_path)
    dst = Path(backup_dir)
    if not src.exists():
        raise FileNotFoundError(f"Playaway drive not accessible: {drive_path}")
    
    dst.mkdir(parents=True, exist_ok=True)
    
    items = list(src.iterdir())
    total_items = len(items)
    copied = 0
    total_bytes = 0
    
    if log_callback:
        log_callback(f"Starting backup of drive {drive_path} to {dst.resolve()}...")
        
    for item in items:
        rel_path = item.name
        dest_item = dst / rel_path
        if item.is_file():
            shutil.copy2(item, dest_item)
            total_bytes += item.stat().st_size
            copied += 1
            if log_callback:
                log_callback(f"Backed up [{copied}/{total_items}]: {rel_path}")
            if progress_callback:
                progress_callback(copied, total_items, f"Backing up {rel_path}")
        elif item.is_dir():
            shutil.copytree(item, dest_item, dirs_exist_ok=True)
            copied += 1
            if log_callback:
                log_callback(f"Backed up directory [{copied}/{total_items}]: {rel_path}")

    if log_callback:
        log_callback(f"\n=== BACKUP COMPLETED! {copied} items saved ({round(total_bytes/(1024*1024), 2)} MB) ===")
    return dst


# ==============================================================================
# Configuration Persistence Manager
# ==============================================================================

DEFAULT_CONFIG_PATH = Path(__file__).parent / "playaway_config.json"

DEFAULT_SETTINGS = {
    "split_mode": "duration",
    "split_mins": 15,
    "subchapter_mode": False,
    "playback_speed": 1.0,
    "preserve_pitch": True,
    "bitrate_kbps": 10,
    "final_chapter_silence": True
}

def load_config(config_path=None):
    """
    Load settings dictionary from JSON config file. Falls back to DEFAULT_SETTINGS if missing or invalid.
    """
    c_path = Path(config_path) if config_path else DEFAULT_CONFIG_PATH
    if not c_path.exists():
        return dict(DEFAULT_SETTINGS)

    try:
        with open(c_path, "r", encoding="utf-8") as f:
            data = json.load(f)
            merged = dict(DEFAULT_SETTINGS)
            merged.update({k: v for k, v in data.items() if k in DEFAULT_SETTINGS})
            return merged
    except Exception:
        return dict(DEFAULT_SETTINGS)


def save_config(settings_dict, config_path=None):
    """
    Save settings dictionary to JSON config file.
    """
    c_path = Path(config_path) if config_path else DEFAULT_CONFIG_PATH
    c_path.parent.mkdir(parents=True, exist_ok=True)
    
    clean_settings = {k: settings_dict.get(k, DEFAULT_SETTINGS[k]) for k in DEFAULT_SETTINGS}
    with open(c_path, "w", encoding="utf-8") as f:
        json.dump(clean_settings, f, indent=4)
    return str(c_path)

