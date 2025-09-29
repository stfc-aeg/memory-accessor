import sys
import logging
import json
import pathlib

from xml.etree import ElementTree as ET
from argparse import ArgumentParser

from RegisterAccessor.RegisterMap import RegisterMap, RegisterEncoder


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

        self.map_src_filename = arg_config.get("map_file")
        self.policy_filename = arg_config.get("policy_file")
        
        self.dest_filename = arg_config.get("dest") or str(pathlib.PurePath(self.map_src_filename).with_suffix(".json"))
        
        self.default_policy = arg_config.get("policy")
        self.default_poll_rate = arg_config.get("poll_rate")



def main(argv=None):
    """
    Run the Register Map Creator
    """
    logging.basicConfig(level=logging.DEBUG)
    config = Config(argv)

    reg_tree = RegisterMap(config.map_src_filename, config.policy_filename)

    with open(config.dest_filename, "w") as outfile:
        json.dump(reg_tree.map, outfile, indent=2, cls=RegisterEncoder)
        logging.info("File output to %s", config.dest_filename)


    return 0


if __name__ == "__main__":

    sys.exit(main())