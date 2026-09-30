"""
slsk.py

Find and download release audio from the soulseek network.

Soulseek has no public api. The network is a proprietary tcp protocol spoken to
a central server, and the only documentation of it is the community's reverse
engineered spec. What it does have is slskd, a headless soulseek client that
runs on this machine and exposes a rest api on localhost, so everything here
talks to slskd and slskd talks to soulseek. slskd owns the account, the peer
connections, the upload queues and transfer resume. This module owns searching,
turning peer file listings into candidates, asking for the files and waiting
for them to land.

Deliberately knows nothing about argv or about discogs: rip.py reads the flags,
does the matching against the tracklist and writes the tags. That keeps the
matcher single sourced across every source, and keeps this testable without a
daemon.
"""

import json
import os
import re
import time


# slskd's own defaults, it listens on 5030 and writes to an app directory
DEFAULT_HOST = "http://localhost:5030"
AUTH_FILE = "slskd-auth.json"

# what we are willing to take from a peer
AUDIO_EXT = (".mp3", ".flac", ".aiff", ".aif", ".wav", ".m4a", ".alac",
             ".ogg", ".opus", ".wma")
LOSSLESS_EXT = (".flac", ".aiff", ".aif", ".wav", ".alac")

# archives, artwork and scene junk that shares up alongside the audio
SKIP_EXT = (".zip", ".rar", ".7z", ".cue", ".nfo", ".sfv", ".m3u", ".m3u8",
            ".jpg", ".jpeg", ".png", ".gif", ".txt", ".log", ".pdf", ".db",
            ".mp4", ".mkv", ".avi", ".mov", ".wmv", ".flv")


# ----------------------------------------------------------------------------
# config and connection
# ----------------------------------------------------------------------------

def auth_config(host=None, key=None):
    """
    Where to find slskd and how to authenticate to it.

    Explicit arguments win, then scrape/slskd-auth.json, following the same
    convention as discogs-auth.json. The file holds:

        {"host": "http://localhost:5030", "key": "..."}

    The key is an api key configured in slskd.yml under
    web.authentication.api_keys, and it needs readwrite to queue downloads.
    """
    config = {"host": host or DEFAULT_HOST, "key": key}
    if host and key:
        return config

    for candidate in (AUTH_FILE,
                      os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                   AUTH_FILE)):
        if not os.path.exists(candidate):
            continue
        try:
            data = json.loads(open(candidate, "r", encoding="utf-8").read())
        except (ValueError, OSError) as e:
            print(f"warning: could not read {candidate}: {e}")
            continue
        if not host and data.get("host"):
            config["host"] = data["host"]
        if not key and data.get("key"):
            config["key"] = data["key"]
        break

    return config


def import_client():
    try:
        import slskd_api
        return slskd_api
    except ImportError:
        print("error: slskd-api is required to rip from soulseek")
        print("       pip install slskd-api  (or re-run scrape/setup.sh)")
        return None


def daemon_state(client):
    """
    slskd's own view of itself, including whether it is logged in to soulseek.

    The api surface has moved between slskd versions, so try the application
    endpoint and fall back to the server one rather than assuming either.

    Raises the last transport error if every endpoint it knows about failed,
    rather than returning nothing: the caller has to be able to tell "slskd is
    not there" from "slskd is there and not logged in", and those two have very
    different fixes.
    """
    last_error = None
    for name in ("application", "server"):
        api = getattr(client, name, None)
        state = getattr(api, "state", None)
        if state is None:
            continue
        try:
            return state()
        except Exception as e:
            last_error = e
    if last_error is not None:
        raise last_error
    return None


def server_status(state):
    """(connected, logged_in, description) out of whatever shape state is."""
    state = state or {}
    server = state.get("server")
    if not isinstance(server, dict):
        server = state
    connected = bool(server.get("isConnected", server.get("connected")))
    logged_in = bool(server.get("isLoggedIn", server.get("loggedIn")))
    description = str(server.get("state") or server.get("address") or "unknown")
    return connected, logged_in, description


def connect(config):
    """
    Connect to slskd. Returns a client, or None with the reason printed.

    None is not fatal to the caller by itself: a session with another source in
    its list carries on without soulseek, a soulseek only session stops. That
    choice belongs to rip.py, not here.
    """
    api = import_client()
    if api is None:
        return None

    host = config.get("host") or DEFAULT_HOST
    key = config.get("key")
    if not key:
        print(f"error: no slskd api key. put one in scrape/{AUTH_FILE} or "
              f"pass -slsk-key")
        return None

    try:
        client = api.SlskdClient(host, key)
        state = daemon_state(client)
    except Exception as e:
        print(f"error: cannot reach slskd at {host}: {type(e).__name__}: {e}")
        print("       is slskd running, and is the api key right?")
        return None

    connected, logged_in, description = server_status(state)
    if not (connected and logged_in):
        print(f"error: slskd is up at {host} but not logged in to soulseek "
              f"({description})")
        print("       check the soulseek credentials in slskd.yml")
        return None

    return client


def describe(client, config, downloads):
    """Print what we are connected to, for -slsk-test."""
    try:
        state = daemon_state(client)
    except Exception as e:
        print(f"slskd at {config.get('host')}: {type(e).__name__}: {e}")
        return
    connected, logged_in, description = server_status(state)
    version = (state or {}).get("version")
    print(f"slskd at {config.get('host')}")
    if version:
        print(f"    version: {version}")
    print(f"    soulseek: connected={connected} logged_in={logged_in} "
          f"({description})")
    print(f"    downloads dir: {downloads}"
          f"{'' if os.path.isdir(downloads) else '  [missing]'}")
    try:
        shared = client.shares.all_contents()
        count = sum(len(d.get("files") or []) for d in shared or [])
        print(f"    shares: {count} files in {len(shared or [])} directories")
        if not count:
            print("    warning: sharing nothing. peers commonly refuse "
                  "non-sharers, expect rejected queues")
    except Exception as e:
        print(f"    shares: could not read ({type(e).__name__}: {e})")


def default_downloads_dir():
    """
    Where slskd puts finished files when it has not been told otherwise.

    slskd keeps an application directory per platform and downloads live under
    it. Only used as a fallback, -slsk-downloads is the reliable answer.
    """
    local = os.environ.get("LOCALAPPDATA")
    if local:
        return os.path.join(local, "slskd", "downloads")
    return os.path.join(os.path.expanduser("~"), ".local", "share", "slskd",
                        "downloads")


# ----------------------------------------------------------------------------
# searching
# ----------------------------------------------------------------------------

def search(client, text, timeout_ms=15000, wait=45.0, verbose=False):
    """
    Run one soulseek search and return the peer responses.

    A search is asynchronous: slskd asks the server, peers answer over the
    following seconds, and the search is complete when it times out. So we
    start it, wait for it to settle, then read the responses and delete the
    search so slskd's history does not fill up with our queries.
    """
    try:
        started = client.searches.search_text(searchText=text,
                                              searchTimeout=timeout_ms)
    except Exception as e:
        print(f"    [warn] soulseek search failed: {type(e).__name__}: {e}")
        return []

    search_id = (started or {}).get("id")
    if not search_id:
        print("    [warn] soulseek search returned no id")
        return []

    deadline = time.time() + max(wait, timeout_ms / 1000.0 + 5.0)
    responses = []
    try:
        while time.time() < deadline:
            time.sleep(1.0)
            state = client.searches.state(search_id)
            if (state or {}).get("isComplete"):
                break
        responses = client.searches.search_responses(search_id) or []
    except Exception as e:
        print(f"    [warn] reading soulseek results failed: "
              f"{type(e).__name__}: {e}")
    finally:
        try:
            client.searches.delete(search_id)
        except Exception:
            pass

    if verbose:
        files = sum(len(r.get("files") or []) for r in responses)
        print(f"    [slsk] '{text}': {len(responses)} peers, {files} files")
    return responses


def remote_dirname(filename):
    """Parent directory of a peer's file path, which is windows shaped."""
    return re.split(r"[\\/](?=[^\\/]*$)", filename)[0] if filename else ""


def remote_basename(filename):
    return re.split(r"[\\/]", filename or "")[-1]


def extension_of(filename):
    return os.path.splitext(remote_basename(filename))[1].lower()


def candidates(responses, min_bitrate=0):
    """
    Flatten peer responses into one candidate per audio file.

    Locked files are skipped: the peer has them behind a share ratio we are not
    going to satisfy, and asking only earns a rejection. Non audio is skipped
    too, a release folder is usually full of artwork and a cue sheet.
    """
    found = []
    for response in responses or []:
        username = response.get("username")
        if not username:
            continue
        for item in response.get("files") or []:
            filename = item.get("filename")
            if not filename:
                continue
            ext = extension_of(filename)
            if ext in SKIP_EXT or ext not in AUDIO_EXT:
                continue
            bitrate = item.get("bitRate")
            # a bitrate floor only means anything where the peer reported one,
            # and it never applies to lossless
            if (min_bitrate and bitrate and ext not in LOSSLESS_EXT
                    and bitrate < min_bitrate):
                continue
            found.append({
                "title": os.path.splitext(remote_basename(filename))[0],
                "duration": item.get("length") or None,
                "url": f"slsk://{username}/{remote_basename(filename)}",
                "username": username,
                "filename": filename,
                "dirname": remote_dirname(filename),
                "size": item.get("size") or 0,
                "bitrate": bitrate,
                "format": ext,
                "lossless": ext in LOSSLESS_EXT,
                "queue_length": response.get("queueLength") or 0,
                "free_slots": bool(response.get("hasFreeUploadSlot")),
                "speed": response.get("uploadSpeed") or 0,
            })
    return found


def folders(candidates_list):
    """
    Group candidates by the peer directory they live in.

    A release is normally shared as a folder, and taking a whole folder from
    one peer is what gets a consistent set of files at one quality. Matching
    per file across every peer on the network gets twelve different rips.
    """
    grouped = {}
    for candidate in candidates_list:
        grouped.setdefault((candidate["username"], candidate["dirname"]),
                           []).append(candidate)
    return grouped


def quality_rank(candidate, want_bitrate=320):
    """
    How much we want this file, higher is better.

    mp3 first because the library is mp3 and taking one avoids a re-encode,
    lossless next because transcoding it is lossy but from a better master,
    everything else last.
    """
    if candidate["format"] == ".mp3":
        bitrate = candidate.get("bitrate") or 0
        # 320 is the target, anything above it is no better for our purposes
        return 300 + min(bitrate, want_bitrate) / 10.0
    if candidate["lossless"]:
        return 200.0
    return 100.0


def peer_rank(candidate):
    """
    How likely this peer is to actually serve us, higher is better.

    A free slot means the transfer starts now instead of sitting in a queue
    behind forty other people, which is the difference between a rip that
    finishes in this session and one that does not.
    """
    score = 0.0
    if candidate.get("free_slots"):
        score += 100.0
    score -= min(candidate.get("queue_length") or 0, 50) * 2.0
    score += min((candidate.get("speed") or 0) / 1000.0, 50.0)
    return score


# ----------------------------------------------------------------------------
# transfers
# ----------------------------------------------------------------------------

# slskd reports transfer state as comma joined flags, and the exact spellings
# have changed between releases and broken other clients. Match on substrings
# so "Completed, Succeeded" and a future "Completed, Succeeded, Whatever" both
# read the same.
PENDING_STATES = ("requested", "queued", "initializing", "inprogress")


def state_of(transfer):
    return str((transfer or {}).get("state") or "").strip()


def is_pending(state):
    low = state.lower().replace(" ", "")
    if "completed" in low:
        return False
    return any(marker in low for marker in PENDING_STATES)


def succeeded(state):
    low = state.lower()
    return "completed" in low and "succeeded" in low


def failed(state):
    low = state.lower()
    if "completed" not in low:
        return False
    return any(word in low for word in
               ("errored", "cancelled", "canceled", "timedout", "rejected"))


def enqueue(client, username, files):
    """
    Ask a peer for files. files is [{"filename", "size"}].

    A true return only means slskd accepted the request, not that the peer
    will serve it: a rejection or a ban shows up later as a failed transfer.
    """
    try:
        client.transfers.enqueue(username=username, files=files)
        return True, None
    except Exception as e:
        return False, f"{type(e).__name__}: {e}"


def downloads(client):
    """Every download slskd knows about, flattened to one list of transfers."""
    try:
        users = client.transfers.get_all_downloads() or []
    except Exception as e:
        print(f"    [warn] could not read slskd downloads: "
              f"{type(e).__name__}: {e}")
        return []

    flat = []
    if isinstance(users, dict):
        users = [users]
    for user in users:
        username = user.get("username")
        for directory in user.get("directories") or []:
            for transfer in directory.get("files") or []:
                transfer = dict(transfer)
                transfer.setdefault("username", username)
                flat.append(transfer)
    return flat


def wait_for(client, wanted, seconds, poll=4.0, verbose=False):
    """
    Wait for enqueued files to reach a terminal state.

    Returns {remote filename: state}, with anything still queued when the wait
    runs out left exactly as it is. Soulseek queues run to hours, so giving up
    on the wait is not the same as giving up on the file: slskd keeps the
    transfer, it may well complete while we get on with the rest of the
    collection, and the next session picks the finished file up off disk.
    """
    outstanding = {name for name in wanted}
    states = {name: "Requested" for name in wanted}
    deadline = time.time() + max(seconds, 0)
    announced = 0.0

    while outstanding and time.time() < deadline:
        time.sleep(poll)
        for transfer in downloads(client):
            name = transfer.get("filename")
            if name not in outstanding:
                continue
            state = state_of(transfer)
            states[name] = state
            if not is_pending(state):
                outstanding.discard(name)

        waited = time.time() - (deadline - max(seconds, 0))
        if outstanding and (verbose or waited - announced >= 30.0):
            announced = waited
            example = sorted(outstanding)[0]
            print(f"    [slsk] {len(outstanding)} of {len(wanted)} still "
                  f"pending after {int(waited)}s "
                  f"({states.get(example, 'unknown')})")

    return states


def find_download(downloads_dir, remote_filename, size=0):
    """
    The local path slskd wrote a finished transfer to.

    Predicting the path is not safe: slskd names the local folder after the
    peer's and sanitises both folder and file for the local filesystem, and
    that sanitising differs by platform and version. Looking for the basename
    under the downloads directory is boring and always right, and the size
    confirms it when several releases share a track name.
    """
    if not downloads_dir or not os.path.isdir(downloads_dir):
        return None

    target = remote_basename(remote_filename)
    stem = os.path.splitext(target)[0].lower()
    fallback = None

    for root, _dirs, names in os.walk(downloads_dir):
        for name in names:
            if name.lower().endswith(".incomplete"):
                continue
            path = os.path.join(root, name)
            if name == target:
                if not size or abs(os.path.getsize(path) - size) < 1024:
                    return path
                fallback = fallback or path
                continue
            # sanitised on the way to disk, compare what survives
            if os.path.splitext(name)[0].lower() == stem:
                fallback = fallback or path

    return fallback
