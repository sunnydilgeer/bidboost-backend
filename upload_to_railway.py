"""
One-time script to upload CSVs to Railway volume
Run this locally to seed the Railway volume with your CSVs
"""
import os
from pathlib import Path

# This assumes you've mounted Railway volume at /app/data
RAILWAY_DATA_DIR = Path(os.getenv("RAILWAY_VOLUME_MOUNT_PATH", "./data"))

def main():
    print("📤 Railway Volume Upload Helper")
    print("=" * 70)
    print(f"Target directory: {RAILWAY_DATA_DIR}")
    print()
    print("To upload CSVs to Railway:")
    print("1. Ensure volume is mounted at /app/data in Railway")
    print("2. Use Railway CLI or scp to copy files:")
    print()
    print("   railway run bash")
    print("   # Then in Railway shell:")
    print("   # Upload via your method of choice")
    print()
    print("Or use Railway's file upload feature when available")

if __name__ == "__main__":
    main()