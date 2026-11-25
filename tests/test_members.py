"""Tests for the member list and "last seen" logic (no Home Assistant needed)."""

import importlib.util
import json
from pathlib import Path
import sys

_PKG = Path(__file__).parents[1] / "custom_components" / "teamspeak6"


def _load(name):
    spec = importlib.util.spec_from_file_location(f"ts6_{name}", _PKG / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[f"ts6_{name}"] = module  # needed by dataclasses
    spec.loader.exec_module(module)
    return module


tracker = _load("tracker")
members = _load("members")

UID_A = "A" * 43 + "="  # TeamSpeak 6: 44 characters
UID_B = "b" * 27 + "="  # TeamSpeak 3: 28 characters


def online(*people):
    """people: (clid, nick, dbid)"""
    return {
        str(clid): tracker.Client(clid=str(clid), database_id=str(dbid), nickname=nick, cid="1")
        for clid, nick, dbid in people
    }


def dbrow(dbid, nick, uid, last=0, total=5):
    return {
        "cldbid": str(dbid),
        "client_totalconnections": str(total),
        "client_nickname": nick,
        "client_unique_identifier": uid,
        "client_lastconnected": str(last),
    }


def test_identity_filter():
    assert members.is_real_identity(UID_A)
    assert not members.is_real_identity("serveradmin")
    assert not members.is_real_identity("ServerQuery")
    assert members.is_real_identity(None)  # field missing: keep


def test_real_ts6_dblist_shape():
    # Shape of a real TeamSpeak 6 answer (values made up).
    body = [
        {"cldbid": "2", "client_nickname": "ServerQuery Guest", "client_lastconnected": "1770000000",
         "client_totalconnections": "0", "client_unique_identifier": "ServerQuery"},
        {"cldbid": "3", "client_nickname": "Alice", "client_lastconnected": "1790000000",
         "client_totalconnections": "441", "client_unique_identifier": "Zm9vYmFyZm9vYmFyZm9vYmFyZm9vYmFyZm9vYmFyMTI="},
    ]
    reg = members.MemberRegistry()
    reg.merge_dblist(body, complete=True)
    assert reg.options() == ["Alice"]
    assert reg.status("3").timestamp == 1790000000


def test_dblist_skips_query_logins_and_sorts_options():
    reg = members.MemberRegistry()
    reg.merge_dblist(
        [dbrow(1, "serveradmin", "serveradmin"), dbrow(5, "bob", UID_A), dbrow(6, "Alice", UID_B)],
        complete=True,
    )
    assert reg.options() == ["Alice", "bob"]


def test_duplicate_nicknames_get_unique_options():
    reg = members.MemberRegistry()
    reg.merge_dblist([dbrow(5, "Max", UID_A), dbrow(6, "max", UID_B)], complete=True)
    assert reg.options() == ["Max (#5)", "max (#6)"]
    assert reg.select("max (#6)") and reg.selected == "6"
    assert not reg.select("Max")


def test_observation_only_fallback():
    reg = members.MemberRegistry()
    assert reg.observe({}, now=1000) is False
    assert reg.observe(online((1, "alice", 5)), now=1015) is True
    assert reg.options() == ["alice"]
    reg.select("alice")

    st = reg.status("5")
    assert st.online and st.timestamp == 1015 and st.source == members.SOURCE_ONLINE

    reg.observe(online((1, "alice", 5)), now=1030)
    assert reg.observe({}, now=1045) is True  # left -> save
    st = reg.status("5")
    assert not st.online
    assert st.timestamp == 1030  # last poll in which she was online
    assert st.source == members.SOURCE_OBSERVED


def test_last_login_from_database_wins_when_newer():
    reg = members.MemberRegistry()
    reg.observe(online((1, "alice", 5)), now=100)
    reg.observe({}, now=115)
    # Later she was online while Home Assistant was off.
    reg.merge_dblist([dbrow(5, "alice", UID_A, last=5000)], complete=True)
    st = reg.status("5")
    assert st.timestamp == 5000 and st.source == members.SOURCE_LAST_LOGIN


def test_session_start_after_restart_comes_from_database():
    reg = members.MemberRegistry()
    reg.merge_dblist([dbrow(5, "alice", UID_A, last=900)], complete=True)
    reg.observe(online((1, "alice", 5)), now=1000)  # first poll = baseline
    assert reg.status("5").timestamp == 900
    reg.observe({}, now=1015)
    reg.observe(online((2, "alice", 5)), now=2000)  # a real join later
    assert reg.status("5").timestamp == 2000


def test_heartbeat_marks_dirty_while_online():
    reg = members.MemberRegistry()
    assert reg.observe(online((1, "alice", 5)), now=1000)
    assert not reg.observe(online((1, "alice", 5)), now=1015)
    assert reg.observe(online((1, "alice", 5)), now=1000 + members.HEARTBEAT)


def test_nickname_change_and_two_connections():
    reg = members.MemberRegistry()
    reg.observe(online((1, "alice", 5), (2, "alice", 5)), now=10)
    assert reg.options() == ["alice"]
    reg.observe(online((1, "Alice_new", 5)), now=25)
    assert reg.options() == ["Alice_new"]


def test_complete_dblist_prunes_deleted_members_but_not_online_ones():
    reg = members.MemberRegistry()
    reg.merge_dblist([dbrow(5, "alice", UID_A), dbrow(6, "bob", UID_B)], complete=True)
    reg.select("bob")
    reg.observe(online((1, "carol", 7)), now=10)
    reg.merge_dblist([dbrow(5, "alice", UID_A)], complete=True)
    assert reg.options() == ["alice", "carol"]
    assert reg.selected is None
    # An incomplete list never removes anybody.
    reg.merge_dblist([], complete=False)
    assert reg.options() == ["alice", "carol"]


def test_store_roundtrip_keeps_selection_not_online_state():
    reg = members.MemberRegistry()
    reg.merge_dblist([dbrow(5, "alice", UID_A, last=50)], complete=True)
    reg.observe(online((1, "alice", 5)), now=100)
    reg.select("alice")
    data = json.loads(json.dumps(reg.as_dict()))

    again = members.MemberRegistry()
    again.load(data)
    assert again.selected == "5"
    st = again.status("5")
    assert not st.online and st.timestamp == 100 and st.last_login == 50


def test_load_ignores_garbage():
    reg = members.MemberRegistry()
    reg.load({"selected": "9", "members": {"0": {}, "x": "nope", "5": {"nickname": "a"}}})
    assert reg.options() == ["a"] and reg.selected is None
    assert reg.status(None) is None and reg.status("404") is None


def _keys(obj, prefix=""):
    if isinstance(obj, dict):
        out = set()
        for k, v in obj.items():
            out |= _keys(v, f"{prefix}.{k}")
        return out
    return {prefix}


def test_translations_have_the_same_keys():
    en = json.loads((_PKG / "translations" / "en.json").read_text(encoding="utf-8"))
    de = json.loads((_PKG / "translations" / "de.json").read_text(encoding="utf-8"))
    strings = json.loads((_PKG / "strings.json").read_text(encoding="utf-8"))
    assert _keys(en) == _keys(de) == _keys(strings)
