#!/usr/bin/env python3
import os
import re
import sys
from pathlib import Path


def load_env_file(path):
    for raw_line in Path(path).read_text(encoding="utf-8-sig").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].lstrip()
        name, separator, value = line.partition("=")
        name = name.strip()
        if not separator or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name):
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        os.environ[name] = value


if len(sys.argv) < 3:
    raise SystemExit("Usage: rdgen-env-exec CONFIG COMMAND...")

load_env_file(sys.argv[1])
os.execvp(sys.argv[2], sys.argv[2:])
