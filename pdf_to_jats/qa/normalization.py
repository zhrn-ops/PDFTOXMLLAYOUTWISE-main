"""Versioned comparison normalization; no NFKC, case folding or symbol folding."""
import unicodedata

POLICY = "unicode-nfc-whitespace-v1"


def normalized(text):
    return " ".join(unicodedata.normalize("NFC", text).split())
