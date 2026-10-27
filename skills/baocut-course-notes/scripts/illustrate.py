#!/usr/bin/env python3
"""Hand-drawn infographic explainers made with an image model (e.g. Codex image generation).

  prompt --notes N --ref s3|map      print the generation prompt for one explainer
  fit    --in raw.png --out visuals/s03.jpg   downscale/compress for the page (needs ffmpeg)

Order of work: write the explainer's facts into the full notes first, then set visual.refs and
visual.labels (every word the picture may show, copied from the notes), then generate with the
prompt, then fit. Image models misspell and invent; the precision review checks the picture
against labels and the transcript, so keep labels few and short.
"""
import argparse
import shutil
import subprocess

from course_notes import dump, read_json, safe_path, text_of
from reading_layout import FIELDS

STYLE = ('手绘风格的中文教学信息图：米白纸张底色；彩色马克笔与彩铅质感的线条，轻微手绘抖动；'
         '用圆角卡片分区，卡片用蓝色、绿色、橙色描边配浅色底；简洁可爱的扁平人物和图标表达角色与动作；'
         '粗体大号中文标题，左侧圆圈编号；用粗箭头连接步骤或因果；底部一条圆角横幅写一句话总结。'
         '版面留白充足、层次清楚，手机上缩小后标题和标签仍然清晰可读。')
RULES = ('严格要求：图中出现的文字只能来自下面的“文字清单”，逐字照抄，不增不删不改，不出现清单以外的数字、英文、日期或标点句子；'
         '中文字形端正、没有错别字和乱码；不加水印、logo、签名或真实人物肖像；不画清单没有提到的事实或因果关系。')


def section_context(note, ref):
    if ref == 'map':
        v = note.get('map') or {}
        facts = [f"第{i}节 {s['title']}：{s['takeaway']}" for i, s in enumerate(note['sections'], 1)]
        return '本课地图（论证链或知识结构）', v, facts, '横版 3:2（如 1536×1024）'
    i = int(ref.lstrip('s'))
    s = note['sections'][i - 1]
    v = s.get('visual') or {}
    facts = [f"一句话结论：{s['takeaway']}"]
    for token in v.get('refs', []):
        field = FIELDS.get(token[0])
        if field and token[0] != 'f':
            facts.append(text_of(s[field][int(token[1:])]))
    return f"第 {i} 节 · {s['title']}", v, facts, '竖版 2:3（如 1024×1536），手机单列阅读'


def prompt(args):
    note = read_json(args.notes)
    title, visual, facts, size = section_context(note, args.ref)
    labels = visual.get('labels')
    if not labels:
        raise ValueError(f'Write {args.ref} visual.labels first: the exact short phrases the picture may show, taken from the full notes')
    text = (f'画一张{size}的{STYLE}\n\n主题：{title}\n\n只能依据这些事实构图（不要把它们整段写进图里）：\n'
            + '\n'.join(f'- {f}' for f in facts)
            + '\n\n文字清单（图中全部文字，逐字照抄）：\n' + '\n'.join(f'- {t}' for t in labels)
            + f'\n\n{RULES}')
    print(text if args.plain else dump({'ref': args.ref, 'size': size, 'target': visual.get('path'), 'prompt': text}))


def fit(args):
    if not shutil.which('ffmpeg'):
        raise ValueError('ffmpeg not found; compress the image another way to under 3 MB')
    src, out = safe_path(args.input), safe_path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    res = subprocess.run(['ffmpeg', '-hide_banner', '-loglevel', 'error', '-y', '-i', str(src), '-vf',
                          f"scale='min({args.max},iw)':'min({args.max},ih)':force_original_aspect_ratio=decrease",
                          '-q:v', '3', str(out)], capture_output=True, text=True)
    if res.returncode:
        raise ValueError('ffmpeg failed: ' + res.stderr[-300:])
    print(dump({'output': str(out), 'bytes': out.stat().st_size}))


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest='command', required=True)
    pr = sub.add_parser('prompt'); pr.add_argument('--notes', required=True); pr.add_argument('--ref', required=True)
    pr.add_argument('--plain', action='store_true', help='print only the prompt text')
    ft = sub.add_parser('fit'); ft.add_argument('--in', dest='input', required=True); ft.add_argument('--out', required=True)
    ft.add_argument('--max', type=int, default=1280, help='longest side in px')
    args = p.parse_args()
    try:
        {'prompt': prompt, 'fit': fit}[args.command](args)
    except (ValueError, KeyError, IndexError, OSError) as exc:
        p.exit(1, 'Error: ' + str(exc) + '\n')


if __name__ == '__main__':
    main()
