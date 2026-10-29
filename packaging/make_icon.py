"""Convert a supplied bitmap to a multi-size Windows ICO without redesigning it."""
import argparse
from pathlib import Path

from PIL import Image


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path)
    parser.add_argument('output', type=Path)
    arguments = parser.parse_args()
    if arguments.output.resolve() == arguments.source.resolve():
        parser.error('Use a separate output path to preserve the original.')
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    with Image.open(arguments.source) as source:
        image = source.convert('RGBA')
        image.thumbnail((256, 256), Image.Resampling.LANCZOS)
        canvas = Image.new('RGBA', (256, 256), (0, 0, 0, 0))
        canvas.alpha_composite(image, ((256 - image.width) // 2, (256 - image.height) // 2))
        canvas.save(arguments.output, format='ICO', sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
