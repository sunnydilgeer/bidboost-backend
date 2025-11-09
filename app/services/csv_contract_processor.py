"""
CSV Contract Processor for UK Contracts Finder
Downloads and processes CSV data into ContractOpportunity objects
"""

import csv
import logging
from datetime import datetime, timezone
from typing import List, Optional
from io import StringIO

from app.models.schemas import ContractOpportunity

logger = logging.getLogger(__name__)


class CSVContractProcessor:
    """Process UK Contracts Finder CSV data"""
    
    def __init__(self, csv_file_path: Optional[str] = None):
        """
        Initialize processor.
        
        Args:
            csv_file_path: Path to local CSV file.
        """
        self.csv_file_path = csv_file_path
    
    async def close(self):
        """Close the HTTP client (no-op for local files)"""
        pass
    
    def read_local_csv(self) -> str:
        """Read CSV from local file"""
        try:
            logger.info(f"📥 Reading CSV from {self.csv_file_path}")
            with open(self.csv_file_path, 'r', encoding='utf-8') as f:
                content = f.read()
            logger.info(f"✅ Read {len(content):,} bytes from local file")
            return content
        except Exception as e:
            logger.error(f"❌ Failed to read local CSV: {e}")
            raise
    
    def parse_csv(self, csv_content: str) -> List[dict]:
        """Parse CSV content into list of dicts"""
        try:
            csv_file = StringIO(csv_content)
            reader = csv.DictReader(csv_file)
            rows = list(reader)
            logger.info(f"✅ Parsed {len(rows):,} rows from CSV")
            return rows
        except Exception as e:
            logger.error(f"❌ Failed to parse CSV: {e}")
            raise
    
    def _parse_date(self, date_str: Optional[str]) -> Optional[datetime]:
        """Parse date string to datetime with timezone (handles multiple formats)"""
        if not date_str or date_str.strip() == "":
            return None
        
        date_str = date_str.strip()
        
        # Try ISO 8601 formats first (most common in the CSV)
        try:
            # Handle ISO format with Z (2023-02-15T09:55:27Z)
            if date_str.endswith('Z'):
                dt = datetime.fromisoformat(date_str.replace('Z', '+00:00'))
                return dt
            # Handle ISO format with timezone (2022-07-26T10:17:59+01:00)
            elif 'T' in date_str and ('+' in date_str or date_str.count(':') >= 2):
                dt = datetime.fromisoformat(date_str)
                return dt
        except (ValueError, AttributeError):
            pass
        
        # Fallback to other formats
        formats = [
            "%d/%m/%Y",  # 25/12/2024
            "%d-%m-%Y",  # 25-12-2024
            "%Y-%m-%d",  # 2024-12-25 (ISO)
            "%d/%m/%Y %H:%M:%S",  # With time
        ]
        
        for fmt in formats:
            try:
                dt = datetime.strptime(date_str, fmt)
                # Add UTC timezone to match existing pattern
                return dt.replace(tzinfo=timezone.utc)
            except ValueError:
                continue
        
        logger.warning(f"⚠️ Could not parse date: {date_str}")
        return None
    
    def _parse_value(self, value_str: Optional[str]) -> Optional[float]:
        """Parse monetary value (handles £, commas, etc.)"""
        if not value_str or value_str.strip() == "":
            return None
        
        try:
            # Remove £, commas, whitespace
            clean = value_str.replace("£", "").replace(",", "").strip()
            return float(clean)
        except ValueError:
            logger.warning(f"⚠️ Could not parse value: {value_str}")
            return None
    
    def _clean_text(self, text: Optional[str]) -> str:
        """Clean text fields (remove excess whitespace, etc.)"""
        if not text:
            return ""
        return " ".join(text.strip().split())
    
    def _parse_cpv_codes(self, cpv_str: Optional[str]) -> List[str]:
        """Parse CPV codes string into list (matches API format)"""
        if not cpv_str:
            return []
        
        # CPV codes might be comma or semicolon separated
        codes = cpv_str.replace(";", ",").split(",")
        return [code.strip() for code in codes if code.strip()]
    
    def row_to_contract(self, row: dict) -> Optional[ContractOpportunity]:
        """
        Convert CSV row to ContractOpportunity object.
        FILTERS: Status="Open" + closing_date > now
        """
        try:
            # FILTER 1: Only "Open" status (matches API "active" filter)
            status = row.get("Status", "").strip()
            if status.lower() != "open":
                logger.debug(f"Skipping non-open: {row.get('Notice Identifier')} (status: {status})")
                return None
            
            # Parse dates
            published_date = self._parse_date(row.get("Published Date"))
            closing_date = self._parse_date(row.get("Closing Date"))
            
            # Skip if no closing date (invalid contract)
            if not closing_date:
                logger.debug(f"Skipping - no closing date: {row.get('Notice Identifier')}")
                return None
            
            # FILTER 2: Skip closed contracts (matches API filter)
            now = datetime.now(timezone.utc)
            if closing_date < now:
                logger.debug(f"Skipping closed: {row.get('Notice Identifier')} (closed: {closing_date.date()})")
                return None
            
            # Skip if no published date (schema requires it)
            if not published_date:
                logger.debug(f"Skipping - no published date: {row.get('Notice Identifier')}")
                return None
            
            # Parse value (prioritize Value Low, fallback to Value High)
            value_low = self._parse_value(row.get("Value Low"))
            value_high = self._parse_value(row.get("Value High"))
            value = value_low if value_low else value_high
            
            # Parse CPV codes
            cpv_codes = self._parse_cpv_codes(row.get("Cpv Codes"))
            
            # Build ContractOpportunity (matches API schema exactly)
            contract = ContractOpportunity(
                notice_id=self._clean_text(row.get("Notice Identifier")),
                title=self._clean_text(row.get("Title")),
                description=self._clean_text(row.get("Description")),
                buyer_name=self._clean_text(row.get("Organisation Name")) or "Unknown Buyer",
                published_date=published_date,
                closing_date=closing_date,
                value=value,
                region=self._clean_text(row.get("Region")),
                cpv_codes=cpv_codes
            )
            
            return contract
            
        except Exception as e:
            logger.warning(f"⚠️ Failed to parse contract {row.get('Notice Identifier', 'unknown')}: {str(e)}")
            return None
    
    async def fetch_contracts(self) -> List[ContractOpportunity]:
        """
        Main method: Read CSV (local file) and return list of open/active contracts.
        Matches the signature of ContractFetcherService.fetch_contracts()
        """
        try:
            # Read CSV from local file
            csv_content = self.read_local_csv()
            
            # Parse CSV
            rows = self.parse_csv(csv_content)
            
            # Convert to ContractOpportunity objects (with filters)
            contracts = []
            for row in rows:
                contract = self.row_to_contract(row)
                if contract:
                    contracts.append(contract)
            
            logger.info(f"✅ Processed {len(contracts)} ACTIVE contracts out of {len(rows)} total")
            return contracts
            
        except Exception as e:
            logger.error(f"❌ Failed to fetch contracts from CSV: {str(e)}")
            raise


# Testing
async def main():
    # Path to your CSV file
    csv_path = "data/notices.csv"  # ← Your CSV file
    
    processor = CSVContractProcessor(csv_file_path=csv_path)
    try:
        contracts = await processor.fetch_contracts()
        print(f"🎉 Fetched {len(contracts)} open contracts")
        
        if contracts:
            print(f"\n📋 Example contract:")
            print(f"  Title: {contracts[0].title}")
            print(f"  Buyer: {contracts[0].buyer_name}")
            print(f"  Closing: {contracts[0].closing_date}")
            print(f"  Value: £{contracts[0].value:,.2f}" if contracts[0].value else "  Value: N/A")
    finally:
        await processor.close()


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())