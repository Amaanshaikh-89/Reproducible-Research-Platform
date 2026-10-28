import pytest
from fastapi.testclient import TestClient
from app.database import init_db
import app.main as main_module

@pytest.fixture()
def client(tmp_path, monkeypatch):
    db_path = tmp_path / "test.db"
    monkeypatch.setattr(main_module, "connect", lambda: __import__("app.database", fromlist=["connect"]).connect(db_path))
    init_db(db_path)
    with TestClient(main_module.app) as test_client:
        yield test_client
