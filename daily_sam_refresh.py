"""
Daily SAM.gov Data Refresh Orchestrator
Processes ContractOpportunitiesFullCSV.csv using the new ingestion pipeline

Usage:
    python daily_sam_refresh.py
"""

import os
import sys
import subprocess
from pathlib import Path
from datetime import datetime
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Configuration
DATA_DIR = Path("./data")
CONTRACT_OPPS_CSV = DATA_DIR / "ContractOpportunitiesFullCSV.csv"
PINECONE_NAMESPACE = os.getenv("PINECONE_NAMESPACE", "contracts")


def validate_csv_files() -> bool:
    """Check if required CSV file exists."""
    print("=" * 70)
    print("📂 Validating CSV Files")
    print("=" * 70)
    
    if CONTRACT_OPPS_CSV.exists():
        size = CONTRACT_OPPS_CSV.stat().st_size
        print(f"✅ {CONTRACT_OPPS_CSV.name}: {size:,} bytes")
        print()
        return True
    else:
        print(f"❌ Missing: {CONTRACT_OPPS_CSV}")
        print()
        return False


def run_command(command: list, description: str) -> bool:
    """Run a command and return success status."""
    print("=" * 70)
    print(f"🚀 {description}")
    print("=" * 70)
    print(f"Command: {' '.join(command)}")
    print()
    
    try:
        result = subprocess.run(
            command,
            check=True,
            capture_output=False,
            text=True
        )
        print()
        print(f"✅ {description} - SUCCESS")
        print()
        return True
        
    except subprocess.CalledProcessError as e:
        print()
        print(f"❌ {description} - FAILED")
        print(f"Exit code: {e.returncode}")
        print()
        return False
    except Exception as e:
        print()
        print(f"❌ {description} - ERROR: {e}")
        print()
        return False


def main():
    print("=" * 70)
    print("DAILY SAM.GOV DATA REFRESH")
    print("=" * 70)
    print(f"🕐 Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"📂 Data directory: {DATA_DIR.absolute()}")
    print(f"🏷️  Pinecone namespace: {PINECONE_NAMESPACE}")
    print()
    
    # Validate environment variables
    required_env_vars = ["PINECONE_API_KEY", "OPENAI_API_KEY"]
    missing_vars = [var for var in required_env_vars if not os.getenv(var)]
    
    if missing_vars:
        print(f"❌ Missing required environment variables: {', '.join(missing_vars)}")
        return 1
    
    # Track pipeline success
    pipeline_results = {}
    
    # Step 1: Validate CSV file exists
    if not validate_csv_files():
        print("❌ Required CSV file not found in data directory.")
        print("   Please ensure ContractOpportunitiesFullCSV.csv is uploaded to: ./data/")
        return 1
    
    pipeline_results["validate"] = True
    
    # Step 2: Ingest contract opportunities
    pipeline_results["ingest"] = run_command(
        [
            "python", "ingest_contract_opportunities.py",
            str(CONTRACT_OPPS_CSV),
            clear edxisting= "true",
            "--namespace", PINECONE_NAMESPACE,
            "--clear-existing"
        ],
        "Step 2: Ingest Contract Opportunities"
    )
    
    if not pipeline_results["ingest"]:
        print("❌ Pipeline failed at ingestion step. Aborting.")
        return 1
    
    # Step 3: Check coverage (optional)
    pipeline_results["check"] = run_command(
        [
            "python", "check_opp_id_coverage.py",
            "--namespace", PINECONE_NAMESPACE
        ],
        "Step 3: Check OPP_ID Coverage"
    )
    
    # Final summary
    print("=" * 70)
    print("PIPELINE SUMMARY")
    print("=" * 70)
    print(f"✅ Validate CSV: {'Success' if pipeline_results['validate'] else 'Failed'}")
    print(f"✅ Ingest Data: {'Success' if pipeline_results['ingest'] else 'Failed'}")
    print(f"✅ Coverage Check: {'Success' if pipeline_results['check'] else 'Failed'}")
    print()
    print(f"🕐 Finished: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 70)
    
    if pipeline_results["validate"] and pipeline_results["ingest"]:
        print("✅ DAILY REFRESH COMPLETED SUCCESSFULLY")
        return 0
    else:
        print("❌ DAILY REFRESH FAILED")
        return 1


if __name__ == "__main__":
    sys.exit(main())