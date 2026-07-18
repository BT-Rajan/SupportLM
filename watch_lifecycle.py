"""
watch_lifecycle.py
Standalone monitor. Does NOT require editing chat.py.
Place at: htdocs/supportlm/watch_lifecycle.py   (project root, next to where you run uvicorn)

WHAT IT DOES
1. Tails your app's stdout log for the existing "ask() timing" lines your app
   already prints, and reprints them clearly, flagging slow/cold embeds.
2. Every 3s, polls MySQL row counts for documents / document_chunks / usage_log
   so you can watch, live, whether usage_log actually increments after a chat.

SETUP (2 steps)
1. Edit the DB_* values below to match your MySQL creds (same ones your app uses).
2. Start your app redirecting output to a file, then run this script pointed at it:

   uvicorn supportlm.main:app --reload > app.log 2>&1 &
   python watch_lifecycle.py app.log

Then use the chat widget in your browser. Watch this terminal.
"""

import re
import sys
import time
import threading

import os
import pymysql  # pip install pymysql

def load_env(path=".env"):
    env = {}
    with open(path, encoding="utf-8", errors="ignore") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip()
    return env

_env = load_env()
DB_HOST = _env.get("DB_HOST", "localhost")
DB_PORT = int(_env.get("DB_PORT", 3306))
DB_USER = _env.get("DB_USER", "root")
DB_PASS = _env.get("DB_PASSWORD", "")
DB_NAME = _env.get("DB_NAME", "knowledgelm")

TIMING_RE = re.compile(
    r"ask\(\) timing.*embed:\s*([\d.]+).*vector_search:\s*([\d.]+).*"
    r"llm_call:\s*([\d.]+).*db_write:\s*([\d.]+).*total:\s*([\d.]+)"
)


def tail(path):
    with open(path, "r") as f:
        f.seek(0, 2)  # jump to end, only watch new lines
        while True:
            line = f.readline()
            if not line:
                time.sleep(0.2)
                continue
            m = TIMING_RE.search(line)
            if m:
                embed, vsearch, llm, dbw, total = m.groups()
                flag = " <-- COLD EMBED, slow" if float(embed) > 2 else ""
                print(
                    f"\n[QUERY] embed={embed}s  vector_search={vsearch}s  "
                    f"llm_call={llm}s  db_write={dbw}s  total={total}s{flag}"
                )


def poll_db():
    while True:
        try:
            conn = pymysql.connect(
                host=DB_HOST, port=DB_PORT, user=DB_USER, password=DB_PASS,
                database=DB_NAME, connect_timeout=3,
            )
            with conn.cursor() as cur:
                counts = {}
                for tbl in ("document", "document_chunk", "llm_usage_log"):
                    cur.execute(f"SELECT COUNT(*) FROM {tbl}")
                    counts[tbl] = cur.fetchone()[0]
            conn.close()
            print(
                f"[DB] document={counts['document']}  "
                f"document_chunk={counts['document_chunk']}  "
                f"llm_usage_log={counts['llm_usage_log']}",
                end="\r",
            )
        except Exception as e:
            print(f"[DB ERROR] {e}")
        time.sleep(3)


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python watch_lifecycle.py <path-to-app.log>")
        sys.exit(1)

    threading.Thread(target=poll_db, daemon=True).start()
    tail(sys.argv[1])
