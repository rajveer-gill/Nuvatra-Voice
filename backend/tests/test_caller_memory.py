"""Caller memory must accept explicit name updates (not stuck on old COALESCE)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import database


def test_db_caller_memory_upsert_overwrites_name_when_provided():
    conn = MagicMock()
    cur = MagicMock()
    conn.cursor.return_value = cur
    cur.fetchone.side_effect = [(2, {})]  # existing row

    with patch.object(database, "_get_conn", return_value=conn), patch.object(
        database, "_client_id", return_value="test"
    ), patch.object(database, "_normalize_phone", return_value="15551234567"):
        database.db_caller_memory_upsert(
            "+15551234567",
            name="Raj",
            increment_count=False,
        )

    update_sql = cur.execute.call_args_list[1][0][0]
    assert "name = %s" in update_sql
    assert "COALESCE(%s, name)" not in update_sql
    assert cur.execute.call_args_list[1][0][1][0] == "Raj"
