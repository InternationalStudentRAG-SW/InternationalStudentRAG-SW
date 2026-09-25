import os
import pytest
from unittest.mock import MagicMock, patch
from fastapi.testclient import TestClient

os.environ.setdefault("OPENAI_API_KEY", "test-key")
os.environ.setdefault("SUPABASE_URL", "https://test.supabase.co")
os.environ.setdefault("SUPABASE_ANON_KEY", "test-anon-key")
os.environ.setdefault("SUPABASE_SERVICE_KEY", "test-service-key")
os.environ.setdefault("ADMIN_SECRET", "test-admin-secret")

with patch("app.db.database.supabase", MagicMock()):
    from app.main import app

_client = TestClient(app)


@pytest.fixture(scope="session")
def client():
    yield _client
