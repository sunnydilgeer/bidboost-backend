"""
SAM.gov API Scraper - Fix #2 (Updated with API Key)
Fetches full descriptions from SAM.gov API for POOR/MISSING contracts.

Usage:
    python improve_descriptions_from_sam.py --limit 10  # Test on 10 contracts
    python improve_descriptions_from_sam.py             # Process all POOR/MISSING
"""

import argparse
import time
import re
import os
from typing import Optional
from datetime import datetime, timezone

import requests
from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models.company import OpportunityChain


# SAM.gov API Key
SAM_API_KEY = os.getenv("SAM_API_KEY", "SAM-b597a7b8-c26e-491b-80dd-4e5fe477acb6")


def clean_html(text: str) -> str:
    """Remove HTML tags and clean up text."""
    if not text:
        return ""
    text = re.sub(r'<[^>]+>', ' ', text)
    text = re.sub(r'\s+', ' ', text).strip()
    return text


def assess_description_quality(description: str) -> str:
    """Assess quality of description text."""
    if not description:
        return "MISSING"
    
    clean_desc = clean_html(description)
    
    if len(clean_desc) < 50:
        return "POOR"
    
    # Check for garbage patterns
    garbage_keywords = ['see attached', 'see attachment', 'refer to', 'amendment', 'modification']
    if any(keyword in clean_desc.lower() for keyword in garbage_keywords):
        return "POOR"
    
    return "GOOD"


def fetch_sam_gov_description(notice_id: str, sol_number: str) -> Optional[str]:
    """
    Fetch full description from SAM.gov API.
    
    Args:
        notice_id: The NoticeId (OPP_ID) from the CSV
        sol_number: The solicitation number (Sol#) from the CSV
    
    Returns:
        Extracted description or None if not found
    """
    
    # SAM.gov Opportunities API v2
    url = "https://api.sam.gov/opportunities/v2/search"
    
    # Try searching by solicitation number
    params = {
        'api_key': SAM_API_KEY,
        'postedFrom': '01/01/2020',
        'postedTo': '12/31/2026',
        'ptype': 'o',
        'solnum': sol_number,
        'limit': 10
    }
    
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36',
            'Accept': 'application/json'
        }
        
        response = requests.get(url, params=params, headers=headers, timeout=15)
        
        if response.status_code != 200:
            print(f"      ⚠️  API returned status {response.status_code}")
            return None
        
        data = response.json()
        
        # Parse the API response
        if 'opportunitiesData' in data and len(data['opportunitiesData']) > 0:
            # Look for matching opportunity
            for opp in data['opportunitiesData']:
                opp_notice_id = opp.get('noticeId', '')
                opp_sol_num = opp.get('solicitationNumber', '')
                
                # Match by either notice ID or solicitation number
                if opp_notice_id == notice_id or opp_sol_num == sol_number:
                    # Try multiple description fields
                    description = (
                        opp.get('description', '') or
                        opp.get('synopsis', '') or
                        opp.get('additionalInfoText', '') or
                        ''
                    )
                    
                    # Clean and return if substantial
                    if description:
                        cleaned = clean_html(description)
                        if len(cleaned) > 100:
                            return cleaned
            
            # If no exact match, return first result's description (best effort)
            first_opp = data['opportunitiesData'][0]
            description = (
                first_opp.get('description', '') or
                first_opp.get('synopsis', '') or
                first_opp.get('additionalInfoText', '') or
                ''
            )
            
            if description:
                cleaned = clean_html(description)
                if len(cleaned) > 100:
                    return cleaned
        
        return None
        
    except requests.exceptions.RequestException as e:
        print(f"      ⚠️  Network error: {str(e)[:100]}")
        return None
    except Exception as e:
        print(f"      ⚠️  Parse error: {str(e)[:100]}")
        return None


def improve_descriptions(db: Session, limit: Optional[int] = None, verbose: bool = True):
    """
    Fetch improved descriptions from SAM.gov API for POOR/MISSING contracts.
    """
    
    if verbose:
        print("=" * 70)
        print("SAM.GOV API SCRAPER - FIX #2")
        print("=" * 70)
        print()
    
    # Get all POOR/MISSING contracts
    query = db.query(OpportunityChain).filter(
        OpportunityChain.base_description_quality.in_(['POOR', 'MISSING'])
    )
    
    if limit:
        query = query.limit(limit)
    
    contracts = query.all()
    
    if verbose:
        print(f"📊 Found {len(contracts)} contracts with POOR/MISSING descriptions")
        if limit:
            print(f"   Processing first {limit} for testing")
        print()
    
    improved_count = 0
    failed_count = 0
    still_poor_count = 0
    
    for idx, contract in enumerate(contracts, 1):
        if verbose:
            print(f"[{idx}/{len(contracts)}] {contract.solicitation_number}...")
        
        # Fetch description from SAM.gov API
        new_description = fetch_sam_gov_description(
            contract.base_notice_id,
            contract.base_sol_number
        )
        
        if new_description:
            # Assess new description quality
            new_quality = assess_description_quality(new_description)
            
            if new_quality == "GOOD":
                # Update database
                contract.base_description = new_description
                contract.base_description_quality = "GOOD"
                contract.needs_sow_extraction = False
                contract.updated_at = datetime.now(timezone.utc)
                
                improved_count += 1
                
                if verbose:
                    preview = new_description[:100] + "..." if len(new_description) > 100 else new_description
                    print(f"   ✅ Improved! {contract.base_description_quality} → GOOD")
                    print(f"      Preview: {preview}")
            else:
                still_poor_count += 1
                if verbose:
                    print(f"   ⚠️  Fetched but still {new_quality}")
        else:
            failed_count += 1
            if verbose:
                print(f"   ❌ No description found in API")
        
        # Commit every 10 updates
        if idx % 10 == 0:
            db.commit()
        
        # Rate limiting - be nice to SAM.gov
        time.sleep(0.5)
        
        if verbose and idx % 10 == 0:
            print()
    
    db.commit()
    
    if verbose:
        print()
        print("=" * 70)
        print("✅ SAM.GOV API SCRAPING COMPLETE")
        print("=" * 70)
        print(f"   Improved to GOOD: {improved_count}")
        print(f"   API returned nothing: {failed_count}")
        print(f"   Fetched but still poor: {still_poor_count}")
        print(f"   Total processed: {len(contracts)}")
        
        # Calculate improvement percentage
        if len(contracts) > 0:
            improvement_pct = (improved_count / len(contracts)) * 100
            print(f"   Success rate: {improvement_pct:.1f}%")
        
        print()
        
        # Show updated stats
        from sqlalchemy import func
        stats = db.query(
            OpportunityChain.base_description_quality,
            func.count(OpportunityChain.id)
        ).group_by(OpportunityChain.base_description_quality).all()
        
        total = sum(count for _, count in stats)
        print("📊 Overall Database Quality:")
        for quality, count in stats:
            pct = (count / total * 100) if total > 0 else 0
            print(f"   {quality}: {count} ({pct:.1f}%)")


def main():
    parser = argparse.ArgumentParser(description="Improve descriptions using SAM.gov API")
    parser.add_argument('--limit', type=int, default=None, help="Process only first N contracts (for testing)")
    parser.add_argument('--quiet', action='store_true', help="Suppress output")
    
    args = parser.parse_args()
    
    db = SessionLocal()
    
    try:
        improve_descriptions(db, limit=args.limit, verbose=not args.quiet)
    finally:
        db.close()


if __name__ == "__main__":
    main()