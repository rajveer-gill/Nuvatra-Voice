"""Tests for usage tracking. Mocks database when DATABASE_URL is not set."""
import pytest
from unittest.mock import MagicMock, patch

# Import database module - when no DB, _get_conn returns None
import database as db


def test_db_usage_get_returns_none_without_db():
    """Without DB connection, db_usage_get returns None or empty dict."""
    with patch.object(db, "_get_conn", return_value=None):
        result = db.db_usage_get("client1", "2025-02")
        # When conn is None, returns None
        assert result is None


def test_db_usage_get_returns_empty_for_invalid_input():
    """db_usage_get with empty client_id returns None."""
    with patch.object(db, "_get_conn", return_value=None):
        result = db.db_usage_get("", "2025-02")
        assert result is None
    with patch.object(db, "_get_conn", return_value=None):
        result = db.db_usage_get("client1", "")
        assert result is None


def test_db_usage_increment_voice_returns_false_without_db():
    """Without DB, db_usage_increment_voice returns False."""
    with patch.object(db, "_get_conn", return_value=None):
        result = db.db_usage_increment_voice("client1", "2025-02", 5)
        assert result is False


def test_db_usage_increment_voice_rejects_negative_minutes():
    """db_usage_increment_voice rejects negative minutes."""
    with patch.object(db, "_get_conn", return_value=MagicMock()):
        result = db.db_usage_increment_voice("client1", "2025-02", -1)
        assert result is False


def test_db_usage_increment_sms_returns_false_without_db():
    """Without DB, db_usage_increment_sms returns False."""
    with patch.object(db, "_get_conn", return_value=None):
        result = db.db_usage_increment_sms("client1", "2025-02")
        assert result is False


def test_db_usage_get_with_mock_conn():
    """With mocked conn, db_usage_get returns voice_minutes and sms_count."""
    mock_cur = MagicMock()
    mock_cur.fetchone.return_value = (10, 5)
    mock_conn = MagicMock()
    mock_conn.cursor.return_value = mock_cur

    with patch.object(db, "_get_conn", return_value=mock_conn):
        result = db.db_usage_get("client1", "2025-02")
        assert result is not None
        assert result["voice_minutes"] == 10
        assert result["sms_count"] == 5


def test_db_usage_get_missing_row_returns_zeros():
    """When no row exists, db_usage_get returns zeros."""
    mock_cur = MagicMock()
    mock_cur.fetchone.return_value = None
    mock_conn = MagicMock()
    mock_conn.cursor.return_value = mock_cur

    with patch.object(db, "_get_conn", return_value=mock_conn):
        result = db.db_usage_get("client1", "2025-02")
        assert result == {"voice_minutes": 0, "sms_count": 0}
