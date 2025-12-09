#!/usr/bin/env python3
"""
Migration script: Add pinecone_id to past_wins table
Run this locally to migrate your Railway PostgreSQL database
"""

import os
import sys
import psycopg2
from psycopg2 import sql

def run_migration():
    """Run the migration to add pinecone_id column"""
    
    # Get DATABASE_URL from environment (Railway provides this)
    database_url = os.getenv("DATABASE_URL")
    
    if not database_url:
        print("❌ ERROR: DATABASE_URL not found in environment variables")
        print("\nTo fix this:")
        print("1. Go to Railway dashboard → Your PostgreSQL service")
        print("2. Click 'Variables' tab")
        print("3. Copy the DATABASE_URL value")
        print("4. Run: export DATABASE_URL='postgresql://...'")
        print("5. Then run this script again")
        sys.exit(1)
    
    print("🔗 Connecting to Railway PostgreSQL...")
    
    try:
        # Connect to database
        conn = psycopg2.connect(database_url)
        cursor = conn.cursor()
        
        print("✅ Connected successfully!")
        
        # Check if column already exists
        cursor.execute("""
            SELECT column_name 
            FROM information_schema.columns 
            WHERE table_name = 'past_wins' 
            AND column_name = 'pinecone_id';
        """)
        
        if cursor.fetchone():
            print("⚠️  Column 'pinecone_id' already exists in past_wins table")
            print("✅ Migration already completed - nothing to do!")
            cursor.close()
            conn.close()
            return
        
        print("\n📝 Running migration...")
        
        # Step 1: Add column
        print("  → Adding pinecone_id column...")
        cursor.execute("""
            ALTER TABLE past_wins 
            ADD COLUMN pinecone_id VARCHAR(100);
        """)
        conn.commit()
        print("  ✅ Column added")
        
        # Step 2: Add index
        print("  → Creating index...")
        cursor.execute("""
            CREATE INDEX idx_past_wins_pinecone_id 
            ON past_wins(pinecone_id);
        """)
        conn.commit()
        print("  ✅ Index created")
        
        # Verify
        cursor.execute("""
            SELECT column_name, data_type, is_nullable 
            FROM information_schema.columns 
            WHERE table_name = 'past_wins' 
            AND column_name = 'pinecone_id';
        """)
        
        result = cursor.fetchone()
        if result:
            print("\n✅ Migration completed successfully!")
            print(f"   Column: {result[0]}")
            print(f"   Type: {result[1]}")
            print(f"   Nullable: {result[2]}")
        
        cursor.close()
        conn.close()
        
    except psycopg2.Error as e:
        print(f"\n❌ Database error: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ Error: {e}")
        sys.exit(1)

if __name__ == "__main__":
    print("=" * 60)
    print("🚀 DATABASE MIGRATION: Add pinecone_id to past_wins")
    print("=" * 60)
    run_migration()
    print("=" * 60)
    print("🎉 Done! You can now proceed to Step 3")
    print("=" * 60)