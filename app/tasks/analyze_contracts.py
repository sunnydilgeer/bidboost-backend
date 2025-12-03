"""
Analyze SAM.gov contracts in Pinecone
Check product/service types and deadline status
"""
import sys
from pathlib import Path
from datetime import datetime, timezone
from collections import Counter

# Add project root to path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from app.services.pinecone_store import PineconeStoreService
from app.core.config import settings

def analyze_contracts():
    """Analyze contracts in Pinecone"""
    
    # Connect to Pinecone
    pinecone = PineconeStoreService(api_key=settings.PINECONE_API_KEY)
    
    print("📊 Fetching contract data from Pinecone...\n")
    
    # Get sample of contracts using dummy vector query
    dummy_vector = [0.0] * 768  # Match your embedding dimensions
    
    results = pinecone.index.query(
        vector=dummy_vector,
        top_k=10000,  # Fetch large sample
        include_metadata=True
    )
    
    contracts = results['matches']
    total_fetched = len(contracts)
    
    print(f"✅ Fetched {total_fetched} contracts\n")
    print("=" * 80)
    
    # Analyze deadlines
    now = datetime.now(timezone.utc)
    open_count = 0
    closed_count = 0
    no_deadline_count = 0
    
    # Analyze product/service types
    naics_codes = []
    psc_codes = []
    agencies = []
    set_asides = []
    
    print("\n📋 SAMPLE CONTRACTS (First 5):\n")
    
    for i, contract in enumerate(contracts[:5]):
        meta = contract['metadata']
        
        print(f"\n--- Contract #{i+1} ---")
        print(f"Notice ID: {meta.get('notice_id', 'N/A')}")
        print(f"Title: {meta.get('title', 'N/A')[:100]}...")
        print(f"Agency: {meta.get('agency', 'N/A')}")
        print(f"NAICS Code: {meta.get('naics', 'N/A')}")
        print(f"PSC Code: {meta.get('psc', 'N/A')}")
        print(f"Set-Aside: {meta.get('set_aside', 'N/A')}")
        print(f"Location: {meta.get('city', 'N/A')}, {meta.get('state', 'N/A')}")
        print(f"Posted: {meta.get('posted_date', 'N/A')}")
        print(f"Deadline: {meta.get('response_deadline', 'N/A')}")
        
        # Check deadline status
        deadline_str = meta.get('response_deadline', '')
        if deadline_str:
            try:
                # Try parsing common date formats
                for fmt in ['%Y-%m-%d', '%Y-%m-%dT%H:%M:%S', '%Y-%m-%d %H:%M:%S']:
                    try:
                        deadline = datetime.strptime(deadline_str[:19], fmt).replace(tzinfo=timezone.utc)
                        if deadline > now:
                            print(f"Status: ✅ OPEN")
                        else:
                            print(f"Status: ❌ CLOSED")
                        break
                    except:
                        continue
            except:
                print(f"Status: ⚠️ UNKNOWN (parse error)")
        else:
            print(f"Status: ⚠️ NO DEADLINE")
        
        print(f"Description: {meta.get('description', 'N/A')[:200]}...")
        print(f"URL: {meta.get('source_url', 'N/A')}")
        print("-" * 80)
    
    # Analyze all contracts
    print("\n\n📊 ANALYZING ALL CONTRACTS...\n")
    
    for contract in contracts:
        meta = contract['metadata']
        
        # Collect data
        if meta.get('naics'):
            naics_codes.append(meta['naics'])
        if meta.get('psc'):
            psc_codes.append(meta['psc'])
        if meta.get('agency'):
            agencies.append(meta['agency'])
        if meta.get('set_aside'):
            set_asides.append(meta['set_aside'])
        
        # Check deadline
        deadline_str = meta.get('response_deadline', '')
        if deadline_str:
            try:
                for fmt in ['%Y-%m-%d', '%Y-%m-%dT%H:%M:%S', '%Y-%m-%d %H:%M:%S']:
                    try:
                        deadline = datetime.strptime(deadline_str[:19], fmt).replace(tzinfo=timezone.utc)
                        if deadline > now:
                            open_count += 1
                        else:
                            closed_count += 1
                        break
                    except:
                        continue
            except:
                no_deadline_count += 1
        else:
            no_deadline_count += 1
    
    # Print summary
    print("=" * 80)
    print("📊 SUMMARY STATISTICS")
    print("=" * 80)
    
    print(f"\n🗓️  DEADLINE STATUS:")
    print(f"  ✅ Open contracts: {open_count}")
    print(f"  ❌ Closed contracts: {closed_count}")
    print(f"  ⚠️  No deadline/Parse error: {no_deadline_count}")
    total_with_deadline = open_count + closed_count
    if total_with_deadline > 0:
        open_pct = (open_count / total_with_deadline) * 100
        print(f"  📈 {open_pct:.1f}% of contracts with deadlines are still open")
    
    print(f"\n🏢 TOP 10 AGENCIES:")
    for agency, count in Counter(agencies).most_common(10):
        print(f"  {count:4d} - {agency}")
    
    print(f"\n🏷️  TOP 10 NAICS CODES (Industry Categories):")
    for naics, count in Counter(naics_codes).most_common(10):
        print(f"  {count:4d} - {naics}")
    
    print(f"\n📦 TOP 10 PSC CODES (Product/Service Codes):")
    for psc, count in Counter(psc_codes).most_common(10):
        print(f"  {count:4d} - {psc}")
    
    print(f"\n🎯 SET-ASIDE TYPES:")
    for set_aside, count in Counter(set_asides).most_common():
        if set_aside:  # Skip empty
            print(f"  {count:4d} - {set_aside}")
    
    print("\n" + "=" * 80)
    print(f"Total contracts analyzed: {total_fetched}")
    print(f"📊 Total in Pinecone: {pinecone.get_document_count()}")
    print("=" * 80)

if __name__ == "__main__":
    analyze_contracts()