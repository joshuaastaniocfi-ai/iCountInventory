import zipfile
import os

# Path to your zip file
zip_path = "/home/nexentry2025/icebergINV/Iceberg_INV.zip"

# Folder where you want to extract
extract_to = "/home/nexentry2025/icebergINV"


os.makedirs(extract_to, exist_ok=True)

with zipfile.ZipFile(zip_path, 'r') as zip_ref:
    for file_info in zip_ref.infolist():
        # Show file details before extraction
        print(f"📂 Extracting: {file_info.filename}")
        print(f"   - Compressed size: {file_info.compress_size} bytes")
        print(f"   - Uncompressed size: {file_info.file_size} bytes\n")

        # Extract the file
        zip_ref.extract(file_info, extract_to)

print(f"✅ All files extracted to: {extract_to}")