
import sys
import os
import json
from unittest.mock import MagicMock, patch
from bson import ObjectId
from datetime import datetime

# Add project root to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

# Mock Flask and other dependencies
sys.modules['flask'] = MagicMock()
sys.modules['flask'].request = MagicMock()
sys.modules['flask'].jsonify = lambda x: x
sys.modules['app.middleware.auth'] = MagicMock()
sys.modules['app.middleware.auth'].requires_auth = lambda: lambda f: f
sys.modules['app.database.mongo'] = MagicMock()
sys.modules['app.utils.validators'] = MagicMock()
sys.modules['app.utils.id_helpers'] = MagicMock()
sys.modules['app.services.notification_service'] = MagicMock()
sys.modules['app.services.audit_service'] = MagicMock()
sys.modules['boto3'] = MagicMock()

# Import the function to test
# We need to mock the imports inside ideas.py before importing it
with patch('app.database.mongo.ideas_coll') as mock_ideas_coll, \
     patch('app.database.mongo.users_coll') as mock_users_coll, \
     patch('app.utils.id_helpers.find_user') as mock_find_user, \
     patch('flask.request') as mock_request, \
     patch('app.utils.id_helpers.ids_match') as mock_ids_match, \
     patch('app.utils.validators.clean_doc') as mock_clean_doc:

    from app.routes.ideas import get_ideas_by_user

    # Setup Mocks
    mock_request.user_id = "user123"
    mock_request.user_role = "innovator"
    mock_request.args.get.side_effect = lambda k, d=None: d  # Mock args.get
    
    # Mock find_user to return current user
    mock_find_user.side_effect = lambda uid: {"_id": uid, "email": "test@example.com", "name": "Test User", "organization": "Test Org"} if uid == "user123" or uid == "mentor123" else None

    # Mock ids_match
    def side_effect_match(id1, id2):
        return str(id1) == str(id2)
    mock_ids_match.side_effect = side_effect_match

    # Mock clean_doc
    mock_clean_doc.side_effect = lambda x: x

    # Test Data
    idea_with_consultation = {
        "_id": ObjectId(),
        "title": "Test Idea",
        "innovatorId": "user123",
        "consultationMentorId": "mentor123",
        "consultationStatus": "assigned",
        "consultationScheduledAt": datetime(2023, 11, 15, 14, 30),
        "createdAt": datetime.now()
    }
    
    idea_without_consultation = {
        "_id": ObjectId(),
        "title": "Pending Idea",
        "innovatorId": "user123",
        "createdAt": datetime.now()
    }

    # Mock DB Query
    mock_ideas_coll.count_documents.return_value = 2
    mock_ideas_coll.find.return_value.sort.return_value.skip.return_value.limit.return_value = [
        idea_with_consultation,
        idea_without_consultation
    ]

    # Run the Function
    try:
        print("Calling get_ideas_by_user...")
        response_tuple = get_ideas_by_user("me")
        print(f"Result type: {type(response_tuple)}")
        
        if isinstance(response_tuple, tuple) and len(response_tuple) == 2:
            response, status = response_tuple
        else:
            print(f"Unexpected return format: {response_tuple}")
            response = response_tuple
            status = 200

        # Verify Response
        print("Response Keys:", response.keys())
        data = response['data']
        print(f"Number of ideas: {len(data)}")

        for idea in data:
            print(f"Idea: {idea['title']}")
            if idea.get('consultation'):
                print("  ✅ Consultation found:")
                print(json.dumps(idea['consultation'], indent=4, default=str))
                
                # Assertions
                cons = idea['consultation']
                assert cons['status'] == 'Scheduled'
                assert cons['mentor']['name'] == 'Test User'
                assert cons['mentor']['organization'] == 'Test Org'
            else:
                print("  ℹ️ No consultation")

        print("\n✅ Verification Passed!")

    except Exception as e:
        print("\n❌ Error during execution:")
        import traceback
        traceback.print_exc()
        sys.exit(1)
