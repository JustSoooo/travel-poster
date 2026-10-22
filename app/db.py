# -*- coding: utf-8 -*-
import os, sqlite3, threading

DATA_DIR = os.environ.get("DATA_DIR", "/data")
DB_PATH = os.path.join(DATA_DIR, "poster.db")
_lock = threading.Lock()

SCHEMA = """
CREATE TABLE IF NOT EXISTS files (
  path TEXT PRIMARY KEY, size INTEGER, mtime REAL, kind TEXT, folder TEXT,
  make TEXT, model TEXT, dt TEXT, subsec TEXT, lat REAL, lon REAL, err TEXT);
CREATE INDEX IF NOT EXISTS i_files_model ON files(model);
CREATE INDEX IF NOT EXISTS i_files_dt ON files(dt);
CREATE TABLE IF NOT EXISTS devices (model TEXT PRIMARY KEY, owner TEXT DEFAULT '');
CREATE TABLE IF NOT EXISTS folders (folder TEXT PRIMARY KEY, excluded INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS kv (k TEXT PRIMARY KEY, v TEXT);
CREATE TABLE IF NOT EXISTS trip_names (trip_id TEXT PRIMARY KEY, name TEXT);
"""


def connect():
    os.makedirs(DATA_DIR, exist_ok=True)
    con = sqlite3.connect(DB_PATH, timeout=60, check_same_thread=False)
    con.execute("PRAGMA journal_mode=WAL")
    con.executescript(SCHEMA)
    return con


def kv_get(con, k, default=None):
    r = con.execute("SELECT v FROM kv WHERE k=?", (k,)).fetchone()
    return r[0] if r else default


def kv_set(con, k, v):
    with _lock:
        con.execute("INSERT INTO kv(k,v) VALUES(?,?) ON CONFLICT(k) DO UPDATE SET v=excluded.v", (k, str(v)))
        con.commit()
