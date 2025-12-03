"""
Test NAICS and PSC code coverage
Checks that all codes in your Pinecone data have mappings
"""

import json
import sys
from pathlib import Path
from typing import Dict, Set, Tuple

def load_your_codes() -> Tuple[Set[str], Set[str]]:
    """Load unique codes from extraction script output"""
    
    naics_path = Path("/tmp/unique_naics.txt")
    psc_path = Path("/tmp/unique_psc.txt")
    
    if not naics_path.exists() or not psc_path.exists():
        print("❌ Missing code files. Run extraction script first:")
        print("   python -m app.tasks.extract_unique_codes")
        sys.exit(1)
    
    # Load NAICS codes
    with open(naics_path, 'r') as f:
        naics_codes = set()
        for line in f:
            code = line.strip()
            if code and code != '[]':
                # Remove .0 suffix
                code = code.replace('.0', '')
                naics_codes.add(code)
    
    # Load PSC codes
    with open(psc_path, 'r') as f:
        psc_codes = set([line.strip() for line in f if line.strip() and line.strip() != '[]'])
    
    return naics_codes, psc_codes

def load_mappings() -> Tuple[Dict[str, str], Dict[str, str]]:
    """Load code mappings from JSON files"""
    
    naics_path = Path("app/data/naics_codes.json")
    psc_path = Path("app/data/psc_codes.json")
    
    if not naics_path.exists() or not psc_path.exists():
        print("❌ Missing mapping files:")
        if not naics_path.exists():
            print(f"   {naics_path} not found")
        if not psc_path.exists():
            print(f"   {psc_path} not found")
        sys.exit(1)
    
    with open(naics_path, 'r') as f:
        naics_mapping = json.load(f)
    
    with open(psc_path, 'r') as f:
        psc_mapping = json.load(f)
    
    return naics_mapping, psc_mapping

def test_naics_coverage(your_codes: Set[str], mapping: Dict[str, str]):
    """Test NAICS code coverage"""
    
    print("\n" + "="*80)
    print("🏷️  NAICS CODE COVERAGE TEST")
    print("="*80)
    
    missing = your_codes - set(mapping.keys())
    covered = your_codes & set(mapping.keys())
    
    coverage_pct = (len(covered) / len(your_codes) * 100) if your_codes else 0
    
    print(f"\n📊 Results:")
    print(f"   Total unique codes in your data: {len(your_codes)}")
    print(f"   Codes with descriptions:         {len(covered)} ({coverage_pct:.1f}%)")
    print(f"   Codes missing descriptions:      {len(missing)}")
    
    if missing:
        print(f"\n❌ Missing NAICS codes:")
        for code in sorted(missing)[:20]:
            print(f"   {code}")
        if len(missing) > 20:
            print(f"   ... and {len(missing) - 20} more")
        
        # Save to file
        with open('/tmp/missing_naics.txt', 'w') as f:
            for code in sorted(missing):
                f.write(f"{code}\n")
        print(f"\n💾 Full list saved to /tmp/missing_naics.txt")
    else:
        print("\n✅ All NAICS codes are covered!")
    
    # Show sample mappings
    print(f"\n📋 Sample mappings:")
    for code in sorted(covered)[:5]:
        desc = mapping[code][:60] + "..." if len(mapping[code]) > 60 else mapping[code]
        print(f"   {code}: {desc}")
    
    return len(missing) == 0

def test_psc_coverage(your_codes: Set[str], mapping: Dict[str, str]):
    """Test PSC code coverage"""
    
    print("\n" + "="*80)
    print("📦 PSC CODE COVERAGE TEST")
    print("="*80)
    
    missing = your_codes - set(mapping.keys())
    covered = your_codes & set(mapping.keys())
    
    coverage_pct = (len(covered) / len(your_codes) * 100) if your_codes else 0
    
    print(f"\n📊 Results:")
    print(f"   Total unique codes in your data: {len(your_codes)}")
    print(f"   Codes with descriptions:         {len(covered)} ({coverage_pct:.1f}%)")
    print(f"   Codes missing descriptions:      {len(missing)}")
    
    if missing:
        print(f"\n❌ Missing PSC codes:")
        for code in sorted(missing)[:20]:
            print(f"   {code}")
        if len(missing) > 20:
            print(f"   ... and {len(missing) - 20} more")
        
        # Categorize missing codes
        print(f"\n📊 Missing codes by category:")
        categories = {}
        for code in missing:
            if code.isdigit():
                cat = "Numeric (Federal Supply Class)"
            elif code[0].isdigit():
                cat = f"{code[0]}XXX series"
            elif code[0].isalpha():
                cat = f"{code[0]} series"
            else:
                cat = "Other"
            categories[cat] = categories.get(cat, 0) + 1
        
        for cat, count in sorted(categories.items()):
            print(f"   {cat}: {count} codes")
        
        # Save to file
        with open('/tmp/missing_psc.txt', 'w') as f:
            for code in sorted(missing):
                f.write(f"{code}\n")
        print(f"\n💾 Full list saved to /tmp/missing_psc.txt")
    else:
        print("\n✅ All PSC codes are covered!")
    
    # Show sample mappings
    print(f"\n📋 Sample mappings:")
    for code in sorted(covered)[:5]:
        desc = mapping[code][:60] + "..." if len(mapping[code]) > 60 else mapping[code]
        print(f"   {code}: {desc}")
    
    return len(missing) == 0

def test_code_lookup_service():
    """Test the actual CodeLookupService"""
    
    print("\n" + "="*80)
    print("🧪 CODE LOOKUP SERVICE TEST")
    print("="*80)
    
    try:
        from app.services.code_lookup import get_code_lookup_service
        
        service = get_code_lookup_service()
        
        # Test NAICS lookup
        test_cases_naics = [
            ("541519", "Other Computer Related Services"),
            ("541519.0", "Other Computer Related Services"),  # Test .0 handling
            ("541511", "Custom Computer Programming Services"),
            ("", ""),  # Empty code
            ("999999", "999999"),  # Non-existent code
        ]
        
        print("\n🏷️  Testing NAICS lookups:")
        naics_passed = 0
        for code, expected_substring in test_cases_naics:
            result = service.get_naics_name(code)
            passed = expected_substring in result or result == expected_substring
            status = "✅" if passed else "❌"
            print(f"   {status} Code '{code}': {result}")
            if passed:
                naics_passed += 1
        
        # Test PSC lookup
        test_cases_psc = [
            ("DD01", "Database"),
            ("9999", "Miscellaneous"),
            ("R425", "Engineering"),
            ("", ""),
            ("XXXX", "XXXX"),
        ]
        
        print("\n📦 Testing PSC lookups:")
        psc_passed = 0
        for code, expected_substring in test_cases_psc:
            result = service.get_psc_name(code)
            passed = expected_substring in result or result == expected_substring
            status = "✅" if passed else "❌"
            print(f"   {status} Code '{code}': {result}")
            if passed:
                psc_passed += 1
        
        total_tests = len(test_cases_naics) + len(test_cases_psc)
        total_passed = naics_passed + psc_passed
        
        print(f"\n📊 Test Summary: {total_passed}/{total_tests} tests passed")
        
        return total_passed == total_tests
        
    except Exception as e:
        print(f"\n❌ Error testing service: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    print("🧪 NAICS/PSC CODE COVERAGE TEST SUITE")
    print("="*80)
    
    # Load data
    print("\n📖 Loading data...")
    your_naics, your_psc = load_your_codes()
    naics_mapping, psc_mapping = load_mappings()
    
    print(f"✅ Found {len(your_naics)} unique NAICS codes in your data")
    print(f"✅ Found {len(your_psc)} unique PSC codes in your data")
    print(f"✅ Loaded {len(naics_mapping)} NAICS descriptions")
    print(f"✅ Loaded {len(psc_mapping)} PSC descriptions")
    
    # Run tests
    naics_ok = test_naics_coverage(your_naics, naics_mapping)
    psc_ok = test_psc_coverage(your_psc, psc_mapping)
    service_ok = test_code_lookup_service()
    
    # Summary
    print("\n" + "="*80)
    print("📊 FINAL SUMMARY")
    print("="*80)
    
    results = {
        "NAICS Coverage": naics_ok,
        "PSC Coverage": psc_ok,
        "Lookup Service": service_ok
    }
    
    for test, passed in results.items():
        status = "✅ PASS" if passed else "❌ FAIL"
        print(f"{status} - {test}")
    
    all_passed = all(results.values())
    
    if all_passed:
        print("\n🎉 All tests passed! Your code mappings are complete.")
    else:
        print("\n⚠️  Some tests failed. Check the output above for details.")
    
    sys.exit(0 if all_passed else 1)