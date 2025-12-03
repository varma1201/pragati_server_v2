# app/utils/validators.py
from bson import ObjectId


def normalize_user_id(user_id):
    """
    Create MongoDB query that works with both ObjectId and string UUIDs.
    
    Usage:
        user = users_coll.find_one({**normalize_user_id(user_id), "isDeleted": {"$ne": True}})
    
    Args:
        user_id: String or ObjectId
    
    Returns:
        dict: MongoDB query with $or condition for both formats
    """
    if isinstance(user_id, ObjectId):
        return {"_id": user_id}
    
    if isinstance(user_id, str):
        # If it's 24 chars, it might be an ObjectId string
        if len(user_id) == 24:
            try:
                oid = ObjectId(user_id)
                # Try both ObjectId and string
                return {"$or": [{"_id": oid}, {"_id": user_id}]}
            except:
                # Invalid ObjectId format, use as string
                return {"_id": user_id}
        else:
            # It's a UUID string (old format)
            return {"_id": user_id}
    
    return {"_id": user_id}


def get_user_by_any_id(user_id):
    """
    Retrieve user by ID (supports both ObjectId and string UUID).
    Returns the actual user document with the correct _id format.
    
    Usage:
        user = get_user_by_any_id(user_id)
        if user:
            actual_id = user["_id"]  # Use this for all queries
    
    Args:
        user_id: String or ObjectId
    
    Returns:
        dict: User document or None
    """
    from app.database.mongo import users_coll
    
    return users_coll.find_one({
        **normalize_user_id(user_id),
        "isDeleted": {"$ne": True}
    })


def normalize_any_id_field(field_name, id_value):
    """
    Create MongoDB query for any ID field (not just _id).
    Useful for innovatorId, mentorId, recipientId, etc.
    
    Usage:
        query = normalize_any_id_field("innovatorId", user_id)
        ideas = ideas_coll.find({**query, "isDeleted": {"$ne": True}})
    
    Args:
        field_name: Name of the ID field
        id_value: String or ObjectId
    
    Returns:
        dict: MongoDB query with $or condition
    """
    if isinstance(id_value, ObjectId):
        return {field_name: id_value}
    
    if isinstance(id_value, str) and len(id_value) == 24:
        try:
            oid = ObjectId(id_value)
            return {"$or": [{field_name: oid}, {field_name: id_value}]}
        except:
            return {field_name: id_value}
    
    return {field_name: id_value}


def parse_oid(id_value):
    """
    Convert ID to appropriate format for MongoDB queries.
    Handles both string UUIDs and ObjectIds.
    
    Args:
        id_value: String or ObjectId
    
    Returns:
        ObjectId or str: Converted ID
    """
    if isinstance(id_value, ObjectId):
        return id_value
    
    if isinstance(id_value, str) and len(id_value) == 24:
        try:
            return ObjectId(id_value)
        except:
            return id_value
    
    return id_value


def clean_doc(doc):
    """
    Convert ObjectId, datetime, and bytes to JSON-serializable formats.
    Removes sensitive fields like passwords.
    
    Args:
        doc: MongoDB document, list, or primitive value
    
    Returns:
        JSON-serializable version of the input
    """
    if doc is None:
        return None
    
    if isinstance(doc, list):
        return [clean_doc(item) for item in doc]
    
    if isinstance(doc, dict):
        cleaned = {}
        for k, v in doc.items():
            # Skip sensitive fields
            if k in ['password', 'passwordHash']:
                continue
            
            # Handle bytes (bcrypt hashes)
            if isinstance(v, bytes):
                continue
            
            if isinstance(v, ObjectId):
                cleaned[k] = str(v)
            elif isinstance(v, dict):
                cleaned[k] = clean_doc(v)
            elif isinstance(v, list):
                cleaned[k] = [clean_doc(item) for item in v]
            elif hasattr(v, 'isoformat'):  # datetime
                cleaned[k] = v.isoformat()
            else:
                cleaned[k] = v
        return cleaned
    
    if isinstance(doc, ObjectId):
        return str(doc)
    
    if isinstance(doc, bytes):
        return None
    
    if hasattr(doc, 'isoformat'):
        return doc.isoformat()
    
    return doc
