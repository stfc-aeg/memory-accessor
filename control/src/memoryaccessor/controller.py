import logging
from odin.adapters.parameter_tree import ParameterTree, ParameterTreeError

from .base.base_controller import BaseController, BaseError


class MemoryaccessorError(BaseError):
    """Simple exception class to wrap lower-level exceptions."""


class MemoryaccessorController(BaseController):
    """Controller class for MEMORYACCESSOR."""

    def __init__(self, options):
        self.options = options
        self.example_param = "Example"
        self.param_tree = ParameterTree({
            "example_param": (lambda: self.example_param,  lambda v: setattr(self, 'example_param', v))
        })

    def initialize(self, adapters):
        self.adapters = adapters
        logging.debug(f"Adapters initialized: {list(adapters.keys())}")
        # Add to param tree if needed post-initialization

    def cleanup(self):
        logging.info("Cleaning up MemoryaccessorController")

    def get(self, path, with_metadata=False):
        try:
            return self.param_tree.get(path, with_metadata)
        except ParameterTreeError as error:
            logging.error(error)
            raise MemoryaccessorError(error)

    def set(self, path, data):
        try:
            self.param_tree.set(path, data)
        except ParameterTreeError as error:
            logging.error(error)
            raise MemoryaccessorError(error)