"""
Add missing metadata fields to opportunity_chains table
Run ONCE before migration
"""

from app.database import SessionLocal, engine
from sqlalchemy import text

def add_metadata_columns():
    """Add missing metadata columns to opportunity_chains"""
    
    db = SessionLocal()
    
    try:
        print("=" * 70)
        print("ADDING METADATA COLUMNS TO OPPORTUNITY_CHAINS")
        print("=" * 70)
        
        # Check if columns already exist
        check_query = text("""
            SELECT column_name 
            FROM information_schema.columns 
            WHERE table_name = 'opportunity_chains';
        """)
        
        existing_columns = {row[0] for row in db.execute(check_query)}
        print(f"Existing columns: {len(existing_columns)}")
        
        # Define new columns to add
        new_columns = [
            ("base_agency", "VARCHAR(255)"),
            ("base_office", "TEXT"),
            ("base_naics", "VARCHAR(10)"),
            ("base_psc", "VARCHAR(10)"),
            ("base_set_aside", "VARCHAR(100)"),
            ("base_state", "VARCHAR(50)"),
            ("base_city", "VARCHAR(100)"),
            ("base_contact_name", "VARCHAR(200)"),
            ("base_contact_email", "VARCHAR(200)"),
            ("base_contact_phone", "VARCHAR(50)"),
        ]
        
        added_count = 0
        
        for col_name, col_type in new_columns:
            if col_name not in existing_columns:
                print(f"Adding column: {col_name} ({col_type})")
                
                alter_sql = text(f"""
                    ALTER TABLE opportunity_chains 
                    ADD COLUMN {col_name} {col_type};
                """)
                
                db.execute(alter_sql)
                db.commit()
                added_count += 1
            else:
                print(f"✓ Column already exists: {col_name}")
        
        print()
        print("=" * 70)
        print("MIGRATION COMPLETE")
        print("=" * 70)
        print(f"Added {added_count} new columns")
        print()
        
    except Exception as e:
        print(f"❌ Migration failed: {e}")
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    add_metadata_columns()