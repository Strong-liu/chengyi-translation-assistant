"""Local keep-English rules. Automatic discovery is heuristic and reviewable."""

from __future__ import annotations

import hashlib
import json
import re
import statistics
import unicodedata
from pathlib import Path

POLICY_VERSION = 'english-preservation-v4'
DEFAULT_TERMS = [
    'EEGNet', 'DeepConvNet', 'ShallowConvNet', 'Compact-CNN', 'CompactCNN',
    'CNN', 'RNN', 'LSTM', 'BiLSTM', 'GRU', 'Transformer', 'SSVEPformer',
    'TFF-Former', 'FB-CCNN', 'FB-tCNN', 'FB-DNN', 'bi-SiamCA', 'ConvCA',
    'TRCA', 'eTRCA', 'TDCA', 'CCA', 'FBCCA', 'FB-CCA', 'MsetCCA', 'MsiCCA',
    'MSI', 'CORRCA', 'SVM', 'KNN', 'k-NN', 'ResNet', 'VGG', 'AlexNet',
    'Inception', 'BERT', 'GPT', 'Mamba', 'GraphSAGE', 'GNN', 'GCN',
    'STA-Net', 'RSMTA-Net', 'ALPHA', 'CSSFT', 'SiamCA', 'Siamese',
    'ReLU', 'ELU', 'GELU', 'PReLU', 'Adam', 'SGD', 'Softmax', 'Sigmoid',
    'BatchNorm', 'Dropout', 'FFT', 'STFT', 'CWT', 'DWT', 'PCA', 'ICA',
    'convolutional neural network', 'recurrent neural network',
    'long short-term memory', 'canonical correlation analysis',
    'task-related component analysis', 'task discriminant component analysis',
    'support vector machine', 'random forest', 'principal component analysis',
    'Brain Sciences', 'Brain Sci.', 'Electronics', 'Nature', 'Science',
    'Journal of Neural Engineering', 'J. Neural Eng.',
    'Journal of Neuroscience Methods', 'J. Neurosci. Methods',
    'IEEE Transactions on Neural Systems and Rehabilitation Engineering',
    'IEEE Trans. Neural Syst. Rehabil. Eng.', 'IEEE Access',
    'Frontiers in Neuroscience', 'Front. Neurosci.', 'Scientific Reports',
    'Brain-Apparatus Communication', 'NeuroImage', 'Neural Networks',
]
TOKEN_RE = re.compile(r'ZXQPT\d{6}ZXQ', re.IGNORECASE)
TOKEN_ARTIFACT_RE = re.compile(r'Z\s*X\s*Q\s*P\s*T', re.IGNORECASE)
FORMULA_RE = re.compile(r'\{\s*v\s*\d+\s*\}|</?style\b[^>]*>', re.IGNORECASE)
HYPHENS = '\u2010\u2011\u2012\u2013\u2014\u2212'
REFERENCE_NUMBER_RE = re.compile(r'^\s*(?:\[\s*\d+\s*\]|\d+[.)])\s*')
AUTHOR_NAME = r"[A-ZÀ-ÖØ-Þ][A-Za-zÀ-ÖØ-öø-ÿ’'\-]+"
AUTHOR_INITIAL = r'[A-ZÀ-ÖØ-Þ]\.(?:\s*[-\u2010\u2011]\s*[A-Za-zÀ-ÖØ-öø-ÿ]\.)?'
AUTHOR_INITIALS = rf'(?:{AUTHOR_INITIAL}\s*){{1,4}}'
REFERENCE_AUTHOR_RE = re.compile(
    rf'^(?:{AUTHOR_INITIALS}(?:(?:van|von|de|del|da|di|le|la)\s+)?{AUTHOR_NAME}'
    rf'|{AUTHOR_NAME},\s*{AUTHOR_INITIALS}'
    rf'|{AUTHOR_NAME}\s+[A-Z]{{1,4}}(?=\s*[,;.])'
    rf'|{AUTHOR_NAME}\s+et\s+al\.'
    rf'|{AUTHOR_NAME}(?:\s+{AUTHOR_NAME}){{1,3}}(?=[,.;])'
    rf'|{AUTHOR_NAME},\s+{AUTHOR_NAME}(?=[,.;]))'
)
PUBLICATION_DETAILS_RE = re.compile(
    r'doi\s*:|https?://(?:dx\.)?doi\.org/|\barXiv\s*:|\bISBN\b'
    r'|\b(?:vol\.|pp\.|Art\.\s*no\.)'
    r'|\b\d+\s*\(\s*\d+\s*\)\s*,\s*\d+'
    r'|\b\d+\s*,\s*\d+\s*[-–]\s*\d+', re.IGNORECASE
)


class ProtectionError(RuntimeError):
    pass


def normalize_text(text: str) -> str:
    text = unicodedata.normalize('NFKC', text)
    text = FORMULA_RE.sub('', text)
    text = text.translate(str.maketrans({char: '-' for char in HYPHENS}))
    return re.sub(r'[^a-zA-Z0-9]+', '', text).lower()


def term_pattern(term: str) -> str:
    parts = []
    for character in term:
        if character.isspace():
            if not parts or parts[-1] != r'\s+':
                parts.append(r'\s+')
        elif character in '-' + HYPHENS:
            parts.append('[-' + HYPHENS + ']')
        else:
            parts.append(re.escape(character))
    return r'(?<![A-Za-z0-9])' + ''.join(parts) + r'(?![A-Za-z0-9])'


def _reference_heading(text: str) -> bool:
    # Publishers may letter-space headings or number them with Arabic/Roman
    # section labels. Compare the complete line so a prose mention does not
    # turn the rest of the manuscript into a bibliography.
    compact = re.sub(r'\s+', '', unicodedata.normalize('NFKC', text)).strip(':：.')
    return bool(re.fullmatch(
        r'(?:(?:\d+(?:\.\d+)*|[IVXLCDM]+)\.?)?'
        r'(?:References?|Bibliography|Literaturecited|参考文献)', compact, re.IGNORECASE))


def _reference_entry(text: str) -> bool:
    text = unicodedata.normalize('NFKC', text).strip()
    number = REFERENCE_NUMBER_RE.match(text)
    content = text[number.end():] if number else text
    # Search for an author at the start of the entry, rather than any later
    # surname/initial pair in a paragraph that merely cites another paper.
    if not REFERENCE_AUTHOR_RE.match(content):
        return False
    if not re.search(r'\b(?:19|20)\d{2}[a-z]?\b', content):
        return False
    # A numbered bibliography item has both the citation label and author
    # prefix. An unnumbered item needs publication metadata as extra evidence.
    return bool(number or PUBLICATION_DETAILS_RE.search(content))


class TermProtector:
    def __init__(self, terms=None, preserve_texts=None, preserve_references=True):
        self.terms = sorted({str(term).strip() for term in (terms or DEFAULT_TERMS) if str(term).strip()}, key=lambda value: (-len(value), value))
        self.preserve_texts = list(preserve_texts or [])
        self.preserve_references = preserve_references
        self.normalized_preserved = [normalize_text(text) for text in self.preserve_texts if normalize_text(text)]
        self.joined_preserved = ''.join(self.normalized_preserved)
        words = '|'.join(term_pattern(term) for term in self.terms)
        # Formula markers and external identifiers are also losslessly masked.
        extra = [FORMULA_RE.pattern, r'https?://[^\s<>]+', r'[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}', r'\b(?:doi:\s*)?10\.\d{4,9}/[^\s<>]+']
        self.pattern = re.compile('|'.join(extra + ([words] if words else [])), re.IGNORECASE)
        specification = [POLICY_VERSION, self.terms, sorted(self.normalized_preserved), preserve_references]
        self.fingerprint = hashlib.sha256(json.dumps(specification, ensure_ascii=False).encode('utf-8')).hexdigest()

    def should_preserve(self, text: str) -> bool:
        # Keep publisher/contact metadata in English along with its names and
        # identifiers; it is not manuscript prose and often contains URLs or
        # copyright clauses which online translation services may rewrite.
        if re.match(r'^\s*(?:CONTACT\b|Correspondence\s*:|Citation\s*:|To cite this article\s*:|Copyright\b|©|Academic Editor\s*:)', text, re.IGNORECASE):
            return True
        normalized = normalize_text(text)
        if normalized and any(normalized == item or (len(normalized) >= 24 and normalized in item) for item in self.normalized_preserved):
            return True
        # PDF extraction and the layout engine may split/merge a bibliography
        # entry at different line boundaries. Match across adjacent source
        # blocks as well, without freezing unrelated appendix paragraphs.
        if len(normalized) >= 24 and normalized in self.joined_preserved:
            return True
        if self.preserve_references:
            # A bibliography entry remains English in its entirety, including
            # title, authors, journal, year, volume, DOI and citation markers.
            if _reference_heading(text) or _reference_entry(text):
                return True
        return False

    def mask(self, text: str):
        if TOKEN_RE.search(text):
            raise ProtectionError('输入包含与术语保护标记冲突的文本，请更换保护标记后重试。')
        replacements = {}

        def replace(match):
            token = f'ZXQPT{len(replacements):06d}ZXQ'
            replacements[token] = match.group(0)
            return token

        return self.pattern.sub(replace, text), replacements

    def restore(self, translated: str, replacements: dict[str, str]) -> str:
        result = translated
        for token, original in replacements.items():
            # Accept case changes and inserted whitespace, not altered IDs or
            # translated markers. Every protected occurrence must survive once.
            expression = re.compile(r'\s*'.join(re.escape(char) for char in token), re.IGNORECASE)
            if len(list(expression.finditer(result))) != 1:
                raise ProtectionError('翻译服务改变或遗漏了术语保护标记，本段译文已拒绝，请重试或调整术语表。')
            result = expression.sub(lambda _: original, result, count=1)
        if TOKEN_RE.search(result) or TOKEN_ARTIFACT_RE.search(result):
            raise ProtectionError('译文存在无法恢复的术语保护标记，本段译文已拒绝。')
        return result

    def translate(self, text, translate_chunk):
        if self.should_preserve(text):
            return text
        masked, replacements = self.mask(text)
        non_terms = TOKEN_RE.sub('', masked)
        if not re.search(r'[A-Za-z\u3400-\u9fff]', non_terms):
            return text
        return self.restore(translate_chunk(masked), replacements)


def _dedupe(values):
    return sorted({re.sub(r'\s+', ' ', value).strip(' ,;') for value in values if value and len(value.strip()) >= 2}, key=str.casefold)


def _clean_author_line(line):
    spans = [span for span in line.get('spans', []) if not span.get('flags', 0) & 1]
    pieces, previous_end = [], None
    for span in spans:
        if previous_end is not None and span['bbox'][0] - previous_end > span.get('size', 10) * .2:
            pieces.append(' ')
        pieces.append(span.get('text', ''))
        previous_end = span['bbox'][2]
    return ''.join(pieces)


def _appendix_heading(text):
    return bool(re.match(r'^\s*(?:(?i:Appendi(?:x|ces)\b|Supplement(?:ary|al)\b)|[A-Z](?:\.\d+)*\s*\n\s*[A-Z][A-Za-z -]{5,})', text))


def _page_reading_lines(page_dict, page_width):
    """Return text lines in column order without grouping neighbouring columns.

    PyMuPDF can put left and right text in one block at the same Y coordinate.
    A bibliography boundary must therefore select lines, not whole blocks.
    Require narrow text on both sides before using two-column reading order;
    full-width paragraphs keep the ordinary top-to-bottom order.
    """
    lines = []
    for block in page_dict.get('blocks', []):
        block_lines = block.get('lines', [])
        block_text = '\n'.join(''.join(span.get('text', '') for span in line.get('spans', []))
                               for line in block_lines)
        for index, line in enumerate(block_lines):
            content = ''.join(span.get('text', '') for span in line.get('spans', [])).strip()
            if content:
                appendix = _appendix_heading(content) or (index == 0 and _appendix_heading(block_text))
                lines.append((line['bbox'], content, appendix))
    middle = page_width / 2
    gutter = page_width * .025
    has_left = any(box[2] <= middle + gutter and len(content) >= 24 for box, content, _ in lines)
    has_right = any(box[0] >= middle - gutter and len(content) >= 24 for box, content, _ in lines)
    two_columns = has_left and has_right
    ordered = []
    for box, content, appendix in lines:
        column = int(two_columns and box[0] >= middle - gutter)
        ordered.append(((column, box[1]), content, appendix))
    return sorted(ordered, key=lambda item: item[0])


def discover_protected_terms(pdf_path, custom_terms=None):
    """Return reviewable candidates, exact protected blocks and provenance.

    This is intentionally a heuristic candidate detector, not a claim of
    universal named-entity recognition. The user can edit the returned terms.
    """
    import pymupdf

    authors, journals, methods, preserved = [], [], list(DEFAULT_TERMS), []
    reference_texts = []
    reference_pages = []
    full_text = []
    with pymupdf.open(pdf_path) as document:
        metadata_author = (document.metadata or {}).get('author', '')
        for value in re.split(r';|\s+and\s+', metadata_author):
            value = value.strip()
            if value and len(value) < 150:
                authors.append(value)
                if len(value.split()) >= 2:
                    authors.append(value.split()[-1].strip(','))
        in_references = False
        for page_number, page in enumerate(document):
            blocks = page.get_text('blocks')
            page_dict = page.get_text('dict')
            sizes = [span.get('size', 10) for block in page_dict.get('blocks', [])
                     for line in block.get('lines', []) for span in line.get('spans', [])
                     if len(span.get('text', '').strip()) >= 12 and block.get('bbox', [0, 0])[1] > page.rect.height * .12]
            body_size = statistics.median(sizes) if sizes else 10
            # Affiliation superscripts are separate spans in publisher PDFs.
            # Plain extraction joins them to surnames (e.g. "Pana"), whereas
            # BabelDOC separates them again before translation.
            clean_blocks = {}
            for item in page_dict.get('blocks', []):
                # Block numbers differ between text-only and image-inclusive
                # extraction. Geometry identifies the same block in both.
                clean_blocks[tuple(item.get('bbox', ()))] = '\n'.join(
                    _clean_author_line(line)
                    for line in item.get('lines', []))
            text = page.get_text()
            full_text.append(text)
            reading_lines = _page_reading_lines(page_dict, page.rect.width)
            reference_start = (0, float('-inf')) if in_references else None
            if not in_references:
                for position, content, _ in reading_lines:
                    # Do not treat an early survey table's References column
                    # as a section heading. Bibliographies may precede appendices.
                    if not _reference_heading(content):
                        continue
                    following = text[text.find(content) + len(content):]
                    bibliography_context = (len(re.findall(r'\b(?:19|20)\d{2}\b', following[:5000])) >= 2
                                            and re.search(r'doi\s*:|https?://|Journal|Proceedings|\bvol\.', following[:5000], re.I))
                    eligible_page = (len(document) <= 4 or page_number >= len(document) * .5
                                     or (page_number >= 2 and bibliography_context))
                    if eligible_page:
                        reference_start = position
                        in_references = True
                        break
            if in_references:
                reference_end = next((position for position, _, appendix in reading_lines
                                      if position > reference_start and appendix), None)
                selected = [content for position, content, _ in reading_lines
                            if position >= reference_start and (reference_end is None or position < reference_end)]
                if selected:
                    reference_pages.append(page_number + 1)
                    preserved.extend(selected)
                    reference_texts.extend(selected)
                if reference_end is not None:
                    in_references = False
            if page_number < 2:
                # Journal mastheads normally occupy the top quarter of page 1.
                for block in blocks:
                    content = re.sub(r'\s+', ' ', block[4]).strip()
                    lines = [line.strip() for line in block[4].splitlines() if line.strip()]
                    masthead = lines[0] if lines else ''
                    if len(lines) >= 2 and masthead.lower() == 'brain' and lines[1].lower() == 'sciences':
                        masthead = 'Brain Sciences'
                    if block[1] < page.rect.height * .12 and len(content) < 300 and re.search(r'Journal|Transactions|Neurosci|Neural Eng|Brain Sci|Electronics|Nature|Science|Frontiers|Communication|IEEE Access', masthead, re.IGNORECASE):
                        # DOI/year lines often share a block with the masthead;
                        # their presence must not disable journal protection.
                        journals.append(masthead)
                        preserved.append(block[4])
                        preserved.extend(lines)
                # Discover multi-word names in the title/author region while
                # avoiding abstract prose and affiliation/contact blocks.
                abstract_y = page.rect.height * .48
                for block in blocks:
                    if re.match(r'\s*(?:ABSTRACT|Abstract)\b', block[4]):
                        abstract_y = min(abstract_y, block[1])
                for block in blocks:
                    if page_number != 0:
                        continue
                    clean = clean_blocks.get(tuple(block[:4]), block[4])
                    content = re.sub(r'\s+', ' ', clean).strip()
                    if not (.12 * page.rect.height < block[1] < abstract_y):
                        continue
                    source_block = next((item for item in page_dict.get('blocks', [])
                                         if tuple(item.get('bbox', ())) == tuple(block[:4])), {})
                    block_sizes = [span.get('size', body_size) for line in source_block.get('lines', [])
                                   for span in line.get('spans', []) if not span.get('flags', 0) & 1]
                    if '?' in content or (block_sizes and max(block_sizes) > body_size * 1.25):
                        continue
                    if re.search(r'University|Institute|School|Department|Laboratory|Correspond|https?://|@|Review|Survey|Analysis|classification|Article|Received|Accepted|Published', content, re.IGNORECASE):
                        continue
                    names = re.findall(r'\b[A-ZÀ-ÖØ-Þ][a-zà-öø-ÿ\'-]+(?:\s+[A-ZÀ-ÖØ-Þ][a-zà-öø-ÿ\'-]+){1,3}\b', content)
                    if names and len(content) < 300:
                        authors.extend(names)
                        authors.extend(name.split()[-1] for name in names)
                        preserved.append(block[4])
                        preserved.append(clean)
        text = '\n'.join(full_text)
        authors.extend(re.findall(r'\b([A-ZÀ-ÖØ-Þ][A-Za-zÀ-ÖØ-öø-ÿ\'-]+)\s+et\s+al\.?', text))
        references = '\n'.join(reference_texts)
        authors.extend(re.findall(r'\b([A-ZÀ-ÖØ-Þ][a-zA-ZÀ-ÖØ-öø-ÿ\'-]+),\s*(?:[A-Z]\.\s*){1,4}', references))
        authors.extend(re.findall(r'\b([A-ZÀ-ÖØ-Þ][a-zà-öø-ÿ\'-]+)\s+[A-Z]{1,3}(?=\s*[,;])', references))
        methods.extend(re.findall(r'\b[A-Za-z][A-Za-z0-9]*(?:[-\u2010\u2011][A-Za-z0-9]+)*(?:Net|CNN|RNN|LSTM|Former|former)\b', text))
        # Internal capitals are common in model names such as AlphaBrain,
        # ABraMod and LaBraM; suffix-only matching misses these architectures.
        methods.extend(re.findall(r'\b(?=[A-Za-z0-9-]{3,40}\b)(?=[A-Za-z0-9-]*[a-z])(?=(?:[a-z0-9-]*[A-Z]){3})[A-Za-z][A-Za-z0-9-]+\b', text))
        excluded = {'ABSTRACT', 'ARTICLE', 'REFERENCES', 'KEYWORDS', 'REVIEW', 'INTRODUCTION', 'CONCLUSIONS', 'METHODS', 'RESULTS', 'DISCUSSION', 'ORCID', 'ISSN', 'DOI'}
        methods.extend(value for value in re.findall(r'\b[A-Z][A-Z0-9]{1,14}(?:[-\u2010\u2011][A-Za-z0-9]+)*\b', text) if value not in excluded)
    authors, journals, methods = map(_dedupe, (authors, journals, methods))
    custom = _dedupe(custom_terms or [])
    return {
        'policy_version': POLICY_VERSION,
        'terms': _dedupe(authors + journals + methods + custom),
        'candidates': {'authors': authors, 'journals': journals, 'models_methods': methods, 'custom': custom},
        'preserve_texts': preserved,
        'reference_preserve_texts': reference_texts,
        'preserve_references': True,
        'reference_pages': reference_pages,
        'review_notice': '自动识别是候选规则，可能遗漏或误判；请在翻译前审核、增删作者名、期刊名及方法名。参考文献默认整段保留英文。',
    }


def load_policy(path=None, *, preserve_references=None):
    if not path:
        return TermProtector(preserve_references=True if preserve_references is None else preserve_references)
    payload = json.loads(Path(path).read_text(encoding='utf-8-sig'))
    if isinstance(payload, list):
        payload = {'terms': payload}
    if preserve_references is not None:
        payload['preserve_references'] = preserve_references
    texts = payload.get('preserve_texts', [])
    if not payload.get('preserve_references', True):
        reference_texts = set(payload.get('reference_preserve_texts', []))
        texts = [text for text in texts if text not in reference_texts]
    return TermProtector(terms=payload.get('terms', DEFAULT_TERMS),
                         preserve_texts=texts,
                         preserve_references=payload.get('preserve_references', True))
