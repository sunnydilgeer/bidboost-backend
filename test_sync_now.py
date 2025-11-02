from app.tasks.email_scheduler import email_scheduler
import time

print("🚀 Starting email scheduler...")
email_scheduler.start()

print("⚡ Triggering contract sync job NOW...")
email_scheduler.run_job_now('sync_contracts_daily')

print("⏳ Waiting for job to complete...")
time.sleep(10)  # Wait 10 seconds for job to finish

print("✅ Done! Check logs above for sync results.")
email_scheduler.shutdown()
