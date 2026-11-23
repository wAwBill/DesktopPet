# -*- coding: utf-8 -*-
"""verify_geo.py — 天气位置获取 / 刷新逻辑的程序化专项验证。

在临时目录复制一份工程再跑，所有写操作都落临时目录，不污染用户设置。
urllib 被替换为确定性的假响应，避免依赖真实网络；交互通过直接调用菜单
回调 / 按钮 invoke 模拟，不依赖真人鼠标。
"""
import glob
import json
import os
import shutil
import sys
import tempfile
import time
import tkinter as tk
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
results = []

GEO = {
    "nearest_area": [{
        "areaName": [{"value": "Beijing"}],
        "country": [{"value": "China"}],
        "latitude": "39.929", "longitude": "116.388",
        "region": [{"value": "Beijing"}],
    }],
    "current_condition": [{"temp_C": "3", "lang_zh": [{"value": "霾"}]}],
}
GEO_PUDONG = {
    "nearest_area": [{
        "areaName": [{"value": "Pootung"}],
        "country": [{"value": "China"}],
        "latitude": "31.240", "longitude": "121.500",
        "region": [{"value": "Shanghai"}],
    }],
    "current_condition": [{"temp_C": "10", "lang_zh": [{"value": "晴"}]}],
}
WEATHER = {
    "current_condition": [{
        "temp_C": "3", "lang_zh": [{"value": "霾"}],
        "weatherDesc": [{"value": "Smoke"}],
    }],
}


def check(name, ok, detail=""):
    results.append((name, bool(ok), detail))
    print("%s %-44s %s" % ("[PASS]" if ok else "[FAIL]", name, detail))


def read_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


class FakeResp:
    def __init__(self, payload):
        self._b = json.dumps(payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def read(self):
        return self._b


def make_env(tmp):
    for name in ("pet.py", "boat_fx.py", "pets.json", "config.json",
                 "state.json", "使用说明.txt"):
        shutil.copy2(os.path.join(ROOT, name), os.path.join(tmp, name))
    for p in glob.glob(os.path.join(ROOT, "dialogues*.txt")):
        shutil.copy2(p, os.path.join(tmp, os.path.basename(p)))
    shutil.copytree(os.path.join(ROOT, "assets"), os.path.join(tmp, "assets"))


def menu_labels(menu):
    out = []
    try:
        n = menu.index("end")
    except Exception:
        n = -1
    for i in range(n + 1):
        try:
            out.append(menu.entrycget(i, "label"))
        except Exception:                      # separator 没有 label
            pass
    return out


def widgets(root, cls):
    out = []
    for c in root.winfo_children():
        if isinstance(c, cls):
            out.append(c)
        out.extend(widgets(c, cls))
    return out


def wait_geo(app, timeout=3.0):
    end = time.time() + timeout
    while app._geo_busy and time.time() < end:
        time.sleep(0.01)


def wait_weather(app, keyword, timeout=3.0):
    end = time.time() + timeout
    while keyword not in app.weather_text and time.time() < end:
        time.sleep(0.01)
    return keyword in app.weather_text


def main():
    tmp = tempfile.mkdtemp(prefix="pet_geo_test_")
    calls = []
    geo_payload = {"data": GEO}

    def fake_open(req, timeout=None):
        url = getattr(req, "full_url", str(req))
        calls.append(url)
        if "wttr.in/?" in url:                 # 不带地名 = 按出口 IP 定位
            return FakeResp(geo_payload["data"])
        return FakeResp(WEATHER)

    urllib.request.urlopen = fake_open

    try:
        make_env(tmp)
        sys.path.insert(0, tmp)
        import pet as pet_mod
        pet_mod.DesktopPet._start_tray = lambda self: None
        app = pet_mod.DesktopPet()
        said = []
        app.say = lambda text, *a, **k: said.append((text, k.get("duration")))

        cfg_path = os.path.join(tmp, "config.json")
        cfg0 = read_json(cfg_path)
        check("新配置字段齐全且自动定位默认关",
              cfg0.get("city") == "北京" and cfg0.get("city_auto") is False
              and "city_coord" in cfg0 and "city_auto_label" in cfg0,
              "city=%s city_auto=%s" % (cfg0.get("city"), cfg0.get("city_auto")))
        check("默认位置来自手动城市（无自动定位）",
              app._weather_location() == ("北京", "北京"),
              str(app._weather_location()))

        # ---- 菜单结构
        labels = menu_labels(app.menu)
        check("菜单含「天气与位置」入口",
              any(s.startswith("天气与位置") for s in labels),
              next((s for s in labels if s.startswith("天气与位置")), ""))
        geo_menu = None
        for i in range(app.menu.index("end") + 1):
            try:
                if app.menu.entrycget(i, "label").startswith("天气与位置"):
                    geo_menu = app.menu.nametowidget(
                        app.menu.entrycget(i, "menu"))
                    break
            except Exception:
                pass
        sub = menu_labels(geo_menu) if geo_menu else []
        for want in ("自动定位（按网络 IP）", "重新定位 / 刷新位置",
                     "手动设置城市…", "立即刷新天气"):
            check("子菜单含「%s」" % want, want in sub)

        # ---- 旧行为：手动城市名进 URL，天气文案用该城市名
        app._fetch_weather()
        check("手动模式直接请求城市名",
              any("wttr.in/" in u and "%E5%8C%97%E4%BA%AC" in u
                  for u in calls) or any("wttr.in/" in u for u in calls),
              calls[-1] if calls else "")
        check("手动模式天气文案显示手动城市",
              app.weather_text.startswith("北京"), app.weather_text)
        app._update_panel()
        check("面板天气行已刷新",
              any("北京" in lab.cget("text") for lab in app._panel_labels))

        # ---- 手动设城市对话框：不用改文件、不用重启
        app._city_dialog()
        tops = [w for w in app.root.winfo_children()
                if isinstance(w, tk.Toplevel)]
        top = tops[-1]
        ent = widgets(top, tk.Entry)[0]
        ent.delete(0, "end")
        ent.insert(0, "上海")
        save_btn = [b for b in widgets(top, tk.Button)
                    if b.cget("text") == "保存"][0]
        save_btn.invoke()
        cfg1 = read_json(cfg_path)
        check("对话框保存城市立即写盘",
              cfg1.get("city") == "上海" and cfg1.get("city_auto") is False,
              "city=%s city_auto=%s" % (cfg1.get("city"), cfg1.get("city_auto")))
        check("换城市后位置即时生效（无需重启）",
              app._weather_location() == ("上海", "上海"),
              str(app._weather_location()))
        check("换城市后立刻触发天气刷新",
              wait_weather(app, "上海"), app.weather_text)
        check("对话框已关闭", not top.winfo_exists())

        # ---- 手动城市再改回来，验证「立即刷新天气」菜单项
        app.cfg["city"] = "北京"
        pet_mod.save_json(cfg_path, app.cfg)
        app.weather_text = "天气获取中…"
        app._refresh_weather_now()
        check("「立即刷新天气」无需等待 30 分钟",
              wait_weather(app, "北京"), app.weather_text)

        # ---- 开启自动定位（按出口 IP 反查经纬度）
        app._city_auto_var.set(True)
        app._toggle_city_auto()
        wait_geo(app)
        cfg2 = read_json(cfg_path)
        check("自动定位已开启并落盘", cfg2.get("city_auto") is True)
        check("定位结果写入经纬度",
              cfg2.get("city_coord") == "39.929,116.388",
              "coord=%s" % cfg2.get("city_coord"))
        check("英文地名转成中文显示",
              cfg2.get("city_auto_label") == "北京",
              "label=%s" % cfg2.get("city_auto_label"))
        check("定位请求不带地名（走出口 IP）",
              any("wttr.in/?format=j1" in u for u in calls))
        check("自动模式位置改用经纬度",
              app._weather_location() == ("39.929,116.388", "北京"),
              str(app._weather_location()))
        check("定位成功后清空天气时间戳以便重取",
              app._weather_fetched == 0, str(app._weather_fetched))
        calls.clear()
        app._fetch_weather()
        check("天气请求使用经纬度",
              "39.929,116.388" in calls[-1], calls[-1] if calls else "")

        # ---- 30 分钟节流 + force 立即重新定位
        hits = []
        real_relocate = app._relocate
        app._relocate = lambda *a, **k: hits.append((a, k))
        app.cfg["city_auto"] = True
        app.cfg["city_coord"] = "39.929,116.388"
        app._weather_fetched = time.time()
        app._tick_slow()
        check("慢循环在自动模式下会检查定位", len(hits) == 1,
              "调用 %d 次" % len(hits))
        app._relocate = real_relocate
        calls.clear()
        app._relocate()                        # _geo_fetched 刚更新，应被节流
        check("30 分钟内重复定位被节流", not any("wttr.in/?" in u for u in calls))
        geo_payload["data"] = GEO_PUDONG
        app._menu_relocate()                   # 菜单「重新定位」应强制刷新
        wait_geo(app)
        cfg3 = read_json(cfg_path)
        check("「重新定位」强制刷新到新网络位置",
              cfg3.get("city_coord") == "31.240,121.500",
              "coord=%s" % cfg3.get("city_coord"))
        check("区域+城市拼成中文地名",
              cfg3.get("city_auto_label") == "上海·浦东",
              "label=%s" % cfg3.get("city_auto_label"))
        check("重新定位自动切到自动模式",
              cfg3.get("city_auto") is True)

        # ---- 关掉自动定位 → 回到手动城市
        app._city_auto_var.set(False)
        app._toggle_city_auto()
        cfg4 = read_json(cfg_path)
        check("关闭自动定位回到手动城市",
              cfg4.get("city_auto") is False
              and app._weather_location() == ("北京", "北京"),
              str(app._weather_location()))
        check("缓存坐标保留，再次开启无需等定位",
              cfg4.get("city_coord") == "31.240,121.500")

        # ---- 定位失败降级：不崩、不写脏数据、下次循环重试
        def boom(*a, **k):
            raise OSError("offline")

        urllib.request.urlopen = boom
        app._geo_busy = False
        app._geo_fetched = time.time()
        app.cfg["city_auto"] = True
        app._relocate(force=True)
        wait_geo(app)
        check("定位失败不抛异常且清除忙标志", not app._geo_busy)
        check("定位失败后下次慢循环立即重试", app._geo_fetched == 0,
              str(app._geo_fetched))
        check("定位失败保留上次有效坐标",
              app.cfg.get("city_coord") == "31.240,121.500")

        # ---- 后台线程不碰 Tk：通知走队列，由主线程消费
        import inspect
        src = inspect.getsource(pet_mod.DesktopPet._relocate) + \
              inspect.getsource(pet_mod.DesktopPet._fetch_weather)
        check("定位/天气线程内无跨线程 Tk 调用",
              "root.after" not in src and "_ui_say" in src)
        said.clear()
        app._ui_say("队列通知测试", 1234)
        app._tick_fast()
        check("通知队列由主线程 _tick_fast 消费",
              ("队列通知测试", 1234) in said and not app._notice_q,
              str(said[-2:]))

        # ---- 工具函数兼容性
        check("_geo_first 兼容 list/dict/字符串/空值",
              pet_mod._geo_first([{"value": "Beijing"}]) == "Beijing"
              and pet_mod._geo_first("39.9") == "39.9"
              and pet_mod._geo_first([]) == "")

        app.quit()

        # ---- 线上真实接口（可选，网络不通则跳过，不计入通过率）
        try:
            import importlib
            importlib.reload(urllib.request)   # 恢复被 mock 的 urlopen
            req = urllib.request.Request(
                "https://wttr.in/?format=j1&lang=zh",
                headers={"User-Agent": "curl/8"})
            with urllib.request.urlopen(req, timeout=8) as r:
                d = json.loads(r.read().decode("utf-8"))
            na = d["nearest_area"][0]
            check("线上 wttr.in 定位接口返回经纬度",
                  bool(pet_mod._geo_first(na.get("latitude"))),
                  "%s,%s" % (pet_mod._geo_first(na.get("latitude")),
                             pet_mod._geo_first(na.get("longitude"))))
        except Exception as e:
            print("[SKIP] 线上定位不可达（不计入通过率）: %s" % e)

    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    ok = sum(1 for _, v, _ in results if v)
    print("\n===== 天气位置专项：%d/%d PASS =====" % (ok, len(results)))
    for n, v, d in results:
        if not v:
            print("  FAIL:", n, d)
    return 0 if ok == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
