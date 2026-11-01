"""Optional full-engine regression using synthetic PDFs and a fake Baidu API.

Requires the complete application runtime and bundled BabelDOC assets. No real
translation credentials are read, and no translation service request is sent.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--assets', type=Path, default=ROOT / 'build/payload/assets')
    parser.add_argument('--output', type=Path, default=ROOT / 'build/engine-reference-smoke')
    options = parser.parse_args()
    output = options.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    os.environ['PDFMT_BABELDOC_ASSETS'] = str(options.assets.resolve())
    os.environ['BABELDOC_CACHE_DIR'] = str(options.assets.resolve())
    os.environ['PDFMT_CACHE_DIR'] = str(output / 'cache')
    import pymupdf
    from engine_support import run_engine
    from engine_support.baidu_academic import BaiduAcademicClient, BaiduConfig
    from engine_support.term_protection import TOKEN_RE, discover_protected_terms

    input_pdf = output / 'synthetic-reference-paper.pdf'
    references = [
        f'[{number}] A. Example, "Synthetic bibliography entry {number}," '
        f'Journal for Testing, vol. 2, pp. 10-20, {2020 + number}.'
        for number in range(1, 7)
    ]
    with pymupdf.open() as document:
        page = document.new_page()
        page.insert_text((50, 90), 'Synthetic reference preservation regression', fontsize=15)
        page.insert_textbox(pymupdf.Rect(50, 160, 545, 280),
                            'This main paragraph must be translated. The EEGNet model '
                            'is used as an English name in this synthetic software test.', fontsize=11)
        # The right column starts its bibliography while the left column still
        # contains body prose, even below the bibliography heading's Y value.
        page.insert_textbox(pymupdf.Rect(50, 350, 280, 440),
                            'The left column paragraph continues the main discussion '
                            'and must be translated.', fontsize=10)
        page.insert_textbox(pymupdf.Rect(50, 475, 280, 555),
                            'An additional body paragraph remains in the left column '
                            'before the bibliography in reading order.', fontsize=10)
        page.insert_text((325, 300), '4. R E F E R E N C E S', fontsize=10)
        for index, reference in enumerate(references[:4]):
            page.insert_textbox(pymupdf.Rect(325, 340 + index * 55, 555, 388 + index * 55),
                                reference, fontsize=8)
        page = document.new_page()
        for index, reference in enumerate(references[4:]):
            page.insert_text((50, 90 + index * 40), reference, fontsize=8)
        page.insert_text((50, 270), 'Appendix A', fontsize=14)
        page.insert_textbox(pymupdf.Rect(50, 320, 545, 460),
                            'This appendix paragraph must be translated. It describes '
                            'additional observations from the synthetic software test.', fontsize=11)
        document.save(input_pdf)

    policy = discover_protected_terms(input_pdf)
    # Simulate an older saved task that had disabled reference preservation.
    policy['preserve_references'] = False
    policy_path = output / 'legacy-policy.json'
    policy_path.write_text(json.dumps(policy, ensure_ascii=False), encoding='utf-8')
    queries, clients, events = [], [], []

    class FakeResponse:
        status_code = 200

        def __init__(self, query):
            self.query = query

        def json(self):
            # Keep every protected token; linguistic quality is outside this
            # offline test, which checks the real PDF engine's preservation.
            translated = '这是一段用于软件回归验证的中文译文。' + ' '.join(TOKEN_RE.findall(self.query))
            return {'trans_result': [{'src': self.query, 'dst': translated}]}

    class FakeSession:
        trust_env = False

        def post(self, url, **kwargs):
            query = kwargs['json']['q']
            queries.append(query)
            return FakeResponse(query)

    def create_client(config, protector, cache_path):
        client = BaiduAcademicClient(config, protector, None,
                                     session_factory=FakeSession, sleep=lambda _: None)
        clients.append(client)
        return client

    args = SimpleNamespace(input=input_pdf, output=output / 'output', terms=policy_path,
                           engine_dir=ROOT / 'engine')
    config = BaiduConfig(service_mode='llm', api_key='offline-test-not-a-real-key', qps=10)
    with patch.object(run_engine, 'BaiduAcademicClient', side_effect=create_client), \
            patch.object(run_engine, 'emit', side_effect=events.append):
        asyncio.run(run_engine.translate(args, config))
    assert events[-1]['type'] == 'finish', events[-1]
    assert clients[0].protector.preserve_references is True
    requests = '\n'.join(queries)
    assert 'main paragraph' in requests, queries
    assert 'left column paragraph' in requests, queries
    assert 'appendix paragraph' in requests, queries
    assert 'bibliography entry' not in requests, queries
    norm = lambda text: re.sub(r'[^A-Za-z0-9]', '', text).lower()
    with pymupdf.open(events[-1]['mono']) as translated:
        assert len(translated) == 2
        text = norm(''.join(page.get_text() for page in translated))
        for reference in references:
            assert norm(reference) in text, reference
    report = {'result': 'PASS', 'real_translation_api': False,
              'reference_entries_preserved': len(references),
              'main_and_appendix_translated': True, 'left_column_body_translated': True, 'pages': 2,
              'mock_requests': len(queries), 'stats': clients[0].stats}
    (output / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False))


if __name__ == '__main__':
    main()
