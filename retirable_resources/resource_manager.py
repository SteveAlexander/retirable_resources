from typing import (
    cast,
    Literal,
    Optional,
    Any,
    Generator,
    Union,
    Iterable,
    TypedDict,
    Protocol,
)

from datetime import datetime

from google.cloud.exceptions import Conflict, NotFound
from google.cloud.firestore_v1.base_query import BaseQuery
from google.cloud.firestore_v1.transforms import Sentinel, ArrayUnion, ArrayRemove
from google.cloud.firestore_v1.field_path import (
    get_field_path,
    FieldPath,
)
from google.cloud.firestore_v1 import (
    Client,
    DocumentReference,
    DocumentSnapshot,
    CollectionReference,
    Transaction,
    transactional,
    DELETE_FIELD,
    SERVER_TIMESTAMP,
)

_free_marker_literal = Literal["_FREE_MARKER_"]
_free_marker: _free_marker_literal = "_FREE_MARKER_"
_owned_marker_literal = Literal["_OWNED_MARKER_"]
_owned_marker: _owned_marker_literal = "_OWNED_MARKER_"
_retired_marker_literal = Literal["_RETIRED_MARKER_"]
_retired_marker: _retired_marker_literal = "_RETIRED_MARKER_"
_active_field_literal = Literal["_ACTIVE_"]
_active_field: _active_field_literal = "_ACTIVE_"


OwnerDataContainer = dict[str, Any]


class OwnerDataContainer(TypedDict, total=True):
    state: Union[_free_marker_literal, _owned_marker_literal, _retired_marker_literal]
    data: dict[str, Any]
    modified: Union[Sentinel, datetime]


class OwnedDataContainer(OwnerDataContainer):
    tag: str


ResourceOwnersDict = dict[str, OwnerDataContainer]


class RetirableResourceException(Exception):
    pass


class ResourceDoesNotExist(RetirableResourceException):
    pass


class ResourceNotAllocated(RetirableResourceException):
    pass


class OwnerDoesNotExist(RetirableResourceException):
    pass


class UpdateCommand(Protocol):
    def _update(self, data: dict[str, Any]) -> None:
        """Update the dict with fields names and updates to add"""


class SetValue:
    def __init__(self, key: str, value: Any):
        self._key = key
        self._value = value

    def _update(self, data: dict[str, Any]) -> None:
        data[self._key] = self._value


class AddToList:
    def __init__(self, key: str, *values: Any):
        self._key = key
        self._values = values

    def _update(self, data: dict[str, Any]) -> None:
        data[self._key] = ArrayUnion(self._values)


class RetirableResourceManager:
    def __init__(
        self, root_doc_path: Union[str, tuple[str], list[str]], *, client: Client
    ):
        """Initialize retirable resources manager, situated at `root_doc_path`,
        using the provided Firestore client.

        `root_doc_path` is either a slash-delimited string, or a sequence of path
        segments, and must refer to a document location, not a collection location,
        in firestore.

        Raises a ValueError if `root_doc_path` does not have an even number of
        path elements.
        """
        if isinstance(root_doc_path, str):
            root_path = root_doc_path.split("/")
        elif isinstance(root_doc_path, (list, tuple)):
            root_path = tuple(root_doc_path)
        else:
            raise TypeError(
                "root_doc_path must be a str, list[str] or tuple[str]", root_doc_path
            )

        if not root_path or len(root_path) % 2 != 0:
            raise ValueError("root path must be a valid document path", root_path)

        self._root_doc_path: tuple[str] = tuple(root_path)
        self._client = client

    @property
    def root_path(self):
        return self._root_doc_path

    def list_owners(self) -> list[str]:
        """Returns list of owners"""
        return self._root_dict().get("owners", [])

    def set_owners(self, owners: list[str]) -> None:
        """Set the owners to `owners`"

        Update all active resources with the new owners list, preserving
        tags for owners that did not change.
        """

        @transactional
        def t_update(transaction: Transaction) -> None:
            previous_owners = self._owners(transaction=transaction)
            new_owners = set(owners)
            update_spec = {
                **{k: DELETE_FIELD for k in previous_owners - new_owners},
                **{k: self._new_owner_data() for k in new_owners - previous_owners},
            }
            # NB: transactions require all reads before all writes
            active_resources = self._active_resources_list(transaction=transaction)
            transaction.set(self._root_docref(), {"owners": owners}, merge=True)
            for doc in active_resources:
                # TODO: does this mean we have a max of 500 resources here,
                #       due to the limit on operations in one tranaction?
                transaction.update(doc.reference, update_spec)

        t_update(self._client.transaction())

    def take(self, owner: str, tag: str) -> Optional[str]:
        """Take an additional free resource for the owner"""

        @transactional
        def t_take(transaction: Transaction) -> Optional[str]:
            resource = self._find_free_resource_for(owner, transaction=transaction)
            if resource is None:
                return None
            else:
                self._set_tag(resource, owner=owner, tag=tag, transaction=transaction)
                return resource

        return t_take(self._client.transaction())

    def status(self, resource: str, owner: str) -> Literal["owned", "free", "retired"]:
        """Return the status of the resource as owned by `owner`

        The status is "owner", "free", or "retired"
        """
        owner_dict = self._owner_data_container(resource, owner)
        state = owner_dict["state"]
        if state == _owned_marker:
            return "owned"
        if state == _free_marker:
            return "free"
        if state == _retired_marker:
            return "retired"
        raise Exception("owner_dict in invalid state", owner_dict)

    def dispose_all_resources(self) -> None:
        """Dispose all resources"""
        for doc in self._resources_collection().stream():
            cast(DocumentReference, doc.reference).delete()

    def dispose_resource(self, resource: str) -> None:
        """Dispose a single resource"""
        self._resource_docref(resource).delete()

    def dispose(self) -> None:
        """Dispose everything"""
        self.dispose_all_resources()
        self._root_docref().delete()

    def retire_resource(self, resource: str) -> None:
        """Retire the resource"""

        @transactional
        def t_retire_resource(transaction):
            self._t_retire_resource(transaction, resource)

        t_retire_resource(self._client.transaction())

    def retire(
        self, resource: str, owner: str
    ) -> Literal["resource retired", "resource active"]:
        """Retire ownership of a resource"""

        @transactional
        def t_retire(
            transaction: Transaction,
        ) -> Literal["resource retired", "resource active"]:
            if self._active_owners(resource, transaction=transaction) == {owner}:
                self._t_retire_resource(transaction, resource)
                return "resource retired"
            else:
                transaction.update(
                    self._resource_docref(resource),
                    {
                        FieldPath(owner, "state").to_api_repr(): _retired_marker,
                        FieldPath(owner, "tag").to_api_repr(): DELETE_FIELD,
                    },
                )
                return "resource active"

        return t_retire(self._client.transaction())

    def free(self, resource: str, owner: str) -> None:
        """Free the resource for the owner"""
        self._resource_docref(resource).update(
            {
                FieldPath(owner, "state").to_api_repr(): _free_marker,
                FieldPath(owner, "tag").to_api_repr(): DELETE_FIELD,
            }
        )

    def is_active(self, resource: str) -> Optional[bool]:
        """Returns True if active, False if retired, None if does not exist"""
        data = self._resource_doc(resource).to_dict()
        if data is None:
            return None
        return data[_active_field]

    def add_resource(self, resource: str) -> Literal["ok", "already exists"]:
        """Add the resource, with a free tag for each owner.

        Returns "ok" if the resource was created, or "already exists" if
        the resource already exists.
        """
        try:
            self._resource_docref(resource).create(self._new_resource_data())
            return "ok"
        except Conflict:
            return "already exists"

    def resource_exists(self, resource: str) -> bool:
        """Return True if this resource exists.

        The resource may be active or may be retired.
        """
        return self._resource_doc(resource).exists

    def get_data(self, resource: str, owner: str) -> dict:
        """"""
        return self._get_owner_data_container(resource, owner=owner)["data"]

    def update_data(
        self, resource: str, owner: str, *update_commands: UpdateCommand
    ) -> None:
        """"""
        updates = {}
        for command in update_commands:
            command._update(updates)

        docref = self._resource_docref(resource)

        try:
            docref.update(
                {
                    **{
                        FieldPath(owner, "data", key).to_api_repr(): value
                        for key, value in updates.items()
                    },
                    FieldPath(owner, "modified").to_api_repr(): SERVER_TIMESTAMP,
                }
            )
        except NotFound:
            raise ResourceDoesNotExist(resource)

    def list_allocation(self, owner: str, tag: str) -> set[str]:
        """Returns set of resources allocated to the owner and tag"""
        docs = (
            self._resources_collection()
            .where(
                FieldPath(owner, "tag").to_api_repr(),
                "==",
                tag,
            )
            .select(())
            .get()
        )
        return {doc.id for doc in docs}

    def request_allocation(self, owner: str, tag: str, qty: int) -> set[str]:
        """Request allocation of resource for the owner and the tag.

        Returns the allocated resources, which might be less than what
        was requested.
        """
        allocated_resources = self.list_allocation(owner, tag)
        num_allocated = len(allocated_resources)
        num_to_take = max(0, qty - num_allocated)
        num_to_free = max(0, num_allocated - qty)
        if num_to_take:
            for _ in range(num_to_take):
                resource = self.take(owner, tag)
                if resource is None:
                    break
                allocated_resources.add(resource)
        if num_to_free:
            for _ in range(num_to_free):
                self.free(allocated_resources.pop(), owner)
        return allocated_resources

    def clear_allocation(self, owner: str) -> None:
        """Clear all allocations for the owner"""
        for resource in self._resources_by_state(owner, _owned_marker):
            self.free(resource, owner)

    def free_allocation_count(self, owner: str) -> int:
        """How many resources are available to become allocated for owner

        Caution: Because Firestore has no `count` operation, this operation may
        be unexpectedly expensive.
        """
        return len(self._resources_by_state(owner, _free_marker))

    def when_modified(self, resource: str, owner: str) -> datetime:
        owner_dict = self._owner_data_container(resource, owner)
        return owner_dict["modified"]

    @staticmethod
    def _doc_owner_dict(doc: DocumentSnapshot, owner: str) -> datetime:
        owner_dict = doc.to_dict().get(owner)
        if owner_dict is None:
            raise Exception("invalid owner_dict for doc", doc.id)
        return owner_dict

    def _owner_data_container(self, resource: str, owner: str) -> OwnerDataContainer:
        owners_dict = self._resource_owners_dict(resource)
        if owners_dict is None:
            raise ResourceDoesNotExist(resource)
        owner_dict = owners_dict.get(owner)
        if owner_dict is None:
            raise OwnerDoesNotExist(resource, owner)
        return owner_dict

    def _resources_by_state(self, owner: str, state: str) -> set[str]:
        docs = (
            self._resources_collection()
            .where(
                FieldPath(owner, "state").to_api_repr(),
                "==",
                state,
            )
            .select(())
            .get()
        )
        return {doc.id for doc in docs}

    def _get_owner_data_container(
        self, resource: str, *, owner: str, transaction: Optional[Transaction] = None
    ) -> OwnerDataContainer:
        owners_dict = self._resource_owners_dict(resource, transaction=transaction)
        if owners_dict is None:
            raise ResourceDoesNotExist(resource)
        data = owners_dict.get(owner)
        if data is None:
            raise OwnerDoesNotExist(resource, owner)
        return data

    def _find_free_resource_for(
        self, owner: str, transaction: Optional[Transaction] = None
    ) -> Optional[str]:
        """"""
        result = (
            self._resources_collection()
            .where(
                FieldPath(owner, "state").to_api_repr(),
                "==",
                _free_marker,
            )
            .limit(1)
            .get(transaction=transaction)
        )
        docs = list(result)
        return docs[0].id if len(docs) else None

    def _t_retire_resource(
        self,
        transaction: Transaction,
        resource: str,
    ) -> None:
        doc = self._resource_doc(resource, transaction=transaction)
        if not doc.exists:
            raise ResourceDoesNotExist(resource)
        data = doc.to_dict()
        owners = [key for key in data.keys() if key != _active_field]
        updates = {
            _active_field: False,
        }
        for owner in owners:
            updates[FieldPath(owner, "state").to_api_repr()] = _retired_marker
            updates[FieldPath(owner, "tag").to_api_repr()] = DELETE_FIELD

        transaction.update(self._resource_docref(resource), updates)

    def _set_tag(
        self,
        resource: str,
        /,
        *,
        owner: str,
        tag: str,
        transaction: Optional[Transaction] = None,
    ) -> None:
        """Set the tag for this resource

        This is only called when the resource is free
        """
        updatee = transaction if transaction else DocumentReference
        updatee.update(
            self._resource_docref(resource),
            {
                FieldPath(owner, "tag").to_api_repr(): tag,
                FieldPath(owner, "state").to_api_repr(): _owned_marker,
            },
        )

    def _active_owners(
        self, resource: str, *, transaction: Optional[Transaction] = None
    ) -> set[str]:
        """Active owners are owners of a resource that are not retired"""
        owners_dict = self._resource_owners_dict(resource, transaction=transaction)
        return (
            set()
            if owners_dict is None
            else set(
                owner
                for owner, v in owners_dict.items()
                if v["state"] != _retired_marker
            )
        )

    @staticmethod
    def _escape_field(name: str) -> str:
        return get_field_path((name,))

    def _child_path(self, *parts: str) -> tuple[str]:
        return FieldPath(*self._root_doc_path + parts).parts

    def _resource_path(self, resource: str) -> tuple[str]:
        return self._child_path("resources", resource)

    def _resources_collection(self) -> CollectionReference:
        return self._client.collection(*self._child_path("resources"))

    def _resource_owners_dict(
        self, resource: str, transaction: Optional[Transaction] = None
    ) -> Optional[ResourceOwnersDict]:
        """Returns a ResourceOwnersDict, or None if the resource does not
        exist.

        Keys are owners, as str
        Values are `OwnerDataContainer` objects
        """
        data = self._resource_doc(resource, transaction=transaction).to_dict()
        if data is None:
            return None
        del data[_active_field]
        return data

    def _resource_doc(
        self, resource: str, *, transaction: Optional[Transaction] = None
    ) -> DocumentSnapshot:
        return self._resource_docref(resource).get(transaction=transaction)

    def _resource_docref(self, resource: str) -> DocumentReference:
        return self._client.document(*self._resource_path(resource))

    def _root_docref(self) -> DocumentReference:
        return self._client.document(*self._root_doc_path)

    def _root_dict(
        self, *, transaction: Optional[Transaction] = None
    ) -> dict[str, Any]:
        return self._root_docref().get(transaction=transaction).to_dict() or {}

    def _active_resources_query(self) -> BaseQuery:
        return self._resources_collection().where(_active_field, "==", True)

    def _active_resources(self) -> Generator[DocumentSnapshot, Any, None]:
        return self._active_resources_query().stream()

    def _active_resources_list(
        self, transaction: Optional[Transaction] = None
    ) -> Iterable[DocumentSnapshot]:
        return self._active_resources_query().get(transaction=transaction)

    def _owners(self, *, transaction: Optional[Transaction] = None) -> set[str]:
        return set(self._root_dict(transaction=transaction).get("owners", set()))

    def _new_resource_data(self) -> dict[str, Any]:
        return {
            _active_field: True,
            **{
                FieldPath(k).to_api_repr(): self._new_owner_data()
                for k in self._owners()
            },
        }

    def _new_owner_data(self) -> dict[str, Any]:
        return {
            "state": _free_marker,
            "data": {},
            "modified": SERVER_TIMESTAMP,
        }
