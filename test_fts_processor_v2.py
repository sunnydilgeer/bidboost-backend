#!/usr/bin/env python3
"""
Enhanced FTS Processor - V2 Compatible
Tests data quality for FTS scraped opportunities and awards
Supports both V1 and V2 JSON files with progress tracking
"""
import json
import sys
from pathlib import Path
from typing import Dict, List, Tuple
from datetime import datetime

# Default to V2, but allow V1 via command line
INFILE = "fts_live_rich_v2.json" if len(sys.argv) < 2 else sys.argv[1]


def is_pin_or_market_engagement(entry: Dict) -> Tuple[bool, str]:
    """
    Determine if an opportunity is a PIN or market engagement (no deadline expected)
    Returns (is_special_notice, notice_type)
    """
    title = (entry.get('title') or '').lower()
    desc = (entry.get('description') or '').lower()
    
    # Check for Prior Information Notice (PIN)
    if any([
        'prior information' in title,
        'prior information' in desc,
        'f01:' in desc,
        'f01 -' in desc,
        'preliminary market' in title,
        'preliminary market' in desc,
    ]):
        return (True, "Prior Information Notice (PIN)")
    
    # Check for Market Engagement
    if any([
        'market engagement' in title,
        'market engagement' in desc,
        'preliminary engagement' in title,
        'supplier engagement' in title,
        'industry engagement' in title,
    ]):
        return (True, "Market Engagement")
    
    # Check for expressions of interest / pre-qualification
    if any([
        'expression of interest' in title,
        'expressions of interest' in title,
        'pqq' in title.split(),  # Pre-Qualification Questionnaire
        'pre-qualification' in title,
    ]):
        return (True, "Expression of Interest / PQQ")
    
    return (False, "Standard Opportunity")


def analyze_opportunities(data: List[Dict]) -> Dict:
    """Analyze opportunities with PIN/market engagement detection"""
    opportunities = [d for d in data if d.get('notice_type') == 'opportunity']
    
    # Categorize opportunities
    pins = []
    market_engagement = []
    eoi_pqq = []
    standard_opps = []
    
    for opp in opportunities:
        is_special, notice_type = is_pin_or_market_engagement(opp)
        
        if is_special:
            if "PIN" in notice_type:
                pins.append(opp)
            elif "Market Engagement" in notice_type:
                market_engagement.append(opp)
            elif "Expression of Interest" in notice_type:
                eoi_pqq.append(opp)
        else:
            standard_opps.append(opp)
    
    # Analyze standard opportunities (should have deadlines)
    standard_with_deadline = [o for o in standard_opps if o.get('deadline')]
    standard_missing_deadline = [o for o in standard_opps if not o.get('deadline')]
    
    # NEW: Filter for current/future deadlines
    now = datetime.now()
    current_deadlines = []
    expired_deadlines = []
    
    for opp in standard_with_deadline:
        deadline_str = opp.get('deadline', '')
        # Try to parse deadline to check if expired
        try:
            # Handle common formats
            for fmt in ['%d %B %Y, %I:%M%p', '%d %B %Y']:
                try:
                    deadline_dt = datetime.strptime(deadline_str.split('(')[0].strip(), fmt)
                    if deadline_dt >= now:
                        current_deadlines.append(opp)
                    else:
                        expired_deadlines.append(opp)
                    break
                except ValueError:
                    continue
        except:
            # If can't parse, assume it's current
            current_deadlines.append(opp)
    
    # Analyze special notices (may not have deadlines)
    special_with_deadline = [o for o in (pins + market_engagement + eoi_pqq) if o.get('deadline')]
    special_missing_deadline = [o for o in (pins + market_engagement + eoi_pqq) if not o.get('deadline')]
    
    # Overall stats for standard opportunities
    stats = {
        'total_opportunities': len(opportunities),
        'pins': len(pins),
        'market_engagement': len(market_engagement),
        'eoi_pqq': len(eoi_pqq),
        'standard_opportunities': len(standard_opps),
        'standard_with_deadline': len(standard_with_deadline),
        'standard_missing_deadline': len(standard_missing_deadline),
        'current_biddable': len(current_deadlines),
        'expired_deadlines': len(expired_deadlines),
        'special_with_deadline': len(special_with_deadline),
        'special_missing_deadline': len(special_missing_deadline),
        'standard_deadline_rate': (len(standard_with_deadline) / len(standard_opps) * 100) if standard_opps else 0,
    }
    
    # Collect other quality metrics for standard opportunities
    stats['with_value'] = len([o for o in standard_opps if o.get('contract_value')])
    stats['with_buyer'] = len([o for o in standard_opps if o.get('authority_name')])
    stats['with_cpv'] = len([o for o in standard_opps if o.get('cpv_codes')])
    stats['with_description'] = len([o for o in standard_opps if o.get('description')])
    stats['with_region'] = len([o for o in standard_opps if o.get('region')])
    stats['with_contact'] = len([o for o in standard_opps if o.get('authority_email')])
    stats['sme_suitable'] = len([o for o in standard_opps if o.get('suitable_for_sme')])
    
    # Sample entries for display
    stats['sample_standard'] = standard_opps[0] if standard_opps else None
    stats['missing_deadline_samples'] = standard_missing_deadline[:5]
    
    return stats


def analyze_awards(data: List[Dict]) -> Dict:
    """Analyze awarded contracts"""
    awards = [d for d in data if d.get('notice_type') == 'award']
    
    stats = {
        'total_awards': len(awards),
        'with_value': len([a for a in awards if a.get('contract_value')]),
        'with_supplier': len([a for a in awards if a.get('supplier_name')]),
        'with_buyer': len([a for a in awards if a.get('authority_name')]),
        'with_cpv': len([a for a in awards if a.get('cpv_codes')]),
        'with_description': len([a for a in awards if a.get('description')]),
        'with_region': len([a for a in awards if a.get('region')]),
        'with_contact': len([a for a in awards if a.get('authority_email')]),
        'with_award_date': len([a for a in awards if a.get('award_date')]),
        'sme_suitable': len([a for a in awards if a.get('suitable_for_sme')]),
    }
    
    stats['sample_award'] = awards[0] if awards else None
    
    return stats


def get_scrape_progress(data: List[Dict]) -> Dict:
    """Analyze scrape progress - NEW for V2"""
    if not data:
        return {
            'total_scraped': 0,
            'estimated_pages': 0,
            'last_scraped_id': None,
        }
    
    # Count unique tender IDs
    tender_ids = [d.get('tender_id') for d in data if d.get('tender_id')]
    
    # Estimate pages scraped (10 tenders per page average)
    estimated_pages = len(data) // 10
    
    # Get last scraped ID
    last_id = data[-1].get('tender_id') if data else None
    
    return {
        'total_scraped': len(data),
        'unique_tenders': len(set(tender_ids)),
        'estimated_pages': estimated_pages,
        'last_scraped_id': last_id,
    }


def format_percentage(count: int, total: int) -> str:
    """Format count as percentage"""
    if total == 0:
        return "N/A"
    pct = (count / total) * 100
    return f"{count}/{total} ({pct:.1f}%)"


def main():
    """Run FTS data quality analysis"""
    infile = Path(INFILE)
    
    print(f"🔍 Testing file: {INFILE}")
    
    if not infile.exists():
        print(f"❌ Error: {INFILE} not found. Run scraper first.")
        print(f"\nUsage: python test_fts_processor_v2.py [json_file]")
        print(f"Default: fts_live_rich_v2.json")
        print(f"Example: python test_fts_processor_v2.py fts_live_rich.json")
        return
    
    # Load data
    try:
        with open(infile, 'r') as f:
            data = json.load(f)
    except json.JSONDecodeError as e:
        print(f"❌ Error: Invalid JSON in {INFILE}")
        print(f"Error: {e}")
        return
    
    # NEW: Show scrape progress
    progress = get_scrape_progress(data)
    
    print("=" * 60)
    print(f"FTS SCRAPER PROGRESS - {INFILE}")
    print("=" * 60)
    print(f"📊 Total records scraped: {progress['total_scraped']:,}")
    print(f"📄 Estimated pages scraped: ~{progress['estimated_pages']}")
    print(f"🆔 Last tender ID: {progress['last_scraped_id']}")
    print(f"🔢 Unique tenders: {progress['unique_tenders']:,}")
    
    # Analyze
    award_stats = analyze_awards(data)
    opp_stats = analyze_opportunities(data)
    
    # Print Awards Report
    print("\n" + "=" * 60)
    print("FTS PROCESSOR TEST RESULTS - AWARDS")
    print("=" * 60)
    print(f"Total awarded contracts: {award_stats['total_awards']}")
    
    if award_stats['sample_award']:
        sample = award_stats['sample_award']
        print(f"📋 Sample contract:")
        print(f"  Tender ID: {sample['tender_id']}")
        print(f"  Title: {sample.get('title', 'N/A')[:50]}...")
        print(f"  Supplier: {sample.get('supplier_name', 'N/A')}")
        print(f"  Buyer: {sample.get('authority_name', 'N/A')}")
        if sample.get('contract_value'):
            print(f"  Value: £{sample['contract_value']:,.2f}")
        if sample.get('cpv_codes'):
            print(f"  CPV Codes: {', '.join(sample['cpv_codes'][:3])}")
        if sample.get('region'):
            print(f"  Region: {sample['region']}")
    
    print(f"\n📊 Data quality (Awards):")
    print(f"  Contracts with value: {format_percentage(award_stats['with_value'], award_stats['total_awards'])}")
    print(f"  Contracts with supplier: {format_percentage(award_stats['with_supplier'], award_stats['total_awards'])}")
    print(f"  Contracts with buyer: {format_percentage(award_stats['with_buyer'], award_stats['total_awards'])}")
    print(f"  Contracts with CPV codes: {format_percentage(award_stats['with_cpv'], award_stats['total_awards'])}")
    print(f"  Contracts with description: {format_percentage(award_stats['with_description'], award_stats['total_awards'])}")
    print(f"  Contracts with region: {format_percentage(award_stats['with_region'], award_stats['total_awards'])}")
    print(f"  Contracts with contact info: {format_percentage(award_stats['with_contact'], award_stats['total_awards'])}")
    print(f"  Contracts with award date: {format_percentage(award_stats['with_award_date'], award_stats['total_awards'])}")
    print(f"  SME-suitable contracts: {format_percentage(award_stats['sme_suitable'], award_stats['total_awards'])}")
    
    # Print Opportunities Report
    print("\n" + "=" * 60)
    print("FTS PROCESSOR TEST RESULTS - OPPORTUNITIES")
    print("=" * 60)
    print(f"Total opportunities: {opp_stats['total_opportunities']}")
    print(f"\n📋 Opportunity Breakdown:")
    print(f"  Prior Information Notices (no deadline expected): {opp_stats['pins']}")
    print(f"  Market Engagement (no deadline expected): {opp_stats['market_engagement']}")
    print(f"  Expression of Interest/PQQ: {opp_stats['eoi_pqq']}")
    print(f"  Standard Opportunities (MUST have deadline): {opp_stats['standard_opportunities']}")
    print(f"\n⏰ Deadline Status:")
    print(f"  Current/Future deadlines: {opp_stats['current_biddable']} (BIDDABLE)")
    print(f"  Expired deadlines: {opp_stats['expired_deadlines']} (HISTORICAL)")
    
    if opp_stats['sample_standard']:
        sample = opp_stats['sample_standard']
        print(f"\n📋 Sample standard opportunity:")
        print(f"  Tender ID: {sample['tender_id']}")
        print(f"  Title: {sample.get('title', 'N/A')[:50]}...")
        print(f"  Buyer: {sample.get('authority_name', 'N/A')}")
        if sample.get('contract_value'):
            print(f"  Value: £{sample['contract_value']:,.2f}")
        print(f"  Deadline: {sample.get('deadline', 'N/A')}")
        if sample.get('region'):
            print(f"  Region: {sample['region']}")
    
    # Critical deadline stats
    deadline_rate = opp_stats['standard_deadline_rate']
    deadline_status = "✅" if deadline_rate >= 80 else "⚠️  CRITICAL"
    
    print(f"\n📊 Data quality (Standard Opportunities):")
    print(f"  Opportunities with deadline: {format_percentage(opp_stats['standard_with_deadline'], opp_stats['standard_opportunities'])} {deadline_status}")
    print(f"  Opportunities with value: {format_percentage(opp_stats['with_value'], opp_stats['standard_opportunities'])}")
    print(f"  Opportunities with buyer: {format_percentage(opp_stats['with_buyer'], opp_stats['standard_opportunities'])}")
    print(f"  Opportunities with CPV codes: {format_percentage(opp_stats['with_cpv'], opp_stats['standard_opportunities'])}")
    print(f"  Opportunities with description: {format_percentage(opp_stats['with_description'], opp_stats['standard_opportunities'])}")
    print(f"  Opportunities with region: {format_percentage(opp_stats['with_region'], opp_stats['standard_opportunities'])}")
    print(f"  Opportunities with contact info: {format_percentage(opp_stats['with_contact'], opp_stats['standard_opportunities'])}")
    print(f"  SME-suitable opportunities: {format_percentage(opp_stats['sme_suitable'], opp_stats['standard_opportunities'])}")
    
    if opp_stats['standard_missing_deadline'] > 0:
        print(f"\n  🚨 WARNING: {opp_stats['standard_missing_deadline']} standard opportunities missing deadline (CANNOT BID)")
        
        if opp_stats['missing_deadline_samples']:
            print(f"\n  📋 Sample opportunities missing deadlines:")
            for i, sample in enumerate(opp_stats['missing_deadline_samples'], 1):
                print(f"\n    {i}. {sample['tender_id']}")
                print(f"       Title: {sample.get('title', 'N/A')[:60]}...")
                print(f"       URL: {sample['url']}")
    else:
        print(f"\n  ✅ All standard opportunities have deadlines!")
    
    # Special notices deadline info
    if opp_stats['special_missing_deadline'] > 0:
        print(f"\n  ℹ️  INFO: {opp_stats['special_missing_deadline']} PINs/market engagement notices without deadlines (EXPECTED)")
    
    print("\n" + "=" * 60)
    print("📈 SUMMARY")
    print("=" * 60)
    print(f"✅ Total scraped: {progress['total_scraped']:,} records")
    print(f"✅ Biddable opportunities: {opp_stats['current_biddable']}")
    print(f"✅ Competitive intelligence: {award_stats['total_awards']} awards")
    print(f"✅ Deadline coverage: {deadline_rate:.1f}%")
    
    if opp_stats['current_biddable'] > 0:
        print(f"\n🎯 Ready for production sync!")
    else:
        print(f"\n⚠️  No current biddable opportunities found - keep scraping!")
    
    print("=" * 60)


if __name__ == "__main__":
    main()