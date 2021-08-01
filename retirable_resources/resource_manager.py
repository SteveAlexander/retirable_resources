from typing import cast, Literal, Optional, Any, Generator, Union, Iterable

from google.auth.credentials import Credentials
from google.cloud.exceptions import Conflict
from google.cloud.firestore_v1.base_query import BaseQuery
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
)


class RetirableResourcesException(Exception):
    pass


class ResourceDoesNotExist(Exception):
    pass


class RetirableResources:
    _free_marker = "_FREE_MARKER_"
    _retired_marker = "_RETIRED_MARKER_"
    _active_field = "_ACTIVE_"

    def __init__(self, root_doc_path, *, client: Client):
        self._root_doc_path: tuple[str] = FieldPath.from_string(
            get_field_path(root_doc_path.split("."))
        ).parts
        self._client = client

    def set_owners(self, owners: list[str]) -> None:
        """Set the owners to `owners`"

        Update all active resources with the new owners list, preserving
        values for owners that did not change.
        """

        @transactional
        def update(transaction: Transaction) -> None:
            previous_owners = self._owners(transaction=transaction)
            new_owners = set(owners)
            update_spec = {
                **{k: DELETE_FIELD for k in previous_owners - new_owners},
                **{k: self._free_marker for k in new_owners - previous_owners},
            }
            # NB: transactions require all reads before all writes
            active_resources = self._active_resources_list(transaction=transaction)
            transaction.set(self._root_docref(), {"owners": owners}, merge=True)
            for doc in active_resources:
                transaction.update(doc.reference, update_spec)

        update(self._client.transaction())

    def take(self, owner: str, value: str) -> Optional[str]:
        """"""

        @transactional
        def _take(transaction: Transaction) -> Optional[str]:
            resource = self._find_free_resource_for(owner, transaction=transaction)
            if resource is None:
                return None
            else:
                self._set_value(resource, owner, value, transaction=transaction)
                return resource

        return _take(self._client.transaction())

    def dispose_all_resources(self) -> None:
        """Dispose all resources"""
        for doc in self._resources_collection().stream():
            doc.reference.delete()

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
                    {self._escape_field(owner): self._retired_marker},
                )
                return "resource active"

        return t_retire(self._client.transaction())

    def free(self, resource: str, owner: str) -> None:
        """Free the resource for the owner"""
        self._resource_docref(resource).update(
            {self._escape_field(owner): self._free_marker}
        )

    def add_resource(self, resource: str) -> Literal["ok", "already exists"]:
        """"""
        try:
            self._client.document(*self._resource_path(resource)).create(
                self._new_resource_data()
            )
            return "ok"
        except Conflict:
            return "already exists"

    def _find_free_resource_for(
        self, owner: str, transaction: Optional[Transaction] = None
    ) -> Optional[str]:
        """"""
        result = (
            self._resources_collection()
            .where(
                self._escape_field(owner),
                "==",
                self._free_marker,
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
        transaction.set(self._resource_docref(resource), {self._active_field: False})

    def _set_value(
        self,
        resource: str,
        owner: str,
        value: str,
        transaction: Optional[Transaction] = None,
    ) -> None:
        """"""
        if value == self._free_marker or value == self._retired_marker:
            raise ValueError(value)
        updatee = transaction if transaction else DocumentReference
        updatee.update(
            self._resource_docref(resource), {self._escape_field(owner): value}
        )

    def _active_owners(
        self, resource: str, transaction: Optional[Transaction] = None
    ) -> set[str]:
        """Active owners are owners of a resource that are not retired"""
        data = self._resource_dict(resource, transaction=transaction)
        return (
            set()
            if data is None
            else set(k for k, v in data.items() if v != self._retired_marker)
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

    def _resource_dict(
        self, resource: str, transaction: Optional[Transaction] = None
    ) -> Optional[dict[str, Any]]:
        data = self._resource_doc(resource, transaction=transaction).to_dict()
        if data is None:
            return None
        del data[self._active_field]
        return data

    def _resource_doc(
        self, resource: str, transaction: Optional[Transaction] = None
    ) -> DocumentSnapshot:
        return self._resource_docref(resource).get(transaction=transaction)

    def _resource_docref(self, resource: str) -> DocumentReference:
        return self._client.document(*self._resource_path(resource))

    def _root_docref(self) -> DocumentReference:
        return self._client.document(*self._root_doc_path)

    def _root_dict(self, transaction: Optional[Transaction] = None) -> dict[str, Any]:
        return self._root_docref().get(transaction=transaction).to_dict() or {}

    def _active_resources_query(self) -> BaseQuery:
        return self._resources_collection().where(self._active_field, "==", True)

    def _active_resources(self) -> Generator[DocumentSnapshot, Any, None]:
        return self._active_resources_query().stream()

    def _active_resources_list(
        self, transaction: Optional[Transaction] = None
    ) -> Iterable[DocumentSnapshot]:
        return self._active_resources_query().get(transaction=transaction)

    def _owners(self, transaction: Optional[Transaction] = None) -> set[str]:
        return set(self._root_dict(transaction=transaction).get("owners", set()))

    def _new_resource_data(self) -> dict[str, Any]:
        return {
            self._active_field: True,
            **{k: self._free_marker for k in self._owners()},
        }
