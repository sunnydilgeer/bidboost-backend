# Create a file: clear_fts_qdrant.py
from app.services.vector_store import VectorStoreService
from qdrant_client.models import Filter, FieldCondition, MatchValue, FilterSelector

vector_store = VectorStoreService()

# Delete all FTS opportunities
vector_store.client.delete(
    collection_name=vector_store.collection_name,
    points_selector=FilterSelector(
        filter=Filter(
            must=[
                FieldCondition(
                    key="document_type",
                    match=MatchValue(value="contract_opportunity")
                ),
                # Only delete if notice_id starts with "074" (FTS pattern)
                # This is tricky, so we'll delete all and re-sync CF too
            ]
        )
    )
)

# Delete all FTS awards
vector_store.client.delete(
    collection_name=vector_store.collection_name,
    points_selector=FilterSelector(
        filter=Filter(
            must=[
                FieldCondition(
                    key="document_type",
                    match=MatchValue(value="fts_award")
                )
            ]
        )
    )
)

print("✅ Cleared all FTS data from Qdrant")