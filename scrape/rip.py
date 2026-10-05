"""
rip.py

Build a local audio library for the releases in a discogs collection.

Discogs is the catalogue: it knows the tracklist, the timings, the label, the
catalogue number and the artwork for every record in the collection. This turns
that into files on disk, taking the audio from whichever source can provide it
and writing the discogs metadata over the top so the library is consistent
however each file arrived.

Three sources, in order of preference:

    -input <dir>    rips the user already has, matched to the collection by
                    catalogue number, converted and renamed to match
    soulseek        via slskd, see slsk.py
    release links   the media linked on the discogs release page itself,
                    fetched with yt-dlp

Whichever source a track comes from, the same matcher decides which file is
which track, the same length check decides whether it is the whole thing, and
the same tags are written. A ledger in the output directory records what each
release got and from where, so a session can be stopped and resumed, sources can
be worked one at a time in separate sessions, and the gaps can be found again
later.

Entry point is rip_collection, driven by discogs.py -rip.
"""

import datetime
import json
import os
import random
import re
import shutil
import subprocess
import sys
import time
import types
import unicodedata

import yt_dlp
from rapidfuzz import fuzz

import slsk


LEDGER_NAME = ".diig-rip-ledger.json"
LEDGER_VERSION = 1

# where -flag puts a file it has rejected, under the library root. moved rather
# than deleted: a bad rip is still evidence of what went wrong, and a mistaken
# flag should cost nothing to undo
REJECTED_DIR = ".diig-rejected"

# status values recorded per release in the ledger
STATUS_COMPLETE = "complete"    # every track on the release was downloaded
STATUS_PARTIAL = "partial"      # some tracks downloaded, some missing
STATUS_NO_VIDEOS = "no_videos"  # the discogs page links nothing playable
STATUS_NO_MATCH = "no_match"    # sources had nothing that matched a track
STATUS_QUEUED = "queued"        # waiting in a soulseek upload queue
STATUS_FAILED = "failed"        # blew up while ripping

# statuses worth another go with -retry
RETRYABLE = (STATUS_PARTIAL, STATUS_NO_MATCH, STATUS_QUEUED, STATUS_FAILED)

# how a status reads in a report. the ledger keeps the underscored names, they
# are what older ledgers hold and what the code compares against
STATUS_LABELS = {
    STATUS_NO_VIDEOS: "no links",
    STATUS_NO_MATCH: "no match",
}


def status_label(status):
    return STATUS_LABELS.get(status, str(status).replace("_", " "))

# where audio can come from. soulseek is tried first where both are asked for:
# it is the better copy and it is not rate limited per address, so the release
# links are only asked for the tracks nobody on soulseek is sharing
SOURCE_SOULSEEK = "soulseek"
SOURCE_YOUTUBE = "youtube"
SOURCE_ORDER = (SOURCE_SOULSEEK, SOURCE_YOUTUBE)

# rips you already have, imported from a directory with -input. not part of
# SOURCE_ORDER: there is nothing to go looking for, the files are already there,
# so it is a mode of its own rather than something a session falls back on. it
# is recorded in the ledger like the others, so an import leaves the remaining
# tracks visible to a later session on either of the other two
SOURCE_LOCAL = "local"

# what to call each source in a report. the ledger keeps the short names above,
# since they are what -source takes and what older ledgers already hold, and only
# the printing side uses these
SOURCE_LABELS = {
    SOURCE_SOULSEEK: "soulseek",
    SOURCE_YOUTUBE: "yt-dlp",
    SOURCE_LOCAL: "local files",
}

# a track ripped before the ledger recorded where it came from. at that point the
# release links were the only source there was, so that is what these are, but it
# is inferred rather than known and the report says so
UNRECORDED_SOURCES = ("", "?", "disk", "unknown", None)


def source_label(source):
    if source in UNRECORDED_SOURCES:
        return "yt-dlp"
    return SOURCE_LABELS.get(source, str(source))

# discogs allows 60 requests/min authenticated, stay well inside that
API_SLEEP = 1.2

# set when a source asked us to sign in, so the session can say what to do
bot_check_seen = False

# consecutive blocked downloads, and the resulting session wide stop
consecutive_blocks = 0
session_blocked = False

# how many downloads each kind of failure accounted for, and which hints have
# been printed, so the same advice is not repeated per track
refusal_counts = {}
hints_shown = set()

# set when discogs answered 429, so the summary can say the run was throttled
discogs_rate_limited = False

# how many tracks each source landed this session, the number a soulseek only
# pass exists to produce
source_counts = {}

# the slskd connection, made once on first use and cached. False means we tried
# and could not, so we do not retry the connection for every release
slsk_client = None


# ----------------------------------------------------------------------------
# args
# ----------------------------------------------------------------------------

def arg_value(flag, default=None):
    if flag in sys.argv:
        i = sys.argv.index(flag) + 1
        if i < len(sys.argv):
            return sys.argv[i]
    return default


def arg_int(flag, default=None):
    val = arg_value(flag)
    if val is None:
        return default
    try:
        return int(val)
    except ValueError:
        print(f"error: {flag} expects a number, got '{val}'")
        sys.exit(1)


def arg_float(flag, default):
    val = arg_value(flag)
    if val is None:
        return default
    try:
        return float(val)
    except ValueError:
        print(f"error: {flag} expects a number, got '{val}'")
        sys.exit(1)


def base_pause():
    """
    Seconds to wait between downloads.

    Bursting is what gets an address rate limited, and a vpn exit is treated
    far more harshly than a home connection, so the default deliberately
    crawls. -slow crawls harder again, -sleep 0 turns it off.
    """
    if "-slow" in sys.argv:
        return arg_float("-sleep", 20.0)
    return arg_float("-sleep", 8.0)


def jittered(seconds):
    """Spread a wait randomly so the request pattern is not a metronome."""
    if seconds <= 0:
        return 0.0
    return random.uniform(seconds * 0.5, seconds * 1.5)


def crawl_pause(reason):
    wait = jittered(base_pause())
    if wait <= 0:
        return
    print(f"    [wait] {int(wait)}s {reason}")
    time.sleep(wait)


def verbose():
    return "-verbose" in sys.argv


def debug():
    """
    Print the reasoning rather than just the result.

    Currently the length comparison for every track, which is the one thing a
    finished rip cannot show you: a snippet upload is a valid mp3 with correct
    tags, and the only sign it is not the record is how long it runs.
    """
    return "-debug" in sys.argv


def requested_sources():
    """
    Which sources this session may use, in the order they are tried.

    Naming a single source is the point of the flag rather than a curiosity. A
    session restricted to one of them makes no requests of the other at all, so
    an address that has started getting refused gets a rest while we find out how
    much the other source can cover on its own. The gaps are picked up in a later
    session, and the ledger remembers which sources a release has already been
    through, so that session needs no extra flags.
    """
    wanted = (arg_value("-source", "both") or "both").lower()
    if wanted in ("both", "all", "any"):
        return list(SOURCE_ORDER)
    if wanted in ("slsk", "soulseek", "seek"):
        return [SOURCE_SOULSEEK]
    if wanted in ("yt", "youtube", "tube", "yt-dlp", "ytdlp", "links"):
        return [SOURCE_YOUTUBE]
    print(f"error: -source expects soulseek, youtube or both, got '{wanted}'")
    sys.exit(1)


def slsk_config():
    return slsk.auth_config(arg_value("-slsk-host"), arg_value("-slsk-key"))


def slsk_downloads_dir():
    path = arg_value("-slsk-downloads") or slsk.default_downloads_dir()
    return os.path.abspath(os.path.expanduser(path))


def slsk_connect():
    """
    The slskd client, connected on first use and cached for the session.

    Returns None if slskd is not there. Whether that is fatal depends on the
    sources asked for, which is the caller's business, not ours.
    """
    global slsk_client
    if slsk_client is None:
        slsk_client = slsk.connect(slsk_config()) or False
    return slsk_client or None


def make_console_printable():
    """
    Track and video titles are full of unicode the windows console codepage
    cannot encode (curly quotes, unicode hyphens). Without this a print of a
    title raises UnicodeEncodeError and takes the whole release down with it.
    """
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="replace")
        except (AttributeError, ValueError, OSError):
            pass


# ----------------------------------------------------------------------------
# discogs api
# ----------------------------------------------------------------------------

def http_status_of(error):
    """
    The http status behind an exception, whoever raised it.

    discogs_client raises its own HTTPError carrying status_code, requests
    raises one carrying a response, and both stringify with the code in them.
    """
    status = getattr(error, "status_code", None)
    if isinstance(status, int):
        return status
    status = getattr(getattr(error, "response", None), "status_code", None)
    if isinstance(status, int):
        return status
    match = re.match(r"\s*(\d{3})\b", str(error))
    if match:
        return int(match.group(1))
    return None


def discogs_call(what, call):
    """
    Make a discogs request, waiting out a rate limit instead of dying on it.

    Discogs allows 60 requests a minute and answers 429 once that is spent.
    The client library raises that straight out of whatever you were doing,
    including from inside its own collection iterator, which ends the session
    mid run. Every discogs request goes through here so a 429 or a server
    error costs a wait rather than the session. Anything else, a 404 on a
    deleted release say, is left to the caller.
    """
    global discogs_rate_limited

    attempts = max(1, arg_int("-discogs-attempts", 5))
    base = arg_float("-discogs-backoff", 60.0)

    for attempt in range(attempts):
        try:
            return call()
        except Exception as e:
            status = http_status_of(e)
            limited = status == 429
            server_error = status is not None and 500 <= status < 600
            if limited:
                discogs_rate_limited = True
            if not limited and not server_error:
                raise
            if attempt + 1 >= attempts:
                print(f"    [fail] discogs still refusing {what} after "
                      f"{attempts} attempts ({status})")
                raise
            # the limit is a rolling 60 second window, so a minute clears it
            wait = base * (attempt + 1) + random.uniform(0, 10)
            reason = "rate limited (429)" if limited else f"server error {status}"
            print(f"    [wait] discogs {reason} on {what}, retrying in "
                  f"{int(wait)}s (attempt {attempt + 2} of {attempts})")
            time.sleep(wait)


def fetch_release(discogs, release_id):
    """Full release, the collection listing only carries basic information."""
    release = discogs.release(release_id)
    release.refresh()
    return release


def iter_releases(paginated, what="collection"):
    """
    Walk a discogs paginated list a page at a time, retrying a page that 429s.

    The client fetches inside its own generator, so a rate limit part way
    through the collection raises out of the for loop with no way to resume.
    Driving the pagination here costs nothing extra, pages are cached by the
    client once fetched, and a retry only re-requests the page that failed.
    """
    pages = discogs_call(f"{what} page count", lambda: paginated.pages)
    for index in range(1, pages + 1):
        page = discogs_call(f"{what} page {index}",
                            lambda: paginated.page(index))
        for item in page:
            yield item


# ----------------------------------------------------------------------------
# text helpers
# ----------------------------------------------------------------------------

ZERO_WIDTH = ["​", "‌", "‍", "﻿"]

# windows reserved device names, a file called "con.mp3" cannot be created
WIN_RESERVED = set(
    ["con", "prn", "aux", "nul"]
    + ["com%d" % i for i in range(1, 10)]
    + ["lpt%d" % i for i in range(1, 10)]
)


def normalize_unicode(s):
    if not s:
        return ""
    s = unicodedata.normalize("NFC", s)
    for zw in ZERO_WIDTH:
        s = s.replace(zw, "")
    return re.sub(r"\s+", " ", s).strip()


def sanitize_filename(name, max_len=120):
    """Make name safe to use as a single path component on windows and posix."""
    name = normalize_unicode(name)
    # characters windows outright rejects
    name = re.sub(r'[<>:"/\\|?*]', "-", name)
    # control characters
    name = "".join(c for c in name if ord(c) >= 32)
    name = re.sub(r"\s+", " ", name).strip()
    # windows strips trailing dots and spaces, do it here so our paths match
    name = name.rstrip(". ")
    if not name:
        name = "untitled"
    if name.split(".")[0].lower() in WIN_RESERVED:
        name = "_" + name
    if len(name) > max_len:
        name = name[:max_len].rstrip(". ")
    return name


def strip_discogs_suffix(name):
    """Discogs disambiguates duplicate artist names with a trailing (2), (11)."""
    if not name:
        return ""
    return re.sub(r"\s*\(\d+\)\s*$", "", name).strip()


def parse_duration(text):
    """'4:35' or '1:02:03' to seconds. None if unparseable."""
    if text is None:
        return None
    if isinstance(text, int):
        return text if text > 0 else None
    text = str(text).strip()
    if not text:
        return None
    parts = text.split(":")
    seconds = 0
    for part in parts:
        part = part.strip()
        if not part.isdigit():
            return None
        seconds = seconds * 60 + int(part)
    return seconds if seconds > 0 else None


# junk uploaders bolt onto titles, stripped before matching
VIDEO_NOISE = [
    r"official\s*(music\s*)?(video|audio|visualiser|visualizer)",
    r"lyric\s*video", r"audio\s*only", r"full\s*stream", r"hq\s*audio",
    r"free\s*(dl|download)", r"out\s*now", r"premiere", r"premier",
    r"exclusive", r"forthcoming", r"snippet", r"teaser",
    r"\bhq\b", r"\bhd\b", r"\b4k\b", r"\b1080p?\b", r"\b720p?\b",
    r"\bwav\b", r"\bflac\b", r"\b320\b", r"\bvinyl\s*rip\b", r"\bvinyl\b",
    r"\bremaster(ed)?\b", r"\bupload(ed)?\b",
    # the same job for a filename off a soulseek peer, which carries its own
    # dialect of noise: the format and bitrate it was encoded at, and whatever
    # the site or ripper stamped on it
    r"\b\d{2,3}\s*kbps\b", r"\bv[02]\b", r"\b24\s*[-/]\s*\d{2,3}\b",
    r"\b\d{2}\s*bit\b", r"\bcbr\b", r"\bvbr\b", r"\blossless\b",
    r"\bweb\b", r"\bcdm?\b", r"\bcdr\b", r"\bwebrip\b", r"\bproper\b",
    r"www\.[a-z0-9.-]+", r"\b[a-z0-9-]+\.(com|net|org|ru)\b",
]
VIDEO_NOISE_RE = re.compile("|".join(VIDEO_NOISE), re.IGNORECASE)

# a leading "A1.", "B2 -", "01 -", "[A1]" position marker
POSITION_PREFIX_RE = re.compile(
    r"^\s*[\[\(]?\s*([A-Z]{1,2}\d{1,2}|\d{1,2})\s*[\]\)]?\s*[\.\-\:\)]\s+",
    re.IGNORECASE,
)


def normalize_for_match(s):
    """Aggressively normalise a title down to comparable words."""
    s = normalize_unicode(s).lower()
    s = s.replace("&", "and")
    s = re.sub(r"[’`´]", "'", s)
    s = re.sub(r"[^a-z0-9' ]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def drop_noise_group(match):
    """Remove a bracketed group only if it is upload noise, keep '(Original Mix)'."""
    if VIDEO_NOISE_RE.search(match.group(1)):
        return " "
    return match.group(0)


def clean_video_title(title, artists, label, catno):
    """
    Strip everything from a candidate's name that is not the track title.

    A name from any source carries the same clutter: the artist, the label, the
    catalogue number, a position marker, the format it was encoded at and
    whatever the uploader or ripper felt like adding. What is left can be fuzzy
    matched against the tracklist.
    """
    cleaned = normalize_unicode(title)

    cleaned = re.sub(r"\[([^\]]*)\]", drop_noise_group, cleaned)
    cleaned = re.sub(r"\(([^\)]*)\)", drop_noise_group, cleaned)

    # remaining loose noise words
    cleaned = VIDEO_NOISE_RE.sub(" ", cleaned)

    # catalogue number anywhere in the string, spaced and unspaced
    if catno:
        cleaned = re.sub(re.escape(catno.strip()), " ", cleaned, flags=re.IGNORECASE)
        loose = re.sub(r"[\s\-\.]", "", catno)
        if loose:
            cleaned = re.sub(re.escape(loose), " ", cleaned, flags=re.IGNORECASE)

    # artist and label prefixes or suffixes
    names = list(artists)
    if label:
        names.append(label)
    for name in names:
        name = strip_discogs_suffix(name)
        if len(name) < 3:
            continue
        esc = re.escape(name)
        cleaned = re.sub(r"^\s*" + esc + r"\s*[\-–—:|/]+\s*", " ",
                         cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"\s*[\-–—:|/]+\s*" + esc + r"\s*$", " ",
                         cleaned, flags=re.IGNORECASE)

    cleaned = POSITION_PREFIX_RE.sub("", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned.strip(" -–—:|/")


# ----------------------------------------------------------------------------
# release metadata
# ----------------------------------------------------------------------------

def release_artists(release):
    """List of artist names for a release, discogs numbering removed."""
    names = []
    data = release.data or {}
    for artist in data.get("artists", []) or []:
        name = strip_discogs_suffix(artist.get("name", ""))
        if name:
            names.append(name)
    return names


def release_artist_string(release):
    data = release.data or {}
    sort_name = strip_discogs_suffix(data.get("artists_sort", "") or "")
    names = release_artists(release)
    if len(names) > 3:
        return "Various"
    if sort_name:
        return sort_name
    if names:
        return ", ".join(names)
    return "Unknown Artist"


def track_artist_string(track, fallback):
    names = []
    data = track.data or {}
    for artist in data.get("artists", []) or []:
        name = strip_discogs_suffix(artist.get("name", ""))
        if name:
            names.append(name)
    if names:
        return ", ".join(names)
    return fallback


def release_label_and_catno(release):
    data = release.data or {}
    labels = data.get("labels") or []
    if not labels:
        return "", ""
    first = labels[0]
    return strip_discogs_suffix(first.get("name", "")), (first.get("catno", "") or "").strip()


def genre_string(release):
    data = release.data or {}
    styles = data.get("styles") or []
    genres = data.get("genres") or []
    if styles:
        return ", ".join(styles)
    if genres:
        return ", ".join(genres)
    return ""


def build_track_records(release, fallback_artist):
    """
    Playable tracks only. Discogs tracklists also carry 'heading' and 'index'
    rows (side titles, medley parents) which have no audio of their own.
    """
    records = []
    for track in release.tracklist or []:
        data = track.data or {}
        if data.get("type_") and data.get("type_") != "track":
            continue
        title = normalize_unicode(track.title or "")
        if not title:
            continue
        records.append({
            "position": normalize_unicode(track.position or ""),
            "title": title,
            "artist": track_artist_string(track, fallback_artist),
            "duration": parse_duration(track.duration),
        })
    return records


def build_video_records(release):
    """Unique media links on the discogs release page, in the order listed."""
    videos = []
    seen = set()
    try:
        source = release.videos or []
    except Exception:
        source = []
    for video in source:
        url = getattr(video, "url", None)
        if not url or url in seen:
            continue
        seen.add(url)
        videos.append({
            "url": url,
            "title": normalize_unicode(getattr(video, "title", "") or ""),
            "duration": parse_duration(getattr(video, "duration", None)),
        })
    return videos


def release_dir_name(artist, title, catno):
    name = artist + " - " + title
    if catno:
        name += " (" + catno + ")"
    return sanitize_filename(name)


def disc_number_for_position(position):
    """'C2' on a 2xLP is disc 2. 'A1' and 'B3' are disc 1. Numeric gives None."""
    if not position:
        return None
    match = re.match(r"^([A-Za-z])", position.strip())
    if not match:
        return None
    letter = match.group(1).upper()
    if letter < "A" or letter > "Z":
        return None
    # A/B -> 1, C/D -> 2, E/F -> 3 ...
    return (ord(letter) - ord("A")) // 2 + 1


# ----------------------------------------------------------------------------
# video to track matching
# ----------------------------------------------------------------------------

# wording that only ever means a whole release in one file
ALBUM_STRONG_RE = re.compile(
    r"full\s*(album|ep|lp|length)|continuous|megamix|\bmixtape\b|"
    r"\ball\s*tracks\b|\bfull\s*record\b",
    re.IGNORECASE,
)

# wording that usually means it, but is also how half the dance records ever
# pressed name a track: "(Original Mix)", "Side A". Never enough on its own
ALBUM_WEAK_RE = re.compile(r"\bmix\b|\bside\s*[abcd]\b", re.IGNORECASE)


def looks_like_album_video(candidate, track_count, total_duration):
    """
    A single file covering the whole release rather than one track.

    The weak wording needs a long duration to be believed. Without that rule a
    soulseek file called "A1 Something (Original Mix).flac" reads as an album
    rip and gets thrown away, because peers rarely report a length for lossless
    and "mix" is in the name of half the tracks we are looking for.
    """
    if track_count < 2:
        return False
    duration = candidate.get("duration")
    if duration and total_duration and duration >= total_duration * 0.75:
        return True
    title = candidate.get("title", "")
    if ALBUM_STRONG_RE.search(title):
        if duration is None or duration > 15 * 60:
            return True
    if ALBUM_WEAK_RE.search(title) and duration and duration > 15 * 60:
        return True
    return False


def score_pair(track, video, artists, label, catno, release_artist):
    """Score how well a candidate matches a track. Higher is better."""
    track_title = normalize_for_match(track["title"])
    video_clean = normalize_for_match(
        clean_video_title(video["title"], artists, label, catno)
    )
    if not track_title or not video_clean:
        return 0, []

    reasons = []
    score = max(
        fuzz.ratio(track_title, video_clean),
        fuzz.token_set_ratio(track_title, video_clean),
        fuzz.partial_ratio(track_title, video_clean) * 0.9,
    )

    # a standalone position token in the raw name is strong evidence
    position = (track["position"] or "").strip()
    if position:
        pattern = r"(?<![A-Za-z0-9])" + re.escape(position) + r"(?![A-Za-z0-9])"
        if re.search(pattern, video["title"], re.IGNORECASE):
            score += 25
            reasons.append("position")

    track_len = track["duration"]
    video_len = video["duration"]
    if track_len and video_len:
        diff = abs(track_len - video_len)
        if diff <= 3:
            score += 20
            reasons.append("duration")
        elif diff <= 10:
            score += 10
            reasons.append("duration~")
        elif length_verdict(video_len, track_len)[0] == "snippet":
            # a preview upload of the right track under the right name. the
            # title will match perfectly, which is exactly why the length has
            # to be able to veto it
            score -= 60
            reasons.append("snippet")
        elif diff > 45 and diff > track_len * 0.25:
            score -= 30
            reasons.append("duration-mismatch")

    # a per track artist named in the video title, for various artists releases
    if track["artist"] and track["artist"] != release_artist:
        if normalize_for_match(track["artist"]) in normalize_for_match(video["title"]):
            score += 10
            reasons.append("artist")

    return score, reasons


def accept_match(score, reasons):
    """
    Whether a candidate is a good enough match to take.

    Lengths that disagree badly usually mean a live take, an edit or a different
    mix, so leave the track missing rather than take the wrong file, unless a
    position marker says it really is this track.

    A snippet is the exception that nothing overrides. A preview upload has the
    right artist, the right title and often the right position in its name, so
    every other signal says take it, and it is still 90 seconds of a six minute
    record.
    """
    if "snippet" in reasons:
        return False
    if "duration-mismatch" in reasons and "position" not in reasons:
        return False
    strong = "position" in reasons or "duration" in reasons
    return score >= 70 or (score >= 55 and strong)


def match_videos_to_tracks(tracks, videos, artists, label, catno, release_artist):
    """
    Greedy best first assignment of candidate files to tracks.

    Returns (assignments, whole_release, unmatched) where assignments maps a
    track index to {"candidate", "score", "reasons"}. A candidate is a file on
    disk, a file offered by a soulseek peer or something linked from the release
    page: all three arrive as {"title", "duration"} and all three are scored
    here, so there is one matcher rather than one per source.
    """
    total_duration = 0
    for track in tracks:
        total_duration += track["duration"] or 0
    if total_duration == 0:
        total_duration = None

    whole_release = []
    candidates = []
    for video in videos:
        if looks_like_album_video(video, len(tracks), total_duration):
            whole_release.append(video)
        else:
            candidates.append(video)

    pairs = []
    for ti in range(len(tracks)):
        for vi in range(len(candidates)):
            score, reasons = score_pair(tracks[ti], candidates[vi], artists,
                                        label, catno, release_artist)
            pairs.append((score, ti, vi, reasons))
    pairs.sort(key=lambda p: p[0], reverse=True)

    assignments = {}
    used_videos = set()
    for score, ti, vi, reasons in pairs:
        if ti in assignments or vi in used_videos:
            continue
        if accept_match(score, reasons):
            assignments[ti] = {
                "candidate": candidates[vi],
                "score": round(score, 1),
                "reasons": reasons,
            }
            used_videos.add(vi)

    # a single track release with one leftover candidate: take it anyway, single
    # track uploads are often titled with only the artist or the label name
    if len(tracks) == 1 and not assignments and len(candidates) == 1:
        assignments[0] = {
            "candidate": candidates[0],
            "score": 0,
            "reasons": ["only-candidate"],
        }
        used_videos.add(0)

    unmatched = []
    for vi in range(len(candidates)):
        if vi not in used_videos:
            unmatched.append(candidates[vi])

    return assignments, whole_release, unmatched


# ----------------------------------------------------------------------------
# ledger
# ----------------------------------------------------------------------------

def ledger_path(root):
    return os.path.join(root, LEDGER_NAME)


def load_ledger(root):
    path = ledger_path(root)
    if not os.path.exists(path):
        return {"version": LEDGER_VERSION, "releases": {}}
    try:
        ledger = json.loads(open(path, "r", encoding="utf-8").read())
    except (ValueError, OSError) as e:
        print(f"warning: could not read ledger {path}: {e}")
        backup = path + ".corrupt-" + str(int(time.time()))
        try:
            os.replace(path, backup)
            print(f"moved unreadable ledger to {backup}, starting a new one")
        except OSError:
            pass
        return {"version": LEDGER_VERSION, "releases": {}}
    if "releases" not in ledger:
        ledger["releases"] = {}
    if "version" not in ledger:
        ledger["version"] = LEDGER_VERSION
    return ledger


def save_ledger(root, ledger):
    """Write via a temp file so an interrupt cannot leave a half written ledger."""
    path = ledger_path(root)
    tmp = path + ".tmp"
    ledger["updated"] = datetime.datetime.now().isoformat(timespec="seconds")
    open(tmp, "w", encoding="utf-8").write(json.dumps(ledger, indent=4))
    os.replace(tmp, path)


def flagged_keys(entry):
    """
    What has been marked up by hand in the ledger as wrongly ripped.

    The ledger is the interface, because the two things that go wrong are only
    obvious to a person listening. Open it, find the release, and write a note:

        on one track   "A1": { ..., "flag": "snippet, not the full track" }
        on the release { "id": 123, ..., "flag": "wrong record entirely" }

    The note is free text and is kept as the reason. A flag on the release means
    every track, which is the ambiguous match case where nothing in the folder
    belongs to this record.

    Returns (keys, release wide note).
    """
    if not entry:
        return [], None
    tracks = entry.get("tracks") or {}
    release_note = entry.get("flag")
    if release_note:
        return sorted(tracks.keys()), str(release_note)
    return sorted(key for key, track in tracks.items()
                  if (track or {}).get("flag")), None


def quarantine_file(root, entry, filename):
    """
    Move a rejected file out of the library rather than deleting it.

    A bad rip is still the evidence of what went wrong, and a flag written in
    haste should cost nothing to undo. -delete-flagged removes them instead.
    Returns where it went, or None if there was nothing to move.
    """
    source = os.path.join(root, entry.get("dir", ""), filename)
    if not os.path.exists(source):
        return None

    if "-delete-flagged" in sys.argv:
        try:
            os.remove(source)
            return "deleted"
        except OSError as e:
            print(f"    [warn] could not delete {source}: {e}")
            return None

    target_dir = os.path.join(root, REJECTED_DIR, entry.get("dir", ""))
    os.makedirs(target_dir, exist_ok=True)
    target = os.path.join(target_dir, filename)
    stem, ext = os.path.splitext(target)
    count = 2
    while os.path.exists(target):
        target = f"{stem} ({count}){ext}"
        count += 1
    try:
        shutil.move(source, target)
        return target
    except OSError as e:
        print(f"    [warn] could not move {source}: {e}")
        return None


def apply_flags(ctx):
    """
    Act on hand written flags before any source is asked for anything.

    Three things have to happen together or the flag does not stick. The file
    goes, so it is not adopted straight back off disk. What it came from is
    recorded as rejected, so the matcher cannot choose the same bad copy again.
    And the source that produced it is forgotten, so the next ordinary run has a
    reason to go looking rather than treating the release as already done.
    """
    previous = ctx.get("previous")
    keys, release_note = flagged_keys(previous)
    if not keys:
        return

    entry = ctx["entry"]
    tracks = previous.get("tracks") or {}
    name = f"{previous.get('artist', '?')} - {previous.get('title', '?')}"
    print(f"    [flag] {name}: {len(keys)} track(s) flagged"
          + (f", {release_note}" if release_note else ""))

    forget = set()
    for key in keys:
        track = tracks.get(key) or {}
        reason = str(track.get("flag") or release_note or "flagged by hand")
        identity = track_identity(track)
        moved = quarantine_file(ctx["root"], previous, track.get("file") or "")

        if identity:
            entry.setdefault("rejected", []).append({
                "id": identity,
                "track": key,
                "reason": reason,
                "source": track.get("source", ""),
                "when": datetime.datetime.now().isoformat(timespec="seconds"),
            })
        if track.get("source"):
            forget.add(track["source"])

        where = "" if moved in (None, "deleted") else f" -> {REJECTED_DIR}"
        print(f"    [flag] {key} {track.get('title', '?')}: {reason}"
              f"{' (deleted)' if moved == 'deleted' else where}")

    # a whole release flagged is every source wrong about it, so ask them all
    # again. one track is only the source that produced that track
    if release_note:
        previous["sources_tried"] = []
    else:
        previous["sources_tried"] = [s for s in tried_sources(previous)
                                     if s not in forget]


def candidate_identity(candidate):
    """
    A stable name for the thing a track would be taken from.

    The same shape whichever source offered it, so one rejected list can keep
    every source from offering the same bad file twice. A peer's copy is named
    by peer and path, since the same filename from someone else is a different
    file and may well be fine.
    """
    if candidate.get("username") and candidate.get("filename"):
        return f"slsk:{candidate['username']}:{candidate['filename']}"
    if candidate.get("path"):
        return "file:" + os.path.abspath(candidate["path"]).lower()
    return candidate.get("url", "")


def track_identity(track):
    """The same name, worked back out of what the ledger recorded."""
    if track.get("peer") and track.get("remote_file"):
        return f"slsk:{track['peer']}:{track['remote_file']}"
    if track.get("local_file"):
        return "file:" + os.path.abspath(track["local_file"]).lower()
    return track.get("video") or track.get("source_url") or ""


def rejected_identities(entry):
    """What this release has been told never to take again."""
    return {row.get("id") for row in (entry or {}).get("rejected") or []
            if row.get("id")}


def drop_rejected(ctx, candidates):
    """
    Remove anything this release has been flagged for.

    Without this a flagged rip is undone by the very run that acts on the flag:
    the matcher scores the same candidates, the best one is the same one, and
    the same bad file comes straight back down. Flagging has to be something the
    ledger remembers, not just a deleted file.

    Read off the entry being built rather than the previous one, because that is
    where both live: the rejections carried forward from earlier runs, and the
    ones apply_flags has just added from this run's flags.
    """
    rejected = rejected_identities(ctx.get("entry"))
    if not rejected:
        return candidates
    kept = [c for c in candidates if candidate_identity(c) not in rejected]
    dropped = len(candidates) - len(kept)
    if dropped and verbose():
        print(f"    [slsk] skipping {dropped} previously flagged candidate(s)"
              if kept else f"    skipping {dropped} previously flagged")
    return kept


def tried_sources(entry):
    """
    Which sources a release has already been through.

    A ledger written before -source existed had only the release links to work
    with, so an entry with no list at all gets read as having tried that and
    nothing else. Without this, the first soulseek pass over an old ledger would
    think every release had already been offered to soulseek.

    An empty list is not the same as a missing one: it means every source has
    been deliberately forgotten, which is what flagging a release does so that
    all of them are asked again.
    """
    if not entry:
        return []
    if "sources_tried" not in entry:
        return [SOURCE_YOUTUBE]
    return [str(s) for s in entry.get("sources_tried") or []]


def untried_sources(entry, sources):
    tried = tried_sources(entry)
    return [source for source in sources if source not in tried]


def merge_tried(previous, entry):
    """Union of the sources a release has been through, oldest order kept."""
    merged = tried_sources(previous) if previous else []
    for source in entry.get("sources_tried") or []:
        if source not in merged:
            merged.append(source)
    return merged


def should_rip(key, ledger, sources):
    """Decide whether a release needs work this session."""
    previous = ledger["releases"].get(key)
    if previous is None:
        return True, None
    if "-force" in sys.argv:
        return True, previous
    # flagged by hand, so it needs doing again whatever it says it is. this has
    # to come before the complete check: a snippet noticed by ear is sitting in
    # a release the ledger is perfectly happy with
    if flagged_keys(previous)[0]:
        return True, previous
    status = previous.get("status")
    if status == STATUS_COMPLETE:
        return False, previous
    # a source this release has never been offered to is new work whatever the
    # status says. a pass with one source leaves plenty of releases partial, and
    # the session that follows on the other source must not read that as done:
    # this is what lets the two be run days apart with no flags to remember
    if untried_sources(previous, sources):
        return True, previous
    if status in RETRYABLE:
        return "-retry" in sys.argv, previous
    if status == STATUS_NO_VIDEOS:
        # the page may have gained links since, but only look again on -retry
        return "-retry" in sys.argv, previous
    return True, previous


# ----------------------------------------------------------------------------
# download, verify and tag
# ----------------------------------------------------------------------------

def short_error(e):
    """
    yt-dlp errors run to several lines of advice, flatten them to one.

    Kept long enough that classify_error can still see the wording it matches
    on, the printing side clips it again for the console.
    """
    text = str(e).replace("\n", " ").strip()
    text = re.sub(r"\s+", " ", text)
    text = re.sub(r"^ERROR:\s*", "", text)
    if len(text) > 400:
        text = text[:400].rstrip() + "..."
    return f"{type(e).__name__}: {text}"


def cookie_options(opts):
    """
    Sign requests in as the user, from their own browser session.

    Anonymous requests increasingly get asked to prove they are a person.
    Passing your own cookies is what yt-dlp itself recommends when that happens,
    and it means the request is made as you rather than as nobody.

    Note that on windows, chrome and edge cookies cannot be read at all any
    more. Chromium app bound encryption makes yt-dlp fail with a DPAPI decrypt
    error, so -cookies-from-browser only really works with firefox here.
    """
    browser = arg_value("-cookies-from-browser")
    if browser:
        opts["cookiesfrombrowser"] = (browser.lower(),)
    cookie_file = arg_value("-cookies")
    if cookie_file:
        opts["cookiefile"] = os.path.abspath(os.path.expanduser(cookie_file))
    return opts


def player_client_options(opts):
    """
    Which client yt-dlp presents itself as.

    Sites treat their various clients unevenly, and treat vpn and datacenter
    addresses more harshly again, so the one that works changes over time.
    Leaving this unset uses yt-dlp's own default, which is usually right. When a
    run starts getting refused, this is the first thing to try, along with
    updating yt-dlp itself.
    """
    client = arg_value("-player-client")
    if client:
        clients = [c.strip() for c in client.split(",") if c.strip()]
        opts["extractor_args"] = {"youtube": {"player_client": clients}}
    return opts


def quiet_logger():
    """
    yt-dlp writes its own errors straight to stderr even when quiet, which
    duplicates the message we already report per track. Swallow its output and
    let the returned error be the single source of truth.
    """
    def swallow(msg):
        pass

    return types.SimpleNamespace(
        debug=swallow, info=swallow, warning=swallow, error=swallow)


def download_once(video_url, out_stem, quality):
    """One download attempt. Returns (path, error)."""
    produced = []

    def postprocessor_hook(d):
        if d.get("status") == "finished":
            path = (d.get("info_dict") or {}).get("filepath")
            if path:
                produced.append(path)

    opts = {
        "format": "bestaudio/best",
        "outtmpl": out_stem + ".%(ext)s",
        "postprocessors": [{
            "key": "FFmpegExtractAudio",
            "preferredcodec": "mp3",
            "preferredquality": quality,
        }],
        "postprocessor_hooks": [postprocessor_hook],
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
        "noplaylist": True,
        "retries": 3,
        "fragment_retries": 3,
        "sleep_interval_requests": 1,
        "ignoreerrors": False,
        "overwrites": True,
        "logger": quiet_logger(),
    }
    cookie_options(opts)
    player_client_options(opts)

    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            ydl.download([video_url])
    except Exception as e:
        return None, short_error(e)

    for path in reversed(produced):
        if path.lower().endswith(".mp3") and os.path.exists(path):
            return path, None

    # the hook can be skipped when the file was already present, check disk
    fallback = out_stem + ".mp3"
    if os.path.exists(fallback):
        return fallback, None
    return None, "download produced no mp3"


# ----------------------------------------------------------------------------
# reading a download failure
# ----------------------------------------------------------------------------

# How to read what yt-dlp reported, so the log can say what actually happened
# rather than just "it did not work". Each entry is:
#
#   (kind, retry, patterns, label, hint)
#
# kind goes in the ledger, label is printed next to the track, retry says
# whether waiting and asking again has any chance of working, and hint is the
# advice printed once per session the first time that kind shows up.
#
# Order matters, first match wins, so the specific cases come before the ones
# whose wording would otherwise swallow them.
LINK_ERRORS = [
    ("age_check", False,
     ["confirm your age", "age-restricted", "age restricted",
      "inappropriate for some users"],
     "age restricted, a signed in viewer is required",
     "age gated media never comes down anonymously: pass "
     "-cookies-from-browser firefox, or -cookies <file>"),

    ("bot_check", True,
     ["not a bot", "sign in to confirm", "sign in to view", "please sign in",
      "account cookies"],
     "asked to prove we are a person, a signed in session is required",
     "the site wants a login. -cookies-from-browser firefox works, chrome and "
     "edge cookies cannot be read on windows any more, failing that export a "
     "cookies.txt and pass -cookies <file>"),

    ("rate_limit", True,
     ["http error 429", "too many requests", "rate-limit", "rate limit",
      "please try again later"],
     "429 too many requests, this address is rate limited",
     "a real rate limit on your address, not a broken link. stop for an hour "
     "or two then re-run with -retry -slow, or spend the time on -source "
     "soulseek instead. a vpn exit gets limited far sooner than a home "
     "connection"),

    ("forbidden", True,
     ["http error 403", "403: forbidden", "forbidden"],
     "403 forbidden, the media request was rejected",
     "403 on everything is usually yt-dlp being out of date rather than a "
     "ban, 'pip install -U yt-dlp' first. if it persists try another "
     "-player-client (tv, ios, web_safari) or pass cookies. 403 on the odd "
     "link is just that link"),

    ("geo_blocked", False,
     ["in your country", "from your location", "in your location",
      "geo restricted", "geo-restricted", "blocked it on copyright grounds"],
     "not available where this address appears to be",
     "blocked for this region, only a different exit will get it"),

    ("no_formats", False,
     ["requested format is not available", "no video formats",
      "unable to extract", "failed to extract", "nsig extraction",
      "signature extraction", "player response", "unsupported url"],
     "yt-dlp could not read the page it was pointed at",
     "the site changed and this yt-dlp cannot follow it, "
     "'pip install -U yt-dlp' is the fix nine times out of ten"),

    ("unavailable", False,
     ["video unavailable", "private video", "removed by the uploader",
      "has been terminated", "video has been removed", "no longer available",
      "members-only", "join this channel", "who has blocked it",
      "this live event", "premieres in"],
     "gone, private or members only",
     "nothing to do here, what the page links no longer exists. the discogs "
     "page needs a different link, or another source has it"),

    ("network", True,
     ["timed out", "timeout", "connection reset", "connection aborted",
      "connection refused", "remote end closed", "name resolution",
      "unable to connect", "http error 5"],
     "network error",
     "transient, the backoff usually rides it out"),
]

HTTP_STATUS_RE = re.compile(r"http error (\d{3})", re.IGNORECASE)


def http_status_in(text):
    """The status the server answered with, when the error carries one."""
    match = HTTP_STATUS_RE.search(text or "")
    return int(match.group(1)) if match else None


def classify_error(text):
    """
    Work out what actually went wrong. Returns (kind, retry, label, hint).

    A refusal means our address is being turned away and waiting may clear it.
    Something that no longer exists never will, so the two must not be treated
    the same: one is worth another attempt, the other is worth recording and
    moving on. Anything unrecognised counts as a problem with that one link, so
    an odd failure cannot stall the session.
    """
    low = (text or "").lower()
    for kind, retry, patterns, label, hint in LINK_ERRORS:
        for pattern in patterns:
            if pattern in low:
                return kind, retry, label, hint
    return "error", False, "download failed", ""


# why a soulseek attempt came to nothing, in the same shape as the kinds above
# so that one tally and one set of hints covers every source
SLSK_REASONS = {
    "slsk_offline": (
        "slskd could not be reached, so nothing was tried on soulseek. start "
        "the daemon and check -slsk-host, or run -slsk-test"),
    "slsk_no_results": (
        "nobody answered the search. obscure records genuinely are not shared, "
        "and this is the gap the other sources exist to fill"),
    "slsk_no_match": (
        "peers answered but nothing lined up with the tracklist. -verbose "
        "prints the candidates and their scores, which usually shows whether "
        "it was a different pressing or just an unhelpful filename"),
    "slsk_no_peer": (
        "the file exists but no peer would take the request. usually a share "
        "ratio: peers commonly refuse anyone not sharing, so point slskd's "
        "shares at a real directory"),
    "slsk_queue_timeout": (
        "still queued when the wait ran out. it is left enqueued in slskd and "
        "may well finish in the background, a later -retry picks it up off "
        "disk. -slsk-wait buys more patience per release"),
    "slsk_errored": (
        "the transfer started and then failed, usually the peer going offline "
        "mid upload. a -retry finds a different peer"),
    "slsk_missing_file": (
        "slskd says the transfer finished but the file is not under the "
        "downloads directory. check -slsk-downloads matches slskd's own "
        "downloads path"),
    "slsk_encode_failed": (
        "the file arrived but ffmpeg could not turn it into an mp3. check "
        "ffmpeg is on PATH and that the download is not truncated"),
}

# importing files that are already on disk
LOCAL_REASONS = {
    "local_no_audio": (
        "the folder matched a release but holds no audio this can read. mp3, "
        "flac, wav, aiff, m4a and ogg are all fine"),
    "local_no_match": (
        "the folder is the right release but nothing in it lined up with this "
        "track. -debug shows the lengths, -verbose the scores. a file named "
        "with the position, 'A1 ...', is the easiest thing to match"),
    "local_convert_failed": (
        "ffmpeg could not convert the file. check it plays, and that ffmpeg is "
        "on PATH"),
}

# failures that are nothing to do with getting hold of the file
FILE_REASONS = {
    "snippet": (
        "the file arrived intact but runs far shorter than the track: a preview "
        "or a snippet rather than the whole thing, which is common among links "
        "on a release page. the track is left missing so another source can "
        "have a go. -no-length-check accepts them anyway"),
    "deleted": (
        "the file was deleted from the library by hand and -filecheck took "
        "that to mean it was wrong. the copy it came from will not be taken "
        "again. drop the right file in the release folder and -filecheck "
        "again to adopt it"),
}

# the two ways the release links come up empty before a download is even tried
LINK_REASONS = {
    "yt_no_videos": (
        "the discogs page links nothing playable. users do add links over time, "
        "so -retry looks again another day, and the other sources are the "
        "better bet meanwhile"),
    "yt_no_match": (
        "the page has links but none of them lines up with the tracklist. "
        "-verbose prints the candidates and their scores"),
}


def clip(text, length=200):
    text = (text or "").strip()
    if len(text) <= length:
        return text
    return text[:length].rstrip() + "..."


def failure_hints():
    """Advice by kind, across both sources."""
    hints = {kind: hint for kind, _r, _p, _l, hint in LINK_ERRORS}
    hints.update(SLSK_REASONS)
    hints.update(LINK_REASONS)
    hints.update(LOCAL_REASONS)
    hints.update(FILE_REASONS)
    return hints


def failure(kind, label, source):
    """A failure record in the shape note_refusal and the ledger want."""
    return {
        "kind": kind,
        "label": label,
        "hint": failure_hints().get(kind, ""),
        "blocked": False,
        "source": source,
    }


def note_refusal(info):
    """Count a failure by kind, and print its advice the first time it shows."""
    kind = info.get("kind", "error")
    refusal_counts[kind] = refusal_counts.get(kind, 0) + 1
    hint = info.get("hint")
    if hint and kind not in hints_shown:
        hints_shown.add(kind)
        print(f"    [hint] {hint}")


def note_source(source):
    source_counts[source] = source_counts.get(source, 0) + 1


def download_audio(video_url, out_stem, quality):
    """
    Download with backoff. Returns (path, error, info).

    info is None when the download worked, otherwise a dict describing the last
    failure: the kind, the printable label, the http status if there was one, how
    many attempts were spent, and whether we were being refused rather than the
    thing simply not being there any more.

    A short burst is tolerated and then requests start getting refused, far
    sooner from a vpn address than a home one. Backing off and trying again
    clears it often enough to be worth doing before giving up on a track.
    """
    attempts = max(1, arg_int("-attempts", 4))
    backoff = arg_float("-backoff", 60.0)

    info = None
    for attempt in range(attempts):
        path, error = download_once(video_url, out_stem, quality)
        if not error:
            return path, None, None

        kind, retry, label, hint = classify_error(error)
        status = http_status_in(error)
        info = {
            "kind": kind,
            "label": label,
            "hint": hint,
            "blocked": retry,
            "attempts": attempt + 1,
            "error": error,
        }
        if status:
            info["http_status"] = status

        # the first failure is the informative one, so print what came back
        # verbatim rather than leaving "it was refused" to be guessed at
        if attempt == 0 or verbose():
            print(f"    [why ] {label}")
            print(f"           yt-dlp: {clip(error)}")

        if not retry:
            # gone, or a broken extractor. another go only wastes requests
            return None, error, info

        if attempt + 1 < attempts:
            wait = jittered(backoff * (2 ** attempt))
            print(f"    [wait] backing off {int(wait)}s, "
                  f"attempt {attempt + 2} of {attempts}")
            time.sleep(wait)

    return None, info["error"], info


# ----------------------------------------------------------------------------
# getting a downloaded file into the library
# ----------------------------------------------------------------------------

def to_mp3(src, dest, quality):
    """
    Re-encode a file to mp3. Returns (ok, error).

    Soulseek serves a lot of flac, and the library, the tagger and everything
    downstream are mp3. -map_metadata -1 drops the peer's tags on the way
    through: the discogs metadata is written afterwards and is meant to be the
    only thing describing the file.
    """
    command = [
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
        "-i", src,
        "-map_metadata", "-1",
        "-map", "a",
        "-c:a", "libmp3lame", "-b:a", f"{quality}k",
        dest,
    ]
    try:
        result = subprocess.run(command, capture_output=True, text=True)
    except FileNotFoundError:
        return False, "ffmpeg not found on PATH"
    except Exception as e:
        return False, f"{type(e).__name__}: {e}"

    if result.returncode != 0 or not os.path.exists(dest):
        detail = (result.stderr or "").strip().replace("\n", " ")
        return False, f"ffmpeg failed: {clip(detail, 160)}"
    return True, None


def place_file(src, out_stem, quality):
    """
    Put a downloaded file in the release directory as <out_stem>.mp3.

    A peer's mp3 is moved as it is, because re-encoding mp3 to mp3 only throws
    quality away for nothing. Anything else is transcoded. Either way the
    source file is consumed, so a re-run does not trip over last time's
    leftovers. Returns (path, transcoded, error).
    """
    target = out_stem + ".mp3"
    ext = os.path.splitext(src)[1].lower()

    try:
        if ext == ".mp3":
            shutil.move(src, target)
            return target, False, None
    except OSError as e:
        return None, False, f"could not move file: {e}"

    ok, error = to_mp3(src, target, quality)
    if not ok:
        return None, True, error
    try:
        os.remove(src)
    except OSError:
        # the mp3 is written, a leftover original is untidy but harmless
        pass
    return target, True, None


# ----------------------------------------------------------------------------
# is this the whole track
# ----------------------------------------------------------------------------

# How far a file may be from the discogs duration before it is worth saying so.
#
# The two directions are not symmetric, and treating them as if they were is
# what lets a snippet through. A file that runs long is usually benign: a vinyl
# rip carries the run in groove and the lift at the end, a fade outlasts the
# timing the label printed, an upload has a talkover intro or applause. A file
# that runs short is usually not the track at all. It is a preview, a radio
# edit, or one of the 90 second snippet uploads labels put up to promote a
# release, and discogs users attach those to release pages like any other video.
SHORT_RATIO = 0.15       # missing 15% of the track: worth flagging
SHORT_SECONDS = 20       # ... and at least this much of it, for short tracks
SNIPPET_RATIO = 0.40     # missing 40%: this is not the track, it is a preview
SNIPPET_SECONDS = 45
LONG_RATIO = 0.35        # a third longer than discogs says: worth flagging
LONG_SECONDS = 60        # ... and at least a minute over


def length_verdict(length, expected):
    """
    How a measured length compares with the one discogs lists.

    Returns (verdict, note) where verdict is one of "unknown", "ok", "short",
    "snippet" or "long". Only "snippet" is grounds for rejecting a file: the
    discogs timings are user entered and often rounded, so a flag is a flag and
    not a verdict on its own.
    """
    if not expected or not length:
        return "unknown", "no discogs duration to compare against"

    missing = expected - length
    excess = length - expected

    if missing >= max(SNIPPET_SECONDS, expected * SNIPPET_RATIO):
        return "snippet", (f"{length}s against discogs {expected}s, "
                           f"{missing}s short: a snippet or an edit, not the "
                           f"whole track")
    if missing >= max(SHORT_SECONDS, expected * SHORT_RATIO):
        return "short", f"{length}s against discogs {expected}s, {missing}s short"
    if excess >= max(LONG_SECONDS, expected * LONG_RATIO):
        return "long", f"{length}s against discogs {expected}s, {excess}s over"
    return "ok", f"{length}s against discogs {expected}s"


def measure_silence(path, length):
    """
    Leading and trailing silence in a file, in seconds.

    This is the tolerance for a rip that runs long: the run in groove, the gap
    before the needle finds the first beat and the lift at the end are padding,
    not a different take, and a file should not be flagged for carrying them.
    Returns (lead_in, lead_out), or (None, None) if ffmpeg cannot say.
    """
    command = ["ffmpeg", "-hide_banner", "-nostats", "-i", path,
               "-af", "silencedetect=noise=-50dB:d=0.5", "-f", "null", "-"]
    try:
        result = subprocess.run(command, capture_output=True, text=True)
    except (FileNotFoundError, OSError):
        return None, None

    blocks = []
    pending = None
    for line in (result.stderr or "").splitlines():
        if "silence_start:" in line:
            try:
                pending = float(line.split("silence_start:")[1].strip())
            except ValueError:
                pending = None
        elif "silence_end:" in line and pending is not None:
            try:
                end = float(line.split("silence_end:")[1].split("|")[0].strip())
            except ValueError:
                end = None
            if end is not None:
                blocks.append((pending, end))
            pending = None
    if pending is not None and length:
        # a silence that never ended, so it ran to the end of the file
        blocks.append((pending, float(length)))

    if not blocks:
        return 0.0, 0.0

    lead_in = blocks[0][1] if blocks[0][0] <= 1.0 else 0.0
    last_start, last_end = blocks[-1]
    lead_out = 0.0
    if length and last_end >= length - 1.0:
        lead_out = max(0.0, length - last_start)
    return lead_in, lead_out


def check_length(path, length, expected, measure=False):
    """
    Judge a file's length against discogs, silence allowed for.

    A file flagged long gets its silence measured before the flag sticks, since
    padding is the usual reason and it is not a fault. Nothing excuses a file
    that is short, so the measurement is not wasted on those.
    """
    verdict, note = length_verdict(length, expected)
    detail = {"length_verdict": verdict, "length_note": note}
    if expected:
        detail["expected_length"] = expected

    if verdict == "long" and (measure or debug()):
        lead_in, lead_out = measure_silence(path, length)
        if lead_in is not None:
            silence = int(lead_in + lead_out)
            sounding = length - silence
            detail["silence"] = silence
            detail["sounding_length"] = sounding
            revised, revised_note = length_verdict(sounding, expected)
            if revised == "ok":
                verdict = "ok"
                note = (f"{length}s with {silence}s of lead in and lead out, "
                        f"{sounding}s of audio against discogs {expected}s")
            else:
                verdict, note = revised, revised_note + f" ({silence}s silence)"
            detail["length_verdict"] = verdict
            detail["length_note"] = note

    return verdict, note, detail


def verify_audio(path, expected_duration):
    """
    Confirm the file on disk is a real, playable mp3. Returns (ok, detail).

    detail carries the measured length and how it compares with the duration
    discogs lists. A file far shorter than the track is rejected outright: it
    verifies as a perfectly good mp3, it is simply not the track we asked for,
    and keeping it means a snippet sitting in the library pretending to be the
    record. -no-length-check turns that off.
    """
    if not path or not os.path.exists(path):
        return False, {"error": "file missing"}

    size = os.path.getsize(path)
    if size < 16 * 1024:
        return False, {"error": f"file too small ({size} bytes)"}

    detail = {"bytes": size}
    try:
        from mutagen.mp3 import MP3
        info = MP3(path).info
        length = int(info.length)
        detail["length"] = length
        if length < 5:
            detail["error"] = f"audio too short ({length}s)"
            return False, detail
    except Exception as e:
        # unreadable by mutagen means it is not a usable mp3
        detail["error"] = f"unreadable mp3: {e}"
        return False, detail

    verdict, note, length_detail = check_length(path, length, expected_duration)
    detail.update(length_detail)

    if debug():
        print(f"    [len ] {os.path.basename(path)}: {note} [{verdict}]")

    if verdict == "snippet" and "-no-length-check" not in sys.argv:
        detail["error"] = note
        detail["kind"] = "snippet"
        return False, detail
    if verdict in ("short", "long", "snippet"):
        detail["warning"] = note

    return True, detail


def fetch_cover(release, token):
    """Primary release image as (bytes, mime), or (None, None)."""
    data = release.data or {}
    images = data.get("images") or []
    if not images:
        return None, None
    ordered = sorted(images, key=lambda i: 0 if i.get("type") == "primary" else 1)
    uri = ordered[0].get("uri")
    if not uri:
        return None, None
    try:
        import requests
        headers = {"User-Agent": "diig-rip/1.0 +https://github.com/polymonster/diig"}
        if token:
            headers["Authorization"] = f"Discogs token={token}"
        resp = requests.get(uri, headers=headers, timeout=30)
        if resp.status_code == 429:
            # artwork is not worth stalling the rip for, say so and go on
            # untagged rather than spending the retry budget on a picture
            global discogs_rate_limited
            discogs_rate_limited = True
            print("    [warn] discogs rate limited the cover image, "
                  "ripping without artwork")
            return None, None
        if resp.status_code != 200 or not resp.content:
            if verbose():
                print(f"    [warn] cover image returned {resp.status_code}")
            return None, None
        mime = resp.headers.get("Content-Type", "image/jpeg").split(";")[0]
        if not mime.startswith("image/"):
            mime = "image/jpeg"
        return resp.content, mime
    except Exception:
        return None, None


def tag_mp3(path, meta, cover_data, cover_mime):
    """
    Write id3v2.4 tags onto a downloaded mp3.

    Everything already on the file is thrown away first. A file off soulseek
    arrives with whoever ripped it's tags, comments, artwork and ratings, and
    the point of ripping against a discogs release is that the metadata is
    consistent: discogs is the only thing that should describe these files.
    """
    from mutagen.id3 import (
        ID3, APIC, TIT2, TPE1, TPE2, TALB, TRCK, TPOS,
        TDRC, TCON, TPUB, TXXX, WXXX, COMM,
    )

    # built from nothing rather than read from the file, so whatever tags came
    # with it are gone by construction rather than by remembering to delete
    # each frame we do not happen to overwrite
    tags = ID3()

    tags["TIT2"] = TIT2(encoding=3, text=meta["title"])
    tags["TPE1"] = TPE1(encoding=3, text=meta["artist"])
    tags["TPE2"] = TPE2(encoding=3, text=meta["album_artist"])
    tags["TALB"] = TALB(encoding=3, text=meta["album"])
    tags["TRCK"] = TRCK(encoding=3,
                        text=f"{meta['track_number']}/{meta['track_total']}")

    if meta.get("disc_number"):
        tags["TPOS"] = TPOS(encoding=3, text=str(meta["disc_number"]))
    if meta.get("year"):
        tags["TDRC"] = TDRC(encoding=3, text=str(meta["year"]))
    if meta.get("genre"):
        tags["TCON"] = TCON(encoding=3, text=meta["genre"])
    if meta.get("label"):
        tags["TPUB"] = TPUB(encoding=3, text=meta["label"])
    if meta.get("catno"):
        tags.add(TXXX(encoding=3, desc="CATALOGNUMBER", text=meta["catno"]))
    if meta.get("position"):
        tags.add(TXXX(encoding=3, desc="DISCOGS_POSITION", text=meta["position"]))
    if meta.get("release_id"):
        tags.add(TXXX(encoding=3, desc="DISCOGS_RELEASE_ID",
                      text=str(meta["release_id"])))
    if meta.get("release_url"):
        tags.add(WXXX(encoding=3, desc="DISCOGS", url=meta["release_url"]))
    if meta.get("source_url"):
        tags.add(TXXX(encoding=3, desc="SOURCE_URL", text=meta["source_url"]))
        tags.add(COMM(encoding=3, lang="eng", desc="",
                      text="ripped by diig from " + meta["source_url"]))

    if cover_data:
        tags.add(APIC(encoding=3, mime=cover_mime, type=3, desc="Cover",
                      data=cover_data))

    # v1=0 takes any id3v1 tag off the end too, same reason
    tags.save(path, v2_version=4, v1=0)


# ----------------------------------------------------------------------------
# ripping a single release
# ----------------------------------------------------------------------------

def print_match_plan(tracks, assignments, whole_release, unmatched, source):
    """What a source would take, for -dry-run."""
    print(f"    [{source}]")
    for index in range(len(tracks)):
        track = tracks[index]
        name = f"{track['position'] or index + 1}. {track['title']}"
        match = assignments.get(index)
        if match:
            why = ",".join(match["reasons"]) or "title"
            print(f"    {name} <- {match['candidate']['title']} "
                  f"(score {match['score']}, {why})")
        else:
            print(f"    {name} <- nothing")
    for candidate in whole_release:
        print(f"    [whole release] {candidate['title']}")
    for candidate in unmatched:
        print(f"    [unmatched]     {candidate['title']}")


# ----------------------------------------------------------------------------
# the parts every source shares
# ----------------------------------------------------------------------------

def track_key(ctx, index):
    """How a track is keyed in the ledger: its position, or its number."""
    track = ctx["tracks"][index]
    return track["position"] or str(index + 1)


def track_stem(ctx, index):
    track = ctx["tracks"][index]
    return sanitize_filename("%02d - %s" % (index + 1, track["title"]))


def track_path(ctx, index):
    return os.path.join(ctx["release_dir"], track_stem(ctx, index) + ".mp3")


def new_track_entry(ctx, index):
    track = ctx["tracks"][index]
    return {
        "title": track["title"],
        "position": track["position"],
        "number": index + 1,
    }


def record_track(ctx, index, track_entry):
    ctx["entry"]["tracks"][track_key(ctx, index)] = track_entry


def pending_tracks(ctx):
    """Track indexes still without a file, in tracklist order."""
    return [i for i in range(len(ctx["tracks"])) if i not in ctx["done"]]


def fail_track(ctx, index, status, info, message=None):
    """Record a track a source could not get, and count why it could not."""
    track = ctx["tracks"][index]
    key = track_key(ctx, index)
    reason = message or info.get("label", "")
    track_entry = new_track_entry(ctx, index)
    track_entry["status"] = status
    track_entry["source"] = info.get("source", "")
    track_entry["error"] = reason
    track_entry["error_kind"] = info.get("kind", "error")
    record_track(ctx, index, track_entry)
    note_refusal(info)
    print(f"    [ -- ] {key} {track['title']}: {reason}")
    return track_entry


def plan_tracks(ctx, assignments):
    """
    Mark what a dry run would have taken.

    Recorded in the same place a real rip records a file, so a second source in
    the same dry run plans only the gaps the first one left, exactly as it would
    when actually downloading.
    """
    for index, match in assignments.items():
        if index in ctx["done"]:
            continue
        track_entry = new_track_entry(ctx, index)
        track_entry["status"] = "planned"
        track_entry["candidate"] = match["candidate"]["title"]
        track_entry["match_score"] = match["score"]
        record_track(ctx, index, track_entry)
        ctx["done"][index] = track_entry


def collect_existing(ctx):
    """
    Adopt tracks an earlier session already ripped.

    Done before any source runs rather than inside a download loop, so a second
    session neither searches soulseek nor fetches a link for a track already
    sitting on disk. That is what makes one pass followed later by another cost
    only what is genuinely missing.
    """
    if ctx["force"] or ctx["dry_run"]:
        return
    previous = (ctx["previous"] or {}).get("tracks") or {}
    for index in range(len(ctx["tracks"])):
        path = track_path(ctx, index)
        if not os.path.exists(path):
            continue
        ok, detail = verify_audio(path, ctx["tracks"][index]["duration"])
        if not ok:
            continue
        key = track_key(ctx, index)
        track_entry = new_track_entry(ctx, index)
        track_entry["status"] = "ok"
        track_entry["file"] = os.path.basename(path)
        # keep whatever source got it last time rather than claiming this one.
        # empty where even that is unknown, which reports as unrecorded rather
        # than inventing a source called "disk" that nothing can be run against
        track_entry["source"] = (previous.get(key) or {}).get("source", "")
        track_entry.update(detail)
        record_track(ctx, index, track_entry)
        ctx["done"][index] = track_entry
        print(f"    [skip] {key} {ctx['tracks'][index]['title']} "
              f"(already on disk)")


def track_meta(ctx, index, source_url):
    """The id3 metadata for a track, all of it from discogs."""
    track = ctx["tracks"][index]
    return {
        "title": track["title"],
        "artist": track["artist"],
        "album_artist": ctx["artist"],
        "album": ctx["title"],
        "track_number": index + 1,
        "track_total": len(ctx["tracks"]),
        "disc_number": disc_number_for_position(track["position"]),
        "year": ctx["data"].get("year"),
        "genre": genre_string(ctx["release"]),
        "label": ctx["label"],
        "catno": ctx["catno"],
        "position": track["position"],
        "release_id": ctx["release"].id,
        "release_url": ctx["data"].get("uri", ""),
        "source_url": source_url,
    }


def finish_track(ctx, index, path, source, source_url, track_entry=None):
    """
    The common tail for a file that made it to disk, whatever fetched it.

    Verifies it really is playable audio, writes the discogs tags over whatever
    it arrived with, and records it. Returns True if the track is now ripped.
    """
    track = ctx["tracks"][index]
    key = track_key(ctx, index)
    track_entry = track_entry or new_track_entry(ctx, index)
    track_entry["source"] = source

    ok, detail = verify_audio(path, track["duration"])
    if not ok:
        track_entry["status"] = "failed"
        track_entry.update(detail)
        track_entry["error_kind"] = detail.get("kind", "bad_file")
        record_track(ctx, index, track_entry)
        note_refusal(failure(track_entry["error_kind"],
                             detail.get("error", "unusable file"), source))
        # a snippet is worth deleting rather than leaving to be adopted as
        # "already on disk" by the next session
        if detail.get("kind") == "snippet":
            try:
                os.remove(path)
            except OSError:
                pass
        print(f"    [fail] {key} {track['title']}: {detail.get('error')}")
        return False

    try:
        tag_mp3(path, track_meta(ctx, index, source_url),
                ctx["cover"][0], ctx["cover"][1])
        track_entry["tagged"] = True
    except Exception as e:
        track_entry["tagged"] = False
        track_entry["tag_error"] = f"{type(e).__name__}: {e}"
        print(f"    [warn] {key} tagging failed: {e}")

    track_entry["status"] = "ok"
    track_entry["file"] = os.path.basename(path)
    track_entry.update(detail)
    record_track(ctx, index, track_entry)
    ctx["done"][index] = track_entry
    note_source(source)

    note = ""
    if detail.get("warning"):
        note = " (" + detail["warning"] + ")"
    print(f"    [ ok ] {key} {track['title']}{note}")
    return True


# ----------------------------------------------------------------------------
# soulseek
# ----------------------------------------------------------------------------

# how many per track searches to spend on the gaps the folder search left. each
# costs a search timeout, so chasing a long tracklist file by file is not worth
# it: the folder search is what covers a release properly
TRACK_SEARCH_LIMIT = 6


def query_text(s):
    """
    Trim a name down to something worth typing into a soulseek search.

    Peers are searched by filename, so punctuation, bracketed asides and
    discogs' own disambiguation only narrow the search towards nothing.
    """
    s = strip_discogs_suffix(normalize_unicode(s or ""))
    s = re.sub(r"[\(\[][^\)\]]*[\)\]]", " ", s)
    s = re.sub(r"[^\w\s'&-]", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def soulseek_queries(ctx):
    """
    What to ask soulseek for, most specific first.

    A catalogue number is often the entire folder name for a 12", and is the
    one string that names a pressing rather than a song, so it leads where we
    have one.
    """
    artist = query_text(ctx["artist"])
    album = query_text(ctx["title"])
    label = query_text(ctx["label"])
    catno = query_text(ctx["catno"])

    queries = []
    if catno and len(catno) >= 4:
        queries.append(f"{label} {catno}".strip() if label else catno)
    if artist and album and artist.lower() != "various":
        queries.append(f"{artist} {album}")
    elif album:
        queries.append(album)

    ordered = []
    for query in queries:
        if query and query not in ordered:
            ordered.append(query)
    return ordered


def want_bitrate(ctx):
    quality = str(ctx.get("quality") or "320")
    return int(quality) if quality.isdigit() else 320


def soulseek_search(ctx, client, text, min_bitrate):
    responses = slsk.search(client, text,
                            timeout_ms=arg_int("-slsk-search-timeout", 15000),
                            verbose=verbose())
    return drop_rejected(ctx, slsk.candidates(responses, min_bitrate))


def best_soulseek_folder(ctx, candidates, pending):
    """
    Pick the peer directory that covers the most of what is missing.

    Every folder is scored with the same matcher every other source uses, so one
    implementation decides them all. Ties go to the better format and then to the
    peer most likely to actually serve us, since a free upload slot is the
    difference between a rip that finishes now and one that queues for hours.
    """
    best = None
    for (username, dirname), files in slsk.folders(candidates).items():
        assignments, _whole, _unmatched = match_videos_to_tracks(
            ctx["tracks"], files, ctx["artists"], ctx["label"], ctx["catno"],
            ctx["artist"])
        assignments = {i: m for i, m in assignments.items() if i in pending}
        if not assignments:
            continue
        quality = max(slsk.quality_rank(f, want_bitrate(ctx)) for f in files)
        rank = (len(assignments), quality, slsk.peer_rank(files[0]))
        if best is None or rank > best[0]:
            best = (rank, assignments, username, dirname)

    if best is None:
        return {}, None
    _rank, assignments, username, dirname = best
    if verbose():
        print(f"    [slsk] best folder: {username} :: {dirname} "
              f"({len(assignments)} of {len(pending)} tracks)")
    return assignments, dirname


def soulseek_track_search(ctx, client, index, min_bitrate, taken=()):
    """
    One candidate for one track, for the gaps a folder search left.

    taken is the files already promised to another track. Without it a peer
    whose folder search matched one track can have the same file matched again
    for the next one, and two tracks pointing at a single file is one file and
    one lost track.
    """
    track = ctx["tracks"][index]
    artist = query_text(track["artist"] or ctx["artist"])
    query = f"{artist} {query_text(track['title'])}".strip()
    if not query:
        return None

    best = None
    for candidate in soulseek_search(ctx, client, query, min_bitrate):
        if (candidate["username"], candidate["filename"]) in taken:
            continue
        score, reasons = score_pair(track, candidate, ctx["artists"],
                                    ctx["label"], ctx["catno"], ctx["artist"])
        if not accept_match(score, reasons):
            continue
        rank = (score, slsk.quality_rank(candidate, want_bitrate(ctx)),
                slsk.peer_rank(candidate))
        if best is None or rank > best[0]:
            best = (rank, {"candidate": candidate, "score": round(score, 1),
                           "reasons": reasons})
    return best[1] if best else None


def rip_tracks_soulseek(ctx):
    """
    Rip whatever is still missing from soulseek, through slskd.

    Folder first: a release is normally shared as a directory, and one peer's
    directory is one pressing at one quality where a file each from twelve peers
    is twelve different rips. Per track searches then mop up the gaps.

    Returns True if soulseek was actually consulted. An unreachable daemon
    returns False, which leaves the release recorded as never having been
    offered to soulseek, so a later session still tries it.
    """
    pending = pending_tracks(ctx)
    if not pending:
        return False

    client = slsk_connect()
    if client is None:
        note_refusal(failure("slsk_offline", "slskd is not available",
                             SOURCE_SOULSEEK))
        return False

    min_bitrate = arg_int("-slsk-min-bitrate", 0) or 0
    found = []
    seen = set()
    assignments = {}
    dirname = None
    for query in soulseek_queries(ctx):
        for candidate in soulseek_search(ctx, client, query, min_bitrate):
            # the same file answers more than one of our queries. counted twice
            # it looks like two copies, and the matcher will happily give one
            # track each
            key = (candidate["username"], candidate["filename"])
            if key in seen:
                continue
            seen.add(key)
            found.append(candidate)
        assignments, dirname = best_soulseek_folder(ctx, found, pending)
        # a folder covering everything missing is worth stopping the search for
        if len(assignments) >= len(pending):
            break

    if dirname:
        ctx["entry"]["slsk_folder"] = dirname

    taken = {(m["candidate"]["username"], m["candidate"]["filename"])
             for m in assignments.values()}
    gaps = [index for index in pending if index not in assignments]
    for index in gaps[:TRACK_SEARCH_LIMIT]:
        match = soulseek_track_search(ctx, client, index, min_bitrate, taken)
        if match:
            assignments[index] = match
            taken.add((match["candidate"]["username"],
                       match["candidate"]["filename"]))

    # a dry run says it all in the plan, which names the tracks nothing was
    # found for, so it needs none of the recording below
    if ctx["dry_run"]:
        print_match_plan(ctx["tracks"], assignments, [], [], SOURCE_SOULSEEK)
        plan_tracks(ctx, assignments)
        return True

    # every track soulseek could not account for gets recorded with the reason,
    # not just left out of the entry: a later session, and the tally at the end
    # of this one, both want to know whether it was not shared or not matched
    unmatched = [index for index in pending if index not in assignments]
    if unmatched:
        empty = not found
        ctx["reasons"][SOURCE_SOULSEEK] = "no_results" if empty else "no_match"
        info = failure(
            "slsk_no_results" if empty else "slsk_no_match",
            "nobody is sharing this release" if empty
            else "nothing on soulseek matched this track",
            SOURCE_SOULSEEK)
        for index in unmatched:
            fail_track(ctx, index, "missing", info)

    if not assignments:
        return True

    return download_soulseek(ctx, client, assignments)


def download_soulseek(ctx, client, assignments):
    """
    Ask the peers for the matched files and wait for them to land.

    One request per peer rather than one per file: that is a single place in
    their queue instead of five, and it is how downloading a folder behaves in
    any other client.
    """
    downloads_dir = slsk_downloads_dir()

    by_peer = {}
    for index, match in assignments.items():
        by_peer.setdefault(match["candidate"]["username"], []).append(
            (index, match))

    # one entry per track rather than a mapping by filename: two tracks can
    # legitimately end up on the same file, and keying by name would drop one
    wanted = []
    for username, items in by_peer.items():
        files = [{"filename": m["candidate"]["filename"],
                  "size": m["candidate"]["size"]} for _index, m in items]
        keys = ", ".join(track_key(ctx, index) for index, _m in items)
        print(f"    [slsk] asking {username} for {len(files)} file(s): {keys}")
        ok, error = slsk.enqueue(client, username, files)
        if not ok:
            info = failure("slsk_no_peer",
                           f"{username} would not take the request",
                           SOURCE_SOULSEEK)
            for index, _match in items:
                fail_track(ctx, index, "missing", info, message=error)
            continue
        for index, match in items:
            wanted.append((match["candidate"]["filename"], index, match))

    if not wanted:
        return True

    states = slsk.wait_for(client, {name for name, _i, _m in wanted},
                           arg_float("-slsk-wait", 300.0), verbose=verbose())

    for filename, index, match in wanted:
        candidate = match["candidate"]
        track = ctx["tracks"][index]
        key = track_key(ctx, index)
        state = states.get(filename, "")

        track_entry = new_track_entry(ctx, index)
        track_entry.update({
            "candidate": candidate["title"],
            "match_score": match["score"],
            "peer": candidate["username"],
            "remote_file": filename,
            "format": candidate["format"],
        })
        if candidate.get("bitrate"):
            track_entry["bitrate"] = candidate["bitrate"]

        if slsk.failed(state):
            track_entry["status"] = "failed"
            track_entry["source"] = SOURCE_SOULSEEK
            track_entry["error"] = f"transfer {state}"
            track_entry["error_kind"] = "slsk_errored"
            record_track(ctx, index, track_entry)
            note_refusal(failure("slsk_errored", f"transfer {state}",
                                 SOURCE_SOULSEEK))
            print(f"    [fail] {key} {track['title']}: {state}")
            continue

        if not slsk.succeeded(state):
            # left enqueued in slskd deliberately: soulseek queues run to hours
            # and this may well finish while we get on with the collection, for
            # the next session to pick up off disk
            track_entry["status"] = "queued"
            track_entry["source"] = SOURCE_SOULSEEK
            track_entry["error"] = f"still {state} when the wait ran out"
            track_entry["error_kind"] = "slsk_queue_timeout"
            record_track(ctx, index, track_entry)
            note_refusal(failure("slsk_queue_timeout",
                                 f"still {state} when the wait ran out",
                                 SOURCE_SOULSEEK))
            print(f"    [wait] {key} {track['title']}: {state}, left queued")
            continue

        src = slsk.find_download(downloads_dir, filename, candidate["size"])
        if not src:
            fail_track(ctx, index, "failed",
                       failure("slsk_missing_file",
                               "finished transfer not found on disk",
                               SOURCE_SOULSEEK),
                       message=f"not found under {downloads_dir}")
            continue

        path, transcoded, error = place_file(
            src, os.path.join(ctx["release_dir"], track_stem(ctx, index)),
            ctx["quality"])
        track_entry["transcoded"] = transcoded
        if error:
            fail_track(ctx, index, "failed",
                       failure("slsk_encode_failed", error, SOURCE_SOULSEEK),
                       message=error)
            continue

        finish_track(ctx, index, path, SOURCE_SOULSEEK, candidate["url"],
                     track_entry)

    return True


# ----------------------------------------------------------------------------
# the media linked on the discogs release page
# ----------------------------------------------------------------------------

def rip_tracks_youtube(ctx):
    """
    Rip whatever is still missing from the media linked on the release page.

    Discogs users attach links to a release, so what is here varies from nothing
    at all to a full tracklist, and the quality varies just as much. It is the
    last source tried for that reason.

    Returns True if it was actually consulted. A session run with
    -source soulseek never reaches this function, which is the point of the flag:
    an address that has started getting refused sees no traffic at all.
    """
    global bot_check_seen, consecutive_blocks, session_blocked

    pending = pending_tracks(ctx)
    if not pending:
        return False

    entry = ctx["entry"]
    tracks = ctx["tracks"]
    quality = ctx["quality"]

    videos = drop_rejected(ctx, build_video_records(ctx["release"]))
    if not videos:
        ctx["reasons"][SOURCE_YOUTUBE] = "no_videos"
        info = failure("yt_no_videos", "no videos on the discogs page",
                       SOURCE_YOUTUBE)
        for index in pending:
            fail_track(ctx, index, "missing", info)
        return True

    assignments, whole_release, unmatched = match_videos_to_tracks(
        tracks, videos, ctx["artists"], ctx["label"], ctx["catno"],
        ctx["artist"])

    if whole_release:
        entry["album_videos"] = [
            {"title": v["title"], "url": v["url"], "duration": v["duration"]}
            for v in whole_release
        ]
    if unmatched:
        entry["unmatched_videos"] = [
            {"title": v["title"], "url": v["url"]} for v in unmatched
        ]

    if not assignments:
        ctx["reasons"][SOURCE_YOUTUBE] = "no_match"
        info = failure("yt_no_match", "no video matched this track",
                       SOURCE_YOUTUBE)
        for index in pending:
            fail_track(ctx, index, "missing", info)
        return True

    if ctx["dry_run"]:
        print_match_plan(tracks, assignments, whole_release, unmatched,
                         SOURCE_YOUTUBE)
        plan_tracks(ctx, assignments)
        return True

    for index in pending:
        track = tracks[index]
        key = track_key(ctx, index)
        match = assignments.get(index)

        if not match:
            fail_track(ctx, index, "missing",
                       failure("yt_no_match", "no video matched this track",
                               SOURCE_YOUTUBE))
            continue

        video = match["candidate"]
        track_entry = new_track_entry(ctx, index)
        track_entry["video"] = video["url"]
        track_entry["video_title"] = video["title"]
        track_entry["match_score"] = match["score"]

        out_stem = os.path.join(ctx["release_dir"], track_stem(ctx, index))

        print(f"    [ .. ] {key} {track['title']}")
        path, error, info = download_audio(video["url"], out_stem, quality)

        if error:
            info = info or {"kind": "error", "label": error, "blocked": False}
            info["source"] = SOURCE_YOUTUBE
            track_entry["source"] = SOURCE_YOUTUBE
            track_entry["error"] = error
            track_entry["error_kind"] = info.get("kind", "error")
            if info.get("http_status"):
                track_entry["http_status"] = info["http_status"]
            record_track(ctx, index, track_entry)
            note_refusal(info)

            if info.get("blocked"):
                bot_check_seen = True
                consecutive_blocks += 1
                track_entry["status"] = "blocked"
                print(f"    [block] {key} {track['title']}: "
                      f"{info.get('label', 'refused')}, gave up after "
                      f"{info.get('attempts', 1)} attempts")
                # once the address is properly rate limited nothing else will
                # download either. stop instead of marching through the rest of
                # the collection turning every release into a false failure
                if consecutive_blocks >= arg_int("-block-limit", 3):
                    session_blocked = True
                    print(f"    [block] {consecutive_blocks} blocked in a row, "
                          f"stopping the session")
                    break
            else:
                consecutive_blocks = 0
                track_entry["status"] = "failed"
                print(f"    [fail] {key} {track['title']}: "
                      f"{info.get('label', error)}")
            continue

        if finish_track(ctx, index, path, SOURCE_YOUTUBE, video["url"],
                        track_entry):
            consecutive_blocks = 0

        crawl_pause("before next track")

    return True


# ----------------------------------------------------------------------------
# ripping one release from whichever sources the session allows
# ----------------------------------------------------------------------------

def make_context(release, root, token, previous=None):
    """
    Everything a source needs to rip a release, or None if there is no point.

    Shared by every source and by the local import, so the release directory
    name, the tags, the ledger entry and the already on disk check are decided
    in one place regardless of where the audio comes from. Returns (ctx, entry):
    ctx is None when the release has no tracklist to work against.
    """
    data = release.data or {}
    artist = release_artist_string(release)
    title = normalize_unicode(release.title or "")
    label, catno = release_label_and_catno(release)
    artists = release_artists(release)
    if not artists:
        artists = [artist]

    entry = {
        "id": release.id,
        "artist": artist,
        "title": title,
        "label": label,
        "catno": catno,
        "url": data.get("uri", ""),
        "year": data.get("year"),
        "tracks": {},
        "sources_tried": [],
        # everything this release has ever been told not to take again, carried
        # forward so a rejection outlives the run that made it
        "rejected": list((previous or {}).get("rejected") or []),
    }

    tracks = build_track_records(release, artist)
    if not tracks:
        entry["status"] = STATUS_FAILED
        entry["error"] = "release has no tracklist"
        return None, entry

    dir_name = release_dir_name(artist, title, catno)
    entry["dir"] = dir_name
    dry_run = "-dry-run" in sys.argv

    ctx = {
        "release": release,
        "data": data,
        "entry": entry,
        "previous": previous,
        "root": root,
        "tracks": tracks,
        "artist": artist,
        "title": title,
        "artists": artists,
        "label": label,
        "catno": catno,
        "release_dir": os.path.join(root, dir_name),
        "quality": arg_value("-quality", "320"),
        "force": "-force" in sys.argv,
        "dry_run": dry_run,
        "cover": (None, None),
        "done": {},
        "reasons": {},
    }

    # flags first: a file that has been rejected must be gone before the disk
    # check runs, or it is adopted straight back as though nothing happened
    if not dry_run:
        apply_flags(ctx)
    collect_existing(ctx)

    if not dry_run and pending_tracks(ctx):
        os.makedirs(ctx["release_dir"], exist_ok=True)
        # the artwork is the same for every track and costs a request, so once
        if "-no-cover" not in sys.argv:
            ctx["cover"] = fetch_cover(release, token)

    return ctx, entry


def rip_release(release, root, token, previous=None):
    """
    Rip one discogs release. Returns the ledger entry for it.

    Each source in turn is given whatever is still missing, and the entry
    records which of them were really consulted, so a session run later with a
    different -source knows there is work left to do here.
    """
    ctx, entry = make_context(release, root, token, previous)
    if ctx is None:
        return entry

    for source in requested_sources():
        if session_blocked or not pending_tracks(ctx):
            break
        if source == SOURCE_SOULSEEK:
            attempted = rip_tracks_soulseek(ctx)
        else:
            attempted = rip_tracks_youtube(ctx)
        if attempted:
            entry["sources_tried"].append(source)

    return finish_release(ctx)


def finish_release(ctx):
    """Where the release ended up once every source has had its go."""
    entry = ctx["entry"]
    done = ctx["done"]

    entry["total"] = len(ctx["tracks"])
    entry["ripped"] = len(done)
    entry["missing"] = [track_key(ctx, index) for index in pending_tracks(ctx)]
    if ctx["dry_run"]:
        entry["dry_run"] = True

    queued = [key for key, track in entry["tracks"].items()
              if track.get("status") == "queued"]
    if queued:
        entry["queued"] = queued

    if len(done) == len(ctx["tracks"]):
        entry["status"] = STATUS_COMPLETE
    elif queued:
        # sitting in someone's upload queue is not a failure, it is unfinished
        entry["status"] = STATUS_QUEUED
    elif done:
        entry["status"] = STATUS_PARTIAL
    elif (entry["sources_tried"] == [SOURCE_YOUTUBE]
          and ctx["reasons"].get(SOURCE_YOUTUBE) == "no_videos"):
        # that source alone, and the release page links nothing to work with
        entry["status"] = STATUS_NO_VIDEOS
    else:
        entry["status"] = STATUS_NO_MATCH
    return entry


# ----------------------------------------------------------------------------
# collection walk
# ----------------------------------------------------------------------------

def collection_date_added(item):
    """
    When a release was added to the collection.

    Read it from the raw response rather than the model attribute. The
    maintained python3-discogs-client exposes a date_added field but the older
    discogs-client package does not, and the json carries it either way.
    """
    data = getattr(item, "data", None) or {}
    added = data.get("date_added")
    if added:
        return str(added)
    added = getattr(item, "date_added", None)
    return str(added) if added else None


def pick_folder(user, wanted):
    """Resolve -folder to a collection folder. Defaults to 'All' (id 0)."""
    folders = discogs_call("collection folders",
                           lambda: list(user.collection_folders))
    if not folders:
        print("error: no collection folders found for this user")
        return None

    if wanted is None:
        for folder in folders:
            if folder.id == 0:
                return folder
        return folders[0]

    if str(wanted).isdigit():
        for folder in folders:
            if folder.id == int(wanted):
                return folder

    for folder in folders:
        if folder.name.lower() == str(wanted).lower():
            return folder

    print(f"error: no collection folder matching '{wanted}'")
    print("available folders:")
    for folder in folders:
        print(f"    {folder.id}: {folder.name} ({folder.count})")
    return None


def check_mutagen():
    try:
        import mutagen  # noqa: F401
        return True
    except ImportError:
        print("error: mutagen is required for id3 tagging")
        print("       pip install mutagen  (or re-run scrape/setup.sh)")
        return False


def report_refusals():
    """
    Why downloads failed this session, by kind, with the advice for each.

    Worth repeating at the end: the inline hints have long scrolled away by
    the time a collection sized run finishes, and which kind dominates is
    what decides whether the fix is cookies, a yt-dlp update, or just waiting.
    """
    if not refusal_counts:
        return

    total = sum(refusal_counts.values())
    print(f"\n{total} downloads did not happen, by reason:")
    for kind in sorted(refusal_counts, key=lambda k: -refusal_counts[k]):
        print(f"    {refusal_counts[kind]:4}  {kind}")

    hints = failure_hints()
    for kind in sorted(refusal_counts, key=lambda k: -refusal_counts[k]):
        if hints.get(kind):
            print(f"\n  {kind}: {hints[kind]}")


def report_sources(ledger, sources):
    """
    What each source landed this session, and what the others have left.

    The first number is the point of restricting a pass to one source: how much
    of the collection that source can cover on its own. The second sizes the
    session that has to follow it.
    """
    if source_counts:
        print("\ntracks by source this session:")
        for source in sorted(source_counts, key=lambda s: -source_counts[s]):
            print(f"    {source_counts[source]:4}  {source_label(source)}")

    waiting = {}
    for entry in ledger["releases"].values():
        if entry.get("status") == STATUS_COMPLETE:
            continue
        for source in untried_sources(entry, list(SOURCE_ORDER)):
            waiting[source] = waiting.get(source, 0) + 1

    for source in SOURCE_ORDER:
        if not waiting.get(source):
            continue
        if source in sources:
            # in this session's source list but still untried, so the session
            # stopped early or the source was unavailable
            continue
        print(f"\n{waiting[source]} unfinished releases have never been tried "
              f"on {source}.")
        print(f"run the same command with -source {source} to work through "
              f"them, no -retry needed.")


def report_outstanding(ledger, sources):
    """List everything still needing attention across all sessions."""
    partial = []
    no_videos = []
    failed = []
    queued = []

    for entry in ledger["releases"].values():
        status = entry.get("status")
        name = f"{entry.get('artist', '?')} - {entry.get('title', '?')}"
        if status == STATUS_PARTIAL:
            partial.append((name, entry))
        elif status == STATUS_QUEUED:
            queued.append((name, entry))
        elif status == STATUS_NO_VIDEOS:
            no_videos.append((name, entry))
        elif status in (STATUS_FAILED, STATUS_NO_MATCH):
            failed.append((name, entry))

    if queued:
        print(f"\n{len(queued)} releases waiting in a soulseek queue:")
        for name, entry in queued[:20]:
            print(f"    {name}: {', '.join(entry.get('queued', []))}")
        if len(queued) > 20:
            print(f"    ... and {len(queued) - 20} more")
        print("these are still enqueued in slskd and may finish on their own,")
        print("a later -retry picks the finished files up off disk.")

    if partial:
        print(f"\n{len(partial)} partial releases (missing tracks):")
        for name, entry in partial[:20]:
            print(f"    {name}: missing {', '.join(entry.get('missing', []))}")
        if len(partial) > 20:
            print(f"    ... and {len(partial) - 20} more")

    if no_videos:
        print(f"\n{len(no_videos)} releases with no videos on discogs")
        if verbose():
            for name, entry in no_videos:
                print(f"    {name}")

    if failed:
        print(f"\n{len(failed)} releases failed or had nothing that matched")
        if verbose():
            for name, entry in failed:
                print(f"    {name}: {entry.get('error', entry.get('status'))}")

    report_refusals()
    report_sources(ledger, sources)

    if session_blocked:
        print("\nstopped early: this address is no longer being served.")
        print("nothing was lost, the ledger holds everything done so far.")
        print("wait a while, then re-run the same command with -retry to")
        print("pick up where it left off. -slow crawls harder if it recurs.")
        print("or leave it for now and run -source soulseek, which makes no")
        print("requests of this source at all.")
    elif bot_check_seen:
        print("\nat least one download was refused but the run recovered.")

    if discogs_rate_limited:
        print("\ndiscogs rate limited this session and the run waited it out.")
        print("raise -api-sleep above the default 1.2s if it keeps happening.")

    if partial or failed:
        print("\nre-run with -retry to attempt these again")


# ----------------------------------------------------------------------------
# importing rips you made yourself
# ----------------------------------------------------------------------------

def normalize_catno(text):
    """
    A catalogue number reduced to what is worth comparing.

    Everyone writes them differently: discogs has "SUB 001", the folder on the
    stick says "sub-001", the label's sleeve says "SUB001". Case, spaces and
    punctuation carry no information here, so they go.
    """
    return re.sub(r"[^a-z0-9]", "", (text or "").lower())


def basic_catnos(item):
    """Every catalogue number on a collection item, normalised."""
    data = getattr(item, "data", None) or {}
    found = []
    for label in data.get("labels") or []:
        catno = normalize_catno(label.get("catno"))
        if catno and catno not in found:
            found.append(catno)
    return found


def collection_catnos(discogs):
    """
    Map catalogue number to the releases in the collection carrying it.

    Built from basic_information, which every collection page already contains,
    so reading a whole collection costs one request per fifty releases rather
    than one per release. The full release is only fetched later, for the
    folders that actually matched something.

    Deduplicated by release id. A collection holds one entry per copy owned, so
    two copies of the same record are two entries carrying the same release, and
    for ripping purposes that is one release: the tracklist, the timings and the
    metadata are identical, there is nothing to choose between them. Only genuine
    ambiguity, two different releases sharing a catalogue number, is worth
    reporting, and merging the copies here is what keeps that report meaningful.
    """
    user = discogs_call("identity", discogs.identity)
    folder = pick_folder(user, arg_value("-folder"))
    if folder is None:
        return None

    print(f"reading catalogue numbers from '{folder.name}' "
          f"({folder.count} releases)")

    catnos = {}
    count = 0
    copies = 0
    for item in iter_releases(folder.releases):
        basic = item.release
        count += 1
        record = {
            "id": basic.id,
            "artist": strip_discogs_suffix(
                ((getattr(basic, "data", None) or {}).get("artists") or [{}])[0]
                .get("name", "")),
            "title": normalize_unicode(basic.title or ""),
            "date_added": collection_date_added(item),
            "copies": 1,
        }
        for catno in basic_catnos(basic):
            known = catnos.setdefault(catno, [])
            existing = next((r for r in known if r["id"] == record["id"]), None)
            if existing:
                # another copy of one we already have. count it and move on,
                # keeping the earliest date added of the two
                existing["copies"] += 1
                copies += 1
                if (record["date_added"] and
                        (not existing["date_added"]
                         or record["date_added"] < existing["date_added"])):
                    existing["date_added"] = record["date_added"]
                continue
            known.append(record)

    unique = len({r["id"] for records in catnos.values() for r in records})
    print(f"read {count} collection entries, {unique} distinct releases, "
          f"{len(catnos)} distinct catalogue numbers")
    if copies:
        print(f"{copies} entries were extra copies of a release already seen, "
              f"counted once")
    return catnos


def match_source_folder(name, catnos):
    """
    Find the release a folder on the stick belongs to.

    The folder name is the catalogue number, so an exact match on the whole name
    is the normal case. Failing that it is tried as a leading token, for a folder
    named "SUB001 - Artist - Title", and then as anything contained in the name,
    which is the last thing worth trying before giving up and saying so.
    """
    whole = normalize_catno(name)
    if not whole:
        return None, None

    if whole in catnos:
        return catnos[whole], "exact"

    # "SUB001 - Artist - Title" and friends, on the usual separators
    lead = normalize_catno(re.split(r"[-–—_(\[]", name)[0])
    if lead and lead in catnos:
        return catnos[lead], "prefix"

    # a catalogue number sitting somewhere inside the name. longest first, so
    # "SUB0012" is preferred over "SUB001" when both are in the collection
    contained = [catno for catno in catnos
                 if len(catno) >= 4 and catno in whole]
    if contained:
        contained.sort(key=len, reverse=True)
        return catnos[contained[0]], "contained"

    return None, None


def audio_length(path):
    """Length in seconds of any audio file mutagen can read, else None."""
    try:
        import mutagen
        media = mutagen.File(path)
        if media is None or not getattr(media, "info", None):
            return None
        return int(media.info.length)
    except Exception:
        return None


# Directories an operating system leaves on a stick, never ours to read
JUNK_DIRS = {"__macosx", ".trashes", ".spotlight-v100", ".fseventsd",
             ".temporaryitems", "system volume information", "$recycle.bin",
             ".documentrevisions-v100"}

# The smallest a real track could possibly be, as a sanity floor. An
# AppleDouble sidecar is a few kilobytes, a real 30 second cut is hundreds
JUNK_SIZE = 4096


def is_junk_file(name):
    """
    Whether a filename is an operating system artefact rather than music.

    The one that matters is the AppleDouble sidecar: copy a folder from a mac to
    a stick and every "A1 Track.m4a" gains a "._A1 Track.m4a" holding the
    resource fork. It carries the audio extension and none of the audio, so
    ffmpeg says "moov atom not found", and because "._" sorts before a letter it
    reaches the matcher first and wins the track off the real file. Both losses
    at once, which is why this is filtered on the way in rather than handled as
    a conversion failure later.
    """
    lower = name.lower()
    if name.startswith("._"):
        return True
    if lower in (".ds_store", "thumbs.db", "desktop.ini", ".localized"):
        return True
    # a leading dot is a hidden file on every system that has the convention,
    # and nobody names a track that on purpose
    return name.startswith(".")


def source_audio_files(directory):
    """Audio files in a directory, deepest last, in name order."""
    found = []
    for root, dirs, names in os.walk(directory):
        # prune in place so os.walk does not descend into them at all
        dirs[:] = [d for d in dirs if d.lower() not in JUNK_DIRS]
        for name in sorted(names):
            if os.path.splitext(name)[1].lower() not in slsk.AUDIO_EXT:
                continue
            if is_junk_file(name):
                continue
            path = os.path.join(root, name)
            try:
                if os.path.getsize(path) < JUNK_SIZE:
                    continue
            except OSError:
                continue
            found.append(path)
    return found


def local_candidates(paths):
    """
    Local files in the shape the matcher wants.

    The strongest candidates of any source, because the duration is measured off
    the file rather than taken on trust: the position marker in the filename and
    a length that agrees with the tracklist together leave very little room to
    match the wrong thing. It also means a rip that is really a partial take is
    caught by the same length check as anything else, before it is imported
    rather than after.

    A file nothing can read the length of is dropped here rather than carried as
    far as the converter. Every format accepted is one mutagen knows, so failing
    to read one means it is not the audio file its extension claims, and matching
    a track to it only loses that track twice over: once when the conversion
    fails and again because the file that would have worked went unused.
    """
    candidates = []
    for path in paths:
        duration = audio_length(path)
        if duration is None:
            print(f"    [warn] skipping {os.path.basename(path)}: "
                  f"not readable as audio")
            continue
        candidates.append({
            "title": os.path.splitext(os.path.basename(path))[0],
            "duration": duration,
            "url": "file:///" + path.replace("\\", "/"),
            "path": path,
            "format": os.path.splitext(path)[1].lower(),
        })
    return candidates


def import_file(src, out_stem, quality):
    """
    Put a file from elsewhere into the release directory as <out_stem>.mp3.

    Copies rather than moves. The source is the user's own rip on their own
    stick and this has no business consuming it. An mp3 is copied as it is,
    since re-encoding one only loses quality, and anything else is converted.
    Returns (path, converted, error).
    """
    target = out_stem + ".mp3"
    if os.path.splitext(src)[1].lower() == ".mp3":
        try:
            shutil.copyfile(src, target)
        except OSError as e:
            return None, False, f"could not copy file: {e}"
        return target, False, None

    ok, error = to_mp3(src, target, quality)
    if not ok:
        return None, True, error
    return target, True, None


def import_tracks_local(ctx, paths):
    """
    Match the files in one folder to the tracklist and bring them in.

    Uses the same matcher as every other source, so a folder of files named
    however the ripper happened to name them is lined up against the discogs
    tracklist the same way a peer's folder or a page of links is.
    """
    pending = pending_tracks(ctx)
    if not pending:
        return False

    candidates = drop_rejected(ctx, local_candidates(paths))
    if not candidates:
        info = failure("local_no_audio", "no audio files in the folder",
                       SOURCE_LOCAL)
        for index in pending:
            fail_track(ctx, index, "missing", info)
        return True

    assignments, whole_release, unmatched = match_videos_to_tracks(
        ctx["tracks"], candidates, ctx["artists"], ctx["label"], ctx["catno"],
        ctx["artist"])
    assignments = {i: m for i, m in assignments.items() if i in pending}

    if ctx["dry_run"]:
        print_match_plan(ctx["tracks"], assignments, whole_release, unmatched,
                         SOURCE_LOCAL)
        plan_tracks(ctx, assignments)
        return True

    if unmatched:
        # worth naming: a file on the stick that went nowhere is either a track
        # discogs lists differently or something that does not belong here
        ctx["entry"]["unused_files"] = [
            os.path.basename(candidate["path"]) for candidate in unmatched
        ]

    for index in pending:
        track = ctx["tracks"][index]
        key = track_key(ctx, index)
        match = assignments.get(index)

        if not match:
            fail_track(ctx, index, "missing",
                       failure("local_no_match",
                               "no file in the folder matched this track",
                               SOURCE_LOCAL))
            continue

        candidate = match["candidate"]
        track_entry = new_track_entry(ctx, index)
        track_entry.update({
            "candidate": candidate["title"],
            "match_score": match["score"],
            "local_file": candidate["path"],
            "format": candidate["format"],
        })

        print(f"    [ .. ] {key} {track['title']} <- "
              f"{os.path.basename(candidate['path'])}")
        path, converted, error = import_file(
            candidate["path"],
            os.path.join(ctx["release_dir"], track_stem(ctx, index)),
            ctx["quality"])
        track_entry["converted"] = converted
        if error:
            fail_track(ctx, index, "failed",
                       failure("local_convert_failed", error, SOURCE_LOCAL),
                       message=error)
            continue

        finish_track(ctx, index, path, SOURCE_LOCAL, candidate["url"],
                     track_entry)

    return True


def import_release(release, root, token, paths, previous=None):
    """Bring one folder of local files in against its discogs release."""
    ctx, entry = make_context(release, root, token, previous)
    if ctx is None:
        return entry
    if import_tracks_local(ctx, paths):
        entry["sources_tried"].append(SOURCE_LOCAL)
    return finish_release(ctx)


def import_local(discogs, root, source_dir, token, ledger):
    """
    Import rips made elsewhere, matching each folder to the collection by catno.

    The walk is the other way round from a normal session. Ripping asks what the
    collection needs and goes looking for it; an import has the files already
    and asks which release each folder is, so the collection is read once for
    its catalogue numbers and the folders are matched against that.

    Everything else is the same as any other source: the same matcher decides
    which file is which track, the same conversion and the same tags, so an
    imported record is indistinguishable from a ripped one.
    """
    source_dir = os.path.abspath(os.path.expanduser(source_dir))
    if not os.path.isdir(source_dir):
        print(f"error: -input '{source_dir}' is not a directory")
        return

    folders = []
    for name in sorted(os.listdir(source_dir)):
        path = os.path.join(source_dir, name)
        if os.path.isdir(path) and source_audio_files(path):
            folders.append((name, path))
    # pointed straight at one release rather than at a folder of folders
    if not folders and source_audio_files(source_dir):
        folders = [(os.path.basename(source_dir), source_dir)]

    if not folders:
        print(f"no folders with audio in {source_dir}")
        return

    print(f"importing from {source_dir}")
    print(f"{len(folders)} folders with audio")

    catnos = collection_catnos(discogs)
    if catnos is None:
        return

    dry_run = "-dry-run" in sys.argv
    count_limit = arg_int("-count")
    # -release pins the import to one release, which is how a catalogue number
    # shared by an original and a reissue gets settled
    wanted_id = arg_int("-release")
    if wanted_id:
        print(f"only importing folders belonging to release {wanted_id}")
    unmatched_folders = []
    ambiguous = []
    processed = 0
    stats = {}

    try:
        for number, (name, path) in enumerate(folders, start=1):
            if count_limit is not None and processed >= count_limit:
                print(f"\nreached -count {count_limit}, stopping")
                break

            releases, how = match_source_folder(name, catnos)
            if not releases:
                unmatched_folders.append(name)
                continue

            if wanted_id:
                # asked for one release, so every other folder is not our
                # business this run, and is not an unmatched folder either
                releases = [r for r in releases if r["id"] == wanted_id]
                if not releases:
                    continue
            # more than one release under this catalogue number, and they really
            # are different records: an original and a reissue, or a label that
            # reused a number. the first is taken and it is said out loud
            elif len(releases) > 1:
                ambiguous.append((name, releases))
            record = releases[0]

            key = str(record["id"])
            previous = ledger["releases"].get(key)
            copies = ""
            if record.get("copies", 1) > 1:
                copies = f", {record['copies']} copies owned"
            if (previous and previous.get("status") == STATUS_COMPLETE
                    and not flagged_keys(previous)[0]
                    and "-force" not in sys.argv):
                print(f"\n[{number}/{len(folders)}] {name} -> "
                      f"{record['artist']} - {record['title']}: "
                      f"already complete, skipping")
                continue

            print(f"\n[{number}/{len(folders)}] {name} -> {record['artist']} - "
                  f"{record['title']} ({record['id']}, matched {how}{copies})")

            try:
                time.sleep(arg_float("-api-sleep", API_SLEEP))
                release = discogs_call(
                    f"release {record['id']}",
                    lambda: fetch_release(discogs, record["id"]))
            except Exception as e:
                print(f"    failed to fetch release {record['id']}: {e}")
                continue

            files = source_audio_files(path)
            try:
                entry = import_release(release, root, token, files, previous)
            except KeyboardInterrupt:
                raise
            except Exception as e:
                print(f"    failed: {type(e).__name__}: {e}")
                if verbose():
                    import traceback
                    traceback.print_exc()
                continue

            entry["source_dir"] = path
            entry["sources_tried"] = merge_tried(previous, entry)
            entry["attempts"] = (previous or {}).get("attempts", 0) + 1
            if record.get("date_added"):
                entry["date_added"] = record["date_added"]
            entry["ripped_at"] = datetime.datetime.now().isoformat(
                timespec="seconds")

            ledger["releases"][key] = entry
            if not dry_run:
                save_ledger(root, ledger)

            status = entry["status"]
            stats[status] = stats.get(status, 0) + 1
            processed += 1
            print(f"    -> {status_label(status)}: {entry.get('ripped', 0)}/"
                  f"{entry.get('total', 0)} tracks"
                  + (f", missing {', '.join(entry.get('missing', []))}"
                     if entry.get("missing") else ""))

    except KeyboardInterrupt:
        print("\ninterrupted")

    if not dry_run:
        save_ledger(root, ledger)

    print("\nimport summary")
    print(f"    folders: {len(folders)}")
    print(f"    imported: {processed}")
    for status in sorted(stats):
        print(f"    {status_label(status)}: {stats[status]}")

    if ambiguous:
        print(f"\n{len(ambiguous)} folders whose catalogue number belongs to "
              f"more than one release in the collection.")
        print("these are different records sharing a number, an original and a "
              "reissue usually.")
        print("the first was used. if it was the wrong one, re-import naming "
              "the right release:")
        print("    -input <dir> -release <id> -force")
        for name, releases in ambiguous:
            print(f"    {name}")
            for candidate in releases[:4]:
                print(f"        {candidate['id']}  {candidate['artist']} - "
                      f"{candidate['title']}")

    if unmatched_folders:
        print(f"\n{len(unmatched_folders)} folders matched nothing in the "
              f"collection:")
        for name in unmatched_folders:
            print(f"    {name}")
        print("either the record is not in your discogs collection, or the")
        print("folder is not named after its catalogue number. adding it to")
        print("the collection and re-running is the easy fix.")

    report_outstanding(ledger, requested_sources())


# ----------------------------------------------------------------------------
# where the library stands
# ----------------------------------------------------------------------------

def transient_kinds():
    """
    Failure kinds that say nothing about whether the audio exists.

    A rate limit, an upload queue, a peer dropping out or a converter falling
    over are all our problem and another run may well fix them. They must not be
    counted alongside "nobody has this", because the answer to one is to run it
    again and the answer to the other is to rip the record yourself.

    The link kinds come from LINK_ERRORS' own retry flag rather than a second
    list that could drift away from it.
    """
    kinds = {kind for kind, retry, _p, _l, _h in LINK_ERRORS if retry}
    kinds |= {"slsk_offline", "slsk_queue_timeout", "slsk_errored",
              "slsk_missing_file", "slsk_encode_failed", "no_formats",
              "local_convert_failed", "bad_file"}
    return kinds


POSITION_SIDE_RE = re.compile(r"^\s*([A-Za-z]+)\s*(\d*)\s*$")


def side_openers(keys):
    """
    The first track of each side, which is mostly what a record is bought for.

    On a twelve inch the later positions are where the tools, the locked grooves,
    the acapellas and the DJ edits live, and those are exactly the ones nobody
    uploads. Missing A2 or B3 usually leaves a record that is still worth having.
    Missing A1 does not, and a count that treats the two the same tells you
    nothing about which of your partial releases actually need attention.

    Positions with no side letter, a cd or digital tracklist, have no sides to
    open, so the first track stands in as the nearest equivalent.
    """
    sides = {}
    plain = []
    for key in keys:
        match = POSITION_SIDE_RE.match(str(key))
        if match:
            side, number = match.group(1).upper(), match.group(2)
            # a side with a single track is written "A", which is its own opener
            order = int(number) if number else 0
            if side not in sides or order < sides[side][0]:
                sides[side] = (order, key)
            continue
        digits = re.sub(r"[^0-9]", "", str(key))
        if digits:
            plain.append((int(digits), key))

    if sides:
        return {key for _order, key in sides.values()}
    if plain:
        return {min(plain)[1]}
    return set()


# how a record names the things nobody goes looking for
MINOR_TITLE_RE = re.compile(
    r"lock(ed)?\s*groove|\btool\b|\btools\b|\bacap+ella\b|\ba\s*cappella\b|"
    r"\bintro\b|\boutro\b|\binterlude\b|\bskit\b|\breprise\b|\bbonus\s*beats\b|"
    r"\bdrum\s*track\b|\bloop\b|\bbeats\s*only\b",
    re.IGNORECASE,
)


def track_seconds(track):
    """What we know of a track's length, from discogs or from the file."""
    for field in ("expected_length", "length"):
        value = (track or {}).get(field)
        if value:
            return value
    return None


def key_tracks(entry):
    """
    The tracks a release is really bought for, worked out from the release.

    Every side opener counts, whatever the sides turn out to be: a twelve inch
    gives A1 and B1, a double gives four, a one sided gives one. Beyond those,
    a track counts unless the record itself says otherwise, which it does in two
    ways. It runs short against the rest of this release, or it is named the way
    tools, locked grooves and acapellas are named. Those are the cuts nobody
    uploads and nobody misses, and counting a release as broken for want of one
    buries the releases that are genuinely missing their main track.

    Judged per release rather than against a fixed length, because what counts
    as short on an ambient twelve is a whole track on a hardcore one.
    """
    tracks = entry.get("tracks") or {}
    if not tracks:
        return set()

    known = sorted(s for s in (track_seconds(t) for t in tracks.values()) if s)
    typical = known[len(known) // 2] if known else None

    minor = set()
    for position, track in tracks.items():
        title = str((track or {}).get("title") or "")
        seconds = track_seconds(track)
        # named like a tool, or short against everything else on this record
        if MINOR_TITLE_RE.search(title):
            minor.add(position)
        elif typical and seconds and seconds < typical * 0.5:
            minor.add(position)

    # a filler cut can be a side opener too: a twelve with one track a side and
    # a locked groove on the flip opens side B with the groove. what the record
    # says about the track beats where the track sits
    keys = {position for position in tracks if position not in minor}

    # unless that leaves nothing, which means the reasoning does not apply to
    # this record, and the side openers are the best guess available
    if not keys:
        keys = side_openers(tracks.keys())
    return keys


def missing_key_tracks(entry):
    """
    Which of a release's key tracks are still missing, if it can be told.

    Returns None where the ledger entry carries no per track detail, so the
    caller can say "cannot tell" rather than claiming nothing is missing.
    """
    tracks = entry.get("tracks") or {}
    if not tracks:
        return None
    keys = key_tracks(entry)
    if not keys:
        return None
    return sorted(key for key in keys
                  if (tracks.get(key) or {}).get("status") != "ok")


def outstanding_tracks(ledger):
    """
    Every track still without a file, split by what would fix it.

    Returns (exhausted, retryable) lists of (entry, key, track). Exhausted means
    every source has been offered this release and the reason it came back empty
    was availability rather than a rate limit or a queue: those are the ones only
    a copy of the record itself will fix.
    """
    transient = transient_kinds()
    exhausted = []
    retryable = []

    for entry in ledger["releases"].values():
        if entry.get("status") == STATUS_COMPLETE:
            continue

        tracks = entry.get("tracks") or {}
        missing = entry.get("missing") or []
        # a release that never got as far as a tracklist has nothing to list
        if not tracks and not missing:
            continue

        # every source has had its go at this release
        searched = not untried_sources(entry, list(SOURCE_ORDER))

        for key in missing or [k for k, t in tracks.items()
                               if t.get("status") != "ok"]:
            track = tracks.get(key) or {"title": "?"}
            if track.get("status") == "ok":
                continue
            kind = track.get("error_kind", "")
            if searched and kind not in transient:
                exhausted.append((entry, key, track))
            else:
                retryable.append((entry, key, track))

    return exhausted, retryable


def count_collection(discogs):
    """
    How many distinct releases the collection holds, and how many entries.

    The two are not the same and only one of them can be compared with the
    ledger. A collection has an entry per copy owned, so owning a record twice
    is two entries and one release, while the ledger is keyed by release id and
    collapses them. Counting entries and calling it releases makes a library
    that is finished look three short.

    Costs a page per fifty entries, which is why the answer gets remembered.
    """
    user = discogs_call("identity", discogs.identity)
    folder = pick_folder(user, arg_value("-folder"))
    if folder is None:
        return None

    seen = set()
    entries = 0
    for item in iter_releases(folder.releases):
        entries += 1
        seen.add(item.release.id)

    return {
        "folder": folder.name,
        "entries": entries,
        "releases": len(seen),
        "copies": entries - len(seen),
        "read_at": datetime.datetime.now().isoformat(timespec="seconds"),
    }


def collection_size(discogs, ledger):
    """
    The collection counts to measure the ledger against, read or remembered.

    Remembered by default, because walking the collection is the expensive part
    of an otherwise instant report and it only changes when records are added.
    -refresh reads it again.
    """
    stored = ledger.get("collection")
    if stored and "-refresh" not in sys.argv:
        return stored, False

    if discogs is not None:
        try:
            counts = count_collection(discogs)
            if counts:
                ledger["collection"] = counts
                return counts, True
        except Exception as e:
            print(f"note: could not read the collection: {e}")

    return stored, False


def status_report(root, ledger, discogs=None):
    """
    What the library holds and what it is still missing, near enough off the
    ledger alone.

    The only thing fetched is the size of the collection, so the ledger has
    something to be counted against, and that is remembered for the times it
    cannot be. No files are read: this answers "where am I" in a second, where
    -audit re-measures every file. Whether those files are still on disk is a
    question for -audit, not for this.
    """
    releases = ledger["releases"].values()
    statuses = {}
    total_tracks = 0
    ripped_tracks = 0
    by_source = {}

    for entry in releases:
        statuses[entry.get("status", "?")] = statuses.get(
            entry.get("status", "?"), 0) + 1
        total_tracks += entry.get("total") or 0
        for track in (entry.get("tracks") or {}).values():
            if track.get("status") == "ok":
                ripped_tracks += 1
                label = source_label(track.get("source"))
                by_source[label] = by_source.get(label, 0) + 1

    print(f"\nlibrary status for {root}")

    held = len(ledger["releases"])
    counts, current = collection_size(discogs, ledger)
    if counts:
        folder_name = counts.get("folder", "")
        distinct = counts.get("releases") or 0
        where = f" in '{folder_name}'" if folder_name else ""
        print(f"\n{held} / {distinct} releases{where} are in the ledger")
        if counts.get("copies"):
            print(f"    {counts.get('entries', 0)} collection entries, "
                  f"{counts['copies']} of them extra copies of a record "
                  f"already counted")
        if not current:
            print(f"    counted {counts.get('read_at', 'earlier')}, "
                  f"-refresh reads the collection again")
        if distinct > held:
            print(f"    {distinct - held:5}  never looked at, run a rip to "
                  f"reach them")
    else:
        print(f"\n{held} releases in the ledger")

    for status in sorted(statuses, key=lambda s: -statuses[s]):
        print(f"    {statuses[status]:5}  {status_label(status)}")

    # not all partial releases are equally partial, and the difference is what
    # decides which are worth chasing
    playable, broken, untold = [], [], []
    for entry in releases:
        if entry.get("status") not in (STATUS_PARTIAL, STATUS_QUEUED,
                                       STATUS_NO_MATCH):
            continue
        missing = missing_key_tracks(entry)
        if missing is None:
            untold.append(entry)
        elif missing:
            broken.append((entry, missing))
        else:
            playable.append(entry)

    if playable or broken or untold:
        print(f"\n{len(playable) + len(broken) + len(untold)} unfinished "
              f"releases, by what is actually missing")
        if playable:
            print(f"    {len(playable):5}  have key tracks")
        if broken:
            print(f"    {len(broken):5}  missing a key track")
        if untold:
            print(f"    {len(untold):5}  nothing recorded to tell either way")

    print(f"\n{total_tracks} tracks on those tracklists")
    print(f"    {ripped_tracks:5}  ripped")
    print(f"    {max(total_tracks - ripped_tracks, 0):5}  missing")

    if by_source:
        print("\nripped by source")
        for label in sorted(by_source, key=lambda s: -by_source[s]):
            print(f"    {by_source[label]:5}  {label}")

    waiting = {}
    for entry in releases:
        if entry.get("status") == STATUS_COMPLETE:
            continue
        for source in untried_sources(entry, list(SOURCE_ORDER)):
            waiting[source] = waiting.get(source, 0) + 1
    if waiting:
        print("\nunfinished releases never offered to a source")
        for source in SOURCE_ORDER:
            if waiting.get(source):
                print(f"    {waiting[source]:5}  {source}"
                      f"{' ' * max(1, 10 - len(source))}(-source {source})")

    exhausted, retryable = outstanding_tracks(ledger)
    print(f"\n{len(exhausted) + len(retryable)} missing tracks")
    print(f"    {len(retryable):5}  worth another run: rate limits, upload "
          f"queues, transient failures")
    print(f"    {len(exhausted):5}  every source tried and nothing found")

    if not exhausted:
        return

    if "-list" not in sys.argv and not verbose():
        print("\nadd -list to list the tracks nothing could get")
        return

    print(f"\n{len(exhausted)} tracks to rip yourself, by release.")
    print("a * is a key track: a side opener, or one this record gives no "
          "reason to think")
    print("is a tool or a locked groove. the rest you may not miss.")
    grouped = {}
    for entry, key, track in exhausted:
        grouped.setdefault(str(entry.get("id")), (entry, []))[1].append(
            (key, track))

    def release_name(pair):
        entry = pair[1][0]
        return (str(entry.get("artist", "")), str(entry.get("title", "")))

    for _id, (entry, rows) in sorted(grouped.items(), key=release_name):
        catno = entry.get("catno")
        keys = key_tracks(entry)
        print(f"\n  {entry.get('artist', '?')} - {entry.get('title', '?')}"
              + (f" ({catno})" if catno else ""))
        if entry.get("url"):
            print(f"    {entry['url']}")
        for key, track in sorted(rows):
            why = track.get("error") or track.get("error_kind") or "not found"
            mark = "*" if key in keys else " "
            print(f"    {mark} {key:>4}  {track.get('title', '?')}")
            print(f"            {why}")


def added_sort_key(entry):
    """
    When a release entered the collection, for ordering newest first.

    Entries with no date fall to the end rather than to the top: an old ledger
    entry with nothing recorded is not news.
    """
    return str(entry.get("date_added") or entry.get("ripped_at") or "")


def todo_report(root, ledger):
    """
    The releases still needing tracks, newest in the collection first.

    A worklist rather than a statistic. Newest first because that is the order
    records get bought and the order they are wanted in, and limited by -count
    so an evening's ripping can be a short list rather than the whole backlog.
    """
    unfinished = []
    for entry in ledger["releases"].values():
        if entry.get("status") == STATUS_COMPLETE:
            continue
        tracks = entry.get("tracks") or {}
        missing = sorted(key for key, track in tracks.items()
                         if (track or {}).get("status") != "ok")
        # nothing itemised, so fall back to whatever the entry claims
        if not missing:
            missing = list(entry.get("missing") or [])
        if not missing:
            continue
        keys = key_tracks(entry)
        if "-key-only" in sys.argv and not any(k in keys for k in missing):
            continue
        unfinished.append((entry, missing, keys))

    if not unfinished:
        print("\nnothing outstanding, every release in the ledger is complete")
        return

    unfinished.sort(key=lambda row: added_sort_key(row[0]), reverse=True)
    limit = arg_int("-count")
    shown = unfinished[:limit] if limit else unfinished

    total_tracks = sum(len(missing) for _e, missing, _k in unfinished)
    print(f"\n{len(unfinished)} releases still needing {total_tracks} tracks, "
          f"newest in the collection first")
    if limit and limit < len(unfinished):
        print(f"showing {len(shown)}, -count changes that")
    if "-key-only" in sys.argv:
        print("only releases missing a key track, -key-only")

    for number, (entry, missing, keys) in enumerate(shown, start=1):
        catno = entry.get("catno")
        added = str(entry.get("date_added") or "")[:10]
        done = entry.get("ripped", 0)
        total = entry.get("total", 0)
        print(f"\n{number}. {entry.get('artist', '?')} - "
              f"{entry.get('title', '?')}" + (f" ({catno})" if catno else ""))
        detail = [status_label(entry.get("status", "?"))]
        if total:
            detail.append(f"{done}/{total} tracks")
        if added:
            detail.append(f"added {added}")
        print(f"   {', '.join(detail)}")
        if entry.get("url"):
            print(f"   {entry['url']}")

        tracks = entry.get("tracks") or {}
        for key in missing:
            track = tracks.get(key) or {}
            mark = "*" if key in keys else " "
            why = track.get("error") or track.get("error_kind") or ""
            title = track.get("title", "?")
            print(f"   {mark} {key:>4}  {title}"
                  + (f"   {clip(why, 60)}" if why else ""))
        print(f"   rip it: -release {entry.get('id')} -retry")

    print("\n* is a key track: a side opener, or one this record gives no "
          "reason to think")
    print("is a tool or a locked groove.")


def expected_lengths(discogs, entry):
    """
    Discogs durations for a ledger entry's tracks, keyed the way they are keyed.

    Only called for entries written before the length check existed, which have
    no expected length recorded. Costs one release fetch, and the answer is
    written back into the ledger so it is a one off.
    """
    try:
        time.sleep(arg_float("-api-sleep", API_SLEEP))
        release = discogs_call(f"release {entry.get('id')}",
                               lambda: fetch_release(discogs, entry.get("id")))
    except Exception as e:
        print(f"    could not fetch release {entry.get('id')}: {e}")
        return {}

    artist = release_artist_string(release)
    lengths = {}
    for index, track in enumerate(build_track_records(release, artist)):
        key = track["position"] or str(index + 1)
        lengths[key] = track["duration"]
        lengths[str(index + 1)] = track["duration"]
    return lengths


def audit_library(discogs, root, ledger, dry_run):
    """
    Re-check every ripped file against the duration discogs lists for it.

    This is its own mode because a finished library cannot show you the problem.
    A snippet upload downloads cleanly, verifies as a valid mp3 and carries the
    tags we wrote, so the only thing that gives it away is that it runs 90
    seconds where the record runs six minutes.

    Comparing against discogs can only say so much, because plenty of releases
    have no timings entered at all, and a snippet of a track nobody timed sails
    through. So every short file is listed as well, compared or not: a promo
    snippet is around ninety seconds whatever it is a snippet of, and that is a
    fact about the file rather than about the comparison. Some will be genuine
    interludes and locked grooves, which is why they are a list to look down
    rather than a verdict.

    Nothing is deleted or re-ripped here, it only reports: discogs timings are
    user entered and a flag is not a verdict.
    """
    releases = sorted(ledger["releases"].values(),
                      key=lambda e: (str(e.get("artist", "")),
                                     str(e.get("title", ""))))
    count_limit = arg_int("-count")
    # anything at or under this is worth a look whatever discogs says. a snippet
    # upload sits around 1:30, so the default gives that room either side
    short_max = arg_int("-short-max", 165)

    findings = {"snippet": [], "short": [], "long": [], "gone": [],
                "unknown": []}
    suspect = []
    checked = 0
    fetched = 0

    print(f"\nauditing track lengths in {root}")
    for entry in releases:
        if count_limit is not None and checked >= count_limit:
            print(f"reached -count {count_limit}, stopping the audit")
            break

        tracks = entry.get("tracks") or {}
        ripped = {key: track for key, track in tracks.items()
                  if track.get("status") == "ok" and track.get("file")}
        if not ripped or not entry.get("dir"):
            continue

        name = f"{entry.get('artist', '?')} - {entry.get('title', '?')}"
        release_dir = os.path.join(root, entry["dir"])

        # fill in what the ledger predates, once, then remember it
        lengths = {}
        if discogs and any("expected_length" not in track
                           for track in ripped.values()):
            lengths = expected_lengths(discogs, entry)
            fetched += 1

        for key, track in sorted(ripped.items()):
            path = os.path.join(release_dir, track["file"])
            where = f"{name} [{key}] {track.get('title', '')}"

            if not os.path.exists(path):
                findings["gone"].append((where, "file is not on disk", path))
                continue

            expected = track.get("expected_length")
            if expected is None:
                expected = lengths.get(key) or lengths.get(str(track.get("number")))
                if expected:
                    track["expected_length"] = expected

            try:
                from mutagen.mp3 import MP3
                length = int(MP3(path).info.length)
            except Exception as e:
                findings["gone"].append((where, f"unreadable: {e}", path))
                continue

            track["length"] = length
            verdict, note, detail = check_length(path, length, expected,
                                                 measure=True)
            track.update(detail)
            checked += 1

            # every short file, listed on its own length rather than on the
            # comparison, so a snippet of an untimed track cannot slip past
            if length <= short_max:
                if expected:
                    agrees = "discogs agrees" if verdict == "ok" else note
                    against = f"discogs says {expected}s, {agrees}"
                else:
                    against = "discogs has no timing for it"
                suspect.append((length, where, against,
                                source_label(track.get("source")), path))

            if verdict == "unknown":
                findings["unknown"].append((where, note, path))
            elif verdict != "ok":
                source = source_label(track.get("source"))
                findings[verdict].append((where, f"{note}, from {source}", path))
            elif verbose() or debug():
                print(f"    [ ok ] {where}: {note}")

    print(f"\nchecked {checked} files"
          + (f", fetched {fetched} releases from discogs" if fetched else ""))

    order = [
        ("snippet", "almost certainly not the whole track"),
        ("short", "shorter than discogs says, worth a listen"),
        ("long", "longer than discogs says, silence already allowed for"),
        ("gone", "in the ledger but not usable on disk"),
        ("unknown", "no discogs duration to compare against"),
    ]
    for verdict, explanation in order:
        rows = findings[verdict]
        if not rows:
            continue
        if verdict == "unknown" and not verbose():
            print(f"\n{len(rows)} tracks with no discogs duration "
                  f"(-verbose lists them)")
            continue
        print(f"\n{len(rows)} {verdict}: {explanation}")
        for where, note, path in rows:
            print(f"    {where}")
            print(f"        {note}")
            print(f"        {path}")

    if suspect:
        def mmss(seconds):
            return f"{seconds // 60}:{seconds % 60:02d}"

        print(f"\n{len(suspect)} files of {mmss(short_max)} or under, shortest "
              f"first. a promo snippet is usually")
        print("around 1:30, so the ones clustered there are the ones to listen "
              "to. interludes,")
        print("locked grooves and skits live here too, hence a list rather than "
              "a verdict.")
        print(f"-short-max <seconds> moves the cutoff, currently {short_max}.\n")
        for length, where, against, source, path in sorted(suspect):
            print(f"    {mmss(length):>6}  {where}")
            print(f"            {against}, from {source}")
            print(f"            {path}")

    if findings["snippet"] or findings["short"] or suspect:
        print("\nto replace one of these, delete the file and re-rip that")
        print("release on its own, preferring soulseek:")
        print("    python discogs.py -rip -dir <dir> -release <id> "
              "-source soulseek -force")

    if not dry_run:
        # the expected lengths just filled in make the next audit offline
        save_ledger(root, ledger)


# ----------------------------------------------------------------------------
# bringing the ledger back in line with the disk
# ----------------------------------------------------------------------------

# ledger fields that describe the release's history rather than its contents,
# kept when -filecheck rebuilds an entry. everything else is worked out afresh
FILECHECK_CARRY = ("date_added", "attempts", "source_dir", "ripped_at")


def library_files(release_dir):
    """Audio files under a release directory, as paths relative to it."""
    if not os.path.isdir(release_dir):
        return []
    return [os.path.relpath(path, release_dir)
            for path in source_audio_files(release_dir)]


def scan_release_files(root, entry):
    """
    What a release directory holds that the ledger does not know about.

    Returns (deleted, new): the track keys the ledger has a file for that is no
    longer there, and the audio files on disk the ledger does not account for.
    Compared case insensitively, since the library lives on windows as often as
    not and a file renamed only in case is the same file there.
    """
    release_dir = os.path.join(root, entry["dir"])
    deleted = []
    known = set()
    for key, track in (entry.get("tracks") or {}).items():
        track = track or {}
        if track.get("status") != "ok" or not track.get("file"):
            continue
        known.add(os.path.normcase(track["file"]))
        if not os.path.exists(os.path.join(release_dir, track["file"])):
            deleted.append(key)
    new = [name for name in library_files(release_dir)
           if os.path.normcase(name) not in known]
    return sorted(deleted), new


def forget_deleted(entry, keys):
    """
    Treat a file deleted from the library as a flag on its track.

    Deleting is the quick way to say a rip is wrong, so it gets the same
    treatment a written flag does: the copy it came from is never taken again,
    and the source that produced it is forgotten so the next ordinary run goes
    looking afresh rather than reading the release as done.
    """
    tracks = entry.get("tracks") or {}
    now = datetime.datetime.now().isoformat(timespec="seconds")
    forget = set()
    for key in keys:
        track = tracks[key]
        identity = track_identity(track)
        if identity:
            entry.setdefault("rejected", []).append({
                "id": identity,
                "track": key,
                "reason": "deleted by hand",
                "source": track.get("source", ""),
                "when": now,
            })
        if track.get("source"):
            forget.add(track["source"])
        track.pop("file", None)
        track["status"] = "missing"
        track["error"] = "file deleted by hand"
        track["error_kind"] = "deleted"
    entry["sources_tried"] = [s for s in tried_sources(entry)
                              if s not in forget]


def recount_entry(entry):
    """Totals and status for an entry changed without a discogs fetch."""
    tracks = entry.get("tracks") or {}
    total = entry.get("total") or len(tracks)
    ripped = sum(1 for track in tracks.values()
                 if (track or {}).get("status") == "ok")
    missing = list(entry.get("missing") or [])
    for key, track in tracks.items():
        if (track or {}).get("status") != "ok" and key not in missing:
            missing.append(key)
    entry["ripped"] = ripped
    entry["missing"] = missing
    if ripped >= total:
        entry["status"] = STATUS_COMPLETE
    elif entry.get("status") == STATUS_QUEUED:
        pass
    elif ripped:
        entry["status"] = STATUS_PARTIAL
    else:
        entry["status"] = STATUS_NO_MATCH


def same_path(a, b):
    return os.path.normcase(os.path.abspath(a)) == \
        os.path.normcase(os.path.abspath(b))


def adopt_dropped_file(ctx, index, src):
    """
    Move a file dropped into the release directory into its track's place.

    The user put it there on purpose, so it is never deleted: a file that will
    not do is left where it is and said so, and an original is only removed
    once the converted copy has verified and been tagged. Returns True if the
    track is now ripped.
    """
    track = ctx["tracks"][index]
    key = track_key(ctx, index)
    target = track_path(ctx, index)
    name = os.path.relpath(src, ctx["release_dir"])
    ext = os.path.splitext(src)[1].lower()

    track_entry = new_track_entry(ctx, index)
    track_entry["dropped_file"] = name
    track_entry["format"] = ext
    print(f"    [ .. ] {key} {track['title']} <- {name}")

    if ext == ".mp3":
        # check before moving, so a file that will not do keeps its own name
        ok, detail = verify_audio(src, track["duration"])
        if not ok:
            print(f"    [fail] {key} {name}: {detail.get('error')}, "
                  f"left where it is")
            return False
        track_entry["converted"] = False
        if not same_path(src, target):
            try:
                os.replace(src, target)
            except OSError as e:
                print(f"    [fail] {key} could not rename {name}: {e}")
                return False
        return finish_track(ctx, index, target, SOURCE_LOCAL, "", track_entry)

    ok, error = to_mp3(src, target, ctx["quality"])
    track_entry["converted"] = True
    if not ok:
        print(f"    [fail] {key} {name}: {error}")
        return False
    if not finish_track(ctx, index, target, SOURCE_LOCAL, "", track_entry):
        try:
            if os.path.exists(target):
                os.remove(target)
        except OSError:
            pass
        print(f"    [fail] {key} {name} left where it is")
        return False
    try:
        os.remove(src)
    except OSError:
        # the mp3 is in place, a leftover original is untidy but harmless
        pass
    return True


def sync_release(release, root, token, previous, new_files):
    """
    Rebuild a release's ledger entry from what is in its directory.

    The same make_context every source uses, so the already on disk check, the
    file names and the tags are the ones a rip would give. On top of that, the
    files dropped in are matched to the tracks still missing and moved into
    their places. Returns (entry, files left unmatched, tracks adopted).
    """
    ctx, entry = make_context(release, root, token, previous)
    if ctx is None:
        return entry, new_files, 0

    previous_tracks = previous.get("tracks") or {}
    release_dir = ctx["release_dir"]

    # dropped in already carrying the right name: adopted off disk by the
    # context, but never tagged by us, so it is treated as a new file
    named = [index for index, track in ctx["done"].items()
             if (previous_tracks.get(track_key(ctx, index)) or {})
             .get("status") != "ok"]
    # the rest were ripped before, so keep what the ledger knew of where each
    # came from. without it a later deletion has nothing to record as rejected
    for index, track_entry in ctx["done"].items():
        if index not in named:
            old = previous_tracks.get(track_key(ctx, index)) or {}
            for field, value in old.items():
                track_entry.setdefault(field, value)

    taken = {os.path.normcase(track["file"]) for track in ctx["done"].values()}
    paths = [os.path.join(release_dir, name) for name in new_files
             if os.path.normcase(name) not in taken]

    if ((named or paths) and ctx["cover"][0] is None
            and "-no-cover" not in sys.argv):
        ctx["cover"] = fetch_cover(release, token)

    adopted = 0
    for index in named:
        track_entry = ctx["done"][index]
        track_entry["source"] = SOURCE_LOCAL
        try:
            tag_mp3(track_path(ctx, index), track_meta(ctx, index, ""),
                    ctx["cover"][0], ctx["cover"][1])
            track_entry["tagged"] = True
        except Exception as e:
            track_entry["tagged"] = False
            track_entry["tag_error"] = f"{type(e).__name__}: {e}"
        adopted += 1
        print(f"    [ ok ] {track_key(ctx, index)} "
              f"{ctx['tracks'][index]['title']} (already named, tagged)")

    pending = pending_tracks(ctx)
    candidates = local_candidates(paths)
    if pending and candidates:
        assignments, _whole, _unmatched = match_videos_to_tracks(
            ctx["tracks"], candidates, ctx["artists"], ctx["label"],
            ctx["catno"], ctx["artist"])
        for index in pending:
            match = assignments.get(index)
            if match and adopt_dropped_file(ctx, index,
                                            match["candidate"]["path"]):
                adopted += 1

    # still missing: keep whatever the ledger knew about why, a deletion or a
    # source that came up empty, rather than forgetting it
    for index in pending_tracks(ctx):
        key = track_key(ctx, index)
        if key not in entry["tracks"] and key in previous_tracks:
            entry["tracks"][key] = previous_tracks[key]

    entry["sources_tried"] = list(tried_sources(previous))
    if adopted and SOURCE_LOCAL not in entry["sources_tried"]:
        entry["sources_tried"].append(SOURCE_LOCAL)
    finish_release(ctx)

    unused = [os.path.relpath(path, release_dir) for path in paths
              if os.path.exists(path)]
    return entry, unused, adopted


def stray_folders(root, ledger):
    """Folders of audio in the library that no ledger entry owns."""
    known = {os.path.normcase(entry["dir"])
             for entry in ledger["releases"].values() if entry.get("dir")}
    return [name for name in sorted(os.listdir(root))
            if os.path.isdir(os.path.join(root, name))
            and not name.startswith(".")
            and os.path.normcase(name) not in known
            and source_audio_files(os.path.join(root, name))]


def filecheck_library(discogs, root, ledger, token, dry_run):
    """
    Bring the ledger back in line with what is actually in the library.

    Two kinds of hand editing are picked up. A file deleted from a release
    directory is taken as a verdict that it was wrong, recorded as rejected and
    its source forgotten, so the next run goes looking for a better copy. A file
    dropped into a release directory is matched to the track it belongs to,
    renamed to the library's naming and tagged from discogs, so it is
    indistinguishable from one that was ripped.

    Deletions are settled off the ledger alone. Only a release with new files
    costs a discogs fetch, for the tracklist to match them against.
    """
    count_limit = arg_int("-count")
    releases = sorted(ledger["releases"].items(),
                      key=lambda kv: (str(kv[1].get("artist", "")),
                                      str(kv[1].get("title", ""))))

    print(f"\nchecking files in {root} against the ledger")
    changed = 0
    deleted_total = 0
    adopted_total = 0
    unused_rows = []

    try:
        for key, entry in releases:
            if not entry.get("dir"):
                continue
            if count_limit is not None and changed >= count_limit:
                print(f"\nreached -count {count_limit}, stopping")
                break

            deleted, new = scan_release_files(root, entry)
            if not deleted and not new:
                continue

            changed += 1
            name = f"{entry.get('artist', '?')} - {entry.get('title', '?')}"
            print(f"\n{name} ({key})")
            tracks = entry.get("tracks") or {}
            for position in deleted:
                track = tracks[position]
                print(f"    [gone] {position} {track.get('title', '?')}: "
                      f"{track.get('file')}")
            for file_name in new:
                print(f"    [new ] {file_name}")
            if dry_run:
                continue

            if deleted:
                forget_deleted(entry, deleted)
                recount_entry(entry)
                deleted_total += len(deleted)

            if new:
                try:
                    time.sleep(arg_float("-api-sleep", API_SLEEP))
                    release = discogs_call(
                        f"release {entry.get('id')}",
                        lambda: fetch_release(discogs, entry.get("id")))
                    synced, unused, adopted = sync_release(
                        release, root, token, entry, new)
                except KeyboardInterrupt:
                    raise
                except Exception as e:
                    # the deletions above still stand, so keep them
                    print(f"    failed: {type(e).__name__}: {e}")
                    if verbose():
                        import traceback
                        traceback.print_exc()
                    save_ledger(root, ledger)
                    continue

                for field in FILECHECK_CARRY:
                    if field in entry:
                        synced[field] = entry[field]
                if unused:
                    synced["unused_files"] = unused
                    unused_rows.extend((name, f) for f in unused)
                adopted_total += adopted
                entry = synced
                ledger["releases"][key] = entry

            entry["checked_at"] = datetime.datetime.now().isoformat(
                timespec="seconds")
            save_ledger(root, ledger)
            print(f"    -> {status_label(entry.get('status'))}: "
                  f"{entry.get('ripped', 0)}/{entry.get('total', 0)} tracks"
                  + (f", missing {', '.join(entry.get('missing', []))}"
                     if entry.get("missing") else ""))

    except KeyboardInterrupt:
        print("\ninterrupted")

    if not dry_run:
        save_ledger(root, ledger)

    print("\nfilecheck summary")
    print(f"    releases changed: {changed}")
    if dry_run:
        print("    dry run, nothing written")
    else:
        print(f"    deleted files recorded: {deleted_total}")
        print(f"    new files adopted: {adopted_total}")

    if unused_rows:
        print(f"\n{len(unused_rows)} new files matched no missing track and "
              f"were left as they are:")
        for name, file_name in unused_rows:
            print(f"    {name}: {file_name}")
        print("either the track already has a file, so delete that one first,")
        print("or the file does not line up with the tracklist. naming it with")
        print("the position, 'A1 ...', is the easiest thing to match.")

    # not guessed at here: -input matches a folder by catalogue number
    strays = stray_folders(root, ledger)
    if strays:
        print(f"\n{len(strays)} folders with audio the ledger knows nothing "
              f"about:")
        for name in strays:
            print(f"    {name}")
        print("move them out of the library and bring them in with")
        print("    -input <folder>")

    if deleted_total:
        print("\nthe deleted tracks are missing again with their sources "
              "forgotten, so the")
        print("next ordinary run goes looking for a better copy.")


def slsk_test():
    """
    Check the slskd connection and print what we are talking to.

    Worth having as its own thing: soulseek ripping depends on a daemon, an
    account, an api key and a shares directory, and finding out which of those
    is wrong halfway through a collection is no way to spend an evening.
    """
    config = slsk_config()
    client = slsk.connect(config)
    if client is None:
        return False
    slsk.describe(client, config, slsk_downloads_dir())
    return True


def rip_collection(discogs, token):
    make_console_printable()

    if "-slsk-test" in sys.argv:
        slsk_test()
        return

    root = arg_value("-dir")
    if not root:
        print("error: -rip requires -dir <output directory>")
        return
    root = os.path.abspath(os.path.expanduser(root))

    dry_run = "-dry-run" in sys.argv
    count_limit = arg_int("-count")
    sources = requested_sources()

    if not dry_run and not check_mutagen():
        return

    # a status report only reads the ledger, so it needs nothing else set up and
    # touches nothing. first, so it works even on a directory that is not there
    # a worklist, read off the ledger like -status and writing nothing
    if "-todo" in sys.argv:
        if not os.path.isdir(root):
            print(f"error: no library at '{root}'")
            return
        todo_report(root, load_ledger(root))
        return

    if "-status" in sys.argv:
        if not os.path.isdir(root):
            print(f"error: no library at '{root}'")
            return
        ledger = load_ledger(root)
        status_report(root, ledger, discogs)
        # only the collection size can have changed, but remembering it is what
        # lets the next report count against something when offline
        if not dry_run:
            save_ledger(root, ledger)
        return

    # an audit reads the library rather than adding to it, so it runs before
    # anything here can create a directory, and nothing else runs after
    if "-audit" in sys.argv:
        if not os.path.isdir(root):
            print(f"error: -audit needs a library to read, '{root}' is not there")
            return
        audit_library(discogs, root, load_ledger(root), dry_run)
        return

    # files added or deleted by hand, brought into the ledger. like the audit it
    # works on a library that is already there and does nothing else after
    if "-filecheck" in sys.argv:
        if not os.path.isdir(root):
            print(f"error: -filecheck needs a library to read, '{root}' is not there")
            return
        filecheck_library(discogs, root, load_ledger(root), token, dry_run)
        return

    if not os.path.isdir(root):
        if dry_run:
            # a dry run writes nothing, so preview against a directory that is
            # not there yet rather than creating it as a side effect
            print(f"note: -dir '{root}' does not exist yet, nothing will be written")
        else:
            os.makedirs(root, exist_ok=True)
            print(f"created output directory {root}")

    ledger = load_ledger(root)

    # -input imports rips made elsewhere rather than fetching anything, so it
    # takes over the session: the walk is over the folders, not the collection
    if arg_value("-input"):
        import_local(discogs, root, arg_value("-input"), token, ledger)
        return

    print(f"ripping to {root}")
    print(f"sources: {', '.join(sources)}")
    print(f"ledger holds {len(ledger['releases'])} releases from previous sessions")

    # fail here rather than one release at a time. a soulseek only session with
    # no daemon has nothing to do at all, and quietly falling through to another
    # source is the one thing it must never do: the whole point of naming one is
    # that the others are left alone
    if sources == [SOURCE_SOULSEEK] and slsk_connect() is None:
        print("error: -source soulseek needs slskd, and it is not reachable")
        print("       run with -slsk-test to check the connection")
        return

    # a single release by id, useful for checking the matching on one record
    single = arg_int("-release")
    if single:
        items = [discogs_call(f"release {single}",
                              lambda: fetch_release(discogs, single))]
        collection_items = False
    else:
        user = discogs_call("identity", discogs.identity)
        folder = pick_folder(user, arg_value("-folder"))
        if folder is None:
            return
        order = "asc" if "-oldest" in sys.argv else "desc"
        releases = folder.releases
        releases.sort("added", order)
        # our own pager rather than the client's, so a rate limit part way
        # through the collection is a wait instead of the end of the session
        items = iter_releases(releases)
        collection_items = True
        when = "oldest" if order == "asc" else "newest"
        print(f"folder '{folder.name}' ({folder.count} releases), {when} added first")

    processed = 0
    skipped = 0
    stats = {}

    try:
        for item in items:
            # the address is rate limited, nothing further will download
            if session_blocked:
                break
            if count_limit is not None and processed >= count_limit:
                print(f"\nreached -count {count_limit}, stopping")
                break

            if collection_items:
                basic = item.release
                date_added = collection_date_added(item)
            else:
                basic = item
                date_added = None

            key = str(basic.id)
            needed, previous = should_rip(key, ledger, sources)
            if not needed:
                skipped += 1
                if verbose():
                    print(f"skip {key} {previous.get('artist')} - "
                          f"{previous.get('title')} ({previous.get('status')})")
                continue

            # basic_information from a collection item carries no videos and no
            # full tracklist, so fetch the full release
            try:
                time.sleep(arg_float("-api-sleep", API_SLEEP))
                release = discogs_call(f"release {basic.id}",
                                       lambda: fetch_release(discogs, basic.id))
            except Exception as e:
                print(f"failed to fetch release {basic.id}: {e}")
                ledger["releases"][key] = {
                    "id": basic.id,
                    "status": STATUS_FAILED,
                    "error": f"fetch failed: {e}",
                    "attempts": (previous or {}).get("attempts", 0) + 1,
                }
                if not dry_run:
                    save_ledger(root, ledger)
                processed += 1
                continue

            artist = release_artist_string(release)
            print(f"\n[{processed + 1}] {artist} - {release.title} ({release.id})")

            try:
                entry = rip_release(release, root, token, previous)
            except KeyboardInterrupt:
                raise
            except Exception as e:
                print(f"    failed: {type(e).__name__}: {e}")
                entry = {
                    "id": release.id,
                    "artist": artist,
                    "title": normalize_unicode(release.title or ""),
                    "status": STATUS_FAILED,
                    "error": f"{type(e).__name__}: {e}",
                }

            # which sources this release has now been through, this session's on
            # top of every earlier one, so a later -source knows what is left
            entry["sources_tried"] = merge_tried(previous, entry)
            entry["attempts"] = (previous or {}).get("attempts", 0) + 1
            if date_added:
                entry["date_added"] = date_added
            entry["ripped_at"] = datetime.datetime.now().isoformat(timespec="seconds")

            ledger["releases"][key] = entry
            if not dry_run:
                save_ledger(root, ledger)

            status = entry["status"]
            stats[status] = stats.get(status, 0) + 1
            processed += 1

            if status == STATUS_COMPLETE:
                print(f"    -> complete: {entry.get('ripped', entry.get('total', 0))} tracks")
            elif status in (STATUS_PARTIAL, STATUS_QUEUED):
                print(f"    -> {status_label(status)}: "
                      f"{entry.get('ripped', 0)}/{entry.get('total', 0)} "
                      f"tracks, missing {', '.join(entry.get('missing', []))}")
            else:
                print(f"    -> {status_label(status)}")

            # breathe between releases as well, the discogs fetch plus a run of
            # track downloads is exactly the burst that trips a rate limit
            if not session_blocked and not dry_run:
                crawl_pause("before next release")

    except KeyboardInterrupt:
        print("\ninterrupted")
    except Exception as e:
        # a discogs request that outlasted its retries, or anything else
        # unexpected. stop with the ledger written and a readable reason,
        # rather than unwinding out of the script and losing the session
        status = http_status_of(e)
        print(f"\nstopped: {type(e).__name__}: {e}")
        if status == 429:
            print("discogs rate limited for longer than the retries cover.")
            print("wait a few minutes and re-run the same command, the ledger")
            print("picks up where this left off. -api-sleep raises the pause")
            print("between api calls if it keeps happening.")
        if verbose():
            import traceback
            traceback.print_exc()

    if not dry_run:
        save_ledger(root, ledger)

    print("\nsession summary")
    print(f"    processed: {processed}")
    print(f"    skipped (already done): {skipped}")
    for status in sorted(stats):
        print(f"    {status_label(status)}: {stats[status]}")

    report_outstanding(ledger, sources)
