import sqlite3
import sys
import tkinter
from compression import zstd

assert sys.version_info[:3] == (3, 14, 10)
assert zstd.decompress(zstd.compress(b"offline")) == b"offline"
print(sys.version)
print("Tk", tkinter.TkVersion, "SQLite", sqlite3.sqlite_version, "Zstd ready")
