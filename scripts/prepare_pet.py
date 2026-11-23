# -*- coding: utf-8 -*-
"""
prepare_pet.py - 把图生图角色稿处理成桌宠可用的真透明 PNG。

处理链：右下角水印清除 -> 品红色键生成软 alpha -> 只保留主体连通块
        -> 边缘去溢色 -> 裁边 -> 质检报告 -> 棋盘格预览图。

用法：
    python prepare_pet.py 生成图.png assets/pet.png --preview 预览.png
"""
import argparse
import os
from collections import deque
from PIL import Image, ImageDraw, ImageFilter

MAGENTA = (255, 0, 255)


def magenta_strength(c):
    """品红强度：min(R,B)-G。纯品红约 255，角色暖色/中性色约 <= 0。"""
    return min(c[0], c[2]) - c[1]


def clear_watermark(img):
    """把右下角非品红的孤立水印块涂回纯品红，避免抠图后被当成主体。"""
    w, h = img.size
    px = img.load()
    x0, y0 = int(w * 0.80), int(h * 0.86)
    box = None
    for y in range(y0, h):
        for x in range(x0, w):
            if magenta_strength(px[x, y]) < 150:
                if box is None:
                    box = [x, y, x, y]
                else:
                    box[0] = min(box[0], x)
                    box[1] = min(box[1], y)
                    box[2] = max(box[2], x)
                    box[3] = max(box[3], y)
    if box is None:
        print("水印检测: 右下角无异常像素")
        return img
    box = [max(0, box[0] - 6), max(0, box[1] - 6),
           min(w, box[2] + 7), min(h, box[3] + 7)]
    area = (box[2] - box[0]) * (box[3] - box[1])
    if area > w * h * 0.06:
        print("水印检测: 异常区过大 %.2f%%，跳过以免误伤主体" % (area * 100 / (w * h)))
        return img
    ImageDraw.Draw(img).rectangle(box, fill=MAGENTA)
    print("水印清除: %s (占画面 %.2f%%)" % (box, area * 100 / (w * h)))
    return img


def build_alpha(img, low=25, high=95):
    """按品红强度生成软 alpha，天然保留绒毛抗锯齿边缘。"""
    w, h = img.size
    px = img.load()
    alpha = Image.new("L", (w, h), 0)
    ap = alpha.load()
    for y in range(h):
        for x in range(w):
            m = magenta_strength(px[x, y])
            if m <= low:
                ap[x, y] = 255
            elif m >= high:
                ap[x, y] = 0
            else:
                ap[x, y] = int(255 * (high - m) / (high - low))
    return alpha.filter(ImageFilter.GaussianBlur(0.5))


def keep_largest_component(alpha, threshold=50):
    """只保留最大的不透明连通块，清除水印残留与零散噪点。"""
    w, h = alpha.size
    data = bytearray(alpha.tobytes())
    seen = bytearray(w * h)
    best, best_size = None, 0
    for start in range(w * h):
        if seen[start] or data[start] < threshold:
            continue
        q = deque([start])
        seen[start] = 1
        comp = []
        while q:
            i = q.popleft()
            comp.append(i)
            x, y = i % w, i // w
            neighbors = (i - 1 if x > 0 else -1, i + 1 if x < w - 1 else -1,
                         i - w if y > 0 else -1, i + w if y < h - 1 else -1)
            for ni in neighbors:
                if ni >= 0 and not seen[ni] and data[ni] >= threshold:
                    seen[ni] = 1
                    q.append(ni)
        if len(comp) > best_size:
            best, best_size = comp, len(comp)
    if best is None:
        return alpha, 0, 0
    out = bytearray(w * h)
    for i in best:
        out[i] = data[i]
    total = sum(1 for v in data if v >= threshold)
    return Image.frombytes("L", (w, h), bytes(out)), best_size, total - best_size


def defringe(img):
    """消除品红溢色：腐蚀 alpha 2px，并用邻近不透明像素颜色重绘边缘带。"""
    w, h = img.size
    a = img.getchannel("A").filter(ImageFilter.MinFilter(5))
    a = a.filter(ImageFilter.GaussianBlur(0.4))
    ap = a.load()
    ep = a.filter(ImageFilter.MaxFilter(7)).load()
    src = img.load()
    out = img.copy()
    dst = out.load()
    for y in range(h):
        for x in range(w):
            if ap[x, y] >= 250 or ep[x, y] == 0:
                continue
            rs = gs = bs = n = 0
            for dy in range(-3, 4):
                yy = y + dy
                if yy < 0 or yy >= h:
                    continue
                for dx in range(-3, 4):
                    xx = x + dx
                    if xx < 0 or xx >= w or ap[xx, yy] < 200:
                        continue
                    c = src[xx, yy]
                    rs += c[0]
                    gs += c[1]
                    bs += c[2]
                    n += 1
            if n:
                dst[x, y] = (rs // n, gs // n, bs // n, ap[x, y])
    out.putalpha(a)
    return out


def normalize_background(img, threshold=8):
    """把全透明区的 RGB 统一成精确色键值，避免 LANCZOS 缩放时把杂色渗进边缘。"""
    px = img.load()
    w, h = img.size
    for y in range(h):
        for x in range(w):
            if px[x, y][3] <= threshold:
                px[x, y] = (255, 0, 255, 0)
    return img


def make_preview(img, path):
    """棋盘格底预览，便于肉眼确认透明区是否干净。"""
    w, h = img.size
    cell = 28
    bg = Image.new("RGB", (w, h), (238, 238, 238))
    d = ImageDraw.Draw(bg)
    for y in range(0, h, cell):
        for x in range(0, w, cell):
            if (x // cell + y // cell) % 2:
                d.rectangle([x, y, x + cell - 1, y + cell - 1], fill=(204, 204, 204))
    bg.paste(img, (0, 0), img)
    bg.save(path)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("src")
    ap.add_argument("dst")
    ap.add_argument("--preview", default="")
    ap.add_argument("--low", type=int, default=25, help="m<=low 判为完全不透明")
    ap.add_argument("--high", type=int, default=95, help="m>=high 判为完全透明")
    ap.add_argument("--min-height", type=int, default=1000, help="输出最小高度，不足则等比放大")
    a = ap.parse_args()

    img = Image.open(a.src).convert("RGB")
    img = clear_watermark(img)
    alpha = build_alpha(img, a.low, a.high)
    alpha, main_size, removed = keep_largest_component(alpha)
    img = img.convert("RGBA")
    img.putalpha(alpha)
    img = defringe(img)
    img = normalize_background(img)

    bbox = img.getchannel("A").getbbox()
    if not bbox:
        raise SystemExit("失败：整张图都被判为背景，请调整阈值")
    img = img.crop(bbox)
    if a.min_height and img.height < a.min_height:
        k = a.min_height / img.height
        img = img.resize((round(img.width * k), a.min_height), Image.LANCZOS)
    os.makedirs(os.path.dirname(os.path.abspath(a.dst)), exist_ok=True)
    img.save(a.dst)

    w, h = img.size
    a_bytes = img.getchannel("A").tobytes()
    kept = sum(1 for v in a_bytes if v > 40) * 100 // (w * h)
    corners = []
    ap2 = img.getchannel("A").load()
    for cx, cy in ((0, 0), (w - 24, 0), (0, h - 24), (w - 24, h - 24)):
        corners.append(max(ap2[x, y] for y in range(cy, min(cy + 24, h))
                           for x in range(cx, min(cx + 24, w))))
    px = img.load()
    residual = 0
    for y in range(0, h, 2):
        for x in range(0, w, 2):
            c = px[x, y]
            if c[3] > 120 and magenta_strength(c) > 170:
                residual += 1

    print("输出: %s (%dx%d)" % (a.dst, w, h))
    print("主体占比: %d%%   主体连通块: %d px   清除杂点: %d px" % (kept, main_size, removed))
    print("四角最大 alpha: %s (应接近 0)" % corners)
    print("残留品红像素(抽样): %d (应为 0)" % residual)
    if a.preview:
        make_preview(img, a.preview)
        print("预览图: %s" % a.preview)


if __name__ == "__main__":
    main()
