from unittest.mock import MagicMock

from auto_reply.llm.client import LLMClient
from auto_reply.pipeline.wiki_qa import Citation, WikiAnswer, WikiQA


def _make_llm(db, body_text: str) -> LLMClient:
    sdk = MagicMock()
    resp = MagicMock()
    resp.id = "msg_qa"
    resp.usage.input_tokens = 1000
    resp.usage.output_tokens = 80
    resp.usage.cache_read_input_tokens = 800
    resp.usage.cache_creation_input_tokens = 0
    resp.content = [MagicMock(text=body_text)]
    sdk.messages.create.return_value = resp
    return LLMClient(sdk=sdk, conn=db)


_WIKI = {
    "emailpilot": "# EmailPilot\nAn AI email tool. Pro is $25/mo.",
    "invoiceflow": "# InvoiceFlow\nInvoicing. Pro is $15/mo.",
}


def test_ask_returns_typed_answer_with_citations(db):
    json_body = (
        '{"answer_markdown": "EmailPilot Pro is $25/mo [1] and InvoiceFlow Pro is $15/mo [2].",'
        ' "citations": ['
        '   {"n": 1, "product_id": "emailpilot", "quote": "Pro is $25/mo."},'
        '   {"n": 2, "product_id": "invoiceflow", "quote": "Pro is $15/mo."}'
        ' ]}'
    )
    llm = _make_llm(db, json_body)
    qa = WikiQA(llm=llm, wiki_docs=_WIKI)
    out = qa.ask("how much is the pro tier for the email tool and the invoice tool?")
    assert isinstance(out, WikiAnswer)
    assert "[1]" in out.answer_markdown and "[2]" in out.answer_markdown
    assert len(out.citations) == 2
    assert out.citations[0] == Citation(n=1, product_id="emailpilot", quote="Pro is $25/mo.")
    assert out.citations[1].product_id == "invoiceflow"


def test_ask_writes_cost_row_with_purpose_wiki_qa(db):
    json_body = '{"answer_markdown": "no idea", "citations": []}'
    llm = _make_llm(db, json_body)
    qa = WikiQA(llm=llm, wiki_docs=_WIKI)
    qa.ask("anything")
    rows = db.execute("SELECT purpose, model FROM cost_log").fetchall()
    assert len(rows) == 1
    assert rows[0]["purpose"] == "wiki_qa"
    assert rows[0]["model"] == "claude-sonnet-4-6"


def test_ask_drops_citations_pointing_to_unknown_product(db):
    json_body = (
        '{"answer_markdown": "ok [1] [2]",'
        ' "citations": ['
        '   {"n": 1, "product_id": "emailpilot", "quote": "x"},'
        '   {"n": 2, "product_id": "nonexistent", "quote": "y"}'
        ' ]}'
    )
    llm = _make_llm(db, json_body)
    qa = WikiQA(llm=llm, wiki_docs=_WIKI)
    out = qa.ask("q")
    ids = [c.product_id for c in out.citations]
    assert "emailpilot" in ids
    assert "nonexistent" not in ids


def test_ask_falls_back_gracefully_on_bad_json(db):
    llm = _make_llm(db, "not JSON at all")
    qa = WikiQA(llm=llm, wiki_docs=_WIKI)
    out = qa.ask("q")
    assert "trouble" in out.answer_markdown.lower() or "rephras" in out.answer_markdown.lower()
    assert out.citations == []


def test_ask_passes_cacheable_wiki_to_llm(db):
    json_body = '{"answer_markdown": "a", "citations": []}'
    llm = _make_llm(db, json_body)
    qa = WikiQA(llm=llm, wiki_docs=_WIKI)
    qa.ask("q")
    call = llm.sdk.messages.create.call_args
    system = call.kwargs["system"]
    assert isinstance(system, list)
    cache_blocks = [b for b in system if b.get("cache_control") == {"type": "ephemeral"}]
    assert len(cache_blocks) >= 1
    cached_text = cache_blocks[-1]["text"]
    assert "EmailPilot" in cached_text
    assert "InvoiceFlow" in cached_text


def test_ask_strips_markdown_code_fences_from_json(db):
    json_body = (
        '```json\n'
        '{"answer_markdown": "ok [1]", "citations": [{"n":1, "product_id":"emailpilot", "quote":"q"}]}\n'
        '```'
    )
    llm = _make_llm(db, json_body)
    qa = WikiQA(llm=llm, wiki_docs=_WIKI)
    out = qa.ask("q")
    assert len(out.citations) == 1
    assert out.citations[0].product_id == "emailpilot"
