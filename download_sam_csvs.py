"""
Download SAM.gov CSV Files
Downloads the two required CSV files for contract data ingestion

Usage:
    python download_sam_csvs.py [--output-dir ./data]
"""

import os
import sys
import argparse
import requests
from pathlib import Path
from datetime import datetime

# SAM.gov CSV URLs (from your manual download links)
CONTRACT_OPPORTUNITIES_URL = "https://sam.gov/data-services/Contract%20Opportunities/datagov"
CONTRACT_NOTICE_DETAILS_URL = "https://sam.gov/databank/report/mstr:B3E641D611E8B2D314280080EF75D7E5:D3952F244D506D03CE6372A5C4C3FB22"

# File names
CONTRACT_OPPS_FILENAME = "ContractOpportunitiesFullCSV.csv"
NOTICE_DETAILS_FILENAME = "contract_notice_details.csv"


def download_file(url: str, output_path: Path, description: str) -> bool:
    """
    Download a file from URL with progress indication.
    
    Args:
        url: URL to download from
        output_path: Path to save file
        description: Description for logging
        
    Returns:
        True if successful, False otherwise
    """
    print(f"📥 Downloading {description}...")
    print(f"   URL: {url}")
    print(f"   Output: {output_path}")
    
    try:
        # Make request with streaming
        response = requests.get(url, stream=True, timeout=300)
        response.raise_for_status()
        
        # Get file size if available
        total_size = int(response.headers.get('content-length', 0))
        
        # Write to file
        downloaded = 0
        chunk_size = 8192
        
        with open(output_path, 'wb') as f:
            for chunk in response.iter_content(chunk_size=chunk_size):
                if chunk:
                    f.write(chunk)
                    downloaded += len(chunk)
                    
                    if total_size > 0:
                        percent = (downloaded / total_size) * 100
                        print(f"\r   Progress: {percent:.1f}% ({downloaded:,} / {total_size:,} bytes)", end='')
        
        print()  # New line after progress
        
        file_size = output_path.stat().st_size
        print(f"   ✅ Downloaded: {file_size:,} bytes")
        print()
        
        return True
        
    except requests.RequestException as e:
        print(f"   ❌ Download failed: {e}")
        print()
        return False
    except Exception as e:
        print(f"   ❌ Unexpected error: {e}")
        print()
        return False


def main():
    parser = argparse.ArgumentParser(
        description="Download SAM.gov CSV files for contract ingestion"
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        default="./data",
        help="Directory to save CSV files (default: ./data)"
    )
    parser.add_argument(
        "--skip-if-exists",
        action="store_true",
        help="Skip download if files already exist"
    )
    
    args = parser.parse_args()
    
    # Create output directory
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    
    print("=" * 70)
    print("SAM.gov CSV Download")
    print("=" * 70)
    print(f"📂 Output directory: {output_dir.absolute()}")
    print(f"🕐 Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print()
    
    # Define output paths
    contract_opps_path = output_dir / CONTRACT_OPPS_FILENAME
    notice_details_path = output_dir / NOTICE_DETAILS_FILENAME
    
    # Track success
    results = {
        "contract_opportunities": False,
        "notice_details": False
    }
    
    # Download Contract Opportunities CSV
    if args.skip_if_exists and contract_opps_path.exists():
        print(f"⏭️  Skipping {CONTRACT_OPPS_FILENAME} (already exists)")
        print()
        results["contract_opportunities"] = True
    else:
        results["contract_opportunities"] = download_file(
            CONTRACT_OPPORTUNITIES_URL,
            contract_opps_path,
            "ContractOpportunitiesFullCSV.csv"
        )
    
    # Download Contract Notice Details CSV
    if args.skip_if_exists and notice_details_path.exists():
        print(f"⏭️  Skipping {NOTICE_DETAILS_FILENAME} (already exists)")
        print()
        results["notice_details"] = True
    else:
        results["notice_details"] = download_file(
            CONTRACT_NOTICE_DETAILS_URL,
            notice_details_path,
            "contract_notice_details.csv"
        )
    
    # Summary
    print("=" * 70)
    print("DOWNLOAD SUMMARY")
    print("=" * 70)
    print(f"Contract Opportunities: {'✅ Success' if results['contract_opportunities'] else '❌ Failed'}")
    print(f"Contract Notice Details: {'✅ Success' if results['notice_details'] else '❌ Failed'}")
    print()
    
    if all(results.values()):
        print("✅ All downloads completed successfully!")
        print(f"🕐 Finished: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print("=" * 70)
        return 0
    else:
        print("❌ Some downloads failed. Check errors above.")
        print("=" * 70)
        return 1


if __name__ == "__main__":
    sys.exit(main())