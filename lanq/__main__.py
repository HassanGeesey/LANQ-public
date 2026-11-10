import uvicorn

from lanq.main import create_app
from lanq.network import detect_lan_ip, server_port

HOST = "0.0.0.0"


def main() -> None:
    port = server_port()
    lan_ip = detect_lan_ip()
    print()
    print(f"  Admin page:   http://{lan_ip}:{port}/admin")
    print(f"  Student page: http://{lan_ip}:{port}/")
    print(f"  This machine: http://127.0.0.1:{port}/admin")
    print()
    uvicorn.run(create_app(), host=HOST, port=port)


if __name__ == "__main__":
    main()
