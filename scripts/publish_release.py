# -*- coding: utf-8 -*-
"""生成发布包 DesktopPet.zip 与 latest.json。

纯 Python 实现，供 GitHub Actions 与本机共用：
    python scripts/publish_release.py --version v1.0.0 --repo owner/repo

替代早前的 publish-release.ps1 —— CI 的 PowerShell 版本/执行策略与本机
不一致会导致同一脚本在云端失败，而 Python 链路（build.py + PyInstaller）
在本机与 CI 完全一致。
"""

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import traceback
import zipfile

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
EXE_NAME = "小仓鼠桌宠.exe"
REQUIRED = (EXE_NAME, "pet.py", "boat_fx.py", "updater.py",
            "version.json", "update.json", "config.json", "pets.json",
            "state.json", "使用说明.txt")
EMPTY_STATE = {
    "date": "", "water": 0, "quota_used": 0, "affection": 0,
    "todos": [], "panel_x": None, "panel_y": None, "boat_prev_pet": "",
}


def read_json(path):
    with open(path, "r", encoding="utf-8-sig") as f:
        return json.load(f)


def write_json(path, data):
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def emit_error(msg):
    """输出 GitHub Actions workflow command（本地运行时只是普通一行文本）。"""
    text = str(msg).replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")
    print("::error::" + text, flush=True)


def main():
    ap = argparse.ArgumentParser(description="生成桌宠发布包与更新清单")
    ap.add_argument("--version", default="", help="tag 版本，如 v1.0.0；默认读 version.json")
    ap.add_argument("--repo", default="", help="更新源 owner/repo")
    ap.add_argument("--out", default="", help="输出目录，默认 <工程>/publish")
    ap.add_argument("--python", default=sys.executable, help="用于打包的 Python 解释器")
    ap.add_argument("--skip-build", action="store_true", help="复用 out/app 里已有的 exe")
    a = ap.parse_args()

    vmeta = read_json(os.path.join(ROOT, "version.json"))
    app_version = str(vmeta["version"])
    app_name = str(vmeta.get("name") or "小仓鼠桌宠")
    zip_name = str(vmeta.get("zip") or "DesktopPet.zip")

    version = (a.version or app_version).strip().lstrip("vV")
    if not re.match(r"^\d+\.\d+\.\d+$", version):
        raise RuntimeError("版本号格式无效：%s" % version)
    if version != app_version:
        raise RuntimeError("tag 版本 %s 与 version.json 的 %s 不一致" % (version, app_version))

    notes_path = os.path.join(ROOT, "Docs", "发布", "本版更新说明.txt")
    with open(notes_path, "r", encoding="utf-8-sig") as f:
        notes = f.read().strip()
    if not notes or re.search(r"TODO|示例|在此填写", notes):
        raise RuntimeError("本版更新说明.txt 为空或仍是模板套话")

    repo = (a.repo or "").strip()
    if not repo:
        repo = str(read_json(os.path.join(ROOT, "update.json")).get("repo") or "").strip()
    if not repo or not re.match(r"^[\w.-]+/[\w.-]+$", repo):
        raise RuntimeError("发版必须指定 --repo owner/repo，或填好 update.json 的 repo")

    out = os.path.abspath(a.out or os.path.join(ROOT, "publish"))
    stage = os.path.join(out, "app")
    if os.path.isdir(out):
        shutil.rmtree(out)
    os.makedirs(stage)

    # ---- 打包主程序（复用本机已验证的 build.py）
    if not a.skip_build:
        cmd = [a.python, os.path.join(ROOT, "scripts", "build.py"), ROOT,
               "--name", "小仓鼠桌宠", "--out", stage]
        print("打包中: %s" % " ".join(cmd), flush=True)
        rc = subprocess.run(cmd, cwd=ROOT).returncode
        if rc != 0:
            raise RuntimeError("PyInstaller 打包失败，退出码 %d" % rc)
    elif not os.path.isfile(os.path.join(stage, EXE_NAME)):
        raise RuntimeError("--skip-build 需要 %s 里已有 exe" % stage)

    # ---- 用户数据换成干净模板，绝不把本机设置发布到公开仓库
    for name in ("config.json", "pets.json"):
        shutil.copy2(os.path.join(ROOT, name), os.path.join(stage, name))
    write_json(os.path.join(stage, "state.json"), EMPTY_STATE)

    for name in ("version.json", "update.json", "updater.py", "README.md"):
        src, dst = os.path.join(ROOT, name), os.path.join(stage, name)
        if os.path.isfile(src) and not os.path.isfile(dst):
            shutil.copy2(src, dst)

    # 发布包必须自带正式更新源，否则新用户解压后自动更新会静默失效
    u = read_json(os.path.join(stage, "update.json"))
    u["repo"] = repo
    write_json(os.path.join(stage, "update.json"), u)

    # ---- 打包前校验
    missing = [n for n in REQUIRED if not os.path.isfile(os.path.join(stage, n))]
    if missing:
        raise RuntimeError("发布目录缺少：%s" % ", ".join(missing))
    st = read_json(os.path.join(stage, "state.json"))
    if st.get("water") != 0 or st.get("date") != "":
        raise RuntimeError("state.json 不是空模板，可能把用户数据带进公开仓库")
    if str(read_json(os.path.join(stage, "version.json")).get("version")) != version:
        raise RuntimeError("发布包内版本号与 tag 不一致")
    if str(read_json(os.path.join(stage, "update.json")).get("repo")) != repo:
        raise RuntimeError("发布包内更新源与 --repo 不一致")

    # ---- zip：文件名必须英文，路径分隔符必须是 /
    zip_path = os.path.join(out, zip_name)
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
        for base, _dirs, files in os.walk(stage):
            for fn in files:
                full = os.path.join(base, fn)
                z.write(full, os.path.relpath(full, stage).replace(os.sep, "/"))
    if not os.path.isfile(zip_path):
        raise RuntimeError("生成 %s 失败" % zip_name)

    # ---- latest.json + 供 gh 使用的英文路径说明文件（避开中文参数）
    latest = {
        "version": version,
        "name": app_name,
        "zip": zip_name,
        "url": "https://github.com/%s/releases/download/v%s/%s" % (repo, version, zip_name),
        "runtime": "win-x64",
        "notes": notes,
    }
    write_json(os.path.join(out, "latest.json"), latest)
    with open(os.path.join(out, "notes.txt"), "w", encoding="utf-8") as f:
        f.write(notes)

    print("已生成 %s (%.1f MB)" % (zip_path, os.path.getsize(zip_path) / 1048576.0), flush=True)
    print("已生成 %s" % os.path.join(out, "latest.json"), flush=True)
    print("version=%s repo=%s url=%s" % (version, repo, latest["url"]), flush=True)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        traceback.print_exc()
        emit_error("发布失败：%s: %s" % (type(exc).__name__, exc))
        sys.exit(1)
