# migrate_onboarding.py
from app.database import engine
from sqlalchemy import text

def run_migration():
    """Add onboarding fields to company_profiles table"""
    
    migration_sql = """
    -- Add the three onboarding columns
    ALTER TABLE company_profiles 
    ADD COLUMN IF NOT EXISTS onboarding_completed INTEGER DEFAULT 0 NOT NULL,
    ADD COLUMN IF NOT EXISTS onboarding_step INTEGER DEFAULT 0 NOT NULL,
    ADD COLUMN IF NOT EXISTS onboarding_completed_at TIMESTAMP WITH TIME ZONE NULL;
    
    -- Set existing companies to "completed" status
    UPDATE company_profiles 
    SET onboarding_completed = 2, 
        onboarding_step = 4,
        onboarding_completed_at = created_at
    WHERE onboarding_completed = 0;
    """
    
    try:
        with engine.connect() as connection:
            # Execute the migration
            connection.execute(text(migration_sql))
            connection.commit()
            print("✅ Migration completed successfully!")
            
            # Verify it worked
            result = connection.execute(text(
                "SELECT id, company_name, onboarding_completed, onboarding_step "
                "FROM company_profiles LIMIT 5"
            ))
            
            print("\n📊 Current company_profiles data:")
            for row in result:
                print(f"  - {row.company_name}: onboarding_completed={row.onboarding_completed}, step={row.onboarding_step}")
                
    except Exception as e:
        print(f"❌ Migration failed: {e}")
        raise

if __name__ == "__main__":
    print("🔄 Starting migration...")
    print("📍 Database: postgresql://legal_rag_user@localhost:5432/legal_rag_db\n")
    run_migration()