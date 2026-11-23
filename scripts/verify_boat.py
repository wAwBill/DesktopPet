# -*- coding: utf-8 -*-
"""verify_boat.py — 划船特效离线专项验证（不弹窗口、不依赖鼠标操作）。

检查：24 相位层尺寸恒定 / 无半透明像素 / 相邻帧确实不同 /
      两值合成后无脏色边 / 每帧开销 / 深色桌面实拍预览。
"""
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from PIL import Image, ImageChops, ImageDraw   # noqa: E402
from pet import DesktopPet                     # noqa: E402
from boat_fx import BoatFX, PHASES             # noqa: E402

H = 220
CHROMA_RGB = (255, 0, 255)
DESK = (32, 32, 38)
results = []


def check(name, ok, detail=""):
    results.append((name, bool(ok), detail))
    print("%s %-38s %s" % ("[PASS]" if ok else "[FAIL]", name, detail))


def desk_shot(rgb):
    """模拟 Windows 色键：纯品红 -> 深色桌面。"""
    out = rgb.copy()
    p = out.load()
    for y in range(out.height):
        for x in range(out.width):
            if p[x, y] == CHROMA_RGB:
                p[x, y] = DESK
    return out


def dirty_stats(rgb):
    """两值合成后，可见像素里偏品红的中间色 = 脏边。"""
    r, g, b = rgb.split()
    m = ImageChops.subtract(ImageChops.darker(r, b), g)
    diff = ImageChops.difference(rgb, Image.new("RGB", rgb.size, CHROMA_RGB))
    non_chroma = ImageChops.lighter(
        ImageChops.lighter(diff.getchannel("R"), diff.getchannel("G")),
        diff.getchannel("B")).point(lambda v: 0 if v == 0 else 255)
    bad70 = ImageChops.multiply(non_chroma,
                                m.point(lambda v: 255 if v > 70 else 0))
    bad10 = ImageChops.multiply(non_chroma,
                                m.point(lambda v: 255 if v > 10 else 0))
    return bad70.histogram()[255], bad10.histogram()[255]


def main():
    src = Image.open(os.path.join(ROOT, "assets", "luoxiaohei_boat.png")).convert("RGBA")
    w = round(H * src.width / src.height)
    base = src.resize((w, H), Image.LANCZOS)
    print("角色帧: %dx%d  源图: %dx%d" % (w, H, src.width, src.height))

    fx = BoatFX()
    # 直接取 24 个预渲染相位，验证的是「相位层本身两两不同」；
    # 运行时每帧只推进 0.914 个相位（25fps / 1.05s 周期 / 24 相位），
    # 采样重复属于正常抽帧，下面另外单独测覆盖率。
    t0 = time.perf_counter()
    layers = fx._build(w, H, False)
    build_ms = (time.perf_counter() - t0) * 1000
    check("24 相位层全部生成", len(layers) == PHASES and all(x is not None for x in layers),
          "预渲染 %.1f ms" % build_ms)
    check("层尺寸与角色帧一致", all(x.size == (w, H) for x in layers),
          "期望 %dx%d" % (w, H))

    half = 0
    for lay in layers:
        hist = lay.getchannel("A").histogram()
        half += sum(hist[1:255])
    check("层内无半透明像素（杜绝粉边）", half == 0, "半透明像素 %d" % half)

    diffs = []
    for i in range(PHASES):
        d = ImageChops.difference(layers[i], layers[(i + 1) % PHASES])
        diffs.append(1 if d.getbbox() else 0)
    check("24 个相位两两不同", sum(diffs) == PHASES,
          "%d/%d 对相邻相位有变化" % (sum(diffs), PHASES))

    fx_run = BoatFX()
    seen = set()
    for _ in range(100):
        fx_run.layer(w, H, False, 0.04, True)
        seen.add(int(fx_run.t * PHASES) % PHASES)
    check("25fps 运行 100 帧相位覆盖率", len(seen) >= 20,
          "覆盖 %d/24 个相位" % len(seen))

    # 全相位渲染 + 脏边统计 + 性能（统计开销单独剔除）
    shots = []
    bad70_total = bad10_total = 0
    render_ms = 0.0
    for i, lay in enumerate(layers):
        t1 = time.perf_counter()
        frame = Image.alpha_composite(base, lay)
        rgb = DesktopPet._compose_chroma(frame)
        render_ms += (time.perf_counter() - t1) * 1000
        b70, b10 = dirty_stats(rgb)
        bad70_total += b70
        bad10_total += b10
        if i in (0, 6, 12, 18):
            shots.append((i, desk_shot(rgb)))
    check("两值合成后无明显脏色边", bad70_total == 0,
          "m>70 可见像素 %d, m>10 参考值 %d" % (bad70_total, bad10_total))
    check("24 帧合成耗时可接受", render_ms / PHASES < 8,
          "%.2f ms/帧 (仅合成+两值化)" % (render_ms / PHASES))

    # 翻向：镜像后的层也要能正常生成、且与正向不同
    fx2 = BoatFX()
    flipped = fx2._build(w, H, True)[:4]
    check("翻向层正常生成且镜像生效",
          all(x is not None and x.size == (w, H) for x in flipped)
          and ImageChops.difference(flipped[0], layers[0]).getbbox() is not None,
          "flip=True 4 帧")
    shots.append((-1, desk_shot(DesktopPet._compose_chroma(
        Image.alpha_composite(base.transpose(Image.FLIP_LEFT_RIGHT), flipped[0])))))

    # 拼图：4 个相位 + 翻向
    pad, label_h = 12, 22
    sheet = Image.new("RGB", (len(shots) * (w + pad) + pad,
                              H + pad * 2 + label_h), (245, 245, 246))
    d = ImageDraw.Draw(sheet)
    for i, (phase, shot) in enumerate(shots):
        x = pad + i * (w + pad)
        title = "flip" if phase < 0 else "phase %02d/%d" % (phase, PHASES)
        d.text((x + 4, pad), title, fill=(40, 40, 45))
        sheet.paste(shot, (x, pad + label_h))
    out = os.path.join(ROOT, "生成稿", "划船特效_相位实拍.png")
    sheet.save(out)
    print("预览图:", out)

    ok = sum(1 for _, o, _ in results if o)
    print("\n===== %d/%d PASS =====" % (ok, len(results)))
    return 0 if ok == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
