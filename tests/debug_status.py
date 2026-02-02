
import os
import sys

# Ensure 'app' module can be found
sys.path.append(os.getcwd())

from app.database.mongo import ideas_coll, results_coll

def debug_status_values():
    print("🔍 Debugging Status Values...")
    
    # 1. Check distinct Idea Statuses
    distinct_idea_status = ideas_coll.distinct("status")
    print(f"📌 Distinct Idea Statuses: {distinct_idea_status}")
    
    # 2. Check distinct Result Outcomes
    distinct_outcomes = results_coll.distinct("validationOutcome")
    print(f"📌 Distinct Validation Outcomes: {distinct_outcomes}")
    
    # 3. Sample check
    print("\n📋 Sample Idea Mapping:")
    ideas = list(ideas_coll.find().limit(5))
    for idea in ideas:
        idea_id = str(idea["_id"])
        result = results_coll.find_one({"ideaId": idea_id})
        
        idea_status = idea.get("status")
        result_outcome = result.get("validationOutcome") if result else "NO_RESULT"
        
        print(f"   Idea {idea_id}: Status='{idea_status}' -> Result='{result_outcome}'")

if __name__ == "__main__":
    debug_status_values()
