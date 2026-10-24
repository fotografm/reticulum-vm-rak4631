# ct168-rak4631

Reticulum LoRa node in the white box: a **RAK4631 WisBlock RNode** (behind
an 868 MHz filter) on USB of **x12-4** (t6), run by an unprivileged Debian 13
container **ct168-rak4631, 192.168.177.168**.

rnsd owns the radio. MeshChat, NomadNet and the LoRa map are shared-instance
clients of rnsd. Landing page and tools are copied from raspi84
(`reticulum-cyberdeck`), minus the Pi-only parts (hotspot, clock sync, CPU
temperature / under-voltage, OpenWebRX+).

| Port | What |
|---|---|
| 80 | Landing page: status badges + buttons |
| 8000 | MeshChat (LXMF messaging) |
| 8085 | rns-map LoRa dartboard, `/api/nodes` for map.mu |
| 8090 | NomadNet pages as HTML (muweb, the SAME page files NomadNet serves) |
| 8096 | Terminal (shell as `user`) |
| 8098 | Services start/stop/restart, rnsd + MeshChat config editors, CT restart/stop |

Landing buttons: MeshChat, LoRa map, rnstatus, NomadNet pages, Terminal,
Services, rnsd config, MeshChat config; Restart / Power off (= the container).

```
 x12-4 host                          ct168-rak4631 (LXC)
 RAK4631 ─USB─ udev ─ /dev/ct168-rak/rak4631 ══bind══ /dev/rak/rak4631
                                                       │
                                                     rnsd (shared instance, transport ON)
                                                       ├─ MeshChat :8000
                                                       ├─ nomadnet  ── muweb :8090 (same pages)
                                                       └─ rns-map  :8085
```

## Radio

- RNode firmware 1.86 `rnode_firmware_rak4631.zip`, SX1262, max 22 dBm.
- NL parameters: **869.463 MHz / 125 kHz / SF8 / CR5**, txpower 22,
  airtime limits 10 % long / 33 % short. `mode = full`, transport ON.
- **RNode only**: no AutoInterface, no TCP.

## Install / rebuild

From the desktop, in this repo:

```
./deploy-host.sh                        # x12-4: udev + create ct168 + passthrough
./deploy.sh                             # ct168: rnsd, MeshChat, landing/terminal/services
./deploy.sh 192.168.177.168 install-nomadnet.sh   # NomadNet, muweb :8090, rns-map
```

All three are idempotent. install.sh never overwrites `~/.reticulum/config`
or `~/.config/meshchat.env`; install-nomadnet.sh never overwrites
`~/.nomadnetwork/config` or the index page text. Page scripts are always
refreshed. Restore the identities (below) BEFORE the first start of
MeshChat / NomadNet when rebuilding, or they get new addresses.

## RAK4631 passthrough (host side)

The nRF52840 has native USB and **re-enumerates on every reset** (ttyACM0 →
ttyACM1). Proxmox `dev0:` passes only the node that existed at CT start and
refuses to start the CT when the device is missing, so it is not used.

- `/etc/udev/rules.d/99-ct168-rak4631.rules` matches 239a:8029 (RNode app,
  not the 239a:0029 bootloader) + USB serial `A1D903F3105B7AFC`, and runs
  `/usr/local/sbin/ct168-rak-node`, which recreates
  `/dev/ct168-rak/rak4631` with the current major:minor, owner
  100000:100020 (= root:dialout in the CT), mode 660.
- `/etc/tmpfiles.d/ct168-rak.conf` recreates `/dev/ct168-rak` at boot.
- **Not /run:** host `/run` is mounted `nodev` and the bind mount inherits it,
  so even root in the CT gets "Permission denied" on the node. `/dev`
  (devtmpfs) has no nodev.
- `/etc/pve/lxc/168.conf`:
  ```
  lxc.cgroup2.devices.allow: c 166:* rwm
  lxc.mount.entry: /dev/ct168-rak dev/rak none bind,optional,create=dir 0 0
  ```
  The DIRECTORY is bind-mounted, so a node recreated after a replug is seen
  in the CT at once. rnsd retries the port every few seconds.
- A different RAK board: change `RAK_SERIAL` in `host/setup-host.sh`, rerun
  `./deploy-host.sh`.

## rnsd start-up race (fixed in rnsd.service)

Anything that runs `rnstatus` while rnsd is starting (MeshChat's wait loop,
the landing page's 5 s poll) can briefly become the shared instance itself;
rnsd then logs "connected to another shared local instance" and runs as a
client that never opens the radio. `ExecStartPost` waits until
`ss -xlpn` shows `@rns/default` owned by rnsd's `$MAINPID`, and fails the
start (→ restart) otherwise.

## Addresses and identities

| What | Address |
|---|---|
| MeshChat identity | `140882154c513a24489faabaeb8d1b21` (`~/meshchat-storage/identity`) |
| NomadNet node | `bc6855d8b192aa21324db080135156d8` (`~/.nomadnetwork/storage/identity`) |
| NomadNet chat (LXMF, unused) | `5615937e0d202d34fc30a692b0ddd01e`, display name `dummy-ignore` |
| MeshChat chat (LXMF) | `575beac8c831dc9c320a35c484094e9b` |

NomadNet's own chat address is unused (MeshChat is the messenger). Unnamed
it shows as "Anonymous Peer", so it is named `dummy-ignore` (key
`display_name` in `storage/peersettings`, msgpack, edit only while nomadnet
is stopped) and was announced once via `[client] announce_at_start = yes`
for one start, then back to `no`. Same as raspi84 and vm169.

Backups on the desktop: `~/Notes/backups/ct168/` (copied with `scp -p`: the
identity file's mtime is the "since" date on the index page).

## Files in the container

| Path | What |
|---|---|
| `~/ct168-rak4631/` | this repo (servers, templates, static, muweb) |
| `~/meshchat-venv/` | rnsd + MeshChat + web servers (rns 1.3.7, lxmf 1.0.1) |
| `~/reticulum-meshchat/` | MeshChat at `df5aea94eab7` + built `public/` |
| `~/nomadnet-env/` | NomadNet 1.4.4 / lxmf 1.2.1 / rns 1.5.7 |
| `~/rns-map/` | rns-map code, venv, `nodes.db` |
| `~/muweb/muweb.py` | Micron → HTML server (Loc2's, md5 bc54b445…) |
| `~/.reticulum/config` | rnsd config |
| `~/.config/meshchat.env` | MeshChat start-up options |
| `~/.nomadnetwork/` | NomadNet config, identity, `storage/pages/`, `storage/pagetext/index.body.mu` |

## License

MIT
