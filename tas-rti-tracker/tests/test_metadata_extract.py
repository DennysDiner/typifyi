from make_pdf import simple_pdf

from rti_tracker.extract import extract
from rti_tracker.metadata import FIELDS, normalise_citations, run_metadata, validate


def test_extract_pdf_and_html():
    r = extract(simple_pdf(["Decision under the Right to Information Act", "s 35 applied"]), "application/pdf")
    assert "s 35 applied" in r["text"] and r["pages"] == 1 and r["method"].startswith("pypdf")
    h = extract(b"<html><body><main><p>Hello RTI</p></main><script>x()</script></body></html>", "text/html")
    assert h["text"].strip() == "Hello RTI"


def test_validate_marks_unsupported_fields_unverified():
    text = "Decision letter. Reference RTI 2026-27/012. Decided on 14 August 2026. Exempt under s 37(1)(b) and s 39. 12 pages released."
    ok, _ = validate("reference", "RTI 2026-27/012", None, text, {35, 37, 39})
    assert ok
    ok, _ = validate("decision_date", "2026-08-14", "Decided on 14 August 2026", text, {35, 37, 39})
    assert ok
    ok, note = validate("decision_date", "2026-08-15", "Decided on 14 August 2026", text, {35, 37, 39})
    assert not ok
    ok, _ = validate("exemptions_cited", ["s 37(1)(b)", "s 39"], None, text, {35, 37, 39})
    assert ok
    ok, note = validate("exemptions_cited", ["s 35"], None, text, {35, 37, 39})
    assert not ok and "s 35" in note
    ok, _ = validate("pages_released", 12, "12 pages released", text, {35})
    assert ok
    ok, _ = validate("pages_released", 13, "12 pages released", text, {35})
    assert not ok
    ok, _ = validate("request_subject", "something the model made up", "not in the text at all", text, {35})
    assert not ok


def test_normalise_citations_excludes_s33():
    assert normalise_citations("s 33 and s 35", {35}) == ["s 35"]


def test_run_metadata_with_fake_llm(conn, archive):
    import yaml
    with open("legal/rules.yaml") as f:
        rules = yaml.safe_load(f)
    cap = archive.store(b"x", url="https://x/d.pdf", content_type="application/pdf", headers={}, http_status=200)
    conn.execute("INSERT INTO documents(url,sha256,capture_id,first_seen_at,text_chars) VALUES ('https://x/d.pdf',?,?,'t',100)", (cap.sha256, cap.id))
    doc_id = conn.execute("SELECT id FROM documents").fetchone()[0]
    conn.execute("INSERT INTO document_text(document_id,text) VALUES (?,?)", (doc_id, "Reference RTI-1. Refused under s 35. Decision 3 March 2026."))

    def fake(text, model, key):
        return {"reference": {"value": "RTI-1", "quote": "Reference RTI-1"}, "decision_type": {"value": "refused", "quote": "Refused under s 35"},
                "exemptions_cited": {"value": ["s35"], "quote": None}, "decision_date": {"value": "2026-03-03", "quote": "Decision 3 March 2026"},
                "pages_released": {"value": 40, "quote": "40 pages"}, "request_subject": {"value": "x", "quote": None}, "applicant_type": {"value": None, "quote": None}, "pages_withheld": {"value": None, "quote": None}}

    assert run_metadata(conn, rules, llm=fake, model="fake") == 1
    rows = {r["field"]: r for r in conn.execute("SELECT * FROM document_metadata")}
    assert set(rows) == set(FIELDS)
    assert rows["reference"]["verified"] == 1 and rows["decision_type"]["verified"] == 1 and rows["decision_date"]["verified"] == 1
    assert rows["exemptions_cited"]["verified"] == 1 and rows["exemptions_cited"]["value"] == '["s 35"]'
    assert rows["pages_released"]["verified"] == 0 and rows["request_subject"]["verified"] == 0
    assert rows["applicant_type"]["verified"] == 0
