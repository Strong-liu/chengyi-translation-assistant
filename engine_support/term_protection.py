"""Local keep-English rules. Automatic discovery is heuristic and reviewable."""

from __future__ import annotations

import hashlib
import json
import re
import statistics
import unicodedata
from pathlib import Path

POLICY_VERSION = 'english-preservation-v3'
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
        if self.preserve_references and re.match(r'^\s*(?:references|bibliography|参考文献)\s*$', text, re.IGNORECASE):
            return True
        if self.preserve_references:
            # A bibliography entry remains English in its entirety, including
            # title, authors, journal, year, volume, DOI and citation markers.
            starts_number = re.match(r'^\s*(?:\[\s*\d{1,3}\s*\]|\d{1,3}\.)\s+', text)
            has_year = re.search(r'\b(?:19|20)\d{2}\b', text)
            has_author = re.search(r'\b[A-ZÀ-ÖØ-Þ][A-Za-zÀ-ÖØ-öø-ÿ\'-]+,\s*(?:[A-Z]\.\s*){1,4}', text)
            if starts_number and has_year and has_author:
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
    return bool(re.match(r'^\s*(?:Appendi(?:x|ces)\b|Supplement(?:ary|al)\b|[A-Z](?:\.\d+)*\s*\n\s*[A-Z][A-Za-z -]{5,})', text))


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
            reference_y = None
            reference_end_y = None
            if in_references:
                for block in blocks:
                    if _appendix_heading(block[4]):
                        reference_end_y = block[1]
                        break
            for line in page_dict.get('blocks', []):
                for item in line.get('lines', []):
                    content = ''.join(span.get('text', '') for span in item.get('spans', []))
                    # A table column named "References" near the beginning of
                    # a survey is not the bibliography section heading.
                    # Many conference papers put a long appendix after their
                    # bibliography. The bibliography need not be in the latter
                    # half of the complete PDF. Require bibliographic content
                    # after early headings instead of assuming document order.
                    following = text[text.find(content) + len(content):]
                    bibliography_context = (len(re.findall(r'\b(?:19|20)\d{2}\b', following[:5000])) >= 2
                                            and re.search(r'doi\s*:|https?://|Journal|Proceedings|\bvol\.', following[:5000], re.I))
                    eligible_page = (len(document) <= 4 or page_number >= len(document) * .5
                                     or (page_number >= 2 and bibliography_context))
                    if eligible_page and re.fullmatch(r'\s*(?:(?:\d+\.)?\s*)?(References?|Bibliography|Literature cited|参考文献)\s*', content, re.IGNORECASE):
                        reference_y = item['bbox'][1]
            if reference_y is not None:
                in_references = True
            if in_references:
                reference_pages.append(page_number + 1)
                for block in blocks:
                    if ((reference_y is None or block[1] >= reference_y - 2)
                            and (reference_end_y is None or block[1] < reference_end_y - 2)):
                        preserved.append(block[4])
                        reference_texts.append(block[4])
                if reference_end_y is not None:
                    in_references = False
                    if reference_end_y <= min((block[1] for block in blocks), default=0) + 2:
                        reference_pages.pop()
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


def load_policy(path=None):
    if not path:
        return TermProtector()
    payload = json.loads(Path(path).read_text(encoding='utf-8-sig'))
    if isinstance(payload, list):
        payload = {'terms': payload}
    texts = payload.get('preserve_texts', [])
    if not payload.get('preserve_references', True):
        reference_texts = set(payload.get('reference_preserve_texts', []))
        texts = [text for text in texts if text not in reference_texts]
    return TermProtector(terms=payload.get('terms', DEFAULT_TERMS),
                         preserve_texts=texts,
                         preserve_references=payload.get('preserve_references', True))
