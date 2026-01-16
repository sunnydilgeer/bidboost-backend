"""
Restore all company capabilities to Pinecone after namespace deletion.
Re-embeds all capabilities and updates qdrant_id in PostgreSQL.

USAGE:
    python restore_capabilities.py

REQUIREMENTS:
    - Run from your backend directory: /Users/sunnyd/legal-rag-backend/
    - Ensure .env file has OPENAI_API_KEY and PINECONE_API_KEY
    - PostgreSQL database must be running and accessible
"""
import asyncio
import sys
from sqlalchemy.orm import Session
from app.database import SessionLocal
from app.models.company import CompanyProfile, CompanyCapability
from app.services.capability_store_pinecone import get_capability_store
from app.services.llm import get_llm_service

async def restore_capabilities():
    """Restore all capabilities to Pinecone"""
    db: Session = SessionLocal()
    capability_store = get_capability_store()
    llm_service = get_llm_service()
    
    try:
        print("=" * 70)
        print("🔄 RESTORING CAPABILITY VECTORS TO PINECONE")
        print("=" * 70)
        
        # Get all companies
        companies = db.query(CompanyProfile).all()
        print(f"📊 Found {len(companies)} companies in database\n")
        
        if not companies:
            print("⚠️  No companies found. Nothing to restore.")
            return
        
        total_capabilities = 0
        total_restored = 0
        companies_with_no_caps = []
        
        # Process each company
        for idx, company in enumerate(companies, 1):
            capabilities = company.capabilities
            
            if not capabilities:
                companies_with_no_caps.append(company.company_name)
                print(f"⏭️  [{idx}/{len(companies)}] {company.company_name}: No capabilities (skipping)")
                continue
            
            print(f"\n{'─' * 70}")
            print(f"🏢 [{idx}/{len(companies)}] {company.company_name} ({company.firm_id})")
            print(f"   Capabilities to restore: {len(capabilities)}")
            
            total_capabilities += len(capabilities)
            
            try:
                # Batch re-embed and store in Pinecone (7× faster!)
                print(f"   🔄 Re-embedding {len(capabilities)} capabilities...")
                vector_ids = await capability_store.add_capabilities_batch(
                    capabilities=capabilities,
                    llm_service=llm_service
                )
                
                # Update PostgreSQL with new Pinecone vector IDs
                for capability, vector_id in zip(capabilities, vector_ids):
                    capability.qdrant_id = vector_id
                    print(f"   ✅ {capability.capability_text[:60]}... → {vector_id[:8]}...")
                
                db.commit()
                total_restored += len(capabilities)
                print(f"   💾 Saved {len(capabilities)} vector IDs to database")
                
            except Exception as e:
                print(f"   ❌ Failed to restore capabilities for {company.company_name}: {e}")
                import traceback
                traceback.print_exc()
                db.rollback()
                continue
        
        # Final summary
        print("\n" + "=" * 70)
        print("📊 RESTORATION COMPLETE")
        print("=" * 70)
        print(f"✅ Total capabilities restored: {total_restored}/{total_capabilities}")
        print(f"🏢 Companies processed: {len(companies)}")
        
        if companies_with_no_caps:
            print(f"\n⚠️  Companies with no capabilities ({len(companies_with_no_caps)}):")
            for name in companies_with_no_caps:
                print(f"   - {name}")
        
        # Show Pinecone stats
        print("\n📈 Pinecone Namespace Stats:")
        stats = capability_store.get_namespace_stats()
        print(f"   Total vectors in 'capabilities' namespace: {stats['total_capabilities']}")
        
        if total_restored == total_capabilities and total_restored > 0:
            print("\n✅ ALL CAPABILITIES SUCCESSFULLY RESTORED!")
            print("   Next step: Run verify_capabilities.py to confirm")
        elif total_restored > 0:
            print(f"\n⚠️  PARTIAL RESTORATION: {total_restored}/{total_capabilities} restored")
            print("   Check errors above for failed companies")
        else:
            print("\n❌ NO CAPABILITIES RESTORED - Check errors above")
        
    except Exception as e:
        print(f"\n❌ CRITICAL ERROR: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
    
    finally:
        db.close()


if __name__ == "__main__":
    print("Starting capability restoration...\n")
    asyncio.run(restore_capabilities())
    print("\n✨ Done! Run verify_capabilities.py next.")