import sys
import logging
import json
import pathlib

from xml.etree import ElementTree as ET
from argparse import ArgumentParser


# attribute key consts for the XMl parsing, based on the XML firmware file
NAME_KEY = "id"
FULLNAME_KEY = "absolute_id"
ADDR_KEY = "absolute_offset"
DESC_KEY = "description"
PERM_KEY = "permission"
MASK_KEY = "mask"
SIZE_KEY = "size"


class Config():

    def __init__(self, argv) -> None:
        parser = ArgumentParser(description=("Create a JSON register map, by converting the provided XML map, "
                                         "and adding defined access policies telling the Adapter "
                                         "how these registers can be accessed"))
        parser.add_argument("--map_file", help="Filepath for the XML Register Definition File", required=True)
        parser.add_argument("--policy_file", help="Filepath for the (optional) JSON register Access Policy file")
        parser.add_argument("--policy", "-p",
                            default="static",
                            help="Default Access policy for all registers",
                            choices=["static", "polled", "immediate"])
        parser.add_argument("--poll_rate", "-r", default=1000, help="Default polling rate for all registers, in milliseconds")
        parser.add_argument("--dest", help="Filepath for the outputted JSON register map")

        (arg_config, _) = parser.parse_known_args(argv)
        arg_config = vars(arg_config)

        map_src_filename = arg_config.get("map_file")
        policy_filename = arg_config.get("policy_file")
        if policy_filename:
            with open(policy_filename) as f:
                self.policy_overwrites = json.load(f)
        else:
            self.policy_overwrites = {}

        self.dest_filename = arg_config.get("dest") or str(pathlib.PurePath(map_src_filename).with_suffix(".json"))
        
        self.default_policy = arg_config.get("policy")
        self.default_poll_rate = arg_config.get("poll_rate")

        self.root = ET.parse(map_src_filename).getroot()


    def parseRegisterElement(self, element: ET.Element):
        
        info = element.attrib
        node = {}

        if len(element):
            first_child = element[0].attrib
            if MASK_KEY in first_child and "address" not in first_child and first_child.get(ADDR_KEY) == info.get(ADDR_KEY):
                # fields of the register
                fields_dict = {}
                for fieldElement in element:
                    field = {}
                    field_info = fieldElement.attrib

                    field['permission'] = field_info.get(PERM_KEY, "r")
                    if field_info.get(DESC_KEY):
                        field["desc"] = field_info.get(DESC_KEY)
                    field['mask'] = field_info.get(MASK_KEY)
                    fields_dict[field_info.get(NAME_KEY)] = field
                
                node['fields'] = fields_dict

            else:
                # subregisters inside area
                for reg in element:
                    node[reg.attrib.get(NAME_KEY)] = self.parseRegisterElement(reg)
                
                return node

        node["addr"] = info.get(ADDR_KEY)
        node["size"] = info.get(SIZE_KEY)
        if info.get(DESC_KEY):
            node["desc"] = info.get(DESC_KEY)
        node["permission"] = info.get(PERM_KEY)

        node_overwrites = {}
        node_path = info.get(FULLNAME_KEY, "").replace(".", "/")
        if info.get(NAME_KEY) in self.policy_overwrites or node_path in self.policy_overwrites:
            node_overwrites = self.policy_overwrites.get(info.get(NAME_KEY)) or self.policy_overwrites.get(node_path)

        node['access_policy'] = node_overwrites.get("policy", self.default_policy)
        if node['access_policy'] == "polled":
            node['poll_rate'] = node_overwrites.get("frequency", self.default_poll_rate)

        return node


def main(argv=None):
    """
    Run the Register Map Creator
    """
    logging.basicConfig(level=logging.DEBUG)
    config = Config(argv)

    reg_tree = config.parseRegisterElement(config.root)

    with open(config.dest_filename, "w") as outfile:
        json.dump(reg_tree, outfile, indent=2)
        logging.info("File output to %s", config.dest_filename)


    return 0


if __name__ == "__main__":

    sys.exit(main())