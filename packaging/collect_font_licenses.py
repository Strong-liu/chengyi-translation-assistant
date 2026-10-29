"""Collect the license and copyright records embedded in bundled fonts."""

import sys
from pathlib import Path

from fontTools.ttLib import TTFont


def main():
    payload = Path(sys.argv[1]).resolve()
    sections = [
        'Bundled font copyright and license notices',
        'These records are copied from the font name tables of the distributed font files.',
    ]
    for path in sorted((payload / 'assets' / 'fonts').glob('*.ttf')):
        values = {0: set(), 13: set(), 14: set()}
        with TTFont(path, lazy=True) as font:
            for record in font['name'].names:
                if record.nameID in values:
                    try:
                        text = record.toUnicode().strip()
                        if text:
                            values[record.nameID].add(text)
                    except UnicodeError:
                        pass
        sections.append('\n' + '=' * 72 + '\n' + path.name)
        for key, label in [(0, 'Copyright'), (13, 'License'), (14, 'License URL')]:
            for value in sorted(values[key]):
                sections.append(label + ':\n' + value)
    output = payload / 'FONT_LICENSES.txt'
    output.write_text('\n\n'.join(sections) + '\n', encoding='utf-8')
    print('Collected bundled-font notices:', output)


if __name__ == '__main__':
    main()
