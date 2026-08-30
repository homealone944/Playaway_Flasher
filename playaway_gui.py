#!/usr/bin/env python3
"""
playaway_gui.py - Modern Tkinter Desktop GUI for Playaway Audiobook Installer
Provides a sleek, user-friendly interface for basic Windows users to tweak audiobooks and flash Playaways.
"""

import os
import sys
import time
import threading
import subprocess
import re
import ctypes
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, simpledialog
from pathlib import Path

try:
    import vlc
    HAS_VLC = True
except Exception:
    vlc = None
    HAS_VLC = False

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
    build_speed_filter as build_atempo_filter,
    format_duration,
    load_config,
    save_config,
    DEFAULT_SETTINGS
)
from fetch_encoder import setup_encoder, find_encoder


class PlayawayStudioGUI(tk.Tk):
    def __init__(self):
        super().__init__()

        self.title("Playaway Audiobook Studio & Flasher")
        self.setup_window_icon()

        # Dynamically set window height to full display height (minus taskbar margin)
        self.update_idletasks()
        scr_w = self.winfo_screenwidth()
        scr_h = self.winfo_screenheight()
        win_w = min(1120, max(960, scr_w - 60))
        win_h = max(750, scr_h - 80)
        self.geometry(f"{win_w}x{win_h}+0+0")
        self.minsize(960, 720)

        # Styling & Dark Palette
        self.style = ttk.Style(self)
        self.setup_theme()

        # State Variables & Load Persistent Config Settings
        cfg = load_config()
        self.input_path = tk.StringVar(value="")
        self.book_title = tk.StringVar(value="My Audiobook")
        self.split_mode = tk.StringVar(value=cfg.get("split_mode", "duration"))
        self.split_mins = tk.IntVar(value=cfg.get("split_mins", 15))
        self.split_mins.trace_add("write", lambda *a: self.after_idle(self.on_split_mins_changed))
        self.subchapter_mode = tk.BooleanVar(value=cfg.get("subchapter_mode", False))
        cfg_bit = cfg.get("bitrate_kbps", "auto")
        if str(cfg_bit).lower() == "auto":
            self.bitrate_is_auto = tk.BooleanVar(value=True)
            self.bitrate_kbps = tk.IntVar(value=10)
        else:
            self.bitrate_is_auto = tk.BooleanVar(value=False)
            try:
                self.bitrate_kbps = tk.IntVar(value=int(cfg_bit))
            except (ValueError, TypeError):
                self.bitrate_kbps = tk.IntVar(value=10)

        self.playback_speed = tk.DoubleVar(value=cfg.get("playback_speed", 1.0))
        self.preserve_pitch = tk.BooleanVar(value=cfg.get("preserve_pitch", True))
        self.final_chapter_silence = tk.BooleanVar(value=cfg.get("final_chapter_silence", True))
        self.selected_drive = tk.StringVar(value="")
        
        self.audio_info = None
        self.planned_segments = []
        self.drives = []
        self.cancel_event = threading.Event()

        # LibVLC Audio Engine Setup
        self.vlc_instance = None
        self.vlc_player = None
        if HAS_VLC:
            try:
                self.vlc_instance = vlc.Instance("--no-xlib", "--quiet", "--no-video-title-show")
                self.vlc_player = self.vlc_instance.media_player_new()
            except Exception as e:
                print(f"VLC initialization fallback: {e}")

        # Build UI
        self.create_widgets()
        self.setup_vlc_engine()

        # Initial Auto-Detect Drives & Encoder
        self.refresh_drives()
        self.check_encoder_status()
        self.protocol("WM_DELETE_WINDOW", self.on_closing)

    def on_closing(self):
        """Clean up audio processes and LibVLC engine when window is closed."""
        self.stop_audio_preview(log_msg=False)
        if self.vlc_player:
            try:
                self.vlc_player.stop()
                self.vlc_player.release()
            except Exception:
                pass
        self.destroy()

    def setup_vlc_engine(self):
        """Bind LibVLC player output HWND handle to self.vlc_frame."""
        if not self.vlc_player or not hasattr(self, "vlc_frame"):
            return

        try:
            self.update_idletasks()
            if sys.platform == "win32":
                self.vlc_player.set_hwnd(self.vlc_frame.winfo_id())
            else:
                self.vlc_player.set_xwindow(self.vlc_frame.winfo_id())
        except Exception as e:
            print(f"LibVLC HWND Embed Warning: {e}")

    def on_vlc_volume_slide(self, val):
        """Adjust LibVLC audio playback volume (0 to 100) and update label."""
        vol = int(float(val))
        if hasattr(self, "vlc_vol_label"):
            self.vlc_vol_label.config(text=f"Volume: {vol}%")
        if self.vlc_player:
            try:
                self.vlc_player.audio_set_volume(vol)
            except Exception:
                pass

    def setup_theme(self):
        """Configure modern dark mode palette."""
        self.configure(bg="#1e1e2e")

        # Global listbox option styling for Combobox dropdown popups
        self.option_add("*TCombobox*Listbox.background", "#181825")
        self.option_add("*TCombobox*Listbox.foreground", "#cdd6f4")
        self.option_add("*TCombobox*Listbox.selectBackground", "#89b4fa")
        self.option_add("*TCombobox*Listbox.selectForeground", "#11111b")
        self.option_add("*TCombobox*Listbox.font", ("Segoe UI", 9))

        self.style.theme_use("clam")
        self.style.configure(".", background="#1e1e2e", foreground="#cdd6f4", font=("Segoe UI", 10))
        self.style.configure("TLabelframe", background="#181825", foreground="#89b4fa", borderwidth=1, relief="solid")
        self.style.configure("TLabelframe.Label", background="#181825", foreground="#89b4fa", font=("Segoe UI", 10, "bold"))
        self.style.configure("TFrame", background="#1e1e2e")
        self.style.configure("Card.TFrame", background="#181825")
        
        self.style.configure("TLabel", background="#1e1e2e", foreground="#cdd6f4")
        self.style.configure("Card.TLabel", background="#181825", foreground="#cdd6f4")
        self.style.configure("Header.TLabel", background="#1e1e2e", foreground="#89b4fa", font=("Segoe UI", 14, "bold"))

        # Button Styles & Hover Mappings
        self.style.configure("TButton", background="#313244", foreground="#cdd6f4", borderwidth=0, padding=6, font=("Segoe UI", 10, "bold"))
        self.style.map("TButton", 
            background=[("active", "#45475a"), ("disabled", "#181825")],
            foreground=[("active", "#ffffff"), ("disabled", "#585b70")]
        )

        self.style.configure("Accent.TButton", background="#89b4fa", foreground="#11111b", borderwidth=0, padding=10, font=("Segoe UI", 11, "bold"))
        self.style.map("Accent.TButton", 
            background=[("active", "#b4befe"), ("disabled", "#313244")],
            foreground=[("active", "#11111b"), ("disabled", "#6c7086")]
        )

        self.style.configure("Danger.TButton", background="#f38ba8", foreground="#11111b", borderwidth=0, padding=6, font=("Segoe UI", 10, "bold"))
        self.style.map("Danger.TButton", 
            background=[("active", "#f5e0dc"), ("disabled", "#313244")],
            foreground=[("active", "#11111b"), ("disabled", "#585b70")]
        )

        # Radiobutton & Checkbutton Styles & Hover/Disabled Mappings
        self.style.configure("TRadiobutton", background="#181825", foreground="#cdd6f4", font=("Segoe UI", 10))
        self.style.map("TRadiobutton",
            background=[("active", "#181825")],
            foreground=[("active", "#89b4fa"), ("disabled", "#585b70")],
            indicatorbackground=[("selected", "#89b4fa"), ("active", "#45475a")]
        )

        self.style.configure("TCheckbutton", background="#181825", foreground="#cdd6f4", font=("Segoe UI", 10))
        self.style.map("TCheckbutton",
            background=[("active", "#181825")],
            foreground=[("active", "#89b4fa"), ("disabled", "#585b70")],
            indicatorbackground=[("selected", "#89b4fa"), ("active", "#45475a")]
        )

        # Combobox Styles & Readonly/Disabled Mappings
        self.style.configure("TCombobox", 
            fieldbackground="#313244", 
            background="#313244", 
            foreground="#cdd6f4", 
            darkcolor="#313244", 
            lightcolor="#313244", 
            bordercolor="#45475a", 
            arrowcolor="#89b4fa",
            font=("Segoe UI", 10)
        )
        self.style.map("TCombobox",
            fieldbackground=[("readonly", "#313244"), ("disabled", "#181825")],
            foreground=[("readonly", "#cdd6f4"), ("disabled", "#6c7086")],
            background=[("active", "#45475a"), ("readonly", "#313244")]
        )

        # Spinbox & Entry Styling for High Contrast in Dark Mode
        self.style.configure("TSpinbox",
            fieldbackground="#313244",
            background="#313244",
            foreground="#cdd6f4",
            darkcolor="#313244",
            lightcolor="#313244",
            bordercolor="#89b4fa",
            arrowcolor="#89b4fa",
            font=("Segoe UI", 10, "bold"),
            padding=[4, 2]
        )
        self.style.map("TSpinbox",
            fieldbackground=[("focus", "#45475a"), ("active", "#45475a"), ("disabled", "#181825")],
            foreground=[("disabled", "#6c7086")],
            background=[("active", "#45475a")]
        )
        self.style.configure("TEntry",
            fieldbackground="#313244",
            background="#313244",
            foreground="#cdd6f4",
            bordercolor="#45475a",
            font=("Segoe UI", 10),
            padding=[4, 2]
        )
        self.style.map("TEntry",
            fieldbackground=[("focus", "#45475a"), ("disabled", "#181825")],
            foreground=[("disabled", "#6c7086")]
        )

        # Treeview Styling & Heading Styles
        self.style.configure("Treeview",
            background="#11111b",
            foreground="#cdd6f4",
            fieldbackground="#11111b",
            font=("Consolas", 9),
            rowheight=22
        )
        self.style.map("Treeview",
            background=[("selected", "#45475a")],
            foreground=[("selected", "#ffffff")]
        )
        self.style.configure("Treeview.Heading",
            background="#313244",
            foreground="#cdd6f4",
            font=("Segoe UI", 9, "bold"),
            relief="flat"
        )
        self.style.map("Treeview.Heading",
            background=[("active", "#45475a")]
        )

        # Notebook Tabs Styling
        self.style.configure("TNotebook", background="#1e1e2e", borderwidth=0, tabmargins=[2, 5, 2, 0])
        self.style.configure("TNotebook.Tab", 
            background="#313244", 
            foreground="#cdd6f4", 
            padding=[16, 8], 
            font=("Segoe UI", 10, "bold"),
            borderwidth=0,
            focuscolor="#1e1e2e"
        )
        self.style.map("TNotebook.Tab",
            background=[("selected", "#89b4fa"), ("active", "#45475a")],
            foreground=[("selected", "#11111b"), ("active", "#ffffff")],
            expand=[("selected", [1, 2, 1, 0])]
        )

    def setup_window_icon(self):
        """Set the window and taskbar icon to match the Calibre plugin icon."""
        # Decouple process from default python.exe icon on Windows taskbar
        if sys.platform == "win32":
            try:
                myappid = "homealone944.playaway.studio.flasher.1.0"
                ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(myappid)
            except Exception:
                pass

        base_dir = Path(__file__).parent
        icon_paths = [
            base_dir / "calibre_plugin" / "images" / "icon.png",
            base_dir / "calibre_plugin" / "icon.png",
            base_dir / "resources" / "icon.png",
            base_dir / "images" / "icon.png",
        ]
        for icon_path in icon_paths:
            if icon_path.exists():
                try:
                    self._app_icon = tk.PhotoImage(file=str(icon_path))
                    self.iconphoto(True, self._app_icon)
                    break
                except Exception as e:
                    print(f"Window icon loading note: {e}")

    def create_widgets(self):
        # Header Banner
        header_frame = ttk.Frame(self)
        header_frame.pack(fill="x", padx=15, pady=10)

        title_label = ttk.Label(header_frame, text="⚡ Playaway Audiobook Studio & Flasher", style="Header.TLabel")
        title_label.pack(side="left")

        self.encoder_status_label = ttk.Label(header_frame, text="Encoder: Checking...", font=("Segoe UI", 9))
        self.encoder_status_label.pack(side="right")

        # Notebook Tabs Layout
        notebook = ttk.Notebook(self)
        notebook.pack(fill="both", expand=True, padx=15, pady=5)

        tab_studio = ttk.Frame(notebook)
        tab_help = ttk.Frame(notebook)

        notebook.add(tab_studio, text="  ⚡ Studio & Flasher  ")
        notebook.add(tab_help, text="  📖 Help & User Guide  ")

        # TAB 1: STUDIO CONTAINER (Scrollable Canvas Wrapper)
        studio_canvas = tk.Canvas(tab_studio, bg="#1e1e2e", highlightthickness=0, borderwidth=0)
        studio_scrollbar = ttk.Scrollbar(tab_studio, orient="vertical", command=studio_canvas.yview)

        main_container = ttk.Frame(studio_canvas, style="TFrame")
        
        def _update_scrollregion(event=None):
            bbox = studio_canvas.bbox("all")
            if bbox:
                # Lock scrollregion boundaries strictly to (0, 0, width, height) to eliminate whitespace above
                studio_canvas.configure(scrollregion=(0, 0, bbox[2], max(bbox[3], 1)))

        main_container.bind("<Configure>", _update_scrollregion)
        canvas_window = studio_canvas.create_window((0, 0), window=main_container, anchor="nw")

        def _on_canvas_resize(event):
            studio_canvas.itemconfig(canvas_window, width=event.width)

        studio_canvas.bind("<Configure>", _on_canvas_resize)
        studio_canvas.configure(yscrollcommand=studio_scrollbar.set)

        studio_canvas.pack(side="left", fill="both", expand=True, padx=4, pady=4)
        studio_scrollbar.pack(side="right", fill="y")

        def _on_mousewheel(event):
            # Only scroll canvas if mouse is not inside Treeview or Text widgets
            w = event.widget
            if isinstance(w, (ttk.Treeview, tk.Text)):
                return

            # Lock mousewheel scrolling so it cannot scroll up past the top y=0 boundary
            top, bottom = studio_canvas.yview()
            if event.delta > 0 and top <= 0.0:
                return
            if event.delta < 0 and bottom >= 1.0:
                return

            studio_canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

        studio_canvas.bind_all("<MouseWheel>", _on_mousewheel)

        # CARD 1: Input Audio File Selection
        input_card = ttk.LabelFrame(main_container, text=" 1. Select Audiobook Source ", padding=12)
        input_card.pack(fill="x", pady=6)

        input_row = ttk.Frame(input_card, style="Card.TFrame")
        input_row.pack(fill="x", expand=True)

        self.input_entry = ttk.Entry(input_row, textvariable=self.input_path, font=("Segoe UI", 10))
        self.input_entry.pack(side="left", fill="x", expand=True, padx=(0, 6))

        btn_browse_file = ttk.Button(input_row, text="📁 Browse File", command=self.browse_file)
        btn_browse_file.pack(side="left", padx=2)

        btn_browse_dir = ttk.Button(input_row, text="📂 Browse Folder", command=self.browse_folder)
        btn_browse_dir.pack(side="left", padx=2)

        self.info_label = ttk.Label(input_card, text="Select any M4B, MP3, M4A, or WAV file/folder on your computer.", style="Card.TLabel", font=("Segoe UI", 9, "italic"), foreground="#a6adc8")
        self.info_label.pack(fill="x", pady=(6, 0))

        # CARD 2: Chapter Tweaks & Quality Settings
        tweaks_card = ttk.LabelFrame(main_container, text=" 2. Chapter Tweaks & Audio Quality (Optional) ", padding=12)
        tweaks_card.pack(fill="x", pady=6)

        # Top Action Bar (Save & Reset Settings)
        top_bar = ttk.Frame(tweaks_card, style="Card.TFrame")
        top_bar.pack(fill="x", pady=(0, 6))

        ttk.Label(top_bar, text="Configure Audio Quality & Chapter Splitting Preferences:", style="Card.TLabel", font=("Segoe UI", 9, "italic")).pack(side="left")

        top_btn_box = ttk.Frame(top_bar, style="Card.TFrame")
        top_btn_box.pack(side="right")

        btn_save = ttk.Button(top_btn_box, text="💾 Save Settings", command=self.save_current_settings)
        btn_save.pack(side="left", padx=2)

        btn_load = ttk.Button(top_btn_box, text="📂 Load Saved", command=self.load_saved_settings)
        btn_load.pack(side="left", padx=2)

        btn_reset = ttk.Button(top_btn_box, text="🔄 Reset Defaults", command=self.reset_default_settings)
        btn_reset.pack(side="left", padx=2)

        # 3-Column Sub-Card Layout: Chapter Layout, Playback & Hardware, Bitrate & Storage
        tweak_grid = ttk.Frame(tweaks_card, style="Card.TFrame")
        tweak_grid.pack(fill="x", pady=(2, 0))

        # Column 1: Chapter Layout Sub-Card
        col1 = ttk.LabelFrame(tweak_grid, text=" 📁 Chapter Layout ", padding=8)
        col1.pack(side="left", fill="both", expand=True, padx=(0, 4))

        ttk.Label(col1, text="Splitting Mode:", style="Card.TLabel", font=("Segoe UI", 9, "bold")).pack(anchor="w", pady=(0, 2))
        
        rb_dur = ttk.Radiobutton(col1, text="Split fixed mins:", variable=self.split_mode, value="duration", command=self.update_estimates)
        rb_dur.pack(anchor="w")

        dur_subframe = ttk.Frame(col1, style="Card.TFrame")
        dur_subframe.pack(anchor="w", padx=16, pady=1)
        self.sp_mins = ttk.Spinbox(
            dur_subframe,
            from_=1,
            to=180,
            textvariable=self.split_mins,
            width=5,
            font=("Segoe UI", 10, "bold"),
            command=self.on_split_mins_changed
        )
        self.sp_mins.pack(side="left", padx=(0, 4))
        self.sp_mins.bind("<Return>", lambda e: self.on_split_mins_changed())
        self.sp_mins.bind("<KP_Enter>", lambda e: self.on_split_mins_changed())
        self.sp_mins.bind("<KeyRelease>", lambda e: self.on_split_mins_changed())
        self.sp_mins.bind("<FocusOut>", lambda e: self.on_split_mins_changed())
        self.sp_mins.bind("<Button-1>", lambda e: self.split_mode.set("duration"))
        ttk.Label(dur_subframe, text="mins per track", style="Card.TLabel", font=("Segoe UI", 9)).pack(side="left")

        rb_chap = ttk.Radiobutton(col1, text="Split by chapter tags", variable=self.split_mode, value="chapters", command=self.update_estimates)
        rb_chap.pack(anchor="w", pady=2)

        rb_none = ttk.Radiobutton(col1, text="Keep tracks as-is", variable=self.split_mode, value="none", command=self.update_estimates)
        rb_none.pack(anchor="w")

        cb_subchap = ttk.Checkbutton(col1, text="Enable Subchapters (AF*)", variable=self.subchapter_mode, command=self.update_estimates)
        cb_subchap.pack(anchor="w", pady=(4, 0))

        # Column 2: Playback & Hardware Tweaks Sub-Card
        col2 = ttk.LabelFrame(tweak_grid, text=" 🎛️ Playback & Hardware ", padding=8)
        col2.pack(side="left", fill="both", expand=True, padx=4)

        ttk.Label(col2, text="Playback Speed:", style="Card.TLabel", font=("Segoe UI", 9, "bold")).pack(anchor="w", pady=(0, 2))
        
        self.speed_combo = ttk.Combobox(
            col2,
            values=["0.75x", "0.85x", "1.0x (Normal)", "1.1x", "1.25x", "1.5x", "1.75x", "2.0x", "2.25x", "2.5x", "2.75x", "3.0x"],
            state="readonly",
            width=13,
            font=("Segoe UI", 9)
        )
        init_spd = self.playback_speed.get()
        init_spd_str = f"{init_spd}x (Normal)" if init_spd == 1.0 else f"{init_spd}x"
        self.speed_combo.set(init_spd_str)
        self.speed_combo.pack(anchor="w", pady=(0, 6))
        self.speed_combo.bind("<<ComboboxSelected>>", self.on_speed_changed)

        cb_pitch = ttk.Checkbutton(col2, text="Preserve Voice Pitch (atempo)", variable=self.preserve_pitch)
        cb_pitch.pack(anchor="w", pady=(2, 4))

        cb_silence = ttk.Checkbutton(col2, text="Add 5s End Silence (Firmware Fix)", variable=self.final_chapter_silence, command=self.on_silence_toggle)
        cb_silence.pack(anchor="w", pady=(0, 2))

        # Column 3: Encoding Bitrate & Storage Sub-Card
        col3 = ttk.LabelFrame(tweak_grid, text=" ⚡ Bitrate & Storage ", padding=8)
        col3.pack(side="left", fill="both", expand=True, padx=(4, 0))

        bitrate_row = ttk.Frame(col3, style="Card.TFrame")
        bitrate_row.pack(fill="x", pady=(0, 2))

        ttk.Label(bitrate_row, text="Encoding Bitrate:", style="Card.TLabel", font=("Segoe UI", 9, "bold")).pack(side="left")

        btn_autofit = ttk.Button(bitrate_row, text="⚡ Auto-Fit Bitrate", command=self.autofit_bitrate)
        btn_autofit.pack(side="right")

        self.bitrate_label = ttk.Label(col3, text="Bitrate: 10 kbps (~23 hrs on 105MB)", style="Card.TLabel", font=("Segoe UI", 8))
        self.bitrate_label.pack(anchor="w")

        bitrate_slider = ttk.Scale(col3, from_=10, to=36, variable=self.bitrate_kbps, orient="horizontal", command=self.on_bitrate_slide)
        bitrate_slider.pack(fill="x", pady=4)

        self.estimate_label = ttk.Label(col3, text="Estimated Encoded Size: 0 MB", style="Card.TLabel", font=("Segoe UI", 9, "bold"), foreground="#a6e3a1")
        self.estimate_label.pack(anchor="w", pady=(2, 0))

        # Chapter & Audio Info Summary Panel (Hidden by default until an audiobook is selected)
        self.info_frame = ttk.LabelFrame(tweaks_card, text=" 📊 Audiobook & Chapter Summary ", padding=8)
        self.info_frame.pack(fill="x", expand=True, pady=(8, 0))
        info_frame = self.info_frame

        self.stats_label = ttk.Label(info_frame, text="No audiobook loaded.", style="Card.TLabel", font=("Segoe UI", 9, "bold"))
        self.stats_label.pack(anchor="w", pady=(0, 2))

        self.chapter_warning_label = ttk.Label(info_frame, text="", style="Card.TLabel", font=("Segoe UI", 9, "bold"), foreground="#fab387", wraplength=720)
        # Note: chapter_warning_label is packed dynamically when >88 min tracks are detected

        list_subframe = ttk.Frame(info_frame, style="Card.TFrame")
        list_subframe.pack(fill="x", expand=True)

        self.chapter_tree = ttk.Treeview(
            list_subframe,
            columns=("index", "title", "timeframe", "length", "status"),
            show="headings",
            height=6,
            selectmode="extended"
        )
        self.chapter_tree.heading("index", text="#")
        self.chapter_tree.heading("title", text="Track Title")
        self.chapter_tree.heading("timeframe", text="Timeframe")
        self.chapter_tree.heading("length", text="Length")
        self.chapter_tree.heading("status", text="Status")

        self.chapter_tree.column("index", width=55, anchor="center")
        self.chapter_tree.column("title", width=320, anchor="w")
        self.chapter_tree.column("timeframe", width=220, anchor="center")
        self.chapter_tree.column("length", width=90, anchor="center")
        self.chapter_tree.column("status", width=90, anchor="center")

        self.chapter_tree.pack(side="left", fill="both", expand=True)

        chap_scroll = ttk.Scrollbar(list_subframe, orient="vertical", command=self.chapter_tree.yview)
        chap_scroll.pack(side="right", fill="y")
        self.chapter_tree.configure(yscrollcommand=chap_scroll.set)

        self.chapter_tree.bind("<<TreeviewSelect>>", self.on_tree_select)

        # Chapter Actions Toolbar (Exclude / Include, Restore All Tracks, Reset Chapters)
        chap_act_bar = ttk.Frame(info_frame, style="Card.TFrame")
        chap_act_bar.pack(fill="x", pady=(6, 2))

        self.btn_toggle_exclude = ttk.Button(chap_act_bar, text="🗑️ Exclude / Include Track", command=self.toggle_exclude_selected_track)
        self.btn_toggle_exclude.pack(side="left", padx=(0, 4))

        self.btn_restore_all = ttk.Button(chap_act_bar, text="🔄 Restore All Tracks", command=self.restore_all_tracks)
        self.btn_restore_all.pack(side="left", padx=4)

        self.btn_reload_chapters = ttk.Button(chap_act_bar, text="🔁 Reset Chapters from Source", command=self.reset_chapters_from_source)
        self.btn_reload_chapters.pack(side="left", padx=4)

        # Embedded LibVLC Media Player Controls
        vlc_container = ttk.LabelFrame(info_frame, text=" 🎧 LibVLC Audio Player ", padding=8)
        vlc_container.pack(fill="x", expand=True, pady=(6, 0))

        # Hidden HWND embed frame for LibVLC video/audio rendering engine
        self.vlc_frame = ttk.Frame(vlc_container, width=1, height=1)
        self.vlc_frame.pack_forget()

        # Row 1: Player Buttons & Volume Slider
        vlc_bar = ttk.Frame(vlc_container, style="Card.TFrame")
        vlc_bar.pack(fill="x", pady=(0, 4))

        self.btn_preview = ttk.Button(vlc_bar, text="▶ Play", command=self.toggle_play_pause)
        self.btn_preview.pack(side="left", padx=(0, 4))

        self.btn_split_at_cursor = ttk.Button(vlc_bar, text="✂️ Split Chapter at Scrubber", command=self.split_selected_chapter)
        self.btn_split_at_cursor.pack(side="left", padx=(0, 8))

        self.vlc_vol_label = ttk.Label(vlc_bar, text="Volume: 100%", style="Card.TLabel", font=("Segoe UI", 9))
        self.vlc_vol_label.pack(side="left", padx=(8, 4))

        self.vlc_volume_var = tk.DoubleVar(value=100.0)
        self.vlc_vol_slider = ttk.Scale(
            vlc_bar, 
            from_=0, 
            to=100, 
            variable=self.vlc_volume_var, 
            orient="horizontal", 
            length=160, 
            command=self.on_vlc_volume_slide
        )
        self.vlc_vol_slider.pack(side="left")

        # Row 2: Live Timeline Scrubber & Position Bar
        scrub_row = ttk.Frame(vlc_container, style="Card.TFrame")
        scrub_row.pack(fill="x", pady=(4, 0))

        self.scrub_pct = tk.DoubleVar(value=0.0)

        self.scrub_label = ttk.Label(scrub_row, text="Position: 0m 00s (0%)", style="Card.TLabel", font=("Segoe UI", 9, "bold"), width=28, anchor="w")
        self.scrub_label.pack(side="left", padx=(0, 6))

        self.scrub_slider = ttk.Scale(scrub_row, from_=0, to=100, variable=self.scrub_pct, orient="horizontal", command=self.on_scrub_slide)
        self.scrub_slider.pack(side="left", fill="x", expand=True)

        # Hide summary panel initially until an audiobook source is loaded
        self.info_frame.pack_forget()

        # CARD 3: Target Playaway Drive
        drive_card = ttk.LabelFrame(main_container, text=" 3. Target Playaway USB Drive ", padding=12)
        drive_card.pack(fill="x", pady=6)

        drive_row = ttk.Frame(drive_card, style="Card.TFrame")
        drive_row.pack(fill="x")

        self.drive_combo = ttk.Combobox(drive_row, textvariable=self.selected_drive, state="readonly", font=("Segoe UI", 10))
        self.drive_combo.pack(side="left", fill="x", expand=True, padx=(0, 6))
        self.drive_combo.bind("<<ComboboxSelected>>", self.on_drive_selected)

        btn_refresh_drives = ttk.Button(drive_row, text="🔄 Refresh Drives", command=self.refresh_drives)
        btn_refresh_drives.pack(side="left", padx=(0, 5))

        self.btn_backup = ttk.Button(drive_row, text="📥 Backup Playaway", command=self.start_backup_thread)
        self.btn_backup.pack(side="left")

        # CARD 4: Flash Action & Console Log
        action_card = ttk.LabelFrame(main_container, text=" 4. Flash Operation & Output Console ", padding=12)
        action_card.pack(fill="x", pady=6)

        btn_row = ttk.Frame(action_card, style="Card.TFrame")
        btn_row.pack(fill="x", pady=(0, 6))

        self.btn_flash = ttk.Button(btn_row, text="⚡ Wipe & Flash Playaway", style="Accent.TButton", command=self.start_flash_thread)
        self.btn_flash.pack(side="left", fill="x", expand=True, padx=(0, 6))

        self.btn_export = ttk.Button(btn_row, text="📁 Export to Local Folder", style="TButton", command=self.start_export_thread)
        self.btn_export.pack(side="left", fill="x", expand=True, padx=(0, 6))

        self.btn_stop = ttk.Button(btn_row, text="🛑 Stop Operation", style="Danger.TButton", command=self.stop_operation, state="disabled")
        self.btn_stop.pack(side="left", fill="x", expand=False)

        self.progress_status_label = ttk.Label(action_card, text="Progress: Ready", style="Card.TLabel", font=("Segoe UI", 9, "bold"))
        self.progress_status_label.pack(anchor="w", pady=(2, 2))

        self.progress_bar = ttk.Progressbar(action_card, orient="horizontal", mode="determinate")
        self.progress_bar.pack(fill="x", pady=(0, 5))

        # Log Console (Compact 7 lines height with scrollbar)
        log_frame = ttk.Frame(action_card, style="Card.TFrame")
        log_frame.pack(fill="x", expand=True)

        self.log_text = tk.Text(log_frame, bg="#11111b", fg="#cdd6f4", insertbackground="white", font=("Consolas", 9), relief="flat", height=7)
        self.log_text.pack(side="left", fill="both", expand=True)

        scrollbar = ttk.Scrollbar(log_frame, orient="vertical", command=self.log_text.yview)
        scrollbar.pack(side="right", fill="y")
        self.log_text.configure(yscrollcommand=scrollbar.set)

        # TAB 2: HELP & USER GUIDE CONTAINER
        help_container = ttk.Frame(tab_help, style="Card.TFrame")
        help_container.pack(fill="both", expand=True, padx=5, pady=5)

        help_scroll = ttk.Scrollbar(help_container, orient="vertical")
        help_scroll.pack(side="right", fill="y")

        help_text_widget = tk.Text(
            help_container,
            bg="#11111b",
            fg="#cdd6f4",
            insertbackground="white",
            font=("Segoe UI", 10),
            relief="flat",
            wrap="word",
            yscrollcommand=help_scroll.set,
            padx=15,
            pady=15
        )
        help_text_widget.pack(side="left", fill="both", expand=True)
        help_scroll.config(command=help_text_widget.yview)

        help_content = """================================================================================
⚡ PLAYAWAY AUDIOBOOK STUDIO & FLASHER - USER GUIDE & SETTINGS REFERENCE
================================================================================

1. 📚 SUPPORTED AUDIOBOOK FORMATS & DIFFERENCES
--------------------------------------------------------------------------------
• .M4B (MPEG-4 Audiobook):
  The standard single-file audiobook format. Contains high-quality AAC audio,
  cover art metadata, and embedded chapter markers. The Studio can inspect M4B
  files and automatically split them into 1:1 tracks matching the original chapters!

• .MP3 (MPEG Layer 3):
  Universal audio format. Supported as a single long file or a folder of pre-split
  chapter files (e.g. 01.mp3, 02.mp3...). Some MP3 files also contain embedded ID3v2
  chapter frames, which are automatically detected.

• .M4A / .AAC (Advanced Audio Coding):
  Similar to M4B files but usually without embedded chapter markers. Fully supported for
  fixed-duration splitting (e.g., every 15 mins).

• .WAV / .FLAC (Uncompressed / Lossless):
  Highest possible source audio fidelity. Converted cleanly to Playaway AMR-WB+ mono.

• .OGG / .WMA / .OPUS:
  Fully supported input formats for conversion to Playaway AMR-WB+.

--------------------------------------------------------------------------------
2. ✂️ CHAPTER SPLITTING & EDITING SUITE
--------------------------------------------------------------------------------
• Split into fixed duration (minutes):
  Automatically splits long audiobooks (.m4b, .mp3, .flac) into clean 10, 15,
  or 30-minute chapter tracks. Best for single-file audiobooks.

• Split by M4B / MP3 Chapter Tags:
  Preserves embedded chapter titles and timestamps directly from your M4B or MP3 file.
  Creates 1:1 tracks matching the original book chapters.

• Keep tracks as-is (no splitting):
  Preserves existing file structures. Best when selecting a folder of pre-split MP3 files.

• ✂️ Split Chapter at Scrubber:
  Cut any selected chapter track into two separate sub-tracks at your scrubber slider
  position. Prompts for a custom name for Part 2 (pre-filled with Chapter ##_pt2).
  Perfect for isolating closing credits, bloopers, or publisher intros!

• 🗑️ Exclude / Include Track:
  Excludes selected tracks from encoding (marked ❌ Excluded in red). Total playtime,
  estimated size, and sequential PATWEAKS.DAT track numbering adjust dynamically.

• 🔄 Restore All Tracks:
  Instantly re-enables all excluded tracks across the audiobook.

• 🔁 Reset Chapters from Source:
  Re-parses and reloads the original chapter markers from the source file, clearing
  all custom splits and restoring the original track layout.

• Subchapter Mode (AF* Header):
  Adds the "AF*" signature to PATWEAKS.DAT, allowing compatible Playaway hardware with
  LCD screens (such as Playaway HD or learning models) to display nested subchapters.

--------------------------------------------------------------------------------
3. 🎬 LibVLC AUDIO PLAYER & TIME CONTROL
--------------------------------------------------------------------------------
• Embedded LibVLC Engine:
  High-performance python-vlc player supporting zero-latency audio playback,
  volume control, and pitch-preserved variable speed rate scaling (0.75x to 3.0x).

• ⏯️ Unified Play / Pause Toggle Button:
  Click ▶ Play to start or resume full chapter playback; toggles to ⏸ Pause while active.

• ⏱️ Millisecond-Accurate Position Scrubber:
  Drag or click the full-width timeline slider to seek instantly anywhere within
  the selected chapter track.

• 🔊 Volume Slider:
  Dedicated 160px volume slider (Volume: 0% to 100%) controlling playback output.

• 📊 Speed-Adjusted Dynamic Timeframes:
  Table columns (Timeframe & Length) automatically recalculate effective listening
  time and timestamps in real-time based on your configured Playback Speed.

--------------------------------------------------------------------------------
4. 🎚️ AUDIO QUALITY & PLAYBACK SPEED CONTROLS
--------------------------------------------------------------------------------
• Playback Speed (0.75x to 3.0x):
  Speeds up or slows down the audiobook prior to encoding using pitch-preserving
  DSP filters (atempo). Speeds like 1.25x, 1.5x, 2.0x, or 2.5x reduce file size proportionally.

• Preserve Voice Pitch Checkbox (atempo):
  - Checked (default): Uses FFmpeg pitch-preserving atempo filters so voices sound
    natural at 1.5x or 2.0x speed instead of sounding high-pitched.
  - Unchecked (Pitch Shift): Speeding up will naturally raise voice pitch.

• Encoding Bitrate (10 kbps to 36 kbps):
  Controls AMR-WB+ mono audio quality vs playtime storage:
    - 10-12 kbps : Standard Playaway quality (~23 hours playtime on 105MB flash)
    - 14-20 kbps : High voice fidelity (~12-16 hours playtime)
    - 24-36 kbps : Maximum voice quality (best for shorter audiobooks)

• ⚡ Auto-Fit Bitrate (Drive-Aware):
  Calculates the highest safe bitrate (between 10 & 36 kbps) to fill storage at peak quality based
  on your connected target USB drive capacity or standard ~105MB flash storage.

• 🔇 Add 5s End Silence Track Checkbox (final_chapter_silence):
  - Checked (default): Automatically appends a 5-second silent track (end_silence) to the end.
  - WHY THIS IS NECESSARY (Firmware Bug Workaround):
    On certain Playaway hardware models (such as Graphics units running Firmware 01:05), the SoC
    microcontroller has a firmware bug where it stops playback at the end of the final audio track,
    but FAILS to auto power off — leaving the screen on and draining the AAA battery.
    Adding a dedicated 5-second silence track at the end mitigates this bug: after playing the
    final silent track, the Playaway firmware powers off automatically and correctly!

• 💾 Save Settings & 🔄 Reset Defaults:
  Saves your preferred splitting mode, bitrate, speedup rate, pitch preference, subchapter mode,
  and end silence preference to playaway_config.json for automatic loading on next startup.

--------------------------------------------------------------------------------
5. 🛡️ TARGET DRIVE SELECTION & SAFETY PROTECTION
--------------------------------------------------------------------------------
• Blank Target Default:
  Target drive starts blank so you must actively pick a drive or export folder.

• System Drive Block (C:\\):
  Strictly blocks selection of the C:\\ OS drive to prevent accidental wiping.

• 2GB Size Limit Block:
  Real Playaway hardware flash chips are <= 2GB (128MB, 256MB, 512MB, 1GB).
  Large external HDDs, SSDs, and main hard drives (> 2048 MB) are blocked.

• 📥 Backup Playaway:
  Saves all original .awb tracks, PATWEAKS.DAT headers, and bookmark files from
  your connected player to your computer before flashing.

--------------------------------------------------------------------------------
6. ⚡ FLASHING VS. 📁 EXPORTING
--------------------------------------------------------------------------------
• ⚡ Wipe & Flash Playaway:
  Automatically purges ALL old files from your Playaway player before writing new audio:
    - Deletes old .awb audio tracks and PATWEAKS.DAT.
    - Deletes factory CMI_CRC.DAT (prevents boot CRC check failures on custom books).
    - Deletes .SAV / .DAT bookmark state files.
    - Purges hidden OS junk files (.DS_Store, desktop.ini, System Volume Information, ._*)
      so the FAT table reading order remains clean for the embedded microcontroller.
    - Writes new AMR-WB+ audio tracks + PATWEAKS.DAT and flushes OS volume buffers.

  *NOTE ON PLAYAWAY OPERATING SYSTEM*:
  Playaway's operating system (firmware kernel) resides on a read-only internal ROM chip
  inside the SoC microcontroller itself — NOT on the USB flash storage volume.
  Wiping the USB drive ONLY cleans audio files and OS junk; it will NEVER delete the
  Playaway's firmware or brick the hardware player!

• 📁 Export to Local Folder:
  Generates .awb audio files, PATWEAKS.DAT, and a step-by-step README_HOW_TO_COPY.txt
  guide into a folder on your computer for manual copying.

--------------------------------------------------------------------------------
7. 🔌 HARDWARE SOLDERING GUIDE
--------------------------------------------------------------------------------
Playaway players have internal PCB test pads intended for factory programming.
Solder 4 connections from a USB cable or USB-C breakout board to the PCB test pads:
  1. VBUS (+5V) -> 5V / VBUS test pad
  2. D- (Data Minus) -> D- test pad
  3. D+ (Data Plus) -> D+ test pad
  4. GND (Ground) -> GND / - test pad

Note: Keep a fresh AAA battery inside the unit while flashing/using, as some SoC chip
revisions require battery power to boot.

--------------------------------------------------------------------------------
8. 🔢 TRACK LIMITS & PERFORMANCE
--------------------------------------------------------------------------------
• Track Limits:
  Playaway firmware supports up to 999 tracks (NMD999 in PATWEAKS.DAT).

• 🚀 Multi-Threaded Encoding Engine:
  Encodes multiple audio tracks simultaneously in parallel (4x-8x speedup using all CPU cores).

• 🛑 Stop Operation:
  Instantly cancels active encoding or flashing operations with a single click.

--------------------------------------------------------------------------------
9. 🐛 HARDWARE FIRMWARE GOTCHAS & SOLUTIONS
--------------------------------------------------------------------------------
• Firmware 01:03 (~88 Min Single-Track Freeze Bug):
  - Bug: On older Graphics models running Firmware 01:03, playing a single track longer than
    1 hour 28 minutes (88 mins) freezes playback at 1h28m and fails to auto power off.
  - Fix: Select 'Split into fixed duration (minutes)' set to 15, 30, or 60 mins! Splitting into
    15-60 min tracks bypasses the 88-minute limit while allowing seamless continuous playback.

• Firmware 01:05 (Auto Power-Off Bug):
  - Bug: On Graphics models running Firmware 01:05, playing to the end of a single track completes
    audio playback but fails to issue the power-down interrupt, leaving the LCD screen on.
  - Fix: Keep 'Add 5s End Silence Track' checked! The 5-second final silent track triggers
    the hardware power-off routine cleanly.

• 🔍 How to Check Your Playaway Firmware Version:
  1. On-Screen Button Combination (LCD Models):
     - Turn off the player. Press and hold 'SPD' (Speed) or '<<' (Reverse) while pressing 'POWER'.
     - Or hold 'POWER' + 'PLAY' for 3 seconds on startup.
     - The LCD display will briefly show the version code (e.g. '01:03' or '01:05').
  2. Battery Compartment Sticker:
     - Remove the AAA battery door and inspect the white barcode/model sticker inside the bay.
================================================================================
"""
        help_text_widget.insert("1.0", help_content)
        help_text_widget.config(state="disabled")

    def log(self, msg):
        """Append message to console log."""
        clean_msg = str(msg).replace("[▶️]", "[▶]").replace("▶️", "▶").replace("⏸️", "⏸").replace("⏹️", "⏹")
        self.log_text.insert("end", f"{clean_msg}\n")
        self.log_text.see("end")

    def check_encoder_status(self):
        enc, dll = find_encoder()
        if enc and dll:
            self.encoder_status_label.config(text="Encoder: Ready ✓", foreground="#a6e3a1")
        else:
            self.encoder_status_label.config(text="Encoder: Missing (Auto-downloading...)", foreground="#f9e2af")
            threading.Thread(target=self.async_setup_encoder, daemon=True).start()

    def async_setup_encoder(self):
        enc, dll = setup_encoder()
        if enc and dll:
            self.encoder_status_label.config(text="Encoder: Ready ✓", foreground="#a6e3a1")
            self.log("[+] 3GPP AMR-WB+ encoder ready.")
        else:
            self.encoder_status_label.config(text="Encoder: Not Found ✗", foreground="#f38ba8")
            self.log("[!] 3GPP encoder missing. Place encoder.exe into tools/")

    def browse_file(self):
        path = filedialog.askopenfilename(
            title="Select Audiobook File",
            filetypes=[("Audio Files", "*.mp3 *.m4b *.m4a *.wav *.flac *.aac *.ogg *.wma"), ("All Files", "*.*")]
        )
        if path:
            self.input_path.set(path)
            self.analyze_source()

    def browse_folder(self):
        path = filedialog.askdirectory(title="Select Folder Containing Audiobook Tracks")
        if path:
            self.input_path.set(path)
            self.analyze_source()

    def analyze_source(self):
        p = self.input_path.get()
        if not p or not Path(p).exists():
            return

        try:
            self.log(f"Analyzing audio source: {p}...")
            self.audio_info = inspect_audio_source(p)
            dur_str = self.audio_info["total_duration_formatted"]
            num_files = len(self.audio_info["files"])
            title = self.audio_info["title"]
            self.book_title.set(title)

            self.info_label.config(
                text=f"Loaded: '{title}' | Files: {num_files} | Total Duration: {dur_str}",
                foreground="#a6e3a1"
            )
            self.update_estimates()
        except Exception as e:
            self.info_label.config(text=f"Error reading audio source: {e}", foreground="#f38ba8")
            self.log(f"[!] Error inspecting audio: {e}")

    def on_speed_changed(self, event=None):
        val_str = self.speed_combo.get().replace("x", "").replace(" (Normal)", "").strip()
        try:
            speed_val = float(val_str)
            self.playback_speed.set(speed_val)
        except ValueError:
            self.playback_speed.set(1.0)
        self.update_estimates()

    def on_silence_toggle(self):
        self.save_current_settings(quiet=True)
        self.update_estimates(replan=True)

    def update_bitrate_label(self):
        kbps = self.bitrate_kbps.get()
        free_mb = 105.0
        sel_drive_str = self.selected_drive.get()
        if sel_drive_str and not sel_drive_str.startswith("--"):
            drive_path = sel_drive_str.split()[0]
            matching_d = next((d for d in self.drives if d['path'] == drive_path), None)
            if matching_d:
                free_mb = matching_d['free_mb']

        total_bits = free_mb * 1024 * 1024 * 8
        hrs = round(total_bits / (kbps * 1000 * 3600), 1)
        mode_tag = " (Auto-Fit)" if getattr(self, "bitrate_is_auto", tk.BooleanVar(value=True)).get() else " (Manual)"
        self.bitrate_label.config(text=f"Bitrate: {kbps} kbps{mode_tag} (Max ~{hrs} hrs on {int(free_mb)}MB capacity)")

    def on_bitrate_slide(self, val):
        self.bitrate_is_auto.set(False)  # User manually adjusted slider!
        kbps = int(float(val))
        self.bitrate_kbps.set(kbps)
        self.update_bitrate_label()
        self.update_estimates()

    def on_split_mins_changed(self, *args):
        """Handle focus out / edits to the fixed chapter split minutes spinbox and refresh the chapter table."""
        if not self.audio_info:
            return
        try:
            raw = self.sp_mins.get().strip() if hasattr(self, "sp_mins") else str(self.split_mins.get())
            if not raw:
                return
            val = int(raw)
            if val <= 0:
                val = 15
            val = max(1, min(360, val))
            self.split_mins.set(val)
        except Exception:
            try:
                val = max(1, min(360, int(self.split_mins.get())))
                self.split_mins.set(val)
            except Exception:
                return

        # Ensure duration splitting mode is active
        if self.split_mode.get() != "duration":
            self.split_mode.set("duration")

        self.update_estimates(replan=True)

    def on_drive_selected(self, event=None):
        self.update_estimates()

    def update_estimates(self, replan=True):
        if not self.audio_info:
            return

        if replan or not self.planned_segments:
            # Preserve existing excluded states if replanning
            excluded_map = {}
            if self.planned_segments:
                for s in self.planned_segments:
                    key = (s.get("file"), s.get("start"), s.get("end"))
                    excluded_map[key] = s.get("excluded", False)

            mode = self.split_mode.get()
            has_chapters = bool(self.audio_info and self.audio_info.get("files") and self.audio_info["files"][0].get("chapters"))
            if mode == "chapters" and not has_chapters:
                self.split_mode.set("duration")
                mode = "duration"

            self.planned_segments = plan_chapters(
                input_path=self.input_path.get(),
                split_mode=mode,
                split_mins=self.split_mins.get(),
                title=self.book_title.get(),
                subchapter_mode=self.subchapter_mode.get(),
                final_chapter_silence=self.final_chapter_silence.get()
            )

            # Re-apply excluded states to matching segments
            for s in self.planned_segments:
                key = (s.get("file"), s.get("start"), s.get("end"))
                if key in excluded_map:
                    s["excluded"] = excluded_map[key]

        # Active vs total tracks & active duration
        active_segments = [s for s in self.planned_segments if not s.get("excluded", False)]
        active_dur_sec = sum(s.get("duration", 0.0) for s in active_segments)

        # Auto-calculate bitrate if Auto-Fit mode is enabled
        if getattr(self, "bitrate_is_auto", tk.BooleanVar(value=True)).get() and active_dur_sec > 0:
            free_mb = 105.0
            sel_drive_str = self.selected_drive.get()
            if sel_drive_str and not sel_drive_str.startswith("--"):
                drive_path = sel_drive_str.split()[0]
                matching_d = next((d for d in self.drives if d['path'] == drive_path), None)
                if matching_d:
                    free_mb = matching_d['free_mb']
            spd = self.playback_speed.get()
            auto_kbps = calculate_autofit_bitrate(active_dur_sec, target_free_mb=free_mb, speed=spd)
            self.bitrate_kbps.set(auto_kbps)

        self.update_bitrate_label()
        
        kbps = self.bitrate_kbps.get()
        spd = self.playback_speed.get()
        est_mb = estimate_bitrate_size(active_dur_sec, kbps, speed=spd)

        num_tracks = len(active_segments)
        ex_count = len(self.planned_segments) - num_tracks
        ex_suffix = f" ({ex_count} cut)" if ex_count > 0 else ""

        # Capacity check threshold
        free_mb = 105.0
        sel_drive_str = self.selected_drive.get()
        has_drive_selected = False
        if sel_drive_str and not sel_drive_str.startswith("--"):
            has_drive_selected = True
            drive_path = sel_drive_str.split()[0]
            matching_d = next((d for d in self.drives if d['path'] == drive_path), None)
            if matching_d:
                free_mb = matching_d['free_mb']

        if num_tracks > 999:
            self.estimate_label.config(
                text=f"Active Tracks: {num_tracks}{ex_suffix} | Estimated Size: ~{est_mb} MB\n⚠️ EXCEEDS FIRMWARE TRACK LIMIT! (Max 999 Tracks)",
                foreground="#f38ba8",
                justify="left"
            )
            self.btn_flash.config(state="disabled")
            if has_drive_selected:
                self.progress_status_label.config(text="⚠️ Flash Disabled: Playaway hardware supports a maximum of 999 tracks.")
        elif est_mb > free_mb:
            # EXCEEDS CAPACITY WARNING: Change text to RED & disable Wipe & Flash
            suggestions = (
                f"Active Tracks: {num_tracks}{ex_suffix} | Estimated Size: ~{est_mb} MB\n"
                f"⚠️ EXCEEDS CAPACITY! (Max: {int(free_mb)} MB)\n"
                f"💡 Options to reduce size:\n"
                f"  • Click ⚡ Auto-Fit Bitrate to lower encoding bitrate\n"
                f"  • Increase Playback Speed (e.g. 1.25x or 1.5x)\n"
                f"  • Exclude unwanted tracks (credits, intro)"
            )
            self.estimate_label.config(
                text=suggestions,
                foreground="#f38ba8",
                justify="left"
            )
            self.btn_flash.config(state="disabled")
            if has_drive_selected:
                self.progress_status_label.config(text="⚠️ Flash Disabled: Size exceeds capacity. Lower bitrate/increase speed or cut tracks.")
        else:
            # SAFE CAPACITY: Check if any single track exceeds 85 mins (Firmware 01:03 limit)
            has_long_track = any(s.get("duration", 0.0) > 5100.0 for s in active_segments if not s.get("is_silence", False))
            warn_str = "\n💡 Tip: Single track > 1h28m detected! Split into 15-60 min tracks to prevent Firmware 01:03 freeze." if has_long_track else ""

            self.estimate_label.config(
                text=f"Active Tracks: {num_tracks}{ex_suffix} | Estimated Size: ~{est_mb} MB (at {spd}x speed){warn_str}",
                foreground="#f9e2af" if has_long_track else "#a6e3a1"
            )
            # Re-enable flash button if target drive selected and operation not running
            if has_drive_selected:
                if not self.cancel_event.is_set():
                    self.btn_flash.config(state="normal")
                self.progress_status_label.config(text="Progress: Target USB Drive Selected — Ready to Flash!")
            else:
                self.btn_flash.config(state="disabled")
                self.progress_status_label.config(text="Progress: Ready (Select a Target USB Drive in Section 3 to Flash, or click Export to Local Folder)")

        self.update_chapter_info_panel()

    def update_chapter_info_panel(self):
        """Update stats label, auto-size columns dynamically, and refresh chapter list treeview preview while preserving track selection."""
        if not self.audio_info or not self.planned_segments:
            if hasattr(self, "info_frame"):
                self.info_frame.pack_forget()
            self.stats_label.config(text="No audiobook loaded.")
            return

        if hasattr(self, "info_frame") and not self.info_frame.winfo_ismapped():
            self.info_frame.pack(fill="x", expand=True, pady=(8, 0))

        # Preserve active track selection before clearing table
        prev_sel = self.chapter_tree.selection()
        saved_idx = int(prev_sel[0]) if prev_sel else 0

        for item in self.chapter_tree.get_children():
            self.chapter_tree.delete(item)

        active_segments = [s for s in self.planned_segments if not s.get("excluded", False)]
        excluded_count = len(self.planned_segments) - len(active_segments)

        active_dur_sec = sum(s.get("duration", 0.0) for s in active_segments)
        orig_dur_str = format_duration(active_dur_sec)
        spd = self.playback_speed.get()
        effective_dur_sec = active_dur_sec / max(0.25, spd)
        eff_dur_str = format_duration(effective_dur_sec)
        num_tracks = len(active_segments)

        if active_segments:
            first_seg = active_segments[0]
            last_seg = active_segments[-1]
            start_time = format_duration(first_seg.get("start", 0.0) / max(0.25, spd))
            end_time = format_duration(last_seg.get("end", 0.0) / max(0.25, spd))
            range_str = f"{start_time} -> {end_time}"
        else:
            range_str = "N/A (All tracks excluded)"

        ex_str = f" ({excluded_count} excluded)" if excluded_count > 0 else ""
        stats_str = f"Active Tracks: {num_tracks}{ex_str} | Original: {orig_dur_str} | Actual: {eff_dur_str} @ {spd}x"
        self.stats_label.config(text=stats_str)

        # Check for tracks exceeding 88 minutes (Firmware 01:03 freeze limit)
        long_warnings = check_track_duration_warnings(self.planned_segments, speed=spd)
        if long_warnings:
            warn_count = len(long_warnings)
            if warn_count == 1:
                first_w = long_warnings[0]
                warn_msg = f"⚠️ WARNING: Track #{first_w['index']} is {first_w['effective_mins']}m (>88m)! Firmware 01:03 devices will freeze. Use '✂️ Split Chapter' or switch Split Mode."
            else:
                warn_msg = f"⚠️ WARNING: {warn_count} tracks exceed 88 mins (Firmware 01:03 freeze limit)! Use '✂️ Split Chapter' or switch Split Mode to fixed 15-60m."
            self.chapter_warning_label.config(text=warn_msg)
            if not self.chapter_warning_label.winfo_ismapped():
                self.chapter_warning_label.pack(anchor="w", pady=(0, 4))
        else:
            self.chapter_warning_label.config(text="")
            if self.chapter_warning_label.winfo_ismapped():
                self.chapter_warning_label.pack_forget()

        # Measure column character lengths for auto-sizing
        col_max_chars = {
            "index": len("#"),
            "title": len("Track Title"),
            "timeframe": len("Timeframe"),
            "length": len("Length"),
            "status": len("Status")
        }

        for idx, seg in enumerate(self.planned_segments, 1):
            raw_title = seg.get("title", "").strip()
            if not raw_title or (raw_title.isdigit() and int(raw_title) == idx):
                t_title = f"Chapter {idx}"
            else:
                t_title = raw_title

            is_silence = seg.get("is_silence", False) or seg.get("file") == "__SILENCE__"
            is_excluded = seg.get("excluded", False)

            if is_silence:
                eff_dur_sec = 5.0
                timeframe_str = "0m 00s -> 0m 05s"
                length_str = "5s"
                row_tag = "active"
            else:
                # Calculate speed-adjusted effective durations and timestamps
                eff_dur_sec = seg.get("duration", 0.0) / max(0.25, spd)
                eff_start_sec = seg.get("start", 0.0) / max(0.25, spd)
                eff_end_sec = seg.get("end", 0.0) / max(0.25, spd)

                dur_m = round(eff_dur_sec / 60.0, 1)
                t_start = format_duration(eff_start_sec)
                t_end = format_duration(eff_end_sec)
                timeframe_str = f"{t_start} -> {t_end}"

                if dur_m > MAX_SAFE_TRACK_MINS and not is_excluded:
                    length_str = f"⚠️ {dur_m}m"
                    row_tag = "warning"
                else:
                    length_str = f"{dur_m}m"
                    row_tag = "excluded" if is_excluded else "active"

            sub_tag = "[AF*] " if self.subchapter_mode.get() else ""
            full_title = f"{sub_tag}{t_title}"
            
            status_str = "❌ Excluded" if is_excluded else "✓ Active"

            # Track character counts for auto-fit column width calculation
            idx_str = f"{idx:03d}"
            col_max_chars["index"] = max(col_max_chars["index"], len(idx_str))
            col_max_chars["title"] = max(col_max_chars["title"], len(full_title))
            col_max_chars["timeframe"] = max(col_max_chars["timeframe"], len(timeframe_str))
            col_max_chars["length"] = max(col_max_chars["length"], len(length_str))
            col_max_chars["status"] = max(col_max_chars["status"], len(status_str))

            self.chapter_tree.insert(
                "",
                "end",
                iid=str(idx - 1),
                values=(idx_str, full_title, timeframe_str, length_str, status_str),
                tags=(row_tag,)
            )

        self.chapter_tree.tag_configure("excluded", foreground="#f38ba8")
        self.chapter_tree.tag_configure("active", foreground="#cdd6f4")
        self.chapter_tree.tag_configure("warning", foreground="#fab387")

        # Auto-size Treeview Columns dynamically based on content lengths
        min_col_widths = {"index": 45, "title": 160, "timeframe": 220, "length": 85, "status": 80}
        char_multipliers = {"index": 8, "title": 8, "timeframe": 8, "length": 9, "status": 9}
        padding_map = {"index": 20, "title": 30, "timeframe": 30, "length": 25, "status": 25}

        for col, max_c in col_max_chars.items():
            calc_w = max(min_col_widths[col], max_c * char_multipliers[col] + padding_map[col])
            self.chapter_tree.column(col, width=calc_w)

        # Restore saved track selection (or default to 1st track if valid)
        if self.planned_segments:
            target_idx = min(saved_idx, len(self.planned_segments) - 1)
            self.chapter_tree.selection_set(str(target_idx))
            self.chapter_tree.see(str(target_idx))

    def restore_all_tracks(self):
        """Re-enable (include) all excluded tracks in the planned segments list."""
        if not self.planned_segments:
            return

        for s in self.planned_segments:
            s["excluded"] = False

        self.update_estimates(replan=False)
        self.log("[🔄] Re-enabled all excluded tracks in list.")

    def reset_chapters_from_source(self):
        """Re-parse and reload original chapter markers and track layout from source file."""
        if not self.audio_info:
            return

        if messagebox.askyesno("Reset Chapters", "Are you sure you want to reset all custom chapter splits and re-enable all excluded tracks back to original source file markers?"):
            self.stop_audio_preview(log_msg=False)
            self.planned_segments = None
            self.update_estimates(replan=True)
            self.scrub_pct.set(0.0)
            self.log("[🔁] Reset chapter splits and reloaded original track markers from source.")

    def split_selected_chapter(self):
        """Split selected chapter track into two separate tracks at current scrubber slider position."""
        sel = self.chapter_tree.selection()
        if not sel:
            messagebox.showinfo("Split Chapter", "Please select a chapter from the table to split.")
            return

        idx = int(sel[0])
        seg = self.planned_segments[idx]
        seg_start = seg.get("start", 0.0)
        seg_dur = seg.get("duration", 0.0)
        seg_end = seg.get("end", seg_start + seg_dur)

        pct = self.scrub_pct.get()
        scrub_offset = (pct / 100.0) * seg_dur

        # Validation: scrub_offset must be at least 2 seconds from start/end
        if scrub_offset < 2.0 or scrub_offset > (seg_dur - 2.0):
            messagebox.showwarning(
                "Invalid Split Position",
                "Please position the scrubber slider inside the track where you want to split (at least 2s away from start/end)."
            )
            return

        # Halt audio playback while splitting
        self.stop_audio_preview(log_msg=False)

        orig_title = seg.get("title", f"Track {idx + 1}").strip()
        if not orig_title or (orig_title.isdigit() and int(orig_title) == (idx + 1)):
            default_base = f"Chapter {idx + 1}"
        else:
            default_base = orig_title

        part1_title = f"{default_base}_pt1"
        default_part2_title = f"{default_base}_pt2"

        # Ask user for part 2 name
        new_name = simpledialog.askstring(
            "Split Chapter",
            f"Splitting '{default_base}' at {format_duration(scrub_offset)}.\n\nEnter name for the new second segment (Part 2):",
            initialvalue=default_part2_title,
            parent=self
        )

        if new_name is None:  # User cancelled dialog
            return

        part2_title = new_name.strip() if new_name.strip() else default_part2_title
        split_point = seg_start + scrub_offset

        part1_seg = {
            "file": seg["file"],
            "start": seg_start,
            "duration": scrub_offset,
            "end": split_point,
            "title": part1_title,
            "excluded": seg.get("excluded", False)
        }

        part2_seg = {
            "file": seg["file"],
            "start": split_point,
            "duration": seg_dur - scrub_offset,
            "end": seg_end,
            "title": part2_title,
            "excluded": False
        }

        # Replace segment with part1 and part2
        self.planned_segments[idx:idx+1] = [part1_seg, part2_seg]

        # Refresh UI table & re-select newly created Part 2 row
        self.update_estimates(replan=False)
        self.chapter_tree.selection_set(str(idx + 1))
        self.chapter_tree.see(str(idx + 1))
        self.scrub_pct.set(0.0)

        self.log(f"[✂️] Split Track #{idx+1} at {format_duration(scrub_offset)} into '{part1_title}' and '{part2_title}'.")

    def on_tree_select(self, event=None):
        """Reset scrub slider when selecting a new chapter row."""
        self.stop_audio_preview(log_msg=False)
        self.scrub_pct.set(0.0)
        self.on_scrub_slide(0.0)

    def on_scrub_slide(self, val):
        """Update scrub position label in H:MM:SS format and seek live if audio is currently playing."""
        pct = float(val)
        sel = self.chapter_tree.selection()
        if not sel or not self.planned_segments:
            self.scrub_label.config(text=f"Position: 0m 00s ({int(pct)}%)")
            return

        idx = int(sel[0])
        seg = self.planned_segments[idx]
        seg_dur = seg.get("duration", 0.0)
        offset_sec = (pct / 100.0) * seg_dur
        time_str = format_duration(offset_sec)
        spd = self.playback_speed.get()
        
        status_icon = "▶" if getattr(self, "is_playing", False) else ("⏸" if getattr(self, "is_paused", False) else "⏱")
        self.scrub_label.config(text=f"{status_icon} {time_str} / {format_duration(seg_dur)} ({int(pct)}% @ {spd}x)")

        # Live Scrub Seeking: Dragging slider while audio is playing immediately seeks playback
        if getattr(self, "is_playing", False):
            if self.vlc_player:
                try:
                    seg_start = seg.get("start", 0.0)
                    target_time_sec = seg_start + offset_sec
                    target_ms = int(target_time_sec * 1000)
                    self.vlc_player.set_time(target_ms)
                    self.player_scrub_offset = offset_sec
                    self.player_start_wall_time = time.time()
                except Exception as e:
                    print(f"VLC seek error: {e}")
            else:
                now = time.time()
                if not hasattr(self, "last_seek_time") or (now - self.last_seek_time > 0.35):
                    self.last_seek_time = now
                    self.preview_selected_track(is_seek=True)

    def toggle_play_pause(self):
        """Toggle audio preview playback between Play and Pause states."""
        if getattr(self, "is_playing", False) and not getattr(self, "is_paused", False):
            self.pause_audio_preview()
        else:
            self.preview_selected_track()

    def preview_selected_track(self, is_seek=False):
        """Play an audio preview sample of the selected track starting from scrub position at user's configured speed using LibVLC (with ffplay fallback)."""
        sel = self.chapter_tree.selection()
        if not sel:
            messagebox.showinfo("Preview Track", "Please select a chapter from the list to preview.")
            return

        idx = int(sel[0])
        seg = self.planned_segments[idx]
        file_path = seg["file"]

        if seg.get("is_silence", False) or file_path == "__SILENCE__":
            messagebox.showinfo("Preview Track", "This is the 5.0s dedicated 'end_silence' track.")
            return

        seg_start = seg["start"]
        seg_dur = seg["duration"]

        pct = self.scrub_pct.get()
        scrub_offset = (pct / 100.0) * seg_dur
        sample_start = seg_start + scrub_offset

        sample_len = max(1.0, seg_dur - scrub_offset)
        start_time_str = format_duration(scrub_offset)
        spd = self.playback_speed.get()

        if self.vlc_player:
            # LibVLC Native Player Engine
            if getattr(self, "is_paused", False) and not is_seek:
                self.is_paused = False
                self.is_playing = True
                self.vlc_player.play()
                if hasattr(self, "btn_preview"):
                    self.btn_preview.config(text="⏸ Pause")
                self.tick_player_progress()
                return

            self.stop_audio_preview(log_msg=False)

            try:
                media = self.vlc_instance.media_new(file_path)
                media.add_option(f":start-time={sample_start:.3f}")
                media.add_option(f":stop-time={(sample_start + sample_len):.3f}")
                self.vlc_player.set_media(media)
                self.vlc_player.play()

                # Set playback rate in LibVLC (0.25x to 4.0x)
                self.vlc_player.set_rate(float(spd))

                self.is_playing = True
                self.is_paused = False
                self.player_seg_dur = seg_dur
                self.player_scrub_offset = scrub_offset
                self.player_sample_len = sample_len
                self.player_start_wall_time = time.time()
                self.player_speed = spd

                if hasattr(self, "btn_preview"):
                    self.btn_preview.config(text="⏸ Pause")

                self.tick_player_progress()
                return

            except Exception as e:
                self.log(f"[!] LibVLC engine warning: {e}. Falling back to ffplay.")

        # Fallback to ffplay engine if LibVLC is not present
        if getattr(self, "is_paused", False) and not is_seek:
            self.is_paused = False
            self.preview_selected_track(is_seek=True)
            return

        self.stop_audio_preview(log_msg=False)
        filter_str = build_atempo_filter(spd)

        self.is_playing = True
        self.is_paused = False
        self.player_seg_dur = seg_dur
        self.player_scrub_offset = scrub_offset
        self.player_sample_len = sample_len
        self.player_start_wall_time = time.time()
        self.player_speed = spd

        if hasattr(self, "btn_preview"):
            self.btn_preview.config(text="⏸ Pause")

        def run_ffplay():
            try:
                ff_play_dur = sample_len / max(0.1, spd)
                cmd = [
                    "ffplay",
                    "-nodisp",
                    "-autoexit",
                    "-ss", str(sample_start),
                    "-t", str(ff_play_dur),
                ]
                if filter_str:
                    cmd.extend(["-af", filter_str])
                cmd.extend(["-i", str(file_path)])

                creationflags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
                self.preview_process = subprocess.Popen(cmd, creationflags=creationflags, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                self.preview_process.wait()
            except Exception as e:
                self.log(f"[!] Audio preview playback error: {e}")
            finally:
                self.is_playing = False
                if hasattr(self, "btn_preview"):
                    self.btn_preview.config(text="▶ Play")

        threading.Thread(target=run_ffplay, daemon=True).start()
        self.tick_player_progress()

    def tick_player_progress(self):
        """Update live scrubber slider position and timestamp display second-by-second while audio is playing."""
        if not getattr(self, "is_playing", False) or getattr(self, "is_paused", False):
            return

        if not hasattr(self, "player_start_wall_time") or getattr(self, "player_seg_dur", 0.0) <= 0:
            return

        # Check LibVLC native state if active
        if self.vlc_player:
            try:
                vlc_state = self.vlc_player.get_state()
                if vlc_state in (vlc.State.Ended, vlc.State.Stopped, vlc.State.Error):
                    self.stop_audio_preview(log_msg=False)
                    self.scrub_pct.set(100.0)
                    self.scrub_label.config(text=f"⏹ Stopped: {format_duration(self.player_seg_dur)}")
                    return
            except Exception:
                pass

        elapsed_wall = time.time() - self.player_start_wall_time
        elapsed_audio = elapsed_wall * self.player_speed

        curr_offset = self.player_scrub_offset + elapsed_audio
        if curr_offset >= self.player_seg_dur or elapsed_audio >= self.player_sample_len:
            # HARD STOP THE PLAYBACK ENGINE IMMEDIATELY
            self.stop_audio_preview(log_msg=False)
            self.scrub_pct.set(100.0)
            self.scrub_label.config(text=f"⏹ Stopped: {format_duration(self.player_seg_dur)}")
            return

        pct = (curr_offset / self.player_seg_dur) * 100.0
        self.scrub_pct.set(pct)
        time_str = format_duration(curr_offset)
        total_str = format_duration(self.player_seg_dur)
        self.scrub_label.config(text=f"▶ {time_str} / {total_str} ({int(pct)}% @ {self.player_speed}x)")

        self.after(200, self.tick_player_progress)

    def pause_audio_preview(self):
        """Pause or unpause active audio preview playback via LibVLC or fallback."""
        if self.vlc_player and self.vlc_player.is_playing():
            self.is_paused = True
            self.is_playing = False
            self.vlc_player.pause()
            if hasattr(self, "btn_preview"):
                self.btn_preview.config(text="▶ Play")
            curr_sec = (self.scrub_pct.get() / 100.0) * getattr(self, "player_seg_dur", 0.0)
            self.scrub_label.config(text=f"⏸ Paused: {format_duration(curr_sec)}")
            return
        elif self.vlc_player and getattr(self, "is_paused", False):
            self.is_paused = False
            self.is_playing = True
            self.vlc_player.play()
            if hasattr(self, "btn_preview"):
                self.btn_preview.config(text="⏸ Pause")
            self.tick_player_progress()
            return

        if getattr(self, "is_paused", False):
            self.is_paused = False
            if hasattr(self, "btn_preview"):
                self.btn_preview.config(text="⏸ Pause")
            self.preview_selected_track(is_seek=True)
        elif getattr(self, "is_playing", False):
            self.is_paused = True
            self.is_playing = False
            if hasattr(self, "btn_preview"):
                self.btn_preview.config(text="▶ Play")
            if hasattr(self, "preview_process") and self.preview_process:
                try:
                    self.preview_process.terminate()
                    self.preview_process = None
                except Exception:
                    pass
            if sys.platform == "win32":
                try:
                    subprocess.run(["taskkill", "/f", "/im", "ffplay.exe"], creationflags=subprocess.CREATE_NO_WINDOW, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                except Exception:
                    pass
            curr_sec = (self.scrub_pct.get() / 100.0) * getattr(self, "player_seg_dur", 0.0)
            self.scrub_label.config(text=f"⏸ Paused: {format_duration(curr_sec)}")

    def stop_audio_preview(self, log_msg=True):
        """Halt active audio preview playback immediately."""
        self.is_playing = False
        self.is_paused = False

        if hasattr(self, "btn_preview"):
            self.btn_preview.config(text="▶ Play")

        if self.vlc_player:
            try:
                self.vlc_player.stop()
            except Exception:
                pass

        if hasattr(self, "preview_process") and self.preview_process:
            try:
                self.preview_process.terminate()
                self.preview_process = None
            except Exception:
                pass

        if sys.platform == "win32":
            try:
                subprocess.run(["taskkill", "/f", "/im", "ffplay.exe"], creationflags=subprocess.CREATE_NO_WINDOW, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            except Exception:
                pass

    def toggle_exclude_selected_track(self):
        """Toggle excluded state for all selected tracks in the list."""
        sel = self.chapter_tree.selection()
        if not sel:
            messagebox.showinfo("Exclude Track", "Please select one or more chapters from the list to exclude/include.")
            return

        for item in sel:
            idx = int(item)
            curr = self.planned_segments[idx].get("excluded", False)
            self.planned_segments[idx]["excluded"] = not curr
            action = "Excluded" if not curr else "Restored"
            self.log(f"[✂️] Track #{idx+1} ({self.planned_segments[idx].get('title', 'Chapter')}) marked as {action}.")

        self.update_estimates(replan=False)

    def restore_all_tracks(self):
        """Restore all excluded tracks back to active status."""
        for seg in self.planned_segments:
            seg["excluded"] = False
        self.log("[🔄] All excluded tracks restored to active status.")
        self.update_estimates(replan=False)

    def refresh_drives(self):
        self.log("Scanning for connected Playaway USB drives...")
        self.drives = detect_playaway_drives(allow_large_drives=False)
        options = ["-- Select Target USB Drive --"]

        for d in self.drives:
            tag = " [PLAYAWAY DETECTED]" if d["is_playaway"] else ""
            opt_str = f"{d['path']} ({d['label']}) - {d['free_mb']}MB free / {d['total_mb']}MB total{tag}"
            options.append(opt_str)

        if len(options) == 1:
            options = ["-- No Playaway USB drives detected (<=2GB) --"]

        self.drive_combo["values"] = options
        self.selected_drive.set("")  # BLANK BY DEFAULT PER USER REQUEST

    def save_current_settings(self, quiet=False):
        """Save current GUI tweaks & preferences to playaway_config.json."""
        cfg = {
            "split_mode": self.split_mode.get(),
            "split_mins": self.split_mins.get(),
            "subchapter_mode": self.subchapter_mode.get(),
            "playback_speed": self.playback_speed.get(),
            "preserve_pitch": self.preserve_pitch.get(),
            "final_chapter_silence": self.final_chapter_silence.get(),
            "bitrate_kbps": "auto" if self.bitrate_is_auto.get() else self.bitrate_kbps.get()
        }
        saved_path = save_config(cfg)
        if not quiet:
            self.log(f"[+] Preferences saved to: {saved_path}")
            messagebox.showinfo(
                "Settings Saved",
                f"Your custom audiobook tweaks & quality preferences have been saved to:\n\n{saved_path}\n\n"
                "These preferences will automatically load whenever you open the app or run CLI commands!"
            )

    def load_saved_settings(self):
        """Load saved preferences from playaway_config.json into GUI controls."""
        cfg = load_config()
        self.split_mode.set(cfg.get("split_mode", DEFAULT_SETTINGS["split_mode"]))
        self.split_mins.set(cfg.get("split_mins", DEFAULT_SETTINGS["split_mins"]))
        self.subchapter_mode.set(cfg.get("subchapter_mode", DEFAULT_SETTINGS["subchapter_mode"]))
        self.playback_speed.set(cfg.get("playback_speed", DEFAULT_SETTINGS["playback_speed"]))
        self.preserve_pitch.set(cfg.get("preserve_pitch", DEFAULT_SETTINGS["preserve_pitch"]))
        self.final_chapter_silence.set(cfg.get("final_chapter_silence", DEFAULT_SETTINGS.get("final_chapter_silence", True)))

        cfg_bit = cfg.get("bitrate_kbps", "auto")
        if str(cfg_bit).lower() == "auto":
            self.bitrate_is_auto.set(True)
        else:
            self.bitrate_is_auto.set(False)
            try:
                self.bitrate_kbps.set(int(cfg_bit))
            except (ValueError, TypeError):
                self.bitrate_kbps.set(10)

        spd_val = self.playback_speed.get()
        spd_str = f"{spd_val}x (Normal)" if spd_val == 1.0 else f"{spd_val}x"
        self.speed_combo.set(spd_str)
        self.update_estimates(replan=True)
        self.log("[📂] Loaded saved settings from playaway_config.json.")
        messagebox.showinfo("Settings Loaded", "Loaded saved preferences from playaway_config.json!")

    def reset_default_settings(self):
        """Reset GUI controls to factory default settings."""
        self.split_mode.set(DEFAULT_SETTINGS["split_mode"])
        self.split_mins.set(DEFAULT_SETTINGS["split_mins"])
        self.subchapter_mode.set(DEFAULT_SETTINGS["subchapter_mode"])
        self.playback_speed.set(DEFAULT_SETTINGS["playback_speed"])
        self.preserve_pitch.set(DEFAULT_SETTINGS["preserve_pitch"])
        self.final_chapter_silence.set(DEFAULT_SETTINGS.get("final_chapter_silence", True))
        self.bitrate_is_auto.set(True)
        self.bitrate_kbps.set(10)

        spd_val = DEFAULT_SETTINGS["playback_speed"]
        spd_str = f"{spd_val}x (Normal)" if spd_val == 1.0 else f"{spd_val}x"
        self.speed_combo.set(spd_str)
        self.update_estimates(replan=True)
        self.log("[i] Settings reset to factory defaults.")

    def start_backup_thread(self):
        sel_drive_str = self.selected_drive.get()
        if not sel_drive_str or sel_drive_str.startswith("--"):
            messagebox.showerror("Error", "Please select a valid Playaway USB drive from the dropdown first!")
            return

        drive_path = sel_drive_str.split()[0]
        if is_system_drive(drive_path):
            messagebox.showerror("Safety Error", f"Action Blocked: System drive '{drive_path}' cannot be backed up as a Playaway!")
            return

        target_dir = filedialog.askdirectory(title=f"Select Destination Folder to Save Playaway Backup ({drive_path})")
        if not target_dir:
            return

        self.btn_backup.config(state="disabled")
        threading.Thread(target=self.run_backup_process, args=(drive_path, target_dir), daemon=True).start()

    def run_backup_process(self, drive_path, target_dir):
        try:
            self.log("\n==================================================")
            self.log(f"Starting Backup from Drive {drive_path} to {target_dir}...")
            self.log("==================================================")

            self.progress_bar["value"] = 10
            backup_playaway_drive(
                drive_path=drive_path,
                backup_dir=target_dir,
                log_callback=self.log,
                progress_callback=lambda cur, tot, msg: self.progress_bar.config(value=10 + int((cur/max(1, tot))*90))
            )
            self.progress_bar["value"] = 100
            messagebox.showinfo("Success", f"Playaway drive backed up successfully to:\n{target_dir}")

        except Exception as e:
            self.log(f"\n[!] BACKUP ERROR: {e}")
            messagebox.showerror("Backup Error", f"An error occurred during backup:\n{e}")
        finally:
            self.btn_backup.config(state="normal")
            self.progress_bar["value"] = 0

    def start_export_thread(self):
        if not self.input_path.get() or not Path(self.input_path.get()).exists():
            messagebox.showerror("Error", "Please select a valid audiobook input file or folder first!")
            return

        parent_dir = filedialog.askdirectory(title="Select Local Folder to Save Generated Playaway Files")
        if not parent_dir:
            return

        self.btn_flash.config(state="disabled")
        self.btn_export.config(state="disabled")
        threading.Thread(target=self.run_export_process, args=(parent_dir,), daemon=True).start()

    def autofit_bitrate(self):
        if not self.audio_info:
            messagebox.showinfo("Auto-Fit Bitrate", "Please select an audiobook source file or folder first!")
            return

        self.bitrate_is_auto.set(True)  # User clicked Auto-Fit button!
        free_mb = 105.0  # Default ~105MB usable space on standard Playaway 128MB flash
        storage_source_desc = "Default Playaway Capacity (~105 MB Usable Flash)"
        
        sel_drive_str = self.selected_drive.get()
        if sel_drive_str and not sel_drive_str.startswith("--"):
            drive_path = sel_drive_str.split()[0]
            matching_d = next((d for d in self.drives if d['path'] == drive_path), None)
            if matching_d:
                free_mb = matching_d['free_mb']
                storage_source_desc = f"Connected USB Drive {drive_path} ({free_mb} MB Free)"

        # Calculate duration of active (non-excluded) segments only
        if self.planned_segments:
            active_segments = [s for s in self.planned_segments if not s.get("excluded", False)]
            dur_sec = sum(s.get("duration", 0.0) for s in active_segments)
        else:
            dur_sec = self.audio_info["total_duration_sec"]

        spd = self.playback_speed.get()
        fit_kbps = calculate_autofit_bitrate(dur_sec, target_free_mb=free_mb, speed=spd)

        self.bitrate_kbps.set(fit_kbps)
        self.update_bitrate_label()
        self.update_estimates()

        self.log(f"[+] Auto-Fit Bitrate: Calculated {fit_kbps} kbps based on {storage_source_desc}")
        messagebox.showinfo(
            "Auto-Fit Bitrate Calculated",
            f"Optimal Bitrate: {fit_kbps} kbps\n\n"
            f"Storage Capacity Source:\n• {storage_source_desc}\n\n"
            f"This automatically selects the highest possible audio quality that will fit your audiobook into {free_mb} MB of target storage!"
        )

    def stop_operation(self):
        """Signal all encoding threads to stop immediately."""
        self.cancel_event.set()
        self.log("\n[!] CANCELLATION REQUESTED BY USER. Stopping active encoding threads...")
        self.btn_stop.config(state="disabled")

    def start_export_thread(self):
        if not self.input_path.get() or not Path(self.input_path.get()).exists():
            messagebox.showerror("Error", "Please select a valid audiobook input file or folder first!")
            return

        # SAFETY CHECK: Track Duration Warning (> 88 mins)
        active_segments = [s for s in self.planned_segments if not s.get("excluded", False)]
        long_tracks = check_track_duration_warnings(active_segments, speed=self.playback_speed.get())
        if long_tracks:
            lines = [f"• Track #{t['index']}: {t['title']} ({t['effective_mins']} mins)" for t in long_tracks[:5]]
            if len(long_tracks) > 5:
                lines.append(f"• ... and {len(long_tracks) - 5} more tracks")
            track_list_str = "\n".join(lines)
            confirm_long = messagebox.askyesno(
                "⚠️ Long Chapter Warning (>88 mins)",
                f"WARNING: {len(long_tracks)} track(s) exceed 88 minutes:\n\n{track_list_str}\n\n"
                f"On Playaway hardware running Firmware 01:03, tracks longer than 88 minutes cause the decoder to freeze playback and fail to auto power off.\n\n"
                f"Recommendation: Set 'Chapter Splitting Mode' to 'Split into fixed duration (15–60 mins)' or split long tracks using '✂️ Split Chapter at Scrubber'.\n\n"
                f"Do you want to proceed with export anyway?",
                icon="warning"
            )
            if not confirm_long:
                return

        parent_dir = filedialog.askdirectory(title="Select Local Folder to Save Generated Playaway Files")
        if not parent_dir:
            return

        self.cancel_event.clear()
        self.btn_flash.config(state="disabled")
        self.btn_export.config(state="disabled")
        self.btn_stop.config(state="normal")
        threading.Thread(target=self.run_export_process, args=(parent_dir,), daemon=True).start()

    def run_export_process(self, parent_dir):
        try:
            clean_title = re.sub(r'[^\w\s-]', '', self.book_title.get()).strip() or "Audiobook"
            export_dir = Path(parent_dir) / f"{clean_title}_Playaway"
            export_dir.mkdir(parents=True, exist_ok=True)

            self.log("\n==================================================")
            self.log(f"Exporting Audiobook to Local Folder: {export_dir}...")
            spd = self.playback_speed.get()
            self.log(f"Configured Playback Speed: {spd}x")
            self.log("==================================================")

            enc_exe, _ = setup_encoder()
            if not enc_exe:
                raise RuntimeError("3GPP AMR-WB+ Encoder binary is missing. Cannot proceed.")

            active_segments = [s for s in self.planned_segments if not s.get("excluded", False)]
            if not active_segments:
                raise ValueError("Cannot export: All planned tracks in the list have been excluded!")

            for idx, seg in enumerate(active_segments, 1):
                track_num = f"{idx:04d}"
                out_name = f"{track_num} {clean_title} 0000.awb"
                if self.subchapter_mode.get():
                    out_name = f"001{idx:03d} {clean_title} 0000.awb"
                seg["out_name"] = out_name

            active_segments[-1]["is_last"] = True
            num_segments = len(active_segments)

            def on_export_progress(cur, tot, eta_str, track_time_str):
                pct = int((cur / max(1, tot)) * 85)
                self.progress_bar.config(value=pct)
                self.progress_status_label.config(text=f"Encoding [{cur}/{tot} tracks] ({pct}%) | Last Track: {track_time_str} | ETA: {eta_str}")

            convert_all_segments_parallel(
                segments=active_segments,
                output_dir=export_dir,
                bitrate_kbps=self.bitrate_kbps.get(),
                speed=spd,
                preserve_pitch=self.preserve_pitch.get(),
                encoder_exe=enc_exe,
                log_callback=self.log,
                progress_callback=on_export_progress,
                cancel_event=self.cancel_event
            )

            # Write PATWEAKS.DAT
            pat_file = export_dir / "PATWEAKS.DAT"
            pat_content = generate_patweaks_content(num_segments, self.subchapter_mode.get())
            with open(pat_file, "wb") as f:
                f.write(pat_content.encode("ascii"))
            self.log(f"Wrote PATWEAKS.DAT with NMD{num_segments:03d}")

            # Write README_HOW_TO_COPY.txt
            readme_file = export_dir / "README_HOW_TO_COPY.txt"
            readme_text = generate_copy_instructions(clean_title, num_segments)
            with open(readme_file, "w", encoding="utf-8") as f:
                f.write(readme_text)
            self.log("Generated README_HOW_TO_COPY.txt manual copy instructions.")

            self.progress_bar["value"] = 100
            self.progress_status_label.config(text="Export Completed ✓")
            messagebox.showinfo("Export Successful", f"Audiobook files and manual copy instructions exported to:\n{export_dir}")

        except InterruptedError:
            self.log("\n[!] OPERATION CANCELLED BY USER.")
            self.progress_status_label.config(text="Operation Cancelled 🛑")
            messagebox.showwarning("Cancelled", "Audiobook export operation was stopped by user.")
        except Exception as e:
            self.log(f"\n[!] EXPORT ERROR: {e}")
            self.progress_status_label.config(text="Export Error ✗")
            messagebox.showerror("Export Error", f"An error occurred during export:\n{e}")
        finally:
            self.btn_flash.config(state="normal")
            self.btn_export.config(state="normal")
            self.btn_stop.config(state="disabled")
            self.progress_bar["value"] = 0
            self.progress_status_label.config(text="Progress: Ready")

    def start_flash_thread(self):
        if not self.input_path.get() or not Path(self.input_path.get()).exists():
            messagebox.showerror("Error", "Please select a valid audiobook input file or folder first!")
            return

        sel_drive_str = self.selected_drive.get()
        if not sel_drive_str or sel_drive_str.startswith("--"):
            messagebox.showerror("Error", "Please select a target Playaway USB drive from the dropdown!")
            return

        drive_path = sel_drive_str.split()[0]
        
        # SAFETY CHECK 1: System Drive Protection
        if is_system_drive(drive_path):
            messagebox.showerror("Safety Error", f"Action Blocked: System drive '{drive_path}' is protected and cannot be wiped!")
            return

        # SAFETY CHECK 2: Size Limit Protection (> 2048 MB)
        matching_d = next((d for d in self.drives if d['path'] == drive_path), None)
        if matching_d and matching_d['total_mb'] > 2048:
            messagebox.showerror(
                "Safety Error",
                f"Action Blocked: Drive '{drive_path}' is {matching_d['total_mb']} MB (> 2GB).\n\n"
                "Real Playaway hardware flash chips are 1GB or smaller. Large hard drives and SSDs are blocked to prevent accidental wiping."
            )
            return

        # SAFETY CHECK 3: Track Duration Warning (> 88 mins)
        active_segments = [s for s in self.planned_segments if not s.get("excluded", False)]
        long_tracks = check_track_duration_warnings(active_segments, speed=self.playback_speed.get())
        if long_tracks:
            lines = [f"• Track #{t['index']}: {t['title']} ({t['effective_mins']} mins)" for t in long_tracks[:5]]
            if len(long_tracks) > 5:
                lines.append(f"• ... and {len(long_tracks) - 5} more tracks")
            track_list_str = "\n".join(lines)
            confirm_long = messagebox.askyesno(
                "⚠️ Long Chapter Warning (>88 mins)",
                f"WARNING: {len(long_tracks)} track(s) exceed 88 minutes:\n\n{track_list_str}\n\n"
                f"On Playaway hardware running Firmware 01:03, tracks longer than 88 minutes cause the decoder to freeze playback and fail to auto power off.\n\n"
                f"Recommendation: Set 'Chapter Splitting Mode' to 'Split into fixed duration (15–60 mins)' or split long tracks using '✂️ Split Chapter at Scrubber'.\n\n"
                f"Do you want to proceed with flashing anyway?",
                icon="warning"
            )
            if not confirm_long:
                return

        # Confirm wipe
        confirm = messagebox.askyesno(
            "Confirm Wipe & Flash",
            f"WARNING: Flashing will COMPLETELY ERASE all files on drive {drive_path}.\n\nAre you sure you want to proceed?"
        )
        if not confirm:
            return

        self.cancel_event.clear()
        self.btn_flash.config(state="disabled")
        self.btn_export.config(state="disabled")
        self.btn_stop.config(state="normal")
        threading.Thread(target=self.run_flash_process, args=(drive_path,), daemon=True).start()

    def run_flash_process(self, drive_path):
        try:
            self.log("\n==================================================")
            self.log(f"Starting Flash Process for Drive {drive_path}...")
            spd = self.playback_speed.get()
            self.log(f"Configured Playback Speed: {spd}x")
            self.log("==================================================")

            enc_exe, _ = setup_encoder()
            if not enc_exe:
                raise RuntimeError("3GPP AMR-WB+ Encoder binary is missing. Cannot proceed.")

            clean_title = re.sub(r'[^\w\s-]', '', self.book_title.get()).strip() or "Audiobook"
            active_segments = [s for s in self.planned_segments if not s.get("excluded", False)]
            if not active_segments:
                raise ValueError("Cannot flash: All planned tracks in the list have been excluded!")

            for idx, seg in enumerate(active_segments, 1):
                track_num = f"{idx:04d}"
                out_name = f"{track_num} {clean_title} 0000.awb"
                if self.subchapter_mode.get():
                    out_name = f"001{idx:03d} {clean_title} 0000.awb"
                seg["out_name"] = out_name

            active_segments[-1]["is_last"] = True
            num_segments = len(active_segments)

            # Create temporary staging directory for .awb files
            with tempfile.TemporaryDirectory(prefix="playaway_staging_") as temp_dir:
                self.log(f"Staging directory created: {temp_dir}")
                
                def on_flash_progress(cur, tot, eta_str, track_time_str):
                    pct = int((cur / max(1, tot)) * 85)
                    self.progress_bar.config(value=pct)
                    self.progress_status_label.config(text=f"Encoding [{cur}/{tot} tracks] ({pct}%) | Last Track: {track_time_str} | ETA: {eta_str}")

                convert_all_segments_parallel(
                    segments=active_segments,
                    output_dir=temp_dir,
                    bitrate_kbps=self.bitrate_kbps.get(),
                    speed=spd,
                    preserve_pitch=self.preserve_pitch.get(),
                    encoder_exe=enc_exe,
                    log_callback=self.log,
                    progress_callback=on_flash_progress,
                    cancel_event=self.cancel_event
                )

                self.progress_bar["value"] = 85
                self.progress_status_label.config(text="Flashing files to Playaway drive...")
                self.log(f"\n[+] All {num_segments} tracks successfully encoded to AMR-WB+.")

                # Flash to Playaway drive
                self.log(f"\nFlashing to drive {drive_path}...")
                flash_playaway(
                    drive_path=drive_path,
                    awb_dir=temp_dir,
                    track_count=num_segments,
                    subchapter_mode=self.subchapter_mode.get(),
                    log_callback=self.log,
                    progress_callback=lambda cur, tot, msg: self.progress_bar.config(value=85 + int((cur/tot)*15))
                )

                self.progress_bar["value"] = 100
                messagebox.showinfo("Success", f"Audiobook successfully flashed to Playaway drive {drive_path}!\nSafe to disconnect USB.")

        except InterruptedError:
            self.log("\n[!] OPERATION CANCELLED BY USER.")
            self.progress_status_label.config(text="Operation Cancelled 🛑")
            messagebox.showwarning("Cancelled", "Flashing operation was stopped by user.")
        except Exception as e:
            self.log(f"\n[!] FLASH ERROR: {e}")
            self.progress_status_label.config(text="Flash Error ✗")
            messagebox.showerror("Flash Error", f"An error occurred during flashing:\n{e}")
        finally:
            self.btn_flash.config(state="normal")
            self.btn_export.config(state="normal")
            self.btn_stop.config(state="disabled")
            self.progress_bar["value"] = 0
            self.progress_status_label.config(text="Progress: Ready")
            self.refresh_drives()


def main():
    app = PlayawayStudioGUI()
    app.mainloop()


if __name__ == "__main__":
    main()
