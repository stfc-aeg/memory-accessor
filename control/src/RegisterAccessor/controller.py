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

from .base.base_controller import BaseController, BaseError
from .base.base_mem_accessor import RegisterAccessor
from RegisterAccessor.adxdma.accessor import AdxdmaAccessor
from RegisterAccessor.xdma.accessor import XDmaAccessor


@dataclass
class Memory:
    """Base Data Class, for inheritance only"""
    name: str
    desc: str = "No Description Provided"
    permission: str = "r"

    def __post_init__(self):
        for classField in fields(self):
            if not isinstance(classField.default, _MISSING_TYPE) and getattr(self, classField.name) is None:
                setattr(self, classField.name, classField.default)
        self.read = "r" in self.permission.lower()
        self.write = "w" in self.permission.lower()


@dataclass
class Register(Memory):
    """Register Data Class, stores the addr, name, size, read/write permissions, description and any bitfields"""
    addr: int = 0  # absolute addr offset
    size: int = 4  # number bytes, default 32 bit reg
    bitFields: dict | None = None
    fullPath: str = ""
    timeLastRead: int = 0  # only used for Polled registers
    value: bytearray = field(default_factory=bytearray)

    def __post_init__(self):
        super().__post_init__()
        split_path = self.fullPath.split(".")[1:]
        if split_path:
            self.fullPath = "/".join(split_path)  # make fullPath appear like Param Path, without root name part
        else:
            self.fullPath = self.name

    def __repr__(self) -> str:
        fields_str = "\n\t\t".join([str(value) for value in self.bitFields.values()]) if self.bitFields else "None"
        return ("\n{name}\n{desc}\n\tAddress: {addr:08X}\n\tSize: {size}\n\tPerms: {perms}\n\tFields:\n\t\t{fields}"
                .format(name=self.name, desc=self.desc, addr=self.addr, size=self.size, perms=self.permission,
                        fields=fields_str))


@dataclass
class BitField(Memory):
    """Data Class for the bitfields within a Register"""
    mask: int = 0  # a mask for the bits the field relate to


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


class RegisterAccessorController(BaseController):
    """Controller class for RegisterAccessor."""

    accessor_map: dict[str, RegisterAccessor] = {
        "xdma": XDmaAccessor,
        "adxdma": AdxdmaAccessor
    }

    def __init__(self, options):

        # get accessor type
        accessorType: type[RegisterAccessor] = self.accessor_map.get(
            options.get("accessor_type").lower(), XDmaAccessor)

        # get register access policy settings
        self.access_policy = options.get("access_policy", "static")
        policy_file_name = options.get("access_policy_file")
        self.access_policy_overwrites = {}
        if policy_file_name:
            with open(policy_file_name) as f:
                self.access_policy_overwrites = json.load(f)
        self.read_on_open = options.get("read_on_open", "").lower() in ["true", "1", "yes"]
        self.poll_rate = int(options.get("poll_rate", 1000))

        # get register map
        reg_map_file = options.get("reg_map")
        reg_tree = ET.parse(reg_map_file)
        reg_tree_root = reg_tree.getroot()

        # get size of memory being mapped (needed if using XDMA) from reg map
        if "byte_size" in reg_tree_root and "device_size" not in options:
            options['device_size'] = reg_tree_root.attrib['byte_size']

        self.registers: dict[int, Register] = {}  # dictionary of registers, key will be reg addr
        self.polled_registers: dict[int, int] = {}

        # initialise the accessor
        self.accessor: RegisterAccessor = accessorType(**options)

        # initialise the Param Tree
        tree = {}
        tree["control"] = {
            "open": (None, lambda _: self.open_device()),
            "close": (None, lambda _: self.accessor.close()),
            "connected": (lambda: self.accessor.isConnected, None)
        }

        tree['registers'] = {}

        # create register Param Tree
        for root_child in reg_tree_root:
            self.registers.update(self.parseRegisterElement(root_child, tree['registers']))

        self.param_tree = ParameterTree(tree)

        # calc frequency needed for callback so every desired polling frequency is covered
        all_freq = list(self.polled_registers.values())
        logging.debug(all_freq)
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

    def parseRegisterElement(self, element: ET.Element, tree: dict):
        reg_dict = {}
        info = element.attrib

        if len(element):
            # element has children. its either a register with bitFields, or a register space
            first_child = element[0].attrib
            if MASK_KEY in first_child and "address" not in first_child and first_child.get(ADDR_KEY, "0") == info.get(ADDR_KEY, "0"):
                # children are bitFields of the Register
                field_dict: dict[str, "BitField"] = {}
                for bitField in element:
                    bitField_info = bitField.attrib
                    bit = BitField(bitField_info[NAME_KEY],
                                   bitField_info.get(DESC_KEY),
                                   bitField_info.get(PERM_KEY, "r"),
                                   int(bitField_info[MASK_KEY], 16))
                    field_dict[bitField_info[NAME_KEY]] = bit
                reg = Register(info.get(NAME_KEY), info.get(DESC_KEY), info.get(PERM_KEY),
                               int(info.get(ADDR_KEY), 16),
                               int(info.get(SIZE_KEY, 1)) * 4,  # size is in number of 32 bit words
                               field_dict,
                               fullPath=info.get(FULLNAME_KEY))
                reg_dict[reg.addr] = reg

                tree[reg.name] = self.create_reg_paramTree(reg)
            else:
                tree[info.get(NAME_KEY)] = {}
                for reg in element:
                    reg_dict.update(self.parseRegisterElement(reg, tree[info.get(NAME_KEY)]))
        else:
            reg = Register(info.get(NAME_KEY), info.get(DESC_KEY), info.get(PERM_KEY),
                           int(info.get(ADDR_KEY), 16),
                           int(info.get(SIZE_KEY, 1)) * 4,
                           fullPath=info.get(FULLNAME_KEY))  # size is in number of 32 bit words
            reg_dict[reg.addr] = reg

            tree[reg.name] = self.create_reg_paramTree(reg)

        return reg_dict
    
    def create_reg_paramTree(self, reg: Register):
        reg_policy = {}
        if reg.fullPath in self.access_policy_overwrites or reg.name in self.access_policy_overwrites:
            # if the register is in the overwrites json, check if it specifies an addr
            reg_policy = self.access_policy_overwrites.get(reg.name) or self.access_policy_overwrites.get(reg.fullPath)

        read_accessor = self.create_read_access_param(reg, **reg_policy)

        tree = {
            "value": (
                read_accessor,
                None if not reg.write else partial(self.write_register, register=reg),
                {"description": reg.desc}
            ),
            "address": (reg.addr, None)
        }
        if reg.bitFields:
            tree['fields'] = {
                name: (
                    partial(self.read_field, register=reg, field=bit),
                    None if not bit.write else partial(self.write_field, register=reg, field=bit),
                    {"description": bit.desc,
                     "min": 0,
                     "max": bit.mask >> _get_bitwise_trailing_zeros(bit.mask)}
                ) for (name, bit) in reg.bitFields.items()
            }
        return tree
    
    def create_read_access_param(self, reg: Register, **kwargs):
        """
        Create the GET ParamTree Access method for the provided register. Access can be done in a few ways:
        - Static: only read from the actual register once and saves it. Afterwards, just return the saved value.
        - Polled: The Adapter will read the register in a PeriodicCallback. The Frequency of which can be customised per register
        - Immediate: The adapter will always read the register value directly from the hardware. This should be limited to avoid strain on the system
        """
        policy = kwargs.get("policy", self.access_policy)
        frequency = kwargs.get("frequency", self.poll_rate)
        
        if policy.lower() in ["immediate", "direct"]:
            logging.debug("Creating Immediate access param for register %s", reg.name)
            return partial(self.immediate_reg_read, register=reg)
        elif policy.lower() in ["static", "once"]:
            return partial(self.static_reg_read, register=reg)
        elif policy.lower() in ["polled", "looped"]:
            logging.debug("Creating Polled access param for register %s, at a frequency of %dms", reg.name, frequency)
            self.polled_registers[reg.addr] = frequency
            return (lambda: int.from_bytes(reg.value, sys.byteorder))
        else:
            raise ControllerError("Access Policy '%s' not recognised for register %s", policy, reg.fullPath)

    def static_reg_read(self, register: Register):
        """
        Statically read the Register value. If the value has already been read, return local copy.
        Otherwise, read from the register and save the value locally
        """
        if not register.value and self.accessor.isConnected:  # is the reg bytearray empty? is the accessor open?
            logging.debug("First Read on static reg %s", register.name)
            register.value = self.accessor.read(register.addr, register.size)
        return int.from_bytes(register.value, sys.byteorder)

    def immediate_reg_read(self, register: Register | int):
        """
        Directly read the register value. This always reads from the actual device, and so should rarely be used in the Param Tree
        """
        if isinstance(register, int):
            reg = self.registers.get(register)
            if reg is None:
                raise ControllerError("Unable to read Address {:X}: Not found in Register map".format(register))
        else:
            reg = register

        if reg.read:
            if self.accessor.isConnected:
                logging.warning("Directly accessing Register %s at addr %s from the Parameter Tree.", reg.name, reg.addr)
                reg.value = self.accessor.read(reg.addr, reg.size)
            return int.from_bytes(reg.value, sys.byteorder)
        else:
            raise ControllerError("Unable to read Register {}: Register not readable".format(reg.name))

    def write_register(self, value: bytearray, register: Register | int):
        if isinstance(register, int):
            reg = self.registers.get(register)
            if reg is None:
                raise ControllerError("Unable to read Address {:X}: Not found in Register map".format(register))
        else:
            reg = register

        if reg.write and self.accessor.isConnected:
            self.accessor.write(reg.addr, value)
            if reg.read:  # some registers can be write only.
                reg.value = self.accessor.read(reg.addr, reg.size)
        else:
            raise ControllerError(("Unable to write to Register {}: {}"
                                   .format(register.name,
                                           "Not Connected" if register.write else "Register not writeable")))

    def read_field(self, register: "Register", field: "BitField") -> int:
        val = int.from_bytes(register.value, sys.byteorder)
        # get shift value
        mask = field.mask
        shift = _get_bitwise_trailing_zeros(mask)
        return (val & mask) >> shift  # bitwise AND and then right shift to remove mask offset

    def write_field(self, value, register: "Register", field: "BitField"):
        mask = field.mask
        shift = _get_bitwise_trailing_zeros(mask)
        start_val = int.from_bytes(register.value, sys.byteorder) & (~mask)  # get the reg value, but 0 out the bits this field relates to
        write_val = start_val & ((value << shift) & mask)  # AND the shifted write_val to the starting reg value

        self.write_register(write_val)

    def open_device(self):
        self.accessor.open()
        if self.accessor.isConnected and self.read_on_open:
            logging.debug("READ ON OPEN. Reading all register values")
            for regAddr, reg in self.registers.items():
                val = self.accessor.read(regAddr, reg.size)
                reg.value = val

    def polling_loop(self):
        if self.accessor.isConnected:
            timestamp = int(time.time() * 1000)  # milliseconds since epoch
            for addr, freq in self.polled_registers.items():
                reg = self.registers[addr]
                if reg.timeLastRead + freq < timestamp:
                    logging.debug("POLLING LOOP READING %s at freq %dms", reg.name, freq)
                    reg.value = self.accessor.read(reg.addr, reg.size)
                    reg.timeLastRead = timestamp

