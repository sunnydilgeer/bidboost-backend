import asyncio
import json
from pathlib import Path
from datetime import datetime, timezone
from collections import Counter
from ted_processor import TEDProcessor

async def test_ted_processor():
    """Validate TED data quality"""
    print("🔍 Testing TED Processor...\n")
    
    # Check if data file exists
    data_file = Path("ted_opportunities.json")
    if not data_file.exists():
        print("❌ ted_opportunities.json not found")
        return
    
    # Load raw data
    with open(data_file, 'r', encoding='utf-8') as f:
        raw_data = json.load(f)
    
    print(f"📊 Raw TED Data: {len(raw_data)} notices\n")
    
    # Initialize processor
    processor = TEDProcessor()
    opportunities = await processor.fetch_opportunities()
    
    print(f"\n✅ Processed: {len(opportunities)} opportunities\n")
    
    # Quality Metrics
    metrics = {
        'total_raw': len(raw_data),
        'total_processed': len(opportunities),
        'english_native': 0,
        'translated': 0,
        'with_deadline': 0,
        'with_value': 0,
        'with_cpv': 0,
        'with_contact': 0,
        'avg_value_eur': 0,
        'languages': Counter(),
        'countries': Counter(),
    }
    
    total_value = 0
    value_count = 0
    
    for opp in opportunities:
        # Language stats - safely access metadata
        try:
            if hasattr(opp, 'metadata') and opp.metadata:
                if opp.metadata.get('translated'):
                    metrics['translated'] += 1
                else:
                    metrics['english_native'] += 1
                
                orig_lang = opp.metadata.get('original_language', 'EN')
                metrics['languages'][orig_lang] += 1
        except:
            metrics['english_native'] += 1
        
        # Field coverage
        if opp.closing_date:
            metrics['with_deadline'] += 1
        if opp.value:
            metrics['with_value'] += 1
            total_value += opp.value
            value_count += 1
        if opp.cpv_codes:
            metrics['with_cpv'] += 1
        if opp.contact_email:
            metrics['with_contact'] += 1
        
        # Region stats
        if opp.region:
            metrics['countries'][opp.region.split(',')[0].strip()] += 1
    
    if value_count > 0:
        metrics['avg_value_eur'] = total_value / value_count
    
    # Print Report
    print("=" * 60)
    print("📈 TED DATA QUALITY REPORT")
    print("=" * 60)
    
    print(f"\n🔢 Volume:")
    print(f"  Raw notices:        {metrics['total_raw']}")
    print(f"  Processed:          {metrics['total_processed']}")
    if metrics['total_raw'] > 0:
        print(f"  Filter rate:        {(1 - metrics['total_processed']/metrics['total_raw'])*100:.1f}%")
    
    print(f"\n🌍 Language Distribution:")
    print(f"  English-native:     {metrics['english_native']}")
    print(f"  Translated:         {metrics['translated']}")
    for lang, count in metrics['languages'].most_common(5):
        print(f"  {lang}:                 {count}")
    
    print(f"\n📍 Geographic Coverage:")
    for country, count in metrics['countries'].most_common(10):
        print(f"  {country}:              {count}")
    
    print(f"\n✅ Field Completeness:")
    if metrics['total_processed'] > 0:
        print(f"  Deadline coverage:  {metrics['with_deadline']/metrics['total_processed']*100:.1f}%")
        print(f"  Value coverage:     {metrics['with_value']/metrics['total_processed']*100:.1f}%")
        print(f"  CPV coverage:       {metrics['with_cpv']/metrics['total_processed']*100:.1f}%")
        print(f"  Contact coverage:   {metrics['with_contact']/metrics['total_processed']*100:.1f}%")
    else:
        print(f"  ❌ No opportunities passed filtering")
    
    print(f"\n💰 Value Statistics:")
    if value_count > 0:
        print(f"  Average value:      €{metrics['avg_value_eur']:,.2f}")
    else:
        print(f"  No value data available")
    
    print("\n" + "=" * 60)
    
    # Sample opportunities
    if opportunities:
        print("\n📋 Sample Opportunities (First 5):\n")
        for i, opp in enumerate(opportunities[:5], 1):
            print(f"{i}. {opp.title[:80]}")
            print(f"   ID: {opp.notice_id}")
            print(f"   Buyer: {opp.buyer_name}")
            print(f"   Value: €{opp.value:,.2f}" if opp.value else "   Value: N/A")
            print(f"   Deadline: {opp.closing_date}")
            print(f"   CPV Codes: {', '.join(opp.cpv_codes[:3]) if opp.cpv_codes else 'N/A'}")
            print()
    
    return metrics

if __name__ == "__main__":
    asyncio.run(test_ted_processor())