#!/usr/bin/env python3
"""Repository entry point for the skill's self-contained synthetic demo."""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'skills/mcd-meal-advisor/scripts'))
from demo import fixture, synthetic_quote, demo_run, main

if __name__ == '__main__':
    if '--output' not in sys.argv:
        sys.argv.extend(['--output', str(ROOT / 'docs/demo.html')])
    main()
