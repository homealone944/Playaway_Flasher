#!/usr/bin/env python3
"""
action.py - Calibre Interface Action Toolbar & Context Menu Handler
Hooks into Calibre's UI to trigger Playaway flashing from selected library books.
"""

import os
from calibre.gui2.actions import InterfaceAction
try:
    from calibre_plugins.playaway_flasher.core_bridge import get_audiobook_formats_for_book, detect_playaway_drives
    from calibre_plugins.playaway_flasher.dialog import (
        PlayawayDialog,
        QuickFlashDialog,
        PlayawayHelpDialog,
        PlayawayConfigWidget
    )
except (ImportError, ValueError):
    try:
        from .core_bridge import get_audiobook_formats_for_book, detect_playaway_drives
        from .dialog import (
            PlayawayDialog,
            QuickFlashDialog,
            PlayawayHelpDialog,
            PlayawayConfigWidget
        )
    except (ImportError, ValueError):
        from core_bridge import get_audiobook_formats_for_book, detect_playaway_drives
        from dialog import (
            PlayawayDialog,
            QuickFlashDialog,
            PlayawayHelpDialog,
            PlayawayConfigWidget
        )

try:
    from qt.core import QMessageBox, QIcon, QPixmap, QMenu, QToolButton, QDialog, QVBoxLayout, QPushButton
except ImportError:
    from PyQt5.QtWidgets import QMessageBox, QMenu, QToolButton, QDialog, QVBoxLayout, QPushButton
    from PyQt5.QtGui import QIcon, QPixmap


class PlayawayAction(InterfaceAction):
    name = 'Playaway Flash'
    action_spec = ('Playaway Flash', 'images/icon.png', 'Quick flash selected audiobook using saved defaults', 'Ctrl+Shift+P')
    action_type = 'current'
    dont_add_to = frozenset()
    dont_remove_from = frozenset()
    popup_type = getattr(QToolButton.ToolButtonPopupMode, 'MenuButtonPopup', getattr(QToolButton, 'MenuButtonPopup', 1))

    def genesis(self):
        self.qaction.setText('Playaway Flash')
        icon = self.load_icon()
        if icon:
            self.qaction.setIcon(icon)

        self.menu = QMenu(self.gui)
        self.qaction.setMenu(self.menu)

        # Dropdown Action 1: Quick Flash
        a_quick = self.menu.addAction('⚡ Quick Flash to Playaway')
        a_quick.setToolTip('Flash selected audiobook directly using your saved default settings')
        a_quick.triggered.connect(self.run_quick_flash)

        # Dropdown Action 2: Custom Flash
        a_custom = self.menu.addAction('🎛️ Custom Flash (Interactive Setup)...')
        a_custom.setToolTip('Open full interactive studio to preview chapters, tweak splits, speed, and bitrates')
        a_custom.triggered.connect(self.run_custom_flash)

        self.menu.addSeparator()

        # Dropdown Action 3: Settings
        a_settings = self.menu.addAction('⚙️ Plugin Default Settings...')
        a_settings.triggered.connect(self.show_settings_dialog)

        # Dropdown Action 4: Detect Drives
        a_drives = self.menu.addAction('🔌 Detect Connected Playaway USB Drives')
        a_drives.triggered.connect(self.show_drives_dialog)

        # Dropdown Action 5: Help & Hardware Guide
        a_help = self.menu.addAction('📖 Playaway User Guide & Hardware Info')
        a_help.triggered.connect(self.show_help_dialog)

        # Main toolbar click triggers 1-Click Quick Flash by default
        self.qaction.triggered.connect(self.run_quick_flash)

    def initialization_complete(self):
        """Ensure action button is always present on Calibre main toolbar and menubar."""
        try:
            # Force add to main toolbar if not already present in cached layout
            if hasattr(self.gui, 'bars_manager') and hasattr(self.gui.bars_manager, 'main_bars'):
                main_bar = self.gui.bars_manager.main_bars.get('main')
                if main_bar and self.qaction not in main_bar.actions():
                    main_bar.addAction(self.qaction)
        except Exception:
            pass

    def show_help_dialog(self):
        dlg = PlayawayHelpDialog(self.gui)
        dlg.exec_()

    def show_drives_dialog(self):
        drives = detect_playaway_drives()
        if not drives:
            QMessageBox.information(
                self.gui,
                "Playaway Drive Detection",
                "<b>No Playaway USB drives detected.</b><br><br>"
                "Please connect your Playaway via USB (or test pads) and verify it appears as a FAT/FAT32 removable drive."
            )
            return

        lines = []
        for d in drives:
            tag = " [Playaway Verified ✓]" if d["is_playaway"] else ""
            lines.append(f"• <b>{d['path']}</b> ({d['label']}) — {d['free_mb']} MB free{tag}")

        QMessageBox.information(
            self.gui,
            "Connected Playaway Drives",
            f"Found {len(drives)} drive(s):<br><br>" + "<br>".join(lines)
        )

    def show_settings_dialog(self):
        dlg = QDialog(self.gui)
        dlg.setWindowTitle("Playaway Flasher — Default Configuration")
        dlg.resize(480, 360)
        layout = QVBoxLayout(dlg)
        w = PlayawayConfigWidget()
        layout.addWidget(w)
        btn_save = QPushButton("💾 Save Configuration", dlg)
        btn_save.clicked.connect(lambda: (w.save_settings(), dlg.accept()))
        layout.addWidget(btn_save)
        dlg.exec_()

    def load_icon(self):
        try:
            from calibre.gui2 import get_icons
            return get_icons('images/icon.png')
        except Exception:
            pass

        try:
            icon_bytes = self.interface_action_base_plugin.load_resources(['images/icon.png']).get('images/icon.png')
            if icon_bytes:
                pix = QPixmap()
                pix.loadFromData(icon_bytes)
                return QIcon(pix)
        except Exception:
            pass
        return None

    def get_selected_book_audio(self):
        gui = self.gui
        db = gui.current_db

        book_ids = []
        if hasattr(gui.library_view, 'get_selected_ids'):
            book_ids = gui.library_view.get_selected_ids()

        if not book_ids:
            rows = gui.library_view.selectionModel().selectedRows()
            if rows:
                for r in rows:
                    try:
                        bid = gui.library_view.model().id(r.row())
                    except Exception:
                        try:
                            bid = gui.library_view.model().id(r)
                        except Exception:
                            bid = None
                    if bid:
                        book_ids.append(bid)

        if not book_ids:
            QMessageBox.information(
                gui,
                "No Book Selected",
                "Please select an audiobook in your Calibre library first."
            )
            return None

        book_id = book_ids[0]
        try:
            mi = db.get_metadata(book_id, index_is_id=True)
            book_title = mi.title if mi and mi.title else "Audiobook"
        except Exception:
            book_title = "Audiobook"

        formats = get_audiobook_formats_for_book(db, book_id)
        if not formats:
            QMessageBox.warning(
                gui,
                "No Audio Format Found",
                f"The selected book <b>'{book_title}'</b> does not have any supported audio files (.m4b, .mp3, .m4a, .flac, .wav, .aac) in your Calibre library.\n\n"
                "Please add an audio file format to this book record in Calibre before flashing."
            )
            return None

        primary_fmt = "M4B" if "M4B" in formats else next(iter(formats))
        primary_path = formats[primary_fmt]

        return {
            "book_id": book_id,
            "book_title": book_title,
            "formats": formats,
            "primary_path": primary_path
        }

    def run_quick_flash(self):
        """1-Click Quick Flash using saved defaults."""
        info = self.get_selected_book_audio()
        if not info:
            return

        dlg = QuickFlashDialog(
            gui=self.gui,
            book_id=info["book_id"],
            book_title=info["book_title"],
            audio_path=info["primary_path"],
            available_formats=info["formats"]
        )
        dlg.exec_()

    def run_custom_flash(self):
        """Full interactive custom studio dialog."""
        info = self.get_selected_book_audio()
        if not info:
            return

        dlg = PlayawayDialog(
            gui=self.gui,
            book_id=info["book_id"],
            book_title=info["book_title"],
            audio_path=info["primary_path"],
            available_formats=info["formats"]
        )
        dialog = dlg
        dialog.exec_()
