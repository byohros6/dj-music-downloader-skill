---
name: dj-music-downloader
description: >-
  Universal DJ music downloader, metadata enricher, and library auditor for
  Windows and macOS. Accepts Spotify, Apple Music, SoundCloud, YouTube,
  YouTube Music, Bandcamp, Mixcloud, plain-text tracklists, or song
  screenshots and outputs 320 kbps 44.1 kHz stereo MP3s with ID3v2.3 tags,
  verified square cover artwork, and strict mix/duration matching ready for
  Rekordbox, Serato, Traktor, Engine DJ, VirtualDJ, CDJs, and controllers. Use
  whenever a user asks to download songs, playlists, sets, bootlegs, or
  tracklists for DJing, fix unplayable `.mp3.mpeg`/`.wav` files, or audit DJ
  audio tags.
---

# DJ Music Downloader

Cross-platform (Windows & macOS) workflow that turns any music link, set,
tracklist, or screenshot into **320 kbps 44.1 kHz stereo MP3s** with
**ID3v2.3 tags** and **verified square cover artwork**, compatible with
Rekordbox, Serato, Traktor, Engine DJ, VirtualDJ, djay Pro, and Pioneer
CDJ/XDJ/DDJ gear.

Locate `scripts/dj_dl.py` next to this `SKILL.md` file. Run commands with
`python` on Windows or `python3` on macOS/Linux.

| Goal | Command |
| :--- | :--- |
| **Check / install deps** | `python <skill_dir>/scripts/dj_dl.py doctor --install` |
| **Extract any music URL** | `python <skill_dir>/scripts/dj_dl.py extract "<url>" -o /tmp/tracks.json` |
| **Download & tag batch** | `python <skill_dir>/scripts/dj_dl.py download -i /tmp/tracks.json -o "<dir>"` |
| **Read-only folder audit** | `python <skill_dir>/scripts/dj_dl.py audit "<dir>"` |
| **Repair extensions / WAVs** | `python <skill_dir>/scripts/dj_dl.py audit "<dir>" --fix-ext [--convert-wav [--delete-wav]]` |

Default output directory (ask to confirm first): `~/Music/DJ Music/<Playlist Name>`.

---

## Ask Before Acting (Required Confirmations)

Never silently make destructive, storage-heavy, or preference decisions. Ask the
user clearly when any of these apply:

1. **Destination folder & disk space:** Confirm where to save files if not
   specified (suggest `~/Music/DJ Music/<Playlist Name>`, or an external drive if
   system free space is tight).
2. **Track numbering (`--index`):** Ask whether to prefix filenames (`001. Artist - Title.mp3`), especially when a playlist contains multiple mixes/versions of the same track.
3. **`.wav` files found during `audit`:** Always run read-only `audit` first. If
   `.wav` files exist, ask the user before converting:
   * Convert to tagged 320 kbps `.mp3` and back up originals in `_original_wav/` (`--convert-wav`)
   * Convert to `.mp3` and delete the original `.wav` files to save space (`--convert-wav --delete-wav`)
   * Leave `.wav` files untouched
4. **Broken extensions & metadata repairs:** Report exact issues found by `audit`
   before running `--fix-ext` or re-tagging existing files.
5. **Private links, >100-track Spotify embeds, or `DURATION MISMATCH`:** Stop and
   ask the user to share/paste missing tracks or confirm a specific candidate URL
   rather than guessing or passing `--allow-duration-mismatch` silently.
6. **DJ databases & USBs:** Never modify `master.db` while Rekordbox is open,
   never overwrite a USB's `PIONEER` folder, and warn before double-storing the
   same files twice on a capacity-limited USB drive.

---

## Step 1: Preflight & Disk Hygiene (`doctor`)

Check dependencies first. Ask before installing if needed, then run:

```bash
python <skill_dir>/scripts/dj_dl.py doctor --install
```

* Installs missing Python packages (`yt-dlp`, `mutagen`, `requests`) and a
  portable `ffmpeg` (`imageio-ffmpeg` if none exists on `PATH`, Homebrew,
  WinGet, or `~/.spotdl`, ~80–120 MB one-time).
* Keep temporary `tracks.json` files in the OS temp directory and delete them
  after the batch finishes. Raw audio downloads run inside an auto-cleaning temp
  folder per track so only the final `.mp3` files remain (~8–12 MB per track).

## Step 2: Gather Tracks & Reason Over Inputs

Build a UTF-8 JSON array from the user's source:

* **Platform URLs (`extract`):** Supports **Spotify**, **Apple Music**,
  **SoundCloud**, **YouTube / YouTube Music**, **Bandcamp**, **Mixcloud**, and
  other `yt-dlp` / Schema.org JSON-LD pages:
  ```bash
  python <skill_dir>/scripts/dj_dl.py extract "<url>" -o tracks.json
  ```
  * *Spotify / Apple Music:* Extracts `duration_sec` automatically. Warn and ask
    if private or capped at 100 tracks.
  * *SoundCloud / Bandcamp / Mixcloud / YouTube:* Preserves direct `url` values
    so bootlegs, mashups, and unofficial DJ edits download from source.
* **Screenshots / Images (Vision Reasoning):**
  * Transcribe every `artist` and `title` carefully—**never strip remixers or
    version labels** (*Extended Mix*, *Radio Edit*, *Rework*, *VIP*).
  * **Compute duration when timestamps show:** e.g., `0:03` + `-2:43` = `duration_sec: 166`.
* **Plain-Text Tracklists:** Strip numbering/bullets while preserving mix/remix
  labels.

**JSON schema** (`genre`, `duration_sec`, `album`, `year`, and `url` are optional):

```json
[
  {
    "artist": "Franky Rizardo",
    "title": "Shinjuku",
    "genre": "Tech House",
    "duration_sec": 166
  }
]
```

## Step 3: Download with Length & Cover Art Verification (`download`)

```bash
python <skill_dir>/scripts/dj_dl.py download -i tracks.json -o "~/Music/DJ Music/My Playlist"
```

* **Strict duration verification:** Rejects full DJ sets/snippets and candidates
  outside `--tolerance` (default `8` s) when `duration_sec` is known, checks
  actual encoded MP3 length afterward, and raises `DURATION MISMATCH` with
  candidate options instead of silently downloading the wrong cut.
* **Scored cover art & metadata matching:** Scores top 5 Deezer and iTunes
  results by artist, title, mix keywords, and duration instead of blindly taking
  the first hit; inspects pixel dimensions/aspect ratio, center-crops rectangular
  art when Pillow is available, and logs exact dimensions (e.g., `3:56 | art: Deezer 1000x1000`).
* **Review flagged warnings:** Whenever a track logs `WARN` (YT fallback cover,
  non-square art, duration mismatch), inspect or ask the user before moving on.
* `download` skips existing valid `.mp3` files (`> 100 KB`) and runs a read-only
  `audit` summary at the end (`--skip-audit` to disable).

## Step 4: Audit & Repair Existing Folders (`audit`)

1. Run read-only first to see exact counts (MP3s, `.wav`s, double extensions,
   tag/art issues):
   ```bash
   python <skill_dir>/scripts/dj_dl.py audit "/path/to/DJ Folder"
   ```
2. After confirming with the user, apply only the requested repairs:
   * `--fix-ext` strips `.mp3.mpeg` / `.m4a.mp4` double extensions.
   * `--convert-wav` transcodes `.wav` files to tagged 320 kbps `.mp3` and moves
     originals to `_original_wav/` (add `--delete-wav` only if the user explicitly
     wants originals deleted to save space).
   * `--fix` runs both `--fix-ext` and `--convert-wav`.
