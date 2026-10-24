#!/bin/bash
# install.sh — ct168-rak4631: rnsd + MeshChat + landing / terminal / services
# Unprivileged Debian 13 LXC on x12-4, RAK4631 RNode at /dev/rak/rak4631
# (bind-mounted from the host, see host/setup-host.sh).
#
# Run IN THE CONTAINER as root from the unpacked repo (deploy.sh does this):
#   bash /home/user/ct168-rak4631/install.sh
#
# Idempotent: safe to re-run. Never overwrites ~/.reticulum/config or
# ~/.config/meshchat.env once they exist (edit those from the landing page).
# Then run install-nomadnet.sh for NomadNet, its web pages and the LoRa map.

set -euo pipefail

# ── Settings ─────────────────────────────────────────────────────────────────
U=user
H=/home/$U
APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV=$H/meshchat-venv
MC_DIR=$H/reticulum-meshchat
MC_REPO=https://github.com/liamcottle/reticulum-meshchat.git
MC_COMMIT=df5aea94eab7      # v2.4.0 + "Stop message progress loop when message is rejected"
PY_PINS=(rns==1.3.7 lxmf==1.0.1 aiohttp==3.13.3 websockets==16.0 "peewee>=3.18.1,<4.0.0" msgpack)
RNODE_PORT=/dev/rak/rak4631

[ "$(id -u)" -eq 0 ] || { echo "Run as root"; exit 1; }
[ "$APP_DIR" = "$H/ct168-rak4631" ] || { echo "Unpack the repo to $H/ct168-rak4631 first"; exit 1; }

as_user() { runuser -u "$U" -- "$@"; }

# ── 1. Packages ──────────────────────────────────────────────────────────────
echo "[1/8] Installing system packages"
export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y python3-venv python3-dev build-essential git curl ca-certificates \
    locales nano

# ── 2. System tweaks ─────────────────────────────────────────────────────────
echo "[2/8] User, locales, journal size"
if ! id "$U" >/dev/null 2>&1; then
    useradd -m -s /bin/bash "$U"
fi
chown "$U:$U" "$H"
usermod -aG dialout "$U"
# Same SSH key as root, so ssh user@ct168 works too
install -d -o "$U" -g "$U" -m 700 "$H/.ssh"
install -o "$U" -g "$U" -m 600 /root/.ssh/authorized_keys "$H/.ssh/authorized_keys"

# SSH from the desktop forwards LANG/LC_* (de_DE + en_US): generate them so
# logins and perl/apt don't warn "cannot change locale"
sed -i -E 's/^# *(de_DE.UTF-8 UTF-8|en_GB.UTF-8 UTF-8|en_US.UTF-8 UTF-8)/\1/' /etc/locale.gen
locale-gen >/dev/null

# Debian 13 template: wtmpdb moved rotation to logrotate, but the template's
# enablement symlink survives and leaves the CT "degraded" after an upgrade
rm -f /etc/systemd/system/timers.target.wants/wtmpdb-rotate.timer

mkdir -p /etc/systemd/journald.conf.d
cat > /etc/systemd/journald.conf.d/50-ct168-size.conf << 'EOT'
[Journal]
SystemMaxUse=100M
EOT
systemctl restart systemd-journald

# ── 3. Python venv (shared by rnsd, MeshChat and the web servers) ────────────
echo "[3/8] Python venv $VENV"
[ -x "$VENV/bin/python" ] || as_user python3 -m venv "$VENV"
as_user "$VENV/bin/pip" install --upgrade pip
as_user "$VENV/bin/pip" install "${PY_PINS[@]}"
as_user sh -c "'$VENV/bin/pip' freeze > '$H/requirements.lock.txt'"

# ── 4. MeshChat, pinned commit ───────────────────────────────────────────────
echo "[4/8] MeshChat $MC_COMMIT"
if [ ! -d "$MC_DIR/.git" ]; then
    as_user git clone "$MC_REPO" "$MC_DIR"
fi
as_user git -C "$MC_DIR" fetch --quiet origin
as_user git -C "$MC_DIR" checkout --quiet "$MC_COMMIT"

# Build only the frontend (build-frontend, NOT build: that also runs the
# cx_freeze desktop build). Node is removed again afterwards.
MARK="$MC_DIR/.ct168-built"
if [ ! -f "$MC_DIR/public/index.html" ] || [ "$(cat "$MARK" 2>/dev/null)" != "$MC_COMMIT" ]; then
    NODE_WAS_INSTALLED=1
    dpkg -s nodejs >/dev/null 2>&1 || NODE_WAS_INSTALLED=0
    apt-get install -y nodejs npm
    as_user sh -c "cd '$MC_DIR' && npm ci && npm run build-frontend"
    rm -rf "$MC_DIR/node_modules"
    echo "$MC_COMMIT" > "$MARK"
    chown "$U:$U" "$MARK"
    if [ "$NODE_WAS_INSTALLED" = 0 ]; then
        apt-get purge -y nodejs npm
        apt-get autoremove -y
    fi
else
    echo "     frontend already built for $MC_COMMIT"
fi
apt-get clean

# ── 5. Reticulum config (only if missing) ────────────────────────────────────
echo "[5/8] Reticulum config"
as_user mkdir -p "$H/.reticulum" "$H/.config" "$H/meshchat-storage"
if [ ! -f "$H/.reticulum/config" ]; then
    sed "s|@RNODE_PORT@|$RNODE_PORT|" "$APP_DIR/config/reticulum.config" > "$H/.reticulum/config"
    chown "$U:$U" "$H/.reticulum/config"
    echo "     written with port $RNODE_PORT"
else
    echo "     exists — left unchanged"
fi
[ -e "$RNODE_PORT" ] || echo "     WARNING: $RNODE_PORT missing — RAK4631 not plugged into x12-4?"
if [ ! -f "$H/.config/meshchat.env" ]; then
    install -o "$U" -g "$U" -m 644 "$APP_DIR/config/meshchat.env" "$H/.config/meshchat.env"
fi

# ── 6. systemd units ─────────────────────────────────────────────────────────
echo "[6/8] systemd units"
UNITS=(rnsd meshchat ct168-landing ct168-terminal ct168-services)
for u in "${UNITS[@]}"; do
    install -m 644 "$APP_DIR/systemd/$u.service" "/etc/systemd/system/$u.service"
done
systemctl daemon-reload
systemctl enable "${UNITS[@]}"

# ── 7. (Re)start ─────────────────────────────────────────────────────────────
echo "[7/8] Starting services"
chown -R "$U:$U" "$APP_DIR"
systemctl restart rnsd
systemctl restart meshchat ct168-landing ct168-terminal ct168-services || true

# ── 8. Summary ───────────────────────────────────────────────────────────────
sleep 5
echo "[8/8] Status"
for u in "${UNITS[@]}"; do printf '     %-16s %s\n' "$u" "$(systemctl is-active "$u" || true)"; done
echo
ETH_IP=$(ip -4 -o addr show eth0 2>/dev/null | awk '{print $4}' | cut -d/ -f1)
echo "  Landing   http://$ETH_IP/"
echo "  MeshChat  port 8000 (first start can take a minute)"
echo
echo "  Back up the LXMF identity once MeshChat has created it:"
echo "    $H/meshchat-storage/identity"
echo
echo "  Next: ./deploy.sh $ETH_IP install-nomadnet.sh"
