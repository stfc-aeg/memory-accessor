import logging
import sys
import json
import time
import math
from odin.adapters.parameter_tree import ParameterTree, ParameterTreeError
import xml.etree.ElementTree as ET
from functools import partial
from dataclasses import dataclass, fields, field, _MISSING_TYPE
from tornado.ioloop import PeriodicCallback
from typing import TypedDict, Callable

from .base.base_controller import BaseController, BaseError
from .base.base_mem_accessor import RegisterAccessor
from RegisterAccessor.adxdma.accessor import AdxdmaAccessor
from RegisterAccessor.xdma.accessor import XDmaAccessor
from RegisterAccessor.RegisterMap import RegisterMap, RegisterMapError, Register, BitField


def _get_bitwise_trailing_zeros(val):
    """Method to get the number of trailing 0s on a binary value.
    Used to calculate how much to shift a masked value to return the specific value regardless of its position"""
    c = 0
    v = (val ^ (val - 1)) >> 1
    while v > 0:
        v >>= 1
        c += 1
    return c


# attribute key consts for the XMl parsing, based on the XML firmware file
NAME_KEY = "id"
FULLNAME_KEY = "absolute_id"
ADDR_KEY = "absolute_offset"
DESC_KEY = "description"
PERM_KEY = "permission"
MASK_KEY = "mask"
SIZE_KEY = "size"


class ControllerError(BaseError):
    """Simple exception class to wrap lower-level exceptions."""

class RegisterParamTree(TypedDict, total=False):
    value: tuple[Callable[[], int], Callable[[int | bytes], None] | None, dict]
    address: tuple[int, None]
    access_policy: str
    fields: dict


class RegisterAccessorController(BaseController):
    """Controller class for RegisterAccessor."""

    accessor_map: dict[str, RegisterAccessor] = {
        "xdma": XDmaAccessor,
        "adxdma": AdxdmaAccessor
    }

    def __init__(self, options: dict[str, str]):

        # get accessor type
        accessorType: type[RegisterAccessor] = self.accessor_map.get(
            options.get("accessor_type", "xdma").lower(), XDmaAccessor)

        # get register access policy settings
        self.access_policy = options.get("access_policy", "static")
        policy_file_name = options.get("access_policy_file")

        self.poll_rate = int(options.get("poll_rate", 1000))

        # get register map
        reg_map_file = options.get("reg_map")
        self.register_map = RegisterMap(reg_map_file, policy_file_name)

        self.polled_registers: list[Register] = []

        # initialise the accessor
        self.accessor: RegisterAccessor = accessorType(**options)

        # initialise the Param Tree
        tree = {}
        tree["control"] = {
            "open": (None, lambda _: self.open_device()),
            "close": (None, lambda _: self.accessor.close()),
            "connected": (lambda: self.accessor.isConnected, None)
        }

        tree['registers'] = self.create_paramTree(self.register_map.map)

        self.param_tree = ParameterTree(tree)

        # calc frequency needed for callback so every desired polling frequency is covered
        if self.polled_registers:
            all_freq = [reg.poll_freq for reg in self.polled_registers]
            poll_freq = math.gcd(*all_freq)
            logging.debug("Polling loop frequency is %d", poll_freq)
            self.background_polling = PeriodicCallback(self.polling_loop, poll_freq)
            self.background_polling.start()

    def initialize(self, adapters):
        self.adapters = adapters
        logging.debug(f"Adapters initialized: {list(adapters.keys())}")
        # Add to param tree if needed post-initialization

    def cleanup(self):
        logging.info("Cleaning up RegisterAccessorController")
        self.background_polling.stop()
        if self.accessor.isConnected:
            self.accessor.close()

    def get(self, path, with_metadata=False):
        try:
            return self.param_tree.get(path, with_metadata)
        except ParameterTreeError as error:
            logging.error(error)
            raise ControllerError(error)

    def set(self, path, data):
        try:
            self.param_tree.set(path, data)
        except ParameterTreeError as error:
            logging.error(error)
            raise ControllerError(error)
    
    def create_paramTree(self, node: dict | Register):
        if isinstance(node, dict):
            return {k: self.create_paramTree(v) for k, v in node.items()}
        elif isinstance(node, Register):
            return self.create_reg_paramTree(node)

    def create_reg_paramTree(self, reg: Register) -> RegisterParamTree:
        """
        Create a Param Tree style dictionary to access a regsiter value, its address, and any
        fields it may have. Uses the Access Policy to ensure the correct read method is used.
        
        :param reg: The Register the tree will communicate with
        :type reg: Register
        :return: A dict object that provides a ParamAccessor style **Value**, as well as other information
        about the Register. It also provides a **Fields** subtree if bitfields are defined for the register.
        :rtype: RegisterParamTree
        """
        read_accessor = self.create_read_access_param(reg)
        tree: RegisterParamTree
        tree = {
            "value": (
                read_accessor,
                None if not reg.write else partial(self.write_register, register=reg),
                {"description": reg.desc}
            ),
            "address": (lambda: reg.addr, None),
            "access_policy": (lambda: reg.policy, None)
        }
        if reg.bitFields:
            tree['fields'] = {
                bit.name: (
                    partial(self.read_field, register=reg, bitField=bit),
                    None if not bit.write else partial(self.write_field, register=reg, bitField=bit),
                    {"description": bit.desc,
                     "min": 0,
                     "max": bit.mask >> _get_bitwise_trailing_zeros(bit.mask)}
                ) for bit in reg.bitFields
            }
        return tree
    
    def create_read_access_param(self, reg: Register):
        """
        Create the GET ParamTree Access method for the provided register. Access can be done in a few ways:
        - Static: only read from the actual register once and saves it. Afterwards, just return the saved value.
        - Polled: The Adapter will read the register in a PeriodicCallback. The Frequency of which can be customised per register
        - Immediate: The adapter will always read the register value directly from the hardware. This should be limited to avoid strain on the system
        """
        policy = reg.policy or self.access_policy
        reg.policy = policy
        frequency = max(reg.poll_freq or self.poll_rate, 100)  # setting a minimum frequency of 100
        
        if policy.lower() in ["immediate", "direct"]:
            logging.debug("Creating Immediate access param for register %s", reg.name)
            return partial(self.immediate_reg_read, register=reg)
        elif policy.lower() in ["static", "once"]:
            return partial(self.static_reg_read, register=reg)
        elif policy.lower() in ["polled", "looped"]:
            logging.debug("Creating Polled access param for register %s, at a frequency of %dms", reg.name, frequency)
            reg.poll_freq = frequency
            self.polled_registers.append(reg)
            return partial(self.static_reg_read, register=reg)
        else:
            raise ControllerError("Access Policy '%s' not recognised for register %s at addr %X", policy, reg.name, reg.addr)

    def static_reg_read(self, register: Register):
        """
        Statically read the Register value. If the value has already been read, return local copy.
        Otherwise, read from the register and save the value locally
        """
        if not register.value and self.accessor.isConnected:  # is the reg bytearray empty? is the accessor open?
            logging.debug("First Read on %s reg %s", register.policy, register.name)
            register.value = self.accessor.read(register.addr, register.size)
        return int.from_bytes(register.value, sys.byteorder)

    def immediate_reg_read(self, register: Register):
        """
        Directly read the register value. This always reads from the actual device, and so should rarely be used in the Param Tree
        """
        if isinstance(register, int):
            reg = self.registers.get(register)
            if reg is None:
                raise ControllerError("Unable to read address %X: Not found in register map", register)
        else:
            reg = register

        if reg.read:
            if self.accessor.isConnected:
                reg.value = self.accessor.read(reg.addr, reg.size)
            return int.from_bytes(reg.value, sys.byteorder)
        else:
            raise ControllerError("Unable to read register %s: Register not readable", reg.name)

    def write_register(self, value: int | bytes, register: Register):
        """
        Write to the register. this will always be a write directly to the hardware, no matter the registers Access Policy
        
        Parameters:
            value: The data to write to the register, as a integer that will become a bytearray


        """
        if register.write and self.accessor.isConnected:
            if type(value) is int:
                byteVal = int.to_bytes(value, register.size, sys.byteorder)
            elif type(value) is bytes:
                byteVal = value
            else:
                raise ControllerError("Invalid Register Value Type: %s", type(value))
            logging.debug("Writing 0x%s to register %s", byteVal.hex().upper(), register.name)
            self.accessor.write(register.addr, byteVal)
            if register.read:  # some registers can be write only.
                register.value = self.accessor.read(register.addr, register.size)
            else:
                register.value = byteVal
        else:
            raise ControllerError("Unable to write to register %s: %s", register.name,
                                  "Not connected" if register.write else "Register not writeable")

    def read_field(self, register: "Register", bitField: BitField) -> int:
        val = int.from_bytes(register.value, sys.byteorder)
        # get shift value
        mask = bitField.mask
        shift = _get_bitwise_trailing_zeros(mask)
        return (val & mask) >> shift  # bitwise AND and then right shift to remove mask offset

    def write_field(self, value: int, register: "Register", bitField: "BitField"):
        mask = bitField.mask
        shift = _get_bitwise_trailing_zeros(mask)
        start_val = int.from_bytes(register.value, sys.byteorder) & (~mask)  # get the reg value, but 0 out the bits this field relates to
        write_val = start_val | ((value << shift) & mask)  # shift the write val based on the mask, to position the bits correctly

        self.write_register(write_val, register)

    def open_device(self):
        self.accessor.open()

    def polling_loop(self):
        if self.accessor.isConnected:
            timestamp = int(time.time() * 1000)  # milliseconds since epoch
            for reg in self.polled_registers:
                if reg.timeLastRead + reg.poll_freq < timestamp:
                    reg.value = self.accessor.read(reg.addr, reg.size)
                    reg.timeLastRead = timestamp

