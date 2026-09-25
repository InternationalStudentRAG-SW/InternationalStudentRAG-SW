from unittest.mock import patch, MagicMock


def test_get_faqs_returns_list(client):
    mock_res = MagicMock()
    mock_res.data = [
        {
            "id": "1",
            "question_ko": "비자 연장은 어떻게 하나요?",
            "question_en": "How do I extend my visa?",
            "question_zh": "",
            "question_es": "",
            "answer_ko": "출입국관리사무소에 신청하세요.",
            "answer_en": "",
            "answer_zh": "",
            "answer_es": "",
            "is_active": True,
            "display_order": 1,
        }
    ]

    with patch("app.db.database.supabase") as mock_supabase:
        mock_supabase.table.return_value.select.return_value \
            .eq.return_value.order.return_value.execute.return_value = mock_res

        res = client.get("/faq")
        assert res.status_code == 200
        assert isinstance(res.json(), list)


def test_get_faqs_empty(client):
    mock_res = MagicMock()
    mock_res.data = []

    with patch("app.db.database.supabase") as mock_supabase:
        mock_supabase.table.return_value.select.return_value \
            .eq.return_value.order.return_value.execute.return_value = mock_res

        res = client.get("/faq")
        assert res.status_code == 200
        assert res.json() == []
