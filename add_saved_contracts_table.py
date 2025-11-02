"""
Migration: Add saved_contracts table
Run with: python add_saved_contracts_table.py
"""

import sys
from sqlalchemy import create_engine, text
from app.core.config import settings

def run_migration():
    """Add saved_contracts table to database"""
    
    engine = create_engine(settings.DATABASE_URL)
    
    print("🔄 Starting migration: Add saved_contracts table...")
    
    with engine.connect() as conn:
        try:
            # Create enum type for contract status
            print("Creating contractstatus enum...")
            conn.execute(text("""
                DO $$ BEGIN
                    CREATE TYPE contractstatus AS ENUM ('interested', 'bidding', 'won', 'lost');
                EXCEPTION
                    WHEN duplicate_object THEN null;
                END $$;
            """))
            conn.commit()
            
            # Create saved_contracts table
            print("Creating saved_contracts table...")
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS saved_contracts (
                    id SERIAL PRIMARY KEY,
                    user_email VARCHAR(255) NOT NULL,
                    firm_id VARCHAR(255) NOT NULL,
                    notice_id VARCHAR(255) NOT NULL,
                    contract_title VARCHAR(500) NOT NULL,
                    buyer_name VARCHAR(255) NOT NULL,
                    contract_value NUMERIC(15, 2),
                    deadline TIMESTAMP WITH TIME ZONE,
                    status contractstatus DEFAULT 'interested' NOT NULL,
                    notes TEXT,
                    saved_at TIMESTAMP WITH TIME ZONE DEFAULT NOW() NOT NULL,
                    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW() NOT NULL
                );
            """))
            conn.commit()
            
            # Create indexes
            print("Creating indexes...")
            conn.execute(text("""
                CREATE INDEX IF NOT EXISTS idx_saved_contracts_user_email 
                ON saved_contracts(user_email);
            """))
            
            conn.execute(text("""
                CREATE INDEX IF NOT EXISTS idx_saved_contracts_firm_id 
                ON saved_contracts(firm_id);
            """))
            
            conn.execute(text("""
                CREATE INDEX IF NOT EXISTS idx_saved_contracts_notice_id 
                ON saved_contracts(notice_id);
            """))
            
            conn.execute(text("""
                CREATE UNIQUE INDEX IF NOT EXISTS idx_user_contract 
                ON saved_contracts(user_email, notice_id);
            """))
            
            conn.commit()
            
            print("✅ Migration completed successfully!")
            print("\nTable created: saved_contracts")
            print("Indexes created: 4")
            print("Enum type created: contractstatus")
            
        except Exception as e:
            print(f"❌ Migration failed: {str(e)}")
            conn.rollback()
            sys.exit(1)

if __name__ == "__main__":
    run_migration()