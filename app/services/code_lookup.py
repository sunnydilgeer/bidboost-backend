"""
NAICS and PSC Code Lookup Service
Converts government codes to human-readable descriptions
FIXED: Handles .0 suffix on NAICS codes from Pinecone
"""
import json
from pathlib import Path
from typing import Optional
import logging

logger = logging.getLogger(__name__)

class CodeLookupService:
    """Service for looking up NAICS and PSC code descriptions"""
    
    def __init__(self):
        """Load code mappings from JSON files"""
        data_dir = Path(__file__).parent.parent / "data"
        
        try:
            # Load NAICS codes
            naics_path = data_dir / "naics_codes.json"
            if naics_path.exists():
                with open(naics_path, 'r') as f:
                    self.naics_codes = json.load(f)
                logger.info(f"✅ Loaded {len(self.naics_codes)} NAICS codes")
            else:
                logger.warning("⚠️ naics_codes.json not found, creating empty mapping")
                self.naics_codes = {}
            
            # Load PSC codes
            psc_path = data_dir / "psc_codes.json"
            if psc_path.exists():
                with open(psc_path, 'r') as f:
                    self.psc_codes = json.load(f)
                logger.info(f"✅ Loaded {len(self.psc_codes)} PSC codes")
            else:
                logger.warning("⚠️ psc_codes.json not found, creating empty mapping")
                self.psc_codes = {}
            
        except Exception as e:
            logger.error(f"❌ Failed to load code mappings: {e}")
            self.naics_codes = {}
            self.psc_codes = {}
    
    def get_naics_name(self, code: str) -> str:
        """
        Get NAICS code description
        
        Args:
            code: NAICS code (e.g., "336413" or "336413.0")
            
        Returns:
            Description or the code itself if not found
        """
        if not code:
            return ""
        
        # Clean code: remove .0 suffix if present (Pinecone float issue)
        clean_code = str(code)
        if clean_code.endswith('.0'):
            clean_code = clean_code[:-2]
        
        return self.naics_codes.get(clean_code, code)
    
    def get_psc_name(self, code: str) -> str:
        """
        Get PSC code description
        
        Args:
            code: PSC code (e.g., "5995")
            
        Returns:
            Description or the code itself if not found
        """
        if not code:
            return ""
        return self.psc_codes.get(str(code), code)
    
    def enrich_contract(self, contract: dict) -> dict:
        """
        Add human-readable code descriptions to contract data
        
        Args:
            contract: Contract dict with naics_code and psc_code
            
        Returns:
            Contract dict with added naics_name and psc_name fields
        """
        if 'naics_code' in contract and contract['naics_code']:
            contract['naics_name'] = self.get_naics_name(contract['naics_code'])
        
        if 'psc_code' in contract and contract['psc_code']:
            contract['psc_name'] = self.get_psc_name(contract['psc_code'])
        
        return contract

# Singleton instance
_code_lookup_service = None

def get_code_lookup_service() -> CodeLookupService:
    """Get singleton instance of CodeLookupService"""
    global _code_lookup_service
    if _code_lookup_service is None:
        _code_lookup_service = CodeLookupService()
    return _code_lookup_service

def clean_naics_code(naics_code: str | None) -> str | None:
    """Remove .0 suffix from NAICS codes for display"""
    if not naics_code:
        return naics_code
    
    code_str = str(naics_code)
    if code_str.endswith('.0'):
        return code_str[:-2]
    return code_str