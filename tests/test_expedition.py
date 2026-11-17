import pytest
from baiaidle.expedition import parse_expedition_cooldown


def test_parse_expedition_cooldown_hours_and_minutes():
    res = parse_expedition_cooldown("espere 3h06 para entrar numa expedição de novo")
    assert res is not None
    assert res["hours"] == 3
    assert res["minutes"] == 6
    assert res["seconds"] == 0
    assert res["total_seconds"] == 3 * 3600 + 6 * 60


def test_parse_expedition_cooldown_compact_hours():
    res = parse_expedition_cooldown("espere 3h12 para entrar numa expedição de novo")
    assert res is not None
    assert res["hours"] == 3
    assert res["minutes"] == 12
    assert res["seconds"] == 0


def test_parse_expedition_cooldown_only_minutes():
    res = parse_expedition_cooldown("espere 45m para entrar numa expedição de novo")
    assert res is not None
    assert res["hours"] == 0
    assert res["minutes"] == 45
    assert res["seconds"] == 0
    assert res["total_seconds"] == 45 * 60


def test_parse_expedition_cooldown_minutes_and_seconds():
    res = parse_expedition_cooldown("espere 10m 30s para entrar numa expedição de novo")
    assert res is not None
    assert res["hours"] == 0
    assert res["minutes"] == 10
    assert res["seconds"] == 30
    assert res["total_seconds"] == 630


def test_parse_expedition_cooldown_empty():
    assert parse_expedition_cooldown("") is None
    assert parse_expedition_cooldown(None) is None
