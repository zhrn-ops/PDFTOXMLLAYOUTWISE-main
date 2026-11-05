"""Repair positioned Arabic presentation glyphs without reversing logical text."""
import unicodedata


def has_presentation_forms(text):
    return any('\ufb50' <= char <= '\ufdff' or '\ufe70' <= char <= '\ufeff' for char in text)


def text_direction(text):
    for char in text:
        direction = unicodedata.bidirectional(char)
        if direction in {'R', 'AL'}:
            return 'rtl'
        if direction == 'L':
            return 'ltr'
    return 'ltr'


def repair_positioned_lines(raw):
    """Convert rawdict to dict and join adjacent shaped RTL fragments by baseline.

    Only horizontal lines with presentation forms are candidates. Gaps larger
    than one em separate columns; ordinary Unicode lines retain source order.
    """
    candidates = []
    for block in raw['blocks']:
        if block.get('type') != 0:
            continue
        for line in block['lines']:
            for span in line['spans']:
                span['text'] = ''.join(char['c'] for char in span['chars'])
            text = ''.join(span['text'] for span in line['spans'])
            if any(unicodedata.bidirectional(char) in {'R', 'AL'} for char in text) and tuple(line.get('dir', (1, 0))) == (1, 0):
                candidates.append((block, line))
    rows = []
    for block, line in sorted(candidates, key=lambda pair: (pair[1]['spans'][0]['origin'][1], pair[1]['bbox'][0])):
        baseline = line['spans'][0]['origin'][1]
        size = max(span['size'] for span in line['spans'])
        row = next((row for row in reversed(rows)
                    if abs(row['baseline'] - baseline) <= 0.8
                    and abs(row['size'] - size) <= 0.5
                    and -0.5 <= line['bbox'][0] - row['right'] <= size), None)
        if row is None:
            row = dict(baseline=baseline, size=size, right=line['bbox'][2], entries=[])
            rows.append(row)
        row['entries'].append((block, line))
        row['right'] = max(row['right'], line['bbox'][2])
    for row in rows:
        entries = row['entries']
        if not any(has_presentation_forms(span['text']) for _, line in entries for span in line['spans']):
            continue
        chars = [char for _, line in entries for span in line['spans']
                 for char in span['chars'] if not char['c'].isspace()]
        # Do not reinterpret mixed Latin/numeric runs without bidi run data.
        if any(unicodedata.bidirectional(char['c']) in {'L', 'EN', 'AN'} for char in chars):
            continue
        chars.sort(key=lambda char: -char['bbox'][0])
        parts = []
        for index, char in enumerate(chars):
            if index and chars[index - 1]['bbox'][0] - char['bbox'][2] > row['size'] * 0.12:
                parts.append(' ')
            parts.append(unicodedata.normalize('NFKC', char['c']))
        text = ''.join(parts)
        boxes = [line['bbox'] for _, line in entries]
        bbox = (min(b[0] for b in boxes), min(b[1] for b in boxes),
                max(b[2] for b in boxes), max(b[3] for b in boxes))
        owner, first = entries[0]
        span = dict(first['spans'][0], text=text, bbox=bbox)
        span.pop('chars', None)
        replacement = dict(first, bbox=bbox, spans=[span])
        for block, line in entries:
            block['lines'].remove(line)
        owner['lines'].append(replacement)
        owner['bbox'] = (min(owner['bbox'][0], bbox[0]), min(owner['bbox'][1], bbox[1]),
                         max(owner['bbox'][2], bbox[2]), max(owner['bbox'][3], bbox[3]))
    return raw
