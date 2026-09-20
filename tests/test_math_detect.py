from polyglotpdf.analysis.fonts import is_math_font, is_tex_text_font, style_from_font
from polyglotpdf.analysis.math_detect import MathDetector
from polyglotpdf.model import CharKind, DocumentStats, FontFamily

from .conftest import make_block, make_line

TIMES_BODY = DocumentStats(body_size=10.0, body_font="nimbusromno9l", tex_body=False)
TEX_BODY = DocumentStats(body_size=10.0, body_font="cmr", tex_body=True)


def run_texts(block) -> list[str]:  # type: ignore[no-untyped-def]
    return ["".join(ch.c for ch in run) for run in block.runs.values()]


def test_font_classification() -> None:
    assert is_math_font("ABCDEF+CMMI10")
    assert is_math_font("CMSY7") and is_math_font("MSBM10") and is_math_font("Cambria Math")
    assert not is_math_font("CMR10") and not is_math_font("Times-Roman")
    assert is_tex_text_font("CMR10") and is_tex_text_font("CMBX12")
    assert style_from_font("NimbusRomNo9L-Medi", 20).bold
    assert style_from_font("NimbusRomNo9L-ReguItal", 6).italic
    assert style_from_font("Courier", 0).family is FontFamily.MONO
    assert style_from_font("Helvetica-Bold", 16).family is FontFamily.SANS


def test_math_font_run_with_glued_brackets() -> None:
    block = make_block(
        [
            make_line(
                [("Let ", "Times-Roman"), ("H", "CMSY10"), ("(x)", "CMR10"), (" be", "Times-Roman")]
            )
        ]
    )
    MathDetector(TIMES_BODY).annotate(block)
    assert run_texts(block) == ["H(x)"]
    assert all(ch.kind is CharKind.TEXT for ch in block.chars if ch.c.isalpha() and ch.run < 0)


def test_computer_modern_text_is_prose_in_tex_documents() -> None:
    block = make_block([make_line([("Let ", "CMR10"), ("x", "CMMI10"), (" be", "CMR10")])])
    MathDetector(TEX_BODY).annotate(block)
    assert run_texts(block) == ["x"]


def test_superscript_marker_is_a_script_run_without_trailing_comma() -> None:
    line = make_line(
        [
            ("functions", "Times-Roman"),
            ("2", "Times-Roman", {"size": 7.0, "baseline": 96.4, "flags": 5}),
            (", then", "Times-Roman"),
        ]
    )
    block = make_block([line])
    MathDetector(TIMES_BODY).annotate(block)
    assert run_texts(block) == ["2"]
    assert block.runs[0][0].kind is CharKind.SCRIPT


def test_bridges_neutral_gaps_between_formulas() -> None:
    block = make_block(
        [
            make_line(
                [
                    ("for ", "Times-Roman"),
                    ("x", "CMMI10"),
                    (", ", "Times-Roman"),
                    ("y", "CMMI10"),
                    (" and more", "Times-Roman"),
                ]
            )
        ]
    )
    MathDetector(TIMES_BODY).annotate(block)
    assert run_texts(block) == ["x, y"]


def test_unicode_operator_absorbs_digits() -> None:
    block = make_block([make_line([("filters of 3×3 size", "Times-Roman")])])
    MathDetector(TIMES_BODY).annotate(block)
    assert run_texts(block) == ["3×3"]


def test_greek_letters_in_text_fonts() -> None:
    block = make_block([make_line([("the α parameter", "Times-Roman")])])
    MathDetector(TIMES_BODY).annotate(block)
    assert run_texts(block) == ["α"]
    block = make_block([make_line([("the α parameter", "Times-Roman")])])
    MathDetector(TIMES_BODY, greek_is_math=False).annotate(block)
    assert run_texts(block) == []


def test_plain_prose_has_no_runs() -> None:
    block = make_block([make_line([("Eqn.(1) shows it, e.g. over 100 layers.", "Times-Roman")])])
    MathDetector(TIMES_BODY).annotate(block)
    assert block.runs == {}
