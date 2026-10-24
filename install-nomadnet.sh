#!/bin/bash
# install-nomadnet.sh — ct168-rak4631: NomadNet page server, web pages, LoRa map
# Kept separate from install.sh on purpose (shorter scripts fail less).
# Run IN THE CONTAINER as root after install.sh:
#   bash /home/user/ct168-rak4631/install-nomadnet.sh
# (deploy.sh does this with:  ./deploy.sh 192.168.177.168 install-nomadnet.sh)
#
# nomadnet and rns-map are clients of rnsd's shared instance; rnsd keeps the RNode.
#   nomadnet       pages index / rnstatus / sysinfo2 / map  (~/.nomadnetwork)
#   nomadnet-web   the SAME page files as HTML via muweb, http://<ct>:8090
#   rns-map        LoRa dartboard http://<ct>:8085, feeds /page/map.mu
#
# Idempotent. Writes ~/.nomadnetwork/config and the index page TEXT only if
# missing; the page scripts are always refreshed.

set -euo pipefail

U=user
H=/home/$U
APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
NN=$H/.nomadnetwork
NN_ENV=$H/nomadnet-env
MAP=$H/rns-map

[ "$(id -u)" -eq 0 ] || { echo "Run with sudo"; exit 1; }

# ── 1. Python venvs (same versions as vm169) ─────────────────────────────────
echo "[1/5] NomadNet + rns-map venvs"
[ -x $NN_ENV/bin/python ] || su - $U -c "python3 -m venv $NN_ENV"
su - $U -c "$NN_ENV/bin/pip install -q -U pip"
su - $U -c "$NN_ENV/bin/pip install -q nomadnet==1.4.4 lxmf==1.2.1 rns==1.5.7"

install -d -o $U -g $U $MAP $MAP/static
install -o $U -g $U -m 644 "$APP_DIR/rns-map/rns_map.py" $MAP/
install -o $U -g $U -m 644 "$APP_DIR/rns-map/static/index.html" $MAP/static/
[ -x $MAP/venv/bin/python ] || su - $U -c "python3 -m venv $MAP/venv"
su - $U -c "$MAP/venv/bin/pip install -q -U pip"
su - $U -c "$MAP/venv/bin/pip install -q rns==1.5.7 aiohttp==3.11.11 msgpack==1.1.2"

# ── 2. NomadNet config + pages ───────────────────────────────────────────────
echo "[2/5] NomadNet config and pages"
install -d -o $U -g $U $NN $NN/storage $NN/storage/pages $NN/storage/pagetext
if [ -e $NN/config ]; then
    echo "     config exists — left unchanged"
else
    install -o $U -g $U -m 644 "$APP_DIR/nomadnet/config" $NN/config
fi
if [ -e $NN/storage/pagetext/index.body.mu ]; then
    echo "     index text exists — left unchanged"
else
    install -o $U -g $U -m 644 "$APP_DIR/nomadnet/pagetext/index.body.mu" $NN/storage/pagetext/
fi
for p in "$APP_DIR"/nomadnet/pages/*.mu; do
    install -o $U -g $U -m 755 "$p" $NN/storage/pages/
done

# ── 3. muweb: NomadNet's own pages dir rendered as HTML ──────────────────────
echo "[3/5] muweb (NomadNet pages over HTTP, :8090)"
install -d -o $U -g $U $H/muweb
install -o $U -g $U -m 755 "$APP_DIR/muweb/muweb.py" $H/muweb/

# ── 4. Services ──────────────────────────────────────────────────────────────
echo "[4/5] systemd units"
for unit in nomadnet nomadnet-web rns-map; do
    install -m 644 "$APP_DIR/systemd/$unit.service" /etc/systemd/system/
done
systemctl daemon-reload
systemctl enable nomadnet nomadnet-web rns-map
systemctl restart nomadnet nomadnet-web rns-map

# ── 5. Landing + services pages ──────────────────────────────────────
echo "[5/5] Reloading landing + services pages"
chown -R "$U:$U" "$APP_DIR"
systemctl restart ct168-landing ct168-services

sleep 10
echo
for unit in rnsd meshchat nomadnet nomadnet-web rns-map; do
    printf '     %-13s %s\n' $unit "$(systemctl is-active $unit || true)"
done
NODE=$(su - $U -c "$NN_ENV/bin/python -c 'import RNS; print(RNS.prettyhexrep(RNS.Destination.hash(RNS.Identity.from_file(\"$NN/storage/identity\"), \"nomadnetwork\", \"node\")))'" 2>/dev/null || echo "not yet created")
echo
echo "  NomadNet node   $NODE"
echo "  Web pages       http://<ct>:8090/   (same files as NomadNet)"
echo "  LoRa map        http://<ct>:8085/   (NomadNet /page/map.mu)"
echo "  Page text       $NN/storage/pagetext/index.body.mu"
