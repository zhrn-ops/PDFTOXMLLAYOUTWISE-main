"""Country_Codes.pdf mappings, with explicit aliases and no fuzzy guessing."""
import json
from pathlib import Path
import unicodedata


def _key(value):
    text = unicodedata.normalize('NFKD', str(value)).casefold()
    return ''.join(char for char in text if char.isalnum() and not unicodedata.combining(char))


COUNTRIES = json.loads(Path(__file__).with_suffix('.json').read_text(encoding='utf-8'))
_LOOKUP = {}
for _row in COUNTRIES:
    for _value in (_row['name'], _row['alpha3'], _row['alpha2']):
        _LOOKUP[_key(_value)] = _row['alpha3']

_ALIASES = {
    'IRN': ['Islamic Republic of Iran', 'Iran (Islamic Republic of)'],
    'USA': ['United States of America', 'U.S.A.', 'U.S.'],
    'GBR': ['UK', 'U.K.', 'Great Britain', 'United Kingdom of Great Britain and Northern Ireland'],
    'KOR': ['Republic of Korea', 'Korea, Republic of'],
    'PRK': ["Democratic People’s Republic of Korea", "Korea, Democratic People's Republic of"],
    'CHN': ["People’s Republic of China", 'PR China', 'P.R. China'],
    'RUS': ['Russia'], 'VNM': ['Vietnam'], 'CZE': ['Czech Republic'],
    'TUR': ['Türkiye'], 'SWZ': ['Eswatini'], 'LBY': ['Libya'],
    'CPV': ['Cabo Verde'], 'CIV': ['Ivory Coast'],
    'COD': ['Democratic Republic of the Congo', 'DR Congo', 'DRC', 'Congo (Kinshasa)'],
    'COG': ['Republic of the Congo', 'Congo (Brazzaville)'],
    'LAO': ["Lao People's Democratic Republic"], 'SYR': ['Syria'],
    'TZA': ['United Republic of Tanzania'], 'MDA': ['Republic of Moldova'],
    'BOL': ['Bolivia (Plurinational State of)'],
    'VEN': ['Venezuela (Bolivarian Republic of)'],
    'PSE': ['State of Palestine'], 'BRN': ['Brunei'],
    'VAT': ['Holy See'], 'MAC': ['Macau'], 'SXM': ['Sint Maarten'],
}
for _code, _names in _ALIASES.items():
    for _name in _names:
        _LOOKUP[_key(_name)] = _code


def country_code(value, *, funding=False):
    code = _LOOKUP.get(_key(value), '')
    return code if code != 'EUE' or funding else ''


def normalize_country_elements(root, *, strict=True):
    """Normalize ANI country fields on an export copy; reject unresolved values."""
    for node in root.iter():
        if not isinstance(node.tag, str) or node.tag.rsplit('}', 1)[-1] != 'country':
            continue
        # JATS uses a different country representation.
        if node.tag.startswith('{') and not node.tag.startswith('{http://www.elsevier.com/xml/ani/ani}'):
            continue
        if not node.tag.startswith('{') and root.tag.rsplit('}', 1)[-1] == 'article':
            continue
        funding = any(isinstance(parent.tag, str) and any(term in parent.tag.rsplit('}', 1)[-1]
                      for term in ('grant', 'funding')) for parent in node.iterancestors())
        raw_code = node.get('iso-code', '').strip()
        text = ''.join(node.itertext()).strip()
        code = country_code(raw_code, funding=funding) if raw_code else country_code(text, funding=funding)
        if not code:
            if not strict:
                continue
            raise ValueError(f'Country {raw_code or text!r} needs review: select a valid three-letter country code.')
        text_code = country_code(text, funding=funding) if text else ''
        if text_code and text_code != code:
            if not strict:
                continue
            raise ValueError(f'Country name {text!r} conflicts with code {raw_code!r}; correct the country field.')
        node.set('iso-code', code)
        node.text = None
        for child in list(node):
            node.remove(child)
