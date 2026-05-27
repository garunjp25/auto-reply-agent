import numpy as np

from auto_reply.sources.wiki_store import WikiChunk, WikiStore


def test_save_and_search_returns_top_k(db):
    store = WikiStore(db)
    v_a = np.array([1.0, 0.0, 0.0], dtype=np.float32)
    v_b = np.array([0.0, 1.0, 0.0], dtype=np.float32)
    v_c = np.array([0.9, 0.1, 0.0], dtype=np.float32)
    v_c /= np.linalg.norm(v_c)

    store.save_chunks([
        WikiChunk(product_id="p1", chunk_id=0, text="apples", embedding=v_a),
        WikiChunk(product_id="p2", chunk_id=0, text="bananas", embedding=v_b),
        WikiChunk(product_id="p1", chunk_id=1, text="apple pie", embedding=v_c),
    ])

    query = v_a
    hits = store.top_k(query, k=2)
    texts = [h.text for h in hits]
    assert "apples" in texts
    assert "apple pie" in texts
    assert "bananas" not in texts


def test_replace_product_chunks_is_idempotent(db):
    store = WikiStore(db)
    v = np.array([1.0, 0.0], dtype=np.float32)
    store.save_chunks([
        WikiChunk(product_id="p1", chunk_id=0, text="old", embedding=v),
    ])
    store.replace_product("p1", [
        WikiChunk(product_id="p1", chunk_id=0, text="new", embedding=v),
        WikiChunk(product_id="p1", chunk_id=1, text="also new", embedding=v),
    ])
    rows = db.execute(
        "SELECT text FROM wiki_index WHERE product_id='p1' ORDER BY chunk_id"
    ).fetchall()
    assert [r["text"] for r in rows] == ["new", "also new"]


def test_top_k_handles_empty_store(db):
    store = WikiStore(db)
    query = np.array([1.0, 0.0, 0.0], dtype=np.float32)
    hits = store.top_k(query, k=3)
    assert hits == []
