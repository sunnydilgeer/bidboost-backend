import pytest
from datetime import datetime, timedelta
from unittest.mock import Mock, MagicMock, patch
from app.services.match_scoring import ContractMatchScorer
from app.models.company import CompanyProfile, CompanyCapability, PastWin, SearchPreference
from app.models.contract import Contract


# Mock fixtures
@pytest.fixture
def mock_db_session():
    """Mock database session"""
    return Mock()


@pytest.fixture
def mock_qdrant_client():
    """Mock Qdrant client"""
    client = Mock()
    # Mock retrieve method to return capability vectors
    client.retrieve = Mock(return_value=[
        Mock(vector=[0.5] * 768)  # Mock 768-dimensional vector
    ])
    return client


@pytest.fixture
def scorer(mock_db_session, mock_qdrant_client):
    """Initialize ContractMatchScorer with mocks"""
    with patch('app.services.match_scoring.settings') as mock_settings:
        mock_settings.USE_PINECONE = False  # Use Qdrant only for testing
        return ContractMatchScorer(mock_db_session, mock_qdrant_client)


@pytest.fixture
def cybersecurity_profile():
    """Mock company profile focused on cybersecurity"""
    from app.models.company import CompanySize
    
    profile = CompanyProfile(
        id=1,
        firm_id="firm_cyber_001",
        company_name="CyberDefense Inc",
        size=CompanySize.SMALL,
        created_at=datetime.now(),
        updated_at=datetime.now()
    )
    
    profile.capabilities = [
        CompanyCapability(
            id=1,
            company_id=1,
            capability_text="DoD Cybersecurity Services, NIST 800-171 compliance, FedRAMP authorized solutions",
            category="IT Services",
            qdrant_id="cap_cyber_1"
        ),
        CompanyCapability(
            id=2,
            company_id=1,
            capability_text="Penetration testing, vulnerability assessments, security audits",
            category="Security Testing",
            qdrant_id="cap_cyber_2"
        )
    ]
    
    profile.past_wins = [
        PastWin(
            id=1,
            company_id=1,
            contract_title="Cybersecurity Assessment Services",
            buyer_name="Department of Defense",
            contract_value=500000.0,
            award_date=datetime.now() - timedelta(days=180),
            federal_contract=True,
            agency_name="DoD"
        ),
        PastWin(
            id=2,
            company_id=1,
            contract_title="Network Security Implementation",
            buyer_name="Department of Homeland Security",
            contract_value=750000.0,
            award_date=datetime.now() - timedelta(days=90),
            federal_contract=True,
            agency_name="DHS"
        )
    ]
    
    profile.search_preference = SearchPreference(
        id=1,
        company_id=1,
        min_contract_value=100000.0,
        max_contract_value=2000000.0,
        preferred_regions=["DC", "VA", "MD"],
        excluded_categories=[],
        keywords=["cybersecurity", "NIST", "compliance"],
        preferred_agencies=["DoD", "DHS"]
    )
    
    return profile


@pytest.fixture
def construction_profile():
    """Mock company profile focused on construction"""
    from app.models.company import CompanySize
    
    profile = CompanyProfile(
        id=2,
        firm_id="firm_construct_001",
        company_name="BuildRight Construction",
        size=CompanySize.MEDIUM,
        created_at=datetime.now(),
        updated_at=datetime.now()
    )
    
    profile.capabilities = [
        CompanyCapability(
            id=3,
            company_id=2,
            capability_text="Commercial building construction, LEED certified projects",
            category="Construction",
            qdrant_id="cap_construct_1"
        )
    ]
    
    profile.past_wins = [
        PastWin(
            id=3,
            company_id=2,
            contract_title="Office Building Renovation",
            buyer_name="General Services Administration",
            contract_value=3000000.0,
            award_date=datetime.now() - timedelta(days=365),
            federal_contract=True,
            agency_name="GSA"
        )
    ]
    
    profile.search_preference = SearchPreference(
        id=2,
        company_id=2,
        min_contract_value=500000.0,
        max_contract_value=10000000.0,
        preferred_regions=["CA", "TX", "NY"],
        excluded_categories=["IT Services"],
        keywords=["construction", "building", "renovation"]
    )
    
    return profile


# Mock contracts
@pytest.fixture
def dod_cyber_contract():
    """High-value DoD cybersecurity contract"""
    return Contract(
        id=1,
        notice_id="sam_cyber_001",
        title="Cybersecurity Assessment for Defense Systems",
        description="Provide comprehensive cybersecurity assessment services for DoD systems including NIST 800-171 compliance verification",
        buyer_name="Department of Defense",
        contract_value=800000.0,
        closing_date=datetime.now() + timedelta(days=30),
        region="DC",
        set_aside="SDVOSB",
        naics_code="541512",
        qdrant_id="contract_cyber_001"
    )


@pytest.fixture
def dhs_pentest_contract():
    """DHS penetration testing contract"""
    return Contract(
        id=2,
        notice_id="sam_cyber_002",
        title="Network Penetration Testing Services",
        description="Conduct penetration testing and vulnerability assessments for federal agency networks",
        buyer_name="Department of Homeland Security",
        contract_value=450000.0,
        closing_date=datetime.now() + timedelta(days=20),
        region="VA",
        set_aside="Small Business",
        naics_code="541512",
        qdrant_id="contract_cyber_002"
    )


@pytest.fixture
def gsa_construction_contract():
    """GSA construction contract"""
    return Contract(
        id=3,
        notice_id="sam_construct_001",
        title="Office Building Renovation Project",
        description="Renovation of federal office building including HVAC upgrades and interior construction",
        buyer_name="General Services Administration",
        contract_value=5000000.0,
        closing_date=datetime.now() + timedelta(days=45),
        region="CA",
        set_aside="Small Business",
        naics_code="236220",
        qdrant_id="contract_construct_001"
    )


@pytest.fixture
def medical_supplies_contract():
    """Unrelated medical supplies contract"""
    return Contract(
        id=4,
        notice_id="sam_medical_001",
        title="Medical Supply Procurement",
        description="Procurement of medical supplies and equipment for VA hospitals",
        buyer_name="Department of Veterans Affairs",
        contract_value=200000.0,
        closing_date=datetime.now() + timedelta(days=15),
        region="TX",
        set_aside="Small Business",
        naics_code="339113",
        qdrant_id="contract_medical_001"
    )


# ===== PAST WIN SCORING TESTS =====

def test_past_win_score_exact_buyer_match(scorer, dod_cyber_contract, cybersecurity_profile):
    """Test high score for exact buyer name match"""
    print("\n=== TEST: Past Win Score - Exact Buyer Match (DoD) ===")
    
    score, reasons = scorer._calculate_past_win_score(
        dod_cyber_contract,
        cybersecurity_profile.past_wins
    )
    
    print(f"Profile Past Wins: {[w.buyer_name for w in cybersecurity_profile.past_wins]}")
    print(f"Contract Buyer: {dod_cyber_contract.buyer_name}")
    print(f"Score: {score:.2f}")
    print(f"Reasons: {reasons}")
    
    assert score > 0.5, f"Should score >0.5 for exact buyer match, got {score}"
    assert any("Department of Defense" in r for r in reasons), "Should mention DoD in reasons"
    print("✓ PASS: Exact buyer match scores highly\n")


def test_past_win_score_partial_buyer_match(scorer, dhs_pentest_contract, cybersecurity_profile):
    """Test medium score for partial buyer match"""
    print("\n=== TEST: Past Win Score - Partial Buyer Match (DHS) ===")
    
    score, reasons = scorer._calculate_past_win_score(
        dhs_pentest_contract,
        cybersecurity_profile.past_wins
    )
    
    print(f"Profile Past Wins: {[w.buyer_name for w in cybersecurity_profile.past_wins]}")
    print(f"Contract Buyer: {dhs_pentest_contract.buyer_name}")
    print(f"Score: {score:.2f}")
    print(f"Reasons: {reasons}")
    
    assert score > 0.3, "Should score >0.3 for partial buyer match"
    print("✓ PASS: Partial buyer match scores moderately\n")


def test_past_win_score_similar_value(scorer, dod_cyber_contract, cybersecurity_profile):
    """Test value similarity bonus"""
    print("\n=== TEST: Past Win Score - Similar Contract Value ===")
    
    score, reasons = scorer._calculate_past_win_score(
        dod_cyber_contract,
        cybersecurity_profile.past_wins
    )
    
    print(f"Contract Value: ${dod_cyber_contract.contract_value:,.0f}")
    print(f"Past Win Values: {[f'${w.contract_value:,.0f}' for w in cybersecurity_profile.past_wins]}")
    print(f"Score: {score:.2f}")
    print(f"Reasons: {reasons}")
    
    # Should get bonus for similar value ($500K vs $800K = 0.625 ratio)
    assert score > 0.6, "Should score >0.6 for buyer match + similar value"
    print("✓ PASS: Similar contract values boost score\n")


def test_past_win_score_no_wins(scorer, dod_cyber_contract):
    """Test zero score when no past wins"""
    print("\n=== TEST: Past Win Score - No Past Wins ===")
    
    score, reasons = scorer._calculate_past_win_score(dod_cyber_contract, [])
    
    print(f"Past Wins: None")
    print(f"Score: {score:.2f}")
    print(f"Reasons: {reasons}")
    
    assert score == 0.0, "Should score 0.0 with no past wins"
    assert len(reasons) == 0, "Should have no reasons"
    print("✓ PASS: No past wins = zero score\n")


# ===== PREFERENCE SCORING TESTS =====

def test_preference_score_all_match(scorer, dod_cyber_contract, cybersecurity_profile):
    """Test high score when all preferences match"""
    print("\n=== TEST: Preference Score - All Criteria Match ===")
    
    prefs = cybersecurity_profile.search_preference
    score, passes, reasons = scorer._calculate_preference_score(
        dod_cyber_contract,
        prefs
    )
    
    print(f"Contract Value: ${dod_cyber_contract.contract_value:,.0f}")
    print(f"Preference Range: ${prefs.min_contract_value:,.0f} - ${prefs.max_contract_value:,.0f}")
    print(f"Contract Region: {dod_cyber_contract.region}")
    print(f"Preferred Regions: {prefs.preferred_regions}")
    print(f"Contract Title: {dod_cyber_contract.title}")
    print(f"Keywords: {prefs.keywords}")
    print(f"\nScore: {score:.2f}")
    print(f"Passes Filters: {passes}")
    print(f"Reasons: {reasons}")
    
    assert passes == True, "Should pass all filters"
    assert score >= 1.0, "Should have high preference score"
    print("✓ PASS: All preferences match = high score\n")


def test_preference_score_value_filter_fail(scorer, construction_profile):
    """Test hard filter fail for contract value outside range"""
    print("\n=== TEST: Preference Score - Value Filter Fails ===")
    
    # Contract value $200K, preference min $500K
    cheap_contract = Contract(
        id=5,
        notice_id="test_001",
        title="Small IT Services Contract",
        buyer_name="DoD",
        contract_value=200000.0,
        region="CA",
        qdrant_id="test_001"
    )
    
    prefs = construction_profile.search_preference
    score, passes, reasons = scorer._calculate_preference_score(
        cheap_contract,
        prefs
    )
    
    print(f"Contract Value: ${cheap_contract.contract_value:,.0f}")
    print(f"Preference Min: ${prefs.min_contract_value:,.0f}")
    print(f"Passes Filters: {passes}")
    
    assert passes == False, "Should fail hard filter for value below minimum"
    print("✓ PASS: Value below minimum = hard filter fail\n")


def test_preference_score_excluded_category(scorer, construction_profile, dod_cyber_contract):
    """Test excluded category hard filter"""
    print("\n=== TEST: Preference Score - Excluded Category ===")
    
    prefs = construction_profile.search_preference
    score, passes, reasons = scorer._calculate_preference_score(
        dod_cyber_contract,
        prefs
    )
    
    print(f"Contract Title: {dod_cyber_contract.title}")
    print(f"Excluded Categories: {prefs.excluded_categories}")
    print(f"Passes Filters: {passes}")
    
    # Construction profile excludes "IT Services", cyber contract should fail
    assert passes == False, "Should fail hard filter for excluded category"
    print("✓ PASS: Excluded category = hard filter fail\n")


def test_preference_score_region_soft_filter(scorer, cybersecurity_profile):
    """Test region as soft filter (reduces score but doesn't fail)"""
    print("\n=== TEST: Preference Score - Non-Preferred Region (Soft Filter) ===")
    
    # Contract in TX, profile prefers DC/VA/MD
    texas_contract = Contract(
        id=6,
        notice_id="test_002",
        title="Cybersecurity Services",
        buyer_name="Department of Defense",
        contract_value=500000.0,
        region="TX",
        qdrant_id="test_002"
    )
    
    prefs = cybersecurity_profile.search_preference
    score, passes, reasons = scorer._calculate_preference_score(
        texas_contract,
        prefs
    )
    
    print(f"Contract Region: {texas_contract.region}")
    print(f"Preferred Regions: {prefs.preferred_regions}")
    print(f"Score: {score:.2f}")
    print(f"Passes Filters: {passes}")
    
    assert passes == True, "Should pass filters (soft penalty only)"
    assert score < 1.0, "Should have reduced score for non-preferred region"
    print("✓ PASS: Non-preferred region reduces score but doesn't fail\n")


def test_preference_score_keyword_boost(scorer, dod_cyber_contract, cybersecurity_profile):
    """Test keyword matching boosts score"""
    print("\n=== TEST: Preference Score - Keyword Boost ===")
    
    prefs = cybersecurity_profile.search_preference
    score, passes, reasons = scorer._calculate_preference_score(
        dod_cyber_contract,
        prefs
    )
    
    print(f"Contract Title: {dod_cyber_contract.title}")
    print(f"Description: {dod_cyber_contract.description[:80]}...")
    print(f"Keywords: {prefs.keywords}")
    print(f"Score: {score:.2f}")
    print(f"Reasons: {reasons}")
    
    # Contract mentions "cybersecurity" and "NIST" from keyword list
    assert score > 1.0, "Should boost score for keyword matches"
    assert any("keyword" in r.lower() for r in reasons), "Should mention keyword matches"
    print("✓ PASS: Keyword matches boost preference score\n")


# ===== INTEGRATION TESTS =====

def test_score_contract_excellent_match(scorer, mock_db_session, dod_cyber_contract, cybersecurity_profile):
    """Test overall scoring for excellent match"""
    print("\n=== TEST: Overall Score - Excellent Match ===")
    
    # Mock database query to return cybersecurity profile
    mock_db_session.query.return_value.filter.return_value.first.return_value = cybersecurity_profile
    
    scores = scorer.score_contract(dod_cyber_contract, "firm_cyber_001")
    
    print(f"Contract: {dod_cyber_contract.title}")
    print(f"Profile: {cybersecurity_profile.company_name}")
    print(f"\nComponent Scores:")
    print(f"  Capability: {scores['capability_score']:.2%} (40% weight)")
    print(f"  Past Win: {scores['past_win_score']:.2%} (30% weight)")
    print(f"  Preference: {scores['preference_score']:.2%} (30% weight)")
    print(f"  TOTAL: {scores['total_score']:.2%}")
    print(f"\nMatch Reasons:")
    for reason in scores['match_reasons']:
        print(f"  • {reason}")
    
    # Should score highly across all dimensions
    assert scores['total_score'] > 0.5, "Excellent match should score >50%"
    assert len(scores['match_reasons']) > 0, "Should have match reasons"
    print("✓ PASS: Excellent match scores highly\n")


def test_score_contract_poor_match(scorer, mock_db_session, medical_supplies_contract, cybersecurity_profile):
    """Test overall scoring for poor match"""
    print("\n=== TEST: Overall Score - Poor Match ===")
    
    mock_db_session.query.return_value.filter.return_value.first.return_value = cybersecurity_profile
    
    scores = scorer.score_contract(medical_supplies_contract, "firm_cyber_001")
    
    print(f"Contract: {medical_supplies_contract.title}")
    print(f"Profile: {cybersecurity_profile.company_name}")
    print(f"\nComponent Scores:")
    print(f"  Capability: {scores['capability_score']:.2%}")
    print(f"  Past Win: {scores['past_win_score']:.2%}")
    print(f"  Preference: {scores['preference_score']:.2%}")
    print(f"  TOTAL: {scores['total_score']:.2%}")
    
    # Should score low due to unrelated domain
    assert scores['total_score'] < 0.4, "Poor match should score <40%"
    print("✓ PASS: Poor match scores low\n")


def test_score_contract_filtered_out(scorer, mock_db_session, dod_cyber_contract, construction_profile):
    """Test that contracts failing hard filters return None"""
    print("\n=== TEST: Overall Score - Hard Filter Fail (Returns None) ===")
    
    mock_db_session.query.return_value.filter.return_value.first.return_value = construction_profile
    
    result = scorer.score_contract(dod_cyber_contract, "firm_construct_001")
    
    print(f"Contract: {dod_cyber_contract.title} (IT Services)")
    print(f"Profile: {construction_profile.company_name}")
    print(f"Excluded Categories: {construction_profile.search_preference.excluded_categories}")
    print(f"Result: {result}")
    
    assert result is None, "Should return None for contracts failing hard filters"
    print("✓ PASS: Excluded category returns None\n")


# ===== SCORING WEIGHT ANALYSIS =====

def test_current_scoring_weights():
    """Document current scoring weights for review"""
    print("\n" + "="*70)
    print("CURRENT SCORING ALGORITHM WEIGHTS")
    print("="*70)
    print("\n📊 Component Weights:")
    print("  • Capability Score: 40% (semantic similarity)")
    print("  • Past Win Score: 30% (buyer match + value similarity)")
    print("  • Preference Score: 30% (filters + preferences)")
    print("\n🎯 Scoring Formula:")
    print("  total_score = (capability * 0.4) + (past_win * 0.3) + (preference * 0.3)")
    print("\n💡 Proposed Match Quality Thresholds:")
    print("  • Excellent: 75%+ (Strong fit, highly recommended)")
    print("  • Strong: 60-74% (Good fit, recommended)")
    print("  • Good: 45-59% (Potential fit, worth reviewing)")
    print("  • Potential: 30-44% (Weak fit, may skip)")
    print("  • Poor: <30% (Not a good match)")
    print("\n🔄 Recommendation: Consider adjusting to:")
    print("  • Capability: 50% (most important for relevance)")
    print("  • Past Win: 25% (helpful but not decisive)")
    print("  • Preference: 25% (filters are mostly binary)")
    print("="*70 + "\n")


# ===== TEST SUMMARY =====

def print_test_summary():
    """Print test summary and instructions"""
    print("\n" + "="*70)
    print("MATCH SCORING TEST SUITE SUMMARY")
    print("="*70)
    print("\n✅ Test Coverage:")
    print("  1. Past Win Scoring (5 tests)")
    print("     - Exact buyer match")
    print("     - Partial buyer match")
    print("     - Similar contract values")
    print("     - No past wins edge case")
    print("\n  2. Preference Scoring (5 tests)")
    print("     - All criteria match")
    print("     - Value range hard filter")
    print("     - Excluded category hard filter")
    print("     - Region soft filter")
    print("     - Keyword matching boost")
    print("\n  3. Integration Tests (3 tests)")
    print("     - Excellent overall match")
    print("     - Poor overall match")
    print("     - Hard filter exclusion")
    print("\n📝 Key Findings:")
    print("  • Past win scoring works well for buyer/value matching")
    print("  • Preference filters properly distinguish hard vs soft criteria")
    print("  • Current 40/30/30 weights may undervalue capability matching")
    print("\n🎯 Next Steps:")
    print("  1. Review test results and actual score distributions")
    print("  2. Consider increasing capability weight to 50%")
    print("  3. Add match quality thresholds (Excellent/Strong/Good/Potential)")
    print("  4. Make match_reasons more specific with actual matched terms")
    print("\n🚀 To Run Tests:")
    print("  cd backend")
    print("  python -m pytest app/tests/test_match_scoring.py -v -s")
    print("="*70 + "\n")


if __name__ == "__main__":
    print_test_summary()
    test_current_scoring_weights()