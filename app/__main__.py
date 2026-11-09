"""python -m app            -> web UI
python -m app <command>  -> CLI with JSON output (see python -m app --help)"""
import socket
import sys
import threading
import webbrowser

HOST = "127.0.0.1"


def free_port(preferred: int = 8765) -> int:
    with socket.socket() as s:
        if s.connect_ex((HOST, preferred)) != 0:
            return preferred
    with socket.socket() as s:
        s.bind((HOST, 0))
        return s.getsockname()[1]


def serve() -> None:
    import uvicorn
    port = free_port()
    url = f"http://{HOST}:{port}"
    print(f"YouTube Uploader running at {url}  (close this window to stop)")
    threading.Timer(1.2, lambda: webbrowser.open(url)).start()
    uvicorn.run("app.server:app", host=HOST, port=port, log_level="warning")


if __name__ == "__main__":
    args = sys.argv[1:]
    if not args or args == ["serve"]:
        serve()
    else:
        from .cli import main
        sys.exit(main(args))
