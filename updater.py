# -*- coding: utf-8 -*-
"""
updater.py — 小仓鼠桌宠的自动更新器（纯逻辑，不依赖 tkinter，可在后台线程调用）

设计参照 ChromeClick3.0 的 AppUpdate.cs，按桌宠的交付形态做了三处适配：
  1. 用户数据就在 exe 旁边：覆盖安装采用白名单，且对 pets.json 做合并，
     绝不整目录 xcopy 覆盖掉用户的组件开关 / 形象 / 面板位置 / 喝水记录。
  2. 程序运行中无法覆盖自己的 exe 和运行库：生成 apply.cmd，等主进程退出后替换并重启。
     运行库是目录里的真实文件（assets/_stage），启动时不再解压到临时目录。
  3. 国内直连 GitHub 常超时：清单与下载都走「代理优先 → 直连兜底」。

典型调用（由 pet.py 在后台线程里驱动）：
    up = Updater(base_dir, repo="owner/repo", local_version="1.0.0")
    info = up.check()                      # None 表示已是最新 / 未配置
    extract = up.download(info, progress)  # 下载 + 安全解压
    payload = up.prepare_payload(extract)  # 白名单 + 配置合并
    up.apply(payload, exe_name)            # 写 apply.cmd 并拉起替换进程
    # 主进程随后自行退出即可
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.parse
import urllib.request
import zipfile

# 与 ChromeClick3.0 保持同一套国内镜像；实测三家均可直连 latest.json
PROXY_PREFIXES = (
    "https://gh-proxy.com/",
    "https://ghproxy.net/",
    "https://ghfast.top/",
)
GITHUB_HOSTS = frozenset({
    "github.com", "www.github.com",
    "objects.githubusercontent.com",
    "release-assets.githubusercontent.com",
})
USER_AGENT = "DesktopPet-Updater/1.0"

DEFAULT_SETTINGS = {
    "repo": "",                 # owner/repo；为空则跳过检查
    "enabled": True,
    "check_on_start": True,
    "start_delay_sec": 8,
    "china_manifest_url": "",   # 自有 Gitee / OSS 源，可选，最高优先
}

# 覆盖白名单：只有这些文件会被新版本替换
OVERWRITE_NAMES = frozenset({
    "小仓鼠桌宠.exe", "pet.py", "boat_fx.py", "updater.py",
    "version.json", "使用说明.txt", "README.md",
})
# 本机存在则原样保留；全新安装时才用发布包里的模板
PRESERVE_NAMES = ("config.json", "state.json", "update.json")
# 需要按「新版结构 + 用户选择 + 自定义形象」合并
MERGE_NAMES = ("pets.json",)
REQUIRED_FILES = ("小仓鼠桌宠.exe", "pet.py", "version.json")

MAX_UNCOMPRESSED = 400 * 1024 * 1024   # 防 zip bomb
MAX_ENTRIES = 8000                      # 目录版运行库文件很多，单文件时代的 800 不够
REPO_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")


class UpdateError(Exception):
    """检查 / 下载 / 安装阶段的可见错误，调用方应静默降级为「暂不更新」。"""


# ---------------------------------------------------------------- 基础工具
def read_json(path, default=None):
    try:
        with open(path, "r", encoding="utf-8-sig") as f:
            return json.load(f)
    except Exception:
        return {} if default is None else default


def write_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def parse_version(text):
    """'v1.2.3-beta' -> (1, 2, 3)；非法值返回 (0,0,0)。"""
    core = str(text or "").strip().lstrip("vV")
    core = re.split(r"[-+]", core, 1)[0]
    parts = core.split(".")
    out = []
    for i in range(3):
        try:
            out.append(max(0, int(parts[i])))
        except (IndexError, ValueError):
            out.append(0)
    return tuple(out)


def is_newer(remote, local):
    return parse_version(remote) > parse_version(local)


def load_version(base_dir):
    """版本号唯一来源是 exe 旁边的 version.json。"""
    data = read_json(os.path.join(base_dir, "version.json"))
    return str(data.get("version") or "0.0.0")


def load_settings(base_dir):
    data = read_json(os.path.join(base_dir, "update.json"))
    out = dict(DEFAULT_SETTINGS)
    out.update(data or {})
    return out


def is_github_file_url(url):
    try:
        p = urllib.parse.urlsplit(url)
        return p.scheme == "https" and (p.hostname or "").lower() in GITHUB_HOSTS
    except Exception:
        return False


def is_allowed_download_url(url):
    """manifest 里的 url 必须指向 GitHub 资源或受信任的代理，防止被劫持到任意地址。"""
    if not isinstance(url, str) or not url.startswith("https://"):
        return False
    if is_github_file_url(url):
        return True
    for prefix in PROXY_PREFIXES:
        if url.startswith(prefix) and is_github_file_url(url[len(prefix):]):
            return True
    return False


class UpdateInfo:
    def __init__(self, version, name="", zip_name="", url="", notes=""):
        self.version = str(version or "")
        self.name = str(name or "")
        self.zip = str(zip_name or "")
        self.url = str(url or "")
        self.notes = str(notes or "")

    @classmethod
    def from_json(cls, raw):
        if not isinstance(raw, dict) or not str(raw.get("version") or "").strip():
            raise UpdateError("更新信息格式无效")
        return cls(raw.get("version"), raw.get("name", ""),
                   raw.get("zip", ""), raw.get("url", ""),
                   raw.get("notes", ""))

    def __repr__(self):
        return "<UpdateInfo %s>" % self.version


# ---------------------------------------------------------------- 更新器
class Updater:
    def __init__(self, base_dir, repo="", local_version="0.0.0", log=None):
        self.base_dir = os.path.abspath(base_dir)
        self.repo = (repo or "").strip()
        self.local_version = local_version
        self.log = log or (lambda *_a, **_k: None)
        self._working_prefix = None
        self.last_feed_hint = ""
        self.work_dir = os.path.join(tempfile.gettempdir(), "DesktopPet-update")

    # ---- 地址
    def manifest_url(self):
        if not self.repo or not REPO_RE.match(self.repo):
            return None
        return ("https://github.com/%s/releases/latest/download/latest.json"
                % self.repo)

    def _ordered_prefixes(self):
        if self._working_prefix:
            yield self._working_prefix
        for p in PROXY_PREFIXES:
            if p != self._working_prefix:
                yield p

    def _manifest_candidates(self, settings):
        own = str(settings.get("china_manifest_url") or "").strip()
        if own.startswith("https://"):
            yield own
        base = self.manifest_url()
        if not base:
            return
        for p in self._ordered_prefixes():
            yield p + base
        yield base

    def _download_candidates(self, origin):
        seen = set()
        if is_github_file_url(origin):
            for p in self._ordered_prefixes():
                u = p + origin
                if u not in seen and is_allowed_download_url(u):
                    seen.add(u)
                    yield u
        if origin not in seen and is_allowed_download_url(origin):
            seen.add(origin)
            yield origin

    def _remember(self, url):
        self.last_feed_hint = "国内镜像" if url.startswith(PROXY_PREFIXES) else "GitHub"
        self._working_prefix = None
        for p in PROXY_PREFIXES:
            if url.startswith(p):
                self._working_prefix = p
                return

    def _fetch(self, url, timeout):
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read()

    # ---- 检查
    def check(self, settings=None, timeout=6):
        """返回更高版本的 UpdateInfo；未配置 / 已是最新 / 全线路失败时返回 None。

        异常统一收敛为 UpdateError，由调用方静默处理，不打断桌宠使用。
        """
        settings = settings or DEFAULT_SETTINGS
        if not settings.get("enabled", True):
            return None
        if not self.manifest_url():
            self.log("未配置 update.json 的 repo，跳过更新检查")
            return None

        last = None
        for url in self._manifest_candidates(settings):
            try:
                raw = json.loads(self._fetch(url, timeout).decode("utf-8-sig"))
                info = UpdateInfo.from_json(raw)
                self._remember(url)
                self.log("更新清单来自%s：本地 %s / 远端 %s"
                         % (self.last_feed_hint, self.local_version, info.version))
                return info if is_newer(info.version, self.local_version) else None
            except Exception as e:                  # 单条线路失败就换下一条
                last = e
                self.log("清单线路失败 %s: %s" % (url[:60], e))
        raise UpdateError("无法连接更新服务器（国内镜像与 GitHub 均失败）：%s" % last)

    # ---- 下载与解压
    def resolve_download_url(self, info):
        if info.url.strip():
            url = info.url.strip()
            if not is_allowed_download_url(url):
                raise UpdateError("更新地址无效，已拒绝下载")
            return url
        zip_name = info.zip.strip() or "DesktopPet.zip"
        if not zip_name or "/" in zip_name or "\\" in zip_name \
                or zip_name in (".", ".."):
            raise UpdateError("更新包文件名无效")
        ver = ".".join(map(str, parse_version(info.version)))
        return ("https://github.com/%s/releases/download/v%s/%s"
                % (self.repo, ver, urllib.parse.quote(zip_name)))

    def download(self, info, progress=None, timeout=30):
        """多线路下载 zip，返回安全解压目录。"""
        progress = progress or (lambda *_a, **_k: None)
        origin = self.resolve_download_url(info)
        if self.work_dir and os.path.isdir(self.work_dir):
            shutil.rmtree(self.work_dir, ignore_errors=True)
        extract_dir = os.path.join(self.work_dir, "extracted")
        os.makedirs(extract_dir, exist_ok=True)
        zip_path = os.path.join(self.work_dir, "package.zip")

        last = None
        for url in self._download_candidates(origin):
            try:
                progress(0, "正在从%s下载…" % (
                    "国内镜像" if url.startswith(PROXY_PREFIXES) else "GitHub"))
                req = urllib.request.Request(
                    url, headers={"User-Agent": USER_AGENT})
                with urllib.request.urlopen(req, timeout=timeout) as r, \
                        open(zip_path, "wb") as f:
                    total = int(r.headers.get("Content-Length") or 0)
                    read = 0
                    while True:
                        chunk = r.read(81920)
                        if not chunk:
                            break
                        f.write(chunk)
                        read += len(chunk)
                        if total:
                            progress(min(99, read * 100 // total),
                                     "已下载 %.1f / %.1f MB" % (
                                         read / 1048576, total / 1048576))
                self._remember(url)
                last = None
                break
            except Exception as e:
                last = e
                self.log("下载线路失败 %s: %s" % (url[:60], e))
                progress(0, "正在切换下载线路…")
                try:
                    os.remove(zip_path)
                except OSError:
                    pass
        if last is not None or not os.path.isfile(zip_path):
            raise UpdateError("下载更新包失败：%s" % last)

        progress(99, "正在校验并解压…")
        self.extract_safely(zip_path, extract_dir)
        missing = [n for n in REQUIRED_FILES
                   if not os.path.isfile(os.path.join(extract_dir, n))]
        if not self.runtime_present(extract_dir):
            missing.append(r"assets\_stage\_internal\python3.dll")
        if missing:
            raise UpdateError("更新包不完整，缺少：%s" % "、".join(missing))
        progress(100, "更新包已就绪")
        return extract_dir

    @staticmethod
    def extract_safely(zip_path, extract_dir):
        """路径穿越 / 绝对路径 / 超大包 / 超多条目 全部拒绝。"""
        root = os.path.abspath(extract_dir)
        prefix = root + os.sep
        with zipfile.ZipFile(zip_path) as z:
            entries = z.infolist()
            if len(entries) > MAX_ENTRIES:
                raise UpdateError("更新包条目过多，已拒绝安装")
            if sum(e.file_size for e in entries) > MAX_UNCOMPRESSED:
                raise UpdateError("更新包体积异常，已拒绝安装")
            for entry in entries:
                rel = entry.filename.replace("/", os.sep)
                if not entry.filename or entry.filename.endswith("/"):
                    continue
                if ".." in rel.replace("\\", "/").split("/") \
                        or os.path.isabs(rel) or ":" in rel.split(os.sep)[0]:
                    raise UpdateError("更新包路径无效，已拒绝安装")
                target = os.path.abspath(os.path.join(root, rel))
                if target != root and not target.startswith(prefix):
                    raise UpdateError("更新包路径越界，已拒绝安装")
                os.makedirs(os.path.dirname(target), exist_ok=True)
                with z.open(entry) as src, open(target, "wb") as dst:
                    shutil.copyfileobj(src, dst, 1024 * 256)

    # ---- 组装待覆盖文件（保护用户数据的核心）
    @staticmethod
    def merge_pets(local_path, new_path):
        """新版结构为基准，保留用户 active 与自定义形象，追加新版新增形象。"""
        new = read_json(new_path, {})
        local = read_json(local_path, {})
        if not local.get("pets"):
            return new
        out = dict(new)
        out["active"] = local.get("active") or new.get("active")
        ids = {x.get("id") for x in new.get("pets", []) if isinstance(x, dict)}
        merged = list(new.get("pets", []))
        for item in local.get("pets", []):
            if isinstance(item, dict) and item.get("id") not in ids:
                merged.append(item)
                ids.add(item.get("id"))
        out["pets"] = merged
        return out

    @staticmethod
    def runtime_present(extract_dir):
        """目录版运行库：python3xx.dll 必须在 assets/_stage/_internal 里。"""
        internal = os.path.join(extract_dir, "assets", "_stage", "_internal")
        try:
            names = os.listdir(internal)
        except OSError:
            return False
        return any(n.lower().startswith("python3") and n.lower().endswith(".dll")
                   for n in names)

    @staticmethod
    def _should_overwrite(rel):
        parts = rel.replace("\\", "/").split("/")
        name = parts[-1]
        if name in OVERWRITE_NAMES:
            return True
        # assets 含形象图，也含 _stage 里的目录版运行库。
        # 已发布的 1.1.0 只会整份覆盖 assets，所以运行库不能放到别处。
        if len(parts) > 1 and parts[0].lower() in ("assets", "_internal"):
            return True
        if name.startswith("dialogues") and name.endswith(".txt"):
            return True
        # 运行库直接放在 exe 旁边时（与 ChromeClick 的 dll 同级）一并覆盖
        if len(parts) == 1 and name.lower().endswith((".dll", ".pyd", ".zip")):
            return True
        return False

    def prepare_payload(self, extract_dir):
        """把「只该被覆盖的文件」挑进 payload，apply.cmd 才能安全地整目录 xcopy。"""
        payload = os.path.join(self.work_dir, "payload")
        if os.path.isdir(payload):
            shutil.rmtree(payload, ignore_errors=True)
        os.makedirs(payload, exist_ok=True)

        count = 0
        for root, _dirs, files in os.walk(extract_dir):
            for name in files:
                src = os.path.join(root, name)
                rel = os.path.relpath(src, extract_dir)
                if not self._should_overwrite(rel):
                    continue
                dst = os.path.join(payload, rel)
                os.makedirs(os.path.dirname(dst), exist_ok=True)
                shutil.copy2(src, dst)
                count += 1
        if count == 0:
            raise UpdateError("更新包里没有可安装的文件")

        # 用户数据：本机已有就绝不进 payload；全新安装才带模板
        for name in PRESERVE_NAMES:
            src = os.path.join(extract_dir, name)
            if os.path.isfile(src) and not os.path.exists(
                    os.path.join(self.base_dir, name)):
                shutil.copy2(src, os.path.join(payload, name))

        # 形象清单：合并后写进 payload（用户选择 + 自定义形象不丢）
        for name in MERGE_NAMES:
            src = os.path.join(extract_dir, name)
            if os.path.isfile(src):
                merged = self.merge_pets(os.path.join(self.base_dir, name), src)
                write_json(os.path.join(payload, name), merged)

        return payload

    # ---- 覆盖安装
    def apply(self, payload, exe_name="小仓鼠桌宠.exe", pid=None):
        """生成 apply.cmd：等主进程退出 → 备份旧 exe → 复制 payload → 重启。"""
        pid = int(pid or os.getpid())
        exe_path = os.path.join(self.base_dir, exe_name)
        backup = os.path.join(self.work_dir, "backup")
        os.makedirs(backup, exist_ok=True)
        if os.path.isfile(exe_path):
            try:
                shutil.copy2(exe_path, os.path.join(backup, exe_name))
            except OSError as e:
                self.log("旧版本备份失败（不阻断更新）：%s" % e)

        script = (
            "@echo off\n"
            "chcp 65001 >nul\n"
            'powershell -NoProfile -Command "Wait-Process -Id %d '
            '-ErrorAction SilentlyContinue; Start-Sleep -Seconds 1"\n'
            'xcopy /E /Y /Q /I "%s\\*" "%s\\" >nul\n'
            'if errorlevel 4 (\n'
            '  echo UPDATE_FAILED > "%s\\error.txt"\n'
            '  exit /b 1\n'
            ')\n'
            'start "" /D "%s" "%s"\n'
        ) % (pid, payload, self.base_dir, self.work_dir,
             self.base_dir, exe_path)
        bat = os.path.join(self.work_dir, "apply.cmd")
        # UTF-8 BOM + chcp 65001，保证中文路径在 cmd 里不乱码
        with open(bat, "w", encoding="utf-8-sig", newline="\r\n") as f:
            f.write(script)

        subprocess.Popen(["cmd.exe", "/c", bat], cwd=self.work_dir,
                         creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL)
        self.log("已启动替换进程，等待主程序退出后覆盖安装")
        return bat


def should_skip_automatic_check():
    """源码运行 / 自测模式不检查更新，避免开发时反复弹窗。"""
    return (not getattr(sys, "frozen", False)) or ("--selftest" in sys.argv)
