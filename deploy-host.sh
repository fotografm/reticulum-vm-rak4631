#!/bin/bash
# deploy-host.sh — copy host/ to x12-4 and run setup-host.sh there (as root).
# Run on the desktop:  ./deploy-host.sh [x12-4-ip] [ssh-pubkey]
# Creates ct168 if missing and sets up the RAK4631 udev passthrough.
set -euo pipefail

HOST=${1:-192.168.177.20}
KEY=${2:-$HOME/.ssh/id_ed25519.pub}
cd "$(dirname "$0")"
[ -f "$KEY" ] || { echo "No such key: $KEY"; exit 1; }

ssh "root@$HOST" 'mkdir -p /root/ct168-host'
scp host/* "$KEY" "root@$HOST:/root/ct168-host/"
ssh "root@$HOST" "bash /root/ct168-host/setup-host.sh /root/ct168-host/$(basename "$KEY")"
