#!/usr/bin/python3
import subprocess, datetime, re

now_str = datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')

print("`l`Ffd0Reticulum Status (ct168):`f")
print("`F0f2━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
print(f"`Ffd0Time:`f      `F0f2{now_str}")
print("`F0f2━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")

output = subprocess.getoutput("/home/user/meshchat-venv/bin/rnstatus")

for line in output.split('\n'):
    line = line.strip()
    if not line:
        continue
    if '---' in line or '===' in line:
        print("`F0f2━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    elif re.match(r'^(Shared Instance|RNodeInterface|BackboneInterface|AutoInterface|AutoInterfacePeer|TCPInterface|UDPInterface)\[', line):
        iface_parts = line.split('[', 1)
        iface_type = iface_parts[0]
        iface_name = iface_parts[1].rstrip(']') if len(iface_parts) > 1 else ''
        print()
        print(f"`Ffd0{iface_type}: `F0f2{iface_name}`f")
    elif ':' in line:
        parts = line.split(':', 1)
        label = parts[0].strip()
        value = parts[1].strip()
        pad = ' ' * (9 - len(label))
        if label == 'Status':
            colour = '`F0f2' if value == 'Up' else '`Ff00'
        elif label in ('Traffic', 'Rate', 'Announces'):
            colour = '`F0fd'
        elif label == 'Mode':
            colour = '`Ffd0'
        else:
            colour = '`F0fd'
        print(f"  `F888{label}:`f{pad}  {colour}{value}`f")
    elif line.startswith('Transport Instance'):
        print()
        print(f"`F0f2{line}`f")
    elif line.startswith('Uptime'):
        print(f"`Ffd0{line}`f")
    elif line.startswith('↓') or line.startswith('↑'):
        print(f"              `F0fd{line}`f")
    else:
        print(f"`F888{line}`f")

print()
print("`F0f2━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
print("`a")
