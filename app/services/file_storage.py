import os
import shutil
from pathlib import Path
from datetime import datetime
from typing import Optional
import hashlib

class FileStorageService:
    def __init__(self, storage_path: str = "storage/documents"):
        self.storage_path = Path(storage_path)
        self.storage_path.mkdir(parents=True, exist_ok=True)
    
    def save_file(self, file_content: bytes, original_filename: str, document_id: str) -> str:
        """Save file to disk and return the storage path"""
        # Create subdirectory by date for organization
        date_folder = datetime.now().strftime("%Y-%m-%d")
        save_dir = self.storage_path / date_folder
        save_dir.mkdir(parents=True, exist_ok=True)
        
        # Use document_id in filename to ensure uniqueness
        file_extension = Path(original_filename).suffix
        safe_filename = f"{document_id}{file_extension}"
        file_path = save_dir / safe_filename
        
        # Write file
        with open(file_path, 'wb') as f:
            f.write(file_content)
        
        # Return relative path from storage root
        return str(file_path.relative_to(self.storage_path))
    
    def get_file_path(self, relative_path: str) -> Optional[Path]:
        """Get absolute path to stored file"""
        full_path = self.storage_path / relative_path
        return full_path if full_path.exists() else None
    
    def delete_file(self, relative_path: str) -> bool:
        """Delete a stored file"""
        file_path = self.get_file_path(relative_path)
        if file_path and file_path.exists():
            file_path.unlink()
            return True
        return False