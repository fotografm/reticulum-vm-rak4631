#!/usr/bin/python3
"""muweb: serve executable Micron (.mu) pages as HTML on the LAN.

Loc2 twin of the x12-2 NomadNet page servers, without NomadNet: the same page
scripts run unchanged, their Micron output is converted to HTML here.

  GET /                     -> redirect to /page/index.mu
  GET /page/X.mu?k=v        -> run PAGES/X.mu with env var_k=v, return HTML
  GET /page/X.mu?k=v&frag=1 -> body fragment only (used by partial refresh)

Micron partials (`{hash:/page/x.mu`secs`k=v|..}) become a <div> that is
rendered inline and re-fetched every <secs> by a few lines of JavaScript.
Links to local pages become ordinary links; links to other Reticulum
destinations cannot be followed from a browser and are shown as text.

Config by environment: MUWEB_PAGES (dir), MUWEB_PORT (default 80),
MUWEB_TITLE (browser tab title).
"""

import html
import os
import re
import subprocess
import sys
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PAGES = os.environ.get("MUWEB_PAGES", "/opt/muweb/pages")
PORT = int(os.environ.get("MUWEB_PORT", "80"))
TITLE = os.environ.get("MUWEB_TITLE", "868 MHz monitor")
PAGE_TIMEOUT = 30

CSS = """
:root { color-scheme: dark; }
body { background:#000; color:#ddd; margin:0; padding:12px 16px;
       font: 14px/1.25 "DejaVu Sans Mono", Menlo, Consolas, monospace; }
.mu { white-space: pre; }
.mu .ln { min-height: 1.25em; }
.mu .c { text-align: center; } .mu .r { text-align: right; }
.mu h1 { font-size: 1.15em; margin: .2em 0; padding: .15em .4em; background:#223; color:#fff; }
.mu hr { border: 0; border-top: 1px solid #555; margin: .4em 0; }
.mu a { color: inherit; text-decoration: underline; }
.mu .ext { text-decoration: underline dotted; cursor: help; }
.mu .partial.stale { opacity: .6; }
"""

JS = """
for (const d of document.querySelectorAll('.partial')) {
  const url = d.dataset.src, secs = parseInt(d.dataset.int || '0', 10);
  if (!secs) continue;
  setInterval(async () => {
    try {
      const r = await fetch(url + (url.includes('?') ? '&' : '?') + 'frag=1', {cache: 'no-store'});
      if (!r.ok) throw new Error(r.status);
      d.innerHTML = await r.text(); d.classList.remove('stale');
    } catch (e) { d.classList.add('stale'); }
  }, secs * 1000);
}
"""

PAGE_RE = re.compile(r"^/page/([A-Za-z0-9_.-]+\.mu)$")
HEX32 = re.compile(r"^[0-9a-f]{32}$")


def run_page(name, fields, served=True):
    """Execute a page script; fields become var_<k> like NomadNet does."""
    path = os.path.join(PAGES, name)
    if not os.path.isfile(path):
        return None
    env = dict(os.environ)
    for k, v in fields.items():
        if re.match(r"^[A-Za-z0-9_]+$", k):
            env["var_" + k] = v
    # The page-view counters only count requests that carry link_id, exactly
    # as under NomadNet; partial refreshes and inline renders do not.
    if served:
        env["link_id"] = "web"
    else:
        env.pop("link_id", None)
    try:
        if os.access(path, os.X_OK):
            out = subprocess.run([path], env=env, capture_output=True,
                                 timeout=PAGE_TIMEOUT).stdout
        else:
            out = open(path, "rb").read()
    except subprocess.TimeoutExpired:
        return "`c`Ff55`!Page timed out``"
    return out.decode("utf-8", "replace")


def parse_fields(s):
    out = {}
    for part in (s or "").split("|"):
        if "=" in part:
            k, v = part.split("=", 1)
            out[k] = v
    return out


def local_path(url):
    """'/page/x.mu', ':/page/x.mu' or '<hash>:/page/x.mu' -> '/page/x.mu'.

    A hash prefix is treated as local only when it is not a real 32-hex
    destination (the pages here embed a placeholder hash for partials).
    """
    if url.startswith("/"):
        return url
    if ":" in url:
        dest, path = url.split(":", 1)
        if path.startswith("/") and (dest == "" or dest == LOCAL_HASH):
            return path
    return None


def href(path, fields):
    q = urllib.parse.urlencode(fields)
    return path + ("?" + q if q else "")


class Style:
    def __init__(self):
        self.reset()

    def reset(self):
        self.fg = self.bg = None
        self.bold = self.ital = self.under = False

    def css(self):
        s = []
        if self.fg:
            s.append("color:#%s" % self.fg)
        if self.bg:
            s.append("background:#%s" % self.bg)
        if self.bold:
            s.append("font-weight:bold")
        if self.ital:
            s.append("font-style:italic")
        if self.under:
            s.append("text-decoration:underline")
        return ";".join(s)


def convert_line(line, st, align):
    """One Micron line -> (html, align). Style persists across lines."""
    out = []
    buf = []
    cur_css = [st.css()]
    line_align = [None]     # alignment in force where the first text lands

    def flush():
        if buf:
            t = html.escape("".join(buf))
            out.append('<span style="%s">%s</span>' % (cur_css[0], t) if cur_css[0] else t)
            buf.clear()

    def restyle():
        c = st.css()
        if c != cur_css[0]:
            flush()
            cur_css[0] = c

    i, n = 0, len(line)
    while i < n:
        ch = line[i]
        if ch == "\\" and i + 1 < n:
            line_align[0] = line_align[0] or align
            buf.append(line[i + 1]); i += 2; continue
        if ch != "`":
            line_align[0] = line_align[0] or align
            buf.append(ch); i += 1; continue
        # ch == backtick
        nx = line[i + 1] if i + 1 < n else ""
        if nx == "`":
            st.reset(); align = "l"; restyle(); i += 2; continue
        if nx == "F" and i + 5 <= n:
            st.fg = line[i + 2:i + 5]; restyle(); i += 5; continue
        if nx == "B" and i + 5 <= n:
            st.bg = line[i + 2:i + 5]; restyle(); i += 5; continue
        if nx == "f":
            st.fg = None; restyle(); i += 2; continue
        if nx == "b":
            st.bg = None; restyle(); i += 2; continue
        if nx == "!":
            st.bold = not st.bold; restyle(); i += 2; continue
        if nx == "*":
            st.ital = not st.ital; restyle(); i += 2; continue
        if nx == "_":
            st.under = not st.under; restyle(); i += 2; continue
        if nx in "clra":
            align = "l" if nx == "a" else nx; i += 2; continue
        if nx == "[":
            j = line.find("]", i)
            if j < 0:
                buf.append(line[i:]); break
            parts = line[i + 2:j].split("`")
            if len(parts) == 1:
                label, url, fields = parts[0], parts[0], ""
            else:
                label, url = parts[0], parts[1]
                fields = parts[2] if len(parts) > 2 else ""
            label = label or url
            line_align[0] = line_align[0] or align
            flush()
            lp = local_path(url)
            sty = (' style="%s"' % cur_css[0]) if cur_css[0] else ""
            if lp and PAGE_RE.match(lp):
                out.append('<a href="%s"%s>%s</a>' % (html.escape(href(lp, parse_fields(fields))),
                                                     sty, html.escape(label)))
            else:
                out.append('<span class="ext" title="%s"%s>%s</span>' % (
                    html.escape("Reticulum link: " + url), sty, html.escape(label)))
            i = j + 1
            continue
        # unknown tag: drop the backtick and its letter, as NomadNet does
        i += 2
    flush()
    return "".join(out), align, (line_align[0] or align)


PARTIAL_RE = re.compile(r"^`\{([^`}]*)(?:`(\d+)(?:`([^}]*))?)?\}\s*$")


def to_html(text, depth=0):
    st = Style()
    align = "l"
    out = []
    for raw in text.splitlines():
        if raw.startswith("#"):          # comments and #! cache directives
            continue
        m = PARTIAL_RE.match(raw)
        if m:
            lp = local_path(m.group(1))
            secs = int(m.group(2) or 0)
            fields = parse_fields(m.group(3))
            if lp and PAGE_RE.match(lp) and depth < 2:
                name = PAGE_RE.match(lp).group(1)
                body = to_html(run_page(name, fields, served=False) or "", depth + 1)
                out.append('<div class="partial" data-src="%s" data-int="%d">%s</div>'
                           % (html.escape(href(lp, fields)), secs, body))
            continue
        if raw.startswith(">"):
            lvl = len(raw) - len(raw.lstrip(">"))
            h, _, _ = convert_line(raw[lvl:], Style(), "l")
            out.append("<h1>%s</h1>" % h)
            continue
        if raw.strip() == "-" or (raw.startswith("-") and len(raw) == 2):
            out.append("<hr>")
            continue
        h, align, la = convert_line(raw, st, align)
        cls = "ln" + ("" if la == "l" else " " + la)
        out.append('<div class="%s">%s</div>' % (cls, h))
    return "".join(out)


class Handler(BaseHTTPRequestHandler):
    server_version = "muweb/1"

    def log_message(self, fmt, *args):
        pass

    def send(self, code, body, ctype="text/html; charset=utf-8"):
        b = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(b)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(b)

    def do_GET(self):
        u = urllib.parse.urlsplit(self.path)
        if u.path in ("/", "/index.html"):
            self.send_response(302)
            self.send_header("Location", "/page/index.mu")
            self.end_headers()
            return
        m = PAGE_RE.match(u.path)
        if not m:
            self.send(404, "not found", "text/plain")
            return
        q = dict(urllib.parse.parse_qsl(u.query))
        frag = q.pop("frag", None) == "1"
        text = run_page(m.group(1), q, served=not frag)
        if text is None:
            self.send(404, "no such page", "text/plain")
            return
        body = to_html(text)
        if frag:
            self.send(200, body)
            return
        self.send(200, "<!doctype html><html><head><meta charset=utf-8>"
                  "<meta name=viewport content='width=device-width,initial-scale=1'>"
                  "<title>%s</title><style>%s</style></head><body><div class=mu>%s</div>"
                  "<script>%s</script></body></html>" % (html.escape(TITLE), CSS, body, JS))


def load_local_hash():
    try:
        return open(os.environ.get("MUWEB_NODEHASH", "")).read().strip()
    except OSError:
        return ""


LOCAL_HASH = load_local_hash()

if __name__ == "__main__":
    ThreadingHTTPServer.daemon_threads = True
    srv = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    print("muweb serving %s on :%d" % (PAGES, PORT), file=sys.stderr, flush=True)
    srv.serve_forever()
