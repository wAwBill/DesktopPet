# -*- coding: utf-8 -*-
"""
build.py — 把桌宠模板打包成可分发的成品（Windows .exe / Mac .app）

用法（在 template 目录的上级执行）：
    python build.py <template目录> [--name 桌面宠物] [--out 输出目录]

流程：
    1. 检查 PyInstaller（没装则提示 pip install pyinstaller）
    2. 打包 pet.py（--noconsole --onefile，assets/dialogues/config 内嵌一份兜底）
    3. 组装交付目录：可执行文件 + 可编辑资源（assets/dialogues.txt/config.json/
       使用说明.txt/源码 pet.py）——用户替换 exe 旁边的资源即可定制，不用重打包。

Mac 打包 .app 需要在 Mac 上执行（PyInstaller 不能跨平台打包）；
在 Windows 上给 Mac 用户交付时，改交付 .command 启动脚本（见 SKILL.md）。
"""

import argparse
import glob
import os
import shutil
import subprocess
import sys

# dialogue*.txt / pets.json / assets 全部可编辑；add-data 里内嵌一份做兜底
EDITABLE = ["assets", "config.json", "pets.json", "使用说明.txt",
            "pet.py", "boat_fx.py", "updater.py",
            "version.json", "update.json", "README.md"]


def main():
    ap = argparse.ArgumentParser(description="桌宠打包脚本")
    ap.add_argument("template", help="template 目录路径")
    ap.add_argument("--name", default="桌面宠物", help="生成的程序名")
    ap.add_argument("--out", default=None, help="交付目录（默认 template 同级 dist_桌宠）")
    a = ap.parse_args()

    tpl = os.path.abspath(a.template)
    pet_py = os.path.join(tpl, "pet.py")
    if not os.path.exists(pet_py):
        sys.exit("找不到 %s" % pet_py)

    try:
        import PyInstaller  # noqa: F401
    except ImportError:
        sys.exit("缺少 PyInstaller，先执行：pip install pyinstaller")

    sep = ";" if sys.platform.startswith("win") else ":"
    dialogues = sorted(glob.glob(os.path.join(tpl, "dialogues*.txt")))
    add = []
    for item in ("assets", "config.json", "pets.json",
                 "version.json", "update.json"):
        p = os.path.join(tpl, item)
        if os.path.exists(p):
            add += ["--add-data", p + sep + item]
    for p in dialogues:                 # 每个形象可以有自己的文案文件
        add += ["--add-data", p + sep + os.path.basename(p)]

    cmd = [sys.executable, "-m", "PyInstaller", "--noconsole", "--onefile",
           "--name", a.name, "--distpath", os.path.join(tpl, "_dist"),
           "--workpath", os.path.join(tpl, "_build"),
           "--specpath", os.path.join(tpl, "_spec")] + add + [pet_py]
    print("打包中:", " ".join(cmd))
    r = subprocess.run(cmd)
    if r.returncode != 0:
        sys.exit("PyInstaller 打包失败")

    out = a.out or os.path.join(os.path.dirname(tpl), "dist_桌宠")
    os.makedirs(out, exist_ok=True)

    exe_name = a.name + (".exe" if sys.platform.startswith("win") else "")
    built = os.path.join(tpl, "_dist", exe_name)
    if not os.path.exists(built):   # Mac .app
        built = os.path.join(tpl, "_dist", a.name + ".app")
    if not os.path.exists(built):
        sys.exit("没找到打包产物，检查 _dist 目录")
    if os.path.isdir(built):
        shutil.copytree(built, os.path.join(out, os.path.basename(built)),
                        dirs_exist_ok=True)
    else:
        shutil.copy2(built, os.path.join(out, exe_name))

    # 可编辑资源放 exe 旁边（用户改这些就能定制，不用重打包）
    for item in EDITABLE + [os.path.basename(p) for p in dialogues]:
        src = os.path.join(tpl, item)
        dst = os.path.join(out, item)
        if not os.path.exists(src):
            continue
        if os.path.isdir(src):
            shutil.copytree(src, dst, dirs_exist_ok=True)
        else:
            shutil.copy2(src, dst)

    # 清理中间产物
    for junk in ("_dist", "_build", "_spec"):
        shutil.rmtree(os.path.join(tpl, junk), ignore_errors=True)

    print("\n✅ 交付目录: %s" % out)
    print("   提醒：Windows 上杀毒软件可能报毒（PyInstaller 常见误报），")
    print("   交付说明里已写明'添加信任即可'。")


if __name__ == "__main__":
    main()
