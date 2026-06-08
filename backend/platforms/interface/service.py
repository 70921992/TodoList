# interfaces/service.py
from abc import ABC, abstractmethod

class PlatformService(ABC):
    @abstractmethod
    def shortcut_handler(self, shortcut, handler):
        """快捷键的统一接口"""
        pass

    @abstractmethod
    def force_kill_process_tree(self, pid):
        """强制结束当前进程及其所有子进程的统一接口"""
        pass