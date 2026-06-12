#!/usr/bin/env python3
"""
Local web dashboard for running the GeM-CPPP scraper.

This intentionally uses only Python's standard library so non-technical users
can run the same environment without installing an additional web framework.
"""

from __future__ import annotations

import csv
import json
import mimetypes
import os
import shutil
from pathlib import Path
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from subprocess import PIPE, STDOUT, Popen
import subprocess
import sys
import threading
import time
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse


PROJECT_DIR = Path(__file__).resolve().parent
SCRAPER_FILE = PROJECT_DIR / "Scraper.py"
LIVE_DATA_FILE = PROJECT_DIR / "tender_data_live.jsonl"
HOST = "127.0.0.1"
PORT = int(os.environ.get("EPROCURE_UI_PORT", "8000"))
MAX_LOG_LINES = 1500
LIVE_TABLE_HEADERS = [
    "Serial",
    "Status",
    "Page",
    "Row",
    "AOC Date",
    "Title",
    "Organisation Name",
    "Category",
    "Name of Selected Bidder(s)",
    "Number of Bids Received",
    "Contract Value",
    "Extracted At",
]

state_lock = threading.Lock()
scraper_process: Popen[str] | None = None
started_at: float | None = None
ended_at: float | None = None
last_return_code: int | None = None
log_lines: list[str] = []


def append_log(message: str) -> None:
    with state_lock:
        log_lines.append(message)
        if len(log_lines) > MAX_LOG_LINES:
            del log_lines[: len(log_lines) - MAX_LOG_LINES]


def csv_files() -> list[dict[str, Any]]:
    files = []
    for path in PROJECT_DIR.glob("tender_data*.csv"):
        if path.is_file():
            stat = path.stat()
            files.append(
                {
                    "name": path.name,
                    "size": stat.st_size,
                    "modified": stat.st_mtime,
                    "download_url": f"/download?file={path.name}",
                }
            )
    files.sort(key=lambda item: item["modified"], reverse=True)
    return files


def preview_rows() -> dict[str, Any]:
    preview_path = PROJECT_DIR / "tender_data_preview.csv"
    source = preview_path if preview_path.exists() else None
    if source is None:
        for path in PROJECT_DIR.glob("tender_data_*.csv"):
            if path.is_file():
                source = path
                break

    if source is None:
        return {"source": None, "headers": [], "rows": []}

    try:
        with source.open("r", newline="", encoding="utf-8-sig") as csvfile:
            reader = csv.DictReader(csvfile)
            rows = []
            for index, row in enumerate(reader):
                if index >= 25:
                    break
                rows.append(row)
            return {
                "source": source.name,
                "headers": reader.fieldnames or [],
                "rows": rows,
            }
    except Exception as exc:
        return {
            "source": source.name,
            "headers": [],
            "rows": [],
            "error": str(exc),
        }


def live_rows_payload() -> dict[str, Any]:
    if not LIVE_DATA_FILE.exists():
        return {
            "source": None,
            "headers": LIVE_TABLE_HEADERS,
            "rows": [],
            "count": 0,
        }

    rows = []
    try:
        with LIVE_DATA_FILE.open("r", encoding="utf-8") as live_file:
            for line in live_file:
                line = line.strip()
                if not line:
                    continue
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    except Exception as exc:
        return {
            "source": LIVE_DATA_FILE.name,
            "headers": LIVE_TABLE_HEADERS,
            "rows": [],
            "count": 0,
            "error": str(exc),
        }

    return {
        "source": LIVE_DATA_FILE.name,
        "headers": LIVE_TABLE_HEADERS,
        "rows": rows[-300:],
        "count": len(rows),
    }


def process_is_running() -> bool:
    with state_lock:
        process = scraper_process
    return process is not None and process.poll() is None


def scraper_command() -> list[str]:
    in_virtualenv = sys.prefix != getattr(sys, "base_prefix", sys.prefix)
    if in_virtualenv or os.environ.get("VIRTUAL_ENV"):
        return [sys.executable, "-u", str(SCRAPER_FILE)]

    uv_path = shutil.which("uv")
    if uv_path and (PROJECT_DIR / "pyproject.toml").exists():
        return [uv_path, "run", "python", "-u", str(SCRAPER_FILE)]

    return [sys.executable, "-u", str(SCRAPER_FILE)]


def start_scraper() -> dict[str, Any]:
    global ended_at, last_return_code, scraper_process, started_at

    with state_lock:
        if scraper_process is not None and scraper_process.poll() is None:
            return {"ok": True, "message": "Scraper is already running."}

        log_lines.clear()
        started_at = time.time()
        ended_at = None
        last_return_code = None

    if not SCRAPER_FILE.exists():
        append_log(f"ERROR: Missing scraper file: {SCRAPER_FILE}\n")
        return {"ok": False, "message": "Scraper.py was not found."}

    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    creationflags = 0
    if os.name == "nt":
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)

    try:
        command = scraper_command()
        process = Popen(
            command,
            cwd=PROJECT_DIR,
            stdout=PIPE,
            stderr=STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            env=env,
            creationflags=creationflags,
        )
    except Exception as exc:
        with state_lock:
            started_at = None
            ended_at = time.time()
            last_return_code = -1
        append_log(f"ERROR: Could not start scraper: {exc}\n")
        return {"ok": False, "message": str(exc)}

    with state_lock:
        scraper_process = process
    append_log("Started scraper process.\n")
    append_log(f"Command: {' '.join(command)}\n")
    threading.Thread(target=read_process_output, args=(process,), daemon=True).start()
    threading.Thread(target=watch_process, args=(process,), daemon=True).start()
    return {"ok": True, "message": "Scraper started."}


def read_process_output(process: Popen[str]) -> None:
    if process.stdout is None:
        return
    try:
        for line in process.stdout:
            append_log(line)
    except Exception as exc:
        append_log(f"ERROR: Could not read scraper output: {exc}\n")


def watch_process(process: Popen[str]) -> None:
    global ended_at, last_return_code

    return_code = process.wait()
    with state_lock:
        if scraper_process is process:
            ended_at = time.time()
            last_return_code = return_code
    append_log(f"Scraper process finished with exit code {return_code}.\n")


def stop_scraper() -> dict[str, Any]:
    global ended_at, last_return_code

    with state_lock:
        process = scraper_process

    if process is None or process.poll() is not None:
        return {"ok": True, "message": "Scraper is not running."}

    append_log("Stop requested from web UI.\n")
    process.terminate()
    try:
        return_code = process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        append_log("Process did not stop in time; forcing shutdown.\n")
        process.kill()
        return_code = process.wait(timeout=5)

    with state_lock:
        ended_at = time.time()
        last_return_code = return_code
    return {"ok": True, "message": "Scraper stopped."}


def status_payload() -> dict[str, Any]:
    now = time.time()
    with state_lock:
        process = scraper_process
        running = process is not None and process.poll() is None
        active_started_at = started_at
        active_ended_at = ended_at
        return_code = last_return_code
        logs = list(log_lines[-600:])

    if running and active_started_at is not None:
        elapsed = int(now - active_started_at)
    elif active_started_at is not None and active_ended_at is not None:
        elapsed = int(active_ended_at - active_started_at)
    else:
        elapsed = 0

    return {
        "running": running,
        "started_at": active_started_at,
        "ended_at": active_ended_at,
        "elapsed_seconds": elapsed,
        "return_code": return_code,
        "logs": logs,
        "files": csv_files(),
        "live_row_count": live_rows_payload()["count"],
    }


def safe_csv_path(filename: str) -> Path | None:
    decoded = unquote(filename)
    candidate = (PROJECT_DIR / decoded).resolve()
    if candidate.parent != PROJECT_DIR:
        return None
    if candidate.suffix.lower() != ".csv" or not candidate.exists():
        return None
    return candidate


def format_bytes(size: int) -> str:
    units = ["B", "KB", "MB", "GB"]
    value = float(size)
    for unit in units:
        if value < 1024 or unit == units[-1]:
            return f"{value:.0f} {unit}" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1024
    return f"{size} B"


def html_page() -> str:
    return """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>GeM CPPP Scraper Dashboard</title>
  <style>
    :root {
      color-scheme: light;
      --bg: #f6f7f9;
      --surface: #ffffff;
      --surface-2: #eef4f3;
      --text: #20252b;
      --muted: #68717d;
      --line: #dce2e8;
      --primary: #0f766e;
      --primary-strong: #115e59;
      --danger: #b42318;
      --warn: #a15c07;
      --ok: #157347;
      --shadow: 0 12px 30px rgba(30, 41, 59, 0.08);
      font-family: Inter, "Segoe UI", Roboto, Arial, sans-serif;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      background: var(--bg);
      color: var(--text);
      min-height: 100vh;
    }
    header {
      background: var(--surface);
      border-bottom: 1px solid var(--line);
      padding: 18px clamp(16px, 4vw, 42px);
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 16px;
      position: sticky;
      top: 0;
      z-index: 5;
    }
    h1 {
      font-size: clamp(20px, 3vw, 28px);
      line-height: 1.1;
      margin: 0;
      letter-spacing: 0;
    }
    .subtle {
      color: var(--muted);
      font-size: 14px;
      margin-top: 4px;
    }
    main {
      width: min(1440px, 100%);
      margin: 0 auto;
      padding: 22px clamp(14px, 3vw, 34px) 36px;
    }
    .grid {
      display: grid;
      grid-template-columns: minmax(290px, 380px) minmax(0, 1fr);
      gap: 18px;
      align-items: start;
    }
    .stack {
      display: grid;
      gap: 18px;
    }
    section {
      background: var(--surface);
      border: 1px solid var(--line);
      border-radius: 8px;
      box-shadow: var(--shadow);
      overflow: hidden;
    }
    .section-head {
      padding: 16px 18px;
      border-bottom: 1px solid var(--line);
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 12px;
    }
    h2 {
      font-size: 16px;
      line-height: 1.2;
      margin: 0;
      letter-spacing: 0;
    }
    .section-body {
      padding: 18px;
    }
    .controls {
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 10px;
    }
    button {
      border: 0;
      border-radius: 7px;
      padding: 12px 14px;
      min-height: 44px;
      font-size: 15px;
      font-weight: 700;
      cursor: pointer;
      transition: transform 0.12s ease, background 0.12s ease, opacity 0.12s ease;
      letter-spacing: 0;
    }
    button:active { transform: translateY(1px); }
    button:disabled {
      cursor: not-allowed;
      opacity: 0.55;
    }
    .start {
      background: var(--primary);
      color: #fff;
    }
    .start:hover:not(:disabled) { background: var(--primary-strong); }
    .stop {
      background: #fff1f0;
      color: var(--danger);
      border: 1px solid #f1b8b3;
    }
    .stop:hover:not(:disabled) { background: #ffe4e1; }
    .status {
      display: grid;
      gap: 10px;
      margin-top: 18px;
    }
    .status-row {
      display: flex;
      justify-content: space-between;
      gap: 14px;
      border-bottom: 1px solid var(--line);
      padding-bottom: 9px;
      font-size: 14px;
    }
    .status-row:last-child {
      border-bottom: 0;
      padding-bottom: 0;
    }
    .label { color: var(--muted); }
    .value {
      font-weight: 700;
      text-align: right;
      overflow-wrap: anywhere;
    }
    .pill {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      min-height: 26px;
      padding: 0 10px;
      border-radius: 999px;
      font-size: 13px;
      font-weight: 800;
      background: #eceff3;
      color: var(--muted);
      white-space: nowrap;
    }
    .pill.running {
      background: #e5f7ef;
      color: var(--ok);
    }
    .pill.error {
      background: #fff1f0;
      color: var(--danger);
    }
    .pill.done {
      background: var(--surface-2);
      color: var(--primary);
    }
    .files {
      display: grid;
      gap: 10px;
    }
    .file-row {
      display: grid;
      grid-template-columns: minmax(0, 1fr) auto;
      gap: 8px;
      align-items: center;
      padding: 10px 0;
      border-bottom: 1px solid var(--line);
    }
    .file-row:last-child { border-bottom: 0; }
    .file-name {
      font-weight: 700;
      font-size: 14px;
      overflow-wrap: anywhere;
    }
    .file-meta {
      color: var(--muted);
      font-size: 12px;
      margin-top: 3px;
    }
    a.download {
      color: var(--primary);
      font-weight: 800;
      text-decoration: none;
      font-size: 14px;
    }
    a.download:hover { text-decoration: underline; }
    .table-wrap {
      overflow: auto;
      max-height: 420px;
    }
    table {
      border-collapse: collapse;
      width: 100%;
      min-width: 900px;
      font-size: 13px;
    }
    th, td {
      border-bottom: 1px solid var(--line);
      padding: 10px 12px;
      vertical-align: top;
      text-align: left;
      line-height: 1.35;
    }
    th {
      background: #f1f5f6;
      color: #374151;
      position: sticky;
      top: 0;
      z-index: 1;
    }
    td {
      max-width: 360px;
      overflow-wrap: anywhere;
    }
    .empty {
      color: var(--muted);
      padding: 24px 18px;
      text-align: center;
      font-size: 14px;
    }
    .logs {
      background: #15191f;
      color: #dfe7ef;
      font-family: "Cascadia Mono", Consolas, monospace;
      font-size: 12px;
      line-height: 1.55;
      min-height: 360px;
      max-height: 520px;
      overflow: auto;
      padding: 16px;
      white-space: pre-wrap;
      overflow-wrap: anywhere;
    }
    .toast {
      min-height: 20px;
      margin-top: 12px;
      color: var(--muted);
      font-size: 13px;
    }
    .toast.error { color: var(--danger); }
    .toast.ok { color: var(--ok); }
    @media (max-width: 920px) {
      header {
        align-items: flex-start;
        flex-direction: column;
      }
      .grid {
        grid-template-columns: 1fr;
      }
      .controls {
        grid-template-columns: 1fr;
      }
      section {
        border-radius: 7px;
      }
    }
  </style>
</head>
<body>
  <header>
    <div>
      <h1>GeM CPPP Tender Scraper</h1>
      <div class="subtle">Local dashboard for browser-based extraction runs</div>
    </div>
    <span id="statusPill" class="pill">Ready</span>
  </header>

  <main>
    <div class="grid">
      <div class="stack">
        <section>
          <div class="section-head">
            <h2>Run Control</h2>
          </div>
          <div class="section-body">
            <div class="controls">
              <button id="startBtn" class="start" type="button" title="Start scraper">Start</button>
              <button id="stopBtn" class="stop" type="button" title="Stop scraper">Stop</button>
            </div>
            <div id="message" class="toast"></div>
            <div class="status">
              <div class="status-row">
                <span class="label">State</span>
                <span id="stateValue" class="value">Ready</span>
              </div>
              <div class="status-row">
                <span class="label">Elapsed</span>
                <span id="elapsedValue" class="value">0s</span>
              </div>
              <div class="status-row">
                <span class="label">Exit code</span>
                <span id="exitValue" class="value">-</span>
              </div>
              <div class="status-row">
                <span class="label">CSV files</span>
                <span id="fileCountValue" class="value">0</span>
              </div>
              <div class="status-row">
                <span class="label">Extracted rows</span>
                <span id="liveRowCountValue" class="value">0</span>
              </div>
            </div>
          </div>
        </section>

        <section>
          <div class="section-head">
            <h2>Output Files</h2>
          </div>
          <div class="section-body">
            <div id="files" class="files"></div>
          </div>
        </section>
      </div>

      <div class="stack">
        <section>
          <div class="section-head">
            <h2>Live Extraction Table</h2>
            <span id="liveRowPill" class="pill">0 rows</span>
          </div>
          <div id="liveTable" class="table-wrap"></div>
        </section>

        <section>
          <div class="section-head">
            <h2>Live Log</h2>
          </div>
          <pre id="logs" class="logs">No logs yet.</pre>
        </section>
      </div>
    </div>
  </main>

  <script>
    const startBtn = document.getElementById("startBtn");
    const stopBtn = document.getElementById("stopBtn");
    const message = document.getElementById("message");
    const stateValue = document.getElementById("stateValue");
    const elapsedValue = document.getElementById("elapsedValue");
    const exitValue = document.getElementById("exitValue");
    const fileCountValue = document.getElementById("fileCountValue");
    const liveRowCountValue = document.getElementById("liveRowCountValue");
    const statusPill = document.getElementById("statusPill");
    const filesEl = document.getElementById("files");
    const logsEl = document.getElementById("logs");
    const liveTableEl = document.getElementById("liveTable");
    const liveRowPill = document.getElementById("liveRowPill");

    function setMessage(text, kind = "") {
      message.textContent = text;
      message.className = `toast ${kind}`;
    }

    function formatElapsed(seconds) {
      const hrs = Math.floor(seconds / 3600);
      const mins = Math.floor((seconds % 3600) / 60);
      const secs = seconds % 60;
      if (hrs > 0) return `${hrs}h ${mins}m ${secs}s`;
      if (mins > 0) return `${mins}m ${secs}s`;
      return `${secs}s`;
    }

    function formatBytes(size) {
      const units = ["B", "KB", "MB", "GB"];
      let value = Number(size);
      for (let i = 0; i < units.length; i += 1) {
        if (value < 1024 || i === units.length - 1) {
          return i === 0 ? `${value.toFixed(0)} ${units[i]}` : `${value.toFixed(1)} ${units[i]}`;
        }
        value /= 1024;
      }
      return `${size} B`;
    }

    function formatTime(epochSeconds) {
      if (!epochSeconds) return "";
      return new Date(epochSeconds * 1000).toLocaleString();
    }

    function updateFiles(files) {
      filesEl.textContent = "";
      if (!files.length) {
        const empty = document.createElement("div");
        empty.className = "empty";
        empty.textContent = "No CSV files found.";
        filesEl.appendChild(empty);
        return;
      }

      files.forEach((file) => {
        const row = document.createElement("div");
        row.className = "file-row";

        const text = document.createElement("div");
        const name = document.createElement("div");
        name.className = "file-name";
        name.textContent = file.name;
        const meta = document.createElement("div");
        meta.className = "file-meta";
        meta.textContent = `${formatBytes(file.size)} - ${formatTime(file.modified)}`;
        text.appendChild(name);
        text.appendChild(meta);

        const link = document.createElement("a");
        link.className = "download";
        link.href = file.download_url;
        link.textContent = "Download";

        row.appendChild(text);
        row.appendChild(link);
        filesEl.appendChild(row);
      });
    }

    function updateLiveRows(payload) {
      const shouldStick = liveTableEl.scrollTop + liveTableEl.clientHeight >= liveTableEl.scrollHeight - 20;
      liveTableEl.textContent = "";
      liveRowPill.textContent = `${payload.count || 0} rows`;

      if (payload.error) {
        const empty = document.createElement("div");
        empty.className = "empty";
        empty.textContent = payload.error;
        liveTableEl.appendChild(empty);
        return;
      }

      if (!payload.headers.length || !payload.rows.length) {
        const empty = document.createElement("div");
        empty.className = "empty";
        empty.textContent = "Rows will appear here one by one after extraction starts.";
        liveTableEl.appendChild(empty);
        return;
      }

      const table = document.createElement("table");
      const thead = document.createElement("thead");
      const headRow = document.createElement("tr");
      payload.headers.forEach((header) => {
        const th = document.createElement("th");
        th.textContent = header;
        headRow.appendChild(th);
      });
      thead.appendChild(headRow);
      table.appendChild(thead);

      const tbody = document.createElement("tbody");
      payload.rows.forEach((row) => {
        const tr = document.createElement("tr");
        payload.headers.forEach((header) => {
          const td = document.createElement("td");
          td.textContent = row[header] || "";
          tr.appendChild(td);
        });
        tbody.appendChild(tr);
      });
      table.appendChild(tbody);
      liveTableEl.appendChild(table);
      if (shouldStick) {
        liveTableEl.scrollTop = liveTableEl.scrollHeight;
      }
    }

    async function postAction(path) {
      try {
        const response = await fetch(path, { method: "POST" });
        const data = await response.json();
        setMessage(data.message || "Done.", data.ok ? "ok" : "error");
        await refresh();
      } catch (error) {
        setMessage(error.message, "error");
      }
    }

    async function refresh() {
      const [statusResponse, liveRowsResponse] = await Promise.all([
        fetch("/api/status"),
        fetch("/api/live-rows")
      ]);
      const status = await statusResponse.json();
      const liveRows = await liveRowsResponse.json();

      const completeWithError = !status.running && status.return_code !== null && status.return_code !== 0;
      const completeOk = !status.running && status.return_code === 0;
      const stateText = status.running ? "Running" : completeOk ? "Complete" : completeWithError ? "Stopped or failed" : "Ready";

      startBtn.disabled = status.running;
      stopBtn.disabled = !status.running;
      stateValue.textContent = stateText;
      elapsedValue.textContent = formatElapsed(status.elapsed_seconds || 0);
      exitValue.textContent = status.return_code === null ? "-" : status.return_code;
      fileCountValue.textContent = status.files.length;
      liveRowCountValue.textContent = status.live_row_count || liveRows.count || 0;
      statusPill.textContent = stateText;
      statusPill.className = `pill ${status.running ? "running" : completeWithError ? "error" : completeOk ? "done" : ""}`;

      updateFiles(status.files);
      updateLiveRows(liveRows);

      const logText = status.logs.join("");
      const shouldStick = logsEl.scrollTop + logsEl.clientHeight >= logsEl.scrollHeight - 20;
      logsEl.textContent = logText || "No logs yet.";
      if (shouldStick) {
        logsEl.scrollTop = logsEl.scrollHeight;
      }
    }

    startBtn.addEventListener("click", () => postAction("/api/start"));
    stopBtn.addEventListener("click", () => postAction("/api/stop"));
    refresh();
    setInterval(refresh, 1500);
  </script>
</body>
</html>"""


class DashboardHandler(BaseHTTPRequestHandler):
    server_version = "EprocureDashboard/1.0"

    def log_message(self, format: str, *args: Any) -> None:
        return

    def send_json(self, payload: dict[str, Any], status: HTTPStatus = HTTPStatus.OK) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def send_text(self, body_text: str, status: HTTPStatus = HTTPStatus.OK, content_type: str = "text/html") -> None:
        body = body_text.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", f"{content_type}; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        parsed = urlparse(self.path)

        if parsed.path == "/":
            self.send_text(html_page())
            return

        if parsed.path == "/api/status":
            self.send_json(status_payload())
            return

        if parsed.path == "/api/preview":
            self.send_json(preview_rows())
            return

        if parsed.path == "/api/live-rows":
            self.send_json(live_rows_payload())
            return

        if parsed.path == "/download":
            params = parse_qs(parsed.query)
            filename = params.get("file", [""])[0]
            path = safe_csv_path(filename)
            if path is None:
                self.send_json({"ok": False, "message": "File not found."}, HTTPStatus.NOT_FOUND)
                return

            content_type = mimetypes.guess_type(path.name)[0] or "text/csv"
            data = path.read_bytes()
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Content-Disposition", f'attachment; filename="{path.name}"')
            self.end_headers()
            self.wfile.write(data)
            return

        self.send_text("Not found", HTTPStatus.NOT_FOUND, "text/plain")

    def do_POST(self) -> None:
        parsed = urlparse(self.path)

        if parsed.path == "/api/start":
            self.send_json(start_scraper())
            return

        if parsed.path == "/api/stop":
            self.send_json(stop_scraper())
            return

        self.send_json({"ok": False, "message": "Not found."}, HTTPStatus.NOT_FOUND)


def main() -> None:
    server = ThreadingHTTPServer((HOST, PORT), DashboardHandler)
    print(f"Dashboard running at http://{HOST}:{PORT}")
    print("Press Ctrl+C to stop the dashboard.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping dashboard...")
    finally:
        if process_is_running():
            stop_scraper()
        server.server_close()


if __name__ == "__main__":
    main()
