"""
One-time migration script: Move capabilities from Qdrant to Pinecone
Run this ONCE after deploying the new code
"""
import asyncio
import sys
import os

# Add parent directory to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from sqlalchemy.orm import Session
from app.database import SessionLocal
from app.models.company import CompanyCapability
from app.services.capability_store_pinecone import CapabilityStorePinecone
from app.services.llm import LLMService
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def migrate():
    """Migrate all capabilities from Qdrant to Pinecone"""
    db = SessionLocal()
    
    try:
        store = CapabilityStorePinecone()
        llm = LLMService()
        
        # Get all capabilities
        capabilities = db.query(CompanyCapability).all()
        
        print(f"\n{'='*60}")
        print(f"🚀 CAPABILITY MIGRATION: Qdrant → Pinecone")
        print(f"{'='*60}")
        print(f"Found {len(capabilities)} capabilities to migrate\n")
        
        if len(capabilities) == 0:
            print("⚠️  No capabilities found in database")
            return
        
        migrated_count = 0
        failed_count = 0
        
        for i, cap in enumerate(capabilities, 1):
            try:
                print(f"[{i}/{len(capabilities)}] Migrating: {cap.capability_text[:60]}...")
                
                # Add to Pinecone
                pinecone_id = await store.add_capability(cap, llm)
                
                # Update DB with new Pinecone ID
                cap.qdrant_id = pinecone_id  # Reusing same field
                db.commit()
                
                print(f"    ✅ Success! Pinecone ID: {pinecone_id[:8]}...")
                migrated_count += 1
            
            except Exception as e:
                print(f"    ❌ Failed: {str(e)}")
                db.rollback()
                failed_count += 1
                continue
        
        print(f"\n{'='*60}")
        print(f"📊 MIGRATION SUMMARY")
        print(f"{'='*60}")
        print(f"✅ Migrated: {migrated_count}")
        print(f"❌ Failed: {failed_count}")
        print(f"{'='*60}\n")
        
        if migrated_count > 0:
            # Verify in Pinecone
            stats = store.get_namespace_stats()
            print(f"✅ Pinecone capabilities namespace: {stats['total_capabilities']} vectors")
            print(f"\n🎉 Migration complete! You can now:")
            print(f"   1. Test login (should be instant)")
            print(f"   2. Delete Qdrant service from Railway")
        
    except Exception as e:
        logger.error(f"Migration failed: {e}", exc_info=True)
        print(f"\n❌ Migration failed: {str(e)}")
    
    finally:
        db.close()

if __name__ == "__main__":
    print("\n⚠️  This will migrate capabilities from Qdrant to Pinecone")
    print("⚠️  Make sure new code is deployed first!\n")
    
    response = input("Continue? (yes/no): ")
    
    if response.lower() == "yes":
        asyncio.run(migrate())
    else:
        print("Migration cancelled")