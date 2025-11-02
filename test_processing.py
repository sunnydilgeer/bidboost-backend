import asyncio
from app.services.document_processor import processor

async def test():
    try:
        result = await processor.process_and_store(
            file_path="test_capability.txt",
            file_type="txt",
            company_id=1,
            filename="test_capability.txt"
        )
        print("✓ Processing successful!")
        print(f"  Document ID: {result['document_id']}")
        print(f"  Chunks stored: {result['chunks_stored']}")
        print(f"  Processing time: {result['processing_time_seconds']}s")
    except Exception as e:
        print(f"✗ Processing failed: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(test())