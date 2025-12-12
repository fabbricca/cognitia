#!/usr/bin/env python3
"""
Generate placeholder PWA icons for Cognitia web interface.
Creates simple icons with the Cognitia logo text.
"""

from PIL import Image, ImageDraw, ImageFont
import os

def generate_icon(size, output_path):
    """Generate a single icon of the specified size."""
    # Create image with black background
    img = Image.new('RGB', (size, size), color='#000000')
    draw = ImageDraw.Draw(img)

    # Draw orange circle
    circle_margin = size // 6
    draw.ellipse(
        [circle_margin, circle_margin, size - circle_margin, size - circle_margin],
        fill='#ff6600',
        outline='#ff8800',
        width=size // 40
    )

    # Draw text "G" in center
    font_size = size // 2
    try:
        # Try to use a nice font if available
        font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", font_size)
    except:
        # Fallback to default font
        font = ImageFont.load_default()

    text = "G"

    # Get text bounding box for centering
    bbox = draw.textbbox((0, 0), text, font=font)
    text_width = bbox[2] - bbox[0]
    text_height = bbox[3] - bbox[1]

    position = ((size - text_width) // 2, (size - text_height) // 2 - size // 20)

    # Draw text with shadow
    shadow_offset = size // 80
    draw.text((position[0] + shadow_offset, position[1] + shadow_offset), text, fill='#000000', font=font)
    draw.text(position, text, fill='#ffffff', font=font)

    # Save image
    img.save(output_path, 'PNG')
    print(f"Generated: {output_path}")

def main():
    """Generate all required icon sizes."""
    # Get the web/icons directory
    script_dir = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.dirname(script_dir)
    icons_dir = os.path.join(project_root, 'web', 'icons')

    # Create icons directory if it doesn't exist
    os.makedirs(icons_dir, exist_ok=True)

    # Generate icons
    sizes = [192, 512]
    for size in sizes:
        output_path = os.path.join(icons_dir, f'icon-{size}.png')
        generate_icon(size, output_path)

    print("\nIcons generated successfully!")
    print(f"Location: {icons_dir}")

if __name__ == '__main__':
    main()
