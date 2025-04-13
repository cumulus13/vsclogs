#!/usr/bin/env python

import sys
from ctraceback import CTraceback
sys.excepthook = CTraceback()

from pydebugger.debug import debug

import os
import re
import socket
sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
import time
import threading
import stat
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
from rich.console import Console
from rich.text import Text

console = Console()

# === CONFIGURATION ===
LOG_DIR = os.path.join(os.environ["APPDATA"], "Code", "logs")  # Windows path
SYSLOG_SERVER = "127.0.0.1"
SYSLOG_PORT = 514
HOSTNAME = "127.0.0.1"

# === STYLE CONFIG ===
LEVEL_STYLES = {
    "info": "bright_cyan",
    "debug": "black on orange3",
    "error": "white on red",
    "warning": "black on yellow",
    "notice": "black on cyan",
    "alert": "white on blue",
    "emergency": "white on magenta",
    "critical": "black on green",
}

# === SYSLOG PRI MAPPING ===
SYSLOG_PRI = {
    "debug": 7,
    "info": 6,
    "notice": 5,
    "warning": 4,
    "error": 3,
    "critical": 2,
    "alert": 1,
    "emergency": 0,
}

FACILITY = 1  # user-level messages

# Track tailed files by inode
tailed_files = {}

def parse_level(line: str) -> str:
    line_lower = line.lower()
    tag_match = re.search(r"\[(debug|info|notice|warning|error|critical|alert|emergency)\]", line_lower)
    tag_level = tag_match.group(1) if tag_match else None

    if "emergency" in line_lower:
        return "emergency"
    if "alert" in line_lower:
        return "alert"
    if "critical" in line_lower:
        return "critical"
    if "error" in line_lower:
        return "error"
    if "warning" in line_lower:
        return "warning"
    if tag_level:
        return tag_level
    return "notice"

def send_syslog(line):
    debug(line=line)
    stripped = line.strip()

    is_traceback = (
        stripped.startswith("Traceback")
        or stripped.startswith("File ")
        or line.startswith(" ")
        or re.match(r'^\s*at\s+', line, re.IGNORECASE)
    )

    if is_traceback or not stripped:
        console.print(line.rstrip())
        return

    level = parse_level(line)
    pri = FACILITY * 8 + SYSLOG_PRI.get(level, 5)
    timestamp = time.strftime("%b %d %H:%M:%S")
    msg = f"<{pri}>{timestamp} {HOSTNAME} VSCodeLog: {line.strip()}"
    debug(msg=msg)
    sock.sendto(msg.encode(), (SYSLOG_SERVER, SYSLOG_PORT))
    print_to_console(level, line)

def print_to_console(level, line):
    style = LEVEL_STYLES.get(level, "white")
    text = Text(line.strip(), style=style)
    console.print(text)

def tail_file(file_path):
    try:
        inode = os.stat(file_path).st_ino
        if inode in tailed_files:
            return
        tailed_files[inode] = True
    except Exception as e:
        console.print(f"[!] stat() failed on {file_path}: {e}", style="bold red")
        return

    print(f"[*] Tailing: {file_path}")

    def _tail():
        try:
            with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                f.seek(0, os.SEEK_END)
                while True:
                    line = f.readline()
                    if line:
                        send_syslog(line)
                    else:
                        time.sleep(0.2)
        except Exception as e:
            console.print(f"[!] Error reading {file_path}: {e}", style="bold red")
            sock.sendto(str(e).encode(), (SYSLOG_SERVER, SYSLOG_PORT))

    threading.Thread(target=_tail, daemon=True).start()

# class LogHandler(FileSystemEventHandler):
#     def on_created(self, event):
#         if not event.is_directory and event.src_path.endswith(".log"):
#             tail_file(event.src_path)

#     # You can remove or comment this if you want to fully avoid re-tailing on modify
#     # def on_modified(self, event):
#     #     if not event.is_directory and event.src_path.endswith(".log"):
#     #         tail_file(event.src_path)

class LogHandler(FileSystemEventHandler):
    def on_created(self, event):
        if not event.is_directory and event.src_path.endswith(".log"):
            tail_file(event.src_path)

    def on_modified(self, event):
        # If the file isn't already being tailed, start tailing it
        if not event.is_directory and event.src_path.endswith(".log"):
            if event.src_path not in tailed_files:
                tail_file(event.src_path)
    
    def on_deleted(self, event):
        # If the file is deleted, remove it from the tailed_files dictionary
        if not event.is_directory and event.src_path.endswith(".log"):
            try:
                inode = os.stat(event.src_path).st_ino
                if inode in tailed_files:
                    del tailed_files[inode]
            except Exception as e:
                console.print(f"[!] stat() failed on {event.src_path}: {e}", style="bold red")
    
    def on_moved(self, event):
        # If the file is moved, remove it from the tailed_files dictionary
        if not event.is_directory and event.dest_path.endswith(".log"):
            try:
                inode = os.stat(event.dest_path).st_ino
                if inode in tailed_files:
                    del tailed_files[inode]
            except Exception as e:
                console.print(f"[!] stat() failed on {event.dest_path}: {e}", style="bold red")
    
    # def on_any_event(self, event):
    #     # If the file is created, modified, or deleted, remove it from the tailed_files dictionary
    #     if not event.is_directory and event.src_path.endswith(".log"):
    #         try:
    #             inode = os.stat(event.src_path).st_ino
    #             if inode in tailed_files:
    #                 del tailed_files[inode]
    #         except Exception as e:
    #             console.print(f"[!] stat() failed on {event.src_path}: {e}", style="bold red")

def scan_existing_logs():
    for root, _, files in os.walk(LOG_DIR):
        for f in files:
            if f.endswith(".log"):
                tail_file(os.path.join(root, f))

def main():
    scan_existing_logs()
    observer = Observer()
    observer.schedule(LogHandler(), path=LOG_DIR, recursive=True)
    observer.start()
    console.print(f"[*] Watching VSCode logs at: {LOG_DIR}", style="bold green")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        observer.stop()
    observer.join()

if __name__ == "__main__":
    main()
