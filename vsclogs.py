#!/usr/bin/env python

import sys
from ctraceback import CTraceback
sys.except_hook = CTraceback()
import os
import socket
import time
import threading
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

# CONFIGURATION for Windows
LOG_DIR = os.path.join(os.environ["APPDATA"], "Code", "logs")
SYSLOG_SERVER = "127.0.0.1"  # Replace with your remote syslog IP
SYSLOG_PORT = 514

# Tailed files registry
tailed_files = {}

def send_syslog(message):
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    syslog_msg = f"<13>VSCodeLog: {message.strip()}"
    sock.sendto(syslog_msg.encode(), (SYSLOG_SERVER, SYSLOG_PORT))

def tail_file(file_path):
    if file_path in tailed_files:
        return
    print(f"[*] Tailing new file: {file_path}")
    tailed_files[file_path] = True
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
            print(f"[!] Error tailing {file_path}: {e}")
    threading.Thread(target=_tail, daemon=True).start()

# Watchdog Handler
class LogHandler(FileSystemEventHandler):
    def on_modified(self, event):
        if not event.is_directory and event.src_path.endswith(".log"):
            tail_file(event.src_path)

    def on_created(self, event):
        if not event.is_directory and event.src_path.endswith(".log"):
            tail_file(event.src_path)

def scan_existing_logs():
    for root, dirs, files in os.walk(LOG_DIR):
        for f in files:
            if f.endswith(".log"):
                path = os.path.join(root, f)
                tail_file(path)

def main():
    scan_existing_logs()
    event_handler = LogHandler()
    observer = Observer()
    observer.schedule(event_handler, path=LOG_DIR, recursive=True)
    observer.start()
    print("[*] Watching for new logs in:", LOG_DIR)
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        observer.stop()
    observer.join()

if __name__ == "__main__":
    main()
