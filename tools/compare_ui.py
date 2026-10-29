"""Produce an honest pixel overlay/diff, without stretching either input.

Reference coordinates are the approved 1600x1040 SVG canvas's window rectangle.
The screenshot must already show matching content at 1440x900 logical pixels.
For native Retina captures specify --scale 2. Metrics describe differences, not
acceptance: font rasterization, desktop background and fixture parity need review.
"""
import argparse
import json
from pathlib import Path
from PIL import Image, ImageChops, ImageEnhance, ImageStat


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--reference', type=Path, required=True)
    parser.add_argument('--actual', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--scale', type=int, choices=(1, 2), default=1)
    parser.add_argument('--conditions', required=True,
                        help='Record matching or differing data, platform, backdrop and state.')
    args = parser.parse_args()
    reference = Image.open(args.reference).convert('RGB')
    if reference.size != (1600, 1040):
        parser.error('Expected approved 1600x1040 reference; no automatic stretching.')
    reference = reference.crop((80, 70, 1520, 970))
    actual = Image.open(args.actual).convert('RGB')
    expected = (1440 * args.scale, 900 * args.scale)
    if actual.size != expected:
        parser.error(f'Actual image is {actual.size}, expected {expected}; capture at reference size.')
    if args.scale == 2:
        actual = actual.resize(reference.size, Image.Resampling.LANCZOS)
    args.output.mkdir(parents=True, exist_ok=True)
    difference = ImageChops.difference(reference, actual)
    reference.save(args.output / 'reference.png')
    actual.save(args.output / 'actual.png')
    Image.blend(reference, actual, .5).save(args.output / 'overlay.png')
    difference.save(args.output / 'difference.png')
    ImageEnhance.Brightness(difference).enhance(4).save(args.output / 'difference-x4.png')
    result = {'reference': str(args.reference.resolve()), 'actual': str(args.actual.resolve()),
              'conditions': args.conditions, 'scale': args.scale,
              'mean_absolute_rgb_difference': ImageStat.Stat(difference).mean,
              'acceptance': 'not determined by this tool'}
    (args.output / 'comparison.json').write_text(json.dumps(result, ensure_ascii=False, indent=2))
    print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__':
    main()
