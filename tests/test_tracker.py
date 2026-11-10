"""Tests for the Home Assistant independent tracking logic."""

import importlib.util
from pathlib import Path
import sys

_PATH = Path(__file__).parents[1] / "custom_components" / "teamspeak6" / "tracker.py"
_spec = importlib.util.spec_from_file_location("ts6_tracker", _PATH)
tracker = importlib.util.module_from_spec(_spec)
sys.modules["ts6_tracker"] = tracker  # needed by dataclasses
_spec.loader.exec_module(tracker)


def raw(clid, nick, cid="1", dbid=None, ctype="0"):
    return {
        "clid": str(clid),
        "client_nickname": nick,
        "cid": str(cid),
        "client_database_id": str(dbid if dbid is not None else clid + 100),
        "client_type": ctype,
    }


def test_query_clients_are_filtered():
    body = [raw(3, "serveradmin", ctype="1"), raw(1, "alice")]
    clients = tracker.parse_clients(body)
    assert [c.nickname for c in clients.values()] == ["alice"]


def test_client_type_as_int_is_accepted():
    body = [{**raw(1, "alice"), "client_type": 0}]
    assert len(tracker.parse_clients(body)) == 1


def test_spacer_prefixes_are_removed():
    for name, expected in [
        ("[cspacer]Lobby", "Lobby"),
        ("[cspacer0] Gaming", "Gaming"),
        ("[*spacer1]---", "---"),
        ("[RSPACER]Right", "Right"),
        ("[spacer]", ""),
        ("Normal [cspacer]", "Normal [cspacer]"),
    ]:
        assert tracker.clean_channel_name(name) == expected


def test_grouping_keeps_server_order_and_unknown_channels():
    clients = tracker.parse_clients([raw(1, "bob", cid=2), raw(2, "Alice", cid=2), raw(3, "eve", cid=9)])
    channels = {"1": "Lobby", "2": "Gaming"}
    groups = tracker.group_by_channel(clients, channels)
    assert groups == [
        {"cid": "2", "name": "Gaming", "users": ["Alice", "bob"]},
        {"cid": "9", "name": "#9", "users": ["eve"]},
    ]


def test_first_update_is_baseline_only():
    t = tracker.ClientTracker(rejoin_grace=60)
    assert t.update(tracker.parse_clients([raw(1, "alice")]), now=0) == []


def test_join_and_leave():
    t = tracker.ClientTracker(rejoin_grace=60)
    t.update({}, now=0)
    ev = t.update(tracker.parse_clients([raw(1, "alice")]), now=10)
    assert [(e.kind, e.client.nickname, e.rejoin) for e in ev] == [("joined", "alice", False)]
    ev = t.update({}, now=20)
    assert [(e.kind, e.client.nickname) for e in ev] == [("left", "alice")]


def test_quick_reconnect_is_flagged():
    t = tracker.ClientTracker(rejoin_grace=60)
    t.update(tracker.parse_clients([raw(1, "alice", dbid=5)]), now=0)
    t.update({}, now=10)
    ev = t.update(tracker.parse_clients([raw(7, "alice", dbid=5)]), now=40)
    assert [(e.kind, e.rejoin) for e in ev] == [("joined", True)]


def test_late_reconnect_is_a_normal_join():
    t = tracker.ClientTracker(rejoin_grace=60)
    t.update(tracker.parse_clients([raw(1, "alice", dbid=5)]), now=0)
    t.update({}, now=10)
    t.update({}, now=100)
    ev = t.update(tracker.parse_clients([raw(7, "alice", dbid=5)]), now=200)
    assert [(e.kind, e.rejoin) for e in ev] == [("joined", False)]


def test_reconnect_within_one_poll_is_flagged():
    # Old connection gone and new one present in the same poll.
    t = tracker.ClientTracker(rejoin_grace=60)
    t.update(tracker.parse_clients([raw(1, "alice", dbid=5)]), now=0)
    ev = t.update(tracker.parse_clients([raw(8, "alice", dbid=5)]), now=15)
    kinds = sorted((e.kind, e.rejoin) for e in ev)
    assert kinds == [("joined", True), ("left", False)]


def test_second_connection_of_same_user_is_flagged():
    t = tracker.ClientTracker(rejoin_grace=0)
    t.update(tracker.parse_clients([raw(1, "alice", dbid=5)]), now=0)
    ev = t.update(tracker.parse_clients([raw(1, "alice", dbid=5), raw(2, "alice", dbid=5)]), now=15)
    assert [(e.kind, e.rejoin) for e in ev] == [("joined", True)]


def test_reset_suppresses_events_after_outage():
    t = tracker.ClientTracker(rejoin_grace=60)
    t.update({}, now=0)
    t.reset()
    assert t.update(tracker.parse_clients([raw(1, "alice"), raw(2, "bob")]), now=30) == []
