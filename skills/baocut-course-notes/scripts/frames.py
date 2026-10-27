#!/usr/bin/env python3
"""Frame candidates from the original video in one command (needs ffmpeg/ffprobe on PATH).

  scan  --video v.mp4 --out <run>/frames   scene changes + a frame at least every --interval s,
                                           downscaled candidates, contact sheets, candidates.json
  grab  --video v.mp4 --out <run>/frames --time 812.4 [--time ...]
                                           exact full-resolution frames for notes.json "frames"

Look at the contact sheets first, then open only the candidates you may use; pick final
moments with grab. Candidates are evidence for selection, never content by themselves.
"""
import argparse
import json
import re
import shutil
import subprocess
from pathlib import Path

from course_notes import dump, safe_path, write

SHEET = 12  # thumbnails per contact sheet (4 x 3)


def need_ffmpeg():
    for tool in ('ffmpeg', 'ffprobe'):
        if not shutil.which(tool):
            raise ValueError(f'{tool} not found on PATH; install ffmpeg or continue text-only and record the visual gap in limitations')


def duration(video):
    out = subprocess.run(['ffprobe', '-v', 'error', '-show_entries', 'format=duration', '-of', 'csv=p=0', str(video)],
                         capture_output=True, text=True, check=True).stdout.strip()
    return float(out)


def size(video):
    out = subprocess.run(['ffprobe', '-v', 'error', '-select_streams', 'v:0', '-show_entries', 'stream=width,height', '-of', 'csv=p=0',
                          str(video)], capture_output=True, text=True, check=True).stdout.strip().split(',')
    return int(out[0]), int(out[1])


def name(t):
    return f'v{int(round(t * 1000)):09d}.jpg'


def scan(args):
    need_ffmpeg()
    video, out = safe_path(args.video), safe_path(args.out)
    cand = out / 'cand'
    if cand.exists() and any(cand.iterdir()):
        raise ValueError(f'{cand} is not empty; scan never overwrites earlier candidates')
    cand.mkdir(parents=True, exist_ok=True)
    expr = f"gt(scene,{args.threshold})+isnan(prev_selected_t)+gte(t-prev_selected_t,{args.interval})"
    proc = subprocess.run(['ffmpeg', '-hide_banner', '-nostats', '-i', str(video), '-an',
                           '-vf', f"select='{expr}',scale={args.width}:-2,showinfo", '-fps_mode', 'vfr', '-q:v', '4',
                           str(cand / 'tmp-%05d.jpg')], capture_output=True, text=True)
    if proc.returncode:
        raise ValueError('ffmpeg scan failed: ' + proc.stderr[-400:])
    times = [float(t) for t in re.findall(r'pts_time:\s*([\d.]+)', proc.stderr)]
    tmp = sorted(cand.glob('tmp-*.jpg'))
    if len(tmp) != len(times):
        raise ValueError(f'ffmpeg wrote {len(tmp)} frames but reported {len(times)} timestamps')
    rows = []
    for t, f in zip(times, tmp):
        f.rename(cand / name(t))
        rows.append({'time': round(t, 3), 'path': f'cand/{name(t)}'})
    vw, vh = size(video)
    cell = max(2, int(320 * vh / vw) // 2 * 2)  # thumbnails keep the video's aspect ratio
    sheets = []
    for k in range(0, len(rows), SHEET):
        group = rows[k:k + SHEET]
        sheet = out / f'sheet-{k // SHEET + 1:02d}.jpg'
        inputs = sum((['-i', str(out / r['path'])] for r in group), [])
        filt = ''.join(f'[{n}:v]scale=320:{cell}[t{n}];' for n in range(len(group)))
        filt += ''.join(f'[t{n}]' for n in range(len(group))) + f'xstack=inputs={len(group)}:layout=' + '|'.join(
            f'{(n % 4) * 320}_{(n // 4) * cell}' for n in range(len(group))) + ':fill=white' if len(group) > 1 else f'[0:v]scale=320:{cell}'
        res = subprocess.run(['ffmpeg', '-hide_banner', '-loglevel', 'error', *inputs, '-filter_complex', filt,
                              '-frames:v', '1', '-q:v', '4', str(sheet)], capture_output=True, text=True)
        if res.returncode:
            raise ValueError('contact sheet failed: ' + res.stderr[-300:])
        sheets.append({'path': sheet.name, 'candidates': [r['time'] for r in group], 'layout': '4 columns, left to right, top to bottom'})
    report = {'video': str(video), 'duration': round(duration(video), 3), 'threshold': args.threshold,
              'interval': args.interval, 'candidates': rows, 'sheets': sheets}
    write(out / 'candidates.json', dump(report) + '\n')
    print(dump({'candidates': len(rows), 'sheets': len(sheets), 'index': str(out / 'candidates.json')}))


def grab(args):
    need_ffmpeg()
    video, out = safe_path(args.video), safe_path(args.out)
    total = duration(video)
    out.mkdir(parents=True, exist_ok=True)
    frames = []
    for t in args.time:
        if not 0 <= t <= total:
            raise ValueError(f'time {t} outside video duration {total:.1f}')
        path = out / name(t)
        res = subprocess.run(['ffmpeg', '-hide_banner', '-loglevel', 'error', '-y', '-ss', f'{t:.3f}', '-i', str(video),
                              '-frames:v', '1', '-q:v', '2', str(path)], capture_output=True, text=True)
        if res.returncode or not path.exists():
            raise ValueError(f'grab at {t} failed: ' + res.stderr[-300:])
        frames.append({'time': t, 'path': f'{out.name}/{path.name}', 'caption': ''})
    print(dump({'frames': frames, 'note': 'paths are relative to the run directory when --out is <run>/frames; write captions from what the frame shows'}))


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest='command', required=True)
    s = sub.add_parser('scan')
    s.add_argument('--video', required=True); s.add_argument('--out', required=True)
    s.add_argument('--threshold', type=float, default=0.3, help='scene change score, 0-1')
    s.add_argument('--interval', type=float, default=60, help='max seconds between candidates')
    s.add_argument('--width', type=int, default=960, help='candidate width; keeps image tokens low')
    g = sub.add_parser('grab')
    g.add_argument('--video', required=True); g.add_argument('--out', required=True)
    g.add_argument('--time', type=float, action='append', required=True)
    args = p.parse_args()
    try:
        {'scan': scan, 'grab': grab}[args.command](args)
    except (ValueError, OSError, subprocess.CalledProcessError) as exc:
        p.exit(1, 'Error: ' + str(exc) + '\n')


if __name__ == '__main__':
    main()
