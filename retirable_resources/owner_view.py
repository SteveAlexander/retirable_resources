from datetime import datetime
from typing import Literal, Optional, ContextManager

from .resource_manager import UpdateCommand
from .resource_watcher import ResourceWatcherData, RetirableResourceManager


class ResourceOwnerView:
    def __init__(self, owner: str, retirable_resources: RetirableResourceManager):
        self._owner = owner
        self._r = retirable_resources

    def take(self, tag: str) -> Optional[str]:
        return self._r.take(self._owner, tag=tag)

    def status(self, resource: str) -> Literal["owned", "free", "retired"]:
        return self._r.status(resource, owner=self._owner)

    def retire(self, resource: str) -> Literal["resource retired", "resource active"]:
        return self._r.retire(resource, owner=self._owner)

    def free(self, resource: str) -> None:
        self._r.free(resource, owner=self._owner)

    def get_data(self, resource: str) -> dict:
        return self._r.get_data(resource, owner=self._owner)

    def update_data(self, resource: str, *update_commands: UpdateCommand) -> None:
        self._r.update_data(resource, self._owner, *update_commands)

    def when_modified(self, resource: str) -> datetime:
        return self._r.when_modified(resource=resource, owner=self._owner)

    def free_allocation_count(self) -> int:
        return self._r.free_allocation_count(self._owner)

    def clear_allocation(self) -> None:
        self._r.clear_allocation(self._owner)

    def request_allocation(self, tag: str, qty: int) -> set[str]:
        return self._r.request_allocation(owner=self._owner, tag=tag, qty=qty)

    def list_allocation(self, tag: str) -> set[str]:
        return self._r.list_allocation(owner=self._owner, tag=tag)

    def watch(
        self, resource: str, timeout_seconds: float
    ) -> ContextManager[ResourceWatcherData]:
        return self._r.watch(
            resource, owner=self._owner, timeout_seconds=timeout_seconds
        )
