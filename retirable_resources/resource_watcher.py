from contextlib import contextmanager
from datetime import datetime
from threading import Lock
from typing import Optional, Any, Generator, ContextManager

from google.cloud.firestore_v1 import DocumentSnapshot
from google.cloud.firestore_v1.watch import DocumentChange

from .resource_manager import RetirableResourceManager as BaseRetirableResourceManager


class ResourceWatcherData:
    def __init__(self, owner: str, server_timestamp: datetime, lock: Lock):
        self._owner = owner
        self._server_timestamp = server_timestamp
        self._lock = lock
        self._expired = False
        self._data: Optional[dict[str, Any]] = None

    @property
    def expired(self) -> bool:
        return self._expired

    @property
    def data(self) -> Optional[dict[str, Any]]:
        return self._data

    @property
    def updated(self) -> bool:
        return self._data is not None

    def _on_snapshot(
        self,
        snapshots: list[DocumentSnapshot],
        changes: list[DocumentChange],
        read_time: datetime,
    ):
        if self._data is not None or self._expired:
            return
        # print(f'{len(snapshots)} snapshots')
        for doc in snapshots:
            owner_dict = BaseRetirableResourceManager._doc_owner_dict(doc, self._owner)
            modified = owner_dict["modified"]
            if modified > self._server_timestamp:
                self._data = owner_dict["data"]
                self._lock.release()


class ResourceWatcher:
    def __init__(self, manager: BaseRetirableResourceManager, resource: str, owner: str):
        self._manager = manager
        self._resource = resource
        self._owner = owner

    @contextmanager
    def watch(
        self, /, *, timeout_seconds: float
    ) -> Generator[ResourceWatcherData, None, None]:
        server_timestamp = self._manager.when_modified(self._resource, self._owner)
        lock = Lock()
        lock.acquire()
        resource_watcher_data = ResourceWatcherData(self._owner, server_timestamp, lock)
        watch = self._manager._resource_docref(self._resource).on_snapshot(
            resource_watcher_data._on_snapshot
        )
        try:
            yield resource_watcher_data
            lock_result = lock.acquire(timeout=timeout_seconds)
            expired = not lock_result
            resource_watcher_data._expired = expired
        finally:
            watch.unsubscribe()
            watch.close()

class RetirableResourceManager(BaseRetirableResourceManager):
    def watch(
        self, resource: str, owner: str, timeout_seconds: float
    ) -> ContextManager[ResourceWatcherData]:
        return ResourceWatcher(self, resource=resource, owner=owner).watch(
            timeout_seconds=timeout_seconds
        )

