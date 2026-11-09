"""Tiny HTTP API + status page using only the Python standard library.

Runs happily on a Raspberry Pi, an old laptop at the farm office, or a small VPS.

  POST /api/v1/readings      device upload (header X-Device-Key), returns pump command
  GET  /api/v1/advice?station_id=...
  GET  /api/v1/readings?station_id=...&limit=100
  GET  /                     status page
"""
from __future__ import annotations

import hmac
import html
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from .messages import render
from .service import Service

MAX_BODY = 256 * 1024


def make_handler(service: Service):
    class Handler(BaseHTTPRequestHandler):
        server_version = "KrishiSense/0.1"

        def _json(self, code: int, obj) -> None:
            body = json.dumps(obj, ensure_ascii=False).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, fmt, *args):  # quieter logs
            pass

        def do_POST(self):
            if urlparse(self.path).path != "/api/v1/readings":
                return self._json(404, {"error": "not found"})
            length = int(self.headers.get("Content-Length", 0))
            if length <= 0 or length > MAX_BODY:
                return self._json(413, {"error": "bad body size"})
            try:
                payload = json.loads(self.rfile.read(length))
            except json.JSONDecodeError:
                return self._json(400, {"error": "invalid json"})
            station = service.stations.get(payload.get("station_id", ""))
            key = self.headers.get("X-Device-Key", "")
            if station is None or not hmac.compare_digest(key, station.device_key):
                return self._json(401, {"error": "unknown station or wrong key"})
            self._json(200, service.ingest(station, payload))

        def do_GET(self):
            u = urlparse(self.path)
            q = {k: v[0] for k, v in parse_qs(u.query).items()}
            if u.path == "/api/v1/advice":
                st = service.stations.get(q.get("station_id", ""))
                if st is None:
                    return self._json(404, {"error": "unknown station"})
                return self._json(200, service.evaluate(st).to_dict())
            if u.path == "/api/v1/readings":
                if q.get("station_id") not in service.stations:
                    return self._json(404, {"error": "unknown station"})
                limit = max(1, min(int(q.get("limit", 100)), 2000))
                return self._json(200, service.store.readings(q["station_id"], limit))
            if u.path == "/":
                body = status_page(service).encode()
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            self._json(404, {"error": "not found"})

    return Handler


def status_page(service: Service) -> str:
    rows = []
    for st in service.stations.values():
        a = service.evaluate(st)
        rows.append(
            f"<tr><td>{html.escape(st.name)}</td><td>{html.escape(st.crop)} / {st.stage}</td>"
            f"<td><b>{a.status}</b></td><td>{a.available_water_pct if a.available_water_pct is not None else '–'}%</td>"
            f"<td>{a.pump_minutes or '–'}</td><td>{a.rain_next_24h_mm} mm ({int(a.rain_prob_pct)}%)</td>"
            f"<td>{a.battery_v or '–'}</td><td>{a.hours_since_reading if a.hours_since_reading is not None else '–'} h</td>"
            f"<td>{html.escape(render(a, st.name, 'en'))}</td></tr>")
    return f"""<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><meta http-equiv="refresh" content="300">
<title>KrishiSense</title><style>
body{{font-family:system-ui,sans-serif;margin:24px;color:#1d2b1f}} h1{{color:#2e6b34}}
table{{border-collapse:collapse;width:100%}} td,th{{border-bottom:1px solid #ddd;padding:8px;text-align:left;font-size:14px}}
th{{background:#eef5ee}}</style></head><body>
<h1>KrishiSense stations</h1>
<table><tr><th>Station</th><th>Crop / stage</th><th>Status</th><th>Soil water</th><th>Pump min</th>
<th>Rain next 24 h</th><th>Battery V</th><th>Last reading</th><th>Message</th></tr>
{''.join(rows)}</table><p style="color:#777">Refreshes every 5 minutes.</p></body></html>"""


def serve(service: Service, host: str = "0.0.0.0", port: int = 8080) -> ThreadingHTTPServer:
    return ThreadingHTTPServer((host, port), make_handler(service))
