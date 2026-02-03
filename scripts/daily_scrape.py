"""
Daily scraping wrapper.
Reads from to_scrape.csv and calls existing scraper.
"""
import argparse
import subprocess
import sys
from pathlib import Path

def main():
    parser = argparse.ArgumentParser(description="Run daily contract scraping")
    parser.add_argument('--limit', type=int, default=500, help="Max contracts to scrape")
    parser.add_argument('--input', type=str, default='data/to_scrape.csv', help="Input CSV")
    
    args = parser.parse_args()
    
    input_file = Path(args.input)
    
    if not input_file.exists():
        print(f"❌ Input file not found: {args.input}")
        sys.exit(1)
    
    print("=" * 70)
    print("DAILY CONTRACT SCRAPING")
    print("=" * 70)
    print(f"📂 Input: {args.input}")
    print(f"🔢 Limit: {args.limit}")
    print()
    
    result = subprocess.run(
        ["python", "scrape_sam_with_selenium.py", "--limit", str(args.limit)],
        capture_output=False
    )
    
    if result.returncode == 0:
        print("\n✅ Scraping complete")
    else:
        print("\n❌ Scraping failed")
        sys.exit(1)

if __name__ == "__main__":
    main()