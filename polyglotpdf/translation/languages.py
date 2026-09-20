"""Language code helpers (BCP-47-ish codes such as ``pt-BR``, ``en``, ``zh-CN``)."""

from __future__ import annotations

_NAMES = {
    "ar": "Arabic",
    "bg": "Bulgarian",
    "ca": "Catalan",
    "cs": "Czech",
    "da": "Danish",
    "de": "German",
    "el": "Greek",
    "en": "English",
    "en-gb": "British English",
    "en-us": "American English",
    "es": "Spanish",
    "fi": "Finnish",
    "fr": "French",
    "he": "Hebrew",
    "hi": "Hindi",
    "hu": "Hungarian",
    "id": "Indonesian",
    "it": "Italian",
    "ja": "Japanese",
    "ko": "Korean",
    "nl": "Dutch",
    "no": "Norwegian",
    "pl": "Polish",
    "pt": "Portuguese",
    "pt-br": "Brazilian Portuguese",
    "pt-pt": "European Portuguese",
    "ro": "Romanian",
    "ru": "Russian",
    "sk": "Slovak",
    "sv": "Swedish",
    "th": "Thai",
    "tr": "Turkish",
    "uk": "Ukrainian",
    "vi": "Vietnamese",
    "zh": "Simplified Chinese",
    "zh-cn": "Simplified Chinese",
    "zh-tw": "Traditional Chinese",
}

_CJK = {"zh", "ja", "ko"}
_RTL = {"ar", "he", "fa", "ur"}


def normalize(code: str) -> str:
    return code.strip().replace("_", "-").lower()


def base(code: str) -> str:
    return normalize(code).split("-")[0]


def canonical(code: str) -> str:
    """``pt-br`` -> ``pt-BR``, ``EN`` -> ``en``."""
    norm = normalize(code)
    if "-" in norm:
        language, region = norm.split("-", 1)
        return f"{language}-{region.upper()}"
    return norm


def display_name(code: str) -> str:
    norm = normalize(code)
    if norm == "auto":
        return "the source language (detect it automatically)"
    return _NAMES.get(norm) or _NAMES.get(base(norm)) or code


def list_languages() -> list[tuple[str, str]]:
    """``(code, English name)`` pairs sorted by name, for language pickers."""
    return sorted(((canonical(code), name) for code, name in _NAMES.items()), key=lambda p: p[1])


def is_cjk(code: str) -> bool:
    return base(code) in _CJK


def is_rtl(code: str) -> bool:
    return base(code) in _RTL


def google_code(code: str) -> str:
    """Code understood by the Google Translate web endpoint."""
    norm = normalize(code)
    if norm in ("auto", ""):
        return "auto"
    if norm in ("zh", "zh-cn", "zh-hans"):
        return "zh-CN"
    if norm in ("zh-tw", "zh-hant"):
        return "zh-TW"
    return base(norm)


def deepl_source(code: str) -> str | None:
    """DeepL source language (no regional variants; ``None`` = detect)."""
    norm = normalize(code)
    return None if norm in ("auto", "") else base(norm).upper()


def deepl_target(code: str) -> str:
    """DeepL target language (``pt-BR`` -> ``PT-BR``; Portuguese/English need a variant)."""
    norm = normalize(code)
    special = {
        "pt": "PT-PT",
        "en": "EN-US",
        "zh": "ZH-HANS",
        "zh-cn": "ZH-HANS",
        "zh-hans": "ZH-HANS",
        "zh-tw": "ZH-HANT",
        "zh-hant": "ZH-HANT",
    }
    return special.get(norm, norm.upper())


def hyphenation_code(code: str) -> str:
    """Dictionary name for pyphen, e.g. ``pt-BR`` -> ``pt_BR``."""
    norm = normalize(code)
    if "-" in norm:
        language, region = norm.split("-", 1)
        return f"{language}_{region.upper()}"
    defaults = {"pt": "pt_PT", "en": "en_US", "de": "de_DE", "es": "es_ES", "fr": "fr_FR"}
    return defaults.get(norm, norm)
