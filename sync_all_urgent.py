import asyncio
from app.tasks.sam_sync import sync_sam_contracts

async def main():
    print("="*70)
    print("SYNCING ALL URGENT SAM.GOV OPPORTUNITIES")
    print("This will sync 2,984 opportunities with closing deadlines")
    print("="*70)
    
    result = await sync_sam_contracts(
        source="urgent",
        max_records=None  # No limit - sync ALL
    )
    
    print("\n" + "="*70)
    print("FINAL RESULTS:")
    print(f"  Status: {result['status']}")
    print(f"  Total Synced: {result.get('synced', 0):,}")
    print(f"  Duration: {result.get('duration', 0):.1f}s")
    print(f"  Speed: {result.get('avg_speed', 0):.1f} opps/sec")
    print("="*70)

if __name__ == "__main__":
    asyncio.run(main())
