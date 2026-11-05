from pdf_to_jats.core.rtl_text import repair_positioned_lines, text_direction


def block(chars, baseline=20):
    glyphs = [{'c': char, 'bbox': (x, baseline - 10, x + 5, baseline),
               'origin': (x, baseline)} for char, x in chars]
    bbox = (min(c['bbox'][0] for c in glyphs), baseline - 10,
            max(c['bbox'][2] for c in glyphs), baseline)
    return {'type': 0, 'bbox': bbox, 'lines': [{'bbox': bbox, 'dir': (1, 0),
            'spans': [{'chars': glyphs, 'bbox': bbox, 'origin': (bbox[0], baseline), 'size': 10}]}]}


def texts(raw):
    return [span['text'] for b in raw['blocks'] for line in b['lines'] for span in line['spans']]


def test_fragmented_shaped_letters_use_positions_and_keep_unshaped_words():
    raw = {'blocks': [block([('\ufeaa', 10), ('\ufbfe', 15), ('\ufe9f', 25), ('\ufeaa', 20)]),
                      block([('و', 33)]), block([('\ufe96', 41), ('\ufe92', 46)])]}
    assert texts(repair_positioned_lines(raw)) == ['بت و جدید']


def test_normal_unicode_is_not_reordered():
    raw = {'blocks': [block([('ب', 10), ('ت', 20)])]}
    assert texts(repair_positioned_lines(raw)) == ['بت']


def test_columns_and_baselines_are_not_joined():
    raw = {'blocks': [block([('\ufe8f', 10)]), block([('\ufe95', 100)]),
                      block([('\ufe9d', 10)], baseline=40)]}
    assert texts(repair_positioned_lines(raw)) == ['ب', 'ت', 'ج']


def test_mixed_latin_and_numbers_are_not_reversed():
    raw = {'blocks': [block([('\ufe8f', 30), ('A', 20), ('1', 10)])]}
    assert texts(repair_positioned_lines(raw)) == ['\ufe8fA1']


def test_preview_direction_uses_first_strong_character():
    assert text_direction('مراقبت مدرن') == 'rtl'
    assert text_direction('Modern care') == 'ltr'
    assert text_direction('2026 مراقبت') == 'rtl'
