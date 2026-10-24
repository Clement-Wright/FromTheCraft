import logging
import socket
import sys
import threading
import time
import webbrowser
from pathlib import Path

import uvicorn

from . import app as application


def launch(port=0, open_browser=True, idle_timeout=180):
    if not 0 <= port <= 65535:
        raise ValueError("Port must be between 0 and 65535")
    if idle_timeout < 5:
        raise ValueError("Idle timeout must be at least 5 seconds")
    log_folder = Path(sys.executable).parent if getattr(sys, "frozen", False) else Path.cwd()
    logging.basicConfig(
        filename=log_folder / "fromthecraft.log",
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.bind(("127.0.0.1", port))
    listener.listen(128)
    chosen_port = listener.getsockname()[1]
    url = f"http://127.0.0.1:{chosen_port}"
    server = uvicorn.Server(
        uvicorn.Config(
            application.app,
            host="127.0.0.1",
            port=chosen_port,
            log_config=None,
            access_log=False,
            timeout_graceful_shutdown=5,
        )
    )
    application.shutdown_callback = lambda: setattr(server, "should_exit", True)
    if sys.platform == "win32":
        from .native_save import choose_save_file

        application.save_file_picker = choose_save_file
    started = time.monotonic()

    def browser_and_lifecycle():
        while not server.started and not server.should_exit:
            if time.monotonic() - started > 30:
                return
            time.sleep(0.1)
        if server.should_exit:
            return
        if sys.stdout is not None:
            print(f"FromTheCraft: {url}", flush=True)
        logging.info("Local interface: %s", url)
        if open_browser:
            webbrowser.open(url)
        while not server.should_exit:
            with application.sessions_lock:
                last_activity = max([started] + [s.touched for s in application.sessions.values()])
            if time.monotonic() - last_activity > idle_timeout:
                server.should_exit = True
            time.sleep(1)

    threading.Thread(target=browser_and_lifecycle, daemon=True, name="browser-lifecycle").start()
    try:
        server.run(sockets=[listener])
    finally:
        application.save_file_picker = None
        listener.close()
        for session in application.sessions.values():
            session.cancelled.set()
        application.executor.shutdown(wait=True, cancel_futures=True)
