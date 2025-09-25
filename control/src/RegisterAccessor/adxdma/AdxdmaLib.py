from ctypes import CDLL, pointer, POINTER, Structure
from ctypes import c_uint, c_int, c_uint8, c_uint32, c_uint64, c_bool, c_size_t, c_void_p
from ctypes.util import find_library
from RegisterAccessor.base.base_mem_accessor import RegisterAccessorException


class COMPLETION(Structure):
    """Struct for ADXDMA read/write methods"""
    _fields_ = [("Transferred", c_size_t),
                ("Reason", c_int)]
    

class AdxdmaLib(CDLL):

    SUCCESS                = 0
    STARTED                = 0x1
    TRUNCATED              = 0x2
    INTERNAL_ERROR         = 0x100
    UNEXPECTED_ERROR       = 0x101
    BAD_DRIVER             = 0x102
    NO_MEMORY              = 0x103
    ACCESS_DENIED          = 0x104
    DEVICE_NOT_FOUND       = 0x105
    CANCELLED              = 0x106
    HARDWARE_ERROR         = 0x107
    HARDWARE_RESET         = 0x108
    HARDWARE_POWER_DOWN    = 0x109
    INVALID_PARAMETER      = 0x10A
    INVALID_FLAG           = 0x10B
    INVALID_HANDLE         = 0x10C
    INVALID_INDEX          = 0x10D
    NULL_POINTER           = 0x10E
    NOT_SUPPORTED          = 0x10F
    WRONG_HANDLE_TYPE      = 0x110
    TIMEOUT_EXPIRED        = 0x111
    INVALID_SENSITIVITY    = 0x112
    INVALID_MAPPING        = 0x113
    INVALID_WORD_SIZE      = 0x114
    INVALID_REGION         = 0x115
    REGION_OS_LIMIT        = 0x116
    LOCK_LIMIT             = 0x117
    INVALID_BUFFER_HANDLE  = 0x118
    NOT_BUFFER_OWNER       = 0x119
    DMAQ_NOT_IDLE          = 0x11A
    INVALID_DMAQ_MODE      = 0x11B
    DMAQ_OUTSTANDING_LIMIT = 0x11C
    INVALID_DMA_ALIGNMENT  = 0x11D
    EXISTING_MAPPING       = 0x11E
    ALREADY_CANCELLING     = 0x11F
    DEVICE_BUSY            = 0x120
    DEVICE_IDLE            = 0x121
    C2H_TLAST_ASSERTED     = 0x122

    def __init__(self, name: str) -> None:
        
        libName = find_library(name)
        if not libName:
            raise RegisterAccessorException("Library for {} not found".format(name))
        try:
            super().__init__(libName)
        except (FileNotFoundError, PermissionError):
            # Library not found
            raise RegisterAccessorException("Library for {} not found or is otherwise inaccessible".format(name))

        #open, open window, read window, write window, close window, close

        self.ADXDMA_Open.argtypes = [c_uint, c_bool, POINTER(c_int)]
        self.ADXDMA_OpenWindow.argtypes = [c_int, c_uint, c_bool, c_uint, POINTER(c_int)]
        self.ADXDMA_CloseWindow.argtypes = [c_int]
        self.ADXDMA_Close.argtypes = [c_int]
        self.ADXDMA_ReadWindow.argtypes = [c_int, c_uint32, c_uint8, c_uint64, c_size_t, c_void_p, POINTER(COMPLETION)]
        self.ADXDMA_WriteWindow.argtypes = [c_int, c_uint32, c_uint8, c_uint64, c_size_t, c_void_p, POINTER(COMPLETION)]
