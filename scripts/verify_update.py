# -*- coding: utf-8 -*-
"""verify_update.py — 桌宠自动更新的离线专项验证。

完全确定性：urllib 与 subprocess 都被 mock，不访问网络、不真的替换文件。
在临时目录复制一份工程再跑，所有写操作都落临时目录，不污染用户设置。
"""
import glob
import importlib
import io
import json
import os
import shutil
import sys
import tempfile
import tkinter as tk
import urllib.request
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
results = []

MANIFEST = {
    "version": "1.1.0", "name": "小仓鼠桌宠",
    "zip": "DesktopPet.zip",
    "url": "https://github.com/wAwBill/DesktopPet/releases/download/v1.1.0/DesktopPet.zip",
    "runtime": "win-x64",
    "notes": "- 新增自动更新\n- 修复若干小问题",
}
EXE = "小仓鼠桌宠.exe"


def check(name, ok, detail=""):
    results.append((name, bool(ok), detail))
    print("%s %-46s %s" % ("[PASS]" if ok else "[FAIL]", name, detail))


def make_env(tmp):
    for name in ("pet.py", "boat_fx.py", "updater.py", "pets.json",
                 "config.json", "state.json", "version.json", "update.json",
                 "使用说明.txt", "README.md"):
        shutil.copy2(os.path.join(ROOT, name), os.path.join(tmp, name))
    for p in glob.glob(os.path.join(ROOT, "dialogues*.txt")):
        shutil.copy2(p, os.path.join(tmp, os.path.basename(p)))
    shutil.copytree(os.path.join(ROOT, "assets"), os.path.join(tmp, "assets"))
    # 测试环境固定为「未配置更新源」，不依赖工程里实际配置的正式仓库
    with open(os.path.join(tmp, "update.json"), "w", encoding="utf-8") as f:
        json.dump(dict(up_settings_empty()), f, ensure_ascii=False, indent=2)


def up_settings_empty():
    return {"repo": "", "enabled": True, "check_on_start": True,
            "start_delay_sec": 8}


def menu_labels(menu):
    out = []
    try:
        n = menu.index("end")
    except Exception:
        n = -1
    for i in range(n + 1):
        try:
            out.append(menu.entrycget(i, "label"))
        except Exception:
            pass
    return out


class FakeResp:
    def __init__(self, data, headers=None):
        self._data = data
        self.headers = headers or {}
        self.status = 200

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def read(self, n=-1):
        if n is None or n < 0:
            out, self._data = self._data, b""
            return out
        out, self._data = self._data[:n], self._data[n:]
        return out


def make_zip(files):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for name, data in files.items():
            z.writestr(name, data)
    return buf.getvalue()


def base_zip_bytes():
    return make_zip({
        EXE: b"MZ-fake-exe",
        "pet.py": b"# new pet.py",
        "boat_fx.py": b"# new boat_fx.py",
        "updater.py": b"# new updater.py",
        "version.json": json.dumps({"version": "1.1.0"}, ensure_ascii=False),
        "使用说明.txt": "new readme",
        "README.md": "new readme",
        "dialogues.txt": "new lines",
        "assets/pet.png": b"\x89PNG-new",
        "config.json": json.dumps({"city": "上海"}, ensure_ascii=False),
        "state.json": json.dumps({"water": 0, "date": ""}, ensure_ascii=False),
        "update.json": json.dumps({"repo": "wAwBill/DesktopPet"}, ensure_ascii=False),
        "pets.json": json.dumps({
            "active": "hamster",
            "pets": [{"id": "hamster", "name": "小仓鼠", "image": "assets/pet.png"},
                     {"id": "new_pet", "name": "新形象", "image": "assets/new.png"}],
        }, ensure_ascii=False),
        "assets/_stage/小仓鼠桌宠.exe": b"MZ-staged",
        "assets/_stage/_internal/python312.dll": b"MZ-runtime",
        "assets/_stage/_internal/PIL/_imaging.pyd": b"pyd",
        "private_notes.txt": "should not be installed",
    })


def main():
    tmp = tempfile.mkdtemp(prefix="pet_update_test_")
    try:
        make_env(tmp)
        sys.path.insert(0, tmp)
        import pet as pet_mod
        import updater as up_mod
        pet_mod.DesktopPet._start_tray = lambda self: None

        # ---------------- 纯函数
        check("版本解析容忍 v 前缀与预发布",
              up_mod.parse_version("v1.2.3-beta") == (1, 2, 3)
              and up_mod.parse_version("垃圾") == (0, 0, 0))
        check("版本比较正确",
              up_mod.is_newer("1.1.0", "1.0.0")
              and not up_mod.is_newer("1.0.0", "1.1.0")
              and not up_mod.is_newer("1.0.0", "1.0.0"))
        check("下载 URL 白名单：GitHub / 代理放行",
              up_mod.is_allowed_download_url(MANIFEST["url"])
              and up_mod.is_allowed_download_url(
                  "https://gh-proxy.com/" + MANIFEST["url"]))
        check("下载 URL 白名单：http / 任意域名拒绝",
              not up_mod.is_allowed_download_url("http://github.com/a/b")
              and not up_mod.is_allowed_download_url("https://evil.example.com/x.zip")
              and not up_mod.is_allowed_download_url("https://gh-proxy.com/https://evil.com/x"))
        check("源码运行跳过自动检查",
              up_mod.should_skip_automatic_check() is True)

        # ---------------- 配置与地址
        with open(os.path.join(ROOT, "update.json"), encoding="utf-8-sig") as f:
            live = json.load(f)
        check("工程 update.json 已配置正式更新源",
              live.get("repo") == "wAwBill/DesktopPet", str(live.get("repo")))
        zpath = os.path.join(ROOT, "publish", "DesktopPet.zip")
        if os.path.isfile(zpath):
            with zipfile.ZipFile(zpath) as z:
                pkg = json.loads(z.read("update.json").decode("utf-8-sig"))
            check("发布包 update.json 已写入正式更新源",
                  pkg.get("repo") == "wAwBill/DesktopPet", str(pkg.get("repo")))

        settings = up_mod.load_settings(tmp)
        check("默认 update.json 的 repo 为空（跳过检查）",
              settings.get("repo") == "" and settings.get("enabled") is True)
        check("version.json 是唯一版本源",
              up_mod.load_version(tmp) == "1.1.1",
              up_mod.load_version(tmp))
        up0 = up_mod.Updater(tmp, repo="", local_version="1.0.0")
        check("repo 为空时 manifest_url 为 None",
              up0.manifest_url() is None)
        check("repo 未配置时 check 直接返回 None", up0.check(settings) is None)
        up_bad = up_mod.Updater(tmp, repo="../../evil", local_version="1.0.0")
        check("非法 repo 格式被拒绝", up_bad.manifest_url() is None)

        repo = "wAwBill/DesktopPet"
        up = up_mod.Updater(tmp, repo=repo, local_version="1.0.0")
        check("manifest 地址指向 releases/latest/download",
              up.manifest_url().endswith("/releases/latest/download/latest.json"),
              up.manifest_url())
        cands = list(up._manifest_candidates({"china_manifest_url": ""}))
        check("清单线路：3 个代理 + 1 个直连", len(cands) == 4, str(len(cands)))
        check("清单线路代理在前、直连兜底",
              cands[0].startswith("https://gh-proxy.com/")
              and cands[-1] == up.manifest_url())
        own = list(up._manifest_candidates(
            {"china_manifest_url": "https://gitee.com/x/latest.json"}))
        check("自有国内源优先级最高", own[0].startswith("https://gitee.com/"))
        dc = list(up._download_candidates(MANIFEST["url"]))
        check("下载线路同样代理优先 + 直连兜底",
              len(dc) == 4 and dc[0].startswith("https://gh-proxy.com/")
              and dc[-1] == MANIFEST["url"])
        info = up_mod.UpdateInfo.from_json(MANIFEST)
        check("resolve_download_url 优先用 manifest.url",
              up.resolve_download_url(info) == MANIFEST["url"])
        info2 = up_mod.UpdateInfo("1.1.0", zip_name="DesktopPet.zip")
        check("无 url 时按 repo + 版本 + zip 拼地址",
              up.resolve_download_url(info2).endswith(
                  "/releases/download/v1.1.0/DesktopPet.zip"),
              up.resolve_download_url(info2))
        bad = up_mod.UpdateInfo("1.1.0", url="https://evil.example.com/x.zip")
        try:
            up.resolve_download_url(bad)
            check("恶意 url 被拒绝", False)
        except up_mod.UpdateError:
            check("恶意 url 被拒绝", True)

        # ---------------- 检查：多线路、版本、失败
        calls = []

        def fake_open(req, timeout=None):
            url = getattr(req, "full_url", str(req))
            calls.append(url)
            if url.startswith("https://gh-proxy.com/"):
                raise OSError("proxy down")
            if "latest.json" in url:
                return FakeResp(json.dumps(MANIFEST, ensure_ascii=False).encode("utf-8"))
            if url.endswith(".zip"):
                return FakeResp(base_zip_bytes(),
                                {"Content-Length": str(len(base_zip_bytes()))})
            raise OSError("unexpected url " + url)

        up_mod.urllib.request.urlopen = fake_open
        got = up.check({**settings, "repo": repo})
        check("首条代理失败后自动切换下一条",
              got is not None and got.version == "1.1.0",
              "尝试 %d 条线路" % len(calls))
        check("记住可用镜像，下次优先命中",
              up._working_prefix is not None
              and list(up._manifest_candidates({"china_manifest_url": ""}))[0]
                 .startswith(up._working_prefix),
              str(up._working_prefix))
        check("notes 完整保留", "新增自动更新" in got.notes)
        check("远端版本不高于本地时返回 None",
              up_mod.Updater(tmp, repo, "1.1.0").check(
                  {**settings, "repo": repo}) is None)
        check("enabled=false 时跳过检查",
              up.check({**settings, "repo": repo, "enabled": False}) is None)

        def all_fail(*a, **k):
            raise OSError("offline")

        up_mod.urllib.request.urlopen = all_fail
        try:
            up.check({**settings, "repo": repo})
            check("全线路失败抛 UpdateError", False)
        except up_mod.UpdateError:
            check("全线路失败抛 UpdateError", True)

        # ---------------- 下载与安全解压
        up_mod.urllib.request.urlopen = fake_open
        progress = []
        extract = up.download(got, lambda p, t: progress.append((p, t)))
        check("下载并解压出必备文件",
              all(os.path.isfile(os.path.join(extract, n))
                  for n in up_mod.REQUIRED_FILES)
              and up_mod.Updater.runtime_present(extract))
        check("下载进度回调被触发且到 100",
              any(p == 100 for p, _t in progress) and len(progress) >= 2,
              "%d 次回调" % len(progress))
        check("zip 内其它文件也解压出来了",
              os.path.isfile(os.path.join(extract, "private_notes.txt")))

        evil_cases = {
            "路径穿越": {"../evil.txt": b"x"},
            "绝对路径": {"/etc/evil.txt": b"x"},
            "盘符路径": {"C:/evil.txt": b"x"},
        }
        for label, files in evil_cases.items():
            evil_zip = os.path.join(tmp, "evil.zip")
            with open(evil_zip, "wb") as f:
                f.write(make_zip(files))
            try:
                up.extract_safely(evil_zip, os.path.join(tmp, "evil_out"))
                check("%s 被拒绝" % label, False)
            except up_mod.UpdateError:
                check("%s 被拒绝" % label, True)
        big_zip = os.path.join(tmp, "big.zip")
        with open(big_zip, "wb") as f:
            f.write(make_zip({}))
        check("空 zip 可通过基础路径校验",
              up.extract_safely(big_zip, os.path.join(tmp, "empty_out")) is None)

        # ---------------- 白名单与用户数据保护
        base = os.path.join(tmp, "installed")
        os.makedirs(base, exist_ok=True)
        user_cfg = {"city": "广州", "components": {"quota": False, "feed": True}}
        user_state = {"water": 7, "panel_x": 1234, "panel_y": 567}
        user_update = {"repo": "wAwBill/MyFork"}
        user_pets = {
            "active": "luoxiaohei_3d",
            "pets": [{"id": "luoxiaohei_3d", "name": "罗小黑 · 3D 版",
                      "image": "assets/luoxiaohei_3d.png"},
                     {"id": "my_cat", "name": "我家猫", "image": "assets/my.png"}],
        }
        for name, data in (("config.json", user_cfg), ("state.json", user_state),
                           ("update.json", user_update), ("pets.json", user_pets)):
            with open(os.path.join(base, name), "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False)
        with open(os.path.join(base, EXE), "wb") as f:
            f.write(b"MZ-old-exe")

        up2 = up_mod.Updater(base, repo, "1.0.0")
        payload = up2.prepare_payload(extract)
        pnames = []
        for root, _d, files in os.walk(payload):
            for n in files:
                pnames.append(os.path.relpath(os.path.join(root, n), payload)
                              .replace("\\", "/"))
        check("payload 含主程序与源码",
              EXE in pnames and "pet.py" in pnames and "updater.py" in pnames)
        check("payload 含 assets 与文案",
              "assets/pet.png" in pnames and "dialogues.txt" in pnames)
        check("payload 含目录版运行库",
              "assets/_stage/_internal/python312.dll" in pnames
              and "assets/_stage/_internal/PIL/_imaging.pyd" in pnames
              and "assets/_stage/小仓鼠桌宠.exe" in pnames)
        for name in ("config.json", "state.json", "update.json"):
            check("用户数据不进 payload：%s" % name, name not in pnames)
        check("非白名单文件不进 payload",
              "private_notes.txt" not in pnames)
        merged = json.load(open(os.path.join(payload, "pets.json"),
                                encoding="utf-8"))
        ids = [x["id"] for x in merged["pets"]]
        check("pets.json 合并保留用户 active",
              merged["active"] == "luoxiaohei_3d", merged["active"])
        check("pets.json 合并保留用户自定义形象", "my_cat" in ids)
        check("pets.json 合并追加新版形象", "new_pet" in ids, str(ids))
        check("pets.json 合并以新版结构为基准",
              "_字段" in merged or merged.get("pets") is not None)

        # 全新安装（本机无用户数据）应带模板
        fresh = os.path.join(tmp, "fresh")
        os.makedirs(fresh, exist_ok=True)
        payload2 = up_mod.Updater(fresh, repo, "1.0.0").prepare_payload(extract)
        check("全新安装带干净模板",
              all(os.path.isfile(os.path.join(payload2, n))
                  for n in ("config.json", "state.json", "update.json", "pets.json")))
        st = json.load(open(os.path.join(payload2, "state.json"), encoding="utf-8"))
        check("全新安装 state.json 是空模板", st.get("water") == 0)

        layout = os.path.join(tmp, "layout")
        stage_dir = os.path.join(layout, "assets", "_stage")
        os.makedirs(stage_dir)
        with open(os.path.join(layout, "version.json"), "w", encoding="utf-8") as f:
            f.write("{}")
        flat = os.path.join(tmp, "flat")
        os.makedirs(flat)
        with open(os.path.join(flat, "version.json"), "w", encoding="utf-8") as f:
            f.write("{}")
        check("运行库在 assets/_stage 时用户目录仍是安装根",
              os.path.normcase(pet_mod.install_base_dir(stage_dir))
              == os.path.normcase(layout))
        check("运行库与 version.json 同级时用户目录就是该目录",
              os.path.normcase(pet_mod.install_base_dir(flat))
              == os.path.normcase(flat))

        # ---------------- apply.cmd
        launched = []
        up_mod.subprocess.Popen = lambda *a, **k: launched.append((a, k)) or object()
        bat = up2.apply(payload, EXE, pid=424242)
        script = open(bat, "rb").read()
        check("apply.cmd 写入 UTF-8 BOM", script.startswith(b"\xef\xbb\xbf"))
        text = script.decode("utf-8-sig")
        check("apply.cmd 等待主进程退出", "Wait-Process -Id 424242" in text)
        check("apply.cmd 只复制 payload 到安装目录",
              "xcopy /E /Y /Q /I" in text and payload in text and base in text)
        check("apply.cmd 替换后重启主程序",
              "start \"\" /D" in text and EXE in text)
        check("apply.cmd 已拉起独立进程", len(launched) == 1)
        check("旧 exe 已备份",
              os.path.isfile(os.path.join(up2.work_dir, "backup", EXE)))

        # ---------------- pet.py 接线
        app = pet_mod.DesktopPet()
        said = []
        app.say = lambda text, *a, **k: said.append(text)
        labels = menu_labels(app.menu)
        check("菜单含「检查更新（当前版本）」",
              any(s.startswith("检查更新（当前 v1.1.1）") for s in labels),
              next((s for s in labels if s.startswith("检查更新")), ""))
        check("实例已加载版本号与更新器",
              app.app_version == "1.1.1" and app._updater is not None)
        check("未配置 repo 时手动检查只提示、不联网",
              (app._manual_update_check() or True)
              and any("尚未配置更新仓库" in s for s in said), str(said[-1:]))
        check("_tick_fast 会消费 _update_q",
              "_handle_update_event(self._update_q.pop(0))" in
              open(os.path.join(tmp, "pet.py"), encoding="utf-8").read())

        app._handle_update_event(("checked", None, True))
        check("已是最新版本时提示用户",
              any("已是最新版本" in s for s in said), str(said[-1:]))
        app._handle_update_event(("check_failed", "offline", False))
        check("自动检查失败静默不打扰",
              not any("检查更新失败" in s for s in said))
        app._open_progress()
        app._handle_update_event(("progress", 63, "已下载 6.0 MB"))
        check("下载进度驱动 UI 变量",
              app._upd_pct.get() == 63 and app._upd_text.get() == "已下载 6.0 MB")
        app._close_progress()
        check("进度窗可正常关闭",
              app._upd_win is None and app._upd_text is None)
        app._ask_update(info)
        tops = [w for w in app.root.winfo_children() if isinstance(w, tk.Toplevel)]
        check("发现新版本弹出确认框",
              any(w.title() == "发现新版本" for w in tops))
        app.quit()

        # ---------------- 线上真实链路（可选，不计入通过率）
        importlib.reload(urllib.request)
        try:
            req = urllib.request.Request(
                "https://gh-proxy.com/https://github.com/wAwBill/"
                "ChromeClickReleases/releases/latest/download/latest.json",
                headers={"User-Agent": "DesktopPet-Updater/1.0"})
            with urllib.request.urlopen(req, timeout=10) as r:
                d = json.loads(r.read().decode("utf-8-sig"))
            check("线上经代理可拉取 Release 清单",
                  bool(d.get("version")), "远端版本 %s" % d.get("version"))
        except Exception as e:
            print("[SKIP] 线上代理不可达（不计入通过率）: %s" % e)

    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    ok = sum(1 for _, v, _ in results if v)
    print("\n===== 自动更新专项：%d/%d PASS =====" % (ok, len(results)))
    for n, v, d in results:
        if not v:
            print("  FAIL:", n, d)
    return 0 if ok == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
