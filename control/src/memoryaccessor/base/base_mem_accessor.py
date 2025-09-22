from abc import ABC, abstractmethod


class MemoryAccessorException(ABC, Exception):
    pass


class MemoryAccessor(ABC):

    @property
    def isConnected(self):
        return self._isConnected

    @abstractmethod
    def __init__(self, **kwargs):
        """Is the accessor initialised and connected to the device its accessing"""
        self._isConnected = False
        pass

    @abstractmethod
    def open(self) -> None:
        pass

    @abstractmethod
    def close(self) -> None:
        pass

    @abstractmethod
    def read(self, addr: int, size: int) -> bytearray:
        pass

    @abstractmethod
    def write(self, addr: int, data: bytearray) -> None:
        pass
