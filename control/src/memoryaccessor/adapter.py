from .base.base_adapter import BaseAdapter
from .controller import MemoryAccessorController, ControllerError


class MemoryaccessorAdapter(BaseAdapter):
    """MEMORYACCESSOR Adapter class inheriting base adapter functionality."""

    controller_cls = MemoryAccessorController
    error_cls = ControllerError