#!/usr/bin/env python3
"""Copy the self-contained skill without touching MCP settings or credentials."""
import argparse
from pathlib import Path
import shutil
import sys


def install(target):
    source = Path(__file__).resolve().parent / 'skills/mcd-meal-advisor'
    destination = Path(target).expanduser() / source.name
    if destination.exists() or destination.is_symlink():
        raise FileExistsError('Target exists; existing skill was not changed')
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(source, destination, ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
    return destination


if __name__ == '__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--target',default=str(Path.home()/'.agents/skills'))
    args=parser.parse_args()
    try:print(install(args.target))
    except FileExistsError as exc:print(str(exc),file=sys.stderr);sys.exit(1)
