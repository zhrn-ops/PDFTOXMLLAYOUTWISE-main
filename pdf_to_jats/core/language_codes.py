"""Language_Codes.pdf mappings, with explicit aliases and no fuzzy guessing."""
import json
from pathlib import Path
import unicodedata


def _key(value):
    text = unicodedata.normalize('NFKD', str(value)).casefold()
    return ''.join(char for char in text if char.isalnum() and not unicodedata.combining(char))


LANGUAGES = json.loads(Path(__file__).with_suffix('.json').read_text(encoding='utf-8'))

# The appendix prints the bibliographic (ISO 639-2/B) code.  These terminology
# (639-2/T) spellings name the same language and stay accepted so an existing
# title is never rejected on spelling alone.
_TERMINOLOGY_CODES = {
    'SQI': 'ALB', 'HYE': 'ARM', 'EUS': 'BAQ', 'MYA': 'BUR', 'ZHO': 'CHI',
    'CES': 'CZE', 'NLD': 'DUT', 'DEU': 'GER', 'ELL': 'GRE', 'FRA': 'FRE', 'ISL': 'ICE',
    'MKD': 'MAC', 'MSA': 'MAY', 'MRI': 'MAO', 'FAS': 'PER', 'RON': 'RUM',
    'SLK': 'SLO', 'CYM': 'WEL',
}

_LOOKUP = {}
_CODE_KEYS = set()
for _row in LANGUAGES:
    for _value in (_row['name'], *_row.get('aliases', [])):
        _LOOKUP[_key(_value)] = _row['alpha3']
    for _value in (_row['alpha3'], _row['alpha2'], _row['alpha4']):
        if _value:
            _LOOKUP[_key(_value)] = _row['alpha3']
            _CODE_KEYS.add(_key(_value))
for _terminology, _bibliographic in _TERMINOLOGY_CODES.items():
    _LOOKUP[_key(_terminology)] = _bibliographic
    _CODE_KEYS.add(_key(_terminology))

# ``UND`` is not a language in the appendix; it is the undetermined tag the
# generator writes when no language has been chosen.
UNDETERMINED = 'UND'


def language_code(value):
    """Return the appendix's three-letter code for a name or code, else ``''``."""
    return _LOOKUP.get(_key(value), '')


def is_language_code(value):
    """Whether *value* is a code this application may write as ``xml:lang``."""
    key = _key(value)
    return key == _key(UNDETERMINED) or key in _CODE_KEYS
