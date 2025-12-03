"""
Extract unique NAICS and PSC codes from Pinecone
Run this to see which codes you need to populate in JSON files
"""
import sys
import os

# Add parent directory to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app.services.pinecone_store import PineconeStoreService
from app.core.config import settings
import numpy as np

def extract_codes():
    """Extract all unique NAICS and PSC codes from Pinecone"""
    
    print("🔍 Connecting to Pinecone...")
    pinecone = PineconeStoreService(api_key=settings.PINECONE_API_KEY)
    
    # Use a dummy vector to query many results
    dummy_vector = np.random.rand(768).tolist()
    
    print("📊 Fetching contracts from Pinecone (this may take a moment)...")
    results = pinecone.index.query(
        vector=dummy_vector,
        top_k=10000,  # Get as many as possible
        include_metadata=True
    )
    
    naics_set = set()
    psc_set = set()
    
    print(f"✅ Retrieved {len(results.matches)} contracts\n")
    
    for match in results.matches:
        meta = match.metadata
        
        # Collect NAICS codes
        if meta.get('naics_code'):
            naics_set.add(meta['naics_code'])
        
        # Collect PSC codes
        if meta.get('psc_code'):
            psc_set.add(meta['psc_code'])
    
    print(f"📋 Found {len(naics_set)} unique NAICS codes")
    print(f"📋 Found {len(psc_set)} unique PSC codes\n")
    
    # Display codes
    print("=" * 80)
    print("🏷️  NAICS CODES (copy these to naics_codes.json):")
    print("=" * 80)
    for code in sorted(naics_set):
        print(f'  "{code}": "DESCRIPTION_HERE",')
    
    print("\n" + "=" * 80)
    print("📦 PSC CODES (copy these to psc_codes.json):")
    print("=" * 80)
    for code in sorted(psc_set):
        print(f'  "{code}": "DESCRIPTION_HERE",')
    
    # Save to files
    with open('/tmp/unique_naics.txt', 'w') as f:
        f.write('\n'.join(sorted(naics_set)))
    
    with open('/tmp/unique_psc.txt', 'w') as f:
        f.write('\n'.join(sorted(psc_set)))
    
    print("\n" + "=" * 80)
    print("✅ Saved code lists to:")
    print("   - /tmp/unique_naics.txt")
    print("   - /tmp/unique_psc.txt")
    print("=" * 80)
    
    return naics_set, psc_set

if __name__ == "__main__":
    try:
        extract_codes()
    except Exception as e:
        print(f"\n❌ Error: {str(e)}")
        import traceback
        traceback.print_exc()