import csv
from typing import List, Dict, Optional
from datetime import datetime
from pathlib import Path
from app.models.schemas import ContractOpportunity

class SAMCSVProcessor:
    """Process SAM.GOV bulk CSV download (ContractOpportunitiesFullCSV.csv)"""
    
    # CSV Column mapping
    COLUMN_MAP = {
        'notice_id': 'NoticeId',
        'title': 'Title',
        'solicitation_number': 'Sol#',
        'department': 'Department/Ind.Agency',
        'office': 'Office',
        'posted_date': 'PostedDate',
        'type': 'Type',
        'base_type': 'BaseType',
        'archive_date': 'ArchiveDate',
        'set_aside_code': 'SetASideCode',
        'set_aside': 'SetASide',
        'response_deadline': 'ResponseDeadLine',
        'naics_code': 'NaicsCode',
        'classification_code': 'ClassificationCode',
        'pop_city': 'PopCity',
        'pop_state': 'PopState',
        'pop_zip': 'PopZip',
        'pop_country': 'PopCountry',
        'active': 'Active',
        'award_number': 'AwardNumber',
        'award_date': 'AwardDate',
        'award_amount': 'Award$',
        'awardee': 'Awardee',
        'primary_contact_email': 'PrimaryContactEmail',
        'primary_contact_name': 'PrimaryContactFullname',
        'primary_contact_phone': 'PrimaryContactPhone',
        'state': 'State',
        'city': 'City',
        'zip_code': 'ZipCode',
        'country_code': 'CountryCode',
        'link': 'Link',
        'description': 'Description'
    }
    
    def __init__(self, csv_path: str):
        self.csv_path = Path(csv_path)
        
    def process_csv(
        self, 
        max_records: Optional[int] = None,
        filter_types: Optional[List[str]] = None,
        filter_active_only: bool = True
    ) -> List[ContractOpportunity]:
        """
        Parse SAM.GOV CSV and convert to ContractOpportunity objects
        
        Args:
            max_records: Limit processing (for testing)
            filter_types: Only include these types (e.g., ["Solicitation", "Combined Synopsis/Solicitation"])
            filter_active_only: Only include active opportunities (Active="Yes")
        """
        import chardet
        with open(self.csv_path, 'rb') as f:
            result = chardet.detect(f.read(100000))
            detected_encoding = result['encoding']
        
        opportunities = []
        skipped = 0

       
        print(f"📂 Processing {self.csv_path.name}...")
        print(f"🎯 Filters: types={filter_types}, active_only={filter_active_only}")
        
        with open(self.csv_path, 'r', encoding='windows-1252', errors='replace') as f:
            reader = csv.DictReader(f)
            
            for idx, row in enumerate(reader):
                if max_records and len(opportunities) >= max_records:
                    break
                
                # Apply filters
                if filter_active_only and row.get('Active', '').strip().lower() != 'yes':
                    skipped += 1
                    continue
                
                if filter_types:
                    row_type = row.get('Type', '').strip()
                    if row_type not in filter_types:
                        skipped += 1
                        continue
                
                try:
                    opportunity = self._convert_row(row)
                    if opportunity:
                        opportunities.append(opportunity)
                    
                    # Progress indicator
                    if (idx + 1) % 10000 == 0:
                        print(f"✓ Processed {idx + 1:,} rows ({len(opportunities):,} matched, {skipped:,} skipped)...")
                        
                except Exception as e:
                    print(f"⚠️  Row {idx} error: {e}")
                    continue
        
        print(f"\n🎉 Complete!")
        print(f"   Total rows processed: {idx + 1:,}")
        print(f"   Matched opportunities: {len(opportunities):,}")
        print(f"   Skipped: {skipped:,}")
        
        return opportunities
    
    def _convert_row(self, row: Dict) -> Optional[ContractOpportunity]:
        """Convert CSV row to ContractOpportunity schema"""
        
        try:
            # Extract buyer name (Department + Office)
            department = row.get('Department/Ind.Agency', '').strip()
            office = row.get('Office', '').strip()
            buyer_name = f"{department} - {office}" if department and office else (department or office)
            
            # Determine region (use place of performance state, fallback to office state)
            region = row.get('PopState', '').strip() or row.get('State', '').strip()
            
            # Parse dates
            posted_date = self._parse_date(row.get('PostedDate', ''))
            closing_date = self._parse_date(row.get('ResponseDeadLine', ''))
            
            # Parse award amount
            award_amount = self._parse_value(row.get('Award$', ''))
            
            # NAICS code (can be multiple, take first)
            naics_raw = row.get('NaicsCode', '').strip()
            naics_codes = [naics_raw] if naics_raw else []
            
            # Determine if suitable for SME
            set_aside = row.get('SetASide', '').strip()
            set_aside_code = row.get('SetASideCode', '').strip()
            suitable_for_sme = self._is_small_business(set_aside, set_aside_code)
            
            return ContractOpportunity(
                notice_id=row.get('NoticeId', '').strip(),
                title=row.get('Title', '').strip(),
                description=row.get('Description', '').strip(),
                buyer_name=buyer_name,
                published_date=posted_date,
                closing_date=closing_date,
                value=award_amount,
                cpv_codes=naics_codes,  # Using NAICS as CPV equivalent
                region=region,
                contact_email=row.get('PrimaryContactEmail', '').strip(),
                suitable_for_sme=suitable_for_sme,
                source_url=row.get('Link', '').strip(),
                metadata={
                    'source': 'SAM.GOV_CSV',
                    'solicitation_number': row.get('Sol#', '').strip(),
                    'opportunity_type': row.get('Type', '').strip(),
                    'base_type': row.get('BaseType', '').strip(),
                    'set_aside': set_aside,
                    'set_aside_code': set_aside_code,
                    'psc_code': row.get('ClassificationCode', '').strip(),
                    'award_number': row.get('AwardNumber', '').strip(),
                    'award_date': row.get('AwardDate', '').strip(),
                    'awardee': row.get('Awardee', '').strip(),
                    'contact_name': row.get('PrimaryContactFullname', '').strip(),
                    'contact_phone': row.get('PrimaryContactPhone', '').strip(),
                    'place_of_performance': f"{row.get('PopCity', '')}, {row.get('PopState', '')}".strip(', '),
                    'active': row.get('Active', '').strip(),
                    'archive_date': row.get('ArchiveDate', '').strip()
                }
            )
        except Exception as e:
            print(f"⚠️  Conversion error: {e}")
            return None
    
    def _parse_date(self, date_str: str) -> Optional[str]:
        """Parse SAM.GOV date formats"""
        if not date_str or date_str.strip() == '':
            return None
        
        date_str = date_str.strip()
        
        # Try common formats
        formats = [
            "%Y-%m-%d %H:%M:%S.%f%z",   # 2025-11-18 23:04:27.509-05
            "%Y-%m-%dT%H:%M:%S%z",       # 2025-11-21T16:00:00-05:00
            "%Y-%m-%d",                  # 2025-11-18
            "%m/%d/%Y",                  # 11/18/2025
        ]
        
        for fmt in formats:
            try:
                dt = datetime.strptime(date_str.split('.')[0].replace('T', ' '), fmt.replace('%z', '').replace('%f', ''))
                return dt.isoformat()
            except:
                continue
        
        return None
    
    def _parse_value(self, value_str: str) -> Optional[float]:
        """Extract numeric value from string"""
        if not value_str or value_str.strip() in ['', 'null']:
            return None
        
        try:
            # Remove currency symbols, commas, spaces
            clean = value_str.replace('$', '').replace(',', '').replace(' ', '').strip()
            return float(clean)
        except:
            return None
    
    def _is_small_business(self, set_aside: str, set_aside_code: str) -> bool:
        """Determine if opportunity is suitable for SMEs"""
        if not set_aside and not set_aside_code:
            return True  # Unrestricted = all can bid
        
        # Check if contains small business keywords
        combined = f"{set_aside} {set_aside_code}".upper()
        small_biz_keywords = ['SMALL BUSINESS', 'SBA', '8A', 'HUBZONE', 'SDVOSB', 'WOSB', 'EDWOSB']
        
        return any(keyword in combined for keyword in small_biz_keywords)
    
    def get_statistics(self, opportunities: List[ContractOpportunity]) -> Dict:
        """Generate statistics from processed opportunities"""
        stats = {
            'total': len(opportunities),
            'by_type': {},
            'by_set_aside': {},
            'with_deadlines': 0,
            'with_values': 0,
            'by_state': {},
            'sme_suitable': 0
        }
        
        for opp in opportunities:
            # Type breakdown
            opp_type = opp.metadata.get('opportunity_type', 'Unknown')
            stats['by_type'][opp_type] = stats['by_type'].get(opp_type, 0) + 1
            
            # Set-aside breakdown
            set_aside = opp.metadata.get('set_aside', 'Unrestricted') or 'Unrestricted'
            stats['by_set_aside'][set_aside] = stats['by_set_aside'].get(set_aside, 0) + 1
            
            # Coverage stats
            if opp.closing_date:
                stats['with_deadlines'] += 1
            if opp.value:
                stats['with_values'] += 1
            if opp.suitable_for_sme:
                stats['sme_suitable'] += 1
            
            # Regional breakdown
            if opp.region:
                stats['by_state'][opp.region] = stats['by_state'].get(opp.region, 0) + 1
        
        return stats


# Test script
if __name__ == "__main__":
    import json
    
    csv_path = "data/sam_gov/ContractOpportunitiesFullCSV.csv"
    processor = SAMCSVProcessor(csv_path)
    
    print("=" * 60)
    print("TEST 1: Process first 100 rows (all types)")
    print("=" * 60)
    sample_all = processor.process_csv(max_records=100, filter_active_only=False)
    
    stats = processor.get_statistics(sample_all)
    print(f"\n📊 Statistics:")
    print(f"   Total: {stats['total']}")
    print(f"   With deadlines: {stats['with_deadlines']} ({stats['with_deadlines']/stats['total']*100:.1f}%)")
    print(f"   SME suitable: {stats['sme_suitable']}")
    
    print(f"\n   By Type:")
    for t, count in sorted(stats['by_type'].items(), key=lambda x: -x[1])[:5]:
        print(f"      {t}: {count}")
    
    print("\n" + "=" * 60)
    print("TEST 2: Active Solicitations Only")
    print("=" * 60)
    solicitations = processor.process_csv(
        max_records=1000,
        filter_types=["Solicitation", "Combined Synopsis/Solicitation"],
        filter_active_only=True
    )
    
    print(f"\n✅ Found {len(solicitations)} active solicitations")
    
    # Save sample
    if solicitations:
        with open('sam_solicitations_sample.json', 'w') as f:
            json.dump([s.dict() for s in solicitations[:10]], f, indent=2, default=str)
        print(f"💾 Saved 10 samples to sam_solicitations_sample.json")
    