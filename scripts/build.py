# -*- coding: utf-8 -*-
"""
build.py — 把桌宠模板打包成可分发的成品（Windows .exe / Mac .app）

用法（在 template 目录的上级执行）：
    python build.py <template目录> [--name 桌面宠物] [--out 输出目录]

流程：
    1. 检查 PyInstaller（没装则提示 pip install pyinstaller）
    2. 打包 pet.py（--noconsole --onedir）。运行库是真实文件，启动时不再解压到临时目录。
    3. Windows 上把这个目录放到 assets/_stage，根目录的 exe 只是一个很小的启动器。
       已发布的 1.1.0 更新器只会整份覆盖 assets，运行库必须放在这里才能被带上。
    4. 可编辑资源仍放在启动器旁边（assets 里的图片、dialogues、config、源码）。

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


def find_csc():
    """用系统自带的 .NET Framework 编译器，CI 不需要再装 dotnet SDK。"""
    roots = (
        os.environ.get("WINDIR") or r"C:\Windows",
    )
    names = (
        os.path.join("Microsoft.NET", "Framework64", "v4.0.30319", "csc.exe"),
        os.path.join("Microsoft.NET", "Framework", "v4.0.30319", "csc.exe"),
    )
    for root in roots:
        for rel in names:
            path = os.path.join(root, rel)
            if os.path.isfile(path):
                return path
    return None


def compile_launcher(dest_exe):
    csc = find_csc()
    if not csc:
        sys.exit("找不到 csc.exe，无法编译启动器")
    src = os.path.join(os.path.dirname(os.path.abspath(__file__)), "stage_launcher.cs")
    if not os.path.isfile(src):
        sys.exit("找不到 %s" % src)
    cmd = [csc, "/nologo", "/target:winexe", "/optimize+",
           "/r:System.Windows.Forms.dll", "/out:" + dest_exe, src]
    print("编译启动器:", " ".join(cmd))
    r = subprocess.run(cmd)
    if r.returncode != 0 or not os.path.isfile(dest_exe):
        sys.exit("启动器编译失败")


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

    cmd = [sys.executable, "-m", "PyInstaller", "--noconsole", "--onedir",
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
    built_dir = os.path.join(tpl, "_dist", a.name)
    built_file = os.path.join(tpl, "_dist", exe_name)
    mac_app = os.path.join(tpl, "_dist", a.name + ".app")
    if sys.platform.startswith("win"):
        if not os.path.isdir(built_dir):
            sys.exit("没找到目录版打包产物，检查 _dist 目录")
        stage = os.path.join(out, "assets", "_stage")
        if os.path.isdir(stage):
            shutil.rmtree(stage)
        shutil.copytree(built_dir, stage)
        compile_launcher(os.path.join(out, exe_name))
    elif os.path.isdir(mac_app):
        shutil.copytree(mac_app, os.path.join(out, os.path.basename(mac_app)),
                        dirs_exist_ok=True)
    elif os.path.isdir(built_dir):
        shutil.copytree(built_dir, os.path.join(out, os.path.basename(built_dir)),
                        dirs_exist_ok=True)
    elif os.path.isfile(built_file):
        shutil.copy2(built_file, os.path.join(out, exe_name))
    else:
        sys.exit("没找到打包产物，检查 _dist 目录")

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
