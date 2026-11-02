import tempfile
import unittest
from pathlib import Path
from unittest.mock import call, patch

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import sessionmaker

from agent import schema


class SQLiteSchemaTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.database_path = Path(self.temp_dir.name) / "ominix.db"
        self.database_url = f"sqlite:///{self.database_path.as_posix()}"
        self.engine = create_engine(
            self.database_url,
            connect_args={"check_same_thread": False, "timeout": 30},
        )
        self.addCleanup(self.engine.dispose)
        self.engine_patch = patch.object(schema, "engine", self.engine)
        self.engine_patch.start()
        self.addCleanup(self.engine_patch.stop)

    def test_init_db_creates_sqlite_tables_and_data_persists(self):
        schema.init_db()
        session = sessionmaker(bind=self.engine)()
        try:
            session.add(
                schema.Conversation(
                    thread_id="persistent-thread",
                    owner_id="test-owner",
                    title="Persistent conversation",
                )
            )
            session.commit()
        finally:
            session.close()

        self.engine.dispose()
        reopened_engine = create_engine(self.database_url)
        self.addCleanup(reopened_engine.dispose)
        reopened_session = sessionmaker(bind=reopened_engine)()
        try:
            conversation = (
                reopened_session.query(schema.Conversation)
                .filter_by(thread_id="persistent-thread")
                .one()
            )
            self.assertEqual(conversation.owner_id, "test-owner")
            self.assertEqual(conversation.title, "Persistent conversation")
        finally:
            reopened_session.close()

    def test_init_db_adds_owner_id_to_existing_sqlite_database(self):
        with self.engine.begin() as connection:
            connection.execute(
                text(
                    "CREATE TABLE conversations ("
                    "id INTEGER PRIMARY KEY, "
                    "thread_id VARCHAR, "
                    "title VARCHAR, "
                    "created_at DATETIME, "
                    "updated_at DATETIME)"
                )
            )

        schema.init_db()

        columns = {
            column["name"]
            for column in inspect(self.engine).get_columns("conversations")
        }
        self.assertIn("owner_id", columns)

    def test_init_db_retries_transient_connection_failures(self):
        create_all = schema.Base.metadata.create_all
        transient_error = OperationalError(
            "connect", {}, RuntimeError("temporary database outage")
        )
        attempts = 0

        def create_all_with_transient_failures(*args, **kwargs):
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                raise transient_error
            return create_all(*args, **kwargs)

        with (
            patch.object(
                schema.Base.metadata,
                "create_all",
                side_effect=create_all_with_transient_failures,
            ),
            patch.object(schema.time, "sleep") as sleep,
        ):
            schema.init_db()

        self.assertEqual(attempts, 2)
        sleep.assert_has_calls([call(1)])


if __name__ == "__main__":
    unittest.main()
