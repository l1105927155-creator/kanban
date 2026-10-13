# -*- coding: utf-8 -*-
"""创建/重建桌面快捷方式「做不完啊」。

重要说明（为什么图标要用副本）：
    工作区目录（本项目所在目录）的文件带有安全策略赋予的 Low 完整性标签，
    Windows Shell 拒绝为低完整性文件渲染自定义图标（桌面会显示空白默认图标）。
    因此本脚本会先把 app/favicon.ico 复制到用户目录的普通位置
    （%LOCALAPPDATA%\\TaskBoard\\app-icon.ico），快捷方式指向该副本；
    网页端仍由服务从 app/favicon.ico 提供。

需要 pywin32（仅此工具脚本需要）：pip install pywin32
用法：py make_shortcut.py
说明：重复运行时原地更新现有快捷方式（不删除重建），保持桌面图标位置不变。
"""

import ctypes
import os
import shutil
import sys

sys.stdout.reconfigure(encoding="utf-8")

try:
    import win32com.client
except ImportError:
    print("此脚本需要 pywin32，请先安装：pip install pywin32")
    sys.exit(1)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LAUNCHER = os.path.join(ROOT, "launch_board.vbs")
ICON_SRC = os.path.join(ROOT, "app", "favicon.ico")
ICON_DIR = os.path.join(os.environ.get("LOCALAPPDATA",
                                       os.path.expanduser("~")), "TaskBoard")
ICON = os.path.join(ICON_DIR, "app-icon.ico")
DESKTOP = os.path.join(os.path.expanduser("~"), "Desktop")
LNK = os.path.join(DESKTOP, "做不完啊.lnk")


def main():
    if not os.path.isfile(LAUNCHER):
        print("找不到启动器:", LAUNCHER)
        sys.exit(1)
    if not os.path.isfile(ICON_SRC):
        print("找不到图标源文件:", ICON_SRC)
        sys.exit(1)

    os.makedirs(ICON_DIR, exist_ok=True)
    if os.path.isfile(ICON):
        os.remove(ICON)
    shutil.copy2(ICON_SRC, ICON)
    print("图标副本已更新:", ICON)

    wscript = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"),
                           "System32", "wscript.exe")
    ws = win32com.client.Dispatch("WScript.Shell")
    sc = ws.CreateShortcut(LNK)
    sc.TargetPath = wscript
    sc.Arguments = '"%s"' % LAUNCHER
    sc.WorkingDirectory = ROOT
    sc.IconLocation = ICON + ",0"
    sc.Description = "个人开发任务看板 - 双击打开"
    sc.Save()

    check = ws.CreateShortcut(LNK)
    print("快捷方式已更新（原地保存，桌面位置不变）:", LNK)
    print("目标:", check.TargetPath)
    print("参数:", check.Arguments)
    print("工作目录:", check.WorkingDirectory)
    print("图标:", check.IconLocation)

    try:
        ctypes.windll.shell32.SHChangeNotify(0x08000000, 0x0000, None, None)
        print("已发送图标缓存刷新通知 (SHChangeNotify)")
    except Exception as exc:
        print("SHChangeNotify 失败:", exc)


if __name__ == "__main__":
    main()
