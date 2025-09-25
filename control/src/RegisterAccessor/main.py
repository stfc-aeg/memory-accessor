import sys
import logging

from argparse import ArgumentParser

def main(argv=None):
    """
    Run the Register Map Creator
    """

    parser = ArgumentParser()
    parser.add_argument("--XML", help="Filepath for the XML Register Definition File")

    logging.error("HELLO FROM COMMAND LINE")



    return 0


if __name__ == "__main":
    sys.exit(main())