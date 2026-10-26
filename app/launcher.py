import os
import subprocess
import sys
import time
import urllib.request

import webview


ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
URL = "http://127.0.0.1:8788/"


def wait_for_backend():
    for _ in range(60):
        try:
            urllib.request.urlopen(URL, timeout=0.5)
            return
        except Exception:
            time.sleep(0.25)
    raise RuntimeError("本地服务启动超时")


def main():
    backend = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "assistant.backend.main:app", "--host", "127.0.0.1", "--port", "8788"],
        cwd=ROOT,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    try:
        wait_for_backend()
        window = webview.create_window("拜访质量分析助手", URL, width=1440, height=900, min_size=(1000, 680))
        webview.start()
    finally:
        if backend.poll() is None:
            backend.terminate()
            backend.wait(timeout=5)


if __name__ == "__main__":
    main()
