from .base.base_adapter import BaseAdapter
from .controller import MemoryaccessorController, MemoryaccessorError


class MemoryaccessorAdapter(BaseAdapter):
    """MEMORYACCESSOR Adapter class inheriting base adapter functionality."""

    controller_cls = MemoryaccessorController
    error_cls = MemoryaccessorError