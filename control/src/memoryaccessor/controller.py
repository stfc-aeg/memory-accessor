import logging
import sys
from odin.adapters.parameter_tree import ParameterTree, ParameterTreeError
import xml.etree.ElementTree as ET
from functools import partial
from dataclasses import dataclass, fields, field, _MISSING_TYPE


from .base.base_controller import BaseController, BaseError
from .base.base_mem_accessor import MemoryAccessor
from memoryaccessor.adxdma.accessor import AdxdmaAccessor
from memoryaccessor.xdma.accessor import XDmaAccessor


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
    value: bytearray = field(default_factory=bytearray)

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
ADDR_KEY = "absolute_offset"
DESC_KEY = "description"
PERM_KEY = "permission"
MASK_KEY = "mask"
SIZE_KEY = "size"


class ControllerError(BaseError):
    """Simple exception class to wrap lower-level exceptions."""


class MemoryAccessorController(BaseController):
    """Controller class for MEMORYACCESSOR."""

    accessor_map: dict[str, MemoryAccessor] = {
        "xdma": XDmaAccessor,
        "adxdma": AdxdmaAccessor
    }

    def __init__(self, options):
        self.options = options
        accessorType: type[MemoryAccessor] = self.accessor_map.get(options.get("accessor_type").lower(), XDmaAccessor)
        reg_map_file = options.get("reg_map")
        reg_tree = ET.parse(reg_map_file)
        reg_tree_root = reg_tree.getroot()
        if "byte_size" in reg_tree_root and "device_size" not in options:
            options['device_size'] = reg_tree_root.attrib['byte_size']

        self.registers: dict[int, "Register"] = {}  # dictionary of registers, key will be reg addr
        
        self.accessor: MemoryAccessor = accessorType(**options)

        tree = {}
        tree["control"] = {
            "open": (None, lambda _: self.accessor.open()),
            "close": (None, lambda _: self.accessor.close()),
            "connected": (lambda: self.accessor.isConnected, None)
        }

        tree['registers'] = {}

        for root_child in reg_tree_root:
            self.registers.update(self.parseRegisterElement(root_child, tree['registers']))

        self.param_tree = ParameterTree(tree)

    def initialize(self, adapters):
        self.adapters = adapters
        # logging.debug(f"Adapters initialized: {list(adapters.keys())}")
        # Add to param tree if needed post-initialization

    def cleanup(self):
        logging.info("Cleaning up MemoryaccessorController")

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
                               field_dict)
                reg_dict[reg.addr] = reg

                # PARAM TREE STUFF HERE. TODO: DONT ALWAYS READ DIRECT FROM DEVICE IN TREE
                tree[reg.name] = self.create_reg_paramTree(reg)
            else:
                tree[info.get(NAME_KEY)] = {}
                for reg in element:
                    reg_dict.update(self.parseRegisterElement(reg, tree[info.get(NAME_KEY)]))
        else:
            reg = Register(info.get(NAME_KEY), info.get(DESC_KEY), info.get(PERM_KEY),
                           int(info.get(ADDR_KEY), 16),
                           int(info.get(SIZE_KEY, 1)) * 4)  # size is in number of 32 bit words
            reg_dict[reg.addr] = reg

            # PARAM TREE STUFF HERE
            tree[reg.name] = self.create_reg_paramTree(reg)

        return reg_dict
    
    def create_reg_paramTree(self, reg: Register):
        tree = {
            "value": (
                partial(self.immediate_reg_read, register=reg),
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
                    {"description": bit.desc}
                ) for (name, bit) in reg.bitFields.items()
            }
        return tree

    def immediate_reg_read(self, register: Register | int):
        if isinstance(register, int):
            reg = self.registers.get(register)
            if reg is None:
                raise ControllerError("Unable to read Address {:X}: Not found in Register map".format(register))
        else:
            reg = register

        if reg.read:
            if self.accessor.isConnected:
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
            reg.value = value
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
