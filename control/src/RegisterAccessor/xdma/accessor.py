from RegisterAccessor.base.base_mem_accessor import RegisterAccessor, RegisterAccessorException

import mmap
import os
from pathlib import Path
import logging


class XdmaException(RegisterAccessorException):
    pass


class XDmaAccessor(RegisterAccessor):

    def __init__(self, **kwargs):
        super().__init__()
        self.device_index = kwargs.get("device_index", 0)
        self.device_size = int(kwargs.get("device_size", 1048576))
        self.memory = None
        self.dev_file = None

    def open(self) -> None:
        logging.debug("Opening XDMA Device")
        dev_name = "xdma{}_user".format(self.device_index)
        # other devices may need to be opened? such as the interrupts for DMA
        dev_path = Path("/dev")

        fullpath = dev_path.joinpath(dev_name)

        if dev_path.is_dir() and fullpath.is_char_device():  # apparently the XDMA dev files are character devices?
            self.dev_file = os.open(fullpath, os.O_RDWR)
            self.memory = mmap.mmap(self.dev_file, self.device_size)
            self._isConnected = True
        else:
            raise XdmaException("XDMA device {} not found. Check that xdma is installled and the device is available.".format(dev_name))

    def close(self):
        logging.debug("Closing XDMA Device")
        if self.isConnected:
            self.memory.close()
            os.close(self.dev_file)
    
    def read(self, addr: int, size: int) -> bytearray:
        if not self.isConnected:
            raise XdmaException("DEVICE NOT CONNECTED")
        read_reg = self.memory[addr: addr + size]  # this has no checking to ensure addr is legal?
        return bytearray(read_reg)
    
    def write(self, addr: int, data: bytearray) -> None:
        if not self.isConnected:
            raise XdmaException("DEVICE NOT CONNECTED")
        length = len(data)
        self.memory[addr: addr + length] = data
