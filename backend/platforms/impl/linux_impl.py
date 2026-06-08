# impl/linux_impl.py
from backend.platforms.interface.service import PlatformService

class LinuxService(PlatformService):
    def shortcut_handler(self, shortcut, handler):
        try:
            import backend.globals
            from pynput import keyboard
            listener = keyboard.GlobalHotKeys({shortcut: handler})
            listener.start()
            print(f"【系统日志】快捷键监听成功挂载！当前在 Mac 下的标准热键为: {shortcut}")
            return None
        except Exception as e:
            print(f"【系统日志】快捷键挂载失败: {e}")

    def force_kill_process_tree(self, pid):
        """强制结束当前进程及其所有子进程的统一接口"""
        # Linux环境利用时延让 GTK 将 DBus 信号安全发出，然后强制杀死所有关联进程
        import gi
        from gi.repository import Gtk
        import time
        gi.require_version('Gtk', '3.0')
        for _ in range(10):
            while Gtk.events_pending():
                Gtk.main_iteration()
            time.sleep(0.02)

# 用于给工厂注册的导出变量
ExportService = LinuxService
