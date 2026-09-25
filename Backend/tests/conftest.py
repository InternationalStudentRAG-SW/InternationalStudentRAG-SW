import pytest
from unittest.mock import MagicMock, patch
from fastapi.testclient import TestClient


@pytest.fixture(scope="session")
def client():
    # 무거운 모듈 mock 처리 (GitHub Actions에서 실제 모델 로딩 방지)
    mock_retriever = MagicMock()
    mock_kb = MagicMock()
    mock_kg = MagicMock()
    mock_supabase = MagicMock()

    with patch("app.core.retriever.RAGRetriever.__init__", return_value=None), \
         patch("app.core.knowledge_base.KnowledgeBase.__init__", return_value=None), \
         patch("app.core.knowledge_graph.KnowledgeGraph.__init__", return_value=None), \
         patch("app.db.database.supabase", mock_supabase):
        from app.main import app
        yield TestClient(app)
