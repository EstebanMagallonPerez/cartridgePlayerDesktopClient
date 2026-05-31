from PIL import Image, ImageDraw
import os
# === CONFIG ===
ROOT_FOLDER =os.getcwd()   # folder containing subfolders
print(f"Root folder: {ROOT_FOLDER}")
BASE_PNG = "./Cartridge.png"         # your 600dpi 40mm x 45mm PNG
fullPath = os.path.join(os.getcwd(), BASE_PNG)
OUTPUT_FOLDER = "./"

# Create output folder if needed
os.makedirs(OUTPUT_FOLDER, exist_ok=True)

# Load base image
base_img = Image.open(fullPath).convert("RGBA")
base_width, base_height = base_img.size

print(f"Base image size: {base_width}x{base_height}")

def processImage(jpg_path, output_path):
    try:
        img = Image.open(jpg_path).convert("RGBA")

        # Resize to match base height while keeping aspect ratio
        scale = base_height / img.height
        new_width = int(img.width * scale)
        resized = img.resize((new_width, base_height), Image.LANCZOS)

        # Create a copy of base image
        result = base_img.copy()

        # Paste at top-left (0, 0)
        result.paste(resized, (0, 0), resized)

        # === Rounded corners ===
        radius = 40

        # Create rounded mask
        mask = Image.new("L", result.size, 0)
        draw = ImageDraw.Draw(mask)

        draw.rounded_rectangle(
            [(0, 0), (result.width, result.height)],
            radius=radius,
            fill=255
        )

        # Apply mask as alpha channel
        result.putalpha(mask)

        # Save result
        result.save(output_path, "PNG")
        print(f"Saved: {output_path}")

    except Exception as e:
        print(f"Error processing {jpg_path}: {e}")


for folderName in os.listdir(ROOT_FOLDER):
    folder_path = os.path.join(ROOT_FOLDER, folderName)

    # Skip if not a folder
    if not os.path.isdir(folder_path):
        continue

    # Look for jpg/jpeg files in this folder
    for file in os.listdir(folder_path):
        if file.lower().endswith((".jpg", ".jpeg")):
            jpg_path = os.path.join(folder_path, file)

            # Output folder mirrors source folder
            output_dir = os.path.join(OUTPUT_FOLDER, folderName)
            os.makedirs(output_dir, exist_ok=True)

            output_path = os.path.join(
                output_dir,
                os.path.splitext(file)[0] + ".png"
            )

            processImage(jpg_path, output_path)

print("Done.")
