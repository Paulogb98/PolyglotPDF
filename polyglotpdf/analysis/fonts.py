"""Font-name heuristics: math fonts, TeX text fonts and text style (family, weight, slant)."""

from __future__ import annotations

import re

from ..model import FontFamily, TextStyle

_SUBSET_PREFIX = re.compile(r"^[A-Z]{6}\+")

# Matched against the compact name: lower case, alphanumerics only ("Cambria Math" -> "cambriamath")
_MATH_FONT = re.compile(
    r"^(?:cmmi|cmsy|cmex|cmbsy|cmmib|cmbrm|cmbrs|msam|msbm|eufm|eufb|eusm|eusb|eurm|eurb|euex|"
    r"rsfs|lmmi|lmsy|lmex|lmmath|latinmodernmath|txmi|txsy|txex|txsym|pxmi|pxsy|pxex|pxsym|"
    r"ntxmi|ntxsy|ntxex|ntxsym|newtxmath|newpxmath|rtxmi|rtxsy|zxmi|zxsy|stixmath|stixtwomath|"
    r"stixsizes|stixintegrals|stixnonunicode|stixvariants|xitsmath|cambriamath|asanamath|"
    r"texgyre\w*math|firamath|libertinusmath|garamondmath|dejavumathtexgyre|mathjax|mnsymbol|"
    r"stmary|wasy|esint|bbm|dsrom|bbold|mtsy|mtmi|mtex|mtextra|mtpro|mathtime|mathematica|"
    r"mathematicalpi|euclidsymbol|euclidmath|symbolmt|symbol$|lucidanewmath|lucidabrightmath)"
)
_TEX_TEXT_FONT = re.compile(
    r"^(?:cmr|cmbx|cmti|cmsl|cmss|cmtt|cmcsc|cmb\d|cmssbx|cmssi|cmssdc|cmfib|cmdunh|cmu|"
    r"lmroman|lmsans|lmmono|lmr|lmbx|lmti|lmss|lmtt|sfrm|sfbx|sfti|sfsl|sfss|sftt|"
    r"ecrm|ecbx|ecti|ecsl|ecss|ectt|tcrm|tcbx)"
)
_BOLD = re.compile(
    r"bold|black|heavy|semibold|demi|medi(?!um)|[-_,.]bd\b|^cmbx|^cmb\d|^lmbx|^cmssbx", re.I
)
_ITALIC = re.compile(r"italic|oblique|ital|kursiv|slanted|[-_,.]it$|^cmti|^cmsl|^lmti", re.I)
_MONO = re.compile(
    r"mono|courier|consol|menlo|inconsolata|typewriter|^cmtt|^lmmono|^lmtt|^sftt|^ectt|txtt|"
    r"sourcecode|firacode|lucidaconsole|andale|nimbusmon|letter ?gothic",
    re.I,
)
_SANS = re.compile(
    r"sans|arial|helvetica|verdana|tahoma|calibri|segoe|gill|futura|frutiger|myriad|univers|"
    r"roboto|lato|trebuchet|nimbussan|avenir|franklin|century ?gothic|^cmss|^lmss|^sfss|^ecss",
    re.I,
)


def normalize_font_name(name: str) -> str:
    """Strip the subset prefix (``ABCDEF+Times-Roman`` -> ``Times-Roman``)."""
    return _SUBSET_PREFIX.sub("", name or "")


def _compact(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", normalize_font_name(name).lower())


def is_math_font(name: str) -> bool:
    return bool(_MATH_FONT.match(_compact(name)))


def is_tex_text_font(name: str) -> bool:
    """Computer/Latin Modern text fonts: body text in TeX documents, math elsewhere."""
    return bool(_TEX_TEXT_FONT.match(_compact(name)))


def family_key(name: str) -> str:
    """Family without style or size suffixes (``NimbusRomNo9L-Regu`` -> ``nimbusromno9l``)."""
    lowered = normalize_font_name(name).lower()
    head = re.split(r"[-,+ ]", lowered, maxsplit=1)[0]
    head = re.sub(r"(bold|italic|oblique|regular|medium|light|semibold|black|mt|ps)+$", "", head)
    return re.sub(r"\d+$", "", head) or lowered


def style_from_font(name: str, flags: int) -> TextStyle:
    """Derive the style from the font name and MuPDF's span flags.

    Flags: 1 superscript, 2 italic, 4 serif, 8 monospaced, 16 bold.
    """
    clean = normalize_font_name(name)
    bold = bool(flags & 16) or bool(_BOLD.search(clean))
    italic = bool(flags & 2) or bool(_ITALIC.search(clean))
    if flags & 8 or _MONO.search(clean):
        family = FontFamily.MONO
    elif _SANS.search(clean):
        family = FontFamily.SANS
    else:
        family = FontFamily.SERIF
    return TextStyle(family, bold, italic)
