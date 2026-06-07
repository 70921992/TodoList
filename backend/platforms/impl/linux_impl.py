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

# 用于给工厂注册的导出变量
ExportService = LinuxService
