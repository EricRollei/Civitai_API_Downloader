"""
Generate icon PNG files for the Chrome extension.
Run this script once to create the icon files.
Requires Pillow: pip install Pillow
"""

from PIL import Image, ImageDraw, ImageFont
import os

def create_icon(size: int, output_path: str):
    """Create a simple icon with a 'C' letter."""
    # Create image with gradient-like blue background
    img = Image.new('RGBA', (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    
    # Draw rounded rectangle background
    padding = size // 8
    radius = size // 4
    
    # Simple blue background (gradient effect approximation)
    for i in range(size):
        ratio = i / size
        r = int(33 + (21 - 33) * ratio)
        g = int(150 + (101 - 150) * ratio)  
        b = int(243 + (192 - 243) * ratio)
        draw.line([(0, i), (size, i)], fill=(r, g, b, 255))
    
    # Create rounded corners by masking
    mask = Image.new('L', (size, size), 0)
    mask_draw = ImageDraw.Draw(mask)
    mask_draw.rounded_rectangle([0, 0, size-1, size-1], radius=radius, fill=255)
    
    # Apply mask
    img.putalpha(mask)
    
    # Draw the 'C' letter
    draw = ImageDraw.Draw(img)
    
    # Try to use a nice font, fall back to default
    font_size = int(size * 0.6)
    try:
        font = ImageFont.truetype("arial.ttf", font_size)
    except:
        try:
            font = ImageFont.truetype("Arial.ttf", font_size)
        except:
            font = ImageFont.load_default()
    
    text = "C"
    
    # Get text bounding box for centering
    bbox = draw.textbbox((0, 0), text, font=font)
    text_width = bbox[2] - bbox[0]
    text_height = bbox[3] - bbox[1]
    
    x = (size - text_width) // 2
    y = (size - text_height) // 2 - bbox[1]
    
    draw.text((x, y), text, fill=(255, 255, 255, 255), font=font)
    
    img.save(output_path, 'PNG')
    print(f"Created {output_path}")

def main():
    script_dir = os.path.dirname(os.path.abspath(__file__))
    
    sizes = [16, 48, 128]
    for size in sizes:
        output_path = os.path.join(script_dir, f"icon{size}.png")
        create_icon(size, output_path)
    
    print("\nIcons created successfully!")
    print("You can now load the extension in Chrome:")
    print("1. Go to chrome://extensions")
    print("2. Enable 'Developer mode'")
    print("3. Click 'Load unpacked'")
    print(f"4. Select: {script_dir}")

if __name__ == "__main__":
    main()
