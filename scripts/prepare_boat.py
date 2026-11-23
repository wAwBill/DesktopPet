# -*- coding: utf-8 -*-
"""
prepare_boat.py - 把「划船形象」的 3D 生成稿处理成桌宠可用的真透明 PNG。

与 prepare_pet.py 的差别（这张生成稿的两个坑）：
  1. 模型没听话，背景是玫红渐变 (233,30,156) 而不是精确品红 #FF00FF，
     还带右下角「AI生成」水印。直接按品红强度抠会把悬浮水印当成噪点，
     且渐变底色会在绒毛边缘留下粉紫溢色 -> 先把所有近背景像素刷成精确色键。
  2. 巡逻特效需要「船底下有一片水面」来画滚动水浪和入水船桨，
     但普通抠图会紧贴主体裁边 -> 裁边后额外补下方/左右留白，
     让 BoatFX 的水线（约 0.80h）落在船底附近、水浪有空间铺开。

处理链：背景归一 -> 水印刷除 -> 品红色键软 alpha -> 最大连通块
        -> 边缘去溢色 -> 透明区归一 -> 裁边 + 定向补白 -> 放大 -> 质检/预览

用法：
    python prepare_boat.py 生成图.png assets/luoxiaohei_boat.png --preview 预览.png
"""
import argparse
import os
from PIL import Image, ImageDraw

from prepare_pet import (MAGENTA, build_alpha, keep_largest_component,
                         defringe, normalize_background)
from prepare_flat_pet import make_preview

CHROMA = (255, 0, 255, 0)


def normalize_magenta_bg(img):
    """把玫红/品红渐变背景统一刷成精确 #FF00FF。

    判据针对本图的背景色域（R 高、G 很低、B 中高、R-B 明显为正）；
    角色里的橙红鸭嘴 B 低、奶油白与小黄鸭 G 高、猫毛 R 低，均不会误伤。
    反锯齿过渡像素因混了角色色不满足判据，保留原色交给 build_alpha 算软边。
    """
    px = img.load()
    w, h = img.size
    n = 0
    for y in range(h):
        for x in range(w):
            r, g, b = px[x, y]
            if r > 170 and g < 95 and b > 95 and (r - b) > 25:
                px[x, y] = MAGENTA
                n += 1
    print("背景归一: %d px (%.1f%%) -> #FF00FF" % (n, n * 100.0 / (w * h)))

    # 右下角水印：整块刷回色键，避免被判成主体噪点
    box = (int(w * 0.82), int(h * 0.89), w, h)
    ImageDraw.Draw(img).rectangle(box, fill=MAGENTA)
    print("水印清除: %s" % (box,))
    return img


def pad_for_water(img):
    """裁到主体后，按需补白：底部留给水面/浪花，左右留给波浪和船桨。"""
    bbox = img.getchannel("A").getbbox()
    if not bbox:
        raise SystemExit("失败：整张图都被判为背景")
    img = img.crop(bbox)
    print("主体裁剪框:", bbox, " -> %dx%d" % img.size)
    w, h = img.size
    left = int(w * 0.10)
    right = int(w * 0.10)
    top = int(h * 0.03)
    bottom = int(h * 0.22)
    out = Image.new("RGBA", (w + left + right, h + top + bottom), CHROMA)
    out.paste(img, (left, top), img)
    print("补白: 左右 %d/%d 上 %d 下 %d -> %dx%d" %
          (left, right, top, bottom, out.width, out.height))
    return out


def quality_report(img):
    w, h = img.size
    a = img.getchannel("A")
    corners = []
    for cx, cy in ((0, 0), (w - 24, 0), (0, h - 24), (w - 24, h - 24)):
        corners.append(max(a.getpixel((x, y))
                           for y in range(cy, min(cy + 24, h))
                           for x in range(cx, min(cx + 24, w))))
    px = img.load()
    residual = 0
    visible = 0
    for y in range(0, h, 2):
        for x in range(0, w, 2):
            c = px[x, y]
            if c[3] > 120:
                visible += 1
                if min(c[0], c[2]) - c[1] > 170:
                    residual += 1
    print("输出: %dx%d  可见像素(抽样): %d" % (w, h, visible))
    print("四角最大 alpha: %s (应为 0)" % corners)
    print("残留品红像素(抽样): %d (应为 0)" % residual)
    # 船底相对位置：给水浪层的 0.80 水线做校准参考
    bbox = a.getbbox()
    if bbox:
        print("主体在成品中的 y 范围: %d..%d (%.3fh..%.3fh)" %
              (bbox[1], bbox[3], bbox[1] / h, bbox[3] / h))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("src")
    ap.add_argument("dst")
    ap.add_argument("--preview", default="")
    ap.add_argument("--min-height", type=int, default=1000)
    a = ap.parse_args()

    img = Image.open(a.src).convert("RGB")
    print("原图:", img.size)
    img = normalize_magenta_bg(img)
    alpha = build_alpha(img, 25, 95)
    alpha, main_size, removed = keep_largest_component(alpha)
    print("连通块: 主体 %d px, 清除杂点 %d px" % (main_size, removed))
    out = img.convert("RGBA")
    out.putalpha(alpha)
    out = defringe(out)
    out = normalize_background(out)
    out = pad_for_water(out)

    if a.min_height and out.height < a.min_height:
        k = a.min_height / out.height
        out = out.resize((round(out.width * k), a.min_height), Image.LANCZOS)
        out = normalize_background(out)
    os.makedirs(os.path.dirname(os.path.abspath(a.dst)), exist_ok=True)
    out.save(a.dst)
    quality_report(out)
    if a.preview:
        make_preview(out, a.preview)
        print("预览图: %s" % a.preview)


if __name__ == "__main__":
    main()
