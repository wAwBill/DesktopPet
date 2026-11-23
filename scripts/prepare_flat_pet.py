# -*- coding: utf-8 -*-
"""
prepare_flat_pet.py - 把「纯色底 + 硬边卡通」角色图处理成桌宠可用的真透明 PNG。

与 prepare_pet.py（品红色键 + 毛发软边）不同，这类图有两个陷阱：
  1. 角色内部的大块浅色（如罗小黑的奶油白眼睛）与背景色很接近，
     按颜色距离直接抠会把眼睛抠穿 -> 必须从四边洪泛，只挖「与边界连通」的背景。
  2. 边缘抗锯齿带混了背景色，直接保留会出现一圈灰白边
     -> 内缩 1px + 用邻近纯角色色重绘边缘带。

处理链：
  自动测背景色 -> 刷掉主体下方的水印行 -> 四边洪泛生成硬 alpha
  -> 内缩去混色边 -> 边缘去溢色 -> 归一化透明区 RGB 为精确色键
  -> 裁边 -> 等比放大 -> 质检 + 三视图预览

用法：
    python prepare_flat_pet.py 原图.jpg assets/xxx.png --preview 预览.png
"""
import argparse
import os
from collections import deque
from PIL import Image, ImageChops, ImageDraw, ImageFilter

CHROMA = (255, 0, 255, 0)          # 与 pet.py 的透明色键一致


def bg_color(img):
    """取四边 24px 带的中位数作为背景色，抗 JPEG 噪点。"""
    px = img.load()
    w, h = img.size
    pts = []
    for y in list(range(0, 24)) + list(range(h - 24, h)):
        for x in list(range(0, 24)) + list(range(w - 24, w)):
            pts.append(px[x, y])
    n = len(pts)
    return tuple(sorted(c[i] for c in pts)[n // 2] for i in range(3))


def dist(c, bg):
    return max(abs(c[0] - bg[0]), abs(c[1] - bg[1]), abs(c[2] - bg[2]))


def clear_watermark_below(img, bg, strong=95, pad=6):
    """水印通常印在主体下方的空白区；整行刷回背景色最稳，不会误伤角色。"""
    px = img.load()
    w, h = img.size
    last = 0
    for y in range(h):
        for x in range(0, w, 2):
            if dist(px[x, y], bg) > strong:
                last = y
                break
    y0 = min(h, last + pad)
    if y0 < h:
        ImageDraw.Draw(img).rectangle((0, y0, w - 1, h - 1), fill=bg)
        print("水印清除: 整行刷背景 y=%d..%d (主体底部 y=%d)" % (y0, h - 1, last))
    else:
        print("水印清除: 主体已到底边，跳过")
    return img


def flood_alpha(img, bg, tol=46):
    """从四边洪泛，只把与边界连通的近背景像素挖成透明。

    角色内部的大块浅色（眼睛等）被深色描边包围，不与边界连通，会完整保留。
    """
    px = img.load()
    w, h = img.size
    a = bytearray([255]) * (w * h)
    seen = bytearray(w * h)
    q = deque()

    def visit(i):
        if seen[i]:
            return
        seen[i] = 1
        x, y = i % w, i // w
        if dist(px[x, y], bg) <= tol:
            q.append(i)

    for x in range(w):
        visit(x)
        visit((h - 1) * w + x)
    for y in range(h):
        visit(y * w)
        visit(y * w + w - 1)

    while q:
        i = q.popleft()
        x, y = i % w, i // w
        a[i] = 0
        if x > 0:
            visit(i - 1)
        if x < w - 1:
            visit(i + 1)
        if y > 0:
            visit(i - w)
        if y < h - 1:
            visit(i + w)
    return Image.frombytes("L", (w, h), bytes(a))


def defringe(img, alpha, bg, strong=135):
    """内缩 1px 削掉混背景的抗锯齿轮廓，再用邻近纯角色色重绘边缘带。

    卡通图的轮廓是深色描边，混背景的过渡像素只有 1-2px；直接删掉它们
    比保留半透明灰边更干净，最后做 0.5px 羽化恢复柔和感。
    """
    w, h = img.size
    hard = alpha.filter(ImageFilter.MinFilter(3))
    soft = hard.filter(ImageFilter.GaussianBlur(0.5))
    hp = hard.load()
    sp = soft.load()
    src = img.load()
    out = img.copy()
    dst = out.load()

    for y in range(h):
        for x in range(w):
            sv = sp[x, y]
            if sv == 0:
                continue
            if sv >= 250 and hp[x, y] >= 250:
                continue                      # 内部实心，原色保留
            c = src[x, y]
            if dist(c, bg) > strong:
                continue                      # 已是纯角色色，不用改
            rs = gs = bs = n = 0
            for dy in range(-2, 3):
                yy = y + dy
                if yy < 0 or yy >= h:
                    continue
                for dx in range(-2, 3):
                    xx = x + dx
                    if xx < 0 or xx >= w or hp[xx, yy] < 250:
                        continue
                    cc = src[xx, yy]
                    if dist(cc, bg) <= strong:
                        continue
                    rs += cc[0]
                    gs += cc[1]
                    bs += cc[2]
                    n += 1
            if n:
                dst[x, y] = (rs // n, gs // n, bs // n, sv)
    out.putalpha(soft)
    return out


def normalize_background(img, threshold=8):
    """全透明区 RGB 统一成精确色键，避免 LANCZOS 缩放把杂色渗进边缘。"""
    px = img.load()
    w, h = img.size
    for y in range(h):
        for x in range(w):
            if px[x, y][3] <= threshold:
                px[x, y] = CHROMA
    return img


def make_preview(img, path):
    """三视图：棋盘格 / 深色桌面 / 品红色键实际渲染效果。"""
    w, h = img.size
    cell = 26
    pad = 16
    canvas = Image.new("RGB", (w * 3 + pad * 4, h + pad * 2 + 26), (245, 245, 245))
    d = ImageDraw.Draw(canvas)

    def place(rgba, idx, title):
        bg = Image.new("RGBA", (w, h), (0, 0, 0, 255))
        if idx == 0:
            base = Image.new("RGB", (w, h), (238, 238, 238))
            dd = ImageDraw.Draw(base)
            for y in range(0, h, cell):
                for x in range(0, w, cell):
                    if (x // cell + y // cell) % 2:
                        dd.rectangle([x, y, x + cell - 1, y + cell - 1],
                                     fill=(204, 204, 204))
            bg = base.convert("RGBA")
        elif idx == 1:
            bg = Image.new("RGBA", (w, h), (32, 32, 38, 255))
        else:
            bg = Image.new("RGBA", (w, h), (255, 0, 255, 255))
        bg.alpha_composite(rgba)
        rgb = bg.convert("RGB")
        ox = pad + idx * (w + pad)
        if idx == 2:                          # 模拟 Windows 色键：纯品红 -> 深色
            p = rgb.load()
            for y in range(h):
                for x in range(w):
                    if p[x, y] == (255, 0, 255):
                        p[x, y] = (32, 32, 38)
            rgb.save(path.replace(".png", "_色键实拍.png"))
        canvas.paste(rgb, (ox, pad + 22))
        d.text((ox + 8, pad + 4), title, fill=(40, 40, 45))

    place(img, 0, "1 / checker")
    place(img, 1, "2 / dark desktop")
    place(img, 2, "3 / chroma render")
    canvas.save(path)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("src")
    ap.add_argument("dst")
    ap.add_argument("--preview", default="")
    ap.add_argument("--tol", type=int, default=46, help="洪泛背景容差")
    ap.add_argument("--min-height", type=int, default=1000)
    a = ap.parse_args()

    img = Image.open(a.src).convert("RGB")
    bg = bg_color(img)
    print("检测背景色:", bg, " 原图:", img.size)
    img = clear_watermark_below(img, bg)
    alpha = flood_alpha(img, bg, a.tol)
    img = img.convert("RGBA")
    img.putalpha(alpha)
    img = defringe(img, alpha, bg)
    img = normalize_background(img)

    bbox = img.getchannel("A").getbbox()
    if not bbox:
        raise SystemExit("失败：整张图都被判为背景")
    img = img.crop(bbox)
    print("主体裁剪框:", bbox, " -> %dx%d" % img.size)
    if a.min_height and img.height < a.min_height:
        k = a.min_height / img.height
        img = img.resize((round(img.width * k), a.min_height), Image.LANCZOS)
        img = normalize_background(img)       # 缩放后再次归一，杜绝渗色

    os.makedirs(os.path.dirname(os.path.abspath(a.dst)), exist_ok=True)
    img.save(a.dst)

    w, h = img.size
    ap2 = img.getchannel("A").load()
    corners = []
    for cx, cy in ((0, 0), (w - 20, 0), (0, h - 20), (w - 20, h - 20)):
        corners.append(max(ap2[x, y] for y in range(cy, min(cy + 20, h))
                           for x in range(cx, min(cx + 20, w))))
    px = img.load()
    visible = sum(1 for y in range(0, h, 2) for x in range(0, w, 2)
                  if px[x, y][3] > 40)
    # 关键质检：画面中心是否实心（眼睛不能被抠穿）
    cx, cy = w // 2, h // 2
    eye_sample = [(px[x, cy][3], px[x, cy][:3])
                  for x in range(cx - 20, cx + 20, 4)]
    print("输出: %s (%dx%d)" % (a.dst, w, h))
    print("可见像素(抽样): %d / %d" % (visible, (h + 1) // 2 * ((w + 1) // 2)))
    print("四角最大 alpha: %s (应为 0)" % corners)
    print("中心行 alpha 抽样: %s" % [v[0] for v in eye_sample])
    if a.preview:
        make_preview(img, a.preview)
        print("预览图: %s" % a.preview)


if __name__ == "__main__":
    main()
