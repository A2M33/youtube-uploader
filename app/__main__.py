import socket
import threading
import webbrowser

import uvicorn

HOST = "127.0.0.1"


def free_port(preferred: int = 8765) -> int:
    with socket.socket() as s:
        if s.connect_ex((HOST, preferred)) != 0:
            return preferred
    with socket.socket() as s:
        s.bind((HOST, 0))
        return s.getsockname()[1]


if __name__ == "__main__":
    port = free_port()
    url = f"http://{HOST}:{port}"
    print(f"Oddtoon Uploader running at {url}  (close this window to stop)")
    threading.Timer(1.2, lambda: webbrowser.open(url)).start()
    uvicorn.run("app.server:app", host=HOST, port=port, log_level="warning")
