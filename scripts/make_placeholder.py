# -*- coding: utf-8 -*-
"""生成模板自带的占位角色图 assets/pet.png（透明底 Q 版小球）。"""
import os
from PIL import Image, ImageDraw

S = 600
img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
d = ImageDraw.Draw(img)

# 身体（圆润的团子）
body = (255, 183, 77, 255)          # 暖橙色
shade = (245, 158, 60, 255)
d.ellipse([70, 80, 530, 540], fill=body)
d.ellipse([70, 300, 530, 540], fill=shade)
d.ellipse([70, 80, 530, 380], fill=body)

# 耳朵/小角
d.ellipse([120, 40, 220, 140], fill=body)
d.ellipse([380, 40, 480, 140], fill=body)

# 眼睛
d.ellipse([170, 220, 230, 290], fill=(40, 35, 30, 255))
d.ellipse([370, 220, 430, 290], fill=(40, 35, 30, 255))
d.ellipse([185, 230, 205, 252], fill=(255, 255, 255, 255))   # 高光
d.ellipse([385, 230, 405, 252], fill=(255, 255, 255, 255))

# 腮红
d.ellipse([110, 310, 190, 360], fill=(255, 138, 128, 160))
d.ellipse([410, 310, 490, 360], fill=(255, 138, 128, 160))

# 嘴（微笑弧线）
d.arc([250, 300, 350, 400], 20, 160, fill=(40, 35, 30, 255), width=12)

# 小脚
d.ellipse([180, 520, 270, 570], fill=shade)
d.ellipse([330, 520, 420, 570], fill=shade)

out = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                   "..", "assets", "pet.png")
out = os.path.normpath(out)
img.save(out)
print("saved:", out, img.size)
