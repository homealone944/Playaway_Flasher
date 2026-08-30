#!/usr/bin/env python3
"""
core_bridge.py - Bridge between Calibre plugin UI and Playaway Core Engine
"""

import sys
import os
from pathlib import Path

# When packaged in Calibre zip, modules are in the same package namespace
try:
    from calibre_plugins.playaway_flasher.playaway_core import (
        detect_playaway_drives,
        inspect_audio_source,
        plan_chapters,
        check_track_duration_warnings,
        MAX_SAFE_TRACK_MINS,
        convert_all_segments_parallel,
        generate_patweaks_content,
        flash_playaway,
        backup_playaway_drive,
        is_system_drive,
        generate_copy_instructions,
        estimate_bitrate_size,
        calculate_autofit_bitrate,
        format_duration,
        load_config,
        save_config,
        DEFAULT_SETTINGS
    )
    from calibre_plugins.playaway_flasher.fetch_encoder import setup_encoder, find_encoder
except (ImportError, ValueError):
    # Direct local execution fallback
    parent_dir = str(Path(__file__).parent.parent.resolve())
    if parent_dir not in sys.path:
        sys.path.insert(0, parent_dir)

    from playaway_core import (
        detect_playaway_drives,
        inspect_audio_source,
        plan_chapters,
        check_track_duration_warnings,
        MAX_SAFE_TRACK_MINS,
        convert_all_segments_parallel,
        generate_patweaks_content,
        flash_playaway,
        backup_playaway_drive,
        is_system_drive,
        generate_copy_instructions,
        estimate_bitrate_size,
        calculate_autofit_bitrate,
        format_duration,
        load_config,
        save_config,
        DEFAULT_SETTINGS
    )
    from fetch_encoder import setup_encoder, find_encoder


SUPPORTED_AUDIO_FORMATS = {'M4B', 'MP3', 'M4A', 'FLAC', 'AAC', 'WAV', 'OGG', 'WMA'}


def get_audiobook_formats_for_book(db, book_id):
    """
    Query Calibre database for available audio formats for a given book_id.
    Handles both Calibre new_api and legacy db formats representations.
    Returns dict: {'M4B': '/path/to/book.m4b', ...}
    """
    if not book_id:
        return {}

    available = {}

    # Method 1: Try Calibre new_api
    if hasattr(db, 'new_api') and db.new_api is not None:
        try:
            fmts = db.new_api.formats(book_id)
            if fmts:
                for fmt in fmts:
                    fmt_u = str(fmt).upper()
                    if fmt_u in SUPPORTED_AUDIO_FORMATS:
                        p = db.new_api.format_abspath(book_id, fmt)
                        if p and os.path.exists(p):
                            available[fmt_u] = p
        except Exception:
            pass

    # Method 2: Legacy db fallback
    if not available:
        try:
            raw_fmts = db.formats(book_id, index_is_id=True)
            if raw_fmts:
                if isinstance(raw_fmts, str):
                    fmt_list = [f.strip() for f in raw_fmts.split(',') if f.strip()]
                else:
                    fmt_list = list(raw_fmts)

                for fmt in fmt_list:
                    fmt_u = str(fmt).upper()
                    if fmt_u in SUPPORTED_AUDIO_FORMATS:
                        p = db.format_abspath(book_id, fmt, index_is_id=True)
                        if p and os.path.exists(p):
                            available[fmt_u] = p
        except Exception:
            pass

    return available


try:
    from calibre.utils.config import JSONConfig
    plugin_prefs = JSONConfig('plugins/playaway_flasher')
    for k, v in DEFAULT_SETTINGS.items():
        plugin_prefs.defaults[k] = v
except Exception:
    plugin_prefs = None


def load_config_calibre(config_path=None):
    """Load settings using Calibre native JSONConfig with fallback."""
    if plugin_prefs is not None:
        cfg = dict(DEFAULT_SETTINGS)
        for k in DEFAULT_SETTINGS:
            cfg[k] = plugin_prefs.get(k, DEFAULT_SETTINGS[k])
        return cfg
    return load_config(config_path)


def save_config_calibre(settings_dict, config_path=None):
    """Save settings using Calibre native JSONConfig without modifying the plugin zip file."""
    if plugin_prefs is not None:
        for k in DEFAULT_SETTINGS:
            if k in settings_dict:
                plugin_prefs[k] = settings_dict[k]
        try:
            save_config(settings_dict, config_path)
        except Exception:
            pass
        return "calibre_json_config"
    return save_config(settings_dict, config_path)


# Re-export Calibre-safe config handlers
load_config = load_config_calibre
save_config = save_config_calibre
