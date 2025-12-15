# app/utils/id_helpers.py
"""
Universal ID handling utilities.
Import these anywhere you need to work with user IDs.
"""
from bson import ObjectId
from app.database.mongo import users_coll, ideas_coll, notifications_coll
from app.utils.validators import normalize_user_id, normalize_any_id_field, get_user_by_any_id


def find_user(user_id):
    """
    Find user by ID, handling both string and ObjectId formats.
    
    Args:
        user_id: User ID as string or ObjectId
        
    Returns:
        User document or None
    """
    if not user_id:
        return None
    
    try:
        # Convert to ObjectId if it's a string
        if isinstance(user_id, str):
            oid = ObjectId(user_id)
        else:
            oid = user_id
        
        return users_coll.find_one({"_id": oid})
    except Exception as e:
        print(f"❌ Error finding user {user_id}: {e}")
        return None


def ids_match(id1, id2):
    """
    Compare two IDs, handling both string and ObjectId formats.
    
    Args:
        id1: First ID (string or ObjectId)
        id2: Second ID (string or ObjectId)
        
    Returns:
        Boolean: True if IDs match
    """
    if id1 is None or id2 is None:
        return False
    
    # Convert both to strings for comparison
    str1 = str(id1)
    str2 = str(id2)
    
    return str1 == str2


def normalize_id(user_id):
    """
    Convert user ID to ObjectId if it's a string.
    
    Args:
        user_id: User ID as string or ObjectId
        
    Returns:
        ObjectId
    """
    if isinstance(user_id, str):
        return ObjectId(user_id)
    return user_id

def find_user_ideas(user_id):
    """
    Find all ideas for a user (handles both ID formats).
    """
    user = find_user(user_id)
    if not user:
        return []
    
    actual_id = user["_id"]
    return list(ideas_coll.find({
        **normalize_any_id_field("innovatorId", actual_id),
        "isDeleted": {"$ne": True}
    }))


def find_user_notifications(user_id):
    """
    Find all notifications for a user (handles both ID formats).
    """
    user = find_user(user_id)
    if not user:
        return []
    
    actual_id = user["_id"]
    return list(notifications_coll.find({
        **normalize_any_id_field("recipientId", actual_id),
        "isDeleted": {"$ne": True}
    }).sort("createdAt", -1))


def ids_match(id1, id2):
    """
    Check if two IDs are the same (handles ObjectId vs string comparison).
    """
    return str(id1) == str(id2)
