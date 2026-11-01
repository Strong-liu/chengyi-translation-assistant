import copy
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from paragraph_preservation import preserve_original_paragraphs
from run_engine import load_or_discover_policy
from term_protection import POLICY_VERSION, TermProtector


class FakeTranslator:
    def __init__(self, config):
        self.translation_config = config
        self.preprocess_calls = []

    def pre_translate_paragraph(self, paragraph, tracker=None, page_font_map=None, xobj_font_map=None):
        self.preprocess_calls.append(paragraph)
        # Model the PDF engine replacing the citation number before the backend
        # sees it. The bibliography check must run before this mutation.
        text = paragraph.unicode.replace('[1]', '{v1}')
        return text, SimpleNamespace(unicode=text)


class OriginalParagraphPreservationTests(unittest.TestCase):
    def setUp(self):
        self.config = SimpleNamespace()
        self.protector = TermProtector(['CNN'])
        self.reference = SimpleNamespace(
            unicode='[1] Kuo, S. M. Active noise control. IEEE Journal 1999, 87, 943–973.',
            composition=['original PDF characters and fonts'],
        )

    def test_reference_is_skipped_before_placeholder_conversion_without_mutating_layout(self):
        translator = FakeTranslator(self.config)
        retained = []
        composition = self.reference.composition
        original_text = self.reference.unicode
        with preserve_original_paragraphs(FakeTranslator, self.config, self.protector,
                                         on_preserved=lambda: retained.append(True)):
            result = translator.pre_translate_paragraph(self.reference)
        self.assertEqual(result, (None, None))
        self.assertEqual(translator.preprocess_calls, [])
        self.assertEqual(self.reference.unicode, original_text)
        self.assertIs(self.reference.composition, composition)
        self.assertEqual(retained, [True])

    def test_body_and_appendix_paragraphs_continue_through_original_preprocessing(self):
        translator = FakeTranslator(self.config)
        with preserve_original_paragraphs(FakeTranslator, self.config, self.protector):
            for text in ('The CNN model reduces noise by 10 percent.',
                         'Appendix A explains the experiment in more detail.'):
                paragraph = SimpleNamespace(unicode=text)
                result, translate_input = translator.pre_translate_paragraph(
                    paragraph, tracker=None, page_font_map={}, xobj_font_map={})
                self.assertEqual(result, text)
                self.assertEqual(translate_input.unicode, text)
        self.assertEqual(len(translator.preprocess_calls), 2)

    def test_unrelated_configuration_is_not_guarded(self):
        other_translator = FakeTranslator(SimpleNamespace())
        with preserve_original_paragraphs(FakeTranslator, self.config, self.protector):
            result, _ = other_translator.pre_translate_paragraph(self.reference)
        self.assertTrue(result.startswith('{v1}'))
        self.assertEqual(len(other_translator.preprocess_calls), 1)

    def test_split_configuration_copy_keeps_guard(self):
        with preserve_original_paragraphs(FakeTranslator, self.config, self.protector):
            part_config = copy.copy(self.config)
            part_translator = FakeTranslator(part_config)
            self.assertEqual(part_translator.pre_translate_paragraph(self.reference), (None, None))
        self.assertEqual(part_translator.preprocess_calls, [])

    def test_exception_restores_method_and_configuration(self):
        original = FakeTranslator.pre_translate_paragraph
        before = vars(self.config).copy()
        with self.assertRaisesRegex(RuntimeError, 'test cancellation'):
            with preserve_original_paragraphs(FakeTranslator, self.config, self.protector):
                raise RuntimeError('test cancellation')
        self.assertIs(FakeTranslator.pre_translate_paragraph, original)
        self.assertEqual(vars(self.config), before)

    def test_nested_translations_restore_previous_guard(self):
        original = FakeTranslator.pre_translate_paragraph
        other_config = SimpleNamespace()
        first_translator = FakeTranslator(self.config)
        second_translator = FakeTranslator(other_config)
        with preserve_original_paragraphs(FakeTranslator, self.config, self.protector):
            with preserve_original_paragraphs(FakeTranslator, other_config, self.protector):
                self.assertEqual(first_translator.pre_translate_paragraph(self.reference), (None, None))
                self.assertEqual(second_translator.pre_translate_paragraph(self.reference), (None, None))
            self.assertEqual(first_translator.pre_translate_paragraph(self.reference), (None, None))
            self.assertTrue(second_translator.pre_translate_paragraph(self.reference)[0].startswith('{v1}'))
        self.assertIs(FakeTranslator.pre_translate_paragraph, original)


class ReviewedPolicyMigrationTests(unittest.TestCase):
    body_text = 'The experiment compares the two methods and explains the results.'
    reference_text = 'A source citation whose bibliography region must remain unchanged.'

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.args = SimpleNamespace(terms=self.root / 'reviewed.json', input=self.root / 'input.pdf',
                                    output=self.root / 'output')
        self.terms = ['CustomNet', 'Reviewed Author']
        self.fresh_policy = {
            'policy_version': POLICY_VERSION,
            'terms': ['UnreviewedAutoNet'],
            'preserve_texts': [self.reference_text],
            'reference_preserve_texts': [self.reference_text],
            'preserve_references': True,
            'reference_pages': [2],
        }

    def write_policy(self, payload):
        self.args.terms.write_text(json.dumps(payload), encoding='utf-8')

    def test_v3_region_migration_preserves_reviewed_terms_without_freezing_body(self):
        self.write_policy({
            'policy_version': 'english-preservation-v3',
            'terms': self.terms,
            # Simulate an old column/Y-coordinate mistake which protected body
            # text solely because it was lower than the other column's heading.
            'preserve_texts': [self.body_text],
            'reference_preserve_texts': [self.body_text],
            'preserve_references': False,
        })
        original_review = self.args.terms.read_bytes()
        with patch('run_engine.discover_protected_terms', return_value=self.fresh_policy) as discover:
            protector = load_or_discover_policy(self.args)
        self.assertFalse(protector.should_preserve(self.body_text))
        self.assertTrue(protector.should_preserve(self.reference_text))
        self.assertEqual(set(protector.terms), set(self.terms))
        self.assertTrue(protector.preserve_references)
        discover.assert_called_once_with(self.args.input)
        self.assertEqual(self.args.terms.read_bytes(), original_review)
        generated = json.loads((self.args.output / 'protected_terms.generated.json').read_text(encoding='utf-8'))
        self.assertEqual(generated['policy_version'], POLICY_VERSION)
        self.assertEqual(set(generated['terms']), set(self.terms))
        self.assertEqual(generated['preserve_texts'], [self.reference_text])

    def test_current_policy_keeps_custom_preserved_blocks_without_rediscovery(self):
        self.write_policy({
            'policy_version': POLICY_VERSION,
            'terms': self.terms,
            'preserve_texts': [self.body_text, self.reference_text],
            'reference_preserve_texts': [self.reference_text],
            'preserve_references': False,
        })
        with patch('run_engine.discover_protected_terms', side_effect=AssertionError('Unexpected discovery')) as discover:
            protector = load_or_discover_policy(self.args)
        self.assertTrue(protector.should_preserve(self.body_text))
        self.assertTrue(protector.should_preserve(self.reference_text))
        self.assertEqual(set(protector.terms), set(self.terms))
        self.assertTrue(protector.preserve_references)
        discover.assert_not_called()

    def test_legacy_list_policy_gains_fresh_reference_regions_without_changing_terms(self):
        self.write_policy(self.terms)
        with patch('run_engine.discover_protected_terms', return_value=self.fresh_policy) as discover:
            protector = load_or_discover_policy(self.args)
        self.assertTrue(protector.should_preserve(self.reference_text))
        self.assertFalse(protector.should_preserve(self.body_text))
        self.assertEqual(set(protector.terms), set(self.terms))
        discover.assert_called_once_with(self.args.input)

    def test_unversioned_dictionary_gains_current_reference_regions(self):
        self.write_policy({'terms': self.terms, 'preserve_texts': [self.body_text]})
        with patch('run_engine.discover_protected_terms', return_value=self.fresh_policy):
            protector = load_or_discover_policy(self.args)
        self.assertFalse(protector.should_preserve(self.body_text))
        self.assertTrue(protector.should_preserve(self.reference_text))
        self.assertEqual(set(protector.terms), set(self.terms))


if __name__ == '__main__':
    unittest.main()
