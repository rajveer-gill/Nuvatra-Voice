"""Tests for database leads and sms_automations functions."""
import pytest
from unittest.mock import MagicMock, patch
import database as db


def test_db_leads_insert_returns_none_without_db():
    """Without DB, db_leads_insert returns None."""
    with patch.object(db, "_get_conn", return_value=None):
        result = db.db_leads_insert("client1", "Lead Name", "+15551234567", "inquiry", "call")
        assert result is None


def test_db_leads_insert_rejects_invalid_source():
    """db_leads_insert rejects invalid source."""
    with patch.object(db, "_get_conn", return_value=MagicMock()):
        result = db.db_leads_insert("client1", "Lead", "+15551234567", "reason", "invalid")
        assert result is None


def test_db_leads_insert_rejects_empty_phone():
    """db_leads_insert rejects empty phone."""
    with patch.object(db, "_get_conn", return_value=None):
        result = db.db_leads_insert("client1", "Lead", "", "reason", "call")
        assert result is None


def test_db_leads_get_all_returns_empty_without_db():
    """Without DB, db_leads_get_all returns []."""
    with patch.object(db, "_get_conn", return_value=None):
        result = db.db_leads_get_all("client1", 100)
        assert result == []


def test_db_sms_automations_get_all_returns_empty_without_db():
    """Without DB, db_sms_automations_get_all returns []."""
    with patch.object(db, "_get_conn", return_value=None):
        result = db.db_sms_automations_get_all("client1")
        assert result == []


def test_db_sms_automations_count_returns_zero_without_db():
    """Without DB, db_sms_automations_count returns 0."""
    with patch.object(db, "_get_conn", return_value=None):
        result = db.db_sms_automations_count("client1")
        assert result == 0


def test_db_sms_automations_insert_rejects_invalid_trigger():
    """db_sms_automations_insert rejects invalid trigger."""
    with patch.object(db, "_get_conn", return_value=MagicMock()):
        result = db.db_sms_automations_insert("client1", "invalid_trigger", "template")
        assert result is None


def test_db_overage_processed_exists_returns_false_without_db():
    """Without DB, db_overage_processed_exists returns False."""
    with patch.object(db, "_get_conn", return_value=None):
        result = db.db_overage_processed_exists("client1", "2025-02")
        assert result is False


def test_db_tenant_get_by_client_id_returns_none_without_db():
    """Without DB, db_tenant_get_by_client_id returns None."""
    with patch.object(db, "_get_conn", return_value=None):
        result = db.db_tenant_get_by_client_id("client1")
        assert result is None


def test_db_tenant_get_by_client_id_returns_none_for_empty():
    """db_tenant_get_by_client_id returns None for empty client_id."""
    with patch.object(db, "_get_conn", return_value=MagicMock()):
        result = db.db_tenant_get_by_client_id("")
        assert result is None
