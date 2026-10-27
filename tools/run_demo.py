#!/usr/bin/env python3
"""Render bundled synthetic data offline; never downloads or calls BaoCut."""
import argparse
import os
from pathlib import Path
import shutil
import subprocess
import sys


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', default='build/demo', help='A new output directory; existing paths are refused')
    args = parser.parse_args()
    repo = Path(__file__).resolve().parents[1]
    out = Path(args.out).expanduser().resolve()
    if out.exists():
        parser.error('Output already exists. Choose a different --out directory.')
    out.mkdir(parents=True)
    for name in ('transcript.json', 'notes.json', 'synthetic-frame.png'):
        shutil.copy2(repo / 'examples/synthetic' / name, out / name)
    shutil.copytree(repo / 'examples/synthetic/visuals', out / 'visuals')
    scripts = repo / 'skills/baocut-course-notes/scripts'
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE='1')
    commands = [
        ['course_notes.py', 'chunks', '--input', str(out/'transcript.json'), '--out', str(out/'chunks')],
        ['course_notes.py', 'render', '--notes', str(out/'notes.json'), '--index', str(out/'chunks/index.json'), '--out', str(out/'notes.html')],
    ]
    for script, *arguments in commands:
        subprocess.run([sys.executable, str(scripts/script), *arguments], env=env, check=True)
    print('Synthetic demo ready:', out/'notes.html')
    print('This validates rendering only, not real-course reading, ASR, video coverage or fidelity.')


if __name__ == '__main__':
    main()
