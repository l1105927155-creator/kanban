# -*- coding: utf-8 -*-
"""生成任务看板应用图标（app/app.ico），纯标准库实现。

用法：py make_icon.py [输出路径]
"""

import os
import struct
import sys


def lerp(a, b, t):
    return a + (b - a) * t


def inside_rounded_rect(x, y, x0, y0, x1, y1, r):
    if x < x0 or x > x1 or y < y0 or y > y1:
        return False
    cx = min(max(x, x0 + r), x1 - r)
    cy = min(max(y, y0 + r), y1 - r)
    dx = x - cx
    dy = y - cy
    return dx * dx + dy * dy <= r * r


def sample(u, v):
    """u, v ∈ [0,1)，返回像素颜色 (r, g, b, a)。"""
    # 背景：圆角方形 + 垂直渐变
    m = 0.04
    if not inside_rounded_rect(u, v, m, m, 1 - m, 1 - m, 0.18):
        return (0, 0, 0, 0)
    top = (0x3D, 0x82, 0xF6)
    bottom = (0x25, 0x63, 0xEB)
    t = (v - m) / (1 - 2 * m)
    t = max(0.0, min(1.0, t))
    bg = (int(round(lerp(top[0], bottom[0], t))),
          int(round(lerp(top[1], bottom[1], t))),
          int(round(lerp(top[2], bottom[2], t))))
    # 三根白色圆角柱，代表看板列
    bar_w = 0.16
    gap = 0.10
    total = bar_w * 3 + gap * 2
    x0 = (1 - total) / 2
    heights = [0.44, 0.58, 0.36]
    for i, h in enumerate(heights):
        bx0 = x0 + i * (bar_w + gap)
        bx1 = bx0 + bar_w
        by0 = 0.5 - h / 2
        by1 = by0 + h
        if inside_rounded_rect(u, v, bx0, by0, bx1, by1, bar_w * 0.45):
            return (255, 255, 255, 255)
    return (bg[0], bg[1], bg[2], 255)


def render(size):
    """超采样渲染，返回 size x size 的 RGBA 行列表。"""
    ss = 4 if size <= 64 else (3 if size <= 128 else 2)
    n = size * ss
    rows = []
    for py in range(size):
        row = []
        for px in range(size):
            r = g = b = a = 0
            for sy in range(ss):
                for sx in range(ss):
                    u = (px * ss + sx + 0.5) / n
                    v = (py * ss + sy + 0.5) / n
                    c = sample(u, v)
                    r += c[0]
                    g += c[1]
                    b += c[2]
                    a += c[3]
            k = ss * ss
            row.append((r // k, g // k, b // k, a // k))
        rows.append(row)
    return rows


def bmp_blob(size, rows):
    """生成 ICO 中的 32 位 BMP 图像数据（自下而上 BGRA + AND 掩码）。"""
    xor = bytearray()
    for y in range(size - 1, -1, -1):
        for x in range(size):
            r, g, b, a = rows[y][x]
            xor += bytes((b, g, r, a))
    and_row_bytes = ((size + 31) // 32) * 4
    and_mask = bytes(and_row_bytes * size)
    size_image = len(xor) + len(and_mask)
    header = struct.pack("<IiiHHIIiiII", 40, size, size * 2, 1, 32, 0,
                         size_image, 0, 0, 0, 0)
    return header + bytes(xor) + and_mask


def write_ico(path, sizes):
    blobs = []
    for size in sizes:
        blobs.append((size, bmp_blob(size, render(size))))
    out = bytearray()
    out += struct.pack("<HHH", 0, 1, len(blobs))
    offset = 6 + 16 * len(blobs)
    for size, blob in blobs:
        w = 0 if size >= 256 else size
        h = 0 if size >= 256 else size
        out += struct.pack("<BBBBHHII", w, h, 0, 0, 1, 32, len(blob), offset)
        offset += len(blob)
    for _, blob in blobs:
        out += blob
    with open(path, "wb") as f:
        f.write(out)


def main():
    default_out = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "app", "app.ico")
    out = sys.argv[1] if len(sys.argv) > 1 else default_out
    write_ico(out, [16, 32, 48, 64, 256])
    print("图标已生成:", out)


if __name__ == "__main__":
    main()
