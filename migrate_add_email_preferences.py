"""
Database Migration Script: Add Email Notification Preferences to Users Table

Run this script ONCE to add the new columns to your existing users table:
    python migrate_add_email_preferences.py

This script:
1. Connects to your PostgreSQL database
2. Adds 3 new columns to the users table
3. Sets default values for existing users (notifications ON, daily frequency)
"""

import os
from sqlalchemy import create_engine, text
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://legal_rag_user:secure_password@localhost:5432/legal_rag_db"
)

def migrate_add_email_preferences():
    """Add email notification preference columns to users table"""
    
    engine = create_engine(DATABASE_URL)
    
    migrations = [
        # 1. Add email_notifications_enabled column (default TRUE for existing users)
        """
        ALTER TABLE users 
        ADD COLUMN IF NOT EXISTS email_notifications_enabled BOOLEAN NOT NULL DEFAULT TRUE;
        """,
        
        # 2. Add notification_frequency column (default 'daily')
        """
        ALTER TABLE users 
        ADD COLUMN IF NOT EXISTS notification_frequency VARCHAR(20) NOT NULL DEFAULT 'daily';
        """,
        
        # 3. Add last_email_sent_at column (nullable, starts as NULL)
        """
        ALTER TABLE users 
        ADD COLUMN IF NOT EXISTS last_email_sent_at TIMESTAMP;
        """,
    ]
    
    try:
        with engine.connect() as conn:
            print("🔗 Connected to database")
            
            for i, migration_sql in enumerate(migrations, 1):
                print(f"🔧 Running migration {i}/3...")
                conn.execute(text(migration_sql))
                conn.commit()
                print(f"✅ Migration {i}/3 completed")
            
            print("\n🎉 All migrations completed successfully!")
            print("\n📊 Verifying columns were added...")
            
            # Verify the columns exist
            result = conn.execute(text("""
                SELECT column_name, data_type, is_nullable, column_default
                FROM information_schema.columns
                WHERE table_name = 'users'
                AND column_name IN ('email_notifications_enabled', 'notification_frequency', 'last_email_sent_at')
                ORDER BY column_name;
            """))
            
            print("\n✅ New columns in 'users' table:")
            for row in result:
                print(f"   - {row.column_name}: {row.data_type} (nullable: {row.is_nullable}, default: {row.column_default})")
            
            # Count existing users
            count_result = conn.execute(text("SELECT COUNT(*) FROM users"))
            user_count = count_result.scalar()
            print(f"\n👥 Updated {user_count} existing user(s) with default email preferences")
            
    except Exception as e:
        print(f"❌ Migration failed: {e}")
        raise
    finally:
        engine.dispose()

if __name__ == "__main__":
    print("=" * 60)
    print("DATABASE MIGRATION: Add Email Notification Preferences")
    print("=" * 60)
    print()
    
    migrate_add_email_preferences()
    
    print("\n" + "=" * 60)
    print("✅ MIGRATION COMPLETE")
    print("=" * 60)
    print("\nNext steps:")
    print("1. Restart your FastAPI server")
    print("2. Test the new email preference endpoints:")
    print("   GET  /api/user/email-preferences")
    print("   PUT  /api/user/email-preferences")
    print("3. Trigger a test email job:")
    print("   POST /api/user/test-email")