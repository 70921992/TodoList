#!/usr/bin/env python3
"""
系统托盘管理
"""

import sys
import os
import logging
import backend.globals

class SystemTrayManager:
    """系统托盘管理"""

    def __init__(self, service):
        self.service = service

    def on_open(self, icon=None, item=None):
        """显示已隐藏的窗口"""
        if backend.globals.window:
            backend.globals.window.show()

    def on_exit(self, icon, item):
        """点击系统托盘菜单的彻底退出"""
        print("开始从托盘菜单执行彻底退出流程...")

        # 隐藏并停止托盘
        try:
            self.service.start_desktop_task_reminder(False)
            if backend.globals.window:
                backend.globals.window.destroy()
            logging.shutdown()
            icon.visible = False
            icon.stop()
            print("已向 Ubuntu 系统请求隐藏并关闭托盘")
            pid = os.getpid()
            print(f"准备结束当前进程树，主进程PID: {pid}")

            self.service.force_kill_process_tree(pid)
            # 最后使用 os._exit 作为终极保障，确保程序退出
            os._exit(0)
        except Exception as e:
            print(f"icon stop error: {e}")

    def start_app(self, ssl_enable):
        try:
            from backend import start
            from backend.utils.logger import app_logger

            from PIL import Image
            from pystray import Icon, Menu, MenuItem
            from backend.utils import utils

            # 启动任务提醒服务
            print("启动任务提醒服务...")
            self.service.start_desktop_task_reminder(True, self.on_open)

            # 创建系统托盘，但不在主线程阻塞运行
            image = Image.open(utils.get_app_icon())
            menu = Menu(MenuItem('打开应用', self.on_open, default=True), MenuItem('彻底退出', self.on_exit))
            icon = Icon('TodoList', image, menu=menu, title='TodoList')
            # 在后台线程启动托盘
            icon.run_detached()

            # 主线程运行 WebView（阻塞直到窗口被 destroy）
            start.start_app(False, ssl_enable, self.service.start_keyboard)
            print("77777: WebView 窗口已关闭（通常是用户点击了窗口的 [X]）")

            # 如果主线程运行到这里，说明主窗口被关闭了，我们需要同步将托盘和进程连带一起关闭
            print("正在清理托盘并彻底退出程序...")
            self.service.start_desktop_task_reminder(False)
            if backend.globals.window:
                backend.globals.window.destroy()
            logging.shutdown()

            icon.visible = False
            icon.stop()

            self.service.icon_exit()

            print("8888: 进程收尾，彻底退出。")
            os._exit(0)

        except ImportError as e:
            print(f"导入错误: {e}")
            print("请检查Python环境是否正确安装了依赖：pip install pywebview")
            sys.exit(1)
        except Exception as e:
            print(f"启动应用失败: {e}")
            sys.exit(1)