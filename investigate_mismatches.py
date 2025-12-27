"""
Investigate why contracts aren't matching between Pinecone and ContractOpportunitiesFullCSV

This script:
1. Loads ContractOpportunitiesFullCSV.csv
2. Samples unmatched vectors from Pinecone
3. Shows why they didn't match
4. Suggests fixes

Usage:
    python investigate_mismatches.py ContractOpportunitiesFullCSV.csv [--namespace contracts]
"""

import os
import sys
import csv
import re
import argparse
from collections import Counter
from dotenv import load_dotenv
from pinecone import Pinecone

load_dotenv()

PINECONE_API_KEY = os.getenv("PINECONE_API_KEY")
PINECONE_INDEX_NAME = os.getenv("PINECONE_INDEX_NAME", "contracts")


def normalize_solicitation_number(sol_number: str) -> str:
    """Normalize solicitation number (same as enrichment script)."""
    if not sol_number:
        return ""
    return re.sub(r'[^A-Z0-9]', '', sol_number.upper().strip())


def load_csv_solicitations(csv_filepath: str) -> dict:
    """Load all solicitation numbers from CSV and create normalized lookup."""
    
    print("📖 Loading ContractOpportunitiesFullCSV.csv...")
    
    # Store both normalized and original
    normalized_to_original = {}
    all_originals = set()
    
    with open(csv_filepath, 'r', encoding='utf-8', errors='replace') as f:
        reader = csv.DictReader(f)
        
        for row in reader:
            sol_number = row.get("Sol#", "").strip()
            
            if sol_number:
                all_originals.add(sol_number)
                normalized = normalize_solicitation_number(sol_number)
                if normalized:
                    normalized_to_original[normalized] = sol_number
    
    print(f"   Found {len(all_originals)} unique solicitation numbers")
    print(f"   Normalized to {len(normalized_to_original)} unique normalized keys")
    print()
    
    return normalized_to_original, all_originals


def sample_unmatched_vectors(index, namespace: str, sample_size: int = 100):
    """Get a sample of vectors without opp_id."""
    
    print(f"🔍 Sampling {sample_size} vectors without opp_id...")
    
    dimension = index.describe_index_stats().dimension
    dummy_vector = [0.0] * dimension
    
    result = index.query(
        vector=dummy_vector,
        top_k=10000,
        namespace=namespace,
        include_metadata=True
    )
    
    unmatched = []
    for match in result.matches:
        metadata = match.metadata or {}
        if not metadata.get('opp_id') and len(unmatched) < sample_size:
            unmatched.append(metadata)
    
    print(f"   Found {len(unmatched)} unmatched vectors in sample")
    print()
    
    return unmatched


def analyze_mismatches(unmatched_vectors, normalized_lookup, original_sols):
    """Analyze why vectors didn't match."""
    
    print("=" * 80)
    print("MISMATCH ANALYSIS")
    print("=" * 80)
    print()
    
    # Categories of mismatches
    exact_match_in_csv = 0
    normalized_match_in_csv = 0
    partial_match = 0
    not_in_csv = 0
    
    examples = {
        'exact_match': [],
        'normalized_match': [],
        'partial_match': [],
        'not_in_csv': []
    }
    
    for metadata in unmatched_vectors:
        notice_id = metadata.get('notice_id', '')
        
        if not notice_id:
            continue
        
        # Check if exact match exists in CSV
        if notice_id in original_sols:
            exact_match_in_csv += 1
            if len(examples['exact_match']) < 5:
                examples['exact_match'].append(notice_id)
            continue
        
        # Check if normalized match exists
        normalized = normalize_solicitation_number(notice_id)
        if normalized in normalized_lookup:
            normalized_match_in_csv += 1
            if len(examples['normalized_match']) < 5:
                examples['normalized_match'].append({
                    'pinecone': notice_id,
                    'csv': normalized_lookup[normalized],
                    'normalized': normalized
                })
            continue
        
        # Check for partial matches (contains or is contained)
        found_partial = False
        for orig_sol in original_sols:
            if notice_id in orig_sol or orig_sol in notice_id:
                partial_match += 1
                if len(examples['partial_match']) < 5:
                    examples['partial_match'].append({
                        'pinecone': notice_id,
                        'csv_match': orig_sol
                    })
                found_partial = True
                break
        
        if not found_partial:
            not_in_csv += 1
            if len(examples['not_in_csv']) < 10:
                examples['not_in_csv'].append(notice_id)
    
    # Print results
    total = len(unmatched_vectors)
    
    print(f"📊 Sample size: {total} unmatched vectors")
    print()
    
    if exact_match_in_csv > 0:
        print(f"✅ Exact match in CSV: {exact_match_in_csv} ({exact_match_in_csv/total*100:.1f}%)")
        print(f"   → These SHOULD have matched but didn't!")
        print(f"   → Examples: {examples['exact_match'][:3]}")
        print()
    
    if normalized_match_in_csv > 0:
        print(f"⚠️  Normalized match in CSV: {normalized_match_in_csv} ({normalized_match_in_csv/total*100:.1f}%)")
        print(f"   → These should have matched after normalization")
        print(f"   → Examples:")
        for ex in examples['normalized_match'][:3]:
            print(f"      Pinecone: {ex['pinecone']}")
            print(f"      CSV:      {ex['csv']}")
            print(f"      Both →    {ex['normalized']}")
        print()
    
    if partial_match > 0:
        print(f"🔍 Partial match in CSV: {partial_match} ({partial_match/total*100:.1f}%)")
        print(f"   → Substring matches found")
        print(f"   → Examples:")
        for ex in examples['partial_match'][:3]:
            print(f"      Pinecone: {ex['pinecone']}")
            print(f"      CSV:      {ex['csv_match']}")
        print()
    
    if not_in_csv > 0:
        print(f"❌ Not in CSV at all: {not_in_csv} ({not_in_csv/total*100:.1f}%)")
        print(f"   → These contracts don't exist in ContractOpportunitiesFullCSV")
        print(f"   → Examples: {examples['not_in_csv'][:10]}")
        print()
    
    # Pattern analysis
    print("=" * 80)
    print("PATTERN ANALYSIS")
    print("=" * 80)
    print()
    
    # Check if there are common patterns
    prefixes = Counter()
    for metadata in unmatched_vectors:
        notice_id = metadata.get('notice_id', '')
        if notice_id and len(notice_id) >= 4:
            prefix = notice_id[:4]
            prefixes[prefix] += 1
    
    print("Most common prefixes in unmatched notices:")
    for prefix, count in prefixes.most_common(10):
        print(f"   {prefix}*: {count} contracts")
    
    print()
    
    return {
        'exact_match': exact_match_in_csv,
        'normalized_match': normalized_match_in_csv,
        'partial_match': partial_match,
        'not_in_csv': not_in_csv
    }


def main():
    parser = argparse.ArgumentParser(
        description="Investigate contract matching issues"
    )
    parser.add_argument("csv_file", help="Path to ContractOpportunitiesFullCSV.csv")
    parser.add_argument(
        "--namespace",
        type=str,
        default="contracts",
        help="Pinecone namespace (default: contracts)"
    )
    parser.add_argument(
        "--sample-size",
        type=int,
        default=100,
        help="Number of unmatched vectors to analyze (default: 100)"
    )
    
    args = parser.parse_args()
    
    print("=" * 80)
    print("CONTRACT MISMATCH INVESTIGATION")
    print("=" * 80)
    print()
    
    # Load CSV data
    normalized_lookup, original_sols = load_csv_solicitations(args.csv_file)
    
    # Connect to Pinecone
    print("🔌 Connecting to Pinecone...")
    pc = Pinecone(api_key=PINECONE_API_KEY)
    index = pc.Index(PINECONE_INDEX_NAME)
    print()
    
    # Sample unmatched vectors
    unmatched = sample_unmatched_vectors(index, args.namespace, args.sample_size)
    
    if not unmatched:
        print("✅ No unmatched vectors found in sample!")
        return
    
    # Analyze
    results = analyze_mismatches(unmatched, normalized_lookup, original_sols)
    
    # Recommendations
    print("=" * 80)
    print("RECOMMENDATIONS")
    print("=" * 80)
    print()
    
    if results['exact_match'] > 0:
        print("⚠️  ISSUE: Exact matches exist but aren't being found")
        print("   → Check if enrichment script is using correct CSV column names")
        print()
    
    if results['normalized_match'] > 0:
        print("⚠️  ISSUE: Normalization should have caught these")
        print("   → The normalization logic might need adjustment")
        print()
    
    if results['not_in_csv'] > results['partial_match'] + results['normalized_match']:
        print("✅ CONCLUSION: Most unmatched contracts genuinely aren't in the CSV")
        print("   → This is expected - ContractOpportunitiesFullCSV might not include all types")
        print("   → Contract Notice Details has more contracts than Opportunities Full")
        print()


if __name__ == "__main__":
    main()