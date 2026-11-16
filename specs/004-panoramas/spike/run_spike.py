"""Spike T-019 Experiment Runner: Pannellum 2.5.7 Performance Benchmark.

Executes automated trials across device emulation profiles and WebP fixtures,
collecting first-render time, steady-state FPS, 1% low FPS, frame-drop rate,
and memory footprint via Chrome DevTools Protocol.
"""
from __future__ import annotations

import base64
import http.server
import json
import os
import socket
import subprocess
import threading
import time
import urllib.request
from typing import Any, Dict, List, Optional

SPIKE_DIR = os.path.dirname(os.path.abspath(__file__))
PORT = 8765
CHROME_PATH = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
CDP_PORT = 9222

# Results store
collected_reports: List[Dict[str, Any]] = []
report_event = threading.Event()


class SpikeHTTPHandler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=SPIKE_DIR, **kwargs)

    def do_POST(self):
        if self.path == "/report":
            content_length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(content_length)
            try:
                data = json.loads(body.decode("utf-8"))
                collected_reports.append(data)
                report_event.set()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(b'{"status":"ok"}')
            except Exception as e:
                self.send_response(500)
                self.end_headers()
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format, *args):
        # Suppress noisy HTTP request logging
        pass


def start_server():
    server = http.server.ThreadingHTTPServer(("127.0.0.1", PORT), SpikeHTTPHandler)
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    return server


def send_cdp_command(sock: socket.socket, method: str, params: Optional[Dict] = None, msg_id: int = 1):
    payload = json.dumps({"id": msg_id, "method": method, "params": params or {}}).encode("utf-8")
    mask = os.urandom(4)
    masked = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
    length = len(payload)
    if length <= 125:
        header = bytes([0x81, 0x80 | length]) + mask
    else:
        header = bytes([0x81, 0x80 | 126, (length >> 8) & 0xFF, length & 0xFF]) + mask
    sock.sendall(header + masked)


def run_single_trial(profile_key: str, profile_cfg: Dict, fixture_name: str, trial: int) -> Optional[Dict[str, Any]]:
    report_event.clear()
    cmd = [
        CHROME_PATH,
        "--headless=new",
        f"--remote-debugging-port={CDP_PORT}",
        "--disable-gpu=false",
        "--use-gl=angle",
        "--enable-features=NetworkService,NetworkServiceInProcess",
        "--disable-background-timer-throttling",
        "--disable-renderer-backgrounding",
        f"--window-size={profile_cfg['width']},{profile_cfg['height']}",
        "about:blank",
    ]

    proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(1.2)
    sock = None

    try:
        # 1. Connect to CDP
        with urllib.request.urlopen(f"http://127.0.0.1:{CDP_PORT}/json/list") as resp:
            tabs = json.loads(resp.read().decode())
            ws_url = tabs[0]["webSocketDebuggerUrl"]
            path = "/" + ws_url.split("/", 3)[3]

        sock = socket.create_connection(("127.0.0.1", CDP_PORT))
        key = base64.b64encode(os.urandom(16)).decode()
        req = (
            f"GET {path} HTTP/1.1\r\n"
            f"Host: 127.0.0.1:{CDP_PORT}\r\n"
            f"Upgrade: websocket\r\n"
            f"Connection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {key}\r\n"
            f"Sec-WebSocket-Version: 13\r\n\r\n"
        )
        sock.sendall(req.encode())
        sock.recv(2048)  # Read handshake response

        # 2. Apply Device Metrics Emulation
        send_cdp_command(
            sock,
            "Emulation.setDeviceMetricsOverride",
            {
                "width": profile_cfg["width"],
                "height": profile_cfg["height"],
                "deviceScaleFactor": profile_cfg["dpr"],
                "mobile": profile_cfg["mobile"],
            },
            msg_id=1,
        )

        # 3. Apply CPU Throttling Rate
        if profile_cfg.get("cpu_throttling_rate", 1) > 1:
            send_cdp_command(
                sock,
                "Emulation.setCPUThrottlingRate",
                {"rate": profile_cfg["cpu_throttling_rate"]},
                msg_id=2,
            )

        # 4. Navigate to Harness
        fixture_path = f"fixtures/{fixture_name}"
        fixture_full_path = os.path.join(SPIKE_DIR, fixture_path)
        fixture_file_size = os.path.getsize(fixture_full_path) if os.path.exists(fixture_full_path) else 0

        target_url = (
            f"http://127.0.0.1:{PORT}/harness.html"
            f"?fixture={fixture_path}"
            f"&profile={profile_key}"
            f"&trial={trial}"
            f"&duration=4.0"
            f"&rotate=-25.0"
        )

        send_cdp_command(sock, "Page.navigate", {"url": target_url}, msg_id=3)

        # 5. Wait for report callback
        prev_len = len(collected_reports)
        signaled = report_event.wait(timeout=14.0)

        if signaled and len(collected_reports) > prev_len:
            latest = collected_reports[-1]
            latest["fixture_size_bytes"] = fixture_file_size
            latest["profile_cfg"] = profile_cfg
            return latest
        else:
            print(f"      [TIMEOUT] Trial {trial} for {profile_key} / {fixture_name} timed out.")
            return None

    except Exception as exc:
        print(f"      [ERROR] Trial {trial} failed: {exc}")
        return None
    finally:
        if sock:
            try:
                sock.close()
            except Exception:
                pass
        try:
            proc.terminate()
            proc.wait(timeout=2.0)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass


def main():
    print("=" * 80)
    print("Starting Task T-019 WebGL / Pannellum 2.5.7 Performance Spike Suite")
    print(f"Chrome Binary: {CHROME_PATH}")
    print("=" * 80)

    start_server()
    time.sleep(0.5)

    profiles = {
        "desktop_unthrottled": {
            "name": "Desktop Baseline (Unthrottled)",
            "width": 1920,
            "height": 1080,
            "dpr": 1.0,
            "mobile": False,
            "cpu_throttling_rate": 1,
            "device_class": "Desktop Host (Windows 11, Chrome 157, Desktop GPU)",
        },
        "mobile_mid_4x": {
            "name": "Mid-Tier Mobile Emulation (4x CPU Slowdown)",
            "width": 412,
            "height": 915,
            "dpr": 2.625,
            "mobile": True,
            "cpu_throttling_rate": 4,
            "device_class": "Mid-Range Smartphone (e.g. Pixel 5 / Galaxy A52 class)",
        },
        "mobile_low_6x": {
            "name": "Low-End Mobile Emulation (6x CPU Slowdown)",
            "width": 360,
            "height": 800,
            "dpr": 2.0,
            "mobile": True,
            "cpu_throttling_rate": 6,
            "device_class": "Budget Smartphone (e.g. Galaxy A12/A03, Redmi 9A, Helio G35 / Unisoc T606)",
        },
    }

    fixtures = [
        "primary_4096x2048_q82.webp",
        "comparison_4096x2048_q80.webp",
        "comparison_4096x2048_q85.webp",
        "comparison_2048x1024_q82.webp",
    ]

    all_results = []
    num_trials = 3

    for p_key, p_cfg in profiles.items():
        print(f"\n>>> Running Profile: {p_cfg['name']} (CPU Throttling: {p_cfg['cpu_throttling_rate']}x)")
        for f_name in fixtures:
            print(f"  - Fixture: {f_name}")
            for t in range(1, num_trials + 1):
                res = run_single_trial(p_key, p_cfg, f_name, t)
                if res:
                    all_results.append(res)
                    print(
                        f"    Trial {t}: Avg FPS: {res['avg_fps']:>5.1f} | "
                        f"1% Low: {res['one_percent_low_fps']:>5.1f} | "
                        f"Min FPS: {res['min_fps']:>5.1f} | "
                        f"First Paint: {res['t_first_paint_ms']:>6.1f}ms | "
                        f"Load: {res['t_load_ms']:>6.1f}ms | "
                        f"Heap: {res['js_heap_mb']}MB"
                    )
                time.sleep(0.5)

    results_file = os.path.join(SPIKE_DIR, "results.json")
    with open(results_file, "w", encoding="utf-8") as f:
        json.dump(all_results, f, indent=2)

    print(f"\nSaved {len(all_results)} experiment runs to {results_file}")
    return all_results


if __name__ == "__main__":
    main()
