# -*- coding: utf-8 -*-
"""
桌面宠物模板程序 pet.py
========================
基于 tkinter + Pillow 的桌面宠物：
透明无边框置顶窗口、拖动、点击互动动画、中文对话气泡、右键菜单、
滚轮缩放、空闲动作、自动巡逻、16 个可开关趣味组件。

动画设计（避免"僵硬感"的关键）：
- 呼吸基线：任何时候都有微弱的缩放+摇摆循环，单图角色也是"活的"；
- 缓动：所有动作都是弹簧阻尼/抛物线曲线，不是线性分步；
- 预备与回弹：跳跃有蓄力-腾空-落地回弹三段，点击是过冲弹簧；
- 巡逻：移动时带上下颠簸和行进方向倾斜，不是匀速平移贴图；
- 划船形象（pets.json 里 fx="boat"）：滚动水浪 + 摆动船桨 + 入水水花，
  由 boat_fx.py 按 24 个相位预渲染，巡逻时加速、静止时缓慢漂。

运行方式：
    python pet.py             正常运行
    python pet.py --selftest  冒烟自测（3 秒后自动退出）

打包（生成 exe / app）见同目录 build.py 与「使用说明.txt」。
代码注释尽量写全，方便二次修改。
"""

import json
import math
import os
import platform
import random
import subprocess
import sys
import tempfile
import threading
import time
import tkinter as tk
from tkinter import ttk
from datetime import datetime, date, timedelta

try:
    from PIL import Image, ImageTk, ImageChops
except ImportError:
    sys.stderr.write("缺少 Pillow：pip install Pillow\n")
    sys.exit(1)

try:
    from boat_fx import BoatFX
except ImportError:                       # 单独拷走 pet.py 也不至于起不来
    BoatFX = None

try:
    import updater as updater_mod
except ImportError:                       # 更新器缺失时桌宠照常运行
    updater_mod = None

IS_WIN = sys.platform.startswith("win")
IS_MAC = sys.platform == "darwin"
SELFTEST = "--selftest" in sys.argv

# wttr.in 不传地名时会按请求出口 IP 反查 nearest_area，返回的是英文地名。
# 这里把常见国内城市翻成中文，只用于面板显示；不认识的地名原样显示。
CN_CITY = {
    "beijing": "北京", "shanghai": "上海", "guangzhou": "广州",
    "shenzhen": "深圳", "hangzhou": "杭州", "chengdu": "成都",
    "chongqing": "重庆", "wuhan": "武汉", "nanjing": "南京",
    "tianjin": "天津", "xian": "西安", "xi'an": "西安", "suzhou": "苏州",
    "zhengzhou": "郑州", "changsha": "长沙", "qingdao": "青岛",
    "shenyang": "沈阳", "dalian": "大连", "jinan": "济南",
    "fuzhou": "福州", "xiamen": "厦门", "kunming": "昆明",
    "hefei": "合肥", "ningbo": "宁波", "dongguan": "东莞",
    "foshan": "佛山", "harbin": "哈尔滨", "changchun": "长春",
    "shijiazhuang": "石家庄", "taiyuan": "太原", "nanchang": "南昌",
    "guiyang": "贵阳", "nanning": "南宁", "lanzhou": "兰州",
    "urumqi": "乌鲁木齐", "hohhot": "呼和浩特", "haikou": "海口",
    "sanya": "三亚", "hong kong": "香港", "macao": "澳门",
    "macau": "澳门", "taipei": "台北", "pootung": "浦东",
    "pudong": "浦东", "wuxi": "无锡", "wenzhou": "温州",
    "zhuhai": "珠海", "zhongshan": "中山", "huizhou": "惠州",
    "quanzhou": "泉州", "nantong": "南通", "xuzhou": "徐州",
}


def _geo_first(v):
    """nearest_area 的字段可能是 [{"value": x}]，也可能直接是字符串。"""
    if isinstance(v, list):
        if not v:
            return ""
        x = v[0]
        return str(x.get("value", "")) if isinstance(x, dict) else str(x)
    return str(v or "")

# ---------------------------------------------------------------- 路径
# 打包成 exe 后：可编辑资源（assets/dialogues/config）放在安装目录。
# 真正的程序在 assets/_stage，根目录的 exe 只负责把它拉起来；
# 源码运行时：放在 pet.py 旁边。BUNDLE_DIR 是 PyInstaller 内嵌资源的兜底。
def install_base_dir(exe_dir):
    """向上最多两级寻找 version.json。

    目录版的 sys.executable 在 assets/_stage 里，用户数据仍在安装根目录。
    运行库若已经和 version.json 放在同一层，就用那一层。
    """
    cur = os.path.abspath(exe_dir)
    for _ in range(3):
        if os.path.isfile(os.path.join(cur, "version.json")):
            return cur
        parent = os.path.dirname(cur)
        if parent == cur:
            break
        cur = parent
    return os.path.abspath(exe_dir)


if getattr(sys, "frozen", False):
    _EXE_DIR = os.path.dirname(os.path.abspath(sys.executable))
    BASE_DIR = install_base_dir(_EXE_DIR)
    BUNDLE_DIR = getattr(sys, "_MEIPASS", _EXE_DIR)
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
    BUNDLE_DIR = BASE_DIR


def res(*parts):
    """用户可编辑资源：优先取程序旁边那份，没有再取打包内嵌的。"""
    p = os.path.join(BASE_DIR, *parts)
    if not os.path.exists(p):
        p = os.path.join(BUNDLE_DIR, *parts)
    return p


CONFIG_PATH = os.path.join(BASE_DIR, "config.json")
STATE_PATH = os.path.join(BASE_DIR, "state.json")
PETS_PATH = os.path.join(BASE_DIR, "pets.json")

CHROMA = "#ff00ff"          # Windows 透明色键（角色图里别用纯品红）
DRAG_THRESHOLD = 6          # 防误触：移动超过 6px 算拖动，否则算点击
DEFAULT_HEIGHT = 180        # 桌宠默认高度 px（建议 150-200）
ANIM_MS = 40                # 动画帧间隔（25fps），呼吸与动作共用一个循环


# ---------------------------------------------------------------- 配置与状态
DEFAULT_CONFIG = {
    "pet_height_px": DEFAULT_HEIGHT,
    "opacity": 1.0,
    "topmost": True,
    "auto_patrol": False,          # 自动巡逻，默认关；开启后自动换成划船形象
    "follow_mouse": False,         # 跟随鼠标，默认关
    "boat_fx": True,               # 划船形象的水浪/船桨动画总开关
    "fullscreen_hide": False,      # 全屏自动隐藏（仅提示用，见说明）
    "city": "北京",                  # 手动指定的城市名（中文/拼音/英文都行）
    "city_auto": False,              # 按网络出口 IP 自动定位；默认关，保持手工城市行为
    "city_coord": "",                # 自动定位得到的 "纬度,经度"，缓存用
    "city_auto_label": "",           # 自动定位得到的显示名，缓存用
    "offwork_time": "18:00",
    "water_goal": 8,
    "daily_quota_limit": 100,
    "pomodoro_work_min": 25,
    "pomodoro_break_min": 5,
    "fish_idle_sec": 300,          # 摸鱼检测灵敏度：多少秒无操作算摸鱼
    "idle_action_min_sec": 8,      # 随机小动作最短间隔（秒）
    "idle_action_max_sec": 20,     # 随机小动作最长间隔（秒）
    "quick_launch": [],            # [{"name": "微信", "path": "C:/.../WeChat.exe"}]
    "components": {                # 默认只开 4 个轻量组件
        "quota": True, "offwork": True, "water": True, "weather": True,
        "clock": False, "system_status": False, "pomodoro": False,
        "todo": False, "fish_detect": False, "daily_quote": False,
        "feed": False, "affection": False, "quick_launch": False,
        "volume": False, "screenshot": False,
    },
}

DEFAULT_STATE = {
    "date": "",                    # 上次运行的日期，用于每日重置
    "water": 0,
    "quota_used": 0,
    "affection": 0,
    "todos": [],                   # [{"text": "...", "done": false}]
    "last_feed": "",               # 上次投喂日期
    "last_water_remind": 0,
    "celebrated_offwork": "",      # 今天是否已庆祝过下班
    "gloomy_noticed": "",
    "panel_x": None,               # 信息面板独立坐标；None = 默认贴屏幕右下角
    "panel_y": None,
    "boat_prev_pet": "",           # 开巡逻前的形象 id，关巡逻时自动还原
}


def load_json(path, default):
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        out = dict(default)
        out.update(data)
        if "components" in default:
            comp = dict(default["components"])
            comp.update(data.get("components", {}))
            out["components"] = comp
        return out
    except Exception:
        return dict(default)


def save_json(path, data):
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print("写入失败", path, e)


# ---------------------------------------------------------------- 文案加载
# ---------------------------------------------------------------- 宠物形象
# 每一项就是一个「形象」：同一个角色可以有多个形象（原画 / 3D / 表情包…）。
# 用户编辑 exe 旁边的 pets.json 即可增删，程序会过滤掉图片不存在的条目。
DEFAULT_PETS = {
    "active": "hamster",
    "pets": [
        {"id": "hamster", "name": "小仓鼠", "image": "assets/pet.png",
         "dialogues": "dialogues.txt", "greeting": "哼，你们惹毛我了！"},
        {"id": "luoxiaohei", "name": "罗小黑", "image": "assets/luoxiaohei.png",
         "dialogues": "dialogues_luoxiaohei.txt", "greeting": "……（看了你一眼）"},
        {"id": "luoxiaohei_3d", "name": "罗小黑 · 3D 版",
         "image": "assets/luoxiaohei_3d.png",
         "dialogues": "dialogues_luoxiaohei.txt",
         "greeting": "……（毛茸茸地眨了眨眼）"},
        {"id": "luoxiaohei_boat", "name": "罗小黑 · 划船巡逻",
         "image": "assets/luoxiaohei_boat.png",
         "dialogues": "dialogues_luoxiaohei.txt",
         "greeting": "……出发，去巡逻啦",
         "fx": "boat", "height_px": 220},
    ],
}


def res_path(rel):
    """pets.json 里的相对路径 -> 实际路径（统一用 / 书写）。"""
    return res(*str(rel).replace("\\", "/").split("/"))


def load_pets():
    """读取 pets.json，返回 {"active": id, "pets": [规范化的形象...]}。"""
    try:
        with open(PETS_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        data = {}
    raw = data.get("pets") or DEFAULT_PETS["pets"]
    if not isinstance(raw, list):
        raw = DEFAULT_PETS["pets"]
    pets = []
    for i, p in enumerate(raw):
        if not isinstance(p, dict) or not p.get("image"):
            continue
        item = {
            "id": str(p.get("id") or "pet%d" % i),
            "name": str(p.get("name") or "宠物%d" % (i + 1)),
            "image": str(p["image"]),
            "dialogues": str(p.get("dialogues") or "dialogues.txt"),
            "greeting": str(p.get("greeting") or ""),
            "frames": str(p.get("frames") or ""),
            "fx": str(p.get("fx") or ""),
            "height_px": p.get("height_px"),
        }
        if os.path.exists(res_path(item["image"])):
            pets.append(item)
        else:
            print("跳过形象 %s：找不到 %s" % (item["name"], item["image"]))
    if not pets:                                  # 一张图都没有时退回内置占位球
        p = DEFAULT_PETS["pets"][0]
        pets = [{"id": p["id"], "name": p["name"], "image": p["image"],
                 "dialogues": p["dialogues"], "greeting": p["greeting"],
                 "frames": "", "fx": "", "height_px": None}]
    active = str(data.get("active") or DEFAULT_PETS["active"])
    if active not in [x["id"] for x in pets]:
        active = pets[0]["id"]
    return {"active": active, "pets": pets}


def save_active_pet(pet_id):
    """只更新 active 字段，保留用户手写的所有形象条目与说明，不整体覆写。"""
    try:
        with open(PETS_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            data = {}
    except Exception:
        data = {}
    data["active"] = pet_id
    save_json(PETS_PATH, data)


def load_dialogues(path):
    """dialogues.txt 按 `# [分区]` 组织，返回 {分区: [文案...]}。"""
    pools = {}
    cur = "general"
    try:
        with open(path, "r", encoding="utf-8") as f:
            for raw in f:
                line = raw.strip()
                if not line:
                    continue
                if line.startswith("#"):
                    tag = line.lstrip("# ").strip()
                    if tag.startswith("[") and tag.endswith("]"):
                        cur = tag[1:-1]
                    continue
                pools.setdefault(cur, []).append(line)
    except FileNotFoundError:
        pools["general"] = ["你好呀"]
    return pools


def time_pool_name(hour):
    if hour < 6:
        return "night"
    if hour < 9:
        return "morning"
    if hour < 13:
        return "noon"
    if hour < 18:
        return "afternoon"
    if hour < 23:
        return "evening"
    return "night"


def normalize_offwork_time(text):
    """把「18:00」「18：00」收成 HH:MM。不合法返回 None。"""
    raw = str(text or "").strip().replace("：", ":")
    parts = raw.split(":")
    if len(parts) != 2:
        return None
    try:
        hh = int(parts[0].strip())
        mm = int(parts[1].strip())
    except ValueError:
        return None
    if hh < 0 or hh > 23 or mm < 0 or mm > 59:
        return None
    return "%02d:%02d" % (hh, mm)


# ---------------------------------------------------------------- Windows 小工具
def win_set_dpi_aware():
    if IS_WIN:
        try:
            import ctypes
            ctypes.windll.shcore.SetProcessDpiAwareness(2)  # 每显示器 DPI 感知
        except Exception:
            try:
                import ctypes
                ctypes.windll.user32.SetProcessDPIAware()
            except Exception:
                pass


def win_idle_seconds():
    """距上次键盘鼠标输入的秒数（摸鱼检测用）。取不到返回 None。"""
    if not IS_WIN:
        return None
    try:
        import ctypes

        class LASTINPUTINFO(ctypes.Structure):
            _fields_ = [("cbSize", ctypes.c_uint), ("dwTime", ctypes.c_uint)]

        lii = LASTINPUTINFO()
        lii.cbSize = ctypes.sizeof(LASTINPUTINFO)
        ctypes.windll.user32.GetLastInputInfo(ctypes.byref(lii))
        millis = ctypes.windll.kernel32.GetTickCount() - lii.dwTime
        return millis / 1000.0
    except Exception:
        return None


def win_volume(action):
    """系统音量：up / down / mute（仅 Windows）。"""
    if not IS_WIN:
        return False
    try:
        import ctypes
        vk = {"up": 0xAF, "down": 0xAE, "mute": 0xAD}[action]
        ctypes.windll.user32.keybd_event(vk, 0, 0, 0)
        ctypes.windll.user32.keybd_event(vk, 0, 2, 0)
        return True
    except Exception:
        return False


def set_autostart(enable):
    """开机自启（Windows 写注册表 Run 项；Mac 在说明里教用户手动设置）。"""
    if not IS_WIN:
        return False, "Mac 请在 系统设置→通用→登录项 里手动添加本程序"
    try:
        import winreg
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                             r"Software\Microsoft\Windows\CurrentVersion\Run",
                             0, winreg.KEY_SET_VALUE)
        if enable:
            target = sys.executable if getattr(sys, "frozen", False) \
                else '"%s" "%s"' % (sys.executable, os.path.abspath(__file__))
            winreg.SetValueEx(key, "DesktopPet", 0, winreg.REG_SZ, target)
        else:
            try:
                winreg.DeleteValue(key, "DesktopPet")
            except FileNotFoundError:
                pass
        winreg.CloseKey(key)
        return True, ""
    except Exception as e:
        return False, str(e)


# ---------------------------------------------------------------- 主程序
class DesktopPet:
    def __init__(self):
        win_set_dpi_aware()
        self.cfg = load_json(CONFIG_PATH, DEFAULT_CONFIG)
        self.state = load_json(STATE_PATH, DEFAULT_STATE)
        self.pets_cfg = load_pets()
        self._boat_pet_id = next((x["id"] for x in self.pets_cfg["pets"]
                                  if x.get("fx") == "boat"), None)
        self.pet_id = self.pets_cfg["active"]
        self._boot_sync_patrol_pet()      # 巡逻中重启 / 关巡逻后的形象还原
        self.pet = next(x for x in self.pets_cfg["pets"]
                        if x["id"] == self.pet_id)
        self.pools = load_dialogues(res_path(self.pet["dialogues"]))
        self._daily_reset()

        self.root = tk.Tk()
        self.root.withdraw()                     # 主窗口只当载体
        self.root.title("桌面宠物 · %s" % self.pet["name"])

        # ---- 角色图（当前形象）
        self.base_img = self._load_pet_image(self.pet["image"])
        self.height = int(self.pet.get("height_px") or
                          self.cfg.get("pet_height_px", DEFAULT_HEIGHT))
        self.scale = 1.0                         # 用户滚轮缩放系数
        self.flip = False
        self._tkimg = None
        self.frames_walk, self.frames_idle = self._load_frames(self.pet)
        self._frame_idx = 0

        # ---- 动画状态（呼吸基线 + 一次性动作，全在一个 25fps 循环里合成）
        self._breath_t = random.uniform(0, 3)    # 呼吸相位随机，多只桌宠不同步
        self._anim = None                        # 当前一次性动作生成器
        self._base_display = None                # 显示尺寸的角色图缓存
        self._boat_fx = BoatFX() if BoatFX is not None else None

        # ---- 宠物窗口
        self.win = tk.Toplevel(self.root)
        self.win.withdraw()                      # 先隐藏，避免带系统边框闪一帧
        self.win.overrideredirect(True)          # 无边框
        self.win.attributes("-topmost", bool(self.cfg.get("topmost", True)))
        self.win.configure(bg=CHROMA)
        self._make_transparent(self.win)
        self.label = tk.Label(self.win, bd=0, bg=CHROMA)
        self.label.pack()
        self.win.attributes("-alpha", float(self.cfg.get("opacity", 1.0)))

        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        self.x, self.y = int(sw * 0.7), int(sh * 0.75)
        self.patrol_dir = -1
        self._render()
        self.win.deiconify()                     # 配置与首帧完成后再显示

        # 拖动 / 点击 / 滚轮 / 右键
        self._press = None
        self.label.bind("<ButtonPress-1>", self._on_press)
        self.label.bind("<B1-Motion>", self._on_drag)
        self.label.bind("<ButtonRelease-1>", self._on_release)
        self.label.bind("<Button-3>", self._on_right)
        self.label.bind("<MouseWheel>", self._on_wheel)          # Win/Mac
        self.label.bind("<Button-4>", lambda e: self._zoom(1))   # Linux
        self.label.bind("<Button-5>", lambda e: self._zoom(-1))

        # ---- 气泡 & 面板（面板是独立窗口：位置与宠物解耦，可单独拖动）
        self.bubble = None
        self.panel = None
        self._panel_labels = []
        self.panel_x = self.state.get("panel_x")
        self.panel_y = self.state.get("panel_y")
        self._panel_press = None

        # ---- 组件运行时
        self.pomodoro_until = None
        self.pomodoro_mode = None
        self.weather_text = "天气获取中…"
        self._weather_fetched = 0
        self._geo_fetched = 0                   # 上次按 IP 定位的时间
        self._geo_busy = False                  # 防止定位线程叠发
        self._notice_q = []                     # 后台线程 → 主线程的冒泡通知
        self._fish_nagged = 0.0
        self._chimed_hour = -1

        # ---- 自动更新（后台线程只往 _update_q 投事件，UI 全在主线程处理）
        self.app_version = (updater_mod.load_version(BASE_DIR)
                            if updater_mod else "0.0.0")
        vmeta = (updater_mod.read_json(os.path.join(BASE_DIR, "version.json"))
                 if updater_mod else {})
        self._exe_name = str(vmeta.get("exe") or "小仓鼠桌宠.exe")
        self._update_settings = (updater_mod.load_settings(BASE_DIR)
                                 if updater_mod else {})
        self._updater = (updater_mod.Updater(
            BASE_DIR, self._update_settings.get("repo", ""),
            self.app_version, log=self._update_log) if updater_mod else None)
        self._update_q = []
        self._update_busy = False
        self._upd_win = None
        self._upd_text = None
        self._upd_pct = None

        self.menu = None
        self._build_menu()
        self._build_panel()

        # ---- 托盘（可选依赖 pystray）
        self._tray = None
        self._start_tray()

        # ---- 定时器
        self.root.after(ANIM_MS, self._anim_tick)                # 25fps 动画循环
        self.root.after(800, self._tick_fast)      # 1s 级：面板/倒计时
        self.root.after(1500, self._tick_slow)     # 5s 级：摸鱼/天气/联动
        self.root.after(5000, self._idle_action)  # 首次动作提前，间隔由 _idle_action 按配置调度
        if self._updater and self._update_settings.get("check_on_start", True) \
                and (updater_mod is None
                     or not updater_mod.should_skip_automatic_check()):
            delay = max(2, int(self._update_settings.get("start_delay_sec", 8)))
            self.root.after(delay * 1000, self._auto_update_check)
        if self.cfg.get("auto_patrol"):
            self.root.after(60, self._patrol_step)
        if self.cfg.get("follow_mouse"):
            self.root.after(120, self._follow_step)

        # 首次运行引导
        if not self.state.get("welcomed"):
            self.root.after(600, lambda: self.say(
                "欢迎使用！默认开启了 AI 额度、下班倒计时、喝水提醒、天气，"
                "右键我还能切换宠物形象哦～", duration=6000))
            self.state["welcomed"] = True
            self._save_state()

        if SELFTEST:
            self.root.after(300, self._selftest)

    # ------------------------------------------------------------ 图像
    def _load_pet_image(self, rel="assets/pet.png"):
        path = res_path(rel)
        try:
            return Image.open(path).convert("RGBA")
        except Exception:
            # 没有角色图时画一个占位小球，保证程序永远能起来
            img = Image.new("RGBA", (300, 300), (0, 0, 0, 0))
            from PIL import ImageDraw
            d = ImageDraw.Draw(img)
            d.ellipse([30, 30, 270, 270], fill=(120, 180, 255, 255))
            d.ellipse([95, 110, 135, 150], fill=(30, 30, 30, 255))
            d.ellipse([165, 110, 205, 150], fill=(30, 30, 30, 255))
            d.arc([110, 150, 190, 220], 20, 160, fill=(30, 30, 30, 255), width=6)
            return img

    def _load_frames(self, pet=None):
        """动作帧目录里有 walk_*.png / idle_*.png 就启用逐帧动画；
        pets.json 可给单个形象指定专属 frames 目录。"""
        sub = (pet or {}).get("frames") or ""
        d = res_path(sub) if sub else res("assets", "frames")
        walk, idle = [], []
        if os.path.isdir(d):
            for f in sorted(os.listdir(d)):
                try:
                    if f.startswith("walk_"):
                        walk.append(Image.open(os.path.join(d, f)).convert("RGBA"))
                    elif f.startswith("idle_"):
                        idle.append(Image.open(os.path.join(d, f)).convert("RGBA"))
                except Exception:
                    pass
        return walk, idle

    def _make_transparent(self, window):
        """逐像素透明：Windows 用透明色键；Mac 用 -transparent（效果以实测为准）。"""
        if IS_WIN:
            window.attributes("-transparentcolor", CHROMA)
        elif IS_MAC:
            try:
                window.configure(bg="systemTransparent")
                window.attributes("-transparent", True)
            except tk.TclError:
                pass  # 老版本 tk 不支持则保持不透明底

    # ------------------------------------------------------------ 渲染管线
    # 两层：_rebuild_base 只在缩放/换帧/翻向时做（LANCZOS，贵）；
    #       _apply 每帧做（BILINEAR 小图变换，便宜），动画全靠它。
    @staticmethod
    def _snap_chroma(rgb):
        """[兼容兜底] 新渲染管线请用 _compose_chroma；此方法不再被 _apply 调用。

        把「角色色 <-> 品红色键」的混合边缘吸附回精确色键，消除粉色描边。

        Windows 的 -transparentcolor 只抠 #ff00ff 精确值；paste 与逐帧缩放
        产生的半透明混合色不会被抠掉，会显示成一圈粉边。这里用 C 实现的
        通道运算逐帧把偏品红像素吸附回 CHROMA，保证画面只剩「角色色」和
        「纯色键」两种值。判据 m = min(R,B)-G：色键 255，角色色 <= 11。
        """
        r, g, b = rgb.split()
        m = ImageChops.subtract(ImageChops.darker(r, b), g)
        mask = m.point(lambda v: 255 if v > 70 else 0)
        solid = Image.new("RGB", rgb.size, (255, 0, 255))
        return Image.composite(solid, rgb, mask)

    @staticmethod
    def _compose_chroma(img):
        """把 RGBA 帧合成成「角色原色 + 精确色键」两值画面，杜绝边缘脏色。

        Windows 的 -transparentcolor 只把精确 #ff00ff 抠成透明，窗口里其它
        像素一律完全不透明。旧做法用 paste 按 alpha 混合，半透明绒毛边缘会
        与品红底混出粉紫中间色；LANCZOS/BILINEAR 缩放也会把透明区的品红
        渗进边缘 RGB —— 这就是桌面上一圈颗粒状「毛边 / 粉边」的根因。

        两步：
          1) 不做 alpha 混合：用二值 keep mask 把原 RGB 直接贴到精确色键底上，
             画面只剩「角色色」和「纯品红」两种值；
          2) 兜底吸附：仅对 alpha<250 的半透明边缘带，把 m=min(R,B)-G>5 的
             像素吸附回精确色键。实心角色区（粉鼻/粉耳 m 可达 13）完全不受
             影响，不会被误抠。
        """
        a = img.getchannel("A")
        keep = a.point(lambda v: 255 if v > 8 else 0)
        out = Image.new("RGB", img.size, (255, 0, 255))
        out.paste(img.convert("RGB"), (0, 0), keep)

        r, g, b = out.split()
        mm = ImageChops.subtract(ImageChops.darker(r, b), g)
        pink = mm.point(lambda v: 255 if v > 5 else 0)
        soft = a.point(lambda v: 255 if v < 250 else 0)
        mask = ImageChops.multiply(pink, soft)
        return Image.composite(Image.new("RGB", img.size, (255, 0, 255)),
                               out, mask)

    # 固定画布安全系数：动作（压扁变宽/旋转膨胀/跳跃位移）最大约 1.41 倍，
    # 取 1.5 留足余量。窗口尺寸 = 基准 × 此系数，一次算好，动画期间绝不再变，
    # 从根上杜绝「动作第一帧窗口突变 resize 闪黑边」。
    CANVAS_PAD = 1.5

    def _rebuild_base(self, img=None):
        src = img if img is not None else self.base_img
        h = max(30, int(self.height * self.scale))
        w = max(30, int(h * src.width / src.height))
        frame = src.resize((w, h), Image.LANCZOS)
        if self.flip:
            frame = frame.transpose(Image.FLIP_LEFT_RIGHT)
        self._base_display = frame
        self._pet_size = (w, h)
        # 固定画布尺寸：整个运行期只在这里（以及缩放/换形象时）变一次
        self._canvas_size = (int(w * self.CANVAS_PAD),
                             int(h * self.CANVAS_PAD))

    def _apply(self, sx=1.0, sy=1.0, rot=0.0, dx=0.0, dy=0.0):
        """把呼吸/动作合成的变换应用到角色上。

        关键：窗口尺寸固定为 _canvas_size（基准 × 1.5 安全系数），动画只
        替换 label 图片，绝不每帧 resize 窗口。变化帧居中贴到固定画布上，
        旋转/缩放/跳跃位移造成的画布膨胀全部由固定画布的透明边距吸收，
        所以窗口 geometry 在动画过程中恒定不变——这从根上消除了「点击后
        动作第一帧窗口突变 resize、tkinter 先清屏再贴图而闪出的黑边」。
        """
        base = self._base_display
        if base is None:
            return
        bw, bh = base.size
        img = base
        # 划船形象：把当前相位的水浪/船桨层叠到角色帧上（同尺寸，不触发 resize）
        if (self.pet.get("fx") == "boat" and self._boat_fx is not None
                and self.cfg.get("boat_fx", True)):
            fx = self._boat_fx.layer(bw, bh, self.flip,
                                     ANIM_MS / 1000.0,
                                     bool(self.cfg.get("auto_patrol")))
            if fx is not None:
                img = Image.alpha_composite(img, fx)
        if abs(sx - 1) > 0.005 or abs(sy - 1) > 0.005:
            img = img.resize((max(4, int(bw * sx)), max(4, int(bh * sy))),
                             Image.BILINEAR)
        if abs(rot) > 0.4:
            img = img.rotate(-rot, expand=True, resample=Image.BILINEAR)

        # 固定画布：尺寸恒定，变化帧居中贴上，多余部分为透明边距
        cw, ch = self._canvas_size
        canvas = Image.new("RGBA", (cw, ch), (255, 0, 255, 0))
        canvas.paste(img, ((cw - img.width) // 2, (ch - img.height) // 2), img)

        self._tkimg = ImageTk.PhotoImage(self._compose_chroma(canvas))
        self.label.configure(image=self._tkimg)
        # 位移按固定画布中心对齐（角色重心在画布正中，与基准中心差恒定）
        ox = (cw - bw) / 2.0
        oy = (ch - bh) / 2.0
        self.win.geometry("%dx%d+%d+%d" % (
            cw, ch,
            int(self.x + dx - ox), int(self.y + dy - oy)))

    def _render(self, img=None):
        """重建显示缓存并立即应用一次（缩放/换帧/初始化时调用）。"""
        self._rebuild_base(img)
        self._apply()

    # ------------------------------------------------------------ 动画引擎
    # 一次性动作 = 生成器，逐帧 yield (sx, sy, rot, dy, dx)，
    # 与呼吸基线相乘/相加合成，曲线全部是弹簧阻尼或抛物线——不僵硬的核心。
    def _gen_squash(self):
        """压扁回弹：过冲弹簧（先压扁，然后带着回弹晃两下摆稳）。"""
        t = 0.0
        while t < 0.9:
            t += ANIM_MS / 1000.0
            k = math.exp(-4.5 * t) * math.cos(14 * t)
            sy = 1 - 0.20 * k
            sx = 1 + 0.9 * (1 - sy)              # 体积守恒，压扁必变宽
            yield (sx, sy, 0.0, 0.0, 0.0)

    def _gen_jump(self):
        """跳跃三段式：下蹲蓄力 → 抛物线腾空（空中轻微拉长）→ 落地回弹。"""
        for _ in range(3):                       # 蓄力
            yield (1.08, 0.86, 0.0, 0.0, 0.0)
        frames = 11
        for i in range(frames):                  # 腾空：正弦抛物线，慢起慢落
            t = i / (frames - 1)
            arc = math.sin(math.pi * t)
            yield (1 - 0.06 * arc, 1 + 0.10 * arc, 0.0, -46 * arc, 0.0)
        t = 0.0
        while t < 0.35:                          # 落地回弹
            t += ANIM_MS / 1000.0
            k = math.exp(-7 * t) * math.cos(20 * t)
            sy = 1 - 0.14 * k
            yield (1 + 0.9 * (1 - sy), sy, 0.0, 0.0, 0.0)

    def _gen_wobble(self):
        """左右摇摆：旋转阻尼摆动，比生硬的位移抖动自然得多。"""
        t = 0.0
        while t < 0.7:
            t += ANIM_MS / 1000.0
            rot = 13 * math.exp(-4 * t) * math.sin(11 * t)
            yield (1.0, 1.0, rot, 0.0, 0.0)

    def _gen_blink(self):
        """眯眼：轻微快速的纵向挤压，单图角色的"眨眼"近似。"""
        for sy in (1.0, 0.94, 0.91, 0.94, 1.0):
            yield (1 + (1 - sy) * 0.6, sy, 0.0, 0.0, 0.0)

    def _gen_stretch(self):
        """伸懒腰：缓慢拉长并微微侧倾，再带阻尼回落。"""
        n = 22
        for i in range(n):
            t = i / (n - 1)
            lift = math.sin(math.pi * t)
            yield (1 - 0.05 * lift, 1 + 0.13 * lift, 3.0 * lift, -6 * lift, 0.0)
        t = 0.0
        while t < 0.35:
            t += ANIM_MS / 1000.0
            k = math.exp(-6 * t) * math.cos(16 * t)
            sy = 1 - 0.07 * k
            yield (1 + 0.8 * (1 - sy), sy, 0.0, 0.0, 0.0)

    def _gen_tilt(self):
        """歪头：转过去、停一下、带阻尼转回来。"""
        for i in range(6):
            yield (1.0, 1.0, 14 * i / 5, 0.0, 0.0)
        for _ in range(8):
            yield (1.0, 1.0, 14.0, 0.0, 0.0)
        t = 0.0
        while t < 0.55:
            t += ANIM_MS / 1000.0
            yield (1.0, 1.0, 14 * math.exp(-4 * t) * math.cos(9 * t), 0.0, 0.0)

    def _gen_hop(self):
        """原地小蹦两下，比单次跳跃更轻快。"""
        for amp in (24, 16):
            frames = 8
            for i in range(frames):
                t = i / (frames - 1)
                arc = math.sin(math.pi * t)
                yield (1 - 0.03 * arc, 1 + 0.05 * arc, 0.0, -amp * arc, 0.0)
            yield (1.06, 0.94, 0.0, 0.0, 0.0)

    def _gen_nod(self):
        """点头：小幅前倾再回正，弹簧阻尼。"""
        t = 0.0
        while t < 0.8:
            t += ANIM_MS / 1000.0
            k = math.exp(-3.5 * t) * math.sin(12 * t)
            yield (1 + 0.03 * k, 1 - 0.05 * k, 5 * k, 0.0, 0.0)

    def _gen_puff(self):
        """鼓气：整体鼓起再缓缓泄掉，配气鼓鼓文案很搭。"""
        n = 18
        for i in range(n):
            t = i / (n - 1)
            b = math.sin(math.pi * t)
            yield (1 + 0.09 * b, 1 + 0.06 * b, 0.0, 0.0, 0.0)

    # 简洁调用入口（菜单/组件里在用）
    def _anim_squash(self):
        self._anim = self._gen_squash()

    def _anim_jump(self):
        self._anim = self._gen_jump()

    def _anim_shake(self):
        self._anim = self._gen_wobble()

    def _anim_tick(self):
        """25fps 动画循环：呼吸基线 + 巡逻姿态 + 一次性动作，合成后应用。"""
        self._breath_t += ANIM_MS / 1000.0
        t = self._breath_t
        # 呼吸基线：3.6 秒一个周期的微弱缩放 + 5.3 秒的微晃，静止时也"活"
        sx, sy = 1.0, 1 + 0.022 * math.sin(t * 2 * math.pi / 3.6)
        rot = 0.8 * math.sin(t * 2 * math.pi / 5.3)
        dx = dy = 0.0
        if self.cfg.get("auto_patrol"):
            if self.pet.get("fx") == "boat":
                # 划船是「随波起伏 + 缓慢摇摆」，套用走路的颠簸会很出戏
                dy += 3.2 * math.sin(t * 2 * math.pi / 1.10)
                rot += 2.6 * math.sin(t * 2 * math.pi / 1.60)
            else:
                dy += 2.5 * abs(math.sin(t * 9))     # 走路上下颠簸
                rot += self.patrol_dir * -3.5        # 向行进方向倾斜
        if self._anim is not None:
            try:
                a = next(self._anim)
            except StopIteration:
                a = None
                self._anim = None
            if a:
                sx *= a[0]
                sy *= a[1]
                rot += a[2]
                dy += a[3]
                dx += a[4]
        self._apply(sx, sy, rot, dx, dy)
        self.root.after(ANIM_MS, self._anim_tick)

    # ------------------------------------------------------------ 事件
    def _on_press(self, e):
        self._press = (e.x_root, e.y_root, self.x, self.y)

    def _on_drag(self, e):
        if not self._press:
            return
        x0, y0, wx0, wy0 = self._press
        self.x, self.y = wx0 + (e.x_root - x0), wy0 + (e.y_root - y0)
        self._apply()                            # 只挪窗口，不重建图

    def _on_release(self, e):
        if not self._press:
            return
        x0, y0, _, _ = self._press
        self._press = None
        # 防误触：移动距离超过阈值算拖动，否则算点击
        if math.hypot(e.x_root - x0, e.y_root - y0) <= DRAG_THRESHOLD:
            self._on_click()

    def _on_click(self):
        self._add_affection(1)
        self._play_random_action()
        # 每日一言：点击有概率触发当日一言
        if self._comp("daily_quote") and random.random() < 0.2 \
                and self.pools.get("daily"):
            self.say(random.choice(self.pools["daily"]))
        else:
            self.say(self._pick_line())

    def _on_wheel(self, e):
        self._zoom(1 if e.delta > 0 else -1)

    def _zoom(self, direction):
        self.scale = min(2.5, max(0.4, self.scale * (1.1 if direction > 0 else 0.9)))
        self._render()

    def _on_right(self, e):
        self._build_menu()                       # 每次重建，保证勾选状态最新
        try:
            self.menu.tk_popup(e.x_root, e.y_root)
        finally:
            self.menu.grab_release()

    # ------------------------------------------------------------ 空闲动作
    def _idle_action(self):
        """空闲随机动作：按配置间隔动一下，动作池随机，偶尔冒气泡。"""
        if not self.pomodoro_mode and self._anim is None:   # 专注时不打扰，动作不叠播
            if random.random() < 0.72:
                self._play_random_action()
            else:
                self.say(self._pick_line())
        lo = int(self.cfg.get("idle_action_min_sec", 8))
        hi = max(lo, int(self.cfg.get("idle_action_max_sec", 20)))
        self.root.after(random.randint(lo, hi) * 1000, self._idle_action)

    def _play_random_action(self):
        """从动作池随机挑一个 _gen_* 一次性动作，全部走统一的动画合成循环。"""
        gens = (self._gen_squash, self._gen_jump, self._gen_wobble,
                self._gen_blink, self._gen_stretch, self._gen_tilt,
                self._gen_hop, self._gen_nod, self._gen_puff)
        self._anim = random.choice(gens)()

    # ------------------------------------------------------------ 气泡
    def say(self, text, duration=3000):
        if not text:
            return
        if self.bubble is not None:
            try:
                self.bubble.destroy()
            except Exception:
                pass
        b = tk.Toplevel(self.root)
        b.withdraw()                             # 先隐藏，避免系统边框闪一帧
        b.overrideredirect(True)
        b.attributes("-topmost", True)
        b.configure(bg="#fffbe8")               # 窗口底色与气泡一致，不露黑边
        lab = tk.Label(b, text=text, bg="#fffbe8", fg="#333333",
                       font=("Microsoft YaHei UI", 10), wraplength=230,
                       justify="left", padx=10, pady=6, bd=0,
                       highlightthickness=0)
        lab.pack()
        b.update_idletasks()
        bw, bh = b.winfo_reqwidth(), b.winfo_reqheight()
        pw, ph = getattr(self, "_pet_size", (self.height, self.height))
        bx = min(max(0, self.x + pw // 2 - bw // 2), self.root.winfo_screenwidth() - bw)
        by = self.y - bh - 8
        if by < 0:                               # 上面放不下就放侧面
            by, bx = self.y, self.x + pw + 8
        b.geometry("%dx%d+%d+%d" % (bw, bh, int(bx), int(by)))  # 显式尺寸，不留边框余量
        b.deiconify()
        self.bubble = b
        self.root.after(duration, self._hide_bubble)

    def _hide_bubble(self):
        if self.bubble is not None:
            try:
                self.bubble.destroy()
            except Exception:
                pass
            self.bubble = None

    def _pick_line(self):
        pool = list(self.pools.get("general", ["……"]))
        if self._comp("affection"):
            lv = self._affection_level()
            for n in range(2, lv + 2):           # 好感度解锁更多文案
                pool += self.pools.get("lv%d" % n, [])
        return random.choice(pool)

    # ------------------------------------------------------------ 面板
    def _build_panel(self):
        if self.panel is not None:
            try:
                self.panel.destroy()
            except Exception:
                pass
            self.panel = None
        if not self._panel_visible_components():
            return
        p = tk.Toplevel(self.root)
        p.withdraw()
        p.overrideredirect(True)
        p.attributes("-topmost", True)
        p.attributes("-alpha", 0.88)
        p.configure(bg="#22252b")
        self._panel_labels = []
        for _ in range(7):
            lab = tk.Label(p, text="", bg="#22252b", fg="#e8e8e8",
                           font=("Microsoft YaHei UI", 9), anchor="w",
                           padx=8, pady=1, bd=0, highlightthickness=0)
            lab.pack(fill="x")
            lab.bind("<ButtonPress-1>", self._panel_press_cb)
            lab.bind("<B1-Motion>", self._panel_drag_cb)
            lab.bind("<ButtonRelease-1>", self._panel_release_cb)
            self._panel_labels.append(lab)
        # 窗口本体也绑定：点到标签之间的空隙同样能拖
        for ev, cb in (("<ButtonPress-1>", self._panel_press_cb),
                       ("<B1-Motion>", self._panel_drag_cb),
                       ("<ButtonRelease-1>", self._panel_release_cb)):
            p.bind(ev, cb)
        self.panel = p
        self._place_panel()
        p.deiconify()

    # ---- 信息面板：独立窗口，自带拖动，与宠物完全解耦 ----
    def _panel_press_cb(self, e):
        self._panel_press = (e.x_root, e.y_root,
                             self.panel.winfo_x(), self.panel.winfo_y())

    def _panel_drag_cb(self, e):
        if not self._panel_press:
            return
        x0, y0, wx0, wy0 = self._panel_press
        # 拖动时就夹在屏幕内，保证存下来的坐标永远合法：
        # 否则越界坐标在面板重建（组件开关）时会被 _place_panel 夹回，看起来会跳一下。
        bw, bh = self.panel.winfo_width(), self.panel.winfo_height()
        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        self.panel_x = min(max(0, wx0 + (e.x_root - x0)), max(0, sw - bw))
        self.panel_y = min(max(0, wy0 + (e.y_root - y0)), max(0, sh - bh))
        self.panel.geometry("+%d+%d" % (int(self.panel_x), int(self.panel_y)))

    def _panel_release_cb(self, e):
        if not self._panel_press:
            return
        self._panel_press = None
        self._save_panel_pose()               # 拖到哪儿记住哪儿

    def _save_panel_pose(self):
        self.state["panel_x"] = (int(self.panel_x)
                                 if self.panel_x is not None else None)
        self.state["panel_y"] = (int(self.panel_y)
                                 if self.panel_y is not None else None)
        self._save_state()

    def _reset_panel_pos(self):
        """右键菜单：把信息面板复位到屏幕右下角。"""
        self.panel_x = None
        self.panel_y = None
        self._save_panel_pose()
        self._place_panel()
        self.say("信息面板已回到右下角～")

    def _panel_visible_components(self):
        c = self.cfg["components"]
        keys = ["clock", "weather", "quota", "offwork", "water", "todo"]
        return any(c.get(k) for k in keys) or self.pomodoro_mode

    def _place_panel(self):
        """把面板放到它自己的坐标；首次运行默认贴屏幕右下角。

        位置只取决于 panel_x/panel_y，与宠物 self.x/self.y 完全无关，
        因此宠物拖动、缩放、巡逻、跟随鼠标时面板都留在原地不动。
        """
        if self.panel is None:
            return
        self.panel.update_idletasks()
        bw, bh = self.panel.winfo_reqwidth(), self.panel.winfo_reqheight()
        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        if self.panel_x is None or self.panel_y is None:
            margin = 16
            self.panel_x = max(0, sw - bw - margin)
            self.panel_y = max(0, sh - bh - margin)
        # 分辨率变化后夹回可视区，但不写回，避免每次刷新产生位置漂移
        x = min(max(0, int(self.panel_x)), max(0, sw - bw))
        y = min(max(0, int(self.panel_y)), max(0, sh - bh))
        self.panel.geometry("%dx%d+%d+%d" % (bw, bh, x, y))

    def _update_panel(self):
        if self.panel is None:
            return
        c = self.cfg["components"]
        now = datetime.now()
        lines = []
        if c.get("clock"):
            lines.append("🕐 %s" % now.strftime("%H:%M"))
        if c.get("weather"):
            lines.append("🌤 %s" % self.weather_text)
        if c.get("quota"):
            limit = max(1, int(self.cfg.get("daily_quota_limit", 100)))
            used = int(self.state.get("quota_used", 0))
            pct = min(100, used * 100 // limit)
            bar = "▓" * (pct // 10) + "░" * (10 - pct // 10)
            lines.append("🤖 额度 %s %d%%" % (bar, 100 - pct))
        if c.get("offwork"):
            lines.append("🏃 %s" % self._offwork_text(now))
        if c.get("water"):
            lines.append("🥤 喝水 %d/%d" % (self.state.get("water", 0),
                                            int(self.cfg.get("water_goal", 8))))
        if c.get("todo"):
            undone = [t for t in self.state.get("todos", []) if not t.get("done")]
            lines.append("📌 " + (undone[0]["text"][:14] if undone else "今日事毕"))
        if self.pomodoro_mode:
            left = max(0, int((self.pomodoro_until - time.time())))
            tag = "专注" if self.pomodoro_mode == "work" else "休息"
            lines.append("🍅 %s %02d:%02d" % (tag, left // 60, left % 60))
        for i, lab in enumerate(self._panel_labels):
            lab.configure(text=lines[i] if i < len(lines) else "")
        self._place_panel()

    # ------------------------------------------------------------ 右键菜单
    def _build_menu(self):
        c = self.cfg["components"]
        m = tk.Menu(self.root, tearoff=0)

        # 切换宠物形象（列表来自 pets.json，单选按钮带当前选中标记）
        if len(self.pets_cfg["pets"]) > 1:
            sw = tk.Menu(m, tearoff=0)
            self._pet_var = tk.StringVar(value=self.pet_id)
            for item in self.pets_cfg["pets"]:
                sw.add_radiobutton(
                    label=item["name"], variable=self._pet_var,
                    value=item["id"],
                    command=lambda i=item["id"]: self.switch_pet(i))
            m.add_cascade(label="切换宠物（当前：%s）" % self.pet["name"],
                          menu=sw)
            m.add_separator()

        # 组件开关
        comp = tk.Menu(m, tearoff=0)
        names = [("quota", "AI 使用额度"), ("offwork", "下班倒计时"),
                 ("water", "喝水提醒"), ("weather", "天气小标签"),
                 ("clock", "迷你时钟"), ("system_status", "系统状态"),
                 ("pomodoro", "番茄钟"), ("todo", "待办小纸条"),
                 ("fish_detect", "摸鱼检测"), ("daily_quote", "每日一言"),
                 ("feed", "投喂系统"), ("affection", "好感度"),
                 ("quick_launch", "快捷启动"), ("volume", "音量控制"),
                 ("screenshot", "一键截图")]
        self._comp_vars = {}
        for key, label in names:
            v = tk.BooleanVar(value=bool(c.get(key)))
            self._comp_vars[key] = v
            comp.add_checkbutton(label=label, variable=v,
                                 command=lambda k=key: self._toggle_comp(k))
        m.add_cascade(label="组件开关", menu=comp)
        clock = normalize_offwork_time(self.cfg.get("offwork_time", "18:00")) or "18:00"
        m.add_command(label="下班时间（%s）…" % clock, command=self._offwork_dialog)

        # 天气与位置：手动城市 / 按网络 IP 自动定位 / 立即刷新
        loc, label = self._weather_location()
        geo = tk.Menu(m, tearoff=0)
        self._city_auto_var = tk.BooleanVar(value=bool(self.cfg.get("city_auto")))
        geo.add_checkbutton(label="自动定位（按网络 IP）",
                            variable=self._city_auto_var,
                            command=self._toggle_city_auto)
        geo.add_command(label="重新定位 / 刷新位置",
                        command=self._menu_relocate)
        geo.add_command(label="手动设置城市…", command=self._city_dialog)
        geo.add_separator()
        geo.add_command(label="立即刷新天气", command=self._refresh_weather_now)
        geo.add_command(label="当前位置：%s" % label, state="disabled")
        m.add_cascade(label="天气与位置（%s）" % label[:8], menu=geo)

        # 大小 / 透明度 / 置顶
        size = tk.Menu(m, tearoff=0)
        for label, s in [("大", 1.3), ("标准", 1.0), ("小", 0.7), ("迷你", 0.5)]:
            size.add_command(label=label, command=lambda v=s: self._set_scale(v))
        m.add_cascade(label="调整大小", menu=size)
        op = tk.Menu(m, tearoff=0)
        for pct in (100, 85, 70, 50, 30):
            op.add_command(label="%d%%" % pct,
                           command=lambda v=pct: self._set_opacity(v / 100))
        m.add_cascade(label="透明度", menu=op)
        self._top_var = tk.BooleanVar(value=bool(self.cfg.get("topmost", True)))
        m.add_checkbutton(label="窗口置顶", variable=self._top_var,
                          command=self._toggle_topmost)
        if self._panel_visible_components():
            m.add_command(label="信息面板回到右下角",
                          command=self._reset_panel_pos)

        # 巡逻 / 跟随 / 自启
        self._patrol_var = tk.BooleanVar(value=bool(self.cfg.get("auto_patrol")))
        m.add_checkbutton(label="自动巡逻", variable=self._patrol_var,
                          command=self._toggle_patrol)
        if self._boat_pet_id:
            self._boat_var = tk.BooleanVar(value=bool(self.cfg.get("boat_fx", True)))
            m.add_checkbutton(label="划船水浪 / 船桨动画",
                              variable=self._boat_var,
                              command=self._toggle_boat_fx)
        self._follow_var = tk.BooleanVar(value=bool(self.cfg.get("follow_mouse")))
        m.add_checkbutton(label="盯着你（跟随鼠标）", variable=self._follow_var,
                          command=self._toggle_follow)
        self._auto_var = tk.BooleanVar(value=bool(self.cfg.get("autostart")))
        m.add_checkbutton(label="开机自启", variable=self._auto_var,
                          command=self._toggle_autostart)

        m.add_separator()

        # 番茄钟
        if c.get("pomodoro"):
            pomo = tk.Menu(m, tearoff=0)
            pomo.add_command(label="开始专注", command=self._pomo_start)
            pomo.add_command(label="停止", command=self._pomo_stop)
            m.add_cascade(label="番茄钟", menu=pomo)

        # 互动动作
        if c.get("water"):
            m.add_command(label="记一杯水", command=self._water_add)
        if c.get("quota"):
            m.add_command(label="记一次 AI 调用", command=self._quota_add)
            m.add_command(label="重置今日计数", command=self._daily_reset_force)
        if c.get("feed"):
            feed = tk.Menu(m, tearoff=0)
            for food in ("奶茶", "炸鸡", "咖啡", "小蛋糕"):
                feed.add_command(label=food,
                                 command=lambda f=food: self._feed(f))
            m.add_cascade(label="投喂", menu=feed)
        if c.get("affection"):
            m.add_command(label="好感度 Lv.%d（%d 点）" % (
                self._affection_level(), self.state.get("affection", 0)),
                command=lambda: self.say("好感度 Lv.%d：继续陪我玩会解锁更多话哦"
                                         % self._affection_level()))
        if c.get("daily_quote"):
            m.add_command(label="换一句每日一言", command=lambda: self.say(
                random.choice(self.pools.get("daily", ["今天也要加油"]))))
        if c.get("todo"):
            m.add_command(label="今日待办…", command=self._todo_editor)
        if c.get("system_status"):
            m.add_command(label="系统状态", command=self._show_sysstatus)
        if c.get("quick_launch"):
            ql = tk.Menu(m, tearoff=0)
            for app in self.cfg.get("quick_launch", []):
                ql.add_command(label=app.get("name", "应用"),
                               command=lambda p=app.get("path", ""): self._launch(p))
            if not self.cfg.get("quick_launch"):
                ql.add_command(label="（在 config.json 里配置）", state="disabled")
            m.add_cascade(label="快速打开", menu=ql)
        if c.get("screenshot"):
            m.add_command(label="截图存桌面", command=self._screenshot)
        if c.get("volume") and IS_WIN:
            vol = tk.Menu(m, tearoff=0)
            vol.add_command(label="音量 +", command=lambda: win_volume("up"))
            vol.add_command(label="音量 -", command=lambda: win_volume("down"))
            vol.add_command(label="静音/取消", command=lambda: win_volume("mute"))
            m.add_cascade(label="音量", menu=vol)

        m.add_separator()
        m.add_command(label="检查更新（当前 v%s）" % self.app_version,
                      command=self._manual_update_check)
        m.add_command(label="退出", command=self.quit)
        self.menu = m

    # ------------------------------------------------------------ 切换宠物
    def switch_pet(self, pet_id):
        """切换形象：重载图片 / 文案 / 动作帧，记住选择，刷新菜单与托盘。"""
        target = next((x for x in self.pets_cfg["pets"]
                       if x["id"] == pet_id), None)
        if target is None or pet_id == self.pet_id:
            return
        self.pet_id = pet_id
        self.pet = target
        self.pets_cfg["active"] = pet_id
        save_active_pet(pet_id)

        self.base_img = self._load_pet_image(target["image"])
        self.pools = load_dialogues(res_path(target["dialogues"]))
        self.frames_walk, self.frames_idle = self._load_frames(target)
        self._frame_idx = 0
        self._anim = None                        # 中断旧动作，避免叠播
        self.height = int(target.get("height_px") or
                          self.cfg.get("pet_height_px", DEFAULT_HEIGHT))
        self._render()                           # 按新图宽高比重建显示缓存
        self._build_menu()                       # 刷新「当前：xx」与勾选态
        self._refresh_tray_icon()
        self._update_titles()
        self._anim_squash()                      # 出场来个压扁回弹
        self.say(target.get("greeting") or
                 ("变成%s啦～" % target["name"]), duration=2600)

    # ------------------------------------------------------------ 巡逻形象联动
    def _boot_sync_patrol_pet(self):
        """启动阶段同步形象。此时 UI 尚未建立，只改内存与文件，不能调 switch_pet。

        覆盖两种场景：上次在巡逻中直接退出（active 已是划船形象，
        boat_prev_pet 记着原形象），以及用户手动改了 config.json 的巡逻开关。
        """
        boat = self._boat_pet_id
        if not boat:
            return
        ids = [x["id"] for x in self.pets_cfg["pets"]]
        prev = self.state.get("boat_prev_pet") or ""
        if prev and prev not in ids:
            prev = ""
            self.state["boat_prev_pet"] = ""
        state_dirty = False
        if self.cfg.get("auto_patrol"):
            if self.pet_id != boat:
                if not prev:
                    self.state["boat_prev_pet"] = self.pet_id
                    state_dirty = True
                self.pet_id = boat
        elif self.pet_id == boat and prev and prev != boat:
            self.pet_id = prev
            self.state["boat_prev_pet"] = ""
            state_dirty = True
        if self.pet_id != self.pets_cfg["active"]:
            self.pets_cfg["active"] = self.pet_id
            save_active_pet(self.pet_id)
        if state_dirty:
            save_json(STATE_PATH, self.state)

    def _sync_patrol_pet(self):
        """开巡逻 -> 自动换划船形象；关巡逻 -> 还原开之前的形象。

        只在巡逻开关被点击时调用。用户在「切换宠物」里手动选形象不会触发
        这里，所以巡逻期间手动选的形象不会被强行拉回划船形象。
        """
        boat = self._boat_pet_id
        if not boat:
            return
        ids = [x["id"] for x in self.pets_cfg["pets"]]
        prev = self.state.get("boat_prev_pet") or ""
        if self.cfg.get("auto_patrol"):
            if self.pet_id != boat:
                self.state["boat_prev_pet"] = self.pet_id
                save_json(STATE_PATH, self.state)
                self.switch_pet(boat)
        else:
            if self.pet_id == boat and prev in ids and prev != boat:
                self.switch_pet(prev)
            if self.state.get("boat_prev_pet"):
                self.state["boat_prev_pet"] = ""
                save_json(STATE_PATH, self.state)

    def _toggle_boat_fx(self):
        self.cfg["boat_fx"] = bool(self._boat_var.get())
        save_json(CONFIG_PATH, self.cfg)
        self._apply()                            # 立刻刷新掉/加上水浪层

    def _refresh_tray_icon(self):
        if self._tray is None:
            return
        try:
            self._tray.icon = self.base_img.resize((64, 64), Image.LANCZOS)
        except Exception:
            pass

    def _update_titles(self):
        try:
            self.root.title("桌面宠物 · %s" % self.pet["name"])
            if self._tray is not None:
                self._tray.title = self.pet["name"]
        except Exception:
            pass

    # ------------------------------------------------------------ 菜单动作
    def _comp(self, key):
        return bool(self.cfg["components"].get(key))

    def _toggle_comp(self, key):
        self.cfg["components"][key] = bool(self._comp_vars[key].get())
        save_json(CONFIG_PATH, self.cfg)
        if key == "pomodoro" and not self.cfg["components"][key]:
            self._pomo_stop(silent=True)
        self._build_panel()

    def _set_scale(self, v):
        self.scale = v
        self._render()

    def _set_opacity(self, v):
        self.cfg["opacity"] = v
        save_json(CONFIG_PATH, self.cfg)
        self.win.attributes("-alpha", v)

    def _toggle_topmost(self):
        v = bool(self._top_var.get())
        self.cfg["topmost"] = v
        save_json(CONFIG_PATH, self.cfg)
        self.win.attributes("-topmost", v)

    def _toggle_patrol(self):
        self.cfg["auto_patrol"] = bool(self._patrol_var.get())
        save_json(CONFIG_PATH, self.cfg)
        self._sync_patrol_pet()                 # 形象随巡逻开关联动
        if self.cfg["auto_patrol"]:
            self.root.after(60, self._patrol_step)

    def _toggle_follow(self):
        self.cfg["follow_mouse"] = bool(self._follow_var.get())
        save_json(CONFIG_PATH, self.cfg)
        if self.cfg["follow_mouse"]:
            self.root.after(120, self._follow_step)

    def _toggle_autostart(self):
        want = bool(self._auto_var.get())
        ok, msg = set_autostart(want)
        if ok:
            self.cfg["autostart"] = want
            save_json(CONFIG_PATH, self.cfg)
            self.say("已%s开机自启" % ("开启" if want else "关闭"))
        else:
            self._auto_var.set(False)
            self.say(msg or "设置失败")

    # ------------------------------------------------------------ 巡逻 / 跟随
    def _patrol_step(self):
        """只负责位移与换帧；颠簸和倾斜由动画循环按 auto_patrol 状态合成。"""
        if not self.cfg.get("auto_patrol"):
            return
        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        pw, ph = getattr(self, "_pet_size", (self.height, self.height))
        self.x += self.patrol_dir * 2
        self.y = sh - ph - 40                      # 沿屏幕底部走
        if self.x <= 0 or self.x + pw >= sw:
            self.patrol_dir *= -1
            self.flip = self.patrol_dir > 0
            self._render()                         # 翻向要重建缓存
        elif self.frames_walk:
            self._frame_idx = (self._frame_idx + 1) % len(self.frames_walk)
            self._render(img=self.frames_walk[self._frame_idx])
        self.root.after(60, self._patrol_step)

    def _follow_step(self):
        if not self.cfg.get("follow_mouse"):
            return
        mx, my = self.root.winfo_pointerxy()
        dx = mx - (self.x + self._pet_size[0] / 2)
        dy = my - (self.y + self._pet_size[1] / 2)
        dist = math.hypot(dx, dy)
        if dist > 90:                            # 慢慢挪，不抢鼠标
            self.x += dx / dist * 2
            self.y += dy / dist * 2
            new_flip = dx > 0
            if new_flip != self.flip:
                self.flip = new_flip
                self._render()
        self.root.after(120, self._follow_step)

    # ------------------------------------------------------------ 组件逻辑
    def _offwork_text(self, now):
        if now.weekday() >= 5:
            return "今天不上班 ✨"
        clock = normalize_offwork_time(self.cfg.get("offwork_time", "18:00")) or "18:00"
        hh, mm = clock.split(":")
        target = now.replace(hour=int(hh), minute=int(mm), second=0, microsecond=0)
        if now >= target:
            return "已下班，自由啦！"
        left = target - now
        h, r = divmod(int(left.total_seconds()), 3600)
        return "距下班 %d:%02d" % (h, r // 60)

    def _offwork_dialog(self):
        """改下班时间：立刻写入 config.json，面板马上按新时间倒计时。"""
        top = tk.Toplevel(self.root)
        top.title("设置下班时间")
        top.attributes("-topmost", True)
        top.resizable(False, False)
        tk.Label(top, text="下班时间（24 小时制，如 18:00、9:30）",
                 padx=12, pady=6).pack()
        current = normalize_offwork_time(self.cfg.get("offwork_time", "18:00")) or "18:00"
        e = tk.Entry(top, width=16, justify="center")
        e.insert(0, current)
        e.pack(padx=12, pady=4)
        e.focus_set()
        e.select_range(0, "end")
        hint = tk.Label(top, fg="#888888", padx=12,
                        text="保存后立刻生效，不用重启。周末仍显示「今天不上班」。")
        hint.pack()

        def ok():
            clock = normalize_offwork_time(e.get())
            if clock is None:
                hint.configure(fg="#c04040", text="请填 0:00 到 23:59，例如 18:30")
                return
            self.cfg["offwork_time"] = clock
            save_json(CONFIG_PATH, self.cfg)
            # 新时间还没到的话，允许今天再庆祝一次，避免改完时间不再到点提醒
            now = datetime.now()
            target = now.replace(hour=int(clock[:2]), minute=int(clock[3:]),
                                 second=0, microsecond=0)
            if now < target and self.state.get("celebrated_offwork") == date.today().isoformat():
                self.state["celebrated_offwork"] = ""
                self._save_state()
            top.destroy()
            self._update_panel()
            self.say("下班时间改成 %s 啦" % clock, duration=3000)

        bar = tk.Frame(top)
        bar.pack(pady=8)
        tk.Button(bar, text="保存", width=8, command=ok).pack(side="left", padx=6)
        tk.Button(bar, text="取消", width=8,
                  command=top.destroy).pack(side="left", padx=6)
        top.bind("<Return>", lambda _e: ok())
        top.bind("<Escape>", lambda _e: top.destroy())
        top.update_idletasks()
        sw, sh = top.winfo_screenwidth(), top.winfo_screenheight()
        top.geometry("+%d+%d" % ((sw - top.winfo_width()) // 2,
                                 (sh - top.winfo_height()) // 3))

    def _water_add(self):
        self.state["water"] = int(self.state.get("water", 0)) + 1
        goal = int(self.cfg.get("water_goal", 8))
        self._save_state()
        if self.state["water"] >= goal:
            self._anim_jump()
            self.say(random.choice(["今日水量达标！你真棒！", "喝满啦，皮肤会变好哦～"]))
        else:
            self.say("已记第 %d 杯，继续加油" % self.state["water"])

    def _quota_add(self):
        self.state["quota_used"] = int(self.state.get("quota_used", 0)) + 1
        self._save_state()
        limit = max(1, int(self.cfg.get("daily_quota_limit", 100)))
        left_pct = 100 - self.state["quota_used"] * 100 // limit
        if left_pct <= 20:
            self._anim_shake()
            self.say("快没额度啦（剩 %d%%），省着点用！" % left_pct)
        else:
            self.say("已记 1 次调用，今日剩余 %d%%" % left_pct)

    def _feed(self, food):
        reactions = {"奶茶": "咕噜咕噜……奶茶万岁！🧋", "炸鸡": "咔嚓咔嚓，太香了！🍗",
                     "咖啡": "精神百倍！☕", "小蛋糕": "甜甜的，心情超好～🍰"}
        self.state["last_feed"] = date.today().isoformat()
        self._add_affection(2)
        self._save_state()
        self._set_scale(min(2.5, self.scale * 1.05))   # 开心变大一点
        self._anim_jump()
        self.say(reactions.get(food, "谢谢你！"))

    def _add_affection(self, n):
        if not self._comp("affection"):
            return
        before = self._affection_level()
        self.state["affection"] = int(self.state.get("affection", 0)) + n
        self._save_state()
        after = self._affection_level()
        if after > before:
            self._anim_jump()
            self.say("好感度升到 Lv.%d！解锁了新的话～" % after)

    def _affection_level(self):
        pts = int(self.state.get("affection", 0))
        for lv, need in ((4, 100), (3, 60), (2, 30), (1, 10)):
            if pts >= need:
                return lv
        return 0

    def _pomo_start(self):
        mins = int(self.cfg.get("pomodoro_work_min", 25))
        self.pomodoro_until = time.time() + mins * 60
        self.pomodoro_mode = "work"
        self.say("专注 %d 分钟开始，我不吵你" % mins)
        self._build_panel()

    def _pomo_stop(self, silent=False):
        self.pomodoro_until = None
        self.pomodoro_mode = None
        if not silent:
            self.say("番茄钟已停止")
        self._build_panel()

    def _show_sysstatus(self):
        try:
            import psutil
            cpu = psutil.cpu_percent(interval=0.3)
            mem = psutil.virtual_memory().percent
            bat = psutil.sensors_battery()
            text = "CPU %.0f%% · 内存 %.0f%%" % (cpu, mem)
            if bat is not None:
                text += " · 电量 %d%%" % bat.percent
                if bat.percent < 20 and not bat.power_plugged:
                    text += "（快没电了！）"
            if cpu > 85:
                self._anim_squash()
                text += " · CPU 好高，我快被压垮了"
            self.say(text, duration=5000)
        except ImportError:
            self.say("系统状态组件需要 psutil：pip install psutil")

    def _todo_editor(self):
        top = tk.Toplevel(self.root)
        top.title("今日待办（最多 3 件）")
        top.attributes("-topmost", True)
        todos = list(self.state.get("todos", []))[:3]
        while len(todos) < 3:
            todos.append({"text": "", "done": False})
        entries, cvars = [], []
        for i, t in enumerate(todos):
            v = tk.BooleanVar(value=bool(t.get("done")))
            cvars.append(v)
            tk.Checkbutton(top, variable=v).grid(row=i, column=0)
            e = tk.Entry(top, width=26)
            e.insert(0, t.get("text", ""))
            e.grid(row=i, column=1, padx=4, pady=3)
            entries.append(e)

        def save():
            new = [{"text": e.get().strip(), "done": v.get()}
                   for e, v in zip(entries, cvars) if e.get().strip()]
            was = [t for t in self.state.get("todos", []) if not t.get("done")]
            self.state["todos"] = new
            self._save_state()
            top.destroy()
            undone = [t for t in new if not t["done"]]
            if not undone and new:
                self._anim_jump()
                self.say("今天的事都干完啦，可以摸鱼了！")
            elif len(undone) < len(was):
                self._anim_squash()
                self.say("完成一件，Nice！")

        tk.Button(top, text="保存", command=save).grid(row=3, column=1,
                                                       sticky="e", pady=6)

    def _launch(self, path):
        if not path:
            return
        try:
            if IS_WIN:
                os.startfile(path)                # noqa
            elif IS_MAC:
                subprocess.Popen(["open", path])
            else:
                subprocess.Popen(["xdg-open", path])
        except Exception as e:
            self.say("打不开：%s" % e)

    def _screenshot(self):
        try:
            from PIL import ImageGrab
            desktop = os.path.join(os.path.expanduser("~"), "Desktop")
            os.makedirs(desktop, exist_ok=True)
            path = os.path.join(desktop,
                                "截图_%s.png" % datetime.now().strftime("%H%M%S"))
            ImageGrab.grab().save(path)
            self.say("已截图存到桌面")
        except Exception as e:
            self.say("截图失败：%s" % e)

    # ------------------------------------------------------------ 定时任务
    # ------------------------------------------------------------ 自动更新
    def _update_log(self, msg):
        """noconsole 打包下 stdout 可能为 None，日志只写临时文件，绝不 print。"""
        try:
            path = os.path.join(tempfile.gettempdir(), "DesktopPet-update.log")
            with open(path, "a", encoding="utf-8") as f:
                f.write("%s %s\n" % (datetime.now().strftime("%H:%M:%S"), msg))
        except Exception:
            pass

    def _auto_update_check(self):
        self._start_update_check(manual=False)

    def _manual_update_check(self):
        self._start_update_check(manual=True)

    def _start_update_check(self, manual=False):
        if self._update_busy:
            if manual:
                self.say("更新正在进行中…", duration=2500)
            return
        if not self._updater:
            if manual:
                self.say("更新模块不可用（缺少 updater.py）", duration=3500)
            return
        if not self._update_settings.get("repo"):
            if manual:
                self.say("尚未配置更新仓库：请在 update.json 填 repo",
                         duration=4500)
            return
        self._update_busy = True
        if manual:
            self.say("正在检查更新…", duration=2500)
        threading.Thread(target=self._check_worker, args=(manual,),
                         daemon=True).start()

    def _check_worker(self, manual):
        try:
            info = self._updater.check(self._update_settings)
            self._update_q.append(("checked", info, manual))
        except Exception as e:
            self._update_log("检查失败: %s" % e)
            self._update_q.append(("check_failed", str(e), manual))

    def _handle_update_event(self, ev):
        """只有这里能碰 Tk：所有更新相关的 UI 都在主线程 _tick_fast 中处理。"""
        kind = ev[0]
        if kind == "checked":
            self._update_busy = False
            info = ev[1]
            if info is not None:
                self._ask_update(info)
            elif ev[2]:
                self.say("已是最新版本 v%s" % self.app_version, duration=3500)
        elif kind == "check_failed":
            self._update_busy = False
            if ev[2]:
                self.say("检查更新失败：%s" % str(ev[1])[:60], duration=5000)
        elif kind == "progress":
            if self._upd_text is not None:
                try:
                    self._upd_text.set(ev[2])
                    self._upd_pct.set(max(0, min(100, int(ev[1]))))
                except Exception:
                    pass
        elif kind == "apply_ready":
            self._finish_update(ev[1])
        elif kind == "error":
            self._close_progress()
            self._update_busy = False
            self.say("更新失败：%s" % str(ev[1])[:60], duration=5000)

    def _ask_update(self, info):
        top = tk.Toplevel(self.root)
        top.title("发现新版本")
        top.attributes("-topmost", True)
        top.resizable(False, False)
        tk.Label(top, padx=16, pady=8,
                 text="小仓鼠桌宠 v%s    （当前 v%s）"
                      % (info.version, self.app_version)).pack()
        box = tk.Text(top, width=50, height=8, wrap="word", padx=6, pady=6)
        box.insert("1.0", info.notes.strip() or "（本版暂无更新说明）")
        box.configure(state="disabled")
        box.pack(padx=16, pady=4)
        tk.Label(top, fg="#888888", padx=16,
                 text="更新不会清除你的设置、形象和面板位置。").pack()
        bar = tk.Frame(top)
        bar.pack(pady=10)
        tk.Button(bar, text="立即更新", width=10,
                  command=lambda: (top.destroy(),
                                   self._start_update_download(info))
                  ).pack(side="left", padx=6)
        tk.Button(bar, text="稍后再说", width=10,
                  command=top.destroy).pack(side="left", padx=6)

    def _start_update_download(self, info):
        if self._update_busy:
            return
        self._update_busy = True
        self._open_progress()
        threading.Thread(target=self._download_worker, args=(info,),
                         daemon=True).start()

    def _open_progress(self):
        self._close_progress()
        top = tk.Toplevel(self.root)
        top.title("正在更新")
        top.attributes("-topmost", True)
        top.resizable(False, False)
        self._upd_text = tk.StringVar(value="准备下载…")
        self._upd_pct = tk.IntVar(value=0)
        tk.Label(top, textvariable=self._upd_text, padx=18, pady=8).pack()
        ttk.Progressbar(top, variable=self._upd_pct, maximum=100,
                        length=300).pack(padx=18, pady=6)
        self._upd_win = top

    def _close_progress(self):
        try:
            if self._upd_win is not None and self._upd_win.winfo_exists():
                self._upd_win.destroy()
        except Exception:
            pass
        self._upd_win = None
        self._upd_text = None
        self._upd_pct = None

    def _download_worker(self, info):
        try:
            def progress(pct, text):
                self._update_q.append(("progress", pct, text))

            extract = self._updater.download(info, progress)
            payload = self._updater.prepare_payload(extract)
            self._update_q.append(("apply_ready", payload))
        except Exception as e:
            self._update_log("下载/安装失败: %s" % e)
            self._update_q.append(("error", str(e)))

    def _finish_update(self, payload):
        self._close_progress()
        self._update_busy = False
        try:
            self._updater.apply(payload, self._exe_name)
            self.say("更新包已就绪，马上重启～", duration=3000)
            self.root.after(1500, self.quit)
        except Exception as e:
            self._update_log("启动替换进程失败: %s" % e)
            self.say("更新失败：%s" % str(e)[:60], duration=5000)

    def _tick_fast(self):
        """1 秒级：面板刷新、消费后台通知、整点报时、番茄钟结束。"""
        now = datetime.now()
        # 天气/定位都在后台线程跑，Tk 不能跨线程调用，统一走这里冒气泡
        while self._notice_q:
            try:
                text, dur = self._notice_q.pop(0)
                self.say(text, duration=dur)
            except Exception:
                pass
        while self._update_q:
            try:
                self._handle_update_event(self._update_q.pop(0))
            except Exception as e:
                self._update_log("更新事件处理失败: %s" % e)
        self._update_panel()
        if self._comp("clock") and now.minute == 0 and now.hour != self._chimed_hour:
            self._chimed_hour = now.hour
            pool = self.pools.get(time_pool_name(now.hour),
                                  self.pools.get("general", []))
            if pool:
                self.say(random.choice(pool))
        if self.pomodoro_mode and time.time() >= (self.pomodoro_until or 0):
            if self.pomodoro_mode == "work":
                self._anim_jump()
                self.say("时间到！休息 %d 分钟吧～" %
                         int(self.cfg.get("pomodoro_break_min", 5)), duration=5000)
                self.pomodoro_until = time.time() + \
                    int(self.cfg.get("pomodoro_break_min", 5)) * 60
                self.pomodoro_mode = "break"
            else:
                self._pomo_stop()
                self.say("休息结束，继续加油！")
        self.root.after(1000, self._tick_fast)

    def _tick_slow(self):
        """5 秒级：喝水提醒、摸鱼检测、天气刷新、状态联动。"""
        now = time.time()
        # 喝水：每小时提醒一次
        if self._comp("water") and not self.pomodoro_mode:
            if now - float(self.state.get("last_water_remind", 0)) >= 3600:
                self.state["last_water_remind"] = now
                self._save_state()
                self.say(random.choice(["该喝水啦～", "起来倒杯水，顺便活动一下",
                                        "喝水时间到！"]))
        # 摸鱼检测（番茄钟专注期间自动暂停）
        if self._comp("fish_detect") and not self.pomodoro_mode:
            idle = win_idle_seconds()
            if idle is not None and idle >= int(self.cfg.get("fish_idle_sec", 300)) \
                    and now - self._fish_nagged > 600:
                self._fish_nagged = now
                self.say(random.choice(["又在摸鱼？", "屏幕前的你还在吗？",
                                        "我盯——"]))
        # 天气：30 分钟刷一次；自动定位模式下每 30 分钟重新按 IP 定位，
        # 这样换 WiFi / 换网络 / 开关 VPN 后位置会自己跟上来。
        if self._comp("weather"):
            auto = bool(self.cfg.get("city_auto"))
            if auto and not self.cfg.get("city_coord") and not self._geo_busy:
                self._relocate(force=True)               # 首次启动先定位
            elif auto:
                self._relocate()                          # 内部自带 30 分钟节流
            if (not auto or self.cfg.get("city_coord")) \
                    and now - self._weather_fetched > 1800:
                self._weather_fetched = now
                threading.Thread(target=self._fetch_weather, daemon=True).start()
        # 下班联动：最后 10 分钟躁动，到点庆祝
        if self._comp("offwork"):
            text = self._offwork_text(datetime.now())
            if text.startswith("距下班 0:") and random.random() < 0.05:
                self._anim_shake()               # 最后 10 分钟频繁看表
            if text.startswith("已下班") and \
                    self.state.get("celebrated_offwork") != date.today().isoformat():
                self.state["celebrated_offwork"] = date.today().isoformat()
                self._save_state()
                self._anim_jump()
                self.say("下班啦！跑！", duration=5000)
        # 太久没投喂变蔫
        if self._comp("feed"):
            last = self.state.get("last_feed", "")
            try:
                days = (date.today() - date.fromisoformat(last)).days if last else 99
            except ValueError:
                days = 99
            if days >= 3 and self.state.get("gloomy_noticed") != date.today().isoformat():
                self.state["gloomy_noticed"] = date.today().isoformat()
                self._save_state()
                self._set_scale(max(0.4, self.scale * 0.95))
                self.say("饿扁了…… %d 天没喂我了" % days, duration=5000)
        self.root.after(5000, self._tick_slow)

    # ------------------------------------------------------------ 天气与位置
    def _ui_say(self, text, duration=4000):
        """后台线程专用：只入队，由主线程 _tick_fast 取走，绝不跨线程碰 Tk。"""
        try:
            if len(self._notice_q) < 8:
                self._notice_q.append((text, duration))
        except Exception:
            pass

    def _weather_location(self):
        """返回 (wttr.in 查询串, 面板显示名)。

        自动定位开启且已有缓存坐标 → 用经纬度（比城市名精确，也不怕同名地名）；
        否则 → 用 config.json 里手写的城市名。面板上那个地名就是这里返回的值：
        旧版本显示「北京」并不是接口定位的结果，只是把这个字符串拼了上去。
        """
        if self.cfg.get("city_auto") and self.cfg.get("city_coord"):
            return (str(self.cfg["city_coord"]),
                    str(self.cfg.get("city_auto_label") or "当前位置"))
        city = str(self.cfg.get("city", "北京")).strip() or "北京"
        return city, city

    def _relocate(self, force=False, notify=False):
        """后台线程：请求不带地名的 wttr.in，由服务端按出口 IP 反查 nearest_area。

        结果（经纬度 + 中文地名）写入 config.json 缓存，并把天气刷新时间清零，
        下一个 5 秒 tick 就会用新位置重新拉天气，无需重启程序。
        force=True 用于菜单「重新定位」和刚开启自动定位时立即执行一次。
        """
        if self._geo_busy:
            return
        if not force and self.cfg.get("city_coord") \
                and time.time() - self._geo_fetched < 1800:
            return
        self._geo_busy = True
        self._geo_fetched = time.time()

        def work():
            try:
                import urllib.request
                req = urllib.request.Request(
                    "https://wttr.in/?format=j1&lang=zh",
                    headers={"User-Agent": "curl/8"})
                with urllib.request.urlopen(req, timeout=8) as r:
                    data = json.loads(r.read().decode("utf-8"))
                na = data["nearest_area"][0]
                lat = _geo_first(na.get("latitude"))
                lon = _geo_first(na.get("longitude"))
                area = _geo_first(na.get("areaName"))
                region = _geo_first(na.get("region"))
                if not (lat and lon):
                    raise ValueError("定位结果缺少经纬度")
                label = CN_CITY.get(area.lower(), area) or "当前位置"
                region_cn = CN_CITY.get(region.lower())
                if region_cn and region_cn != label:
                    label = "%s·%s" % (region_cn, label)   # 例：Pootung/Shanghai → 上海·浦东
                label = label[:10]
                self.cfg["city_coord"] = "%s,%s" % (lat, lon)
                self.cfg["city_auto_label"] = label
                save_json(CONFIG_PATH, self.cfg)
                self._weather_fetched = 0                 # 用新位置立刻重取天气
                if notify:
                    self._ui_say("定位到 %s（%s, %s），天气已更新"
                                 % (label, lat, lon), 4500)
            except Exception as e:
                self._geo_fetched = 0                     # 失败后下次 tick 就重试
                if notify:
                    self._ui_say("自动定位失败（%s），先用手动城市 %s" % (
                        type(e).__name__, self.cfg.get("city", "北京")), 4500)
            finally:
                self._geo_busy = False

        threading.Thread(target=work, daemon=True).start()

    def _toggle_city_auto(self):
        v = bool(self._city_auto_var.get())
        self.cfg["city_auto"] = v
        save_json(CONFIG_PATH, self.cfg)
        if v:
            self._relocate(force=True, notify=True)
            self.say("已开启自动定位，正在按网络位置找城市…", duration=3500)
        else:
            self._weather_fetched = 0
            self.say("已切回手动城市：%s" % self.cfg.get("city", "北京"),
                     duration=3500)

    def _menu_relocate(self):
        """点「重新定位」= 用网络位置更新一次，并切到自动定位模式。"""
        self.cfg["city_auto"] = True
        save_json(CONFIG_PATH, self.cfg)
        self._relocate(force=True, notify=True)
        self.say("正在重新定位…", duration=3000)

    def _refresh_weather_now(self):
        self._weather_fetched = time.time()
        threading.Thread(target=self._fetch_weather, daemon=True).start()
        self.say("正在刷新天气…", duration=2500)

    def _city_dialog(self):
        """手动改城市：立即写盘并刷新，不用再手改 config.json + 重启。"""
        top = tk.Toplevel(self.root)
        top.title("设置天气城市")
        top.attributes("-topmost", True)
        top.resizable(False, False)
        tk.Label(top, text="城市名（中文 / 拼音 / 英文，如 北京、Shanghai）",
                 padx=12, pady=6).pack()
        e = tk.Entry(top, width=28)
        e.insert(0, str(self.cfg.get("city", "北京")))
        e.pack(padx=12, pady=4)
        e.focus_set()
        e.select_range(0, "end")
        tk.Label(top, fg="#888888", padx=12,
                 text="保存后会关闭自动定位，并立刻重新拉天气").pack()

        def ok():
            name = e.get().strip()
            if not name:
                return
            self.cfg["city"] = name
            self.cfg["city_auto"] = False
            save_json(CONFIG_PATH, self.cfg)
            top.destroy()
            self._refresh_weather_now()
            self.say("天气城市改成 %s 啦" % name, duration=3500)

        bar = tk.Frame(top)
        bar.pack(pady=8)
        tk.Button(bar, text="保存", width=8, command=ok).pack(side="left", padx=6)
        tk.Button(bar, text="取消", width=8,
                  command=top.destroy).pack(side="left", padx=6)
        top.bind("<Return>", lambda _e: ok())
        top.bind("<Escape>", lambda _e: top.destroy())

    def _fetch_weather(self):
        """wttr.in 免 key 接口；位置由 _weather_location() 决定，失败时降级不崩。"""
        loc, label = self._weather_location()
        try:
            import urllib.parse
            import urllib.request
            url = "https://wttr.in/%s?format=j1&lang=zh" % urllib.parse.quote(loc, safe=",")
            req = urllib.request.Request(url, headers={"User-Agent": "curl/8"})
            with urllib.request.urlopen(req, timeout=8) as r:
                data = json.loads(r.read().decode("utf-8"))
            cur = data["current_condition"][0]
            temp = cur.get("temp_C", "?")
            try:
                desc = cur["lang_zh"][0]["value"]
            except Exception:
                desc = cur["weatherDesc"][0]["value"]
            self.weather_text = "%s %s %s°C" % (label, desc, temp)
            # 极端天气提醒
            try:
                t = int(temp)
                if t >= 35:
                    self._ui_say("今天 %s°C 高温，注意防暑！" % t)
                elif t <= 0:
                    self._ui_say("今天 %s°C，多穿点！" % t)
            except (TypeError, ValueError):
                pass
            if any(k in desc for k in ("雨", "雪", "雷")):
                self._ui_say("外面%s呢，出门带伞哦" % desc)
        except Exception:
            self._weather_fetched = time.time() - 1500  # 5 分钟后重试，别等满 30 分钟
            if self.weather_text.startswith("天气获取中"):
                self.weather_text = "%s 天气暂不可用" % label

    # ------------------------------------------------------------ 状态维护
    def _daily_reset(self):
        today = date.today().isoformat()
        if self.state.get("date") != today:
            self.state["date"] = today
            self.state["water"] = 0
            self.state["quota_used"] = 0
            self._save_state()

    def _daily_reset_force(self):
        self.state["water"] = 0
        self.state["quota_used"] = 0
        self._save_state()
        self.say("今日计数已清零")

    def _save_state(self):
        save_json(STATE_PATH, self.state)

    # ------------------------------------------------------------ 托盘
    def _start_tray(self):
        """系统托盘图标（依赖 pystray，装不上就只留右键菜单）。"""
        try:
            import pystray
        except ImportError:
            return
        try:
            icon_img = self.base_img.resize((64, 64), Image.LANCZOS)
            menu = pystray.Menu(
                pystray.MenuItem("退出", lambda: self.root.after(0, self.quit)))
            self._tray = pystray.Icon("DesktopPet", icon_img,
                                     self.pet["name"], menu)
            threading.Thread(target=self._tray.run, daemon=True).start()
        except Exception as e:
            print("托盘启动失败（不影响使用）:", e)

    # ------------------------------------------------------------ 自测
    def _selftest(self):
        """冒烟测试：窗口/动画/气泡/组件/退出全过一遍，3 秒自动结束。"""
        print("[selftest] 宠物形象: %d 个 -> %s" % (
            len(self.pets_cfg["pets"]),
            [(x["name"], x["image"]) for x in self.pets_cfg["pets"]]))
        print("[selftest] 当前形象: %s  角色图 %dx%d  文案分区 %s" % (
            self.pet["name"], self.base_img.width, self.base_img.height,
            {k: len(v) for k, v in self.pools.items()}))
        print("[selftest] 配置组件: %d 项, 默认开启: %s" % (
            len(self.cfg["components"]),
            [k for k, v in self.cfg["components"].items() if v]))
        print("[selftest] 文案分区: %s" %
              {k: len(v) for k, v in self.pools.items()})
        self._anim_squash()
        self.say("自测气泡：你好呀")
        self._update_panel()
        print("[selftest] 动画引擎/气泡/面板 已触发（呼吸基线运行中）")
        self.root.after(2500, self._selftest_done)

    def _selftest_done(self):
        print("[selftest] PASS")
        self.quit()

    # ------------------------------------------------------------ 退出
    def quit(self):
        self._save_panel_pose()
        self._save_state()
        save_json(CONFIG_PATH, self.cfg)
        save_active_pet(self.pet_id)
        if self._tray is not None:
            try:
                self._tray.stop()
            except Exception:
                pass
        try:
            self.root.destroy()
        except Exception:
            pass

    def run(self):
        self.root.mainloop()


if __name__ == "__main__":
    DesktopPet().run()
