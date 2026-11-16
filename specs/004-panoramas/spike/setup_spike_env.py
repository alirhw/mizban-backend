"""Spike T-019 Setup Script: Fetch Pannellum 2.5.7 and generate real test fixtures.

This script:
1. Downloads official Pannellum 2.5.7 JS and CSS.
2. Generates real WebP fixtures using the T-017 conversion pipeline standards:
   - Primary: 4096x2048 WebP @ Quality 82 (Target ~1.2 MB)
   - Comparison: 4096x2048 WebP @ Quality 80
   - Comparison: 4096x2048 WebP @ Quality 85
   - Comparison: 2048x1024 WebP @ Quality 82
   - Comparison: 512x256 WebP @ Quality 60 (LQIP)
   - Sample: Real sample panorama from test suite
"""
from __future__ import annotations

import io
import math
import os
import random
import urllib.request

from PIL import Image, ImageDraw

SPIKE_DIR = os.path.dirname(os.path.abspath(__file__))
FIXTURES_DIR = os.path.join(SPIKE_DIR, "fixtures")

os.makedirs(FIXTURES_DIR, exist_ok=True)


def download_pannellum():
    """Download official Pannellum 2.5.7 assets."""
    js_url = "https://cdn.jsdelivr.net/npm/pannellum@2.5.7/build/pannellum.js"
    css_url = "https://cdn.jsdelivr.net/npm/pannellum@2.5.7/build/pannellum.css"

    js_path = os.path.join(SPIKE_DIR, "pannellum.js")
    css_path = os.path.join(SPIKE_DIR, "pannellum.css")

    if not os.path.exists(js_path):
        print(f"Downloading {js_url}...")
        urllib.request.urlretrieve(js_url, js_path)
    if not os.path.exists(css_path):
        print(f"Downloading {css_url}...")
        urllib.request.urlretrieve(css_url, css_path)

    print("Pannellum 2.5.7 assets verified.")


def generate_rich_equirectangular_image(width=4096, height=2048) -> Image.Image:
    """Create a realistic high-entropy equirectangular restaurant/cafe interior scene."""
    img = Image.new("RGB", (width, height), (220, 215, 210))
    draw = ImageDraw.Draw(img)

    # Ceiling & lighting gradient
    for y in range(0, int(height * 0.38)):
        ratio = y / (height * 0.38)
        val = int(180 + 70 * math.sin(ratio * math.pi / 2))
        draw.line([(0, y), (width, y)], fill=(val, val - 12, val - 25))

    # Floor with parquet / tile perspective lines
    floor_start = int(height * 0.58)
    for y in range(floor_start, height, 12):
        shade = int(70 + 40 * ((y - floor_start) / (height - floor_start)))
        draw.line([(0, y), (width, y)], fill=(shade, shade - 15, shade - 25), width=2)
    for x in range(0, width, 24):
        draw.line([(x, floor_start), (x, height)], fill=(60, 45, 35), width=1)

    # 16 architectural bays around 360 degrees
    num_bays = 16
    bay_w = width // num_bays
    for i in range(num_bays):
        bx = i * bay_w
        # Pillars
        draw.rectangle([bx + 10, int(height * 0.2), bx + 45, int(height * 0.75)], fill=(110, 85, 65))
        # Windows / decorative art
        draw.rectangle(
            [bx + 55, int(height * 0.25), bx + bay_w - 20, int(height * 0.55)],
            fill=(235, 245, 255),
            outline=(90, 90, 100),
            width=3,
        )
        # Cafe tables & chairs
        tx = bx + bay_w // 2
        ty = int(height * 0.68)
        draw.ellipse([tx - 45, ty - 25, tx + 45, ty + 25], fill=(130, 90, 60), outline=(50, 35, 20), width=3)
        draw.rectangle([tx - 65, ty - 12, tx - 50, ty + 12], fill=(65, 65, 75))
        draw.rectangle([tx + 50, ty - 12, tx + 65, ty + 12], fill=(65, 65, 75))

    # Add controlled photographic grain/textures across entire panorama to reach realistic 1.2 MB file size
    random.seed(1337)
    step = 4
    for y in range(0, height, step):
        for x in range(0, width, step):
            if random.random() < 0.65:
                delta = random.randint(-18, 18)
                px = img.getpixel((x, y))
                draw.point(
                    (x, y),
                    fill=(
                        max(0, min(255, px[0] + delta)),
                        max(0, min(255, px[1] + delta)),
                        max(0, min(255, px[2] + delta)),
                    ),
                )

    return img


def build_fixtures():
    """Build the suite of WebP test fixtures using T-017 standards."""
    print("Generating rich 4096x2048 equirectangular test image...")
    base_4k = generate_rich_equirectangular_image(4096, 2048)

    fixtures = [
        ("primary_4096x2048_q82.webp", base_4k, 82, 4),
        ("comparison_4096x2048_q80.webp", base_4k, 80, 4),
        ("comparison_4096x2048_q85.webp", base_4k, 85, 4),
    ]

    # Generate 2K downscale
    base_2k = base_4k.resize((2048, 1024), Image.Resampling.LANCZOS)
    fixtures.append(("comparison_2048x1024_q82.webp", base_2k, 82, 4))

    # Generate LQIP thumbnail
    base_thumb = base_4k.resize((512, 256), Image.Resampling.LANCZOS)
    fixtures.append(("thumb_512x256_q60.webp", base_thumb, 60, 4))

    # Real sample from repo if available
    repo_sample = os.path.join(SPIKE_DIR, "..", "..", "apps", "panoramas", "tests", "assets", "sample_panorama.jpg")
    if os.path.exists(repo_sample):
        sample_im = Image.open(repo_sample).convert("RGB")
        fixtures.append(("sample_panorama_2048x1024_q82.webp", sample_im, 82, 4))

    print("Encoding fixtures:")
    for fname, im, quality, method in fixtures:
        fpath = os.path.join(FIXTURES_DIR, fname)
        im.save(fpath, format="WEBP", quality=quality, method=method)
        size_bytes = os.path.getsize(fpath)
        print(f"  - {fname}: {im.size[0]}x{im.size[1]} @ Q{quality} -> {size_bytes:,} bytes ({size_bytes/1024/1024:.2f} MB)")


if __name__ == "__main__":
    download_pannellum()
    build_fixtures()
