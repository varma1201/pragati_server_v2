
import os
import sys
from datetime import datetime, timezone
from bson import ObjectId

# Ensure 'app' module can be found
sys.path.append(os.getcwd())

from app.database.mongo import users_coll, ideas_coll

def setup_test_data():
    print("🛠️ Setting up test data...")
    
    # 1. Create College Admin
    admin_id = ObjectId()
    admin_doc = {
        "_id": admin_id,
        "name": "Test Principal",
        "email": "principal@test.com",
        "role": "college_admin",
        "collegeId": admin_id
    }
    users_coll.insert_one(admin_doc)
    
    # 2. Create Mentor
    mentor_id = ObjectId()
    mentor_doc = {
        "_id": mentor_id,
        "name": "Test Mentor",
        "email": "mentor@test.com",
        "role": "internal_mentor",
        "collegeId": admin_id,
        "createdBy": admin_id,
        "isDeleted": False
    }
    users_coll.insert_one(mentor_doc)
    
    # 3. Create Innovator
    innovator_id = ObjectId()
    innovator_doc = {
        "_id": innovator_id,
        "name": "Test Innovator",
        "email": "innovator@test.com",
        "phone": "1234567890",
        "role": "innovator"
    }
    users_coll.insert_one(innovator_doc)
    
    # 4. Create Assigned Idea
    idea_id = ObjectId()
    idea_doc = {
        "_id": idea_id,
        "title": "Test Idea",
        "status": "submitted",
        "mentorId": str(mentor_id), 
        "innovatorId": str(innovator_id),
        "isDeleted": False
    }
    ideas_coll.insert_one(idea_doc)
    
    return admin_id, mentor_id, idea_id, innovator_id

def cleanup_test_data(ids):
    print("🧹 Cleaning up...")
    users_coll.delete_many({"_id": {"$in": [ids[0], ids[1], ids[3]]}})
    ideas_coll.delete_many({"_id": ids[2]})

def verify_response_structure(admin_id, mentor_id):
    print("🧪 Verifying Response Structure Logic...")
    
    # Simulate DB Logic
    mentor = users_coll.find_one({"_id": mentor_id})
    ideas = list(ideas_coll.find({"mentorId": str(mentor_id)}))
    
    innovator_ids = set()
    for idea in ideas:
        if idea.get("innovatorId"):
            innovator_ids.add(ObjectId(idea.get("innovatorId")))
            
    innovators = list(users_coll.find({"_id": {"$in": list(innovator_ids)}}))
    
    # Verify Structure
    response = {
        "mentor": {"name": mentor["name"]},
        "assignments": [{"title": i["title"]} for i in ideas],
        "innovators": [{"name": i["name"]} for i in innovators]
    }
    
    print(f"   Response Keys: {list(response.keys())}")
    
    if "innovators" not in response:
        print("❌ 'innovators' list missing")
        return False
        
    if len(response["innovators"]) != 1:
        print("❌ Innovator count mismatch")
        return False
        
    print("✅ Structure Valid")
    return True

if __name__ == "__main__":
    ids = setup_test_data()
    try:
        success = verify_response_structure(ids[0], ids[1])
        if not success:
            sys.exit(1)
    finally:
        cleanup_test_data(ids)
