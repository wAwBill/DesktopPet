# -*- coding: utf-8 -*-
"""
remove_bg.py — 纯色/近白底图片自动抠图（桌宠角色图预处理）

适用：白底、纯色底的角色图（用户发来的大部分 jpg/png 都是这种）。
不适用：复杂场景照、发丝与背景颜色接近的图——那些如实告诉用户需要人工精抠。

用法：
    python remove_bg.py 输入图.jpg 输出图.png [--tolerance 32] [--feather 1.2]

原理：
    从图片四边洪水填充背景色 → 生成蒙版 → 边缘羽化 → 裁掉透明边 → 存透明 PNG。
    非破坏性：原图不动，结果另存。
"""

import argparse
import sys
from collections import deque

from PIL import Image, ImageFilter


def bg_color_samples(img, edge=4):
    """取四条边的像素作为背景色候选。"""
    w, h = img.size
    px = img.load()
    samples = []
    for x in range(0, w, max(1, w // 60)):
        samples.append(px[x, 0][:3])
        samples.append(px[x, h - 1][:3])
    for y in range(0, h, max(1, h // 60)):
        samples.append(px[0, y][:3])
        samples.append(px[w - 1, y][:3])
    return samples


def color_dist(a, b):
    return max(abs(a[0] - b[0]), abs(a[1] - b[1]), abs(a[2] - b[2]))


def flood_mask(img, tolerance):
    """从四边种子点洪水填充，把'接近背景色'的连通区域标为背景。"""
    w, h = img.size
    rgb = img.convert("RGB")
    px = rgb.load()
    samples = bg_color_samples(rgb)
    is_bg = bytearray(w * h)
    q = deque()

    def maybe_seed(x, y):
        c = px[x, y]
        if any(color_dist(c, s) <= tolerance for s in samples):
            q.append((x, y))
            is_bg[y * w + x] = 1

    for x in range(w):
        maybe_seed(x, 0)
        maybe_seed(x, h - 1)
    for y in range(h):
        maybe_seed(0, y)
        maybe_seed(w - 1, y)

    while q:
        x, y = q.popleft()
        c = px[x, y]
        for nx, ny in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
            if 0 <= nx < w and 0 <= ny < h and not is_bg[ny * w + nx]:
                if any(color_dist(px[nx, ny], s) <= tolerance for s in samples):
                    is_bg[ny * w + nx] = 1
                    q.append((nx, ny))
    return is_bg, w, h


def remove_background(src_path, dst_path, tolerance=32, feather=1.2):
    img = Image.open(src_path).convert("RGBA")
    is_bg, w, h = flood_mask(img, tolerance)

    # 背景→透明，主体→不透明，生成 alpha 通道
    alpha = Image.new("L", (w, h), 255)
    apx = alpha.load()
    for y in range(h):
        base = y * w
        for x in range(w):
            if is_bg[base + x]:
                apx[x, y] = 0

    # 边缘羽化：对 alpha 做高斯模糊，去掉硬白边/锯齿（头发丝、毛绒边缘关键）
    if feather > 0:
        alpha = alpha.filter(ImageFilter.GaussianBlur(feather))
        # 羽化后稍微回收：半透明区向"不透明"一侧拉，减少白边残留
        alpha = alpha.point(lambda v: 255 if v > 200 else (0 if v < 40 else v))

    img.putalpha(alpha)

    # 裁掉四周全透明边
    bbox = alpha.getbbox()
    if bbox:
        img = img.crop(bbox)

    img.save(dst_path)
    kept = sum(1 for v in alpha.tobytes() if v > 40) * 100 // (w * h)
    print("✅ 抠图完成: %s  (%dx%d, 主体占比约 %d%%)" % (dst_path, img.width, img.height, kept))
    if kept > 85:
        print("⚠️  主体占比过高，可能背景没抠干净——试试调大 --tolerance，或这张图需要人工精抠。")
    elif kept < 3:
        print("⚠️  主体占比过低，可能把角色也抠掉了——试试调小 --tolerance。")


def main():
    ap = argparse.ArgumentParser(description="纯色/近白底角色图自动抠图")
    ap.add_argument("src", help="输入图片（jpg/png）")
    ap.add_argument("dst", help="输出透明 PNG（建议 assets/pet.png）")
    ap.add_argument("--tolerance", type=int, default=32,
                    help="背景色容差 0-255，越大抠得越狠（默认 32）")
    ap.add_argument("--feather", type=float, default=1.2,
                    help="边缘羽化半径，去白边锯齿（默认 1.2）")
    a = ap.parse_args()
    remove_background(a.src, a.dst, a.tolerance, a.feather)


if __name__ == "__main__":
    main()
