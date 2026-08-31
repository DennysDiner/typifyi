"""Normalisation is the most important code in the project (§2.3, §7)."""

from __future__ import annotations

from conftest import fixture_text

from tnw.hashing import sha256_text
from tnw.normalise import canonical_url, html_to_text, normalise_html_for_hash, normalise_text


def test_two_fetches_differing_only_in_volatile_content_hash_identically():
    a = fixture_text("normalise", "page-fetch-a.html")
    b = fixture_text("normalise", "page-fetch-b.html")
    assert a != b, "the fixtures must actually differ"
    assert sha256_text(normalise_html_for_hash(a)) == sha256_text(normalise_html_for_hash(b))


def test_a_real_content_change_still_changes_the_hash():
    a = fixture_text("normalise", "page-fetch-a.html")
    c = fixture_text("normalise", "page-fetch-c-real-change.html")
    assert sha256_text(normalise_html_for_hash(a)) != sha256_text(normalise_html_for_hash(c))
    assert "24 September 2026" in normalise_html_for_hash(c)


def test_normalised_text_keeps_content_and_drops_chrome():
    text = normalise_html_for_hash(fixture_text("normalise", "page-fetch-a.html"))
    assert "Road maintenance services" in text
    assert "17 September 2026" in text
    assert "supplier expo" not in text  # ad slot
    assert "0.184 seconds" not in text  # render duration
    assert "1,204,551" not in text  # visitor counter
    assert "window.__boot" not in text  # script


def test_canonical_url_drops_session_and_cache_busting_parameters():
    assert canonical_url(
        "HTTPS://WWW.Tenders.TAS.gov.au:443/Tender/View/48211?b=2&a=1&sessionid=zz&_=1756600000#top"
    ) == "https://www.tenders.tas.gov.au/Tender/View/48211?a=1&b=2"


def test_canonical_url_preserves_path_case_and_meaningful_query():
    assert canonical_url("https://x.tas.gov.au/Tender/List?page=2") == (
        "https://x.tas.gov.au/Tender/List?page=2"
    )


def test_canonical_url_strips_path_session_parameters():
    assert canonical_url("https://x.tas.gov.au/a/b;jsessionid=AB12?q=1") == (
        "https://x.tas.gov.au/a/b?q=1"
    )


def test_normalise_text_folds_whitespace_but_not_characters():
    assert normalise_text("A  b\r\nc \n\n\n d ") == "A b\nc\n\nd"
    # NFKC would turn ½ into 1/2 and ﬁ into fi; amounts and names must survive.
    assert normalise_text("½ ﬁnal") == "½ ﬁnal"


def test_soft_hyphens_from_pdf_extraction_are_removed():
    assert normalise_text("Nyr­star") == "Nyrstar"


def test_html_to_text_handles_empty_and_malformed_input():
    assert html_to_text("") == ""
    assert "hello" in html_to_text("<p>hello<b>")
