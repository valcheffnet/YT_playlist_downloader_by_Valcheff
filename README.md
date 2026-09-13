# yt-playlist-dl

A yt-dlp wrapper for pulling down whole YouTube playlists and channels without
having to remember twenty command line flags every time.

It handles the parts you would otherwise write yourself. Filenames keep the
playlist order. Anything already downloaded gets skipped on the next run. And
when one item in a 200 video playlist turns out to be private, the other 199
still arrive.

Meant for material you have the right to download. Your own uploads, Creative
Commons and public domain video, amateur footage, anything the uploader allows.
It does not touch DRM protected streams and cannot be made to.

## Prerequisites

| What | Why | Check |
|---|---|---|
| Python 3.9 or newer | runs the script | `python --version` |
| yt-dlp with the `default` dependency group | does the actual work | `python -m yt_dlp --version` |
| ffmpeg on PATH | merges video and audio, converts audio, embeds subtitles | `ffmpeg -version` |
| deno 2.3.0 or newer | solves YouTube's JavaScript challenge | `deno --version` |

Install the Python side with the dependency group spelled out:

```bash
pip install -U "yt-dlp[default]"
```

The quotes and the `[default]` part matter. A plain `pip install -U yt-dlp`
leaves out `yt-dlp-ejs`, the package holding the challenge solver scripts, and
every download then fails with a misleading "This video is not available".
More on that in [troubleshooting](#when-every-video-is-not-available).

On Windows, ffmpeg and deno are easiest through winget:

```bash
winget install yt-dlp.FFmpeg
```

```bash
winget install DenoLand.Deno
```

Then close and reopen your terminal so the new PATH entries take effect.

## Quick start

Start by looking at what you are about to pull. This downloads nothing:

```bash
python yt_playlist_dl.py "https://www.youtube.com/playlist?list=PLxxxx" --list
```

Then take the first two items as a smoke test:

```bash
python yt_playlist_dl.py "https://www.youtube.com/playlist?list=PLxxxx" -o "D:/Video" --items 1-2
```

If those land correctly, drop `--items` and let it run.

## How resuming works

Every finished video's ID goes into `.downloaded.txt` in the output directory.
On the next run those IDs are skipped. Interrupt a 300 video playlist with
Ctrl+C at item 180, run the identical command tomorrow, and it picks up at 181.

Partially written files are resumed at the byte level too, so a video cut off
halfway does not restart from zero.

Two consequences worth knowing. Moving the finished files elsewhere does not
clear the archive, so they will not be re-downloaded. And if you want the same
playlist again at a different quality, either point `-o` somewhere new or pass
`--no-archive`.

## Flags

### Basics

| Flag | What it does |
|---|---|
| `urls` | one or more playlist, channel or video URLs, space separated |
| `-f, --from-file FILE` | read URLs from a text file, one per line, `#` starts a comment |
| `-o, --output DIR` | where to write. Defaults to the current directory, which is almost never what you want |
| `--flat` | skip the per-playlist subfolder and drop everything straight into `-o` |
| `--list` | print the contents with numbers and durations, download nothing |

Run `--list` first, every time. It tells you how many items are really there,
which ones are unavailable, and gives you the numbers that `--items` expects.
A channel with 1100 videos looks exactly like a playlist with 12 until you ask.

### Quality

| Flag | Default | What it does |
|---|---|---|
| `--max-height PX` | 1080 | resolution ceiling. `0` removes it |
| `--container` | mp4 | mp4, mkv or webm for the merged file |
| `--audio-only` | off | grab the audio stream only |
| `--audio-format` | mp3 | mp3, m4a, opus, flac, wav or vorbis |

The height cap is really a size control. A 4K file is five to eight times the
size of the same video at 1080p. The script always takes the best format
*below* the ceiling, so a 480p source stays 480p rather than being upscaled.

Pick `mkv` when you are pulling several subtitle languages or want chapters
preserved, since mp4 handles both badly. Otherwise mp4 plays on everything and
saves Jellyfin or Plex from transcoding.

One trap in the audio options. YouTube serves audio as opus or m4a, so asking
for `mp3` means ffmpeg re-encodes an already lossy stream and you lose a second
round of quality for nothing. If your player handles opus, and almost everything
made in the last decade does, use `--audio-format opus` and you get the original
bytes untouched. Choose mp3 only for old car stereos and hardware players.
Choosing flac is worse than pointless: five times the file size, none of the
detail YouTube already threw away.

### Selection

| Flag | What it does |
|---|---|
| `--items SPEC` | which items to take: `5-20`, `3,7,12`, `5:`, `:10`, `::2` |
| `--reverse` | walk the playlist from the end backwards |

`--reverse` exists because channels come back newest first. For a lecture
series that means you get the last lecture as file 1. Note that the numbers in
the filenames flip along with the order.

### Extras

| Flag | What it does |
|---|---|
| `--subs` | download subtitles as separate `.srt` files |
| `--auto-subs` | accept YouTube's machine generated captions as well |
| `--sub-langs` | comma separated languages, `en,bg` by default, `all` for everything |
| `--embed-subs` | put the subtitles inside the video file |
| `--thumbnail` | embed the thumbnail as cover art |
| `--metadata` | write title, uploader and date into the file tags. On by default |
| `--no-metadata` | turn the above off |
| `--info-json` | save the full metadata next to each file |
| `--sponsorblock` | cut sponsor segments using the SponsorBlock database |

Without `--auto-subs` you only get captions the uploader typed by hand, which
for amateur video usually means none at all. With it you get a machine
transcript: useful for searching through lectures, irritating to actually read.

`--sponsorblock` only finds segments other people have already marked, so it
does nothing on a video with 200 views. It also re-encodes the file, which
takes time.

Leave `--metadata` alone. Without it, a year from now you have a folder of
files and no idea where any of them came from.

### JavaScript and EJS

| Flag | What it does |
|---|---|
| `--remote-components COMPONENT` | fetch the solver scripts on demand: `ejs:github` or `ejs:npm` |
| `--js-runtimes RUNTIME[:PATH]` | enable another runtime: deno, node, quickjs or bun |
| `--no-default-runtime` | drop deno from the list |

These are escape hatches. If `yt-dlp[default]` is installed you will never need
them.

`ejs:github` downloads the solver from the yt-dlp/ejs releases each run and
works with any runtime. `ejs:npm` does the same through npm and only works with
deno or bun, since those two can pull npm packages themselves. Both hit the
network on every invocation and stop working when the source is unreachable,
which is why the local package is the better answer.

`--no-default-runtime` looks redundant until you try to force a specific
runtime. yt-dlp picks the highest priority one that is actually present, in the
order deno, node, quickjs, bun. Passing `--js-runtimes node` on its own changes
nothing while deno is installed, because deno still wins. You need both flags:

```bash
python yt_playlist_dl.py URL --no-default-runtime --js-runtimes node
```

The path form splits on the first colon only, so a Windows path keeps its drive
letter: `--js-runtimes "deno:C:\tools\deno.exe"`.

### Network

| Flag | Default | What it does |
|---|---|---|
| `--fragments N` | 4 | parallel fragment downloads within one video |
| `--rate-limit RATE` | none | speed ceiling, e.g. `800K`, `5M`, `1.5M` |
| `--sleep SECONDS` | 0 | pause between requests |
| `--proxy URL` | none | http, https or socks proxy |
| `--cookies FILE` | none | Netscape format cookies.txt |
| `--cookies-from-browser BROWSER` | none | read the session from chrome, firefox, edge, brave and friends |

Fragments are the main speed lever, since a large video arrives in hundreds of
pieces. Past 8 YouTube starts throttling and occasionally returns 403, which
feeds the retry loop and ends up slower than 4 would have been.

Reach for `--sleep 1` on very long playlists. Somewhere past 300 items YouTube
tends to start rate limiting, and a one second pause between requests trades a
little wall clock time for not having to restart.

The cookie options are for your own unlisted and private videos, age restricted
material, and the occasional bot check. They bypass nothing; they just hand
yt-dlp the session you already have. On Windows, Chrome locks its cookie
database while running, so you may need to close the browser first.

### Archive

| Flag | Default | What it does |
|---|---|---|
| `--archive-name NAME` | `.downloaded.txt` | the file recording finished video IDs |
| `--no-archive` | off | download everything again, ignoring what is already there |

## Examples

Getting a feel for a playlist before committing to it:

```bash
python yt_playlist_dl.py "URL" --list
```

A lecture course from a channel, oldest first, at 720p, with searchable
captions:

```bash
python yt_playlist_dl.py "https://www.youtube.com/@channel/videos" -o "D:/Course" --reverse --max-height 720 --subs --auto-subs --sub-langs en
```

Podcast archive as audio, no re-encoding, with cover art:

```bash
python yt_playlist_dl.py "URL" -o "D:/Podcasts" --audio-only --audio-format opus --thumbnail
```

A large playlist overnight without saturating the household connection:

```bash
python yt_playlist_dl.py "URL" -o "D:/Video" --rate-limit 3M --sleep 1 --fragments 3
```

Several sources kept in a file and re-run periodically, where the archive does
the deduplication for you:

```bash
python yt_playlist_dl.py -f channels.txt -o "D:/Video" --max-height 1080
```

Everything at maximum quality into an mkv, for archival:

```bash
python yt_playlist_dl.py "URL" -o "D:/Archive" --max-height 0 --container mkv --subs --info-json
```

## Troubleshooting

### When every video is "not available"

The symptom looks like this:

```
WARNING: [youtube] [jsc] Remote components challenge solver script (deno) and
         NPM package (deno) were skipped...
WARNING: [youtube] <id>: n challenge solving failed: Some formats may be missing...
ERROR: [youtube] <id>: This video is not available
```

The video is fine. YouTube obfuscates its stream URLs behind a JavaScript
challenge, and yt-dlp solves it by running an external JS runtime over solver
scripts kept in a separate package. Two pieces are needed and one of them is
usually missing:

| Piece | How you get it |
|---|---|
| A JS runtime | install deno, which yt-dlp enables by default |
| `yt-dlp-ejs` solver scripts | comes with `pip install -U "yt-dlp[default]"` |

If you installed yt-dlp from the GitHub release binary, the solver is baked
into the executable and this never comes up. Installing through plain pip is
what leaves the gap.

Verify both halves:

```bash
python -c "import yt_dlp_ejs; print('solver present')"
```

```bash
python -m yt_dlp -v --simulate "https://www.youtube.com/watch?v=SOME_ID"
```

The verbose output should show `[debug] JS runtimes: deno-<version>` followed by
`[jsc:deno] Solving JS challenges using deno` and no warnings. If it instead
reports that no supported runtime could be found while deno is definitely
installed, your terminal predates the installation and its PATH is stale. Open
a new one.

Keep the two packages in step. yt-dlp raises the minimum solver version without
notice and silently ignores an outdated one, so always update with
`pip install -U "yt-dlp[default]"` rather than plain `pip install -U yt-dlp`.

### A single video fails while the rest succeed

That one is genuinely private, deleted or geo-blocked. The script logs it and
moves on by design, which is the whole point of running a playlist unattended.
You can tell the difference by the absence of EJS warnings around the error.

### Downloads crawl or return 403

Lower `--fragments` to 2 or 3 and add `--sleep 1`. If it persists across a
whole session rather than one video, YouTube is rate limiting your address and
waiting is the only real fix.

### Merging fails or `--audio-only` does nothing

ffmpeg is not on PATH. `ffmpeg -version` will tell you.

## Notes

The script talks to yt-dlp as a library rather than shelling out, so progress
reporting, error handling and the archive all go through the Python API.

`--metadata` is the only extra enabled by default. Everything else is opt-in.

Filenames are sanitised for Windows and capped at 200 characters, which keeps
long titles from hitting the path limit.
