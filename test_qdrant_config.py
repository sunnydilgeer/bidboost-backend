from app.core.config import settings
import os

print("=" * 60)
print("ENVIRONMENT VARIABLES (from os.environ):")
print("=" * 60)
print(f"QDRANT_URL: {os.getenv('QDRANT_URL', 'NOT SET')}")
print(f"QDRANT_HOST: {os.getenv('QDRANT_HOST', 'NOT SET')}")
print(f"QDRANT_PORT: {os.getenv('QDRANT_PORT', 'NOT SET')}")

print("\n" + "=" * 60)
print("PYDANTIC SETTINGS (from app.core.config):")
print("=" * 60)
print(f"settings.QDRANT_URL: {settings.QDRANT_URL}")
print(f"settings.QDRANT_HOST: {settings.QDRANT_HOST}")
print(f"settings.QDRANT_PORT: {settings.QDRANT_PORT}")
print(f"settings.QDRANT_API_KEY: {'SET' if settings.QDRANT_API_KEY else 'NOT SET'}")
print(f"settings.USE_OPENAI_EMBEDDINGS: {settings.USE_OPENAI_EMBEDDINGS}")
print("=" * 60)
