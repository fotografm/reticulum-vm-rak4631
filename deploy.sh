#!/bin/bash
# deploy.sh — copy this repo into ct168 and run a script there (as root).
# Run on the desktop:  ./deploy.sh [ct-ip] [script]
#   ./deploy.sh                                      base install (install.sh)
#   ./deploy.sh 192.168.177.168 install-nomadnet.sh  NomadNet + muweb + LoRa map
# Create the container first with ./deploy-host.sh.
set -euo pipefail

CT=${1:-192.168.177.168}
SCRIPT=${2:-install.sh}
[ -f "$(dirname "$0")/$SCRIPT" ] || { echo "No such script: $SCRIPT"; exit 1; }
cd "$(dirname "$0")"

TAR=$(mktemp --suffix=.tar.gz)
trap 'rm -f "$TAR"' EXIT
tar --exclude=.git -czf "$TAR" .

scp "$TAR" "root@$CT:/tmp/ct168-rak4631.tar.gz"
ssh "root@$CT" 'mkdir -p /home/user/ct168-rak4631 && tar -xzf /tmp/ct168-rak4631.tar.gz -C /home/user/ct168-rak4631 && rm /tmp/ct168-rak4631.tar.gz'
ssh -t "root@$CT" "bash /home/user/ct168-rak4631/$SCRIPT"
