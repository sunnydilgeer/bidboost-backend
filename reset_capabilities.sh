#!/bin/bash

# 🔄 Capability Reset & Optimization Script
# This will delete old capabilities and add optimized ones

TOKEN="eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiJzdXJpbmRlci5kaWxnZWVyKzY5QGdtYWlsLmNvbSIsInVzZXJfaWQiOiIzM2E0ZmZhOC1iMTY5LTRmNDQtOGNjNC1mM2E2NGQ0MjFhNjEiLCJmaXJtX2lkIjoiZmlybS1jbGFyZW5jZS1hbmQtZmlzaGJ1cm4tbGxwIiwicm9sZSI6InVzZXIiLCJuYW1lIjoiQ2xhaXJlIiwiZXhwIjoxNzY1MzM0NjQzLCJpYXQiOjE3NjUzMDU4NDN9.DgmMiHYYOczV0BBAlgpeAqm4ApLPf_dlVCyoSfaciYg"
API_BASE="https://backend-api-production-387c.up.railway.app/api"

echo "🔍 Step 1: Getting current capabilities..."
CAPABILITIES=$(curl -s "$API_BASE/capabilities" -H "Authorization: Bearer $TOKEN")
echo "$CAPABILITIES" | python3 -m json.tool

# Extract capability IDs
CAPABILITY_IDS=$(echo "$CAPABILITIES" | python3 -c "import sys, json; data = json.load(sys.stdin); print(' '.join([str(c['id']) for c in data]))")

echo ""
echo "🗑️  Step 2: Deleting old capabilities..."
for ID in $CAPABILITY_IDS; do
    echo "Deleting capability ID: $ID"
    curl -s -X DELETE "$API_BASE/capabilities/$ID" \
        -H "Authorization: Bearer $TOKEN"
    echo ""
done

echo ""
echo "✅ Step 3: Adding optimized capabilities..."
echo ""

# Capability 1: Cloud Migration & AWS GovCloud
echo "➕ Adding: Cloud Migration & AWS GovCloud..."
curl -s -X POST "$API_BASE/capabilities" \
    -H "Authorization: Bearer $TOKEN" \
    -H "Content-Type: application/json" \
    -d '{
        "capability_text": "Cloud migration and modernization services with expertise in AWS GovCloud, Azure Government Cloud, and Google Cloud Platform. Specializing in lift-and-shift migrations, cloud-native application development, containerization with Docker and Kubernetes, and hybrid cloud architectures for federal agencies requiring FedRAMP compliance.",
        "category": "Cloud Services"
    }' | python3 -m json.tool

echo ""
echo "➕ Adding: DevOps & CI/CD Automation..."
curl -s -X POST "$API_BASE/capabilities" \
    -H "Authorization: Bearer $TOKEN" \
    -H "Content-Type: application/json" \
    -d '{
        "capability_text": "DevOps engineering and automation services including CI/CD pipeline development, infrastructure as code using Terraform and CloudFormation, configuration management with Ansible and Puppet, automated testing frameworks, and GitOps workflows. Experienced with Jenkins, GitLab CI, GitHub Actions, and Azure DevOps for government projects.",
        "category": "DevOps"
    }' | python3 -m json.tool

echo ""
echo "➕ Adding: Cybersecurity & Compliance..."
curl -s -X POST "$API_BASE/capabilities" \
    -H "Authorization: Bearer $TOKEN" \
    -H "Content-Type: application/json" \
    -d '{
        "capability_text": "Cybersecurity services and compliance consulting for federal agencies including FedRAMP authorization support (Moderate and High baselines), NIST 800-53 controls implementation, Authority to Operate (ATO) acquisition, security assessment and authorization (SA&A), continuous monitoring, vulnerability management, penetration testing, and incident response planning.",
        "category": "Security"
    }' | python3 -m json.tool

echo ""
echo "➕ Adding: Data Center Migration & Infrastructure..."
curl -s -X POST "$API_BASE/capabilities" \
    -H "Authorization: Bearer $TOKEN" \
    -H "Content-Type: application/json" \
    -d '{
        "capability_text": "Data center consolidation and migration services including legacy system modernization, network infrastructure design and implementation, server virtualization, storage solutions, disaster recovery planning, business continuity services, and FISMA-compliant infrastructure management for Department of Defense and civilian agencies.",
        "category": "Infrastructure"
    }' | python3 -m json.tool

echo ""
echo "➕ Adding: IT Management & Technical Support..."
curl -s -X POST "$API_BASE/capabilities" \
    -H "Authorization: Bearer $TOKEN" \
    -H "Content-Type: application/json" \
    -d '{
        "capability_text": "IT service management and technical support services including help desk operations, IT service desk management following ITIL best practices, system administration for Windows and Linux environments, database administration (Oracle, SQL Server, PostgreSQL), network operations center (NOC) support, and 24/7 monitoring and maintenance for mission-critical government systems.",
        "category": "IT Services"
    }' | python3 -m json.tool

echo ""
echo "➕ Adding: Software Development & Integration..."
curl -s -X POST "$API_BASE/capabilities" \
    -H "Authorization: Bearer $TOKEN" \
    -H "Content-Type: application/json" \
    -d '{
        "capability_text": "Custom software development and systems integration services including full-stack web application development, API design and integration, microservices architecture, legacy application modernization, mobile app development, agile software development methodologies, and enterprise application integration for federal agencies. Proficient in Java, Python, .NET, React, Angular, and Node.js.",
        "category": "Software Development"
    }' | python3 -m json.tool

echo ""
echo "✅ All capabilities added successfully!"
echo ""
echo "🔍 Step 4: Verifying new capabilities..."
curl -s "$API_BASE/capabilities" -H "Authorization: Bearer $TOKEN" | python3 -m json.tool

echo ""
echo "✅ Setup complete! Your profile now has 6 optimized capabilities."
echo ""
echo "🧪 Ready to test with improved match scores!"