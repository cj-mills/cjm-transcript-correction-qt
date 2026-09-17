"""The scalable assign-lane speaker picker in the shell (DEC 774dbe40, item
75bc0384): the digit slots come from this source's assigned speakers and the
collection's siblings only, the readout groups them by tier, the A editor
searches the whole registry (one match commits, several pin a digit listing,
none mints), and the session resolves the collection scope at spine open
without blocking on it. Unbound methods over SimpleNamespace hosts (the
test_navigation strategy) — no QApplication for the gesture logic."""
import asyncio
from types import SimpleNamespace

from cjm_transcript_correction_qt.app import CorrectionWindow
from cjm_transcript_correction_qt.session import CorrectionShellSession


def _ent(eid, name, provisional=False):
    return {"id": eid, "properties": {"canonical_name": name, "kind": "person",
                                      "provisional": provisional}}


REGISTRY = [_ent("mark", "Mark Saroufim"), _ent("jacob", "Jacob Hemstad"),
            _ent("jeremy", "Jeremy Howard"), _ent("ti", "Ti Morse"),
            _ent("chris", "Chris Wright"), _ent("scott", "Scott Nolan")]


def seg(i, sid):
    return SimpleNamespace(id=sid, index=i, text="t")


def host(**kw):
    """A GPU MODE lecture: jacob then mark assigned in the spine; jeremy + mark
    recur across the collection's siblings; ti / chris / scott live in other
    collections (the registry tier)."""
    view = SimpleNamespace(
        segments=[seg(0, "s0"), seg(1, "s1"), seg(2, "s2")],
        speakers={"s0": {"entity_id": "jacob"}, "s1": {"entity_id": "mark"}},
        queue=None, graph_id="g", source_id="lecture", size=3,
        assign_local=lambda *a, **k: None)
    d = dict(view=view, cursor=2, _entities=list(REGISTRY),
             _picker_scope={"collections": [{"id": "c", "title": "GPU MODE", "status": "confirmed"}],
                            "siblings": {"l1": "Lecture 1", "l2": "Lecture 2"},
                            "entity_sources": {"mark": ["lecture", "l1", "l2"],
                                               "jeremy": ["l1"],
                                               "ti": ["nuke-1"], "chris": ["nuke-1"],
                                               "scott": ["nuke-1"]},
                            "source_collections": {"nuke-1": ["Nuclear Energy"],
                                                   "l1": ["GPU MODE"]}},
             _recent_entities=[], _assign_matches=[], _assign_pinned=[],
             _active_entity=None, _accept_cluster=None,
             ASSIGN_DIGITS=CorrectionWindow.ASSIGN_DIGITS,
             _input_mode="assign", editor=SimpleNamespace(isVisible=lambda: True),
             _editor_helper="", _paint_frame=lambda: None,
             commits=[], session_id="sess", actor="human", _journal_path=None)
    d.update(kw)
    h = SimpleNamespace(**d)
    # bind the shell's own methods onto the stub host
    for name in ("_assign_menu", "_assign_digits", "_speaker_tiers", "_assign_context",
                 "_assign_prompt", "_on_editor_text_changed", "_do_assign_pick",
                 "_do_submit_assign", "_do_commit_assign", "_note_recent",
                 "_pick_provenance", "action_assign_new"):
        setattr(h, name, getattr(CorrectionWindow, name).__get__(h))
    h._search_listing = CorrectionWindow._search_listing

    async def fake_commit_accept(cluster, entity_id):
        h.commits.append(("accept", cluster, entity_id))
        return {"status": f"accept: {cluster} → x (1 segments)"}
    h._do_commit_accept = fake_commit_accept
    return h


def test_digit_slots_hold_source_then_collection_only():
    h = host()
    menu = h._assign_menu()
    assert [(e, t) for e, _, t in menu] == [("jacob", "src"), ("mark", "src"),
                                            ("jeremy", "coll")]
    # the Nuclear Energy speakers never enter a digit slot
    assert {"ti", "chris", "scott"}.isdisjoint({e for e, _, _ in h._assign_digits()})
    assert h._assign_context() == ("speakers: 1:Jacob Hemstad · 2:Mark Saroufim"
                                   " │ collection: 3:Jeremy Howard · A search/new")


def test_context_line_unfiled_source_and_overflow():
    h = host(_picker_scope={"collections": [], "siblings": {}, "entity_sources": {},
                            "source_collections": {}})
    assert h._assign_context() == "speakers: 1:Jacob Hemstad · 2:Mark Saroufim · A search/new"
    many = host(_picker_scope={"collections": [], "siblings": {}, "entity_sources": {},
                               "source_collections": {}})
    many._entities = [_ent(f"e{i}", f"Person {i}") for i in range(12)]
    many.view.speakers = {f"s{i}": {"entity_id": f"e{i}"} for i in range(12)}
    many.view.segments = [seg(i, f"s{i}") for i in range(12)]
    ctx = many._assign_context()
    assert "9:Person 8" in ctx and "10:" not in ctx and "+3 more" in ctx


def test_submit_search_one_match_commits_with_tier_provenance(monkeypatch):
    import cjm_transcript_correction_qt.app as mod

    async def fake_assign(queue, graph_id, source_id, ids, entity_id, session_id, **kw):
        return f"corr-{entity_id}"
    monkeypatch.setattr(mod, "commit_speaker_assign_correction", fake_assign)
    h = host()
    res = asyncio.run(h._do_submit_assign("morse"))
    assert res["advance"] == 1
    assert res["status"] == "@ #2 → Ti Morse (registry · seen in Nuclear Energy)"
    assert h._recent_entities == ["ti"]
    # a collection-tier pick says so; a source-tier pick reads bare
    assert asyncio.run(h._do_submit_assign("jer"))["status"].endswith("Jeremy Howard (collection)")
    assert asyncio.run(h._do_submit_assign("1"))["status"] == "@ #2 → Jacob Hemstad"


def test_submit_search_several_matches_pin_a_digit_listing(monkeypatch):
    import cjm_transcript_correction_qt.app as mod

    async def fake_assign(queue, graph_id, source_id, ids, entity_id, session_id, **kw):
        return "corr"
    monkeypatch.setattr(mod, "commit_speaker_assign_correction", fake_assign)
    h = host()
    res = asyncio.run(h._do_submit_assign("j"))
    assert res["editor"] == ("assign", "")
    assert res["status"].startswith("2 matches for 'j': 1:Jacob Hemstad [src] · 2:Jeremy Howard [coll]")
    assert [e for e, _, _ in h._assign_pinned] == ["jacob", "jeremy"]
    # a bare digit now picks from the PINNED listing, not the digit menu
    res = asyncio.run(h._do_submit_assign("2"))
    assert res["status"].endswith("Jeremy Howard (collection)")
    assert h._assign_pinned == []


def test_submit_no_match_mints_and_exact_provisional_reuses(monkeypatch):
    import cjm_transcript_correction_qt.app as mod
    minted = []

    async def fake_assign(queue, graph_id, source_id, ids, entity_id, session_id, **kw):
        return "corr"

    async def fake_mint(queue, graph_id, name, session_id, *, provisional, actor, journal_path):
        minted.append((name, provisional))
        return "new-1"
    monkeypatch.setattr(mod, "commit_speaker_assign_correction", fake_assign)
    monkeypatch.setattr(mod, "commit_speaker_entity", fake_mint)
    h = host()
    # a distinct full name that shares a first name mints, never resolves to Mark Saroufim
    res = asyncio.run(h._do_submit_assign("Mark Chen"))
    assert minted == [("Mark Chen", False)] and res["status"].endswith("Mark Chen (new)")
    assert h._entities[-1]["id"] == "new-1"
    # the provisional grammar never searches: "? HH" mints a provisional handle
    asyncio.run(h._do_submit_assign("? HH montage narrator"))
    assert minted[-1] == ("HH montage narrator", True)
    # typing an existing name exactly reuses it (search not consulted)
    assert asyncio.run(h._do_submit_assign("mark saroufim"))["status"] == "@ #2 → Mark Saroufim"
    assert len(minted) == 2


def test_live_narrowing_helper_lists_tier_tagged_matches():
    h = host()
    h._on_editor_text_changed("j")
    assert h._editor_helper == ("search 'j': 1:Jacob Hemstad [src] · 2:Jeremy Howard [coll]"
                                " · Enter = digit list")
    h._on_editor_text_changed("morse")
    assert h._editor_helper == "search 'morse': 1:Ti Morse [reg] · Enter picks it"
    h._on_editor_text_changed("zzz")
    assert h._editor_helper == "search 'zzz': no match · Enter mints 'zzz'"
    h._on_editor_text_changed("")
    assert h._editor_helper.startswith("speaker: type to search the registry")
    # a pinned listing survives a bare digit and dies on new text
    h._assign_pinned = [("ti", "Ti Morse", "reg")]
    h._on_editor_text_changed("1")
    assert h._editor_helper.startswith("pick: 1:Ti Morse [reg]")
    h._on_editor_text_changed("sc")
    assert h._assign_pinned == [] and "Scott Nolan" in h._editor_helper
    # other editor modes are untouched
    h._input_mode = "edit"
    h._editor_helper = "keep"
    h._on_editor_text_changed("anything")
    assert h._editor_helper == "keep"


def test_accept_hop_carries_provenance_and_recents():
    h = host(_accept_cluster="S01")
    res = asyncio.run(h._do_commit_assign("jeremy", via="coll"))
    assert h.commits == [("accept", "S01", "jeremy")]
    assert res["status"].endswith("(collection)")
    assert h._accept_cluster is None


def test_session_picker_scope_resolves_collection_tier_and_degrades(monkeypatch):
    import cjm_transcript_correction_qt.session as mod

    async def fake_siblings(queue, graph_id, source_id):
        assert source_id == "lecture"
        return {"collections": [{"id": "c", "title": "GPU MODE", "status": "confirmed"}],
                "siblings": {"l1": "Lecture 1"}}

    async def fake_sources(queue, graph_id, source_ids):
        assert source_ids is None          # the whole registry's placements (seen-in readout)
        return {"mark": ["lecture", "l1"], "ti": ["nuke-1"]}

    async def fake_list(queue, graph_id):
        return [{"id": "c", "title": "GPU MODE", "status": "confirmed"},
                {"id": "n", "title": "Nuclear Energy", "status": "confirmed"},
                {"id": "old", "title": "GPU MODE_OLD", "status": "retired"}]

    async def fake_members(queue, graph_id, coll_id):
        assert coll_id != "old"
        return {"c": [("lecture", "Bonus"), ("l1", "Lecture 1")],
                "n": [("nuke-1", "Power")]}[coll_id]

    monkeypatch.setattr(mod, "sibling_sources", fake_siblings)
    monkeypatch.setattr(mod, "speaker_assignment_sources", fake_sources)
    monkeypatch.setattr(mod, "list_collections", fake_list)
    monkeypatch.setattr(mod, "collection_members", fake_members)
    sess = CorrectionShellSession.__new__(CorrectionShellSession)
    sess.queue, sess.graph_capability = object(), "graph"
    view = SimpleNamespace(queue=object(), graph_id="g")
    scope = asyncio.run(sess._picker_scope(view, "lecture"))
    assert scope["siblings"] == {"l1": "Lecture 1"}
    assert scope["entity_sources"] == {"mark": ["lecture", "l1"], "ti": ["nuke-1"]}
    assert scope["source_collections"] == {"lecture": ["GPU MODE"], "l1": ["GPU MODE"],
                                           "nuke-1": ["Nuclear Energy"]}

    async def boom(queue, graph_id, source_id):
        raise RuntimeError("graph read failed")
    monkeypatch.setattr(mod, "sibling_sources", boom)
    assert asyncio.run(sess._picker_scope(view, "lecture")) == \
        CorrectionShellSession.empty_picker_scope()
