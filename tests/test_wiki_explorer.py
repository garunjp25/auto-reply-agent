import json
from pathlib import Path
from unittest.mock import MagicMock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from auto_reply.pipeline.wiki_qa import Citation, WikiAnswer
from auto_reply.web.wiki_explorer import make_router


def _app(*, wiki_dir: Path, graph_path: Path, wiki_qa) -> FastAPI:
    app = FastAPI()
    app.include_router(
        make_router(wiki_dir=wiki_dir, graph_path=graph_path, wiki_qa=wiki_qa)
    )
    return app


def _seed_wiki(tmp_path: Path) -> Path:
    wiki = tmp_path / "wiki"
    wiki.mkdir()
    (wiki / "emailpilot.md").write_text("# EmailPilot\n\nEmail tool.\n", encoding="utf-8")
    (wiki / "invoiceflow.md").write_text("# InvoiceFlow\n\nInvoicing.\n", encoding="utf-8")
    return wiki


def _seed_graph(tmp_path: Path) -> Path:
    g = tmp_path / "wiki_graph.json"
    g.write_text(json.dumps({
        "nodes": [
            {"id": "emailpilot", "label": "EmailPilot", "tagline": "email tool", "summary": "s"},
            {"id": "invoiceflow", "label": "InvoiceFlow", "tagline": "invoicing", "summary": "s"},
        ],
        "edges": [
            {"source": "emailpilot", "target": "invoiceflow", "relation": "shared_audience", "reason": "x"},
        ],
    }), encoding="utf-8")
    return g


def test_get_html_returns_200(tmp_path: Path):
    wiki = _seed_wiki(tmp_path)
    graph = _seed_graph(tmp_path)
    qa = MagicMock()
    client = TestClient(_app(wiki_dir=wiki, graph_path=graph, wiki_qa=qa))
    r = client.get("/wiki")
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]
    assert "LumenX" in r.text or "Wiki Explorer" in r.text


def test_get_graph_json_returns_graph(tmp_path: Path):
    wiki = _seed_wiki(tmp_path)
    graph = _seed_graph(tmp_path)
    qa = MagicMock()
    client = TestClient(_app(wiki_dir=wiki, graph_path=graph, wiki_qa=qa))
    r = client.get("/wiki/graph.json")
    assert r.status_code == 200
    body = r.json()
    # Two product nodes from the seed + one synthetic LumenX hub.
    assert len(body["nodes"]) == 3
    node_ids = {n["id"] for n in body["nodes"]}
    assert node_ids == {"lumenx", "emailpilot", "invoiceflow"}
    # Edges: 1 seed + 2 hub spokes (lumenx → each product).
    assert len(body["edges"]) >= 3
    assert all("category" in n for n in body["nodes"])


def test_get_graph_json_503_when_not_built(tmp_path: Path):
    wiki = _seed_wiki(tmp_path)
    missing_graph = tmp_path / "missing.json"
    qa = MagicMock()
    client = TestClient(_app(wiki_dir=wiki, graph_path=missing_graph, wiki_qa=qa))
    r = client.get("/wiki/graph.json")
    assert r.status_code == 503
    assert "graph not built" in r.json()["error"]


def test_get_doc_returns_markdown(tmp_path: Path):
    wiki = _seed_wiki(tmp_path)
    graph = _seed_graph(tmp_path)
    qa = MagicMock()
    client = TestClient(_app(wiki_dir=wiki, graph_path=graph, wiki_qa=qa))
    r = client.get("/wiki/doc/emailpilot")
    assert r.status_code == 200
    body = r.json()
    assert body["product_id"] == "emailpilot"
    assert "Email tool" in body["markdown"]


def test_get_doc_404_for_unknown(tmp_path: Path):
    wiki = _seed_wiki(tmp_path)
    graph = _seed_graph(tmp_path)
    qa = MagicMock()
    client = TestClient(_app(wiki_dir=wiki, graph_path=graph, wiki_qa=qa))
    r = client.get("/wiki/doc/nope")
    assert r.status_code == 404


def test_get_doc_rejects_path_traversal(tmp_path: Path):
    wiki = _seed_wiki(tmp_path)
    graph = _seed_graph(tmp_path)
    qa = MagicMock()
    client = TestClient(_app(wiki_dir=wiki, graph_path=graph, wiki_qa=qa))
    r = client.get("/wiki/doc/..%2Fconftest")
    assert r.status_code in (404, 422)


def test_get_doc_appends_related_products(tmp_path: Path):
    wiki = _seed_wiki(tmp_path)
    graph = _seed_graph(tmp_path)
    qa = MagicMock()
    client = TestClient(_app(wiki_dir=wiki, graph_path=graph, wiki_qa=qa))
    r = client.get("/wiki/doc/emailpilot")
    assert r.status_code == 200
    body = r.json()
    assert "Related Products" in body["markdown"]
    assert "(product:invoiceflow)" in body["markdown"]
    assert any(rel["id"] == "invoiceflow" for rel in body["related"])


def test_get_doc_related_empty_when_graph_missing(tmp_path: Path):
    wiki = _seed_wiki(tmp_path)
    missing_graph = tmp_path / "missing.json"
    qa = MagicMock()
    client = TestClient(_app(wiki_dir=wiki, graph_path=missing_graph, wiki_qa=qa))
    r = client.get("/wiki/doc/emailpilot")
    assert r.status_code == 200
    body = r.json()
    assert body["related"] == []
    assert "Email tool" in body["markdown"]
    assert "Related Products" not in body["markdown"]


def test_post_ask_returns_answer(tmp_path: Path):
    wiki = _seed_wiki(tmp_path)
    graph = _seed_graph(tmp_path)
    qa = MagicMock()
    qa.ask.return_value = WikiAnswer(
        answer_markdown="EmailPilot is an email tool [1].",
        citations=[Citation(n=1, product_id="emailpilot", quote="email tool")],
    )
    client = TestClient(_app(wiki_dir=wiki, graph_path=graph, wiki_qa=qa))
    r = client.post("/wiki/ask", json={"question": "what is emailpilot"})
    assert r.status_code == 200
    body = r.json()
    assert body["answer_markdown"].startswith("EmailPilot")
    assert body["citations"] == [
        {"n": 1, "product_id": "emailpilot", "quote": "email tool"}
    ]
    qa.ask.assert_called_once_with("what is emailpilot")


def test_post_ask_rejects_empty_question(tmp_path: Path):
    wiki = _seed_wiki(tmp_path)
    graph = _seed_graph(tmp_path)
    qa = MagicMock()
    client = TestClient(_app(wiki_dir=wiki, graph_path=graph, wiki_qa=qa))
    r = client.post("/wiki/ask", json={"question": "   "})
    assert r.status_code == 400
