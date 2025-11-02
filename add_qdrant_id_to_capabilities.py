from sqlalchemy import text
from app.database import engine
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def add_qdrant_id_column():
    """Add qdrant_id column to company_capabilities table"""
    
    with engine.connect() as conn:
        try:
            # Check if column already exists
            result = conn.execute(text("""
                SELECT column_name 
                FROM information_schema.columns 
                WHERE table_name='company_capabilities' 
                AND column_name='qdrant_id'
            """))
            
            if result.fetchone():
                logger.info("✅ qdrant_id column already exists")
                return
            
            # Add the column
            conn.execute(text("""
                ALTER TABLE company_capabilities 
                ADD COLUMN qdrant_id VARCHAR(100)
            """))
            
            # Create index
            conn.execute(text("""
                CREATE INDEX idx_capabilities_qdrant_id 
                ON company_capabilities(qdrant_id)
            """))
            
            conn.commit()
            
            logger.info("✅ Successfully added qdrant_id column to company_capabilities")
        
        except Exception as e:
            conn.rollback()
            logger.error(f"❌ Migration failed: {str(e)}")
            raise

if __name__ == "__main__":
    add_qdrant_id_column()