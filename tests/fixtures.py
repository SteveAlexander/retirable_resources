import os
import unittest
import http.client
import warnings

from google.cloud import firestore

from retirable_resources import RetirableResources

firestore_project = "foo"
firestore_host = "localhost"
firestore_port = 8080


class FirestoreEmulatorTest:
    def setUp(self):
        self.__set_environ()
        warnings.filterwarnings("ignore", category=ResourceWarning, message="unclosed")

    def __set_environ(self):
        self._original_environ = {}
        self._original_environ["FIRESTORE_EMULATOR_HOST"] = os.environ.get(
            "FIRESTORE_EMULATOR_HOST"
        )
        self._original_environ["GCLOUD_PROJECT"] = os.environ.get("GCLOUD_PROJECT")
        os.environ["FIRESTORE_EMULATOR_HOST"] = f"{firestore_host}:{firestore_port}"
        os.environ["GCLOUD_PROJECT"] = firestore_project

    def __restore_environ(self):
        for k, v in self._original_environ.items():
            if v is not None:
                os.environ[k] = v

    def __clear_firebase(self):
        conn = http.client.HTTPConnection(firestore_host, firestore_port)
        conn.request(
            "DELETE",
            f"/emulator/v1/projects/{firestore_project}/databases/(default)/documents",
        )
        response = conn.getresponse()
        response.read()
        if response.status != 200:
            raise Exception(
                f"unable to delete database: {response.status} {response.reason}"
            )
        response.close()
        conn.close()

    def tearDown(self):
        self.__clear_firebase()
        self.__restore_environ()


class RetirableResourcesTest(FirestoreEmulatorTest, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.client = firestore.Client()
        self.r = RetirableResources('foo/bar', client = self.client)

    def tearDown(self):
        self.client.close()
        super().tearDown()
