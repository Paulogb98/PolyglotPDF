"""Which language a document is written in, from a sample of its text.

No model, no dependency: the writing system settles most cases (Cyrillic, Greek,
Arabic, Hebrew, the CJK scripts), and for the Latin alphabet the most frequent function
words of each language do the rest — they are short, frequent and very different from
one language to the next, which is all a book-length sample needs.
"""

from __future__ import annotations

import re
from collections import Counter

#: A few hundred characters decide nothing; this many are plenty.
SAMPLE = 20_000
_MIN_WORDS = 30


def _words(text: str) -> frozenset[str]:
    return frozenset(text.split())


_FUNCTION_WORDS: dict[str, frozenset[str]] = {
    "pt": _words(
        "de que não uma os do da em para com por mais como mas foi ao ele das tem à seu "
        "sua ou ser quando muito nos já está também só pelo pela até isso ela entre "
        "depois sem mesmo aos seus quem nas me esse eles você essa num nem suas meu "
        "às minha numa pelos elas qual nós lhe deles essas esses pelas este dele são "
        "é então"
    ),
    "es": _words(
        "de que el en y los se del las un por con no una su para es al lo como más pero "
        "sus le ya o fue este ha sí porque esta son entre cuando muy sin sobre también "
        "me hasta hay donde quien desde todo nos durante todos uno les ni contra otros "
        "ese eso ante ellos esto mí antes algunos qué unos yo otro otras otra él"
    ),
    "en": _words(
        "the of and to in is that it for as with was on be by this are not or which "
        "from at an but have has had they their we can its been were more one all "
        "would there when these than so what into only other such also may between "
        "should those our who"
    ),
    "fr": _words(
        "de la le et les des en du un une est que dans qui pour pas par sur au plus ne "
        "se ce il sont avec aux son ou mais comme nous elle être cette ont ses leur "
        "été fait tout peut deux même aussi entre ces sans lui dont où"
    ),
    "de": _words(
        "der die und in den von zu das mit sich des auf für ist im dem nicht ein eine "
        "als auch es an werden aus er hat daß dass sie nach wird bei einer um am sind "
        "noch wie einem über einen so zum war haben nur oder aber vor zur bis mehr "
        "durch man sein wurde sei ist"
    ),
    "it": _words(
        "di e il la che in a per un è non del le si da una con i dei al della come più "
        "sono anche ma gli nel alla su lo ha delle questo essere nella quando tra "
        "loro dalla sua suo degli se ci"
    ),
    "nl": _words(
        "de van het een en in is dat op te zijn met voor niet aan er die als door "
        "om ook maar bij dan nog wordt tot uit werd naar kan wel over deze"
    ),
    "la": _words(
        "et in est non ad cum quod ut sed qui quae per ex enim esse sunt nec autem "
        "etiam quam hoc atque eius ab vel ac sit neque tamen ita nam"
    ),
}

_SCRIPTS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("ru", re.compile(r"[Ѐ-ӿ]")),
    ("el", re.compile(r"[Ͱ-Ͽἀ-῿]")),
    ("ar", re.compile(r"[؀-ۿ]")),
    ("he", re.compile(r"[֐-׿]")),
    ("ja", re.compile(r"[぀-ヿ]")),  # kana: before the ideographs they share
    ("ko", re.compile(r"[가-힯]")),
    ("zh", re.compile(r"[一-鿿]")),
)
_WORD = re.compile(r"[^\W\d_]+", re.UNICODE)


def detect_language(text: str) -> str | None:
    """The language code of ``text`` (``pt``, ``de``…), or ``None`` when unsure."""
    sample = text[:SAMPLE]
    letters = sum(1 for char in sample if char.isalpha())
    if letters < 80:
        return None
    for code, pattern in _SCRIPTS:
        if len(pattern.findall(sample)) > letters * 0.3:
            return code
    words = [word.lower() for word in _WORD.findall(sample)]
    if len(words) < _MIN_WORDS:
        return None
    counts = Counter(words)
    scores = {
        code: sum(counts[word] for word in vocabulary) / len(words)
        for code, vocabulary in _FUNCTION_WORDS.items()
    }
    best, score = max(scores.items(), key=lambda item: item[1])
    runner_up = max((value for code, value in scores.items() if code != best), default=0.0)
    # Function words are a fifth or more of running prose; a thin, close call is noise.
    if score < 0.08 or score < runner_up * 1.25:
        return None
    return best


__all__ = ["SAMPLE", "detect_language"]
