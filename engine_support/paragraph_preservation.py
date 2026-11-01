"""Keep original paragraphs before BabelDOC creates formula/style placeholders."""

from __future__ import annotations

from contextlib import contextmanager
from functools import wraps


_SCOPE_ATTRIBUTE = '_chengyi_original_paragraph_scope'
_MISSING = object()


@contextmanager
def preserve_original_paragraphs(translator_type, config, protector, on_preserved=None):
    """Temporarily guard one translation, including its shallow-copied parts.

    BabelDOC reports the original paragraph in errors, but passes a rewritten
    string to the translation backend. Bibliography numbers and names may have
    become formula placeholders by that point. Skipping at this earlier boundary
    preserves the original paragraph objects and avoids any translation request.

    Split translations copy their configuration with ``copy.copy``. A unique
    marker follows those copies without affecting unrelated configurations.
    The application runs each translation in an isolated engine process.
    """
    original = translator_type.pre_translate_paragraph
    scope = object()
    previous_scope = getattr(config, _SCOPE_ATTRIBUTE, _MISSING)

    @wraps(original)
    def guarded(instance, paragraph, *args, **kwargs):
        current_config = getattr(instance, 'translation_config', None)
        if getattr(current_config, _SCOPE_ATTRIBUTE, None) is scope:
            raw_text = getattr(paragraph, 'unicode', None)
            if isinstance(raw_text, str) and raw_text.strip() and protector.should_preserve(raw_text):
                # Returning no translation input is BabelDOC's existing path
                # for paragraphs which must retain their original composition.
                if on_preserved is not None:
                    on_preserved()
                return None, None
        return original(instance, paragraph, *args, **kwargs)

    setattr(config, _SCOPE_ATTRIBUTE, scope)
    translator_type.pre_translate_paragraph = guarded
    try:
        yield
    finally:
        if translator_type.pre_translate_paragraph is guarded:
            translator_type.pre_translate_paragraph = original
        if getattr(config, _SCOPE_ATTRIBUTE, None) is scope:
            if previous_scope is _MISSING:
                delattr(config, _SCOPE_ATTRIBUTE)
            else:
                setattr(config, _SCOPE_ATTRIBUTE, previous_scope)
