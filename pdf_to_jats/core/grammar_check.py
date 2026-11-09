"""Conservative, offline English checks; no document text leaves the app."""

from dataclasses import dataclass
import re


# Known misspellings rather than an unknown-word dictionary: scientific names,
# abbreviations and valid British/American variants should not be guessed at.
COMMON_TYPOS = {
    'teh': 'the', 'adn': 'and', 'thier': 'their', 'wiht': 'with',
    'wihch': 'which', 'whcih': 'which', 'becuase': 'because',
    'beacuse': 'because', 'recieve': 'receive', 'recieved': 'received',
    'recieving': 'receiving', 'seperate': 'separate', 'seperately': 'separately',
    'occured': 'occurred', 'occuring': 'occurring', 'occurence': 'occurrence',
    'definately': 'definitely', 'alot': 'a lot', 'untill': 'until',
    'wich': 'which', 'betwen': 'between', 'diffrent': 'different',
    'diferent': 'different', 'differnce': 'difference', 'differnces': 'differences',
    'similiar': 'similar', 'neccessary': 'necessary', 'necesary': 'necessary',
    'consistant': 'consistent', 'consistantly': 'consistently',
    'independant': 'independent',
    'signficant': 'significant', 'signficantly': 'significantly',
    'signifcant': 'significant', 'signifcantly': 'significantly',
    'singificant': 'significant', 'singificantly': 'significantly',
    'statstical': 'statistical', 'statstically': 'statistically',
    'statisical': 'statistical', 'statisically': 'statistically',
    'analaysis': 'analysis', 'analyis': 'analysis', 'anaylsis': 'analysis',
    'resutls': 'results', 'resutl': 'result', 'reults': 'results',
    'paitent': 'patient', 'paitents': 'patients', 'patinets': 'patients',
    'particpants': 'participants', 'partcipants': 'participants',
    'treatement': 'treatment', 'treatements': 'treatments',
    'clincial': 'clinical', 'clinicial': 'clinical',
    'efficency': 'efficiency', 'efficacyy': 'efficacy',
    'assocation': 'association', 'assocations': 'associations',
    'corelation': 'correlation', 'correllation': 'correlation',
    'comparision': 'comparison', 'comparisions': 'comparisons',
    'conlcusion': 'conclusion', 'conlcusions': 'conclusions',
    'conculsion': 'conclusion', 'conculsions': 'conclusions',
    'observatons': 'observations', 'obsevation': 'observation',
    'inlcuded': 'included', 'incldued': 'included', 'exlcuded': 'excluded',
    'measurment': 'measurement', 'measurments': 'measurements',
    'assesment': 'assessment', 'assesssment': 'assessment',
    'prevelance': 'prevalence', 'prevelent': 'prevalent',
    'sensivity': 'sensitivity', 'specifcity': 'specificity',
    'charateristics': 'characteristics', 'charcteristics': 'characteristics',
    'investigaton': 'investigation', 'investigatoin': 'investigation',
}


@dataclass(frozen=True)
class GrammarSuggestion:
    start: int
    end: int
    replacement: str
    message: str


def check_grammar(text: str) -> list[GrammarSuggestion]:
    """Find common errors, returning Python character offsets for exact edits.

    This is a limited rule-based review, not a full linguistic analysis.
    Only known common misspellings are flagged; unknown technical words are
    left alone. This is not a comprehensive dictionary spell checker.
    """
    suggestions = []

    def add(match, replacement, message):
        suggestions.append(GrammarSuggestion(match.start(), match.end(), replacement, message))

    # Hyphenation may be intentional or left over from PDF line wrapping.
    # Flag it for review, including identifiers, without calling it an error.
    for match in re.finditer(r'\b[^\W_]+(?:-[ \t]*(?:\r?\n[ \t]*)?[^\W_]+)+\b', text):
        if any(character.isalpha() for character in match.group(0)):
            add(match, re.sub(r'-\s*', '', match.group(0)),
                'Hyphenated word — optional review; keep if intentional')

    for match in re.finditer(r'\b[A-Za-z]+\b', text):
        word = match.group(0)
        replacement = COMMON_TYPOS.get(word.lower())
        # Preserve acronyms and mixed-case scientific identifiers.
        if replacement and (word.islower() or word.istitle()):
            if word.istitle():
                replacement = replacement.capitalize()
            add(match, replacement, 'Possible typo')

    for match in re.finditer(r'\b(the|a|an|of|in|to|and|for|with|is|are)\s+\1\b', text, re.I):
        add(match, match.group(0).split()[0], 'Repeated word')

    # Only use words with unambiguous vowel/consonant sounds. Acronyms and
    # words such as "university", "hour" and "one" need different treatment.
    vowel_words = r'(?:analysis|approach|effect|increase|improvement|outcome|observation|association|experiment|individual|important|effective|observational|unexpected)'
    consonant_words = r'(?:study|result|method|patient|sample|significant|randomized|controlled|clinical|large|small)'
    for pattern, article in [(rf'\ba (?={vowel_words}\b)', 'an '),
                             (rf'\ban (?={consonant_words}\b)', 'a ')]:
        for match in re.finditer(pattern, text, re.I):
            replacement = article.capitalize() if match.group(0)[0].isupper() else article
            add(match, replacement, 'Check the article before this word')

    rules = [
        (r'\b(these|those)\s+(is|was|has)\b', {'is': 'are', 'was': 'were', 'has': 'have'}),
        (r'\b(this|that)\s+(are|were|have)\b', {'are': 'is', 'were': 'was', 'have': 'has'}),
        (r'\b(results|findings|patients|participants|samples|methods)\s+(is|was|has)\b',
         {'is': 'are', 'was': 'were', 'has': 'have'}),
        (r'\b(study|analysis|method|patient|sample)\s+(are|were|have)\b',
         {'are': 'is', 'were': 'was', 'have': 'has'}),
    ]
    for pattern, replacements in rules:
        for match in re.finditer(pattern, text, re.I):
            verb = match.group(2)
            replacement = replacements[verb.lower()]
            if verb.isupper():
                replacement = replacement.upper()
            start, end = match.span(2)
            suggestions.append(GrammarSuggestion(start, end, replacement, 'Check subject–verb agreement'))

    for match in re.finditer(r'[^\S\n]+([,;:!?])', text):
        punctuation = match.group(1)
        if match.end() < len(text) and text[match.end()].isalpha():
            punctuation += ' '
        add(match, punctuation, 'Correct spacing around punctuation')
    for match in re.finditer(r'([,;])(?=[A-Za-z])', text):
        add(match, match.group(1) + ' ', 'Add a space after punctuation')

    # Avoid overlapping edits in the same review pass.
    result = []
    for suggestion in sorted(suggestions, key=lambda item: (item.start, item.end)):
        if not result or suggestion.start >= result[-1].end:
            result.append(suggestion)
    return result
