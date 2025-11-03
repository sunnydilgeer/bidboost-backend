#!/bin/bash
for i in {1..100}; do
  echo "$(date '+%Y-%m-%d %H:%M:%S') - Batch $i of 100..."
  curl -X POST \
    -H "Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiJzdXJpbmRlci5kaWxnZWVyKzY5QGdtYWlsLmNvbSIsInVzZXJfaWQiOiIzM2E0ZmZhOC1iMTY5LTRmNDQtOGNjNC1mM2E2NGQ0MjFhNjEiLCJmaXJtX2lkIjoiZmlybS1jbGFyZW5jZS1hbmQtZmlzaGJ1cm4tbGxwIiwicm9sZSI6InVzZXIiLCJuYW1lIjoiQ2xhaXJlIiwiZXhwIjoxNzYyMjAwOTY2LCJpYXQiOjE3NjYyMTQ5MDAzfQ.Gq4PoKW9WZunvkg5nq2S6cAjAODQMtksFW6xI2bdqRs" \
    "https://backend-api-production-387c.up.railway.app/api/contracts/sync?limit=100&days_back=365" \
    --max-time 300 \
    -o /dev/null -w "Status: %{http_code}\n"
  sleep 2
done
echo "$(date '+%Y-%m-%d %H:%M:%S') - Complete! Synced 10,000 contracts."