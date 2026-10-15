# -*- coding: utf-8 -*-
"""由 PNG 图片生成任务看板应用图标（app/favicon.ico，多分辨率）。

处理流程：
  1) 按透明通道裁剪到内容边界；
  2) 整体等比放大到主体纵向占满画布（不改变宽高比），横向溢出的边缘裁掉；
  3) 用 LANCZOS 逐档下采样，并对小尺寸档做轻度锐化补偿（线条图缩小后易发糊），
     输出 256/128/64/48/32/24/16 共 7 档尺寸的 ICO，
     保证在桌面、任务栏、窗口、小列表视图等各场景下都清晰。
  4) ICO 逐帧手工写入（PNG 压缩帧），避免 Pillow 内部用默认插值重新采样各档。

需要 Pillow（仅此工具脚本需要，应用本体零依赖）：
    pip install pillow

用法：
    py make_icon.py [源图路径] [输出路径] [填充比例] [左裁占比]
    （填充比例默认 0.95；左裁占比默认 0.70，0.5 为对称居中裁剪）
默认：
    源图 = 本目录下的 icon-source.png
    输出 = ../app/favicon.ico
"""

import io
import os
import struct
import sys

try:
    from PIL import Image, ImageFilter
except ImportError:
    print("此脚本需要 Pillow，请先安装：pip install pillow")
    sys.exit(1)

TOOLS_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.dirname(TOOLS_DIR)
DEFAULT_OUT = os.path.join(ROOT_DIR, "app", "favicon.ico")

SIZES = [(256, 256), (128, 128), (64, 64), (48, 48), (32, 32), (24, 24), (16, 16)]
CONTENT_ALPHA_THRESHOLD = 8  # 视为“可见内容”的最小 alpha
MARGIN_RATIO = 0.01          # 画布放大量（1%，基本贴边）
CONTENT_FILL = 0.95          # 主体高度占图标高度比例（等比放大，横向溢出部分裁掉）
CROP_LEFT_SHARE = 0.70       # 横向裁剪偏置：左侧承担 70% 的裁剪量（右侧留出更多空间，修正人物偏右）


def build_master(im, fill=None, left_share=None):
    """裁剪到内容边界，整体等比放大到主体纵向占满画布，横向溢出的边缘裁掉（不变形）。

    适用于宽高比 ≥ 1 的图（宽图）：放大后左右两侧会裁掉一部分，主体显得更大；
    裁剪量偏向左侧（CROP_LEFT_SHARE），人物在图标中的位置更平衡、右侧留白更多。
    fill / left_share 可在命令行覆盖默认值（见文件头用法）。
    """
    fill = CONTENT_FILL if fill is None else fill
    left_share = CROP_LEFT_SHARE if left_share is None else left_share
    im = im.convert("RGBA")
    alpha = im.split()[3]
    mask = alpha.point(lambda v: 255 if v > CONTENT_ALPHA_THRESHOLD else 0)
    bbox = mask.getbbox()
    if not bbox:
        raise ValueError("源图不包含任何可见内容")
    content = im.crop(bbox)
    side = max(content.size)
    canvas_side = int(round(side * (1 + MARGIN_RATIO * 2)))
    # 等比放大：主体高度 = 画布高 × fill（宽度按同比例放大后裁掉两侧）
    k = (canvas_side * fill) / content.height
    new_h = int(round(content.height * k))
    new_w = max(canvas_side, int(round(content.width * k)))
    scaled = content.resize((new_w, new_h), Image.LANCZOS)
    # 横向裁剪：left_share>0.5 偏向裁掉左侧，=0.5 对称居中
    cut_l = int(round((new_w - canvas_side) * left_share))
    scaled = scaled.crop((cut_l, 0, cut_l + canvas_side, new_h))
    canvas = Image.new("RGBA", (canvas_side, canvas_side), (0, 0, 0, 0))
    canvas.paste(scaled, (0, (canvas_side - new_h) // 2), scaled)
    return canvas


def make_frame(master, size):
    """由母版生成单档图标：LANCZOS 缩放 + 小尺寸锐化补偿。

    精细线条（如动漫贴纸）缩小后天然发糊，任务栏/桌面通常只用到
    16~48px，因此对小尺寸档做轻度 UnsharpMask，让边缘线条更"立"。
    """
    img = master.resize((size, size), Image.LANCZOS)
    if size <= 64:
        radius = min(1.2, max(0.4, size / 48.0))
        percent = 130 if size >= 32 else 100
        img = img.filter(ImageFilter.UnsharpMask(radius=radius, percent=percent, threshold=2))
    elif size <= 128:
        img = img.filter(ImageFilter.UnsharpMask(radius=0.6, percent=80, threshold=2))
    return img


def save_ico(path, frames):
    """逐帧手工写 ICO（每帧以 PNG 压缩嵌入，Vista+ 均支持）。

    Pillow 自带的 ICO 保存会对各尺寸用内部默认插值重采样，质量不可控；
    这里改为每帧都经过 make_frame 的 LANCZOS + 锐化流程后再写入。
    """
    frames = sorted(frames, key=lambda im: im.size[0], reverse=True)
    header = struct.pack("<HHH", 0, 1, len(frames))
    entries = b""
    body = b""
    offset = 6 + 16 * len(frames)
    for img in frames:
        s = img.size[0]
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        png = buf.getvalue()
        entries += struct.pack(
            "<BBBBHHII",
            0 if s >= 256 else s,  # width，0 表示 256
            0 if s >= 256 else s,  # height
            0,  # 调色板色数（PNG 帧固定 0）
            0,  # 保留
            1,  # 颜色平面
            32,  # 位深
            len(png),
            offset,
        )
        body += png
        offset += len(png)
    with open(path, "wb") as f:
        f.write(header + entries + body)


def main():
    src = sys.argv[1] if len(sys.argv) > 1 else os.path.join(TOOLS_DIR, "icon-source.png")
    out = sys.argv[2] if len(sys.argv) > 2 else DEFAULT_OUT
    fill = float(sys.argv[3]) if len(sys.argv) > 3 else None
    left_share = float(sys.argv[4]) if len(sys.argv) > 4 else None
    if not os.path.isfile(src):
        print("找不到源图:", src)
        sys.exit(1)
    master = build_master(Image.open(src), fill, left_share)
    frames = [make_frame(master, s[0]) for s in SIZES]
    save_ico(out, frames)
    print("图标已生成:", out)
    print("尺寸档:", " / ".join(str(s[0]) for s in SIZES))
    print("源图:", src, "| 母版画布:", "%dx%d" % master.size,
          "| 填充:", fill if fill is not None else CONTENT_FILL,
          "| 左裁占比:", left_share if left_share is not None else CROP_LEFT_SHARE)


if __name__ == "__main__":
    main()
