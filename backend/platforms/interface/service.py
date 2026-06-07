# interfaces/service.py
from abc import ABC, abstractmethod

class PlatformService(ABC):
    @abstractmethod
    def shortcut_handler(self, shortcut, handler):
        """快捷键的统一接口"""
        pass