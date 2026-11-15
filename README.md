# Music Downloader & Metadata Skill

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](./LICENSE)
[![Agent Skills](https://img.shields.io/badge/Agent_Skills-Compatible-blue.svg)](https://agentskills.io)
[![Platforms](https://img.shields.io/badge/OS-Windows%20%7C%20macOS-lightgrey.svg)](#cli-usage-scriptsdj_dlpy)

A universal, cross-platform (**Windows & macOS**) AI agent skill for anyone who wants clean, high-quality local music files. Give any AI a **Spotify**, **Apple Music**, **SoundCloud**, **YouTube**, **Bandcamp**, or **Mixcloud** link, a **plain-text tracklist**, or **song screenshots**, and it extracts metadata, verifies durations and artwork, and outputs **320 kbps MP3s** with clean **ID3v2.3 tags** and **square cover art**—ready for **offline listening, Apple Music / Plex / Android / iPod / car USBs, and DJ software** (Rekordbox, Serato, Traktor, Engine DJ, VirtualDJ).

Works across **Claude**, **ChatGPT / Codex**, **Gemini / Antigravity**, **Cursor**, **GitHub Copilot**, and any agent supporting the open [Agent Skills](https://agentskills.io) standard.

---

## Install

### Option 1: Ask Your AI Agent (Recommended)
Paste this into **Claude Code**, **Codex**, **Gemini / Antigravity**, or **Cursor**:

```text
Install the dj-music-downloader skill from https://github.com/byohros6/dj-music-downloader-skill and run doctor to check dependencies.
```

### Option 2: One-Command CLI (`skills`)
Works across Claude Code, Codex, Gemini CLI, Antigravity, Cursor, and Copilot:

```bash
npx skills add byohros6/dj-music-downloader-skill
```

### Option 3: Manual Drop-In (2 Files)
Copy `.agents/skills/dj-music-downloader/` (containing only `SKILL.md` and `scripts/dj_dl.py`) into any of these directories:

| AI / Tool | Project Path | Global User Path |
| :--- | :--- | :--- |
| **Universal / Codex / Gemini / Antigravity** | `.agents/skills/dj-music-downloader/` | `~/.agents/skills/dj-music-downloader/` |
| **Claude Code** | `.claude/skills/dj-music-downloader/` | `~/.claude/skills/dj-music-downloader/` |
| **Codex CLI** | `.agents/skills/dj-music-downloader/` | `~/.codex/skills/dj-music-downloader/` |
| **Gemini CLI / Antigravity** | `.agents/skills/dj-music-downloader/` | `~/.gemini/skills/dj-music-downloader/` |
| **ChatGPT / Claude Web UI** | Upload `SKILL.md` + `scripts/dj_dl.py` directly | — |

---

## Supported Sources & Players

* **Inputs:** Spotify (public playlists, albums, tracks), Apple Music, SoundCloud (tracks, sets, edits), YouTube & YouTube Music, Bandcamp, Mixcloud, plain-text tracklists, and screenshots.
* **Works Everywhere:** Apple Music / iTunes local libraries, Plex / Plexamp, car stereo USB sticks, Walkmans / DAPs, phones, plus **Rekordbox**, **Serato**, **Traktor**, **Engine DJ**, and **VirtualDJ**.
* **Audio Specs:** `320 kbps` CBR MP3 (`libmp3lame`), `44.1 kHz`, `16-bit` stereo, `ID3v2.3` (`TIT2`, `TPE1`, `TALB`, `TCON`, `TDRC`, `APIC`), NFC-normalized cross-platform filenames.

---

## Key Safeguards

1. **Strict Length Matching:** Verifies track duration against source metadata (`±8s` default), refuses full mixes or short clips, and flags mismatches instead of silently grabbing the wrong version.
2. **Scored Metadata & Artwork Checks:** Scores Deezer and iTunes candidates by artist, title, version keywords, and duration rather than blindly grabbing result `#1`, then validates image resolution and square aspect ratio.
3. **Asks Before Acting:** Confirms destination folders, track numbering (`--index`), `.wav` handling (`_original_wav/` backup vs delete vs leave untouched), and any duration/artwork warnings before modifying files.
4. **Zero Temp Bloat:** Downloads and transcodes inside auto-cleaning temporary directories so only the final `.mp3` files (`~8–12 MB` each) stay on disk, and checks available drive space before starting.
5. **Library Repair (`audit`):** Detects and optionally fixes `.mp3.mpeg` / `.m4a.mp4` double extensions, untagged `.wav` files, and missing or non-square cover art.

---

## CLI Usage (`scripts/dj_dl.py`)

Use `python` on Windows or `python3` on macOS/Linux:

```bash
# 1. Check / install dependencies (yt-dlp, mutagen, requests, portable ffmpeg)
python .agents/skills/dj-music-downloader/scripts/dj_dl.py doctor --install

# 2. Extract tracks JSON from Spotify, Apple Music, SoundCloud, YouTube, Bandcamp, etc.
python .agents/skills/dj-music-downloader/scripts/dj_dl.py extract "<url>" -o tracks.json

# 3. Download, transcode to 320 kbps MP3, enrich tags/art, and verify lengths
python .agents/skills/dj-music-downloader/scripts/dj_dl.py download -i tracks.json -o "~/Music/My Playlist"

# 4. Read-only audit of an existing music folder (add --fix-ext / --convert-wav after confirming)
python .agents/skills/dj-music-downloader/scripts/dj_dl.py audit "/path/to/Music Folder"
```

---

## Legal Disclaimer & License

This repository provides **code and AI workflow instructions only**—it does **not** host, distribute, or bundle copyrighted audio files, `ffmpeg` binaries, or DRM circumvention tools.

* Intended for **personal archival, royalty-free / Creative Commons releases, promotional free downloads, and media you have the right to download and store locally**.
* Users are solely responsible for complying with applicable copyright laws and the Terms of Service of any third-party platform.
* Released under the [MIT License](./LICENSE) (`"AS IS"`, without warranty or liability). Runtime dependencies (`yt-dlp`, `mutagen`, `requests`, and optionally `imageio-ffmpeg`) are installed separately by the user under their own respective licenses.
