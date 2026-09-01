#!/usr/bin/env python3
"""
dialog.py - Native PyQt Interface Dialog for Calibre Playaway Flasher Plugin
Provides a complete, responsive GUI inside Calibre for chapterizing and flashing audiobooks.
"""

import os
import sys
import tempfile
import threading
from pathlib import Path

try:
    from qt.core import (
        QDialog, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QGroupBox,
        QLabel, QComboBox, QPushButton, QProgressBar, QMessageBox, QSpinBox,
        QRadioButton, QCheckBox, QTreeWidget, QTreeWidgetItem, QThread,
        pyqtSignal, QIcon, QFont, Qt, QFileDialog, QTextEdit, QHeaderView,
        QButtonGroup, QColor
    )
except ImportError:
    from PyQt5.QtWidgets import (
        QDialog, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QGroupBox,
        QLabel, QComboBox, QPushButton, QProgressBar, QMessageBox, QSpinBox,
        QRadioButton, QCheckBox, QTreeWidget, QTreeWidgetItem,
        QFileDialog, QTextEdit, QHeaderView, QButtonGroup
    )
    from PyQt5.QtCore import QThread, pyqtSignal, Qt
    from PyQt5.QtGui import QIcon, QFont, QColor

try:
    from calibre_plugins.playaway_flasher.core_bridge import (
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
        setup_encoder,
        find_encoder,
        DEFAULT_SETTINGS
    )
except (ImportError, ValueError):
    try:
        from .core_bridge import (
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
            setup_encoder,
            find_encoder,
            DEFAULT_SETTINGS
        )
    except (ImportError, ValueError):
        from core_bridge import (
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
            setup_encoder,
            find_encoder,
            DEFAULT_SETTINGS
        )


class WorkerThread(QThread):
    progress = pyqtSignal(int, int, str)
    log = pyqtSignal(str)
    completed = pyqtSignal(str)
    failed = pyqtSignal(str)

    def __init__(self, mode, params):
        super().__init__()
        self.mode = mode
        self.params = params
        self.cancel_event = threading.Event()

    def stop(self):
        self.cancel_event.set()

    def run(self):
        try:
            enc_exe, _ = setup_encoder()
            if not enc_exe:
                raise RuntimeError("3GPP AMR-WB+ encoder binary missing. Please ensure tools/encoder.exe is installed.")

            segments = self.params["segments"]
            speed = self.params["speed"]
            bitrate = self.params["bitrate"]
            preserve_pitch = self.params["preserve_pitch"]
            subchapters = self.params["subchapters"]
            clean_title = self.params["title"]

            if self.mode == "export":
                export_dir = Path(self.params["export_dir"])
                export_dir.mkdir(parents=True, exist_ok=True)
                self.progress.emit(0, len(segments), f"⚡ Starting export of {len(segments)} tracks...")

                def on_prog(cur, tot, eta, track_time):
                    pct = int((cur / max(1, tot)) * 100)
                    tt_str = f" | Last track: {track_time}" if track_time else ""
                    if cur == 0:
                        self.progress.emit(0, tot, f"⚡ Encoding tracks on parallel CPU threads...")
                    else:
                        self.progress.emit(cur, tot, f"⚡ Encoded [{cur}/{tot}] ({pct}%) | ETA: {eta}{tt_str}")

                convert_all_segments_parallel(
                    segments=segments,
                    output_dir=export_dir,
                    bitrate_kbps=bitrate,
                    speed=speed,
                    preserve_pitch=preserve_pitch,
                    encoder_exe=enc_exe,
                    log_callback=lambda m: self.log.emit(m),
                    progress_callback=on_prog,
                    cancel_event=self.cancel_event
                )

                # Write PATWEAKS.DAT
                pat_content = generate_patweaks_content(len(segments), subchapters)
                with open(export_dir / "PATWEAKS.DAT", "wb") as f:
                    f.write(pat_content.encode("ascii"))

                # Write README instructions
                with open(export_dir / "README_HOW_TO_COPY.txt", "w", encoding="utf-8") as f:
                    f.write(generate_copy_instructions(clean_title, len(segments)))

                self.progress.emit(100, 100, "Export Completed ✓")
                self.completed.emit(f"Audiobook exported successfully to:\n{export_dir}")

            elif self.mode == "flash":
                drive_path = self.params["drive_path"]
                self.progress.emit(0, len(segments), f"⚡ Starting encoding of {len(segments)} tracks...")

                with tempfile.TemporaryDirectory(prefix="playaway_calibre_") as temp_dir:
                    def on_prog(cur, tot, eta, track_time):
                        pct = int((cur / max(1, tot)) * 100)
                        tt_str = f" | Last track: {track_time}" if track_time else ""
                        if cur == 0:
                            self.progress.emit(0, tot, f"⚡ Encoding tracks on parallel CPU threads...")
                        else:
                            self.progress.emit(cur, tot, f"⚡ Encoded [{cur}/{tot}] ({pct}%) | ETA: {eta}{tt_str}")

                    convert_all_segments_parallel(
                        segments=segments,
                        output_dir=temp_dir,
                        bitrate_kbps=bitrate,
                        speed=speed,
                        preserve_pitch=preserve_pitch,
                        encoder_exe=enc_exe,
                        log_callback=lambda m: self.log.emit(m),
                        progress_callback=on_prog,
                        cancel_event=self.cancel_event
                    )

                    def on_flash_prog(cur, tot, desc):
                        self.progress.emit(cur, tot, f"💾 {desc}")

                    flash_playaway(
                        drive_path=drive_path,
                        awb_dir=temp_dir,
                        track_count=len(segments),
                        subchapter_mode=subchapters,
                        log_callback=lambda m: self.log.emit(m),
                        progress_callback=on_flash_prog
                    )

                self.progress.emit(100, 100, "Flash Completed ✓")
                self.completed.emit(f"Flash completed successfully on drive {drive_path}! Safe to unplug.")

        except InterruptedError:
            self.failed.emit("Operation cancelled by user.")
        except Exception as e:
            self.failed.emit(f"Error: {e}")


class PlayawayDialog(QDialog):
    def __init__(self, gui, book_id, book_title, audio_path, available_formats):
        super().__init__(gui)
        self.gui = gui
        self.book_id = book_id
        self.book_title = book_title
        self.audio_path = audio_path
        self.available_formats = available_formats
        self.drives = []
        self.planned_segments = []
        self.audio_info = None
        self.worker = None

        self.setWindowTitle(f"⚡ Send to Playaway — {book_title}")
        self.resize(850, 720)
        self.setMinimumSize(780, 600)

        self.init_ui()
        self.load_audiobook_source()
        self.refresh_drives()

    def init_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setSpacing(8)

        # Header Info Banner
        header_box = QGroupBox("📖 Selected Audiobook")
        header_layout = QGridLayout(header_box)
        
        header_layout.addWidget(QLabel("<b>Title:</b>"), 0, 0)
        self.lbl_title = QLabel(self.book_title)
        header_layout.addWidget(self.lbl_title, 0, 1)

        header_layout.addWidget(QLabel("<b>Audio File:</b>"), 1, 0)
        self.combo_format = QComboBox()
        for fmt, p in self.available_formats.items():
            self.combo_format.addItem(f"{fmt}: {os.path.basename(p)}", p)
        self.combo_format.currentIndexChanged.connect(self.on_format_changed)
        header_layout.addWidget(self.combo_format, 1, 1)

        self.lbl_duration = QLabel("Duration: Probing audio...")
        header_layout.addWidget(self.lbl_duration, 1, 2)
        main_layout.addWidget(header_box)

        # Dedicated Full-Width Target Playaway Drive Card
        drive_box = QGroupBox("🔌 Target Playaway Device")
        drive_layout = QHBoxLayout(drive_box)
        drive_layout.addWidget(QLabel("<b>Connected Drive:</b>"))
        self.combo_drives = QComboBox()
        self.combo_drives.currentIndexChanged.connect(self.on_drive_changed)
        drive_layout.addWidget(self.combo_drives, 1)

        btn_refresh_drives = QPushButton("🔄 Refresh Drives")
        btn_refresh_drives.clicked.connect(self.refresh_drives)
        drive_layout.addWidget(btn_refresh_drives)

        btn_backup_drive = QPushButton("📥 Backup Drive")
        btn_backup_drive.setToolTip("Create a full backup of all audio tracks and FAT files from the connected Playaway player")
        btn_backup_drive.clicked.connect(self.on_backup_clicked)
        drive_layout.addWidget(btn_backup_drive)

        main_layout.addWidget(drive_box)

        # Settings Grid (2 Columns: Chapter Layout | Playback & Bitrate)
        settings_layout = QHBoxLayout()

        # Left Column: Chapter Splitting Layout
        left_box = QGroupBox("⚙️ Chapter Splitting Layout")
        left_layout = QVBoxLayout(left_box)

        # Chapter Split Mode
        left_layout.addWidget(QLabel("<b>Splitting Mode:</b>"))
        self.split_group = QButtonGroup(self)
        
        cfg = load_config()
        default_mode = cfg.get("split_mode", "duration")

        self.rb_split_dur = QRadioButton("Split into fixed duration:")
        self.rb_split_dur.setChecked(default_mode == "duration")
        self.split_group.addButton(self.rb_split_dur)
        left_layout.addWidget(self.rb_split_dur)

        dur_row = QHBoxLayout()
        dur_row.setContentsMargins(20, 0, 0, 0)
        self.spin_split_mins = QSpinBox()
        self.spin_split_mins.setRange(1, 180)
        self.spin_split_mins.setValue(int(cfg.get("split_mins", 15)))
        self.spin_split_mins.setSuffix(" mins per track")
        self.spin_split_mins.valueChanged.connect(self.on_split_mins_changed)
        dur_row.addWidget(self.spin_split_mins)
        dur_row.addStretch()
        left_layout.addLayout(dur_row)

        self.rb_split_chap = QRadioButton("Split by embedded chapter tags")
        self.rb_split_chap.setChecked(default_mode == "chapters")
        self.split_group.addButton(self.rb_split_chap)
        left_layout.addWidget(self.rb_split_chap)

        self.rb_split_none = QRadioButton("Keep single track as-is")
        self.rb_split_none.setChecked(default_mode == "none")
        self.split_group.addButton(self.rb_split_none)
        left_layout.addWidget(self.rb_split_none)

        self.split_group.buttonClicked.connect(lambda: self.update_estimates(replan=True))

        self.cb_subchapters = QCheckBox("Enable Subchapters (AF* multi-part)")
        self.cb_subchapters.setChecked(bool(cfg.get("subchapter_mode", False)))
        self.cb_subchapters.stateChanged.connect(lambda: self.update_estimates(replan=True))
        left_layout.addWidget(self.cb_subchapters)

        settings_layout.addWidget(left_box)

        # Right Column: Speed & Bitrate
        right_box = QGroupBox("🎛️ Audio Quality && Playback")
        right_layout = QVBoxLayout(right_box)

        # Speed
        speed_row = QHBoxLayout()
        speed_row.addWidget(QLabel("<b>Playback Speed:</b>"))
        self.combo_speed = QComboBox()
        self.combo_speed.addItems(["0.75x", "0.85x", "1.0x (Normal)", "1.1x", "1.25x", "1.5x", "1.75x", "2.0x", "2.5x", "3.0x"])
        def_spd = cfg.get("playback_speed", 1.0)
        matched_text = f"{def_spd:.2f}".rstrip('0').rstrip('.') + "x"
        if def_spd == 1.0:
            matched_text = "1.0x (Normal)"
        idx = self.combo_speed.findText(matched_text, Qt.MatchStartsWith if hasattr(Qt, 'MatchStartsWith') else 1)
        if idx >= 0:
            self.combo_speed.setCurrentIndex(idx)
        else:
            self.combo_speed.setCurrentText("1.0x (Normal)")
        self.combo_speed.currentIndexChanged.connect(lambda: self.update_estimates(replan=False))
        speed_row.addWidget(self.combo_speed, 1)
        right_layout.addLayout(speed_row)

        self.cb_pitch = QCheckBox("Preserve voice pitch (atempo DSP)")
        self.cb_pitch.setChecked(bool(cfg.get("preserve_pitch", True)))
        right_layout.addWidget(self.cb_pitch)

        # Bitrate
        bitrate_row = QHBoxLayout()
        bitrate_row.addWidget(QLabel("<b>Bitrate (kbps):</b>"))
        self.spin_bitrate = QSpinBox()
        self.spin_bitrate.setRange(10, 36)
        self.spin_bitrate.setValue(10)
        self.spin_bitrate.valueChanged.connect(lambda: self.update_estimates(replan=False))
        bitrate_row.addWidget(self.spin_bitrate, 1)

        btn_autofit = QPushButton("⚡ Auto-Fit")
        btn_autofit.setToolTip("Auto-select maximum bitrate to fit target Playaway storage")
        btn_autofit.clicked.connect(self.on_autofit_clicked)
        bitrate_row.addWidget(btn_autofit)
        right_layout.addLayout(bitrate_row)

        self.lbl_estimates = QLabel("Estimated Size: Calculating...")
        self.lbl_estimates.setStyleSheet("font-weight: bold; color: #2ecc71;")
        right_layout.addWidget(self.lbl_estimates)

        btn_save_defaults = QPushButton("💾 Save Current Settings as Default")
        btn_save_defaults.setToolTip("Save splitting mode, minutes, speed, and pitch as your default configuration for Quick Flash")
        btn_save_defaults.clicked.connect(self.on_save_as_default_clicked)
        right_layout.addWidget(btn_save_defaults)

        self.lbl_warning_banner = QLabel("")
        self.lbl_warning_banner.setStyleSheet("font-weight: bold; color: #e67e22;")
        self.lbl_warning_banner.setWordWrap(True)
        self.lbl_warning_banner.hide()
        right_layout.addWidget(self.lbl_warning_banner)

        right_layout.addStretch()
        settings_layout.addWidget(right_box)
        main_layout.addLayout(settings_layout)

        # Chapter Preview Table
        preview_box = QGroupBox("📊 Chapter && Track Layout Preview")
        preview_layout = QVBoxLayout(preview_box)

        self.tree_chapters = QTreeWidget()
        self.tree_chapters.setHeaderLabels(["#", "Track Title", "Timeframe", "Length", "Status"])
        header = self.tree_chapters.header()
        if hasattr(QHeaderView, 'ResizeMode'):
            header.setSectionResizeMode(0, QHeaderView.ResizeMode.Interactive)
            header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
            header.setSectionResizeMode(2, QHeaderView.ResizeMode.Interactive)
            header.setSectionResizeMode(3, QHeaderView.ResizeMode.Interactive)
            header.setSectionResizeMode(4, QHeaderView.ResizeMode.Interactive)
        self.tree_chapters.setColumnWidth(0, 48)
        self.tree_chapters.setColumnWidth(2, 195)
        self.tree_chapters.setColumnWidth(3, 75)
        self.tree_chapters.setColumnWidth(4, 75)
        self.tree_chapters.setAlternatingRowColors(True)
        preview_layout.addWidget(self.tree_chapters)

        main_layout.addWidget(preview_box)

        # Progress Bar & Status
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        main_layout.addWidget(self.progress_bar)

        self.lbl_status = QLabel("Ready.")
        main_layout.addWidget(self.lbl_status)

        # Action Buttons
        btn_layout = QHBoxLayout()
        
        self.btn_flash = QPushButton("⚡ Wipe && Flash Playaway")
        self.btn_flash.setStyleSheet("font-weight: bold; font-size: 11pt; padding: 6px;")
        self.btn_flash.clicked.connect(self.on_flash_clicked)
        btn_layout.addWidget(self.btn_flash)

        self.btn_export = QPushButton("📁 Export to Local Folder")
        self.btn_export.clicked.connect(self.on_export_clicked)
        btn_layout.addWidget(self.btn_export)

        btn_layout.addStretch()

        self.btn_stop = QPushButton("🛑 Stop")
        self.btn_stop.setEnabled(False)
        self.btn_stop.clicked.connect(self.on_stop_clicked)
        btn_layout.addWidget(self.btn_stop)

        btn_close = QPushButton("Close")
        btn_close.clicked.connect(self.close)
        btn_layout.addWidget(btn_close)

        main_layout.addLayout(btn_layout)

    def load_audiobook_source(self):
        if not self.audio_path or not os.path.exists(self.audio_path):
            QMessageBox.critical(self, "Error", f"Audiobook file not found: {self.audio_path}")
            return

        try:
            self.audio_info = inspect_audio_source(self.audio_path)
            dur_str = self.audio_info["total_duration_formatted"]
            self.lbl_duration.setText(f"<b>Duration:</b> {dur_str}")
            self.update_estimates(replan=True)
        except Exception as e:
            QMessageBox.critical(self, "Error Analyzing Audio", f"Could not analyze audio: {e}")

    def on_format_changed(self, idx):
        self.audio_path = self.combo_format.currentData()
        self.load_audiobook_source()

    def refresh_drives(self):
        self.combo_drives.clear()
        self.drives = detect_playaway_drives()
        
        if not self.drives:
            self.combo_drives.addItem("-- No Playaway USB drive found --", None)
            self.btn_flash.setEnabled(False)
            return

        for d in self.drives:
            tag = " [Playaway ✓]" if d["is_playaway"] else ""
            label = f"{d['path']} ({d['label']}) — {d['free_mb']} MB free / {d['total_mb']} MB total{tag}"
            self.combo_drives.addItem(label, d)

        self.btn_flash.setEnabled(True)
        self.update_estimates(replan=False)

    def on_drive_changed(self):
        self.update_estimates(replan=False)

    def on_backup_clicked(self):
        d_data = self.combo_drives.currentData()
        if not d_data or not isinstance(d_data, dict):
            QMessageBox.warning(self, "Select Drive", "Please select a connected Playaway drive to backup.")
            return

        target_dir = QFileDialog.getExistingDirectory(self, "Select Folder to Save Playaway Backup")
        if not target_dir:
            return

        try:
            drive_path = d_data["path"]
            backup_path = backup_playaway_drive(drive_path, target_dir)
            QMessageBox.information(self, "Backup Complete", f"Successfully backed up Playaway drive to:\n{backup_path}")
        except Exception as e:
            QMessageBox.critical(self, "Backup Error", f"Failed to backup Playaway drive: {e}")

    def on_split_mins_changed(self):
        if not self.rb_split_dur.isChecked():
            self.rb_split_dur.setChecked(True)
        self.update_estimates(replan=True)

    def get_selected_speed(self):
        raw = self.combo_speed.currentText().split()[0].replace("x", "")
        try:
            return float(raw)
        except ValueError:
            return 1.0

    def get_split_mode(self):
        if self.rb_split_chap.isChecked():
            return "chapters"
        elif self.rb_split_none.isChecked():
            return "none"
        return "duration"

    def on_autofit_clicked(self):
        if not self.audio_info:
            return
        
        capacity_mb = 105.0
        d_data = self.combo_drives.currentData()
        if d_data and isinstance(d_data, dict):
            capacity_mb = d_data.get("total_mb", d_data.get("free_mb", 105.0))

        dur_sec = self.audio_info["total_duration_sec"]
        spd = self.get_selected_speed()
        fit_kbps = calculate_autofit_bitrate(dur_sec, target_capacity_mb=capacity_mb, speed=spd)
        self.spin_bitrate.setValue(fit_kbps)
        self.update_estimates(replan=False)
        QMessageBox.information(self, "Auto-Fit Bitrate", f"Optimal Bitrate calculated: {fit_kbps} kbps based on {capacity_mb} MB total storage capacity.")

    def update_estimates(self, replan=True):
        if not self.audio_info:
            return

        split_mode = self.get_split_mode()
        split_mins = self.spin_split_mins.value()
        subchapters = self.cb_subchapters.isChecked()

        # Check if file has embedded chapter markers
        has_chapters = bool(self.audio_info.get("files") and self.audio_info["files"][0].get("chapters"))
        if not has_chapters:
            self.rb_split_chap.setEnabled(False)
            self.rb_split_chap.setText("Split by chapter tags (No tags in this file)")
            if self.rb_split_chap.isChecked():
                self.rb_split_dur.setChecked(True)
                split_mode = "duration"
                replan = True
        else:
            self.rb_split_chap.setEnabled(True)
            num_chaps = len(self.audio_info["files"][0]["chapters"])
            self.rb_split_chap.setText(f"Split by chapter tags ({num_chaps} chapters found)")

        if replan or not self.planned_segments:
            self.planned_segments = plan_chapters(
                input_path=self.audio_path,
                split_mode=split_mode,
                split_mins=split_mins,
                title=self.book_title,
                subchapter_mode=subchapters
            )

        spd = self.get_selected_speed()
        bitrate = self.spin_bitrate.value()

        active_dur = sum(s.get("duration", 0.0) for s in self.planned_segments if not s.get("excluded", False))
        est_mb = estimate_bitrate_size(active_dur, bitrate, speed=spd)
        eff_dur = active_dur / max(0.25, spd)

        self.lbl_estimates.setText(f"Tracks: {len(self.planned_segments)} | Playtime: {format_duration(eff_dur)} @ {spd}x | Est. Size: ~{est_mb} MB")

        # Duration warning check (>88m)
        long_warnings = check_track_duration_warnings(self.planned_segments, speed=spd)
        if long_warnings:
            self.lbl_warning_banner.setText(f"⚠️ WARNING: {len(long_warnings)} track(s) exceed 88 minutes (Firmware 01:03 freeze bug)!")
            self.lbl_warning_banner.show()
        else:
            self.lbl_warning_banner.hide()

        # Update Tree Widget
        self.tree_chapters.clear()
        for idx, seg in enumerate(self.planned_segments, 1):
            dur_sec = seg.get("duration", 0.0) / max(0.25, spd)
            dur_m = round(dur_sec / 60.0, 1)
            start_str = format_duration(seg.get("start", 0.0) / max(0.25, spd))
            end_str = format_duration(seg.get("end", 0.0) / max(0.25, spd))
            
            is_long = dur_m > MAX_SAFE_TRACK_MINS and not seg.get("is_silence", False)
            len_text = f"⚠️ {dur_m}m (>88m)" if is_long else f"{dur_m}m"

            item = QTreeWidgetItem([
                f"{idx:03d}",
                seg.get("title", f"Track {idx}"),
                f"{start_str} -> {end_str}",
                len_text,
                "Active"
            ])
            if is_long:
                item.setForeground(3, QColor("#e74c3c"))
            self.tree_chapters.addTopLevelItem(item)

    def on_export_clicked(self):
        target_dir = QFileDialog.getExistingDirectory(self, "Select Local Folder to Save Playaway Files")
        if not target_dir:
            return

        spd = self.get_selected_speed()
        long_tracks = check_track_duration_warnings(self.planned_segments, speed=spd)
        if long_tracks:
            res = QMessageBox.warning(
                self, "⚠️ Long Chapter Warning (>88m)",
                f"{len(long_tracks)} track(s) exceed 88 minutes.\nFirmware 01:03 players may freeze playback.\n\nProceed anyway?",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No
            )
            if res != QMessageBox.Yes:
                return

        params = {
            "segments": self.planned_segments,
            "speed": spd,
            "bitrate": self.spin_bitrate.value(),
            "preserve_pitch": self.cb_pitch.isChecked(),
            "subchapters": self.cb_subchapters.isChecked(),
            "title": self.book_title,
            "export_dir": os.path.join(target_dir, f"{self.book_title}_Playaway")
        }
        self.start_worker("export", params)

    def on_flash_clicked(self):
        d_data = self.combo_drives.currentData()
        if not d_data or not isinstance(d_data, dict):
            QMessageBox.warning(self, "Select Drive", "Please select a target Playaway USB drive.")
            return

        drive_path = d_data["path"]
        if is_system_drive(drive_path):
            QMessageBox.critical(self, "Safety Protection", f"Drive {drive_path} is the system drive and cannot be wiped.")
            return

        spd = self.get_selected_speed()
        long_tracks = check_track_duration_warnings(self.planned_segments, speed=spd)
        if long_tracks:
            res = QMessageBox.warning(
                self, "⚠️ Long Chapter Warning (>88m)",
                f"{len(long_tracks)} track(s) exceed 88 minutes.\nFirmware 01:03 players may freeze playback.\n\nProceed anyway?",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No
            )
            if res != QMessageBox.Yes:
                return

        res = QMessageBox.warning(
            self, "Confirm Wipe & Flash",
            f"WARNING: Flashing will COMPLETELY ERASE all files on drive {drive_path}.\n\nAre you sure you want to proceed?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No
        )
        if res != QMessageBox.Yes:
            return

        params = {
            "segments": self.planned_segments,
            "speed": spd,
            "bitrate": self.spin_bitrate.value(),
            "preserve_pitch": self.cb_pitch.isChecked(),
            "subchapters": self.cb_subchapters.isChecked(),
            "title": self.book_title,
            "drive_path": drive_path
        }
        self.start_worker("flash", params)

    def start_worker(self, mode, params):
        self.btn_flash.setEnabled(False)
        self.btn_export.setEnabled(False)
        self.btn_stop.setEnabled(True)
        self.progress_bar.setValue(0)

        self.worker = WorkerThread(mode, params)
        self.worker.progress.connect(self.on_worker_progress)
        self.worker.completed.connect(self.on_worker_completed)
        self.worker.failed.connect(self.on_worker_failed)
        self.worker.start()

    def on_save_as_default_clicked(self):
        """Save current GUI configuration to playaway_config.json as the new default."""
        cfg = load_config()
        cfg["split_mode"] = self.get_split_mode()
        cfg["split_mins"] = self.spin_split_mins.value()
        cfg["playback_speed"] = self.get_selected_speed()
        cfg["preserve_pitch"] = self.cb_pitch.isChecked()
        cfg["subchapter_mode"] = self.cb_subchapters.isChecked()
        save_config(cfg)
        QMessageBox.information(
            self,
            "Defaults Saved",
            "Current settings have been saved as your new default configuration for Quick Flash!"
        )

    def on_worker_progress(self, cur, tot, desc):
        pct = int((cur / max(1, tot)) * 100)
        self.progress_bar.setValue(pct)
        self.lbl_status.setText(desc)

    def on_worker_completed(self, msg):
        self.btn_flash.setEnabled(True)
        self.btn_export.setEnabled(True)
        self.btn_stop.setEnabled(False)
        self.progress_bar.setValue(100)
        self.lbl_status.setText("Operation completed successfully ✓")
        QMessageBox.information(self, "Success", msg)

    def on_worker_failed(self, msg):
        self.btn_flash.setEnabled(True)
        self.btn_export.setEnabled(True)
        self.btn_stop.setEnabled(False)
        self.lbl_status.setText("Operation failed / stopped 🛑")
        QMessageBox.critical(self, "Operation Error", msg)

    def on_stop_clicked(self):
        if self.worker and self.worker.isRunning():
            self.worker.stop()
            self.lbl_status.setText("Stopping active encoding threads...")
            self.btn_stop.setEnabled(False)


class QuickFlashDialog(QDialog):
    """
    1-Click Quick Flash Dialog:
    Reads user default settings, auto-detects Playaway drive, calculates optimal bitrate,
    and flashes with a single click while showing live progress.
    """
    def __init__(self, gui, book_id, book_title, audio_path, available_formats):
        super().__init__(gui)
        self.gui = gui
        self.book_id = book_id
        self.book_title = book_title
        self.audio_path = audio_path
        self.available_formats = available_formats
        self.worker = None

        self.setWindowTitle(f"⚡ Quick Flash — {book_title}")
        self.resize(560, 430)
        self.setMinimumSize(500, 380)

        self.cfg = load_config()
        self.drives = detect_playaway_drives()
        self.audio_info = inspect_audio_source(self.audio_path)

        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        # Header Info
        header_box = QGroupBox("📖 Selected Audiobook && Target")
        h_layout = QGridLayout(header_box)
        h_layout.addWidget(QLabel("<b>Book Title:</b>"), 0, 0)
        h_layout.addWidget(QLabel(self.book_title), 0, 1)

        dur_str = self.audio_info["total_duration_formatted"]
        h_layout.addWidget(QLabel("<b>Duration:</b>"), 1, 0)
        h_layout.addWidget(QLabel(dur_str), 1, 1)

        h_layout.addWidget(QLabel("<b>Target Playaway:</b>"), 2, 0)
        if self.drives:
            target_d = self.drives[0]
            self.drive_path = target_d["path"]
            tag = " [Playaway ✓]" if target_d["is_playaway"] else ""
            h_layout.addWidget(QLabel(f"<b>{target_d['path']}</b> ({target_d['label']}) — {target_d['free_mb']} MB free / {target_d['total_mb']} MB total{tag}"), 2, 1)
        else:
            self.drive_path = None
            lbl_no = QLabel("<font color='#e74c3c'><b>No Playaway USB drive detected!</b></font>")
            h_layout.addWidget(lbl_no, 2, 1)
        layout.addWidget(header_box)

        # Applied Defaults Summary
        spd = float(self.cfg.get("playback_speed", 1.0))
        split_mode = self.cfg.get("split_mode", "duration")
        split_mins = int(self.cfg.get("split_mins", 15))
        pitch = bool(self.cfg.get("preserve_pitch", True))
        subchap = bool(self.cfg.get("subchapter_mode", False))

        capacity_mb = (self.drives[0].get("total_mb", self.drives[0].get("free_mb", 105.0))) if self.drives else 105.0
        dur_sec = self.audio_info["total_duration_sec"]
        bitrate = calculate_autofit_bitrate(dur_sec, target_capacity_mb=capacity_mb, speed=spd)

        # Check if the audio file actually contains embedded chapter markers
        has_chapters = bool(self.audio_info.get("files") and self.audio_info["files"][0].get("chapters"))

        if split_mode == "chapters" and not has_chapters:
            # Automatic fallback to fixed duration for MP3 / untagged audio
            effective_split_mode = "duration"
            split_desc = f"Fixed Duration ({split_mins}m per track)"
        elif split_mode == "chapters":
            effective_split_mode = "chapters"
            num_chaps = len(self.audio_info["files"][0]["chapters"])
            split_desc = f"Embedded Chapter Tags ({num_chaps} chapters)"
        elif split_mode == "duration":
            effective_split_mode = "duration"
            split_desc = f"Fixed Duration ({split_mins}m per track)"
        else:
            effective_split_mode = "none"
            split_desc = "Keep Single Track"

        self.planned_segments = plan_chapters(
            input_path=self.audio_path,
            split_mode=effective_split_mode,
            split_mins=split_mins,
            title=self.book_title,
            subchapter_mode=subchap
        )

        active_dur = sum(s.get("duration", 0) for s in self.planned_segments)
        est_mb = estimate_bitrate_size(active_dur, bitrate, speed=spd)
        fill_pct = int(round((est_mb / max(1.0, capacity_mb)) * 100))

        cfg_box = QGroupBox("⚙️ Applied Saved Default Settings")
        c_layout = QGridLayout(cfg_box)
        c_layout.addWidget(QLabel(f"• <b>Splitting:</b> {split_desc}"), 0, 0)
        c_layout.addWidget(QLabel(f"• <b>Planned Tracks:</b> {len(self.planned_segments)} tracks"), 0, 1)
        c_layout.addWidget(QLabel(f"• <b>Speed:</b> {spd}x (Pitch: {'Preserved' if pitch else 'Off'})"), 1, 0)
        c_layout.addWidget(QLabel(f"• <b>Bitrate:</b> {bitrate} kbps (Auto-Fit)"), 1, 1)
        c_layout.addWidget(QLabel(f"• <b>Estimated Size:</b> <b>~{est_mb} MB</b> / {int(capacity_mb)} MB capacity ({fill_pct}% full)"), 2, 0, 1, 2)
        layout.addWidget(cfg_box)

        # Progress bar & Status
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        layout.addWidget(self.progress_bar)

        self.lbl_status = QLabel(f"Ready for 1-Click Quick Flash (~{est_mb} MB output).")
        layout.addWidget(self.lbl_status)

        # Buttons
        btn_box = QHBoxLayout()
        self.btn_quick = QPushButton("⚡ Start Quick Flash")
        self.btn_quick.setStyleSheet("font-weight: bold; font-size: 11pt; padding: 6px;")
        self.btn_quick.setEnabled(bool(self.drive_path))
        self.btn_quick.clicked.connect(lambda: self.start_quick_flash(spd, bitrate, pitch, subchap, est_mb, capacity_mb))
        btn_box.addWidget(self.btn_quick)

        btn_custom = QPushButton("🎛️ Custom Flash...", self)
        btn_custom.setToolTip("Open full custom studio dialog to manually edit chapters and settings")
        btn_custom.clicked.connect(self.switch_to_custom)
        btn_box.addWidget(btn_custom)

        btn_box.addStretch()

        self.btn_stop = QPushButton("🛑 Stop", self)
        self.btn_stop.setEnabled(False)
        self.btn_stop.clicked.connect(self.on_stop_clicked)
        btn_box.addWidget(self.btn_stop)

        btn_close = QPushButton("Close", self)
        btn_close.clicked.connect(self.close)
        btn_box.addWidget(btn_close)

        layout.addLayout(btn_box)

    def switch_to_custom(self):
        self.close()
        dlg = PlayawayDialog(self.gui, self.book_id, self.book_title, self.audio_path, self.available_formats)
        dlg.exec_()

    def start_quick_flash(self, speed, bitrate, pitch, subchap, est_mb=None, capacity_mb=None):
        if not self.drive_path:
            QMessageBox.warning(self, "No Drive", "No Playaway USB drive detected.")
            return

        if is_system_drive(self.drive_path):
            QMessageBox.critical(self, "Safety", f"Drive {self.drive_path} is the system drive.")
            return

        long_tracks = check_track_duration_warnings(self.planned_segments, speed=speed)
        if long_tracks:
            res = QMessageBox.warning(
                self, "⚠️ Long Chapter Warning (>88m)",
                f"{len(long_tracks)} track(s) exceed 88 minutes (Firmware 01:03 freeze limit).\nProceed anyway?",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No
            )
            if res != QMessageBox.Yes:
                return

        size_info = f"\n• Estimated Size: ~{est_mb} MB / {int(capacity_mb)} MB total capacity" if est_mb and capacity_mb else ""
        res = QMessageBox.warning(
            self, "Confirm Quick Flash",
            f"Wipe and flash '{self.book_title}' onto drive {self.drive_path}?\n"
            f"{size_info}\n"
            f"• Planned Tracks: {len(self.planned_segments)}\n"
            f"• Bitrate: {bitrate} kbps @ {speed}x speed\n\n"
            f"WARNING: All existing files on {self.drive_path} will be erased.",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No
        )
        if res != QMessageBox.Yes:
            return

        params = {
            "segments": self.planned_segments,
            "speed": speed,
            "bitrate": bitrate,
            "preserve_pitch": pitch,
            "subchapters": subchap,
            "title": self.book_title,
            "drive_path": self.drive_path
        }

        self.btn_quick.setEnabled(False)
        self.btn_stop.setEnabled(True)
        self.progress_bar.setValue(0)

        self.worker = WorkerThread("flash", params)
        self.worker.progress.connect(self.on_worker_progress)
        self.worker.completed.connect(self.on_worker_completed)
        self.worker.failed.connect(self.on_worker_failed)
        self.worker.start()

    def on_worker_progress(self, cur, tot, desc):
        pct = int((cur / max(1, tot)) * 100)
        self.progress_bar.setValue(pct)
        self.lbl_status.setText(desc)

    def on_worker_completed(self, msg):
        self.btn_quick.setEnabled(True)
        self.btn_stop.setEnabled(False)
        self.progress_bar.setValue(100)
        self.lbl_status.setText("Quick Flash completed successfully ✓")
        QMessageBox.information(self, "Success", msg)

    def on_worker_failed(self, msg):
        self.btn_quick.setEnabled(True)
        self.btn_stop.setEnabled(False)
        self.lbl_status.setText("Flash failed 🛑")
        QMessageBox.critical(self, "Flash Error", msg)

    def on_stop_clicked(self):
        if self.worker and self.worker.isRunning():
            self.worker.stop()
            self.lbl_status.setText("Stopping active encoding threads...")
            self.btn_stop.setEnabled(False)


class PlayawayConfigWidget(QWidget):
    """Calibre Plugin Preferences Configuration Widget."""
    def __init__(self):
        super().__init__()
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("<h3>⚡ Playaway Audiobook Flasher — Default Configuration</h3>"))
        layout.addWidget(QLabel("Configure default settings for 1-click Quick Flash and default studio values."))

        self.cfg = load_config()

        form = QGridLayout()
        form.addWidget(QLabel("<b>Default Chapter Split Mode:</b>"), 0, 0)
        self.combo_mode = QComboBox()
        self.combo_mode.addItems(["duration", "chapters", "none"])
        self.combo_mode.setCurrentText(self.cfg.get("split_mode", "duration"))
        form.addWidget(self.combo_mode, 0, 1)

        form.addWidget(QLabel("<b>Default Fixed Duration (mins):</b>"), 1, 0)
        self.spin_mins = QSpinBox()
        self.spin_mins.setRange(1, 180)
        self.spin_mins.setValue(int(self.cfg.get("split_mins", 15)))
        form.addWidget(self.spin_mins, 1, 1)

        form.addWidget(QLabel("<b>Default Playback Speed:</b>"), 2, 0)
        self.combo_speed = QComboBox()
        self.combo_speed.addItems(["0.75x", "0.85x", "1.0x (Normal)", "1.1x", "1.25x", "1.5x", "1.75x", "2.0x", "2.5x", "3.0x"])
        def_spd = self.cfg.get("playback_speed", 1.0)
        matched_text = f"{def_spd:.2f}".rstrip('0').rstrip('.') + "x"
        if def_spd == 1.0:
            matched_text = "1.0x (Normal)"
        idx = self.combo_speed.findText(matched_text, Qt.MatchStartsWith if hasattr(Qt, 'MatchStartsWith') else 1)
        if idx >= 0:
            self.combo_speed.setCurrentIndex(idx)
        else:
            self.combo_speed.setCurrentText("1.0x (Normal)")
        form.addWidget(self.combo_speed, 2, 1)

        self.cb_pitch = QCheckBox("Preserve voice pitch with atempo DSP")
        self.cb_pitch.setChecked(bool(self.cfg.get("preserve_pitch", True)))
        form.addWidget(self.cb_pitch, 3, 0, 1, 2)

        self.cb_subchap = QCheckBox("Enable Subchapters (AF* multi-part mode)")
        self.cb_subchap.setChecked(bool(self.cfg.get("subchapter_mode", False)))
        form.addWidget(self.cb_subchap, 4, 0, 1, 2)

        self.cb_silence = QCheckBox("Append 5s silence track (Firmware 01:05 auto-power-off fix)")
        self.cb_silence.setChecked(bool(self.cfg.get("final_chapter_silence", True)))
        form.addWidget(self.cb_silence, 5, 0, 1, 2)

        layout.addLayout(form)
        layout.addStretch()

        btn_reset = QPushButton("🔄 Reset to Factory Defaults", self)
        btn_reset.clicked.connect(self.reset_to_defaults)
        layout.addWidget(btn_reset)

    def reset_to_defaults(self):
        self.combo_mode.setCurrentText(DEFAULT_SETTINGS.get("split_mode", "duration"))
        self.spin_mins.setValue(int(DEFAULT_SETTINGS.get("split_mins", 15)))
        self.combo_speed.setCurrentText("1.0x (Normal)")
        self.cb_pitch.setChecked(bool(DEFAULT_SETTINGS.get("preserve_pitch", True)))
        self.cb_subchap.setChecked(bool(DEFAULT_SETTINGS.get("subchapter_mode", False)))
        self.cb_silence.setChecked(bool(DEFAULT_SETTINGS.get("final_chapter_silence", True)))

    def save_settings(self):
        self.cfg["split_mode"] = self.combo_mode.currentText()
        self.cfg["split_mins"] = self.spin_mins.value()
        raw_spd = self.combo_speed.currentText().split()[0].replace("x", "")
        try:
            self.cfg["playback_speed"] = float(raw_spd)
        except ValueError:
            self.cfg["playback_speed"] = 1.0
        self.cfg["preserve_pitch"] = self.cb_pitch.isChecked()
        self.cfg["subchapter_mode"] = self.cb_subchap.isChecked()
        self.cfg["final_chapter_silence"] = self.cb_silence.isChecked()
        save_config(self.cfg)


class PlayawayHelpDialog(QDialog):
    """Rich Guide & Information Dialog for Playaway Hardware and Plugin Usage."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("📖 Playaway Flasher — User Guide & Settings Reference")
        self.resize(800, 660)

        layout = QVBoxLayout(self)

        help_text = QTextEdit(self)
        help_text.setReadOnly(True)
        help_text.setHtml("""
        <h2>⚡ Playaway Audiobook Flasher — Complete Guide</h2>
        <p>This plugin converts, optimizes, and installs audiobooks directly from your Calibre library onto <b>Playaway AudioBook Players</b> via USB.</p>

        <hr/>
        <h3>🚀 Two Ways to Flash</h3>
        <ul>
            <li><b>⚡ 1-Click Quick Flash (Default Toolbar Click)</b>: Automatically uses your saved default settings (split minutes, speed, pitch, silence track), auto-detects your connected Playaway drive, calculates the optimal auto-fit bitrate, and flashes with a single confirmation click!</li>
            <li><b>🎛️ Custom Flash (Interactive Studio)</b>: Opens the complete studio window allowing you to view and scrub chapter timestamps, fine-tune individual track splits, test playback speeds, manually set bitrates, or export files to a local folder.</li>
        </ul>

        <hr/>
        <h3>⚙️ Settings Reference: What Each Setting Does</h3>
        <table border="1" cellpadding="6" cellspacing="0" style="border-collapse: collapse; width: 100%;">
            <tr style="background-color: #2c3e50; color: white;">
                <th style="width: 28%;">Setting Name</th>
                <th>Description & Best Practices</th>
            </tr>
            <tr>
                <td><b>Chapter Splitting Mode</b></td>
                <td>
                    <b>• Split fixed mins (Recommended)</b>: Cuts the audiobook into equal tracks of your chosen length (e.g. 15–30 mins). Ideal for continuous listening and <i>completely eliminates</i> the Firmware 01:03 88-minute freeze bug.<br><br>
                    <b>• Split by chapter tags</b>: Uses embedded chapter markers inside <code>.m4b</code> or <code>.mp3</code> files to create discrete tracks matching book chapters.<br><br>
                    <b>• Keep single track as-is</b>: Keeps the entire audiobook as one single audio track. <i>(Warning: Tracks &gt;88m may freeze older players).</i>
                </td>
            </tr>
            <tr>
                <td><b>Fixed Duration (mins per track)</b></td>
                <td>Number of minutes per track when using Fixed Duration mode. Typical values are <b>15 to 30 minutes</b>. Shorter tracks make fast-forwarding and rewinding on hardware buttons faster and easier.</td>
            </tr>
            <tr>
                <td><b>Playback Speed (0.75x–3.0x)</b></td>
                <td>Pre-renders the audiobook at a faster or slower listening speed before flashing. Increasing playback speed (e.g. <b>1.25x</b> or <b>1.5x</b>) shortens total duration and <b>proportionally reduces file size</b> (e.g., 1.5x reduces storage by 33%), allowing larger books to fit into smaller players!</td>
            </tr>
            <tr>
                <td><b>Preserve Voice Pitch (atempo DSP)</b></td>
                <td>When playback speed is changed, this applies an advanced phase vocoder DSP filter so the narrator's voice remains at its natural vocal pitch, preventing high-pitched 'chipmunk' distortion.</td>
            </tr>
            <tr>
                <td><b>Bitrate & ⚡ Auto-Fit (10–36 kbps)</b></td>
                <td>AMR-WB+ audio bitrate in kilobits per second. Higher bitrates offer higher clarity. Clicking <b>⚡ Auto-Fit</b> automatically calculates and sets the maximum possible bitrate that will fit your entire audiobook onto the target Playaway storage without running out of space!</td>
            </tr>
            <tr>
                <td><b>Enable Subchapters (AF* multi-part)</b></td>
                <td>Enables sequential subchapter indexing inside the <code>PATWEAKS.DAT</code> configuration header for Playaway hardware that supports sub-part navigation.</td>
            </tr>
            <tr>
                <td><b>Append 5s Silence Track (Firmware 01:05 fix)</b></td>
                <td>Appends a small 5-second silent track (<code>end_silence</code>) to the end of the playlist. Solves a known hardware bug on Firmware 01:05 players where playback halts at the end of the book but the LCD screen stays on, draining the AAA battery. The silence track allows the player to safely trigger its automatic power-off!</td>
            </tr>
            <tr>
                <td><b>💾 Save as Default</b></td>
                <td>Saves your current splitting mode, duration, speed, pitch, and silence preferences into Calibre's configuration. These defaults will be automatically applied every time you use <b>1-Click Quick Flash</b>!</td>
            </tr>
        </table>

        <hr/>
        <h3>🔌 Hardware Setup (USB Test Pads)</h3>
        <p>Playaway players have internal PCB test pads intended for factory programming. You can solder a USB-C breakout board or cable to these 4 pads:</p>
        <table border="1" cellpadding="6" cellspacing="0" style="border-collapse: collapse; width: 100%;">
            <tr style="background-color: #2c3e50; color: white;">
                <th>Pad Label</th><th>Signal</th><th>USB Pin / Wire Color</th>
            </tr>
            <tr><td><b>VBUS / VCC</b></td><td>+5V USB Power</td><td>Pin 1 (Red)</td></tr>
            <tr><td><b>D- / DM</b></td><td>USB Data Minus</td><td>Pin 2 (White)</td></tr>
            <tr><td><b>D+ / DP</b></td><td>USB Data Plus</td><td>Pin 3 (Green)</td></tr>
            <tr><td><b>GND</b></td><td>Ground</td><td>Pin 4 (Black)</td></tr>
        </table>
        <p><b>⚠️ Battery Notice:</b> Flashing was tested and verified <b>without the AAA battery inserted</b> (the player is powered directly over USB 5V VBUS). Flashing with the battery installed is currently untested.</p>

        <hr/>
        <h3>⚠️ Critical Firmware Bugs & Gotchas</h3>
        <ul>
            <li><b>Firmware 01:03 (~88m Single Track Freeze)</b>: On older Graphics models running Firmware 01:03, single audio tracks longer than ~88 minutes cause the player to freeze during playback. Splitting chapters into 15–30 minute tracks completely bypasses this limitation!</li>
            <li><b>Firmware 01:05 (Auto-Power-Off Bug)</b>: Certain Firmware 01:05 players fail to auto power off after the final audio track, draining the battery. The plugin automatically appends a 5-second silence track (<code>end_silence</code>) to ensure clean automatic shutdown.</li>
            <li><b>Strict Mono Only</b>: The Playaway microcontroller only plays mono audio. Stereo tracks will be silently skipped. All audio is automatically converted to mono 16-bit 44.1kHz PCM before AMR-WB+ encoding.</li>
        </ul>

        <hr/>
        <h3>💾 Storage & Playtime Capacity Guide</h3>
        <ul>
            <li><b>128 MB Flash (~105 MB usable)</b>:
                <ul>
                    <li>10 kbps: <b>~23 hours</b> playtime</li>
                    <li>16 kbps: <b>~14.5 hours</b> playtime</li>
                    <li>36 kbps: <b>~6.5 hours</b> playtime</li>
                </ul>
            </li>
            <li><b>256 MB Flash (~230 MB usable)</b>:
                <ul>
                    <li>10 kbps: <b>~50 hours</b> playtime</li>
                    <li>16 kbps: <b>~31 hours</b> playtime</li>
                </ul>
            </li>
        </ul>
        """)
        layout.addWidget(help_text)

        btn_box = QHBoxLayout()
        btn_box.addStretch()
        btn_close = QPushButton("Close", self)
        btn_close.clicked.connect(self.close)
        btn_box.addWidget(btn_close)
        layout.addLayout(btn_box)
