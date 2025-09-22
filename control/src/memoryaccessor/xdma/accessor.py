from memoryaccessor.base.base_mem_accessor import MemoryAccessor, MemoryAccessorException

import mmap
import os
from pathlib import Path


class XdmaException(MemoryAccessorException):
    pass


class XDmaAccessor(MemoryAccessor):

    def __init__(self, **kwargs):
        super().__init__()
        self.device_index = kwargs.get("device_index", 0)
        self.memory = None
        self.dev_file = None

    def open(self) -> None:
        dev_name = "xdma{}_user".format(self.device_index)
        # other devices may need to be opened? such as the interrupts for DMA
        dev_path = Path("/dev")

        fullpath = dev_path.joinpath(dev_name)

        if dev_path.is_dir() and fullpath.is_file():
            self.dev_file = os.open(fullpath)
            self.memory = mmap.mmap(self.dev_file, 0)
            self._isConnected = True
        else:
            raise XdmaException("XDMA device {} not found. Check that xdma is installled and the device is available.".format(dev_name))

    def close(self):
        if self.isConnected:
            self.memory.close()
            os.close(self.dev_file)
    
    def read(self, addr: int, size: int) -> bytearray:
        
        read_reg = self.memory[addr: addr + size]  # this has no checking to ensure addr is legal?
        return bytearray(read_reg)
    
    def write(self, addr: int, data: bytearray) -> None:
        length = len(data)
        self.memory[addr: addr + length] = data
