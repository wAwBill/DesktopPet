# 小仓鼠桌宠

基于 Python 3.12 + tkinter + Pillow 的 Windows 透明置顶桌宠，用 PyInstaller 打成目录版程序。
支持多形象切换（小仓鼠 / 罗小黑 / 3D 版 / 划船巡逻）、程序化动画、独立信息面板、
16 个可开关趣味组件，以及基于 GitHub Release 的自动更新。

## 目录

| 路径 | 用途 |
| --- | --- |
| `pet.py` | 主程序：窗口、动画、组件、菜单、面板 |
| `boat_fx.py` | 划船形象的水浪 / 船桨逐帧特效 |
| `updater.py` | 自动更新：清单检查、下载、安全解压、覆盖安装 |
| `assets/` | 形象 PNG（RGBA 真透明） |
| `config.json` | 默认配置模板（组件开关、城市、巡逻等） |
| `pets.json` | 形象清单，用户可自行增删 |
| `dialogues*.txt` | 分时段 / 分形象文案 |
| `version.json` | **唯一版本源**，发版只改这里 |
| `update.json` | 更新源配置（`repo` 填 GitHub 仓库，外置可改） |
| `scripts/build.py` | 本地打包 exe |
| `scripts/publish_release.py` | 生成发布 zip 与 `latest.json`（CI 与本机共用，纯 Python） |
| `scripts/verify_*.py` | 各功能的离线专项验证 |
| `.github/workflows/release.yml` | tag 触发的自动发版流水线 |
| `Docs/发布/` | 发版流程与本版更新说明 |

`state.json` 是运行数据（喝水、面板坐标等），已加入 `.gitignore`，**不入库、不进发布包**。

## 本地运行与打包

```bash
pip install -r requirements.txt
python pet.py                 # 源码运行（跳过自动更新检查）
python pet.py --selftest      # 冒烟自测，3 秒后退出
python scripts/build.py . --name 小仓鼠桌宠 --out ../dist_小仓鼠桌宠
```

## 自动更新机制

参照 `ChromeClick3.0` 的发版体系实现，链路如下：

1. 推 `vX.Y.Z` tag → GitHub Actions（`windows-latest` + Python 3.12 + PyInstaller）打包。
2. 产出 `DesktopPet.zip` 与 `latest.json`，上传为同名 Release 资源。
3. 客户端启动后延迟请求 `releases/latest/download/latest.json`，
   **国内代理优先，直连兜底**（GitHub 直连在国内常超时）。
4. 版本更高时弹出更新说明，用户确认后下载、校验、覆盖、重启。

### 与 ChromeClick 不同的三处（重要）

- **用户数据在安装目录内**：`config.json` / `state.json` / `pets.json` 就在 exe 旁边，
  不能整目录 `xcopy`。更新器采用**白名单覆盖**，且会对 `pets.json` 做合并：
  保留用户 `active` 与自定义形象，追加新版新增形象。
- **运行中的 exe 和运行库无法自覆盖**：由 `apply.cmd` 等待主进程退出后替换并重启。
  运行库在 `assets/_stage`，是磁盘上的真实文件，启动时不再解压到临时目录。
  放在 `assets` 下，是为了让已经发出去的 1.1.0 更新器（只会整份覆盖 `assets`）也能把运行库带上。
- **zip 里是干净模板**：发布脚本从源码模板生成 `config.json` / `state.json`，
  不会把本机用户设置上传到公开仓库。

### 覆盖白名单

| 处理 | 文件 |
| --- | --- |
| 覆盖 | `小仓鼠桌宠.exe`、`pet.py`、`boat_fx.py`、`updater.py`、`version.json`、`使用说明.txt`、`assets/**`（含 `_stage` 运行库）、`dialogues*.txt` |
| 合并 | `pets.json` |
| 保留 | `config.json`（新字段由程序补默认值）、`state.json`、`update.json` |

## 发版

详见 `Docs/发布/更新与发布流程.md`。简要流程：

1. 改 `version.json` 的 `version`。
2. 重写 `Docs/发布/本版更新说明.txt`（3～6 条用户能看懂的本版改动）。
3. `git commit` → `git push origin main`。
4. `git tag vX.Y.Z` → `git push origin vX.Y.Z`（**只推 main 不会发版**）。
5. Actions 变绿后，在 Release 里确认 `DesktopPet.zip` 与 `latest.json`。
6. 发版成功后清空 `本版更新说明.txt` 并 push，避免下版说明堆积。

## 更新源配置

> `update.json` 的 `repo` 已配置为 `wAwBill/DesktopPet`，程序启动 8 秒后
> 自动检查更新（右键菜单也可手动「检查更新」）。把 `repo` 留空即可跳过
> 自动更新检查（不会报错）；该文件在 exe 旁边，**改它不需要重新打包 exe**。
> 发布脚本会把 `--repo` 参数写进发布包的 `update.json`，因此下载安装的新用户
> 也能直接收到后续更新。
