#!/home/user/nomadnet-env/bin/python3
# =============================================================================
#  index.mu  —  NomadNet index page with visit counters
#
#  Two numbers are shown:
#
#   1. "Page visits"  — NomadNet's OWN lifetime counter, read live from
#      ~/.nomadnetwork/storage/peersettings (key "served_page_requests").
#      NomadNet has been incrementing this since the node was first set up,
#      so it is already a large historical number, not a fresh zero. NOTE it
#      counts requests for EVERY page on this node, not just this one. The
#      date shown beside it is the node SETUP date (identity file mtime) —
#      NomadNet does not record when the first hit actually arrived.
#
#   2. "This page"    — a precise per-page count kept by this script in
#      ~/.nomadnetwork/storage/pagecounts/index.count. Starts from when it
#      was added and PERSISTS across nomadnet restarts, VM reboots and host
#      migrations. Delete that file to reset it; edit "total" in it to seed.
#
#  The page TEXT lives in ~/.nomadnetwork/storage/pagetext/index.body.mu —
#  edit that file (plain Micron, no Python) to change what the page says.
#  Text, counts and backups all live OUTSIDE pages/ so NomadNet never serves
#  them as pages of their own.
# =============================================================================

import os, json, fcntl, datetime

BASE  = os.path.expanduser("~/.nomadnetwork/storage")
BODY  = os.path.join(BASE, "pagetext",   "index.body.mu")
COUNT = os.path.join(BASE, "pagecounts", "index.count")
PEERS = os.path.join(BASE, "peersettings")
IDENT = os.path.join(BASE, "identity")


def setup_date():
    """Date this node was set up, or None.

    NomadNet's identity file is written once when the node is first created
    and never rewritten, so its mtime is the node's birthday. It survives
    backup/restore and host migration.

    NOTE this is the SETUP date, not the date of the first page hit —
    NomadNet records no first-hit date. peersettings cannot be used for it:
    save_peer_settings() does os.replace(), so that file's birth time is the
    LAST save, not the first.
    """
    try:
        return datetime.date.fromtimestamp(os.path.getmtime(IDENT)).isoformat()
    except Exception:
        return None


def node_total():
    """NomadNet's own lifetime served-page count, or None if unreadable.

    NomadNet increments and saves this BEFORE it executes this script, so the
    value on disk already includes the current visit.
    """
    try:
        import RNS.vendor.umsgpack as msgpack
        with open(PEERS, "rb") as f:
            return int(msgpack.unpackb(f.read())["served_page_requests"])
    except Exception:
        return None


def bump():
    """Increment and return this page's own visit record.

    Never raises: if the counter file is missing, corrupt or unwritable the
    page must still render. A broken counter must not break the index page.
    flock'd so two simultaneous visitors cannot lose a count.
    """
    try:
        os.makedirs(os.path.dirname(COUNT), exist_ok=True)
        fd = os.open(COUNT, os.O_RDWR | os.O_CREAT, 0o644)
        with os.fdopen(fd, "r+") as f:
            fcntl.flock(f, fcntl.LOCK_EX)
            raw = f.read().strip()
            try:
                rec = json.loads(raw) if raw else {}
            except ValueError:
                rec = {}          # corrupt file: start over rather than fail
            rec["total"] = int(rec.get("total", 0)) + 1
            rec.setdefault("since", datetime.date.today().isoformat())
            rec["last"] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
            f.seek(0)
            f.truncate()
            f.write(json.dumps(rec))
            f.flush()
        return rec
    except Exception:
        return None


# ---- page body -------------------------------------------------------------
try:
    with open(BODY, "r") as f:
        print(f.read().rstrip("\n"))
except Exception:
    print("`Ff00Page body missing — see ~/.nomadnetwork/storage/pagetext/`f")

# ---- visit counter footer --------------------------------------------------
total = node_total()
rec   = bump()

print()
print("`F0f2────────────────────────────────────────")
if total is not None:
    since = setup_date()
    when  = f", since {since}" if since else ""
    print(f"`F888  Page visits: {total:,}  ·  all pages on this node{when}`f")
if rec:
    print(f"`F888  This page: {rec['total']:,}  ·  since {rec['since']}`f")
if total is None and not rec:
    print("`F888  Page visits: counter unavailable`f")
