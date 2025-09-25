import xml.etree.ElementTree as ET
from dataclasses import dataclass, fields, field, _MISSING_TYPE
from functools import partial
from RegisterAccessor.base.base_mem_accessor import RegisterAccessor

from odin.adapters.parameter_tree import ParameterTree, ParameterTreeError
import sys

# Device class to act as intermediary for Accessor class (adxdma/xdma etc) and adapter
# accepts a register map XML file, provides each register as a parameter for adapter

# attribute key consts for the XMl parsing, based on the XML firmware file
NAME_KEY = "id"
ADDR_KEY = "absolute_offset"
DESC_KEY = "description"
PERM_KEY = "permission"
MASK_KEY = "mask"
SIZE_KEY = "size"


class Device():
    """Device class to act as intermediary between Accessor class (adxdma/xdma etc) and adapter.
    Accepts a register map XML file, provides each register as a parameter for the adapter"""

    def __init__(self, register_file_path, AccessorType, **kwargs) -> None:

        reg_tree = ET.parse(register_file_path)
        xml_root = reg_tree.getroot()

        if "byte_size" in xml_root.attrib and "device_size" not in kwargs:
            kwargs["device_size"] = xml_root.attrib["byte_size"]

        self.accessor: "RegisterAccessor" = AccessorType(**kwargs)

        self.tree = {}
        self.tree["control"] = {
            "open": (None, lambda _: self.accessor.open()),
            "close": (None, lambda _: self.accessor.close()),
            "connected": (lambda: self.accessor.isConnected, None)
        }
        self.tree["registers"] = {}
        self.registers = []
        for root_child in xml_root:
            self.registers.extend(self.parseRegisterElement(root_child, self.tree["registers"]))

        self.paramTree = ParameterTree(self.tree)

    def parseRegisterElement(self, element: ET.Element, tree: dict):
        regs = []
        info = element.attrib
        if len(element):
            first_child = element[0].attrib
            if first_child.get(ADDR_KEY, "0") == info.get(ADDR_KEY, "0") and "address" not in first_child:
                # children are bitFields
                try:
                    field_dict: dict[str, "BitField"] = {}
                    for field in element:
                        field_info = field.attrib
                        bit = BitField(field_info[NAME_KEY], field_info.get(DESC_KEY), field_info.get(PERM_KEY, "r"),
                                       int(field_info[MASK_KEY], 16))
                        field_dict[field_info[NAME_KEY]] = bit
                    register = Register(info.get(NAME_KEY), info.get(DESC_KEY), info.get(PERM_KEY),
                                        int(info.get(ADDR_KEY), 16),
                                        int(info.get(SIZE_KEY, 1)) * 4,  # size is in number of 32 bit words
                                        field_dict)
                    regs.append(register)
                    tree[register.name] = ParameterTree({
                        "value": (
                            partial(self.read_register, register=register),
                            None if not register.write else partial(self.write_register, register=register),
                            {DESC_KEY: register.desc}
                        ),
                        "fields": {
                            name: (
                                partial(self.read_field, register=register, field=field),
                                None if not field.write else partial(self.write_field, register=register, field=field),
                                {DESC_KEY: field.desc}
                            ) for (name, field) in field_dict.items()
                        }
                    })
                except KeyError as e:
                    raise e
            else:
                tree[info.get(NAME_KEY)] = {}
                for reg in element:
                    regs.extend(self.parseRegisterElement(reg, tree[info.get(NAME_KEY)]))
        else:
            register = Register(info.get(NAME_KEY), info.get(DESC_KEY), info.get(PERM_KEY),
                                int(info.get(ADDR_KEY), 16),
                                int(info.get(SIZE_KEY, 1)) * 4)  # size is in number of 32 bit words
            regs.append(register)
            tree[info.get(NAME_KEY)] = ParameterTree({
                "value": (partial(self.read_register, register=register),
                          None if not register.write else partial(self.write_register, register=register),
                          {DESC_KEY: register.desc})
            })

        return regs

    def read_register(self, register: "Register") -> int:
        if register.read:
            if self.accessor.isConnected:
                register.value = self.accessor.read(register.addr, register.size)
                return int.from_bytes(register.value, sys.byteorder)
            else:
                return int.from_bytes(register.value, sys.byteorder)
        else:
            raise ParameterTreeError("Unable to read Register {}: {}".format(register.name, "Register not readable"))

    def write_register(self, value: bytearray, register: "Register"):
        if register.write and self.accessor.isConnected:
            self.accessor.write(register.addr, value)
            register.value = self.accessor.read(register.addr, register.size)
        else:
            raise ParameterTreeError("Unable to write to Register {}: {}".format(register.name, "Not Connected" if register.write else "Register not writeable"))

    def _get_bitwise_trailing_zeros(self, val):
        """Method to get the number of trailing 0s on a binary value.
        Used to calculate how much to shift a masked value to return the specific value regardless of its position"""
        c = 0
        v = (val ^ (val - 1)) >> 1
        while v > 0:
            v >>= 1
            c += 1
        return c

    def read_field(self, register: "Register", field: "BitField") -> int:
        val = int.from_bytes(register.value, sys.byteorder)
        # get shift value
        mask = field.mask
        shift = self._get_bitwise_trailing_zeros(mask)
        return (val & mask) >> shift  # bitwise AND and then right shift to remove mask offset

    def write_field(self, value, register: "Register", field: "BitField"):
        mask = field.mask
        shift = self._get_bitwise_trailing_zeros(mask)
        start_val = int.from_bytes(register.value, sys.byteorder) & (~mask)  # get the reg value, but 0 out the bits this field relates to
        write_val = start_val & ((value << shift) & mask)  # AND the shifted write_val to the starting reg value

        self.write_register(write_val)


        

# XML Register assumptions:
# An example of what a register definition looks like in the XML:
# <node absolute_id="adm_pcie_9v5_iconnect.adm_pcie_9v5_stat.qsfp_dd_status" absolute_offset="00000008" address="0x00000008" description="QSFP-DD status register" hw_rst="0x0" id="qsfp_dd_status" permission="rw" size="1">
# The attributes we care about are:

# absolute_offset: the absolute addr of the register
# id: the register name. We're not using the absolute_id because it includes the full path through the register space, and that will be represented in the param tree instead
# size/byte_size: the size of the register. Not sure which is relevant, the example is based off a register map where every register is always 32 bits
# description: If present, a description of the register, for GUI purposes probably?
# permissions: a string that defines the read/write permissions. r means Readable, w means Writeable.

# Additionally, register's defined in XML might have child nodes representing the bitfields within:
# <node absolute_id="adm_pcie_9v5_iconnect.adm_pcie_9v5_stat.cmac_status.cmac_0_lane_up" absolute_offset="0000000c" description="CMAC 0 100GbE Rx aligned, used to indicate lane up" hw_rst="0x0" id="cmac_0_lane_up" mask="0x00000001" permission="r" size="1"/>
# the id, description, and permission will be treated the same as the register
# instead of a size, they will have a mask defining which bits within the register they represent?
# to check that a child node is a bitfield for a register rather than a register within a mapped section, check the absolute offset.
# if the absolute offset is the same as the parent, then it's a bitfield


@dataclass
class Memory:
    """Base Data Class, for inheritance only"""
    name: str
    desc: str = "No Description Provided"
    permission: str = "r"

    def __post_init__(self):
        for field in fields(self):
            if not isinstance(field.default, _MISSING_TYPE) and getattr(self, field.name) is None:
                setattr(self, field.name, field.default)
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

