import requests
from collections import Counter
from PIL import Image
from datetime import datetime, timezone, timedelta

#time 

utc_plus_8 = timezone(timedelta(hours=8))
now = datetime.now(utc_plus_8)

formatted_time = now.strftime("%B %d, %Y, %H_%M_%S %p")
formatted_time += " UTC+08"

# =========================================================
# Configuration
# =========================================================

FILE_URL = "https://d34w1vc7uzb89c.cloudfront.net/canvas/snapshot/latest.bin.gz"

OUTPUT_IMAGE_1 = "milliondollardrawing_palette1 "+ formatted_time + ".png"
OUTPUT_IMAGE_2 = "milliondollardrawing_palette2 "+ formatted_time + ".png"

WIDTH = 1000
HEIGHT = 1000

TRANSPARENT_VALUE = 0xFF

# =========================================================
# Palette 1 (Original)
# =========================================================

palette1 = {
    0x00: (198, 40, 40),
    0x01: (229, 57, 53),
    0x02: (251, 140, 0),
    0x03: (255, 112, 67),
    0x04: (255, 179, 0),
    0x05: (253, 216, 53),
    0x06: (192, 202, 51),
    0x07: (67, 160, 71),
    0x08: (27, 94, 32),
    0x09: (0, 137, 123),
    0x0A: (0, 172, 193),
    0x0B: (38, 198, 218),
    0x0C: (41, 182, 246),
    0x0D: (30, 136, 229),
    0x0E: (13, 71, 161),
    0x0F: (142, 36, 170),
    0x10: (216, 27, 96),
    0x11: (109, 76, 65),
    0x12: (255, 255, 255),
    0x13: (122, 122, 122),
    0x14: (47, 47, 47),
    0x15: (17, 17, 17),
}

# =========================================================
# Palette 2 (New)
# =========================================================

palette2 = {
    0x15: (0, 0, 0),
    0x14: (60, 60, 60),
    0x13: (120, 120, 120),
    0x12: (255, 255, 255),
    0x11: (104, 70, 52),
    0x10: (236, 31, 128),
    0x0F: (120, 12, 153),
    0x0E: (40, 80, 158),
    0x0D: (64, 147, 228),
    0x0C: (125, 199, 255),
    0x0B: (15, 121, 159),
    0x0A: (16, 174, 166),
    0x09: (12, 129, 110),
    0x08: (74, 107, 58),
    0x07: (90, 148, 74),
    0x06: (197, 173, 49),
    0x05: (249, 221, 59),
    0x04: (246, 170, 9),
    0x03: (228, 92, 26),
    0x02: (255, 127, 39),
    0x01: (237, 28, 36),
    0x00: (165, 14, 30),
}

# Unknown bytes = magenta
DEFAULT_COLOR = (255, 0, 255, 255)

# =========================================================
# Helper Functions
# =========================================================

def rgb_to_rgba(rgb):
    return (rgb[0], rgb[1], rgb[2], 255)

palette1_rgba = {
    key: rgb_to_rgba(value)
    for key, value in palette1.items()
}

palette2_rgba = {
    key: rgb_to_rgba(value)
    for key, value in palette2.items()
}

# =========================================================
# Download Binary File
# =========================================================

print("Downloading binary file...")

response = requests.get(FILE_URL)
response.raise_for_status()

data = response.content

print(f"Downloaded {len(data):,} bytes")

# =========================================================
# Validate Size
# =========================================================

required_size = WIDTH * HEIGHT

if len(data) < required_size:
    raise ValueError(
        f"Not enough data. "
        f"Expected {required_size}, got {len(data)}"
    )

data = data[:required_size]

# =========================================================
# Pixel Statistics
# =========================================================

byte_counts = Counter(data)

print("\nPixel Statistics:")
print("=" * 45)

for byte_value in sorted(byte_counts.keys()):

    count = byte_counts[byte_value]

    if byte_value == TRANSPARENT_VALUE:
        color_text = "TRANSPARENT"

    elif byte_value in palette1:
        rgb = palette1[byte_value]
        color_text = f"({rgb[0]}, {rgb[1]}, {rgb[2]})"

    else:
        color_text = "UNKNOWN"

    print(
        f"0x{byte_value:02X} | {color_text} - {count:,} pixels"
    )

# =========================================================
# Function To Generate Image
# =========================================================

def generate_image(output_name, palette):

    print(f"\nGenerating {output_name}...")

    img = Image.new("RGBA", (WIDTH, HEIGHT))
    pixels = img.load()

    for i, byte_value in enumerate(data):

        # Transparent pixel
        if byte_value == TRANSPARENT_VALUE:
            color = (0, 0, 0, 0)

        else:
            color = palette.get(byte_value, DEFAULT_COLOR)

        x = i % WIDTH
        y = i // WIDTH

        pixels[x, y] = color

    img.save(output_name)

    print(f"Saved '{output_name}'")

# =========================================================
# Generate Both Images
# =========================================================

generate_image(
    OUTPUT_IMAGE_1,
    palette1_rgba
)

generate_image(
    OUTPUT_IMAGE_2,
    palette2_rgba
)

print("\nDone.")