
import sys
import os
import json
from unittest.mock import MagicMock
from bson import ObjectId
from datetime import datetime

# 1. Setup Mocks for modules BEFORE importing the SUT (System Under Test)
sys.modules['flask'] = MagicMock()
sys.modules['boto3'] = MagicMock()
sys.modules['app.middleware.auth'] = MagicMock()
sys.modules['app.utils.validators'] = MagicMock()
sys.modules['app.utils.id_helpers'] = MagicMock()
sys.modules['app.services.notification_service'] = MagicMock()
sys.modules['app.services.audit_service'] = MagicMock()
sys.modules['app.database.mongo'] = MagicMock()

# 2. Configure specific mocks
# Flask
mock_request = MagicMock()
sys.modules['flask'].request = mock_request
sys.modules['flask'].jsonify = lambda x: x # Identity function for easier inspection

# Mongo
mock_mongo = sys.modules['app.database.mongo']
mock_ideas_coll = mock_mongo.ideas_coll
mock_users_coll = mock_mongo.users_coll

# Utils
mock_validators = sys.modules['app.utils.validators']
mock_transformers = sys.modules['app.utils.id_helpers']

# Configure helpers
mock_validators.clean_doc = lambda x: x
mock_validators.normalize_any_id_field = lambda k, v: {k: v}
mock_transformers.ids_match = lambda a, b: str(a) == str(b)

# Configure User Lookup
def fake_find_user(uid):
    if str(uid) == "user123":
        return {"_id": "user123", "email": "innovator@example.com", "name": "Innovator", "role": "innovator"}
    if str(uid) == "mentor123":
        return {"_id": "mentor123", "email": "mentor@example.com", "name": "Dr. Mentor", "organization": "IIT Madras"}
    return None

mock_transformers.find_user.side_effect = fake_find_user

# 3. Import SUT
# We need to ensure we can find the app module
sys.path.append(os.path.abspath(os.getcwd()))
try:
    import app.routes.ideas as ideas_module
    from app.routes.ideas import get_ideas_by_user
    
    # Verify mocks are injected
    print(f"🔎 ideas_coll type: {type(ideas_module.ideas_coll)}")
    print(f"🔎 ideas_coll match: {ideas_module.ideas_coll is mock_ideas_coll}")
    
except ImportError as e:
    print(f"❌ Failed to import: {e}")
    sys.exit(1)

# 4. Setup Test Data and Environment
mock_request.user_id = "user123"
mock_request.user_role = "innovator"
mock_request.args.get.side_effect = lambda k, d=None: d

idea_with_cons = {
    "_id": ObjectId(),
    "title": "Smart Irrigation",
    "innovatorId": "user123",
    "consultationMentorId": "mentor123",
    "consultationStatus": "assigned", 
    "consultationScheduledAt": datetime(2023, 11, 15, 14, 30),
    "pptFileKey": None # Simplify
}

# 5. Configure Mongo Query Result
# The chain is: find().sort().skip().limit() -> returns list
mock_cursor = MagicMock()
mock_ideas_coll.find.return_value = mock_cursor
mock_cursor.sort.return_value = mock_cursor
mock_cursor.skip.return_value = mock_cursor
mock_cursor.limit.return_value = [idea_with_cons] # The final object is iterable

mock_ideas_coll.count_documents.return_value = 1

# 6. Run Test
print("🚀 Running get_ideas_by_user('me')...")
try:
    response_tuple = get_ideas_by_user("me")
    
    # Handle tuple response (response, status_code)
    if isinstance(response_tuple, tuple):
        response = response_tuple[0]
        code = response_tuple[1]
    else:
        response = response_tuple
        code = 200

    print(f"✅ Status Code: {code}")
    
    data = response['data']
    print(f"✅ Returned {len(data)} ideas")
    
    # DEBUG: Print interactions
    print("\n🧐 Mock Interactions:")
    print(f"ideas_coll.find called: {mock_ideas_coll.find.called}")
    print(f"ideas_coll.find calls: {mock_ideas_coll.find.call_args_list}")
    print(f"cursor.sort called: {mock_cursor.sort.called}")
    print(f"cursor.skip called: {mock_cursor.skip.called}")
    print(f"cursor.limit called: {mock_cursor.limit.called}")
    
    if len(data) > 0:
        idea = data[0]
        # ... logic ...

        print(f"✅ Idea Title: {idea['title']}")
        
        if 'consultation' in idea:
            cons = idea['consultation']
            print("✅ Consultation Field Present:")
            print(json.dumps(cons, indent=2, default=str))
            
            # Assertions
            if cons['mentor']['organization'] == "IIT Madras":
                print("✅ Mentor Organization verified")
            else:
                print(f"❌ Mentor Organization mismatch: {cons['mentor']['organization']}")
                
            if cons['status'] == "Scheduled":
                 print("✅ Status normalized to Scheduled")
            else:
                 print(f"❌ Status mismatch: {cons['status']}")
                 
        else:
            print("❌ Consultation field MISSING")

except Exception as e:
    print(f"❌ Exception: {e}")
    import traceback
    traceback.print_exc()
