from .base.base_adapter import BaseAdapter
from .controller import RegisterAccessorController, ControllerError


class RegisterAccessorAdapter(BaseAdapter):
    """RegisterAccessor Adapter class inheriting base adapter functionality."""

    controller_cls = RegisterAccessorController
    error_cls = ControllerError