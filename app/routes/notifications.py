# app/routes/notifications.py

from flask import Blueprint, request, jsonify
from bson import ObjectId
from app.middleware.auth import requires_auth
from app.services.notification_service import NotificationService
from app.utils.validators import clean_doc
from app.database.mongo import db
from app.utils.validators import normalize_user_id, normalize_any_id_field, clean_doc, get_user_by_any_id
from app.utils.id_helpers import find_user, ids_match

notifications_bp = Blueprint('notifications', __name__, url_prefix='/api/notifications')

notifications_coll = db['notifications']

# =========================================================================
# 1. GET ALL NOTIFICATIONS FOR CURRENT USER
# =========================================================================

@notifications_bp.route('/', methods=['GET'], strict_slashes=False)
@requires_auth()
def get_notifications():
    """
    Get notifications for current user
    Query params:
    - unreadOnly: true/false (default: false)
    - limit: number of notifications (default: 20)
    """
    user_id = request.user_id
    unread_only = request.args.get('unreadOnly', 'false').lower() == 'true'
    limit = int(request.args.get('limit', 20))

    query = {
        'userId': user_id,  # ✅ Already ObjectId from middleware
        'isDeleted': {'$ne': True}
    }
    
    if unread_only:
        query['read'] = False

    notifications = list(
        notifications_coll.find(query)
        .sort('createdAt', -1)
        .limit(limit)
    )

    return jsonify({
        'success': True,
        'data': [clean_doc(notif) for notif in notifications],
        'count': len(notifications)
    }), 200


# =========================================================================
# 2. GET UNREAD NOTIFICATION COUNT
# =========================================================================

@notifications_bp.route('/unread-count', methods=['GET'])
@requires_auth()
def get_unread_count():
    """Get count of unread notifications for current user"""
    user_id = request.user_id

    count = notifications_coll.count_documents({
        'userId': user_id,
        'read': False,
        'isDeleted': {'$ne': True}
    })

    return jsonify({
        'success': True,
        'count': count
    }), 200


# =========================================================================
# 3. MARK SINGLE NOTIFICATION AS READ (SPECIFIC - BEFORE GENERIC)
# =========================================================================

@notifications_bp.route('/<notification_id>/read', methods=['PUT'])  # ✅ FIXED: Proper route
@requires_auth()
def mark_notification_read(notification_id):
    """Mark a single notification as read"""
    user_id = request.user_id

    try:
        # ✅ Convert string to ObjectId if valid
        notif_id_query = notification_id
        try:
            if ObjectId.is_valid(notification_id):
                notif_id_query = ObjectId(notification_id)
        except:
            pass

        # Verify ownership
        notification = notifications_coll.find_one({
            '_id': notif_id_query,
            'userId': user_id  # ✅ Ensure user owns this notification
        })

        if not notification:
            return jsonify({
                'success': False,
                'error': 'Notification not found or access denied'
            }), 404

        # Mark as read
        result = notifications_coll.update_one(
            {'_id': notif_id_query},
            {'$set': {'read': True}}
        )

        return jsonify({
            'success': True,
            'message': 'Notification marked as read',
            'modified': result.modified_count
        }), 200

    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


# =========================================================================
# 4. MARK ALL NOTIFICATIONS AS READ
# =========================================================================

@notifications_bp.route('/mark-all-read', methods=['PUT'])
@requires_auth()
def mark_all_read():
    """Mark all notifications as read for current user"""
    user_id = request.user_id

    try:
        result = notifications_coll.update_many(
            {
                'userId': user_id,
                'isDeleted': {'$ne': True}
            },
            {'$set': {'read': True}}
        )

        return jsonify({
            'success': True,
            'message': 'All notifications marked as read',
            'modifiedCount': result.modified_count
        }), 200

    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


# =========================================================================
# 5. DELETE A NOTIFICATION (SPECIFIC - BEFORE GENERIC)
# =========================================================================

@notifications_bp.route('/<notification_id>', methods=['DELETE'])  # ✅ FIXED: Proper route with parameter
@requires_auth()
def delete_notification(notification_id):
    """Delete a specific notification"""
    user_id = request.user_id

    try:
        # ✅ Convert string to ObjectId if valid
        notif_id_query = notification_id
        try:
            if ObjectId.is_valid(notification_id):
                notif_id_query = ObjectId(notification_id)
        except:
            pass

        # Verify ownership before deleting
        notification = notifications_coll.find_one({
            '_id': notif_id_query,
            'userId': user_id  # ✅ Ensure user owns this notification
        })

        if not notification:
            return jsonify({
                'success': False,
                'error': 'Notification not found or access denied'
            }), 404

        # Soft delete
        result = notifications_coll.update_one(
            {'_id': notif_id_query},
            {'$set': {'isDeleted': True}}
        )

        return jsonify({
            'success': True,
            'message': 'Notification deleted',
            'deleted': result.modified_count > 0
        }), 200

    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


# =========================================================================
# 6. CLEAR ALL READ NOTIFICATIONS
# =========================================================================

@notifications_bp.route('/clear-read', methods=['DELETE'])
@requires_auth()
def clear_read_notifications():
    """Delete all read notifications for current user"""
    user_id = request.user_id

    try:
        result = notifications_coll.update_many(
            {
                'userId': user_id,
                'read': True,
                'isDeleted': {'$ne': True}
            },
            {'$set': {'isDeleted': True}}  # ✅ Soft delete instead of hard delete
        )

        return jsonify({
            'success': True,
            'message': f'{result.modified_count} notifications cleared',
            'clearedCount': result.modified_count
        }), 200

    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500
