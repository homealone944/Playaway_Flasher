# ⚡ Playaway Audiobook Studio & Flasher

A complete, feature-packed toolkit for installing your own audiobooks onto **Playaway AudioBook Players** via USB. 

Supports both a modern, dark-themed **Graphical Interface (GUI)** for desktop users and a power-user **Command Line Interface (CLI)** for terminal workflow automation on Windows, Linux, and macOS.

---

## 🛠️ Features

### 🎬 Embedded LibVLC Media Player & Scrubber
- **Native LibVLC Player Engine**: Powered by `python-vlc` for hardware-accelerated, zero-latency audio playback directly inside Card 2.
- **⏯️ Unified Play / Pause Toggle**: Click `▶ Play` to stream full chapter audio; dynamically switches to `⏸ Pause` while playing.
- **⏱️ Millisecond-Accurate Timeline Seeking**: Full-width position slider (`Position: 01:23 / 15:45 @ 1.5x`) allows instant 0ms seeking anywhere within multi-hour audiobooks (`set_time(target_ms)`).
- **🔊 Dedicated Volume Control**: Spacious 160px volume slider (`Volume: 0% to 100%`) controlling playback output.
- **📊 Speed-Adjusted Dynamic Timeframes**: Table columns (`Timeframe` & `Length`) dynamically recalculate effective listening durations and timestamps in real-time based on your configured **Playback Speed** (0.75x to 3.0x).

### ✂️ Interactive Chapter Editing & Exclusion Suite
- **✂️ Split Chapter at Scrubber Position**: Cut any selected chapter track into two separate sub-tracks at your scrubber position. Prompts for custom Part 2 track names (pre-filled with `Chapter ##_pt2`), allowing you to isolate and exclude ending credits, bloopers, or publisher intros!
- **🗑️ Exclude / Include Track**: Toggle exclusion of unwanted tracks (`❌ Excluded` in red). Total audiobook playtime, estimated size, and sequential `PATWEAKS.DAT` numbering auto-adjust dynamically!
- **🔄 Restore All Tracks**: Re-enable all excluded tracks across the entire audiobook with one click.
- **🔁 Reset Chapters from Source**: Re-parse original chapter markers from source files/folders, clearing custom splits and restoring original track layout.
- **📐 Dynamic Table Auto-Sizing & Selection Persistence**: Chapter table columns auto-calculate pixel widths based on content lengths without text truncation. Changing audio settings (speed, split mode, pitch, track exclusions) preserves your active chapter selection seamlessly!

### 🎠️ Audio Quality & Playback Speed Controls
- **⏩ Expanded Playback Speed (0.75x to 3.0x)**: Speed up or slow down audiobooks prior to encoding using pitch-preserving DSP filters (`atempo`). Speeds like 1.25x, 1.5x, 2.0x, or 2.5x reduce file size proportionally.
- 🔇 **Add 5s End Silence Track Checkbox (`final_chapter_silence`)**: Appends a 5.0-second silent track (`end_silence`) to the end of your audiobook track list.
  > **Why this is necessary (Firmware 01:05 Bug Workaround)**: On certain Playaway hardware models (such as Graphics units running Firmware 01:05), the SoC microcontroller stops playback at the end of the final audio track, but **fails to auto power off** — leaving the LCD screen on and draining the AAA battery. Adding a dedicated 5-second silence track mitigates this bug: after playing the final silent track, the Playaway powers off automatically and correctly!
- ⏳ **Firmware 01:03 ~1h28m Track Freeze Safety**:
  > **Firmware 01:03 Single-Track Bug**: On older Graphics models running Firmware 01:03, single audio tracks longer than 1 hour 28 minutes (88 mins) cause the decoder to freeze playback and fail to power off. Setting **Chapter Splitting Mode** to `Split into fixed duration (15–60 mins)` bypasses this limitation while providing smooth continuous track playback!
  >
  > **🔍 How to Check Your Firmware Version**:
  > 1. **On-Screen Button Combination**: Turn off the player $\rightarrow$ Hold `SPD` (Speed) or `<<` (Reverse) while pressing `POWER` (or hold `POWER` + `PLAY` for 3s on boot). The LCD display will briefly flash `01:03` or `01:05`.
  > 2. **Battery Compartment Sticker**: Open the AAA battery door and inspect the white model/rev sticker inside the compartment.
- **⚡ Dynamic "Auto" Bitrate Mode (`"bitrate_kbps": "auto"`)**: When set to `"auto"`, the app automatically calculates the optimal encoding bitrate (10 to 36 kbps) every time an audiobook is loaded or drive target changes. Manually moving the bitrate slider switches to `(Manual)` mode and persists your chosen numeric bitrate (e.g. `24`).
- **💾 Settings Management**: Save favorite chapter tweaks, speed, pitch, subchapter mode, end silence preference, and bitrate mode to `playaway_config.json` via **💾 Save Settings**, restore saved configs anytime with **📂 Load Saved**, or reset to factory defaults via **🔄 Reset Defaults**.

### 🛡️ Storage Safety & Flashing Engine
- **🧹 Deep Clean & System Sync**: Purges factory `CMI_CRC.DAT`, `.SAV` / `.DAT` bookmark state files, old `.awb` tracks, and hidden OS junk files (`.DS_Store`, `desktop.ini`, `._*`) so FAT table reading order remains clean for the embedded microcontroller before writing new audio and flushing volume buffers.
- **🛡️ System Drive & Size Protection**: Strictly blocks selection of `C:\` system drives and storage units > 2GB to prevent accidental hard drive wiping.
- **📥 1-Click Playaway Backup**: Save all audio tracks, configuration headers (`PATWEAKS.DAT`), and system files from your connected Playaway device to your computer before flashing.
- **📁 Export to Local Folder**: Generate Playaway `.awb` files, `PATWEAKS.DAT`, and a step-by-step `README_HOW_TO_COPY.txt` manual copy guide to any local directory on your PC.
- **🚀 Multi-Threaded Parallel Encoding**: Encodes multiple audio tracks simultaneously (4x–8x speedup using all CPU cores).

---

## 🔌 Hardware Setup: Connecting USB to Test Pads

Playaway players have internal PCB test pads intended for factory programming. You can solder a **USB-C breakout board** or USB cable to these test pads:

1. Open the Playaway casing (remove battery door and sticker screws).
2. Locate the test pads on the PCB (typically labeled `JP1` or marked with `+`, `-`, `D+`, `D-`).
3. Solder 4 connections:
   - **VBUS (+5V)** -> `5V` / `VBUS` pad
   - **D- (Data Minus)** -> `D-` pad
   - **D+ (Data Plus)** -> `D+` pad
   - **GND (Ground)** -> `GND` / `-` pad
4. (Optional) Mount a USB-C female port into the plastic casing.
5. **Battery Notice**: Flashing was tested and verified **without the AAA battery inserted** (the player is powered directly from USB 5V VBUS). Flashing with the battery installed is currently untested.

---

## 🚀 How to Run

### 1. Graphical Window Interface (Desktop Users)
Double-click `playaway_studio.py` or run:
```bash
python playaway_studio.py
# OR
python playaway_gui.py
```

#### GUI Step-by-Step:
1. **Backup Existing Book**: Select target drive and click **📥 Backup Playaway** to save all files from the player to your computer.
2. **Select Audiobook Source**: Click **Browse File** (to select `.m4b`, `.mp3`, `.flac`, `.wav`, etc.) or **Browse Folder**.
3. **Chapter Tweaks & Quality**:
   - Choose chapter split mode (e.g. Split by embedded chapter tags or every 15 minutes).
   - Use **`✂️ Split Chapter at Scrubber`** inside Card 2 to isolate and exclude credits!
   - Choose playback speed (e.g. `1.25x` speed).
   - Adjust bitrate slider (or click **⚡ Auto-Fit Bitrate**).
4. **Select Playaway USB Drive**: Choose your connected Playaway drive from the dropdown.
5. **Flash**: Click **⚡ Wipe & Flash Playaway**.

---

### 2. Command Line Interface (CLI)

#### Scan for Connected Playaway Drives:
```bash
python playaway_studio.py detect
```

#### Backup Existing Playaway Files to Local Folder:
```bash
python playaway_studio.py backup -d E:\ -o "./backups/original_book"
```

#### Convert Audiobook with 1.25x Speed Adjustment:
```bash
python playaway_studio.py convert -i "MyBook.m4b" -o "./staging" --split-mins 15 --bitrate 10 --speed 1.25
```

#### Direct 1-Command Flash to Playaway at 1.25x Speed:
```bash
python playaway_studio.py flash -i "MyBook.m4b" -d E:\ --split-mins 15 --bitrate 10 --speed 1.25 -y
```

#### Fetch/Verify 3GPP Encoder Binaries:
```bash
python playaway_studio.py fetch-encoder
```

---

### 3. 📚 Calibre Plugin (Direct Library Integration)

Flash audiobooks directly from your **Calibre** library with one click!

#### 📦 Download & Installation:
1. **Download the Plugin**:
   - Download the latest **[`Calibre_Playaway_Flasher.zip`](https://github.com/homealone944/Playaway_Flasher/releases)** from the [GitHub Releases](https://github.com/homealone944/Playaway_Flasher/releases) page.
   - *Or build from source*: Run `python calibre_plugin/build_plugin.py` to generate `dist/Calibre_Playaway_Flasher.zip`.

2. **Install into Calibre**:
   - Open **Calibre** $\rightarrow$ Click **Preferences** (<kbd>Ctrl</kbd>+<kbd>P</kbd>) $\rightarrow$ **Plugins** (under *Advanced*).
   - Click the **"Load plugin from file"** button in the bottom right.
   - Select `Calibre_Playaway_Flasher.zip`.
   - Click **Yes** on the security warning and **restart Calibre**.

3. **Usage in Calibre**:
   - Select an audiobook in your Calibre library (with an attached `.m4b`, `.mp3`, `.m4a`, `.flac`, `.wav`, etc.).
   - **⚡ 1-Click Quick Flash**: Click **"Playaway Flash"** on your toolbar (or press <kbd>Ctrl</kbd>+<kbd>Shift</kbd>+<kbd>P</kbd>) to instantly wipe and flash using your saved defaults!
   - **🎛️ Custom Flash Studio**: Click the dropdown arrow on the toolbar button $\rightarrow$ **"🎛️ Custom Flash (Interactive Setup)..."** to scrub chapter timestamps, fine-tune splits, adjust speeds, and manually set bitrates.
   - **⚙️ Plugin Settings**: Configure global defaults (fixed split minutes, chapter tags, playback speed, pitch preservation, and silence tracks) via the dropdown menu or Calibre's Plugin Preferences.
   - **📖 Help Guide**: Access the built-in hardware wiring guide, pinouts, and firmware bug documentation directly from the toolbar dropdown.

---

## 📌 Critical Gotchas & Storage Reference

1. **Mono Audio**: Playaway hardware *only* plays mono audio. Stereo audio will cause the player to skip tracks silently. The tool automatically forces mono conversion.
2. **Root Directory Only**: Audio files (`.awb`) and `PATWEAKS.DAT` are written directly to the drive's root folder (`E:\`), never inside subfolders.
3. **Storage vs. Bitrate Guide**:
   - **128 MB Flash (~105 MB usable)**:
     - 10 kbps: **~23 hours** playtime
     - 16 kbps: **~14.5 hours** playtime
     - 36 kbps: **~6.5 hours** playtime
   - **256 MB Flash (~230 MB usable)**:
     - 10 kbps: **~50 hours** playtime
     - 16 kbps: **~31 hours** playtime

---

## 📁 File Structure

- `playaway_studio.py`: Main launcher supporting GUI mode and CLI subcommands.
- `playaway_gui.py`: Dark-themed Tkinter GUI desktop window interface with embedded LibVLC media player suite.
- `playaway_core.py`: Core processing engine (drive detection, audio conversion, chapter planner, PATWEAKS generator, flasher).
- `calibre_plugin/`: Native Calibre plugin integration (UI actions, Qt dialogs, packaging builder).
- `fetch_encoder.py`: Automated setup helper for official 3GPP AMR-WB+ encoder binaries.
- `tools/`: Directory holding `encoder.exe` and `er-libisomedia.dll`.
- `dist/`: Directory containing built `Calibre_Playaway_Flasher.zip` Calibre plugin package.

---

## 📚 Sources & Acknowledgements

- **Original Project / Reference**: [lanmarc77/playaway](https://github.com/lanmarc77/playaway) – Original Playaway reverse-engineering research, encoder setup guide, and documentation.


