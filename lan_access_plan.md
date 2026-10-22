# LAN Access Plan

## Goal

Allow phones or other devices on the same Wi-Fi network to open the Game Launch Loop web UI.

Local-only URL:

```text
http://127.0.0.1:20731
```

LAN URL example:

```text
http://192.168.90.68:20731
```

## Start Command

Use `0.0.0.0` so the Python server listens on all network interfaces:

```bash
python3 src/web_input_server.py --host 0.0.0.0 --port 20731
```

Then open this on the phone:

```text
http://192.168.90.68:20731
```

## Python Implementation

Use Python standard library only.

The server should continue using:

```python
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
```

Implementation idea:

```python
server = ThreadingHTTPServer((args.host, args.port), WebInputHandler)
server.serve_forever()
```

When `--host 0.0.0.0` is used, show both local and LAN URLs:

```text
Local: http://127.0.0.1:20731
LAN:   http://192.168.90.68:20731
```

LAN IP detection can use a UDP socket trick without sending real data:

```python
import socket

def get_lan_ip():
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.connect(("8.8.8.8", 80))
        return sock.getsockname()[0]
```

Fallback behavior:

- If LAN IP detection fails, show only the local URL.
- If the port is already in use, print a clear error and suggest another port.
- Keep `--no-browser` available for scheduled or LAN mode.

## Security Notes

- Only use this on trusted Wi-Fi.
- Anyone on the same network who can reach the URL can trigger launch runs.
- `GET /api/config` must not return `x_api_key` or `x_api_secret`.
- Prefer keeping the default host as `127.0.0.1`; use `--host 0.0.0.0` only when phone access is needed.

## Future: VPN Status Badge

Add a small HTML badge that shows:

```text
VPN: Connected
VPN: Disconnected
VPN: Unknown
```

Recommended first-layer approach:

- Python backend adds `GET /api/vpn-status`.
- Frontend calls `/api/vpn-status` when the page loads.
- Backend checks macOS network interfaces for VPN-like names such as `utun`, `ppp`, or `tun`.
- Frontend displays the result near the topbar or Run Status area.
- This should be a warning-only signal, not a blocker for launch runs.

Python implementation idea:

```python
import subprocess

def detect_vpn_status():
    completed = subprocess.run(
        ["ifconfig"],
        text=True,
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0:
        return {
            "status": "unknown",
            "reason": "Unable to read network interfaces",
        }

    vpn_interfaces = []
    for line in completed.stdout.splitlines():
        if line and not line.startswith("\t") and ":" in line:
            interface_name = line.split(":", 1)[0]
            if interface_name.startswith(("utun", "ppp", "tun")):
                vpn_interfaces.append(interface_name)

    if vpn_interfaces:
        return {
            "status": "connected",
            "reason": f"Detected VPN-like interface: {', '.join(vpn_interfaces)}",
        }

    return {
        "status": "disconnected",
        "reason": "No VPN-like network interface detected",
    }
```

Notes:

- Cost is low because it only needs one backend endpoint and a small frontend badge.
- Accuracy is good enough for a reminder, but not perfect.
- Some macOS tools can create `utun` interfaces even when the company VPN is not connected.
- Later improvement: combine this with a VPN-only endpoint check for higher accuracy.
