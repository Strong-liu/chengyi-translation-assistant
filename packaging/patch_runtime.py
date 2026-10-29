"""Apply the readable, version-pinned BabelDOC compatibility changes."""
from __future__ import annotations

import argparse
import shutil
from pathlib import Path


def patch_runtime(site_packages: Path):
    package = site_packages / 'babeldoc'
    constants = package / 'const.py'
    text = constants.read_text(encoding='utf-8')
    if '__version__ = "0.6.4"' not in text:
        raise RuntimeError('This compatibility patch requires BabelDOC 0.6.4.')
    original = 'CACHE_FOLDER = Path.home() / ".cache" / "babeldoc"'
    replacement = 'CACHE_FOLDER = Path(os.environ.get("BABELDOC_CACHE_DIR", Path.home() / ".cache" / "babeldoc"))'
    if original in text:
        constants.write_text(text.replace(original, replacement), encoding='utf-8')
    elif replacement not in text:
        raise RuntimeError('Unsupported BabelDOC cache configuration; review before patching.')
    source = Path(__file__).parent / 'patches' / 'babeldoc-0.6.4-typesetting.py'
    target = package / 'format/pdf/document_il/midend/typesetting.py'
    if source.read_bytes() != target.read_bytes():
        shutil.copyfile(source, target)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('site_packages', type=Path)
    patch_runtime(parser.parse_args().site_packages.resolve())
    print('BabelDOC 0.6.4 compatibility patches applied.')
