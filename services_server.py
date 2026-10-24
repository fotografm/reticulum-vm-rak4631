"""
services_server.py  —  ct168-rak4631 (x12-4 LXC, RAK4631 RNode)
Service control panel backend on port 8098.
Runs as root so it can call systemctl and stop/restart the container.

Copied from raspi84 reticulum-cyberdeck (browser time sync and the
hotspot / OpenWebRX+ rows dropped: the clock is x12-4's).

Endpoints:
  GET  /                            — serves services.html
  GET  /config/<key>                — serves editor.html (key: rnsd, meshchat)
  GET  /api/services                — status of all services
  POST /api/service/<name>/<action> — start | stop | restart
  GET  /api/config/<key>            — config file text
  POST /api/config/<key>            — save config (JSON: text, restart)
  POST /api/reboot                  — restart the container
  POST /api/shutdown                — stop the container (start it on x12-4)
"""

import asyncio
import logging
import os
import pwd
import shutil
import subprocess
import time
from pathlib import Path

from aiohttp import web

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [services] %(levelname)s %(message)s',
    datefmt='%Y-%m-%dT%H:%M:%S',
)
log = logging.getLogger('services')

PORT    = 8098
APP_DIR = Path('/home/user/ct168-rak4631')
USER    = 'user'

# ── Service definitions ───────────────────────────────────────────────────────
# start = enable --now, stop = disable --now (stays off after reboot, as on
# raspi81), restart = restart.

ALL_ACTIONS = ['start', 'stop', 'restart']

SERVICES = [
    {'name': 'rnsd',           'label': 'Reticulum rnsd (owns RAK4631)', 'port': None, 'actions': ALL_ACTIONS},
    {'name': 'meshchat',       'label': 'MeshChat',                      'port': 8000, 'actions': ALL_ACTIONS},
    {'name': 'nomadnet',       'label': 'NomadNet page server',          'port': None, 'actions': ALL_ACTIONS},
    {'name': 'nomadnet-web',   'label': 'NomadNet pages (web, muweb)',   'port': 8090, 'actions': ALL_ACTIONS},
    {'name': 'rns-map',        'label': 'RNS LoRa map',                  'port': 8085, 'actions': ALL_ACTIONS},
    {'name': 'ct168-terminal', 'label': 'Terminal Server',               'port': 8096, 'actions': ALL_ACTIONS},
    {'name': 'ct168-landing',  'label': 'Landing Page',                  'port': 80,   'actions': ALL_ACTIONS},
    {'name': 'ct168-services', 'label': 'Services Control (this page)',  'port': 8098, 'actions': []},
]
SVC_BY_NAME = {s['name']: s for s in SERVICES}

# ── Config files editable from the browser ────────────────────────────────────

CONFIGS = {
    'rnsd': {
        'label':    'Reticulum config (rnsd)',
        'path':     Path('/home/user/.reticulum/config'),
        'restart':  'rnsd',          # meshchat follows via PartOf=rnsd.service
        'validate': 'configobj',
    },
    'meshchat': {
        'label':    'MeshChat options',
        'path':     Path('/home/user/.config/meshchat.env'),
        'restart':  'meshchat',
        'validate': 'env',
    },
}
BACKUPS_KEPT = 10

# ── Helpers ───────────────────────────────────────────────────────────────────

def _svc_status(name: str) -> str:
    """Returns 'active', 'inactive', 'failed', 'activating' or 'unknown'."""
    try:
        r = subprocess.run(
            ['systemctl', 'is-active', name],
            capture_output=True, text=True, timeout=3
        )
        return r.stdout.strip() or 'unknown'
    except Exception:
        return 'unknown'


def _validate(cfg: dict, text: str):
    """Returns an error string, or None if the text is acceptable."""
    if cfg['validate'] == 'configobj':
        # Same parser rnsd uses; a parse error here would crash-loop rnsd.
        try:
            from RNS.vendor.configobj import ConfigObj
            c = ConfigObj(text.splitlines())
        except Exception as e:
            return f'Config does not parse: {e}'
        if 'reticulum' not in c or 'interfaces' not in c:
            return 'Missing [reticulum] or [interfaces] section'
        return None
    if cfg['validate'] == 'env':
        if not any(l.strip().startswith('MESHCHAT_ARGS=') for l in text.splitlines()):
            return 'MESHCHAT_ARGS= line is missing'
        return None
    return None


def _save_config(key: str, text: str) -> dict:
    cfg  = CONFIGS[key]
    path = cfg['path']
    err  = _validate(cfg, text)
    if err:
        return {'ok': False, 'message': err}

    if not text.endswith('\n'):
        text += '\n'
    pw = pwd.getpwnam(USER)

    if path.exists():
        stamp  = time.strftime('%Y%m%d-%H%M%S')
        backup = path.with_name(f'{path.name}.bak-{stamp}')
        shutil.copy2(path, backup)
        os.chown(backup, pw.pw_uid, pw.pw_gid)
        old = sorted(path.parent.glob(f'{path.name}.bak-*'))
        for b in old[:-BACKUPS_KEPT]:
            b.unlink(missing_ok=True)

    tmp = path.with_name(path.name + '.tmp')
    tmp.write_text(text)
    os.chown(tmp, pw.pw_uid, pw.pw_gid)
    os.chmod(tmp, 0o644)
    tmp.replace(path)
    log.info('Saved %s (%d bytes)', path, len(text))
    return {'ok': True, 'message': 'Saved'}


def json_resp(data, status=200):
    return web.json_response(data, status=status)


# ── Handlers ──────────────────────────────────────────────────────────────────

async def handle_root(request):
    path = APP_DIR / 'templates' / 'services.html'
    return web.Response(text=path.read_text(), content_type='text/html')


async def handle_editor(request):
    if request.match_info['key'] not in CONFIGS:
        raise web.HTTPNotFound()
    path = APP_DIR / 'templates' / 'editor.html'
    return web.Response(text=path.read_text(), content_type='text/html')


async def api_services(request):
    loop = asyncio.get_event_loop()
    result = []
    for svc in SERVICES:
        status = await loop.run_in_executor(None, _svc_status, svc['name'])
        result.append({**svc, 'status': status})
    return json_resp(result)


async def api_service_action(request):
    name   = request.match_info['name']
    action = request.match_info['action']
    svc    = SVC_BY_NAME.get(name)
    if not svc or action not in svc['actions']:
        return json_resp({'ok': False, 'message': 'Not allowed'}, 403)
    cmd = {
        'start':   ['systemctl', 'enable', '--now', name],
        'stop':    ['systemctl', 'disable', '--now', name],
        'restart': ['systemctl', 'restart', name],
    }[action]
    try:
        loop = asyncio.get_event_loop()
        r = await loop.run_in_executor(None, lambda: subprocess.run(
            cmd, capture_output=True, text=True, timeout=90))
        ok = r.returncode == 0
        log.info('%s %s → %s', action.upper(), name, 'ok' if ok else r.stderr.strip())
        return json_resp({'ok': ok, 'message': r.stderr.strip() or action + 'ed'})
    except Exception as e:
        return json_resp({'ok': False, 'message': str(e)}, 500)


async def api_config_get(request):
    key = request.match_info['key']
    cfg = CONFIGS.get(key)
    if not cfg:
        return json_resp({'ok': False, 'message': 'Unknown config'}, 404)
    try:
        text = cfg['path'].read_text()
    except FileNotFoundError:
        text = ''
    return json_resp({'ok': True, 'label': cfg['label'], 'path': str(cfg['path']),
                      'restart': cfg['restart'], 'text': text})


async def api_config_save(request):
    key = request.match_info['key']
    cfg = CONFIGS.get(key)
    if not cfg:
        return json_resp({'ok': False, 'message': 'Unknown config'}, 404)
    try:
        body = await request.json()
        text = str(body['text'])
    except Exception:
        return json_resp({'ok': False, 'message': 'Bad request'}, 400)

    loop   = asyncio.get_event_loop()
    result = await loop.run_in_executor(None, _save_config, key, text)
    if not result['ok'] or not body.get('restart'):
        return json_resp(result)

    svc = cfg['restart']
    r = await loop.run_in_executor(None, lambda: subprocess.run(
        ['systemctl', 'restart', svc], capture_output=True, text=True, timeout=90))
    if r.returncode != 0:
        return json_resp({'ok': False, 'message': f'Saved, but restart of {svc} failed: {r.stderr.strip()}'})
    log.info('Restarted %s after config save', svc)
    return json_resp({'ok': True, 'message': f'Saved and restarted {svc}'})


async def api_reboot(request):
    log.info('Reboot requested')
    subprocess.Popen(['systemctl', 'reboot'])
    return json_resp({'ok': True, 'message': 'Rebooting…'})


async def api_shutdown(request):
    log.info('Shutdown requested')
    subprocess.Popen(['systemctl', 'poweroff'])
    return json_resp({'ok': True, 'message': 'Shutting down…'})


# ── CORS + app ────────────────────────────────────────────────────────────────

@web.middleware
async def cors_mw(request, handler):
    if request.method == 'OPTIONS':
        return web.Response(headers={
            'Access-Control-Allow-Origin':  '*',
            'Access-Control-Allow-Methods': 'GET, POST, OPTIONS',
            'Access-Control-Allow-Headers': 'Content-Type',
        })
    resp = await handler(request)
    resp.headers['Access-Control-Allow-Origin'] = '*'
    return resp


def build_app():
    app = web.Application(middlewares=[cors_mw])
    app.router.add_get('/',                                  handle_root)
    app.router.add_get('/config/{key}',                      handle_editor)
    app.router.add_get('/api/services',                      api_services)
    app.router.add_post('/api/service/{name}/{action}',      api_service_action)
    app.router.add_get('/api/config/{key}',                  api_config_get)
    app.router.add_post('/api/config/{key}',                 api_config_save)
    app.router.add_post('/api/reboot',                       api_reboot)
    app.router.add_post('/api/shutdown',                     api_shutdown)
    app.router.add_static('/static', APP_DIR / 'static')
    return app


if __name__ == '__main__':
    log.info('Services server starting on port %d', PORT)
    web.run_app(build_app(), host='0.0.0.0', port=PORT, access_log=None)
