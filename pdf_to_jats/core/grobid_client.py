"""GROBID text parsing with source-marker links retained locally."""
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from lxml import etree

from pdf_to_jats.core.author_linker import AuthorLinker, LinkIssue
from pdf_to_jats.core.parenthesized_authors import split_parenthesized_authors, link_parenthesized_records


class GrobidClient:
    def __init__(self, base_url='http://localhost:8070', timeout=45):
        self.base_url = base_url.rstrip('/')
        self.timeout = timeout

    def _parse(self, endpoint, field, text):
        request = Request(f'{self.base_url}/api/{endpoint}',
                          data=urlencode({field: text}).encode(),
                          headers={'Accept': '*/*',
                                   'Content-Type': 'application/x-www-form-urlencoded'})
        with urlopen(request, timeout=self.timeout) as response:
            data = response.read()
        if not data.strip():
            raise ValueError(f'GROBID returned no result for {endpoint}: {text}')
        # Name services may return several sibling TEI fragments.
        data = data.strip()
        if data.startswith(b'<?xml'):
            data = data.split(b'?>', 1)[1]
        return etree.fromstring(b'<results>' + data + b'</results>', etree.XMLParser(
            resolve_entities=False, no_network=True, load_dtd=False))

    def classify(self, prompt, payload, progress=None):
        linker = AuthorLinker()
        author_blocks = payload.get('author_blocks', [])
        corresponding_texts = [block['text'] for block in author_blocks
                               if block.get('role') == 'corresponding_author']
        byline_blocks = [block for block in author_blocks
                         if block.get('role') != 'corresponding_author']
        records = split_parenthesized_authors(byline_blocks)
        if records is not None and payload.get('affiliation_blocks'):
            raise ValueError('Inline parenthesized affiliations and separate affiliation blocks are both selected; review the selection to avoid losing or guessing links')
        linked = link_parenthesized_records(records) if records is not None else linker.link_from_texts(
            [block['text'] for block in byline_blocks],
            [block['text'] for block in payload.get('affiliation_blocks', [])])
        linked.corresponding_author = linker._find_corresponding_author(corresponding_texts, linked.authors)
        if linked.corresponding_author is None and linked.authors:
            linked.corresponding_author = linked.authors[0]
            linked.issues.append(LinkIssue(
                'warning', 'No corresponding author was matched explicitly; used the first author. Review correspondence.',
                author_id=linked.authors[0].id))
        for index, author in enumerate(linked.authors, 1):
            if progress:
                progress(f'GROBID: parsing author {index}/{len(linked.authors)}')
            root = self._parse('processHeaderNames', 'names', author.display_name)
            names = root.xpath('//*[local-name()="persName"]')
            if len(names) != 1:
                message = (f'GROBID returned {len(names)} names for {author.display_name!r}. '
                           'Kept the local parser name and affiliation links; review this author.')
                linked.issues.append(LinkIssue('warning', message, author_id=author.id))
                if progress:
                    progress(message)
                continue
            name = names[0]
            given = name.xpath('./*[local-name()="forename"]/text()')
            surname = name.xpath('./*[local-name()="surname"]/text()')
            if not surname:
                message = (f'GROBID returned no surname for {author.display_name!r}. '
                           'Kept the local parser name and affiliation links; review this author.')
                linked.issues.append(LinkIssue('warning', message, author_id=author.id))
                if progress:
                    progress(message)
                continue
            author.given_names = ' '.join(given)
            author.surname = ' '.join(surname)
            author.initials = ' '.join(token[0] + '.' for token in given if token)
        for index, affiliation in enumerate(linked.affiliations, 1):
            if progress:
                progress(f'GROBID: parsing affiliation {index}/{len(linked.affiliations)}')
            root = self._parse('processAffiliations', 'affiliations', affiliation.text)
            entries = root.xpath('//*[local-name()="affiliation"]')
            if len(entries) != 1:
                message = (f'GROBID returned {len(entries)} affiliation entries for {affiliation.text!r}. '
                           'Kept the complete source affiliation and existing author links; '
                           'review its organization fields and split the source selection if it contains separate affiliations.')
                linked.issues.append(LinkIssue('warning', message, affiliation_id=affiliation.id))
                if progress:
                    progress(message)
                affiliation.structured = {'organization': [affiliation.text]}
                continue
            entry = entries[0]
            def values(tag):
                return [' '.join(''.join(node.itertext()).split())
                        for node in entry.xpath(f'.//*[local-name()="{tag}"]')]
            affiliation.structured = {
                'organization': values('orgName'), 'address-part': values('addrLine'),
                'city': values('settlement'), 'state': values('region'),
                'postal-code': values('postCode'), 'country': values('country'),
            }
        return linked
