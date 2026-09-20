from polyglotpdf.segmentation import markup as m


def test_parse_styles_and_placeholders() -> None:
    tokens = m.parse("Seja <b>{v1}</b> um <i>vetor</i> e {v2}.")
    assert tokens == [
        m.TextRun("Seja "),
        m.PlaceholderRef(1),
        m.TextRun(" um "),
        m.TextRun("vetor", italic=True),
        m.TextRun(" e "),
        m.PlaceholderRef(2),
        m.TextRun("."),
    ]


def test_parse_tolerates_spacing_and_case_in_placeholders() -> None:
    assert m.parse("a { V3 } b") == [m.TextRun("a "), m.PlaceholderRef(3), m.TextRun(" b")]


def test_parse_ignores_unbalanced_tags() -> None:
    assert m.parse("</i>x<b>y") == [m.TextRun("x"), m.TextRun("y", bold=True)]


def test_nested_tags() -> None:
    assert m.parse("<b>a <i>b</i></b>") == [
        m.TextRun("a ", bold=True),
        m.TextRun("b", bold=True, italic=True),
    ]


def test_validate_reports_every_problem() -> None:
    result = m.validate("{v1} {v1} {v3}", {1, 2})
    assert not result.ok
    assert result.missing == {2}
    assert result.duplicated == {1}
    assert result.unexpected == {3}


def test_repair_normalises_and_drops_extras() -> None:
    assert m.repair("a {v1} b { v1 } c {v9}", {1}) == "a {v1} b c"


def test_repair_rejects_lost_placeholders_and_empty_text() -> None:
    assert m.repair("sem nada", {1}) is None
    assert m.repair("   ", set()) is None
    assert m.repair("ok", set()) == "ok"


def test_repair_removes_invisible_characters() -> None:
    assert m.repair("a​ {v1}﻿ b", {1}) == "a {v1} b"


def test_visible_text() -> None:
    assert m.visible_text("<b>{v1}</b> x") == "x"


def test_monospace_tag() -> None:
    assert m.parse("call <c>np.zeros</c> now") == [
        m.TextRun("call "),
        m.TextRun("np.zeros", mono=True),
        m.TextRun(" now"),
    ]
    assert m.strip_tags("<C>x</C>") == "x"
