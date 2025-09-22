from memoryaccessor.base.base_mem_accessor import MemoryAccessor, MemoryAccessorException
from memoryaccessor.adxdma.AdxdmaLib import AdxdmaLib, COMPLETION
from ctypes import byref
from ctypes import c_int, c_uint32

import logging
import math


class AdxdmaException(MemoryAccessorException):
    """Exception class to handle error codes from the ADXDMA lib"""
    message_lookup = {
            AdxdmaLib.SUCCESS:                "success",
            AdxdmaLib.STARTED:                "Asynchronous operation started without error",
            AdxdmaLib.TRUNCATED:              "Operation transferred some, but not all of the requested bytes",
            AdxdmaLib.INTERNAL_ERROR:         "An error in the API logic was detected",
            AdxdmaLib.UNEXPECTED_ERROR:       "An unexpected error caused the operation to fail",
            AdxdmaLib.BAD_DRIVER:             "The driver might not be correctly installed",
            AdxdmaLib.NO_MEMORY:              "Couldn't allocate memory required to complete operation",
            AdxdmaLib.ACCESS_DENIED:          "The calling process does not have permission to perform the operation",
            AdxdmaLib.DEVICE_NOT_FOUND:       "Failed to open the device with the specified index",
            AdxdmaLib.CANCELLED:              "The operation was aborted due to software-requested cancellation",
            AdxdmaLib.HARDWARE_ERROR:         "The operation failed due to an error in the hardware",
            AdxdmaLib.HARDWARE_RESET:         "The operation was aborted the hardware being reset",
            AdxdmaLib.HARDWARE_POWER_DOWN:    "The operation was aborted due to a hardware power-down event",
            AdxdmaLib.INVALID_PARAMETER:      "The primary parameter to the function was invalid",
            AdxdmaLib.INVALID_FLAG:           "A flag was invalid or not recognized",
            AdxdmaLib.INVALID_HANDLE:         "The device handle was invalid",
            AdxdmaLib.INVALID_INDEX:          "The index parameter was invalid",
            AdxdmaLib.NULL_POINTER:           "A NULL pointer was passed where non-NULL was required",
            AdxdmaLib.NOT_SUPPORTED:          "The hardware or the ADXDMA driver does not support the requested operation",
            AdxdmaLib.WRONG_HANDLE_TYPE:      "The wrong kind of handle was supplied for an API function",
            AdxdmaLib.TIMEOUT_EXPIRED:        "The user-supplied timeout value was exceeded",
            AdxdmaLib.INVALID_SENSITIVITY:    "At least one bit in the sensitivity parameter refers to a non-existent User Interrupt",
            AdxdmaLib.INVALID_MAPPING:        "The virtual base address to be unmapped from the process' address space was not recognized",
            AdxdmaLib.INVALID_WORD_SIZE:      "The word size specified was not valid",
            AdxdmaLib.INVALID_REGION:         "The requested region was partially or completely out of bounds",
            AdxdmaLib.REGION_OS_LIMIT:        "The requested region exceeded a system-imposed limit",
            AdxdmaLib.LOCK_LIMIT:             "The limit on the number of locked buffers has been reached",
            AdxdmaLib.INVALID_BUFFER_HANDLE:  "An invalid locked buffer handle was supplied",
            AdxdmaLib.NOT_BUFFER_OWNER:       "Attempt to unlock a buffer owned by a different device handle",
            AdxdmaLib.DMAQ_NOT_IDLE:          "Attempt to change DMA queue configuration when it was not idle",
            AdxdmaLib.INVALID_DMAQ_MODE:      "Invalid DMA Queue mode requested",
            AdxdmaLib.DMAQ_OUTSTANDING_LIMIT: "Maximum outstanding DMA transfer count reached",
            AdxdmaLib.INVALID_DMA_ALIGNMENT:  "Invalid address alignment, or length is not an integer multiple of length granularity",
            AdxdmaLib.EXISTING_MAPPING:       "At least one Window mapping exists, preventing safe reset",
            # AdxdmaLib.ALREADY_CANCELLING:   "Currently not used",
            AdxdmaLib.DEVICE_BUSY:            "Attempting to perform an operation while there is already one in progress",
            AdxdmaLib.DEVICE_IDLE:            "Attempting to join a non-existent operation",
            AdxdmaLib.C2H_TLAST_ASSERTED:     "At least one DMA descriptor was closed early by C2H user logic asserting TLAST"
    }

    def __init__(self, error_code: int) -> None:
        message = self.message_lookup[error_code]
        super().__init__(message)


class AdxdmaAccessor(MemoryAccessor):
    """Accessor class using Adxdma to read/write register values from an Alphadata Card"""

    def __init__(self, **kwargs):
        super().__init__()
        self.lib = AdxdmaLib("adxdma")

        self.device_index = kwargs.get("device_index", 0)
        self.window_index = kwargs.get("window_index", 2)

        self.deviceHandle = c_int()
        self.windowHandle = c_int()

    def open(self) -> None:

        self._testStatus(self.lib.ADXDMA_Open(self.device_index, False, byref(self.deviceHandle)))
        self._testStatus(self.lib.ADXDMA_OpenWindow(self.deviceHandle, self.device_index,
                                                    False, self.window_index, byref(self.windowHandle)))
        self._isConnected = True

    def close(self) -> None:
        self._testStatus(self.lib.ADXDMA_CloseWindow(self.windowHandle))
        self._isConnected = False
        self._testStatus(self.lib.ADXDMA_Close(self.deviceHandle))

    def __del__(self):
        if self.isConnected:
            self.close()

    def read(self, addr: int, size: int) -> bytearray:
        if not self.isConnected:
            raise AdxdmaException(self.lib.DEVICE_NOT_FOUND)
        complete = COMPLETION()
        num_words = math.ceil(size / 4)
        buf = bytearray(4 * num_words)
        # we are insisting on 4 byte word reads, but that wont effect the returned bytearray
        point = (c_uint32 * num_words).from_buffer(buf)

        status = self.lib.ADXDMA_ReadWindow(self.windowHandle, 0, 4, addr, size, point, byref(complete))
        self._testStatus(status, complete)

        return buf[:size]

    def write(self, addr: int, data: bytearray) -> None:
        if not self.isConnected:
            raise AdxdmaException(self.lib.DEVICE_NOT_FOUND)
        complete = COMPLETION()
        num_words = math.ceil(len(data) / 4)

        point = (c_uint32 * num_words).from_buffer(data)
        status = self.lib.ADXDMA_WriteWindow(self.windowHandle, 0, 4, addr, len(data), point, byref(complete))
        self._testStatus(status, complete)

    def _testStatus(self, status, complete: COMPLETION | None = None):
        if status != self.lib.SUCCESS:
            if complete and status == self.lib.TRUNCATED:
                logging.error("{} bytes transferred in read/write call, which was less than expected.".format(complete.Transferred))
                raise AdxdmaException(complete.Reason)
            else:
                raise AdxdmaException(status)
        else:
            return True
