import sys
import json
import pathlib
import xml.etree.ElementTree as ET
import logging

from dataclasses import dataclass, field, fields, _MISSING_TYPE

from RegisterAccessor.base.base_controller import BaseError


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
class BitField(Memory):
    """Data Class for the bitfields within a Register"""
    mask: int = 0  # a mask for the bits the field relate to


@dataclass
class Register(Memory):
    """Register Data Class, stores the addr, name, size, read/write permissions, description and any bitfields"""
    addr: int = 0  # absolute addr offset
    size: int = 4  # number bytes, default 32 bit reg
    bitFields: list[BitField] = field(default_factory=list)
    policy: str = ""  # defines how the adapter accesses the Register
    poll_freq: int = 0  # millisecond frequency for Polled Registers only
    timeLastRead: int = 0  # only used for Polled registers
    value: bytearray = field(default_factory=bytearray)


class RegisterMapError(BaseError):
    """Another SImple Exception Class"""


# attribute key consts for the XMl parsing, based on the XML firmware file
NAME_KEY = "id"
ADDR_KEY = "absolute_offset"
DESC_KEY = "description"
PERM_KEY = "permission"
MASK_KEY = "mask"
SIZE_KEY = "size"


class RegisterMap():
    """
    Class to read and parse the register map file, and any policy overwrite file. Turns these files
    into a nested dictionary tree structure containing Registers
    """
    supported_file_types = [".xml", ".json"]

    def __init__(self, reg_file: str, policy_file: str | None = None) -> None:
        self.reg_file = pathlib.Path(reg_file)
        self.policy_file = pathlib.Path(policy_file) if policy_file else None
        if not self.reg_file.is_file():
            raise RegisterMapError("Register Map File \"%s\" is not found", reg_file)
        if self.reg_file.suffix not in self.supported_file_types:
            raise RegisterMapError("Register Map File \"%s\" is invalid file type", reg_file)
        
        if not self.policy_file or not self.policy_file.exists():
            logging.info("Policy file invalid/Not provided")
            self.policy_overwrites = {}
        else:
            with open(self.policy_file) as f:
                self.policy_overwrites: dict[str, dict] = json.load(f)

        if ".xml" == self.reg_file.suffix:
            logging.debug("Reading Reg map from XML")
            self.map = self.read_xml_map(self.reg_file)
        elif ".json" == self.reg_file.suffix:
            logging.debug("Reading Reg map from JSON")
            self.map = self.read_json_map(self.reg_file)
        else:
            raise RegisterMapError("Register Map File \"%s\" is invalid file type", reg_file)
        
        # register map now saved and standardised between file types. Apply any additional policy overwrites
        for regName, policy in self.policy_overwrites.items():
            regs = self.getReg(regName, self.map)
            for reg in regs:
                reg.policy = policy.get("policy", reg.policy)
                reg.poll_freq = policy.get("frequency", reg.poll_freq)

    def read_xml_map(self, path: pathlib.Path):
        root = ET.parse(path).getroot()
        return self.parseXMLElement(root)

    def read_json_map(self, path: pathlib.Path):
        with open(path) as f:
            json_tree = json.load(f)
        return self.parseJSONElement("", json_tree)

    def parseXMLElement(self, element: ET.Element):
        info = element.attrib
        fields_list: list[BitField] = []
        if len(element):
            first_child = element[0].attrib
            if MASK_KEY in first_child and "address" not in first_child and first_child.get(ADDR_KEY) == info.get(ADDR_KEY):
                # fields of the register
                for fieldElement in element:
                    field_info = fieldElement.attrib
                    field = BitField(name=field_info.get(NAME_KEY),
                                     desc=field_info.get(DESC_KEY),
                                     permission=field_info.get(PERM_KEY),
                                     mask=int(field_info.get(MASK_KEY), 16))

                    fields_list.append(field)

            else:
                # subregisters inside area
                node = {}
                for reg in element:
                    node[reg.attrib.get(NAME_KEY)] = self.parseXMLElement(reg)
                
                return node

        reg = Register(name=info.get(NAME_KEY),
                       desc=info.get(DESC_KEY),
                       permission=info.get(PERM_KEY),
                       addr=int(info.get(ADDR_KEY), 16),
                       size=int(info.get(SIZE_KEY, 1)) * 4,
                       bitFields=fields_list)
        
        return reg

    def parseJSONElement(self, name: str, element: dict):
        if "addr" in element:
            # Register!
            fields_list: list[BitField] = []
            for field_name, field_info in element.get("fields", {}).items():
                fields_list.append(BitField(name=field_name,
                                            desc=field_info.get("desc"),
                                            permission=field_info.get("permission"),
                                            mask=field_info.get("mask")))

            reg = Register(name=name,
                           desc=element.get("desc"),
                           permission=element.get("permission"),
                           addr=element.get("addr"),
                           size=element.get("size"),
                           policy=element.get("access_policy"),
                           poll_freq=element.get("poll_rate"),
                           bitFields=fields_list
                           )
            return reg
        else:
            node = {}
            for reg_name, reg_dict in element.items():
                node[reg_name] = self.parseJSONElement(reg_name, reg_dict)
            
            return node
    
    def getReg(self, path: str, map: dict):
        """
        Get a list of all registers that match with the Path provided
        If path contains a "/", it is assumed to be a full path to a specific reg
        If not, it is assumed to be just the name of the register(s) desired
        """
        subMap: dict[str, Register | dict] = map
        if "/" in path:
            # is a direct path
            split_path = path.split("/")
            if split_path[-1] == "":
                del split_path[-1]
            for path in split_path:
                try:
                    if isinstance(subMap, dict):
                        subMap = subMap[path]
                    if isinstance(subMap, Register):
                        yield subMap
                except (KeyError, ValueError):
                    logging.error(map.keys())
                    raise RegisterMapError("Invalid Path: %s", path)
        else:
            # is just the register name. Return all registers with that name
            for k, v in subMap.items():
                if k == path and isinstance(v, Register):
                    yield v
                if isinstance(v, dict):
                    for result in self.getReg(path, v):
                        yield result


class RegisterEncoder(json.JSONEncoder):
    """Custom JSON encoder to allow the Register data class to be JSON serializable"""
    def default(self, o):
        if isinstance(o, Register):
            reg_dict = {
             "addr": o.addr,
             "size": o.size,
             "desc": o.desc,
             "permission": o.permission
            }
            if o.policy:
                reg_dict["access_policy"] = o.policy
            if o.poll_freq:
                reg_dict["poll_rate"] = o.poll_freq
            if o.bitFields:
                reg_dict['fields'] = {
                    bitField.name: {
                        "permission": bitField.permission,
                        "desc": bitField.desc,
                        "mask": bitField.mask
                    }
                    for bitField in o.bitFields}
            return reg_dict
        return super().default(self, o)
