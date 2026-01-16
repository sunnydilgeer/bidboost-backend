from sqlalchemy.orm import Session
from app.database import SessionLocal
from app.models.company import CompanyProfile
from app.services.capability_store_pinecone import get_capability_store

def verify_restoration():
    """Verify capabilities in PostgreSQL and Pinecone match"""
    db: Session = SessionLocal()
    capability_store = get_capability_store()
    
    try:
        print("=" * 70)
        print("🔍 VERIFYING CAPABILITY RESTORATION")
        print("=" * 70)
        
        companies = db.query(CompanyProfile).all()
        
        total_caps_db = 0
        total_caps_with_vector_id = 0
        missing_in_pinecone = []
        companies_checked = 0
        
        for company in companies:
            caps = company.capabilities
            if not caps:
                continue
                
            companies_checked += 1
            total_caps_db += len(caps)
            
            print(f"\n🏢 {company.company_name}:")
            print(f"   Capabilities in DB: {len(caps)}")
            
            caps_with_ids = 0
            caps_verified_in_pinecone = 0
            
            for cap in caps:
                if cap.qdrant_id:
                    total_caps_with_vector_id += 1
                    caps_with_ids += 1
                    
                    # Check if vector exists in Pinecone
                    vector_data = capability_store.get_capability(cap.qdrant_id)
                    if vector_data:
                        caps_verified_in_pinecone += 1
                    else:
                        missing_in_pinecone.append({
                            "company": company.company_name,
                            "capability": cap.capability_text[:50],
                            "vector_id": cap.qdrant_id
                        })
            
            print(f"   Capabilities with vector IDs: {caps_with_ids}")
            print(f"   Verified in Pinecone: {caps_verified_in_pinecone}")
            
            if caps_with_ids == len(caps) and caps_verified_in_pinecone == len(caps):
                print(f"   ✅ All capabilities verified!")
            elif caps_verified_in_pinecone > 0:
                print(f"   ⚠️  Partial verification ({caps_verified_in_pinecone}/{len(caps)})")
            else:
                print(f"   ❌ No capabilities verified")
        
        # Pinecone namespace stats
        stats = capability_store.get_namespace_stats()
        
        print("\n" + "=" * 70)
        print("📊 SUMMARY")
        print("=" * 70)
        print(f"\n🏢 Companies:")
        print(f"   Total in database: {len(companies)}")
        print(f"   With capabilities: {companies_checked}")
        
        print(f"\n📊 Capabilities in PostgreSQL:")
        print(f"   Total capabilities: {total_caps_db}")
        print(f"   With vector IDs: {total_caps_with_vector_id}")
        print(f"   Missing vector IDs: {total_caps_db - total_caps_with_vector_id}")
        
        print(f"\n📈 Pinecone 'capabilities' Namespace:")
        print(f"   Total vectors: {stats['total_capabilities']}")
        
        if missing_in_pinecone:
            print(f"\n❌ Found {len(missing_in_pinecone)} capabilities with IDs but missing from Pinecone:")
            for item in missing_in_pinecone[:10]:  # Show first 10
                print(f"   - {item['company']}: {item['capability']}... (ID: {item['vector_id'][:8]}...)")
            if len(missing_in_pinecone) > 10:
                print(f"   ... and {len(missing_in_pinecone) - 10} more")
        else:
            print("\n✅ All capabilities with vector IDs exist in Pinecone!")
        
        # Final verdict
        print("\n" + "=" * 70)
        if total_caps_with_vector_id == total_caps_db and not missing_in_pinecone and total_caps_db > 0:
            print("✅ VERIFICATION PASSED - All capabilities successfully restored!")
            print("\n🎯 Next Steps:")
            print("   1. Rebuild match cache: python -c \"from app.services.match_cache_service import MatchCacheService; MatchCacheService().run_cache_update()\"")
            print("   2. Test dashboard: curl http://localhost:8000/api/contracts/recommended?firm_id=YOUR_FIRM_ID")
            print("   3. Deploy to production")
        elif total_caps_db == 0:
            print("⚠️  NO CAPABILITIES IN DATABASE - Nothing to verify")
            print("   This is expected if you haven't created any companies yet")
        else:
            print("⚠️  VERIFICATION INCOMPLETE - See issues above")
            print("   Some capabilities may not have been restored properly")
        print("=" * 70)
        
    except Exception as e:
        print(f"\n❌ VERIFICATION ERROR: {e}")
        import traceback
        traceback.print_exc()
        
    finally:
        db.close()


if __name__ == "__main__":
    verify_restoration()