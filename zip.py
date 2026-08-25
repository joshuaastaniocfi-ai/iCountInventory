import zipfile
import os
import sys
from datetime import datetime

def zip_folder(source_folder, target_location, exclude_dirs=('venv', '__pycache__', '.git'), exclude_extensions=('.pyc', '.pyo', '.log')):
    """
    Zip a folder with exclusion options
    
    Args:
        source_folder (str): Path to the folder to zip
        target_location (str): Path where the zip file will be created
        exclude_dirs (tuple): Directory names to exclude
        exclude_extensions (tuple): File extensions to exclude
    
    Returns:
        bool: True if successful, False otherwise
    """
    try:
        # Create target directory if it doesn't exist
        os.makedirs(os.path.dirname(target_location), exist_ok=True)

        with zipfile.ZipFile(target_location, 'w', zipfile.ZIP_DEFLATED) as zipf:
            for root, dirs, files in os.walk(source_folder):
                # Exclude specified directories
                dirs[:] = [d for d in dirs if d not in exclude_dirs]

                for file in files:
                    # Skip files with excluded extensions
                    if any(file.endswith(ext) for ext in exclude_extensions):
                        continue
                    
                    file_path = os.path.join(root, file)
                    
                    # Skip if file is the zip file itself (avoid recursion)
                    if os.path.abspath(file_path) == os.path.abspath(target_location):
                        continue
                    
                    relative_path = os.path.relpath(file_path, source_folder)
                    zipf.write(file_path, relative_path)

        print(f"✅ Successfully zipped '{source_folder}' to '{target_location}'")
        return True
    except Exception as e:
        print(f"❌ Error zipping folder: {str(e)}")
        return False

if __name__ == "__main__":
    # Get the current script directory
    current_dir = os.path.dirname(os.path.abspath(__file__))
    
    # If script is in the root directory, use it as source
    # Otherwise, use the parent directory
    source = current_dir
    
    # Create timestamp for the zip file
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    
    # Create target zip file path in the same directory as the script
    target = os.path.join(current_dir, f"icebergINV_backup_{timestamp}.zip")
    
    # Zip the folder
    success = zip_folder(
        source, 
        target, 
        exclude_dirs=('venv', '__pycache__', '.git', '.vscode', 'node_modules', 'uploads', 'reports'),
        exclude_extensions=('.pyc', '.pyo', '.log', '.tmp', '.bak')
    )
    
    if success:
        print(f"📁 Zip file created: {target}")
        print(f"📊 File size: {os.path.getsize(target) / (1024*1024):.2f} MB")
    else:
        print("❌ Failed to create zip file")
        sys.exit(1)