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
        self.device_size = int(kwargs.get("device_size", 1048576))  # TODO: find better means of setting default size. mmap docs say you should be able to set this to 0, but that causes an error
        self.memory = None
        self.dev_file = None

    def open(self) -> None:
        logging.debug("Opening XDMA Device")
        dev_name = "xdma{}_user".format(self.device_index)
        # other devices may need to be opened? such as the interrupts for DMA
        dev_path = Path("/dev")

        fullpath = dev_path.joinpath(dev_name)

        if dev_path.is_dir() and fullpath.is_char_device():  # the XDMA dev files are character devices, not standard files.
            self.dev_file = os.open(fullpath, os.O_RDWR)
            self.memory = mmap.mmap(fileno=self.dev_file, length=self.device_size)
            self._isConnected = True
        else:
            raise XdmaException("XDMA device {} not found. Check that xdma is installed and the device is available.".format(dev_name))

    def close(self):
        logging.debug("Closing XDMA Device")
        if self.isConnected:
            self.memory.close()
            os.close(self.dev_file)
            self._isConnected = False
    
    def read(self, addr: int, size: int) -> bytearray:
        """
        Read from the memory map, using Seek Read methods rather than slicing,
        as these provide additional error handling

        Parameters:
            addr: the address to read from
            size: the number of bytes to read
        
        Returns:
            a bytearray of length <size>, containing the read data
        """
        if not self.isConnected:
            raise XdmaException("DEVICE NOT CONNECTED")
        self.memory.seek(addr)
        read_reg = self.memory.read(size)
        self.memory.seek(0)
        return bytearray(read_reg)
    
    def write(self, addr: int, data: bytearray) -> None:
        """
        Write to the memory map, using the Seek and Read methods rather than slicing,
        as these can provide additional error handling

        Parameters:
            addr: the address to write to
            data: a bytearray, or other byte-like-object, containing the data to write
        """
        if not self.isConnected:
            raise XdmaException("DEVICE NOT CONNECTED")
        self.memory.seek(addr)
        self.memory.write(data)
        self.memory.seek(0)
