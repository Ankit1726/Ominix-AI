import atexit
import os
import tempfile
import unittest
from pathlib import Path
from uuid import uuid4

from fastapi.testclient import TestClient

_test_data = tempfile.TemporaryDirectory()
_database_path = Path(_test_data.name) / "test.sqlite"
os.environ["DATABASE_URL"] = f"sqlite:///{_database_path.as_posix()}"
os.environ["CHECKPOINT_DB_PATH"] = str(Path(_test_data.name) / "checkpoints.sqlite")

from agent.db import create_conversation, list_conversations, search_memory, save_memory
from agent.main import DEFAULT_MODEL, normalize_model_name
from agent.schema import engine
from agent.tools import calculator
from app import app, extract_document_text, split_document


def _cleanup_test_data():
    engine.dispose()
    _test_data.cleanup()


atexit.register(_cleanup_test_data)


class ApplicationTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)
        self.thread_id = uuid4().hex

    def test_home_and_health_endpoints(self):
        self.assertEqual(self.client.get("/").status_code, 200)
        self.assertEqual(
            self.client.get("/healthz").json(),
            {"status": "ok"},
        )

    def test_config_exposes_key_presence_not_key_values(self):
        response = self.client.get("/config")
        self.assertEqual(response.status_code, 200)
        self.assertIn("default_model", response.json())
        self.assertNotIn("api_key", response.json())

    def test_chat_rejects_malformed_and_oversized_messages(self):
        for message in (None, 42, [], "  "):
            with self.subTest(message=message):
                response = self.client.post(
                    "/chat/stream",
                    json={"message": message, "thread_id": self.thread_id},
                )
                self.assertEqual(response.status_code, 400)

        response = self.client.post(
            "/chat/stream",
            json={
                "message": "x" * 20_001,
                "thread_id": self.thread_id,
            },
        )
        self.assertEqual(response.status_code, 413)

    def test_chat_rejects_malformed_json_and_non_object_bodies(self):
        response = self.client.post(
            "/chat/stream",
            content="{",
            headers={"content-type": "application/json"},
        )
        self.assertEqual(response.status_code, 400)

        response = self.client.post("/chat/stream", json=["hello"])
        self.assertEqual(response.status_code, 400)

    def test_chat_rejects_invalid_conversation_and_model_values(self):
        response = self.client.post(
            "/chat/stream",
            json={"message": "hello", "thread_id": "not valid"},
        )
        self.assertEqual(response.status_code, 400)

        response = self.client.post(
            "/chat/stream",
            json={
                "message": "hello",
                "thread_id": self.thread_id,
                "model": "bad model id",
            },
        )
        self.assertEqual(response.status_code, 400)

    def test_conversations_are_scoped_to_the_owner(self):
        self.assertTrue(create_conversation(self.thread_id, "owner-a", "hello"))
        self.assertFalse(create_conversation(self.thread_id, "owner-b", "hello"))
        self.assertEqual(
            [item.thread_id for item in list_conversations("owner-a")],
            [self.thread_id],
        )
        self.assertEqual(list_conversations("owner-b"), [])

    def test_conversation_history_is_not_visible_to_other_sessions(self):
        response = self.client.get(f"/history/{self.thread_id}")
        self.assertEqual(response.status_code, 404)

    def test_document_extraction_and_chunking(self):
        self.assertEqual(
            extract_document_text("note.txt", b"\xef\xbb\xbf hello "),
            "hello",
        )
        chunks = split_document("a" * 2_000)
        self.assertEqual([len(chunk) for chunk in chunks], [1_200, 1_000])
        self.assertEqual(chunks[0][1_000:], chunks[1][:200])

    def test_document_upload_and_owner_isolation(self):
        response = self.client.post(
            f"/documents/{self.thread_id}",
            files={"file": ("note.txt", b"private notes", "text/plain")},
        )
        self.assertEqual(response.status_code, 200)
        document_id = response.json()["document"]["id"]
        self.assertEqual(
            self.client.get(f"/documents/{self.thread_id}").json()["documents"][0][
                "filename"
            ],
            "note.txt",
        )

        other_client = TestClient(app)
        self.assertEqual(
            other_client.get(f"/documents/{self.thread_id}").status_code,
            404,
        )
        self.assertEqual(
            self.client.delete(
                f"/documents/{self.thread_id}/{document_id}"
            ).status_code,
            200,
        )

    def test_document_upload_rejects_invalid_files(self):
        endpoint = f"/documents/{self.thread_id}"
        invalid_uploads = (
            ("note.exe", b"content", 400),
            ("empty.txt", b"", 400),
            ("broken.docx", b"not a zip archive", 400),
            ("large.txt", b"x" * (5 * 1024 * 1024 + 1), 413),
        )
        for filename, content, expected_status in invalid_uploads:
            with self.subTest(filename=filename):
                response = self.client.post(
                    endpoint,
                    files={"file": (filename, content, "application/octet-stream")},
                )
                self.assertEqual(response.status_code, expected_status)

    def test_memory_search_returns_saved_matches(self):
        create_conversation(self.thread_id, "memory-owner")
        save_memory(self.thread_id, "Prefers concise Python examples")
        save_memory(self.thread_id, "Works with web applications")
        self.assertIn("concise Python", search_memory(self.thread_id, "Python"))

    def test_model_normalization_and_calculator(self):
        self.assertEqual(normalize_model_name(None), DEFAULT_MODEL)
        self.assertEqual(normalize_model_name("custom/model-v1"), "custom/model-v1")
        with self.assertRaises(ValueError):
            normalize_model_name("invalid model")
        self.assertEqual(
            calculator.invoke({"expression": "sqrt(81) + 2 * 3"}),
            "15.0",
        )
        self.assertTrue(
            calculator.invoke(
                {"expression": "__import__('os').system('whoami')"}
            ).startswith("Calculation error:")
        )


if __name__ == "__main__":
    unittest.main()
