import os
import socket

DEFAULT_PORT = 8000
LAN_IP_ENV = "LANQ_LAN_IP"
PORT_ENV = "LANQ_PORT"


def detect_lan_ip() -> str:
    override = os.environ.get(LAN_IP_ENV, "").strip()
    if override:
        return override
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
            probe.connect(("192.0.2.1", 9))
            address = probe.getsockname()[0]
        if not address.startswith("127."):
            return address
    except OSError:
        pass
    try:
        address = socket.gethostbyname(socket.gethostname())
        if not address.startswith("127."):
            return address
    except OSError:
        pass
    return "127.0.0.1"


def server_port() -> int:
    raw = os.environ.get(PORT_ENV, "").strip()
    if not raw:
        return DEFAULT_PORT
    try:
        port = int(raw)
    except ValueError:
        return DEFAULT_PORT
    if not 0 < port < 65536:
        return DEFAULT_PORT
    return port


def join_url() -> str:
    return f"http://{detect_lan_ip()}:{server_port()}/"
