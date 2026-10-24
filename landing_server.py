#!/usr/bin/env python3
"""
landing_server.py  —  ct168-rak4631 (x12-4 LXC, RAK4631 RNode)
aiohttp landing page server (port 80).
Serves:
  /               — landing.html
  /rnstatus       — rnstatus.html (interface status page)
  /static/...     — style.css etc.
  /api/sysinfo    — uptime, CPU, RAM, disk, clock, IP (JSON)
  /api/status     — rnsd / meshchat / nomadnet state, RNode interface stats (JSON)
  /api/rnstatus   — plain `rnstatus -a` text
Requires AmbientCapabilities=CAP_NET_BIND_SERVICE in systemd service.

Copied from raspi84 reticulum-cyberdeck; Pi-only readings (CPU temp,
under-voltage, hotspot clients, NTP) dropped: the clock is x12-4's.
"""

import asyncio
import json
import logging
import os
import re
import subprocess
import time
from pathlib import Path

from aiohttp import web

APP_DIR  = Path.home() / 'ct168-rak4631'
TMPL_DIR = APP_DIR / 'templates'
VENV_BIN = Path.home() / 'meshchat-venv' / 'bin'
PORT     = 80

ANSI_RE = re.compile(r'\x1b\[[0-9;]*[A-Za-z]')

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [landing] %(levelname)s %(message)s',
    datefmt='%Y-%m-%dT%H:%M:%S',
)
log = logging.getLogger('landing')


def _run(cmd, timeout=5) -> str:
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return r.stdout
    except Exception:
        return ''


def _ipv4(ifname: str):
    out = _run(['ip', '-4', '-o', 'addr', 'show', ifname])
    m = re.search(r'inet (\d+\.\d+\.\d+\.\d+)', out)
    return m.group(1) if m else None


def _get_sysinfo() -> dict:
    try:
        with open('/proc/uptime') as f:
            uptime_s = float(f.read().split()[0])
        days  = int(uptime_s // 86400)
        hours = int((uptime_s % 86400) // 3600)
        mins  = int((uptime_s % 3600) // 60)
        if days:
            uptime_str = f'{days}d {hours}h {mins}m'
        elif hours:
            uptime_str = f'{hours}h {mins}m'
        else:
            uptime_str = f'{mins}m'
    except Exception:
        uptime_str = '—'

    try:
        with open('/proc/stat') as f:
            line = f.readline()
        vals = list(map(int, line.split()[1:]))
        idle = vals[3]
        total = sum(vals)
        time.sleep(0.1)
        with open('/proc/stat') as f:
            line = f.readline()
        vals2 = list(map(int, line.split()[1:]))
        d_idle  = vals2[3] - idle
        d_total = sum(vals2) - total
        cpu_pct = round(100 * (1 - d_idle / d_total)) if d_total else 0
    except Exception:
        cpu_pct = 0

    try:
        with open('/proc/meminfo') as f:
            lines = f.readlines()
        mem = {}
        for line in lines:
            k, v = line.split(':')
            mem[k.strip()] = int(v.split()[0])
        total_mb = mem['MemTotal'] // 1024
        avail_mb = mem['MemAvailable'] // 1024
        used_mb  = total_mb - avail_mb
    except Exception:
        total_mb = used_mb = 0

    try:
        st = os.statvfs('/home/user')
        disk_total_mb = (st.f_blocks * st.f_frsize) // (1024 * 1024)
        disk_free_mb  = (st.f_bavail * st.f_frsize) // (1024 * 1024)
        disk_used_mb  = disk_total_mb - disk_free_mb
    except Exception:
        disk_total_mb = disk_used_mb = 0

    return {
        'uptime':        uptime_str,
        'cpu_pct':       cpu_pct,
        'ram_used_mb':   used_mb,
        'ram_total_mb':  total_mb,
        'disk_used_mb':  disk_used_mb,
        'disk_total_mb': disk_total_mb,
        'epoch_ms':      int(time.time() * 1000),
        'eth_ip':        _ipv4('eth0'),
    }


# rnstatus takes about a second; several open tabs share one result.
_cache = {}


def _cached(key, ttl, fn):
    now = time.monotonic()
    hit = _cache.get(key)
    if hit and now - hit[0] < ttl:
        return hit[1]
    val = fn()
    _cache[key] = (now, val)
    return val


def _get_status() -> dict:
    def svc(name):
        return _run(['systemctl', 'is-active', name]).strip() or 'unknown'

    rnode = None
    out = _run([str(VENV_BIN / 'rnstatus'), '-j'], timeout=10)
    try:
        stats = json.loads(out[out.index('{'):])
        for i in stats.get('interfaces', []):
            if i.get('type') == 'RNodeInterface':
                rnode = {
                    'name':         i.get('short_name') or i.get('name'),
                    'up':           bool(i.get('status')),
                    'noise_floor':  i.get('noise_floor'),
                    'channel_load': i.get('channel_load_short'),
                    'airtime':      i.get('airtime_short'),
                    'rxb':          i.get('rxb'),
                    'txb':          i.get('txb'),
                }
                break
    except Exception:
        pass

    return {'rnsd': svc('rnsd'), 'meshchat': svc('meshchat'),
            'nomadnet': svc('nomadnet'), 'rnode': rnode}


def _get_rnstatus_text() -> str:
    out = _run([str(VENV_BIN / 'rnstatus'), '-a'], timeout=10)
    return ANSI_RE.sub('', out) or 'No output — is rnsd running?\n'


async def handle_landing(req: web.Request) -> web.Response:
    text = (TMPL_DIR / 'landing.html').read_text()
    return web.Response(text=text, content_type='text/html')


async def handle_rnstatus_page(req: web.Request) -> web.Response:
    text = (TMPL_DIR / 'rnstatus.html').read_text()
    return web.Response(text=text, content_type='text/html')


async def handle_sysinfo(req: web.Request) -> web.Response:
    loop = asyncio.get_event_loop()
    info = await loop.run_in_executor(None, _get_sysinfo)
    return web.json_response(info)


async def handle_status(req: web.Request) -> web.Response:
    loop = asyncio.get_event_loop()
    data = await loop.run_in_executor(None, _cached, 'status', 4, _get_status)
    return web.json_response(data)


async def handle_rnstatus_text(req: web.Request) -> web.Response:
    loop = asyncio.get_event_loop()
    text = await loop.run_in_executor(None, _cached, 'rnstatus', 4, _get_rnstatus_text)
    return web.Response(text=text, content_type='text/plain')


def build_app() -> web.Application:
    app = web.Application()
    app.router.add_get('/', handle_landing)
    app.router.add_get('/rnstatus', handle_rnstatus_page)
    app.router.add_get('/api/sysinfo', handle_sysinfo)
    app.router.add_get('/api/status', handle_status)
    app.router.add_get('/api/rnstatus', handle_rnstatus_text)
    app.router.add_static('/static', APP_DIR / 'static')
    return app


if __name__ == '__main__':
    log.info('Landing server starting on port %d', PORT)
    web.run_app(build_app(), host='0.0.0.0', port=PORT, access_log=None)
