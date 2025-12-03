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
    Find user by ID (string or ObjectId).
    Returns user document with actual _id.
    """
    return get_user_by_any_id(user_id)


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
