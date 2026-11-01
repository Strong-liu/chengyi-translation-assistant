import json
import tempfile
import unittest
from pathlib import Path

from baidu_academic import ENDPOINT, BaiduAcademicClient, BaiduAPIError, BaiduConfig, make_sign, split_utf8
from term_protection import ProtectionError, TOKEN_RE, TermProtector, discover_protected_terms, load_policy


class FakeResponse:
    status_code = 200

    def __init__(self, payload):
        self.payload = payload

    def json(self):
        return self.payload


class FakeSession:
    def __init__(self, transform=lambda text: text, responses=None):
        self.calls = []
        self.transform = transform
        self.responses = list(responses or [])
        self.trust_env = None

    def post(self, url, data, timeout):
        self.calls.append((url, data, timeout))
        if self.responses:
            return FakeResponse(self.responses.pop(0))
        return FakeResponse({'trans_result': [{'src': data['q'], 'dst': self.transform(data['q'])}]})


class BackendTests(unittest.TestCase):
    def config(self, **kwargs):
        return BaiduConfig('test-app', 'very-secret', qps=10, **kwargs)

    def client(self, fake, protector=None, cache_path=None):
        client = BaiduAcademicClient(self.config(), protector=protector, cache_path=cache_path,
                                     session_factory=lambda: fake, sleep=lambda _: None)
        self.addCleanup(client.close)
        return client

    def test_official_domain_signature_includes_unicode_and_domain(self):
        self.assertEqual(make_sign('test-app', 'Hello学术', 'salt', 'very-secret'), '9777c2834ae03f6fbeb1ca31b89b8bdd')

    def test_fixed_academic_endpoint_and_signature_data(self):
        fake = FakeSession(lambda text: text.replace('outperforms', '优于'))
        client = self.client(fake, TermProtector(['EEGNet', 'ResNet']))
        result = client.translate('EEGNet outperforms ResNet.')
        self.assertEqual(result, 'EEGNet 优于 ResNet.')
        url, data, timeout = fake.calls[0]
        self.assertEqual(url, ENDPOINT)
        self.assertEqual(data['domain'], 'academic')
        self.assertEqual(data['from'], 'en')
        self.assertEqual(data['to'], 'zh')
        self.assertEqual(data['sign'], make_sign(data['appid'], data['q'], data['salt'], 'very-secret'))
        self.assertNotIn('EEGNet', data['q'])
        self.assertEqual(timeout, (10, 45))
        self.assertFalse(fake.trust_env)

    def test_lossless_utf8_splitting_and_protect_token_boundaries(self):
        text = '模型保留 English words. ' * 1300 + 'ZXQPT000000ZXQ' + '继续翻译' * 1000
        chunks = split_utf8(text, 500)
        self.assertEqual(''.join(chunks), text)
        self.assertTrue(all(len(chunk.encode('utf-8')) <= 500 for chunk in chunks))
        self.assertTrue(any('ZXQPT000000ZXQ' in chunk for chunk in chunks))

    def test_proper_names_models_journals_and_formula_restore_exactly(self):
        protector = TermProtector(['John Smith', 'IEEE Access', 'bi-SiamCA', 'Transformer'])
        text = 'John Smith uses bi‑SiamCA and Transformer in IEEE Access {v12}.'
        masked, mapping = protector.mask(text)
        self.assertNotIn('John Smith', masked)
        restored = protector.restore(masked.lower(), mapping)
        self.assertEqual(restored, text)

    def test_missing_or_duplicated_marker_is_rejected(self):
        protector = TermProtector(['EEGNet'])
        masked, mapping = protector.mask('The EEGNet model is useful.')
        for damaged in (TOKEN_RE.sub('', masked), masked + ' ' + next(iter(mapping))):
            with self.assertRaises(ProtectionError):
                protector.restore(damaged, mapping)

    def test_unknown_malformed_marker_is_never_exported(self):
        protector = TermProtector(['EEGNet'])
        masked, mapping = protector.mask('The EEGNet method is useful.')
        with self.assertRaises(ProtectionError):
            protector.restore(masked + ' ZXQPTbroken', mapping)

    def test_reference_blocks_can_be_merged_by_layout_without_translation(self):
        protector = TermProtector(['EEGNet'], ['Jane Doe and John Smith.', ' A model. Journal 2020.'])
        self.assertTrue(protector.should_preserve('Jane Doe and John Smith. A model. Journal 2020.'))

    def test_reference_entry_and_known_author_blocks_are_not_sent(self):
        text = '23. Lawhern, V.J.; Solon, A.J. EEGNet: a compact CNN. J. Neural Eng. 2018, 15, 056013.'
        fake = FakeSession()
        client = self.client(fake, TermProtector(['EEGNet'], ['John Smith, Jane Doe']))
        self.assertEqual(client.translate(text), text)
        self.assertEqual(client.translate('John Smith, Jane Doe'), 'John Smith, Jane Doe')
        self.assertEqual(fake.calls, [])

    def test_initials_first_and_surname_first_references_are_not_sent(self):
        entries = [
            '[1] S. M. Smith, "A technical review," IEEE Trans. Example, vol. 8, pp. 12-20, 2020.',
            '[2]W.-S. Smith and A. Doe, "A technical method," Proc. Example Conf., 2021, pp. 1-5.',
            '1001. Smith, J.; Doe, A. A model. J. Example 2022, 15, 056013.',
            '[1002] J. van Smith, "A technical book," Example Press, 2019.',
            '1003) Smith J, Doe A. A technical study. Journal 2023; 12:100-110.',
        ]
        fake = FakeSession()
        client = self.client(fake, TermProtector(['ExampleNet']))
        for text in entries:
            with self.subTest(text=text):
                self.assertEqual(client.translate(text), text)
        self.assertEqual(fake.calls, [])

    def test_long_merged_bibliography_is_preserved_before_masking(self):
        text = ' '.join(
            f'[{index}] A. Smith and J. Doe, "A model {index}," IEEE Example, vol. 9, pp. 1-5, 2020.'
            for index in range(1, 61)
        )
        fake = FakeSession()
        client = self.client(fake, TermProtector(['Smith', 'Doe', 'IEEE Example']))
        self.assertEqual(client.translate(text), text)
        self.assertEqual(fake.calls, [])
        self.assertEqual(client.stats['preserved_paragraphs'], 1)

    def test_unnumbered_reference_needs_author_and_publication_details(self):
        protector = TermProtector()
        for text in (
            'J. Smith and A. Doe, "A technical study," IEEE Example, vol. 4, pp. 1-8, 2020.',
            'Smith, J. (2021). A technical study. Example Methods, 12(3), 100-110.',
            'Smith J, Doe A. A model. doi: 10.1234/example. 2022.',
        ):
            with self.subTest(text=text):
                self.assertTrue(protector.should_preserve(text))
        self.assertFalse(protector.should_preserve('J. Smith demonstrated the benefits of this approach in 2020.'))

    def test_reference_titles_include_numbered_and_letter_spaced_headings(self):
        protector = TermProtector()
        for heading in ('R E F E R E N C E S', 'VII. REFERENCES', '7. References',
                        '7.1 Bibliography', 'L I T E R A T U R E  C I T E D', 'References:'):
            with self.subTest(heading=heading):
                self.assertTrue(protector.should_preserve(heading))
        self.assertFalse(TermProtector(preserve_references=False).should_preserve('VII. REFERENCES'))

    def test_citations_in_prose_captions_and_appendices_are_translatable(self):
        protector = TermProtector()
        for text in (
            '[1] This paragraph compares Smith, J. with other authors in 2020.',
            '[2] The model introduced in 2021 is described in IEEE Example.',
            'Fig. 1. S. M. Smith introduced the baseline in 2020.',
            'Appendix A. Additional analysis of the 2020 model.',
            'References to earlier work are discussed in Section 2.',
        ):
            with self.subTest(text=text):
                self.assertFalse(protector.should_preserve(text))

    def test_failed_protection_does_not_write_cache(self):
        fake = FakeSession(lambda text: TOKEN_RE.sub('', text))
        client = self.client(fake, TermProtector(['EEGNet']))
        with self.assertRaises(ProtectionError):
            client.translate('The EEGNet model performs well.')
        self.assertEqual(client.cache.connection.execute('SELECT count(*) FROM translations').fetchone()[0], 0)
        self.assertEqual(client.errors, ['ProtectionError'])

    def test_author_led_body_with_conference_and_year_is_translatable(self):
        text = 'J. Smith introduced the baseline at IEEE ICASSP in 2020, and our method improves it.'
        self.assertFalse(TermProtector().should_preserve(text))

    def test_right_column_references_do_not_freeze_lower_left_column_body(self):
        import pymupdf
        body = 'Left column body remains translatable.'
        reference = '[1] J. Smith, A study. Journal 2020, vol. 4, pp. 1-5.'
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'right-reference.pdf'
            with pymupdf.open() as document:
                page = document.new_page()
                page.insert_text((50, 200), 'An earlier left column paragraph.', fontsize=8)
                page.insert_text((50, 350), body, fontsize=8)
                page.insert_text((330, 300), 'REFERENCES', fontsize=10)
                page.insert_text((330, 350), reference, fontsize=7)
                document.save(path)
            report = discover_protected_terms(path)
            protected = TermProtector(report['terms'], report['preserve_texts'])
            self.assertFalse(protected.should_preserve(body))
            self.assertTrue(protected.should_preserve(reference))

    def test_left_column_reference_start_keeps_upper_right_continuation_and_stops_at_appendix(self):
        import pymupdf
        continuation = 'Continuation title with publication details in 2021.'
        appendix = 'This right column appendix remains translatable.'
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'left-reference.pdf'
            with pymupdf.open() as document:
                page = document.new_page()
                page.insert_text((50, 200), 'Ordinary left column body paragraph.', fontsize=8)
                page.insert_text((50, 500), 'REFERENCES', fontsize=10)
                page.insert_text((50, 540), '[1] J. Smith, A study. Journal 2020, vol. 4.', fontsize=7)
                page.insert_text((330, 150), continuation, fontsize=7)
                page.insert_text((330, 300), 'APPENDIX A', fontsize=10)
                page.insert_text((330, 350), appendix, fontsize=7)
                page = document.new_page()
                page.insert_text((50, 200), 'The following page continues the appendix.')
                document.save(path)
            report = discover_protected_terms(path)
            protected = TermProtector(report['terms'], report['preserve_texts'])
            self.assertTrue(protected.should_preserve(continuation))
            self.assertFalse(protected.should_preserve(appendix))
            self.assertFalse(protected.should_preserve('The following page continues the appendix.'))

    def test_retries_rate_limit_then_returns_academic_result(self):
        fake = FakeSession(responses=[{'error_code': '54003'}, {'trans_result': [{'dst':'这是一项研究。'}]}])
        client = self.client(fake, TermProtector(['EEGNet']))
        self.assertEqual(client.translate('This is a study.'), '这是一项研究。')
        self.assertEqual(len(fake.calls), 2)
        self.assertTrue(all(call[1]['domain'] == 'academic' for call in fake.calls))

    def test_auth_error_does_not_fallback_or_retry(self):
        fake = FakeSession(responses=[{'error_code':'54001','error_msg':'Invalid Sign'}])
        client = self.client(fake)
        with self.assertRaises(BaiduAPIError) as caught:
            client.translate('A controlled test sentence.')
        self.assertNotIn('very-secret', str(caught.exception))
        self.assertEqual(len(fake.calls), 1)

    def test_cache_reuses_translation_and_excludes_credentials(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'cache.sqlite3'
            fake = FakeSession(lambda text: text.replace('outperforms', '优于'))
            client = self.client(fake, TermProtector(['EEGNet', 'ResNet']), path)
            text = 'EEGNet outperforms ResNet.'
            self.assertEqual(client.translate(text), client.translate(text))
            self.assertEqual(len(fake.calls), 1)
            self.assertEqual(client.stats['cache_hits'], 1)
            self.assertNotIn(b'very-secret', path.read_bytes())
            self.assertNotIn(b'test-app', path.read_bytes())
            client.close()
            # Remove the registered cleanup because this connection is closed.
            self._cleanups.pop()

    def test_policy_changes_do_not_reuse_other_protection_results(self):
        first = TermProtector(['EEGNet'])
        second = TermProtector(['EEGNet', 'ResNet'])
        self.assertNotEqual(first.fingerprint, second.fingerprint)

    def test_discovery_finds_author_model_and_reference_zone(self):
        import pymupdf
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'source.pdf'
            document = pymupdf.open()
            document.set_metadata({'title':'A technical paper','author':'John Smith; Jane Doe'})
            page = document.new_page()
            page.insert_text((50, 40), 'IEEE Access')
            page.insert_text((50, 100), 'A technical paper')
            page.insert_text((50, 140), 'John Smith and Jane Doe')
            page.insert_text((50, 270), 'Abstract: EEGNet and bi-SiamCA improve classification.')
            page.insert_text((50, 420), 'Smith et al. evaluated Transformer and TRCA.')
            page.insert_text((50, 550), 'References')
            page.insert_text((50, 580), '1. Lawhern, V.J. EEGNet. J. Neural Eng. 2018, 15, 056013.')
            document.save(path)
            document.close()
            report = discover_protected_terms(path, ['MyMethod'])
            self.assertIn('John Smith', report['terms'])
            self.assertIn('Jane Doe', report['terms'])
            self.assertIn('MyMethod', report['terms'])
            self.assertIn('EEGNet', report['terms'])
            self.assertIn('IEEE Access', report['terms'])
            self.assertEqual(report['reference_pages'], [1])
            protector = TermProtector(report['terms'], report['preserve_texts'])
            self.assertTrue(protector.should_preserve('1. Lawhern, V.J. EEGNet. J. Neural Eng. 2018, 15, 056013.'))

    def test_discovery_ignores_author_superscripts_and_keeps_journal_with_doi(self):
        import pymupdf
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'publisher.pdf'
            with pymupdf.open() as document:
                page = document.new_page()
                image = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 2, 2), False)
                image.clear_with(255)
                page.insert_image(pymupdf.Rect(400, 10, 420, 30), pixmap=image)
                page.insert_text((50, 40), 'BRAIN-APPARATUS COMMUNICATION: A JOURNAL OF BACOMICS\n2023, VOL. 2\nhttps://doi.org/10.1080/example', fontsize=8)
                page.insert_text((50, 130), 'A survey of technical methods')
                page.insert_text((50, 160), 'Yudong Pan', fontsize=11)
                # The smaller raised span is extracted as superscript "a".
                page.insert_text((111, 156), 'a', fontsize=7)
                page.insert_text((50, 260), 'Abstract: A technical study.')
                document.save(path)
            report = discover_protected_terms(path)
            self.assertIn('Yudong Pan', report['candidates']['authors'])
            self.assertNotIn('Yudong Pana', report['candidates']['authors'])
            self.assertIn('BRAIN-APPARATUS COMMUNICATION: A JOURNAL OF BACOMICS', report['candidates']['journals'])
            protector = TermProtector(report['terms'], report['preserve_texts'])
            self.assertTrue(protector.should_preserve('Yudong Pan'))
            self.assertTrue(protector.should_preserve('BRAIN-APPARATUS COMMUNICATION: A JOURNAL OF BACOMICS'))

    def test_discovery_handles_early_bibliography_then_translatable_appendices(self):
        import pymupdf
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'synthetic.pdf'
            with pymupdf.open() as document:
                for index in range(12):
                    page = document.new_page()
                    if index == 0:
                        page.insert_text((50, 120), 'What Do Technical Models Learn?', fontsize=20)
                        page.insert_text((50, 175), 'John Smith and Jane Doe', fontsize=11)
                        page.insert_text((50, 260), 'Abstract: ABraMod and LaBraM are evaluated.', fontsize=11)
                    elif index == 2:
                        page.insert_text((50, 80), 'References')
                        page.insert_text((50, 120), 'John Smith. A model. Journal 2020. doi: 10.1234/example1')
                        page.insert_text((50, 150), 'Jane Doe. Another model. Journal 2021. doi: 10.1234/example2')
                    elif index == 3:
                        page.insert_text((50, 80), 'Tom Jones. A last model. Journal 2022. doi: 10.1234/example3')
                    elif index == 4:
                        page.insert_text((50, 80), 'A\nA technical appendix')
                        page.insert_text((50, 130), 'This appendix explains the detailed analysis.')
                    else:
                        page.insert_text((50, 200), 'This is regular manuscript prose.')
                document.save(path)
            policy = discover_protected_terms(path)
            self.assertEqual(policy['reference_pages'], [3, 4])
            self.assertIn('John Smith', policy['candidates']['authors'])
            self.assertNotIn('What Do Technical Models Learn', policy['candidates']['authors'])
            self.assertIn('ABraMod', policy['candidates']['models_methods'])
            self.assertIn('LaBraM', policy['candidates']['models_methods'])
            policy_path = Path(folder) / 'policy.json'
            policy_path.write_text(json.dumps(policy), encoding='utf-8')
            protector = load_policy(policy_path)
            self.assertTrue(protector.should_preserve('John Smith. A model. Journal 2020. doi: 10.1234/example1'))
            self.assertFalse(protector.should_preserve('This appendix explains the detailed analysis.'))
            policy['preserve_references'] = False
            policy_path.write_text(json.dumps(policy), encoding='utf-8')
            self.assertFalse(load_policy(policy_path).should_preserve('John Smith. A model. Journal 2020. doi: 10.1234/example1'))

    def test_discovery_finds_letter_spaced_numbered_reference_heading(self):
        import pymupdf
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'synthetic.pdf'
            with pymupdf.open() as document:
                page = document.new_page()
                page.insert_text((50, 90), 'This is regular manuscript prose.')
                page.insert_text((50, 300), 'VII. R E F E R E N C E S')
                page.insert_text((50, 340), '[1] J. Smith, A model. Journal 2020, vol. 4, pp. 1-5.')
                page = document.new_page()
                page.insert_text((50, 90), 'Appendix A')
                page.insert_text((50, 150), 'This appendix explains the detailed analysis.')
                document.save(path)
            policy = discover_protected_terms(path)
            self.assertEqual(policy['reference_pages'], [1])
            self.assertTrue(any('J. Smith' in block for block in policy['reference_preserve_texts']))
            protector = TermProtector(policy['terms'], policy['preserve_texts'])
            self.assertFalse(protector.should_preserve('This is regular manuscript prose.'))
            self.assertFalse(protector.should_preserve('This appendix explains the detailed analysis.'))

    def test_policy_reference_override_preserves_old_disabled_task_blocks(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'policy.json'
            reference = 'An organization. A technical report. Journal 2020.'
            author = 'Jane Doe and John Smith'
            path.write_text(json.dumps({
                'terms': ['ExampleNet'], 'preserve_references': False,
                'preserve_texts': [author, reference], 'reference_preserve_texts': [reference],
            }), encoding='utf-8')
            self.assertFalse(load_policy(path).should_preserve(reference))
            overridden = load_policy(path, preserve_references=True)
            self.assertTrue(overridden.preserve_references)
            self.assertTrue(overridden.should_preserve(reference))
            self.assertTrue(overridden.should_preserve(author))
            self.assertFalse(load_policy(preserve_references=False).preserve_references)

    def test_discovery_keeps_same_page_appendix_translatable(self):
        import pymupdf
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'synthetic.pdf'
            with pymupdf.open() as document:
                page = document.new_page()
                page.insert_text((50, 90), 'This is regular manuscript prose.')
                page.insert_text((50, 300), '4. R E F E R E N C E S')
                page.insert_text((50, 340), '[1] J. Smith, A model. Journal 2020, vol. 4, pp. 1-5.')
                page.insert_text((50, 450), 'APPENDIX A')
                page.insert_text((50, 500), 'This appendix explains the detailed analysis.')
                document.save(path)
            policy = discover_protected_terms(path)
            self.assertEqual(policy['reference_pages'], [1])
            self.assertFalse(any('appendix' in block.lower() for block in policy['reference_preserve_texts']))
            protector = TermProtector(policy['terms'], policy['preserve_texts'])
            self.assertFalse(protector.should_preserve('This appendix explains the detailed analysis.'))

    def test_translation_failures_are_not_double_counted_as_export_failures(self):
        import logging
        from run_engine import ExportErrorCounter
        handler = ExportErrorCounter()
        handler.emit(logging.LogRecord('test', logging.ERROR, '', 0, 'Error translating paragraph', (), None))
        self.assertEqual(handler.translation_count, 1)
        self.assertEqual(handler.count, 0)
        handler.emit(logging.LogRecord('test', logging.ERROR, '', 0, 'Unable to export paragraphs', (), None))
        self.assertEqual(handler.count, 1)


if __name__ == '__main__':
    unittest.main(verbosity=2)
