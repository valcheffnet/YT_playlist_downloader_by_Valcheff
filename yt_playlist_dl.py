#!/usr/bin/env python3
"""
yt_playlist_dl.py - download a YouTube playlist (or channel / single video)
with yt-dlp, keeping the playlist order and skipping items already fetched.

Intended for content you have the right to download: your own uploads,
Creative Commons / public-domain material, amateur videos, and anything the
uploader explicitly allows. It does not touch DRM-protected streams.

Requires:  pip install -U yt-dlp
Optional:  ffmpeg on PATH (needed for merging video+audio and for --audio-only)
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

try:
    import yt_dlp
except ImportError:
    sys.exit("yt-dlp is not installed. Run:  pip install -U yt-dlp")


# --------------------------------------------------------------------------- #
# progress / logging
# --------------------------------------------------------------------------- #

class QuietLogger:
    """Swallow yt-dlp's own chatter, keep warnings and errors."""

    def debug(self, msg):
        pass

    def info(self, msg):
        pass

    def warning(self, msg):
        print("  ! " + str(msg), file=sys.stderr)

    def error(self, msg):
        print("  X " + str(msg), file=sys.stderr)


def progress_hook(d):
    status = d.get("status")
    if status == "downloading":
        pct = d.get("_percent_str", "  ?%").strip()
        speed = d.get("_speed_str", "?").strip()
        eta = d.get("_eta_str", "?").strip()
        name = Path(d.get("filename", "")).name[:60]
        print("\r  {:>6}  {:>11}  ETA {:>6}  {}".format(pct, speed, eta, name),
              end="", flush=True)
    elif status == "finished":
        print("\r  done: {:<78}".format(Path(d.get("filename", "")).name[:70]))
    elif status == "error":
        print("\r  failed: {:<76}".format(Path(d.get("filename", "")).name[:70]))


def postprocessor_hook(d):
    if d.get("status") == "started":
        print("  post-processing: {}".format(d.get("postprocessor")))


# --------------------------------------------------------------------------- #
# options
# --------------------------------------------------------------------------- #

def build_opts(args) -> dict:
    outdir = Path(args.output).expanduser().resolve()
    outdir.mkdir(parents=True, exist_ok=True)

    # playlist_index keeps the on-disk order identical to the playlist order
    name_part = "%(playlist_index|)s%(playlist_index& - |)s%(title).120B [%(id)s].%(ext)s"
    if args.flat:
        template = name_part
    else:
        template = "%(playlist_title|Downloads)s/" + name_part

    opts = {
        "outtmpl": {"default": str(outdir / template)},
        "windowsfilenames": sys.platform == "win32",
        "trim_file_name": 200,

        # keep going when one item is private / removed / geo-blocked
        "ignoreerrors": "only_download",
        "retries": 10,
        "fragment_retries": 10,
        "file_access_retries": 5,
        "continuedl": True,
        "concurrent_fragment_downloads": args.fragments,

        "logger": QuietLogger(),
        "progress_hooks": [progress_hook],
        "postprocessor_hooks": [postprocessor_hook],
        "noprogress": True,
        "quiet": True,
        "no_warnings": False,
        "consoletitle": False,
    }

    # resume across runs: finished video IDs are recorded and skipped next time
    if not args.no_archive:
        opts["download_archive"] = str(outdir / args.archive_name)

    if args.items:
        opts["playlist_items"] = args.items
    if args.reverse:
        opts["playlistreverse"] = True

    postprocessors = []

    # format selection
    if args.audio_only:
        opts["format"] = "bestaudio/best"
        postprocessors.append({
            "key": "FFmpegExtractAudio",
            "preferredcodec": args.audio_format,
            "preferredquality": "0",
        })
    else:
        height = "[height<={}]".format(args.max_height) if args.max_height else ""
        opts["format"] = (
            "bestvideo{h}[ext=mp4]+bestaudio[ext=m4a]/"
            "bestvideo{h}+bestaudio/"
            "best{h}/best".format(h=height)
        )
        opts["merge_output_format"] = args.container

    if args.metadata:
        postprocessors.append({"key": "FFmpegMetadata", "add_metadata": True})

    if args.thumbnail:
        opts["writethumbnail"] = True
        postprocessors.append({"key": "EmbedThumbnail"})

    if args.subs:
        opts["writesubtitles"] = True
        opts["writeautomaticsub"] = args.auto_subs
        opts["subtitleslangs"] = args.sub_langs.split(",")
        opts["subtitlesformat"] = "srt/vtt/best"
        if args.embed_subs:
            postprocessors.append({"key": "FFmpegEmbedSubtitle"})

    if args.sponsorblock:
        postprocessors.append({"key": "SponsorBlock",
                               "categories": ["sponsor"],
                               "when": "after_filter"})
        postprocessors.append({"key": "ModifyChapters",
                               "remove_sponsor_segments": ["sponsor"]})

    if args.info_json:
        opts["writeinfojson"] = True

    if postprocessors:
        opts["postprocessors"] = postprocessors

    # JavaScript challenge solving (EJS)
    #
    # YouTube obfuscates its stream URLs behind a JS challenge. yt-dlp solves it
    # by running an external JS runtime over the yt-dlp-ejs solver scripts.
    # Without both pieces the extraction yields no formats and yt-dlp reports
    # "This video is not available".
    opts["js_runtimes"] = build_js_runtimes(args)
    if args.remote_components:
        opts["remote_components"] = list(args.remote_components)

    # network
    if args.rate_limit:
        opts["ratelimit"] = parse_rate(args.rate_limit)
    if args.sleep:
        opts["sleep_interval_requests"] = args.sleep
    if args.proxy:
        opts["proxy"] = args.proxy
    if args.cookies_from_browser:
        opts["cookiesfrombrowser"] = (args.cookies_from_browser,)
    if args.cookies:
        opts["cookiefile"] = args.cookies

    return opts


def build_js_runtimes(args) -> dict:
    """
    Turn the CLI 'RUNTIME[:PATH]' strings into yt-dlp's API shape,
    {'deno': {'path': None}, 'node': {'path': 'C:/.../node.exe'}}.

    Mirrors the yt-dlp CLI: 'deno' is enabled by default and further runtimes
    are added on top. Because the highest-priority available runtime wins
    (deno > node > quickjs > bun), forcing a lower-priority one means dropping
    the default first with --no-default-runtime.
    """
    names = [] if args.no_default_runtime else ["deno"]
    names += args.js_runtimes or []

    runtimes = {}
    for item in names:
        # split once only: a Windows path keeps its own drive-letter colon
        name, _, path = item.partition(":")
        runtimes[name.strip().lower()] = {"path": path.strip() or None}
    return runtimes


def parse_rate(text: str) -> int:
    """'1.5M' / '800K' / '120000' -> bytes per second."""
    text = text.strip().upper()
    mult = 1
    if text.endswith("K"):
        mult, text = 1024, text[:-1]
    elif text.endswith("M"):
        mult, text = 1024 ** 2, text[:-1]
    elif text.endswith("G"):
        mult, text = 1024 ** 3, text[:-1]
    return int(float(text) * mult)


# --------------------------------------------------------------------------- #
# actions
# --------------------------------------------------------------------------- #

def list_playlist(url: str) -> None:
    """Print the playlist contents without downloading anything."""
    opts = {"quiet": True, "no_warnings": True,
            "extract_flat": "in_playlist", "skip_download": True}
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=False)

    entries = info.get("entries") or [info]
    print("\n{}  ({} items)\n".format(info.get("title", url), len(entries)))
    for i, entry in enumerate(entries, 1):
        if not entry:
            print("{:>4}. <unavailable>".format(i))
            continue
        dur = entry.get("duration")
        stamp = "{:>3}:{:02d}".format(int(dur) // 60, int(dur) % 60) if dur else " --:--"
        print("{:>4}. [{}] {}".format(i, stamp, entry.get("title", "?")))
    print()


def download(urls: list[str], opts: dict) -> int:
    failures = 0
    with yt_dlp.YoutubeDL(opts) as ydl:
        for url in urls:
            print("\n=== {}".format(url))
            try:
                if ydl.download([url]):
                    failures += 1
            except yt_dlp.utils.DownloadError as exc:
                print("  X download error: {}".format(exc), file=sys.stderr)
                failures += 1
            except KeyboardInterrupt:
                print("\nInterrupted. Re-run the same command to resume.")
                return 130
    return 1 if failures else 0


# --------------------------------------------------------------------------- #
# cli
# --------------------------------------------------------------------------- #

EPILOG = """examples:
  python yt_playlist_dl.py "https://www.youtube.com/playlist?list=PL..." -o D:/Video
  python yt_playlist_dl.py URL --audio-only --audio-format mp3
  python yt_playlist_dl.py URL --items 5-20 --max-height 1080
  python yt_playlist_dl.py URL --list
  python yt_playlist_dl.py -f urls.txt -o D:/Video --subs --embed-subs
  python yt_playlist_dl.py URL --remote-components ejs:github
  python yt_playlist_dl.py URL --no-default-runtime --js-runtimes node
"""


def main() -> int:
    p = argparse.ArgumentParser(
        description="Download YouTube playlists / channels / videos with yt-dlp.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=EPILOG)

    p.add_argument("urls", nargs="*", help="playlist / channel / video URLs")
    p.add_argument("-f", "--from-file", metavar="FILE",
                   help="read URLs from a text file, one per line (# = comment)")
    p.add_argument("-o", "--output", default=".", help="output directory")
    p.add_argument("--flat", action="store_true",
                   help="do not create a per-playlist subfolder")
    p.add_argument("--list", action="store_true",
                   help="only list the playlist contents, download nothing")

    q = p.add_argument_group("quality")
    q.add_argument("--max-height", type=int, default=1080, metavar="PX",
                   help="cap video height (0 = unlimited)")
    q.add_argument("--container", default="mp4", choices=["mp4", "mkv", "webm"],
                   help="container for the merged file")
    q.add_argument("--audio-only", action="store_true")
    q.add_argument("--audio-format", default="mp3",
                   choices=["mp3", "m4a", "opus", "flac", "wav", "vorbis"])

    s = p.add_argument_group("selection")
    s.add_argument("--items", metavar="SPEC",
                   help='playlist items, e.g. "1-10", "3,7,12", "5:"')
    s.add_argument("--reverse", action="store_true",
                   help="download the playlist back to front")

    e = p.add_argument_group("extras")
    e.add_argument("--subs", action="store_true", help="download subtitles")
    e.add_argument("--auto-subs", action="store_true",
                   help="also accept auto-generated subtitles")
    e.add_argument("--sub-langs", default="en,bg",
                   help="comma-separated subtitle languages")
    e.add_argument("--embed-subs", action="store_true")
    e.add_argument("--thumbnail", action="store_true",
                   help="embed the thumbnail as cover art")
    e.add_argument("--metadata", action="store_true", default=True,
                   help="write title/uploader/date into the file tags")
    e.add_argument("--no-metadata", dest="metadata", action="store_false")
    e.add_argument("--info-json", action="store_true",
                   help="save the full metadata as .info.json next to the file")
    e.add_argument("--sponsorblock", action="store_true",
                   help="cut SponsorBlock 'sponsor' segments")

    n = p.add_argument_group("network / throttling")
    n.add_argument("--fragments", type=int, default=4,
                   help="parallel fragment downloads per video")
    n.add_argument("--rate-limit", metavar="RATE",
                   help="max download speed, e.g. 2M or 800K")
    n.add_argument("--sleep", type=float, default=0,
                   help="seconds to sleep between requests")
    n.add_argument("--proxy", help="http(s)/socks proxy URL")
    n.add_argument("--cookies", metavar="FILE",
                   help="Netscape cookies.txt (for your own private videos)")
    n.add_argument("--cookies-from-browser", metavar="BROWSER",
                   help="chrome | firefox | edge | brave | ...")

    j = p.add_argument_group(
        "javascript / EJS",
        "YouTube stream URLs sit behind a JS challenge. Solving it needs a JS "
        "runtime (deno by default) plus the yt-dlp-ejs solver scripts. The "
        "cleanest fix is to install the scripts once with "
        '`pip install -U \"yt-dlp[default]\"`; the flags below are for the '
        "cases where you cannot, or where the runtime lives off PATH.")
    j.add_argument("--remote-components", action="append", metavar="COMPONENT",
                   help="let yt-dlp fetch the solver scripts on demand: "
                        "ejs:github (works with any runtime) or ejs:npm "
                        "(deno/bun only). Repeatable.")
    j.add_argument("--js-runtimes", action="append", metavar="RUNTIME[:PATH]",
                   help="enable an extra JS runtime, optionally with a path: "
                        "deno, node, quickjs, bun. Repeatable.")
    j.add_argument("--no-default-runtime", action="store_true",
                   help="drop the default deno runtime, so a lower-priority "
                        "one given via --js-runtimes is actually used")

    a = p.add_argument_group("archive")
    a.add_argument("--archive-name", default=".downloaded.txt",
                   help="archive file recording finished video IDs")
    a.add_argument("--no-archive", action="store_true",
                   help="do not keep an archive (re-downloads everything)")

    args = p.parse_args()

    urls = list(args.urls)
    if args.from_file:
        for line in Path(args.from_file).read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                urls.append(line)
    if not urls:
        p.error("no URLs given (positional arguments or --from-file)")

    if args.max_height == 0:
        args.max_height = None

    if args.list:
        for url in urls:
            list_playlist(url)
        return 0

    return download(urls, build_opts(args))


if __name__ == "__main__":
    sys.exit(main())
