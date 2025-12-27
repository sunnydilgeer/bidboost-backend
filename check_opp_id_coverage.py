"""
Check what percentage of Pinecone vectors have opp_id populated

Usage:
    python check_opp_id_coverage.py [--namespace contracts]
"""

import os
import argparse
from dotenv import load_dotenv
from pinecone import Pinecone

load_dotenv()

PINECONE_API_KEY = os.getenv("PINECONE_API_KEY")
PINECONE_INDEX_NAME = os.getenv("PINECONE_INDEX_NAME", "contracts")


def check_coverage(index, namespace: str = ""):
    """Check opp_id coverage by querying random samples."""
    
    print("=" * 70)
    print("OPP_ID COVERAGE CHECK")
    print("=" * 70)
    
    # Get total count
    stats = index.describe_index_stats()
    if namespace and namespace in stats.namespaces:
        total_count = stats.namespaces[namespace].vector_count
    else:
        total_count = stats.total_vector_count
    
    print(f"Namespace: {namespace}")
    print(f"Total vectors: {total_count}")
    print()
    
    # Query to sample vectors
    print("Sampling vectors to check opp_id coverage...")
    dimension = stats.dimension
    
    # Query with dummy vector to get a large sample
    dummy_vector = [0.0] * dimension
    result = index.query(
        vector=dummy_vector,
        top_k=min(10000, total_count),
        namespace=namespace,
        include_metadata=True
    )
    
    # Count vectors with opp_id
    with_opp_id = 0
    without_opp_id = 0
    
    for match in result.matches:
        metadata = match.metadata or {}
        if metadata.get('opp_id'):
            with_opp_id += 1
        else:
            without_opp_id += 1
    
    sample_size = len(result.matches)
    coverage_pct = (with_opp_id / sample_size * 100) if sample_size > 0 else 0
    
    print()
    print("=" * 70)
    print("RESULTS (based on sample)")
    print("=" * 70)
    print(f"Sample size: {sample_size} vectors")
    print(f"✅ With opp_id: {with_opp_id} ({with_opp_id/sample_size*100:.1f}%)")
    print(f"❌ Without opp_id: {without_opp_id} ({without_opp_id/sample_size*100:.1f}%)")
    print()
    print(f"📊 Estimated total with opp_id: ~{int(total_count * coverage_pct / 100)} / {total_count}")
    print(f"📈 Coverage: {coverage_pct:.1f}%")
    print()
    
    # Show a few examples without opp_id
    if without_opp_id > 0:
        print("Examples of contracts WITHOUT opp_id:")
        count = 0
        for match in result.matches:
            metadata = match.metadata or {}
            if not metadata.get('opp_id') and count < 5:
                print(f"  - {metadata.get('notice_id', 'N/A')}: {metadata.get('title', 'No title')[:60]}...")
                count += 1
    
    return coverage_pct


def main():
    parser = argparse.ArgumentParser(description="Check opp_id coverage in Pinecone")
    parser.add_argument(
        "--namespace",
        type=str,
        default="contracts",
        help="Pinecone namespace to check (default: contracts)"
    )
    args = parser.parse_args()
    
    # Connect to Pinecone
    pc = Pinecone(api_key=PINECONE_API_KEY)
    index = pc.Index(PINECONE_INDEX_NAME)
    
    # Check coverage
    coverage = check_coverage(index, namespace=args.namespace)
    
    # Verdict
    print("=" * 70)
    if coverage >= 99:
        print("✅ EXCELLENT: 99%+ coverage achieved!")
    elif coverage >= 90:
        print("✅ GOOD: 90%+ coverage achieved!")
    elif coverage >= 75:
        print("⚠️  FAIR: 75%+ coverage. Consider running enrichment again.")
    else:
        print("❌ LOW: <75% coverage. Run enrichment script again.")
    print("=" * 70)


if __name__ == "__main__":
    main()