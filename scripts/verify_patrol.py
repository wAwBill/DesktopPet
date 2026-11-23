# -*- coding: utf-8 -*-
"""verify_patrol.py — 巡逻/划船形象联动的程序化交互验证。

在临时目录里复制一份完整工程再跑，所有写操作（config/state/pets.json）
都落在临时目录，绝不污染用户当前设置。用直接调用菜单回调的方式模拟点击，
不依赖真人鼠标。
"""
import glob
import json
import os
import shutil
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
results = []


def check(name, ok, detail=""):
    results.append((name, bool(ok), detail))
    print("%s %-42s %s" % ("[PASS]" if ok else "[FAIL]", name, detail))


def read_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def make_env(tmp):
    for name in ("pet.py", "boat_fx.py", "pets.json", "config.json",
                 "state.json", "使用说明.txt"):
        shutil.copy2(os.path.join(ROOT, name), os.path.join(tmp, name))
    for p in glob.glob(os.path.join(ROOT, "dialogues*.txt")):
        shutil.copy2(p, os.path.join(tmp, os.path.basename(p)))
    shutil.copytree(os.path.join(ROOT, "assets"), os.path.join(tmp, "assets"))


def new_app(pet_mod, tmp, cfg=None, pets=None, state=None):
    """按指定配置重建一份环境，再创建 DesktopPet 实例。"""
    if cfg is not None:
        with open(os.path.join(tmp, "config.json"), "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
    if pets is not None:
        with open(os.path.join(tmp, "pets.json"), "w", encoding="utf-8") as f:
            json.dump(pets, f, ensure_ascii=False, indent=2)
    if state is not None:
        with open(os.path.join(tmp, "state.json"), "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
    return pet_mod.DesktopPet()


def menu_labels(menu):
    out = []
    try:
        n = menu.index("end")
    except Exception:
        n = -1
    for i in range(n + 1):
        try:
            out.append(menu.entrycget(i, "label"))
        except Exception:                     # separator 没有 label
            pass
    return out


def main():
    tmp = tempfile.mkdtemp(prefix="pet_patrol_test_")
    try:
        make_env(tmp)
        sys.path.insert(0, tmp)
        import pet as pet_mod
        pet_mod.DesktopPet._start_tray = lambda self: None   # 不启真实托盘线程

        cfg0 = read_json(os.path.join(tmp, "config.json"))
        pets0 = read_json(os.path.join(tmp, "pets.json"))
        boat_id = "luoxiaohei_boat"
        origin = pets0["active"]
        print("测试环境:", tmp)
        print("初始形象:", origin)

        app = new_app(pet_mod, tmp)
        check("划船形象已加载进菜单",
              any(x["id"] == boat_id for x in app.pets_cfg["pets"])
              and app._boat_pet_id == boat_id,
              "共 %d 个形象" % len(app.pets_cfg["pets"]))
        labels = menu_labels(app.menu)
        check("菜单含自动巡逻", "自动巡逻" in labels)
        check("菜单含划船特效开关", "划船水浪 / 船桨动画" in labels)
        check("菜单含切换宠物子菜单",
              any(s.startswith("切换宠物") for s in labels))
        check("形象配置识别 fx=boat",
              next(x for x in app.pets_cfg["pets"]
                   if x["id"] == boat_id)["fx"] == "boat")
        check("默认不开启巡逻", not app.cfg.get("auto_patrol"))

        # ---- 开启巡逻：自动换形象 + 记住原形象
        app._patrol_var.set(True)
        app._toggle_patrol()
        cfg1 = read_json(os.path.join(tmp, "config.json"))
        pets1 = read_json(os.path.join(tmp, "pets.json"))
        state1 = read_json(os.path.join(tmp, "state.json"))
        check("开启巡逻 -> 自动换成划船形象", app.pet_id == boat_id,
              "当前 %s" % app.pet_id)
        check("开启巡逻 -> 记住原形象", state1.get("boat_prev_pet") == origin,
              "prev=%s" % state1.get("boat_prev_pet"))
        check("开启巡逻 -> 配置与 active 已落盘",
              cfg1.get("auto_patrol") is True and pets1.get("active") == boat_id)
        check("划船形象单独高度生效", app.height == 220,
              "height=%d" % app.height)
        check("划船形象的文案已重载", bool(app.pools))

        # ---- 动画期间窗口尺寸恒定（含 24 相位 + 各种变换）
        sizes = set()
        fx = app._boat_fx
        for i in range(24):
            fx.t = i / 24.0
            app._apply(1 + 0.08 * (i % 3), 1 - 0.05 * (i % 4),
                       8 * (i % 5), i * 0.6, -i * 0.4)
            sizes.add(tuple(map(int, app.win.geometry().split("+")[0].split("x"))))
        check("24 帧水浪动画窗口尺寸恒定", len(sizes) == 1,
              "尺寸集合 %s" % sorted(sizes))
        check("特效层缓存按尺寸复用", fx._key == (app._pet_size[0],
                                                app._pet_size[1],
                                                bool(app.flip)),
              "key=%s" % (fx._key,))

        # ---- 关闭划船特效：不抛异常、配置落盘
        app._boat_var.set(False)
        app._toggle_boat_fx()
        app._apply()
        check("关闭划船特效后仍可渲染",
              read_json(os.path.join(tmp, "config.json")).get("boat_fx") is False)
        app._boat_var.set(True)
        app._toggle_boat_fx()

        # ---- 关闭巡逻：还原原形象
        app._patrol_var.set(False)
        app._toggle_patrol()
        state2 = read_json(os.path.join(tmp, "state.json"))
        pets2 = read_json(os.path.join(tmp, "pets.json"))
        check("关闭巡逻 -> 还原原形象", app.pet_id == origin,
              "当前 %s" % app.pet_id)
        check("关闭巡逻 -> 清空记录", not state2.get("boat_prev_pet"))
        check("关闭巡逻 -> active 已还原", pets2.get("active") == origin)
        app.quit()

        # ---- 巡逻中手动选形象：手动选择优先，关巡逻不强行还原
        app2 = new_app(pet_mod, tmp)
        app2._patrol_var.set(True)
        app2._toggle_patrol()
        app2.switch_pet("hamster")
        app2._patrol_var.set(False)
        app2._toggle_patrol()
        check("巡逻中手动换形象后关巡逻保留手动选择",
              app2.pet_id == "hamster" and not app2.state.get("boat_prev_pet"),
              "当前 %s" % app2.pet_id)
        app2.quit()

        # ---- 模拟「巡逻中直接退出后重启」：应保持划船形象且记住 prev
        cfg_on = dict(cfg0, auto_patrol=True)
        pets_on = dict(pets0, active=boat_id)
        state_on = dict(read_json(os.path.join(ROOT, "state.json")),
                        boat_prev_pet=origin)
        app3 = new_app(pet_mod, tmp, cfg_on, pets_on, state_on)
        check("巡逻中重启 -> 仍是划船形象", app3.pet_id == boat_id)
        check("巡逻中重启 -> 保留原形象记录",
              app3.state.get("boat_prev_pet") == origin)
        app3._patrol_var.set(False)
        app3._toggle_patrol()
        check("重启后关巡逻 -> 还原重启前的形象", app3.pet_id == origin)
        app3.quit()

        # ---- 模拟「关掉巡逻但外部改了 config」：启动时自动还原
        cfg_off = dict(cfg_on, auto_patrol=False)
        state_prev = dict(state_on, boat_prev_pet=origin)
        app4 = new_app(pet_mod, tmp, cfg_off, pets_on, state_prev)
        check("配置里关掉巡逻后重启 -> 自动还原形象",
              app4.pet_id == origin and not app4.state.get("boat_prev_pet"),
              "当前 %s" % app4.pet_id)
        app4.quit()

        # ---- 其它形象不受特效影响
        app5 = new_app(pet_mod, tmp, dict(cfg0, auto_patrol=True),
                       dict(pets0, active=origin))
        app5.switch_pet("luoxiaohei_3d")
        before = app5._pet_size
        for i in range(8):
            app5._apply(1.0, 1.0, 5.0, 2.0, 1.0)
        check("非划船形象渲染不叠加特效层",
              app5._base_display is not None and app5._pet_size == before)
        app5.quit()

        ok = sum(1 for _, o, _ in results if o)
        print("\n===== %d/%d PASS =====" % (ok, len(results)))
        return 0 if ok == len(results) else 1
    finally:
        try:
            shutil.rmtree(tmp)
        except Exception:
            pass


if __name__ == "__main__":
    sys.exit(main())
