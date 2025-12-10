#!/usr/bin/env python3
"""
Data Migration: Embed existing past wins in Pinecone
Run this AFTER the schema migration (pinecone_id column exists)
"""

import asyncio
import os
import sys
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

# Add parent directory to path so we can import app modules
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.models.company import PastWin
from app.services.past_win_store_pinecone import get_past_win_store
from app.services.llm import LLMService

async def migrate_past_wins():
    """Embed all existing past wins that don't have pinecone_id"""
    
    database_url = os.getenv("DATABASE_URL")
    
    if not database_url:
        print("❌ ERROR: DATABASE_URL not found")
        print("Run: railway run python migrate_existing_past_wins.py")
        sys.exit(1)
    
    print("=" * 60)
    print("🚀 EMBEDDING PAST WINS IN PINECONE")
    print("=" * 60)
    
    # Connect to database
    engine = create_engine(database_url)
    SessionLocal = sessionmaker(bind=engine)
    db = SessionLocal()
    
    try:
        # Get all past wins without pinecone_id
        past_wins = db.query(PastWin).filter(
            PastWin.pinecone_id == None
        ).all()
        
        if not past_wins:
            print("✅ All past wins already have pinecone_id")
            print("Nothing to migrate!")
            return
        
        print(f"\n📋 Found {len(past_wins)} past wins to embed:\n")
        
        for win in past_wins:
            print(f"  • ID {win.id}: {win.contract_title[:50]}...")
        
        # Initialize services
        llm_service = LLMService()
        win_store = get_past_win_store()
        
        print(f"\n🔄 Starting embedding process...\n")
        
        migrated = 0
        errors = []
        
        for win in past_wins:
            try:
                print(f"  → Embedding past win {win.id}...")
                
                # Generate embedding and store in Pinecone
                pinecone_id = await win_store.add_past_win(win, llm_service)
                
                # Update database
                win.pinecone_id = pinecone_id
                db.flush()
                
                print(f"    ✅ Success! Pinecone ID: {pinecone_id[:20]}...")
                migrated += 1
                
            except Exception as e:
                error_msg = f"Failed to embed past win {win.id}: {str(e)}"
                print(f"    ❌ {error_msg}")
                errors.append(error_msg)
        
        # Commit all changes
        db.commit()
        
        print("\n" + "=" * 60)
        print(f"✅ MIGRATION COMPLETE!")
        print(f"   Embedded: {migrated}/{len(past_wins)} past wins")
        
        if errors:
            print(f"\n⚠️  Errors encountered:")
            for error in errors:
                print(f"   - {error}")
        
        print("=" * 60)
        
    except Exception as e:
        print(f"\n❌ Migration failed: {str(e)}")
        db.rollback()
        sys.exit(1)
    
    finally:
        db.close()

if __name__ == "__main__":
    asyncio.run(migrate_past_wins())