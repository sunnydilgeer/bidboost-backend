"""
Daily re-embedding wrapper.
Re-embeds contracts scraped in last 24 hours.
"""
import argparse
import subprocess
import sys

def main():
    parser = argparse.ArgumentParser(description="Re-embed recently scraped contracts")
    parser.add_argument('--hours', type=int, default=24, help="Re-embed contracts scraped in last N hours")
    
    args = parser.parse_args()
    
    print("=" * 70)
    print("RE-EMBED SCRAPED CONTRACTS")
    print("=" * 70)
    print(f"⏰ Time window: Last {args.hours} hours")
    print()
    
    result = subprocess.run(
        ["python", "re_embed_updated_contracts.py", "--hours", str(args.hours)],
        capture_output=False
    )
    
    if result.returncode == 0:
        print("\n✅ Re-embedding complete")
    else:
        print("\n❌ Re-embedding failed")
        sys.exit(1)

if __name__ == "__main__":
    main()