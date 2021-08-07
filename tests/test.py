import unittest

from retirable_resources import (
    RetirableResourceManager,
    SetValue,
    AddToList,
    ResourceDoesNotExist,
    OwnerDoesNotExist,
    ResourceOwnerView,
    ResourceWatcher,
)

from .fixtures import RetirableResourceManagerTest


class TestInitialize(unittest.TestCase):
    def test_init_with_empty_path(self):
        client = object()
        with self.assertRaises(ValueError):
            r = RetirableResourceManager("", client=client)
        with self.assertRaises(ValueError):
            r = RetirableResourceManager([], client=client)
        with self.assertRaises(ValueError):
            r = RetirableResourceManager(tuple(), client=client)

    def test_init_with_incorrect_type_path(self):
        client = object()
        with self.assertRaises(TypeError):
            r = RetirableResourceManager(object(), client=client)

    def test_init_fails_with_odd_doc_path(self):
        client = object()
        with self.assertRaises(ValueError):
            r = RetirableResourceManager(["foo"], client=client)
        with self.assertRaises(ValueError):
            r = RetirableResourceManager(("foo",), client=client)
        with self.assertRaises(ValueError):
            r = RetirableResourceManager("foo", client=client)

    def test_init_with_even_doc_path(self):
        client = object()
        r = RetirableResourceManager("foo/bar", client=client)
        self.assertEqual(r.root_path, ("foo", "bar"))
        r = RetirableResourceManager(["foo", "bar"], client=client)
        self.assertEqual(r.root_path, ("foo", "bar"))
        r = RetirableResourceManager(("foo", "bar"), client=client)
        self.assertEqual(r.root_path, ("foo", "bar"))


class Test(RetirableResourceManagerTest):
    def test_set_owners(self):
        r = self.r
        self.assertListEqual(r.list_owners(), [])
        r.set_owners(["bob"])
        self.assertListEqual(r.list_owners(), ["bob"])
        r.set_owners(["bob", "mary"])
        self.assertListEqual(r.list_owners(), ["bob", "mary"])

    def test_update_data_on_nonexistent_resource(self):
        r = self.r
        with self.assertRaises(ResourceDoesNotExist):
            r.update_data("resource", "bob", SetValue("foo", "bar"))

    def test_data(self):
        r = self.r
        data1 = {"example": "1234"}
        data2 = {"example": "abcd"}
        r.add_resource("resource.1")
        r.set_owners(["bob"])
        bobresource1 = "resource.1"
        r.update_data(bobresource1, "bob", SetValue("example", "1234"))
        self.assertDictEqual(r.get_data(bobresource1, owner="bob"), data1)
        r.update_data(bobresource1, "bob", SetValue("example", "abcd"))
        self.assertDictEqual(r.get_data(bobresource1, owner="bob"), data2)
        r.update_data(
            bobresource1,
            "bob",
            SetValue("example", "wxyz"),
            AddToList("log", "apple"),
        )
        self.assertDictEqual(
            r.get_data(bobresource1, owner="bob"),
            {
                "example": "wxyz",
                "log": ["apple"],
            },
        )
        r.update_data(
            bobresource1,
            "bob",
            AddToList("log", "banana", "carrot"),
        )

        def check_nothing_changed():
            self.assertDictEqual(
                r.get_data(bobresource1, owner="bob"),
                {
                    "example": "wxyz",
                    "log": ["apple", "banana", "carrot"],
                },
            )

        resource_taken_by_bob = r.take("bob", tag="coffee")
        self.assertEqual(resource_taken_by_bob, bobresource1)
        check_nothing_changed()
        r.free(bobresource1, "bob")
        check_nothing_changed()
        r.set_owners(["bob", "mary"])
        check_nothing_changed()
        r.retire(bobresource1, owner="bob")
        check_nothing_changed()
        r.retire_resource(bobresource1)
        check_nothing_changed()
        self.assertEqual(r.status(bobresource1, "mary"), "retired")

    def test_resource_exists(self):
        r = self.r
        self.assertListEqual(r.list_owners(), [])
        self.assertFalse(r.resource_exists("resource.1"))
        r.add_resource("resource.1")
        self.assertTrue(r.resource_exists("resource.1"))

    def test_is_active(self):
        r = self.r
        self.assertIsNone(r.is_active("resource"))
        r.add_resource("resource")
        self.assertTrue(r.is_active("resource"))
        r.retire_resource("resource")
        self.assertIsNotNone(r.is_active("resource"))
        self.assertFalse(r.is_active("resource"))

    def test_allocation_clears_on_retirement(self):
        r = self.r
        r.set_owners(["bob"])

        r.add_resource("resource")
        r.take("bob", "coffee")
        self.assertSetEqual(r.list_allocation("bob", "coffee"), {"resource"})
        r.retire("resource", "bob")
        self.assertSetEqual(r.list_allocation("bob", "coffee"), set())

        r.add_resource("resource2")
        r.take("bob", "coffee")
        self.assertSetEqual(r.list_allocation("bob", "coffee"), {"resource2"})
        r.retire_resource("resource2")
        self.assertSetEqual(r.list_allocation("bob", "coffee"), set())

    def test_allocation(self):
        r = self.r
        r.set_owners(["bob"])
        all_resources = {"r1", "r2", "r3"}
        for resource in all_resources:
            r.add_resource(resource)
        self.assertSetEqual(r.list_allocation("bob", "coffee"), set())

        allocated_resources = r.request_allocation("bob", "coffee", 10)
        self.assertSetEqual(allocated_resources, all_resources)
        for resource in allocated_resources:
            self.assertEqual(r.status(resource, "bob"), "owned")
        self.assertSetEqual(r.list_allocation("bob", "coffee"), allocated_resources)

        allocated_resources = r.request_allocation("bob", "coffee", 2)
        self.assertEqual(len(allocated_resources), 2)
        unallocated_resources = all_resources - allocated_resources
        self.assertEqual(len(unallocated_resources), 1)
        for resource in allocated_resources:
            self.assertEqual(r.status(resource, "bob"), "owned")
        for resource in unallocated_resources:
            self.assertEqual(r.status(resource, "bob"), "free")
        self.assertSetEqual(r.list_allocation("bob", "coffee"), allocated_resources)

        allocated_resources = r.request_allocation("bob", "coffee", 0)
        self.assertSetEqual(allocated_resources, set())
        for resource in all_resources:
            self.assertEqual(r.status(resource, "bob"), "free")
        self.assertSetEqual(r.list_allocation("bob", "coffee"), set())

    def test_free_allocation_count(self):
        r = self.r
        r.set_owners(["bob"])
        all_resources = {"r1", "r2", "r3", "r4", "r5"}
        for resource in all_resources:
            r.add_resource(resource)
        r.take("bob", "coffee")
        r.take("bob", "coffee")
        r.take("bob", "tea")
        self.assertEqual(len(r.list_allocation("bob", "coffee")), 2)
        self.assertEqual(len(r.list_allocation("bob", "tea")), 1)
        self.assertEqual(r.free_allocation_count("bob"), 2)
        r.clear_allocation("bob")
        self.assertSetEqual(r.list_allocation("bob", "coffee"), set())
        self.assertEqual(r.free_allocation_count("bob"), 5)
        r.retire_resource("r2")
        self.assertEqual(r.free_allocation_count("bob"), 4)

    def test_owner_lifecycle(self):
        r = self.r
        with self.assertRaises(ResourceDoesNotExist):
            r.status("resource", "mary")
        self.assertEqual(r.add_resource("resource"), "ok")
        self.assertTrue(r.is_active("resource"))

        self.assertEqual(r.add_resource("resource"), "already exists")

        with self.assertRaises(OwnerDoesNotExist):
            r.status("resource", "mary")
        r.set_owners(["mary"])
        self.assertEqual(r.status("resource", "mary"), "free")
        r.take("mary", tag="green tea")
        self.assertEqual(r.status("resource", "mary"), "owned")

        r.free("resource", owner="mary")
        self.assertEqual(r.status("resource", "mary"), "free")

        # We can retire an unknown owner, and it's a no-op
        self.assertEqual(r.retire("resource", "unknown owner"), "resource active")

        r.set_owners(["bob", "mary"])

        self.assertEqual(r.retire("resource", "mary"), "resource active")

        # When the last owner is retired, the whole resource is retired
        self.assertEqual(r.retire("resource", "bob"), "resource retired")

    def test_resource_retirement(self):
        r = self.r
        r.set_owners(["bob"])
        r.add_resource("resource")
        self.assertTrue(r.is_active("resource"))
        self.assertEqual(r.status("resource", "bob"), "free")
        r.retire_resource("resource")
        self.assertFalse(r.is_active("resource"))
        self.assertEqual(r.status("resource", "bob"), "retired")

    def test_set_owners_updates_resources(self):
        r = self.r
        data = {"example": "1234"}
        self.assertListEqual(r.list_owners(), [])
        r.add_resource("resource.1")
        r.add_resource("resource.2")
        self.assertIsNone(r.take("bob", tag="coffee"))
        r.set_owners(["bob"])
        bobresource1 = r.take("bob", tag="coffee")
        self.assertTrue(r.is_active(bobresource1))
        self.assertTrue(bobresource1.startswith("resource."))
        r.update_data(bobresource1, "bob", SetValue("example", "1234"))
        self.assertDictEqual(r.get_data(bobresource1, owner="bob"), data)
        self.assertListEqual(r.list_owners(), ["bob"])
        r.set_owners(["bob", "mary"])
        self.assertListEqual(r.list_owners(), ["bob", "mary"])
        maryresource1 = r.take("mary", tag="green tea")
        self.assertTrue(maryresource1.startswith("resource."))
        maryresource2 = r.take("mary", tag="earl grey")
        self.assertNotEqual(maryresource1, maryresource2)
        self.assertIsNone(r.take("mary", tag="cola"))
        self.assertEqual(r.status(maryresource2, "mary"), "owned")
        r.free(maryresource2, "mary")
        self.assertEqual(r.status(maryresource2, "mary"), "free")
        r.add_resource("resource.3")

        r.set_owners(["mary"])
        self.assertListEqual(r.list_owners(), ["mary"])

    def test_owner_view(self):
        r = self.r
        r.set_owners(["bob"])
        r.add_resource("resource")
        ov = ResourceOwnerView("bob", r)
        ov.update_data("resource", SetValue("foo", 123))
        self.assertEqual(r.get_data("resource", "bob"), {"foo": 123})
        self.assertEqual(ov.get_data("resource"), {"foo": 123})
        self.assertEqual(ov.status("resource"), "free")
        bob_resource = ov.take("coffee")
        self.assertEqual(bob_resource, "resource")
        self.assertEqual(ov.status("resource"), "owned")
        ov.free(bob_resource)
        self.assertEqual(ov.status("resource"), "free")
        ov.retire(bob_resource)
        self.assertEqual(ov.status("resource"), "retired")

    def test_watch(self):
        r = self.r
        r.add_resource("resource")
        r.update_data("resource", "bob", SetValue("tokens", []))

        rw = ResourceWatcher(r, "resource", "bob")
        with rw.watch(timeout_seconds=1) as watcher:
            r.update_data("resource", "mary", AddToList("tokens", "1234"))
            r.update_data(
                "resource", "bob", AddToList("tokens", "BOB VALUE", "BOB VALUE 1")
            )
            r.update_data("resource", "bob", AddToList("tokens", "BOB VALUE 2"))
            r.update_data("resource", "mary", AddToList("tokens", "1234"))
        self.assertTrue(watcher.updated)
        self.assertFalse(watcher.expired)
        self.assertDictEqual(watcher.data, {"tokens": ["BOB VALUE", "BOB VALUE 1"]})

        with rw.watch(timeout_seconds=1) as watcher:
            r.update_data("resource", "mary", AddToList("tokens", "1234"))
            r.update_data("resource", "mary", AddToList("tokens", "1234"))
        self.assertFalse(watcher.updated)
        self.assertTrue(watcher.expired)
        self.assertIsNone(watcher.data)

    def test_dispose_resource(self):
        r = self.r
        r.add_resource("resource")
        r.dispose_resource("resource")
        with self.assertRaises(ResourceDoesNotExist):
            r.get_data("resource", "bob")

    def test_dispose_all_resources(self):
        r = self.r
        all_resources = ["r1", "r2", "r3", "r4"]
        for resource in all_resources:
            r.add_resource(resource)
        r.dispose_all_resources()
        for resource in all_resources:
            with self.assertRaises(ResourceDoesNotExist):
                r.get_data(resource, "bob")


if __name__ == "__main__":
    unittest.main()
