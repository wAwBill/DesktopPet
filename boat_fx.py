# -*- coding: utf-8 -*-
"""
boat_fx.py — 划船形象的程序化水面特效（滚动水浪 + 划动船桨）

为什么不用「多张生成图序列帧」：
  1. 生成图无法保证相邻帧的像素级对齐，逐帧播放会抖；
  2. 巡逻速度、左右翻向、窗口缩放都要实时响应，序列帧得为每种组合都备一套；
  3. 水浪/桨是简单的几何形状，程序画既干净又能和巡逻速度联动。

做法：按 (w, h, flip) 预渲染 PHASES=24 个相位的 RGBA 叠加层，运行时每帧
只做一次 alpha_composite（约 0.2ms），相位按「巡逻 1.05s / 静止 1.9s」
的周期推进。所有绘制都用 alpha=255 的实心像素 —— 透明色键窗口只认
精确 #ff00ff，半透明像素会在合成时混出粉边/毛边，这里从源头杜绝。

坐标全部用相对比例，改桌宠大小不用调参数。水线落在船底附近（0.795h），
与 prepare_boat.py 裁边后补的下方留白配套。
"""
import math
from PIL import Image, ImageDraw

PHASES = 24
CLEAR = (0, 0, 0, 0)
TAU = 2 * math.pi


class BoatFX(object):
    WATER_Y = 0.795        # 水面基准线
    PIVOT_X = 0.335        # 桨架握点（翻向时镜像），落在船舷上
    PIVOT_Y = 0.665
    OAR_LEN = 0.140        # 桨杆长
    BLADE_LEN = 0.095      # 桨叶长
    BASE_ANGLE = 30.0      # 桨相对竖直向下的基准角
    SWING = 26.0           # 划动摆幅（± 度）

    def __init__(self):
        self.t = 0.0                 # 已走过的周期数（浮点）
        self._key = None
        self._layers = []

    def advance(self, dt, moving):
        period = 1.05 if moving else 1.9
        self.t += dt / period

    def layer(self, w, h, flip, dt, moving):
        """返回当前相位的特效层（与角色帧同尺寸），不需要时返回 None。"""
        self.advance(dt, moving)
        key = (w, h, bool(flip))
        if key != self._key:
            self._layers = self._build(w, h, bool(flip))
            self._key = key
        if not self._layers:
            return None
        return self._layers[int(self.t * PHASES) % PHASES]

    # ------------------------------------------------------------ 预渲染
    def _build(self, w, h, flip):
        return [self._frame(w, h, flip, TAU * i / PHASES)
                for i in range(PHASES)]

    def _frame(self, w, h, flip, ph):
        img = Image.new("RGBA", (w, h), CLEAR)
        d = ImageDraw.Draw(img)
        wy = self.WATER_Y * h
        amp1, amp2, amp3 = 0.022 * h, 0.020 * h, 0.015 * h

        # 远层浪：颜色最淡、频率最高，制造纵深
        self._wave(d, w, h, wy - 0.018 * h, amp1, 2.10, ph,
                   (112, 186, 226, 255), max(2, int(0.016 * h)))
        # 主浪：相位反向滚动，与远层形成交错
        self._wave(d, w, h, wy, amp2, 1.75, -ph + 0.9,
                   (166, 222, 248, 255), max(2, int(0.019 * h)))
        # 船尾向后漂的泡沫
        self._foam(d, w, h, wy, ph, flip)
        # 船桨（在浪上方）
        self._oar(d, w, h, wy, ph, flip)
        # 前景断续白色高光，压住桨叶入水处，像被浪花舔过
        self._wave_segments(d, w, h, wy + 0.028 * h, amp3, 2.50,
                            ph + 1.7, (238, 251, 255, 255),
                            max(1, int(0.008 * h)))
        return img

    # ------------------------------------------------------------ 图元
    @staticmethod
    def _wave_y(x, w, y0, amp, cycles, phase):
        u = x / float(w)
        return (y0
                + amp * math.sin(TAU * cycles * u + phase)
                + 0.32 * amp * math.sin(TAU * cycles * 1.9 * u - phase * 1.4))

    def _wave(self, d, w, h, y0, amp, cycles, phase, color, width):
        pts = [(x, int(round(self._wave_y(x, w, y0, amp, cycles, phase))))
               for x in range(-3, w + 4, 3)]
        d.line(pts, fill=color, width=width, joint="curve")

    def _wave_segments(self, d, w, h, y0, amp, cycles, phase, color, width):
        """断续短弧高光：整条线会显得死板，分段并随相位平移才像水在流。"""
        period = max(8, int(w * 0.13))
        seg = max(5, int(w * 0.065))
        shift = int((phase / TAU) * period) % period
        x0 = -period + shift
        while x0 < w + period:
            pts = [(x, int(round(self._wave_y(x, w, y0, amp, cycles, phase))))
                   for x in range(x0, x0 + seg + 1, 3)]
            if len(pts) > 1:
                d.line(pts, fill=color, width=width, joint="curve")
            x0 += period

    def _foam(self, d, w, h, wy, ph, flip):
        side = 0.87 if not flip else 0.13
        direction = 1 if not flip else -1
        for i in range(4):
            f = (i / 4.0 + (ph / TAU) * 0.25) % 1.0
            x = (side + direction * f * 0.10) * w
            y = wy + 0.014 * h + 0.007 * h * math.sin(ph + i)
            r = max(1, int(0.007 * h * (1.1 - f)))
            d.ellipse([x - r, y - r, x + r, y + r],
                      fill=(226, 246, 255, 255))

    def _oar(self, d, w, h, wy, ph, flip):
        theta = math.radians(self.BASE_ANGLE + self.SWING * math.sin(ph))
        if flip:
            theta = -theta
        ux, uy = math.sin(theta), math.cos(theta)
        nx, ny = math.cos(theta), -math.sin(theta)

        px = (self.PIVOT_X if not flip else 1 - self.PIVOT_X) * w
        py = self.PIVOT_Y * h
        length = self.OAR_LEN * h
        ex, ey = px + ux * length, py + uy * length
        blade = self.BLADE_LEN * h
        tx, ty = ex + ux * blade, ey + uy * blade
        hw = max(4.0, 0.030 * w)

        # 杆：深色描边 + 木色杆身 + 一道高光，不用抗锯齿也有圆柱感
        d.line([(px, py), (ex, ey)], fill=(78, 48, 28, 255),
               width=max(5, int(0.020 * w)))
        d.line([(px, py), (ex, ey)], fill=(168, 110, 60, 255),
               width=max(3, int(0.013 * w)))
        d.line([(px - 1, py), (ex - 1, ey)], fill=(214, 166, 108, 255),
               width=max(1, int(0.005 * w)))

        # 桨叶：末端略宽的梯形
        poly = [(ex + nx * hw, ey + ny * hw),
                (ex - nx * hw, ey - ny * hw),
                (tx - nx * hw * 1.5, ty - ny * hw * 1.5),
                (tx + nx * hw * 1.5, ty + ny * hw * 1.5)]
        d.polygon(poly, fill=(198, 138, 76, 255),
                  outline=(96, 58, 32, 255))
        d.line([(ex + nx * hw * 0.35, ey + ny * hw * 0.35),
                (tx + nx * hw * 0.55, ty + ny * hw * 0.55)],
               fill=(238, 192, 132, 255), width=max(1, int(0.004 * w)))

        # 船舷上的小桨架，别做成猫脸上的一颗黑痣
        r = max(3, int(0.014 * w))
        d.ellipse([px - r, py - r, px + r, py + r], fill=(104, 66, 38, 255))
        d.ellipse([px - r + 1, py - r + 1, px + r - 1, py + r - 1],
                  fill=(198, 138, 76, 255))

        # 入水水花：桨叶越接近/越过水线越明显，划水推进相位再增强一次
        depth = (ty - (wy - 0.012 * h)) / (0.055 * h)
        strength = max(0.0, min(1.0, depth))
        if strength <= 0:
            return
        drive = 0.30 + 0.70 * max(0.0, math.cos(ph + 0.7))
        for j in range(3):
            sx = tx + (j - 1) * hw * 1.5
            sy = wy + 0.009 * h * math.sin(ph * 2 + j)
            rr = max(1, int(0.014 * h * strength * drive * (1.25 - 0.18 * j)))
            d.ellipse([sx - rr, sy - rr, sx + rr, sy + rr],
                      fill=(238, 251, 255, 255))
        for j in range(2):
            dx = (j * 2 - 1) * hw * 2.0 * strength
            dy = -(0.014 * h + 0.016 * h * drive)
            rr = max(1, int(0.007 * h * strength * drive))
            d.ellipse([tx + dx - rr, wy + dy - rr,
                       tx + dx + rr, wy + dy + rr],
                      fill=(214, 242, 255, 255))
