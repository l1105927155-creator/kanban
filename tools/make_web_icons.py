# -*- coding: utf-8 -*-
"""由 icon-source.png 生成 Web App Manifest 用的多尺寸 PNG 图标。

与 make_icon.py 共用同一套裁剪/缩放规则（build_master），保证网页图标
与任务栏图标视觉一致；输出到 app/icons/。
"""
import os
import sys

from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)

from make_icon import build_master, make_frame  # noqa: E402

SIZES = [48, 72, 96, 128, 144, 192, 256, 512]


def main():
    src = os.path.join(HERE, "icon-source.png")
    out_dir = os.path.join(ROOT, "app", "icons")
    os.makedirs(out_dir, exist_ok=True)

    master = build_master(Image.open(src))
    print("母版尺寸:", master.size)

    for s in SIZES:
        img = make_frame(master, s)
        path = os.path.join(out_dir, "icon-%d.png" % s)
        img.save(path)
        print("  %3dpx -> %s" % (s, os.path.basename(path)))

    print("完成，输出目录:", out_dir)


if __name__ == "__main__":
    main()