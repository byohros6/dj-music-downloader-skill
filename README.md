# DJ Music Downloader Skill

A universal, cross-platform (**Windows & macOS**) AI agent skill for DJs. Give any AI a **Spotify**, **Apple Music**, **SoundCloud**, **YouTube**, **Bandcamp**, or **Mixcloud** link, a **plain-text tracklist**, or **screenshots of songs**, and it downloads, verifies durations and artwork, and exports **Rekordbox- and CDJ-ready 320 kbps MP3s** with clean **ID3v2.3 tags** and **square cover art**.

Works across **Claude**, **ChatGPT / Codex**, **Gemini / Antigravity**, **Cursor**, **GitHub Copilot**, and any agent supporting the open [Agent Skills](https://agentskills.io) format.

*(Companion standalone desktop app specification/project: [DeckPrep](https://github.com/byohros6/DeckPrep).)*

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

## Supported Sources & DJ Software

* **Inputs:** Spotify (public playlists, albums, tracks), Apple Music, SoundCloud (sets, bootlegs, edits), YouTube & YouTube Music, Bandcamp, Mixcloud, plain-text tracklists, and song/playlist screenshots.
* **DJ Compatibility:** Pioneer **Rekordbox** (DDJ-FLX4, CDJ/XDJ standalone), **Serato DJ**, **Traktor**, **Engine DJ**, **VirtualDJ**, and **djay Pro**.
* **Audio Specs:** `320 kbps` CBR MP3 (`libmp3lame`), `44.1 kHz`, `16-bit` stereo, `ID3v2.3` (`TIT2`, `TPE1`, `TALB`, `TCON`, `TDRC`, `APIC`), NFC-normalized cross-platform filenames.

---

## Key Safeguards

1. **Strict Length Matching:** Verifies track duration against source metadata (`±8s` default), rejects full DJ sets or snippets, and flags mismatches instead of silently downloading the wrong mix.
2. **Scored Metadata & Artwork Checks:** Scores Deezer and iTunes candidates by artist, title, mix/remix descriptors, and duration rather than blindly grabbing result `#1`, then validates image resolution and square aspect ratio.
3. **Asks Before Acting:** Always confirms destination folders, track numbering (`--index`), `.wav` handling (`_original_wav/` backup vs delete vs leave untouched), and any duration/artwork warnings before modifying files.
4. **Zero Temp Bloat:** Downloads and transcodes inside auto-cleaning temporary directories so only the final `.mp3` files (`~8–12 MB` each) stay on disk, and checks available drive space before starting.
5. **Library Repair (`audit`):** Detects and optionally repairs `.mp3.mpeg` / `.m4a.mp4` double extensions, untagged `.wav` files, and missing or non-square cover art.

---

## CLI Usage (`scripts/dj_dl.py`)

Use `python` on Windows or `python3` on macOS/Linux:

```bash
# 1. Check / install dependencies (yt-dlp, mutagen, requests, portable ffmpeg)
python .agents/skills/dj-music-downloader/scripts/dj_dl.py doctor --install

# 2. Extract tracks JSON from Spotify, Apple Music, SoundCloud, YouTube, Bandcamp, etc.
python .agents/skills/dj-music-downloader/scripts/dj_dl.py extract "<url>" -o tracks.json

# 3. Download, transcode to 320 kbps MP3, enrich tags/art, and verify lengths
python .agents/skills/dj-music-downloader/scripts/dj_dl.py download -i tracks.json -o "~/Music/DJ Music/My Set"

# 4. Read-only audit of an existing DJ folder (add --fix-ext / --convert-wav after confirming)
python .agents/skills/dj-music-downloader/scripts/dj_dl.py audit "/path/to/DJ Folder"
```
