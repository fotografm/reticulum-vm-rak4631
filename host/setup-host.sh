#!/bin/bash
# setup-host.sh — run ON x12-4 as root (deploy-host.sh on the desktop does this).
#
# 1. udev rule + helper: the RAK4631 RNode gets a stable device node in
#    /run/ct168-rak/, which is bind-mounted into ct168 at /dev/rak.
# 2. Creates ct168-rak4631 (unprivileged Debian 13) if it does not exist yet.
# 3. Adds the RAK passthrough lines to /etc/pve/lxc/168.conf and starts it.
#
# Why not Proxmox "dev0:"? The nRF52 re-enumerates on every reset (ttyACM0 ->
# ttyACM1), dev0 only passes the node that existed when the CT started, and
# Proxmox refuses to start the CT at all when the device is missing.
#
# Idempotent: an existing ct168 is left as it is apart from the two lxc lines.
#   bash setup-host.sh <ssh-pubkey-file>

set -euo pipefail

CTID=168
NAME=ct168-rak4631
IP=192.168.177.168/24
GW=192.168.177.1
TEMPLATE=local:vztmpl/debian-13-standard_13.6-1_amd64.tar.zst
RAK_SERIAL=A1D903F3105B7AFC    # USB serial of this RAK4631 (lsusb -v / udevadm info)
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PUBKEY=${1:-}

[ "$(id -u)" -eq 0 ] || { echo "Run as root"; exit 1; }

# ── 1. udev ──────────────────────────────────────────────────────────────────
echo "[1/3] udev rule for RAK4631 $RAK_SERIAL"
install -m 755 "$HERE/ct168-rak-node" /usr/local/sbin/ct168-rak-node
# 239a:8029 = RNode firmware running. The bootloader (239a:0029) is ignored.
cat > /etc/udev/rules.d/99-ct168-rak4631.rules << EOF
# RAK4631 RNode for ct168 — see /usr/local/sbin/ct168-rak-node
ACTION=="add", SUBSYSTEM=="tty", ENV{ID_VENDOR_ID}=="239a", ENV{ID_MODEL_ID}=="8029", ENV{ID_SERIAL_SHORT}=="$RAK_SERIAL", RUN+="/usr/local/sbin/ct168-rak-node add %M %m"
ACTION=="remove", SUBSYSTEM=="tty", ENV{ID_VENDOR_ID}=="239a", ENV{ID_MODEL_ID}=="8029", ENV{ID_SERIAL_SHORT}=="$RAK_SERIAL", RUN+="/usr/local/sbin/ct168-rak-node remove"
EOF
# /run is empty after a host reboot: recreate the directory before CTs start
echo 'd /run/ct168-rak 0755 root root -' > /etc/tmpfiles.d/ct168-rak.conf
systemd-tmpfiles --create /etc/tmpfiles.d/ct168-rak.conf
udevadm control --reload
udevadm trigger --action=add --subsystem-match=tty
udevadm settle
if [ -e /run/ct168-rak/rak4631 ]; then
    echo "     RAK4631 present: $(ls -l /run/ct168-rak/rak4631)"
else
    echo "     RAK4631 not plugged in (or not running RNode firmware) — node appears when it is"
fi

# ── 2. Container ─────────────────────────────────────────────────────────────
echo "[2/3] Container $CTID"
if pct status $CTID >/dev/null 2>&1; then
    echo "     exists — left unchanged"
else
    [ -f "$PUBKEY" ] || { echo "Need an SSH public key file for a new CT"; exit 1; }
    ping -c1 -W1 "${IP%/*}" >/dev/null 2>&1 && { echo "${IP%/*} answers ping — in use?"; exit 1; }
    pct create $CTID "$TEMPLATE" \
        --hostname $NAME --ostype debian --unprivileged 1 --features nesting=1 \
        --cores 1 --memory 1024 --swap 512 --rootfs local:8 \
        --net0 name=eth0,bridge=vmbr0,firewall=1,gw=$GW,ip=$IP,type=veth \
        --nameserver $GW --onboot 1 --ssh-public-keys "$PUBKEY" \
        --description "RAK4631 RNode in the white box (868 MHz filter). rnsd owns the radio; MeshChat :8000, NomadNet + web :8090, LoRa map :8085, landing :80. Repo/playbook ct168-rak4631."
fi

# ── 3. RAK passthrough lines ─────────────────────────────────────────────────
echo "[3/3] Passthrough lines in /etc/pve/lxc/$CTID.conf"
CONF=/etc/pve/lxc/$CTID.conf
# 166 = ttyACM major. "optional": the CT still starts if /run/ct168-rak is missing.
for line in 'lxc.cgroup2.devices.allow: c 166:* rwm' \
            'lxc.mount.entry: /run/ct168-rak dev/rak none bind,optional,create=dir 0 0'; do
    grep -qxF "$line" "$CONF" || echo "$line" >> "$CONF"
done
grep '^lxc\.' "$CONF" | sed 's/^/     /'

if [ "$(pct status $CTID)" != "status: running" ]; then
    pct start $CTID
    sleep 5
fi
pct status $CTID
pct exec $CTID -- ls -l /dev/rak/ 2>/dev/null || echo "     /dev/rak empty in the CT (RAK not plugged in)"
