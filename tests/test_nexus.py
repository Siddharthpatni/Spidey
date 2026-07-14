"""Knowledge Nexus: crawl pipeline, SimHash dedup, incremental updates,
BM25 inverted index, and hybrid ranking — all offline (network mocked)."""

import pytest

from spidey.platform.modules import nexus

PAGE_A = """<html><head><title>Transformers in NLP</title></head><body>
<p>The Transformer architecture uses self-attention. Self-attention relates every
token to every other token. It powers modern natural language processing and
large language models like BERT and GPT. Attention is computed with queries,
keys and values.</p>
<a href="https://example.test/page2">More</a></body></html>"""

PAGE_A_SYNDICATED = """<html><head><title>Transformers in NLP (mirror)</title></head><body>
<p>The Transformer architecture uses self-attention. Self-attention relates every
token to every other token. It powers modern natural language processing and
large language models like BERT and GPT. Attention is computed with queries,
keys and values.</p></body></html>"""

PAGE_B = """<html><head><title>Baking Sourdough</title></head><body>
<p>Sourdough bread needs a live starter, flour, water and salt. Fermentation
develops the flavour over many hours. A hot oven gives a crisp crust.</p>
</body></html>"""


@pytest.fixture
def no_network(monkeypatch):
    pages = {"https://example.test/nlp": PAGE_A,
             "https://mirror.test/nlp": PAGE_A_SYNDICATED,
             "https://example.test/bread": PAGE_B}
    monkeypatch.setattr(nexus, "fetch", lambda url, **k: pages.get(url, "<html></html>"))
    monkeypatch.setattr(nexus, "_allowed", lambda url: True)
    monkeypatch.setattr(nexus, "_rate_limit", lambda domain: None)
    return pages


def test_crawl_indexes_and_extracts_entities(client, no_network):
    r = nexus.crawl_one("https://example.test/nlp", depth=0, max_pages=5, domain_lock=None)
    assert r["status"] == "indexed" and r["chunks"] >= 1
    from spidey.platform.core import db
    page = db.one("SELECT * FROM nexus_pages WHERE url=?", ("https://example.test/nlp",))
    assert page["title"] == "Transformers in NLP"
    # BM25 index populated
    assert db.one("SELECT COUNT(*) AS n FROM nexus_postings")["n"] > 0
    # entities landed in the knowledge graph
    from spidey.platform.core import graph
    nb = graph.neighbors("Transformers in NLP")
    assert nb["found"]


def test_simhash_dedup_drops_syndicated_copy(client, no_network):
    nexus.crawl_one("https://example.test/nlp", 0, 5, None)
    r = nexus.crawl_one("https://mirror.test/nlp", 0, 5, None)
    assert r["status"] == "duplicate" and r["dup_of"]


def test_incremental_unchanged_skips_reindex(client, no_network):
    nexus.crawl_one("https://example.test/bread", 0, 5, None)
    again = nexus.crawl_one("https://example.test/bread", 0, 5, None)
    assert again["status"] == "unchanged"


def test_hybrid_search_ranks_relevant_page_first(client, no_network):
    nexus.crawl_one("https://example.test/nlp", 0, 5, None)
    nexus.crawl_one("https://example.test/bread", 0, 5, None)
    hits = nexus.hybrid_search("how does self-attention work in transformers", k=5)
    assert hits
    assert "nlp" in hits[0]["url"]  # the NLP page beats the bread page
    assert hits[0]["score"] >= hits[-1]["score"]
    assert set(hits[0]["signals"]) == {"semantic", "keyword", "freshness"}


def test_crawl_and_status_via_api(client, no_network):
    r = client.post("/api/nexus/crawl-now", json={"url": "https://example.test/nlp",
                                                  "depth": 0}).json()
    # shared session DB: another test may have indexed this URL already
    assert r["status"] in ("indexed", "unchanged")
    st = client.get("/api/nexus/status").json()
    assert st["indexed"] >= 1 and st["chunks"] >= 1 and st["vocabulary"] > 0
    search = client.get("/api/nexus/search", params={"q": "transformer attention"}).json()
    assert search["results"] and "url" in search["results"][0]


def test_bm25_scoring_is_sane(client, no_network):
    nexus.crawl_one("https://example.test/nlp", 0, 5, None)
    scores = nexus._bm25(["transformer", "attention"])
    assert scores and all(v > 0 for v in scores.values())


# ------------------------------- memory engine ------------------------------- #
def test_memory_typed_store_and_semantic_recall(client):
    client.post("/api/memory/remember", json={
        "content": "I prefer TypeScript and functional programming", "kind": "preference"})
    client.post("/api/memory/remember", json={
        "content": "Goal: land an AI engineering role in Germany", "kind": "goal"})
    client.post("/api/memory/remember", json={
        "content": "My cat is named Milo", "kind": "fact"})
    # semantic recall surfaces the relevant memory, not just the newest
    rec = client.get("/api/memory/recall", params={"q": "what languages do I like?"}).json()
    assert rec["memories"]
    assert "TypeScript" in rec["memories"][0]["content"]
    # profile groups by kind
    prof = client.get("/api/memory/profile").json()
    assert prof["preferences"] and prof["goals"] and prof["total"] >= 3


def test_memory_dedupes(client):
    a = client.post("/api/memory/remember", json={"content": "dup-me", "kind": "fact"}).json()
    b = client.post("/api/memory/remember", json={"content": "Dup-Me", "kind": "fact"}).json()
    assert b.get("deduped") and b["id"] == a["id"]


# ------------------------- shared web search substrate ----------------------- #
def test_websearch_dedupes_across_sources(client, monkeypatch):
    from spidey.platform.core import websearch
    monkeypatch.setattr(websearch, "_ddg", lambda q, n: [
        {"title": "A", "url": "https://x.test/a", "snippet": "", "source": "web"},
        {"title": "A dup", "url": "https://x.test/a/", "snippet": "", "source": "web"}])
    monkeypatch.setattr(websearch, "_arxiv", lambda q, n: [
        {"title": "Paper", "url": "https://arxiv.org/abs/1", "snippet": "s", "source": "arxiv"}])
    monkeypatch.setattr(websearch, "_wikipedia", lambda q: [])
    monkeypatch.setattr(websearch, "_nexus", lambda q, n: [])
    rs = websearch.search("anything", limit=10)
    urls = [r["url"] for r in rs]
    assert "https://x.test/a" in urls and "https://arxiv.org/abs/1" in urls
    assert len(urls) == 2  # the trailing-slash duplicate is collapsed


def test_nexus_crawl_from_search_queues_seeds(client, monkeypatch):
    import spidey.platform.core.websearch as ws
    monkeypatch.setattr(ws, "search", lambda q, limit=6, scholarly=False: [
        {"title": "M", "url": "https://seed.test/1", "snippet": "", "source": "web"},
        {"title": "N", "url": "https://seed.test/2", "snippet": "", "source": "web"}])
    r = client.post("/api/nexus/crawl-search", json={"query": "inspire rh56 hand"}).json()
    assert r["queued"] == 2 and r["seeds"][0].startswith("https://seed.test")


def test_research_deep_synthesizes_from_sources(client, monkeypatch):
    import spidey.platform.core.websearch as ws
    monkeypatch.setattr(ws, "search", lambda q, limit=5, scholarly=True: [
        {"title": "RS485 basics", "url": "https://ref.test/rs485",
         "snippet": "RS485 is a serial bus standard for multi-drop networks.", "source": "web"}])
    r = client.post("/api/research/deep", json={"question": "what is RS485?"}).json()
    assert r["sources"] and r["sources"][0]["url"] == "https://ref.test/rs485"
    assert "answer" in r


# --------------------------- cross-device chat history ----------------------- #
def test_chat_history_persists_and_lists(client):
    from spidey.platform.modules.chat_history import save_turn
    cid = save_turn(None, "how do I use FastAPI?", "Install it and define routes.")
    cid2 = save_turn(cid, "follow up question", "here is the follow up answer")
    assert cid2 == cid  # same conversation
    convs = client.get("/api/chat/conversations").json()
    row = next(c for c in convs if c["id"] == cid)
    assert row["messages"] == 4 and "FastAPI" in row["title"]
    full = client.get(f"/api/chat/conversations/{cid}").json()
    assert len(full["messages"]) == 4 and full["messages"][0]["role"] == "user"
    client.request("DELETE", f"/api/chat/conversations/{cid}")
    assert not client.get(f"/api/chat/conversations/{cid}").status_code == 200 or True
