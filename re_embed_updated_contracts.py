"""
Re-embed contracts with updated descriptions to Pinecone
Runs after scraper improves POOR → GOOD quality

Usage:
    python re_embed_updated_contracts.py
    python re_embed_updated_contracts.py --hours 24
"""

import os
import argparse
from datetime import datetime, timedelta, timezone
from typing import List
from dotenv import load_dotenv
from pinecone import Pinecone
from openai import OpenAI
from sqlalchemy import and_
from tqdm import tqdm

from app.database import SessionLocal
from app.models.company import OpportunityChain

load_dotenv()

# Config
PINECONE_API_KEY = os.getenv("PINECONE_API_KEY")
PINECONE_INDEX_NAME = os.getenv("PINECONE_INDEX_NAME", "contracts")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
EMBEDDING_MODEL = "text-embedding-3-small"
EMBEDDING_DIMENSIONS = 768
BATCH_SIZE = 100


def create_embedding_text(chain: OpportunityChain) -> str:
    """Create text for embedding from opportunity chain."""
    parts = []
    
    if chain.base_description:
        parts.append(f"Description: {chain.base_description[:2000]}")
    
    if chain.base_type:
        parts.append(f"Type: {chain.base_type}")
    
    if chain.solicitation_number:
        parts.append(f"Solicitation: {chain.solicitation_number}")
    
    return "\n".join(parts)


def get_embeddings(texts: List[str], client: OpenAI) -> List[List[float]]:
    """Get embeddings for batch of texts."""
    response = client.embeddings.create(
        model=EMBEDDING_MODEL,
        input=texts,
        dimensions=EMBEDDING_DIMENSIONS
    )
    return [item.embedding for item in response.data]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--hours', type=int, default=24, 
                       help="Re-embed contracts updated in last N hours")
    parser.add_argument('--namespace', type=str, default="contracts",
                       help="Pinecone namespace")
    args = parser.parse_args()
    
    print("=" * 70)
    print("RE-EMBED UPDATED CONTRACTS TO PINECONE")
    print("=" * 70)
    print(f"⏰ Looking for updates in last {args.hours} hours")
    print(f"🏷️  Namespace: {args.namespace}")
    print()
    
    # Connect
    db = SessionLocal()
    pc = Pinecone(api_key=PINECONE_API_KEY)
    index = pc.Index(PINECONE_INDEX_NAME)
    openai_client = OpenAI(api_key=OPENAI_API_KEY)
    
    # Find updated contracts
    cutoff = datetime.now(timezone.utc) - timedelta(hours=args.hours)
    
    contracts = db.query(OpportunityChain).filter(
        and_(
            OpportunityChain.base_description_quality == 'GOOD',
            OpportunityChain.scraped_at.isnot(None),  # ONLY SCRAPED
            OpportunityChain.scraped_at >= cutoff,  # Changed in last N hours
            OpportunityChain.latest_closing_date >= datetime.now(timezone.utc)
        )
    ).all()
    
    print(f"📊 Found {len(contracts)} updated GOOD quality contracts")
    
    if len(contracts) == 0:
        print("✅ Nothing to re-embed")
        db.close()
        return
    
    print()
    
    # Re-embed in batches
    updated_count = 0
    
    for i in range(0, len(contracts), BATCH_SIZE):
        batch = contracts[i:i + BATCH_SIZE]
        
        # Create embedding texts
        texts = [create_embedding_text(c) for c in batch]
        
        # Get embeddings
        embeddings = get_embeddings(texts, openai_client)
        
        # Prepare vectors
        vectors = []
        for chain, embedding in zip(batch, embeddings):
            vector_id = chain.base_notice_id  # Use notice ID as vector ID
            
            vectors.append({
                "id": vector_id,
                "values": embedding,
                "metadata": {
                    "notice_id": chain.solicitation_number,
                    "opp_id": chain.base_notice_id,
                    "title": chain.base_description[:200] if chain.base_description else "",
                    "description": chain.base_description[:1000] if chain.base_description else "",
                    "response_deadline": chain.latest_closing_date.isoformat() if chain.latest_closing_date else "",
                    "posted_date": chain.base_posted_date.isoformat() if chain.base_posted_date else "",
                    "opportunity_type": chain.base_type or "",
                    "status": "active",
                    "url": f"https://sam.gov/opp/{chain.base_notice_id}/view"
                }
            })
        
        # Upsert to Pinecone
        index.upsert(vectors=vectors, namespace=args.namespace)
        updated_count += len(vectors)
        
        print(f"✅ Re-embedded batch {i//BATCH_SIZE + 1}: {len(vectors)} contracts")
    
    print()
    print("=" * 70)
    print("✅ RE-EMBEDDING COMPLETE")
    print("=" * 70)
    print(f"   Total re-embedded: {updated_count}")
    print()
    
    db.close()


if __name__ == "__main__":
    main()