
import os
import sys
from collections import defaultdict

# Ensure 'app' module can be found
sys.path.append(os.getcwd())

from app.database.mongo import ideas_coll, results_coll

def verify_dashboard_logic():
    print("🧪 Verifying Dashboard Logic...")
    
    ideas = list(ideas_coll.find().limit(20)) # Check first 20 ideas
    status_counts = defaultdict(int)
    
    print(f"   Analyzing {len(ideas)} ideas...")
    
    for idea in ideas:
        result = results_coll.find_one({"ideaId": str(idea["_id"])})
        
        # Logic from dashboard.py
        if result:
            raw_outcome = result.get("validationOutcome", "Pending")
        else:
            raw_outcome = idea.get("status", "Pending")
        
        val = str(raw_outcome).upper()
        if val == "APPROVED":
            outcome = "Approved"
        elif val == "MODERATE":
            outcome = "Moderate"
        elif val == "REJECTED":
            outcome = "Rejected"
        elif val == "SUBMITTED" or val == "PENDING":
            outcome = "Pending"
        else:
            outcome = "Pending" 
            
        print(f"   Idea {idea['_id']} -> Raw: '{raw_outcome}' -> Normalized: '{outcome}'")
        status_counts[outcome] += 1
        
    print("\n📊 Final Counts:")
    for k, v in status_counts.items():
        print(f"   {k}: {v}")
        
    if sum(status_counts.values()) > 0:
        print("✅ Success: Logic produces counts")
    else:
        print("⚠️ Warning: No counts found (DB might be empty)")

if __name__ == "__main__":
    verify_dashboard_logic()
