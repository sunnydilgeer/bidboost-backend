from lxml import etree
from pathlib import Path
import json
from datetime import datetime
from typing import Dict, List, Optional

NAMESPACES = {
    'cbc': 'urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2',
    'cac': 'urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2',
    'efac': 'http://data.europa.eu/p27/eforms-ubl-extension-aggregate-components/1',
    'efbc': 'http://data.europa.eu/p27/eforms-ubl-extension-basic-components/1',
    'efext': 'http://data.europa.eu/p27/eforms-ubl-extensions/1'
}

class TEDParser:
    def __init__(self, target_langs: List[str] = ['EN', 'en']):
        self.target_langs = target_langs
    
    def parse_notice(self, xml_path: Path) -> Optional[Dict]:
        """Parse single TED XML notice to ContractOpportunity format"""
        try:
            tree = etree.parse(str(xml_path))
            root = tree.getroot()
            
            # Extract core fields
            notice_id = self._get_text(root, "//cbc:ID[@schemeName='notice-id']")
            if not notice_id:
                return None
            
            return {
                "notice_id": notice_id,
                "title": self._get_multilang_text(root, "//cac:ProcurementProject/cbc:Name"),
                "description": self._get_multilang_text(root, "//cac:ProcurementProject/cbc:Description"),
                "buyer_name": self._get_buyer_name(root),
                "published_date": self._get_text(root, "//efbc:PublicationDate"),
                "closing_date": self._get_deadline(root),
                "closing_time": self._get_text(root, "//cac:ParticipationRequestReceptionPeriod/cbc:EndTime"),
                "value": self._get_value(root),
                "cpv_codes": self._get_cpv_codes(root),
                "region": self._get_nuts_codes(root),
                "contact_email": self._get_contact(root, "cbc:ElectronicMail"),
                "contact_phone": self._get_contact(root, "cbc:Telephone"),
                "links": self._get_links(root),
                "original_language": self._detect_language(root),
                "available_languages": self._get_available_languages(root)
            }
        except Exception as e:
            print(f"Error parsing {xml_path}: {e}")
            return None
    
    def _get_text(self, root, xpath: str) -> Optional[str]:
        """Safe XPath text extraction"""
        elements = root.xpath(xpath, namespaces=NAMESPACES)
        return elements[0].text if elements else None
    
    def _get_multilang_text(self, root, xpath: str) -> str:
        """Extract text with language priority"""
        elements = root.xpath(xpath, namespaces=NAMESPACES)
        
        # Try preferred languages first
        for lang in self.target_langs:
            for elem in elements:
                if elem.get('languageID', '').upper() == lang.upper():
                    return elem.text or ""
        
        # Fallback to first available
        return elements[0].text if elements else ""
    
    def _get_buyer_name(self, root) -> str:
        """Extract buyer from ORG-0001 (actual contracting authority)"""
        org_xpath = "//efac:Organization[efac:Company/cac:PartyIdentification/cbc:ID='ORG-0001']//cac:PartyName/cbc:Name"
        return self._get_text(root, org_xpath) or "Unknown"
    
    def _get_cpv_codes(self, root) -> List[str]:
        """Extract main + additional CPV codes"""
        cpv_codes = []
        
        # Main CPV
        main = root.xpath("//cac:MainCommodityClassification/cbc:ItemClassificationCode", namespaces=NAMESPACES)
        cpv_codes.extend([c.text for c in main if c.text])
        
        # Additional CPVs
        additional = root.xpath("//cac:AdditionalCommodityClassification/cbc:ItemClassificationCode", namespaces=NAMESPACES)
        cpv_codes.extend([c.text for c in additional if c.text])
        
        return cpv_codes
    
    def _get_deadline(self, root) -> Optional[str]:
        """Extract closing date in ISO format"""
        date_str = self._get_text(root, "//cac:ParticipationRequestReceptionPeriod/cbc:EndDate")
        return date_str
    
    def _get_value(self, root) -> Optional[float]:
        """Extract estimated value in EUR"""
        value_str = self._get_text(root, "//cac:RequestedTenderTotal/cbc:EstimatedOverallContractAmount")
        try:
            return float(value_str) if value_str else None
        except:
            return None
    
    def _get_nuts_codes(self, root) -> List[str]:
        """Extract NUTS region codes"""
        nuts = root.xpath("//cac:RealizedLocation/cac:Address/cbc:CountrySubentityCode[@listName='nuts']", namespaces=NAMESPACES)
        return [n.text for n in nuts if n.text]
    
    def _get_contact(self, root, field: str) -> Optional[str]:
        """Extract contact info from first organization"""
        xpath = f"//efac:Organization[1]//cac:Contact/{field}"
        return self._get_text(root, xpath)
    
    def _get_links(self, root) -> List[str]:
        """Extract tender document URLs"""
        urls = root.xpath("//cac:CallForTendersDocumentReference//cac:ExternalReference/cbc:URI", namespaces=NAMESPACES)
        return [u.text for u in urls if u.text]
    
    def _detect_language(self, root) -> str:
        """Detect primary language of notice"""
        title_elem = root.xpath("//cac:ProcurementProject/cbc:Name[1]", namespaces=NAMESPACES)
        return title_elem[0].get('languageID', 'EN') if title_elem else 'EN'
    
    def _get_available_languages(self, root) -> List[str]:
        """List all available languages in notice"""
        langs = set()
        for elem in root.xpath("//*[@languageID]", namespaces=NAMESPACES):
            langs.add(elem.get('languageID'))
        return list(langs)

def parse_directory(input_dir: Path, output_file: Path = Path("ted_opportunities.json")):
    """Parse all XMLs in directory"""
    parser = TEDParser()
    opportunities = []
    
    for xml_file in input_dir.rglob("*.xml"):
        result = parser.parse_notice(xml_file)
        if result:
            opportunities.append(result)
    
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(opportunities, f, indent=2, ensure_ascii=False)
    
    print(f"Parsed {len(opportunities)} opportunities → {output_file}")

if __name__ == "__main__":
    input_dir = Path("data/TED")
    output_file = Path("ted_opportunities.json")
    
    print(f"🔍 Scanning {input_dir} for XML files...")
    xml_count = len(list(input_dir.rglob("*.xml")))
    print(f"📁 Found {xml_count} XML files")
    
    parse_directory(input_dir, output_file)