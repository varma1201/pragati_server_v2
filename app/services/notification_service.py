# app/services/notification_service.py

from datetime import datetime, timezone
from app.database.mongo import db
from bson import ObjectId

notifications_coll = db['notifications']


class NotificationService:
    
    NOTIFICATION_TYPES = {
        # ========== TEAM INVITATIONS ==========
        'TEAM_INVITATION_RECEIVED': {
            'title': 'Team Collaboration Invitation',
            'description': '{inviterName} invited you to collaborate on "{ideaTitle}"'
        },
        'TEAM_INVITATION_ACCEPTED': {
            'title': 'Team Invitation Accepted',
            'description': '{memberName} accepted your team invitation for "{ideaTitle}"'
        },
        'TEAM_INVITATION_REJECTED': {
            'title': 'Team Invitation Declined',
            'description': '{memberName} declined your team invitation for "{ideaTitle}"'
        },
        
        # ========== MENTOR REQUESTS ==========
        'MENTOR_REQUEST_RECEIVED': {
            'title': 'New Mentorship Request',
            'description': '{innovatorName} requested your mentorship for "{ideaTitle}"'
        },
        'MENTOR_REQUEST_ACCEPTED': {
            'title': 'Mentor Request Accepted',
            'description': '{mentorName} accepted your mentorship request for "{ideaTitle}"'
        },
        'MENTOR_REQUEST_REJECTED': {
            'title': 'Mentor Request Declined',
            'description': '{mentorName} declined your mentorship request for "{ideaTitle}"'
        },
        
        # ========== CREDIT MANAGEMENT ==========
        'CREDIT_REQUEST_RECEIVED_TTC': {
            'title': 'Credit Request from Innovator',
            'description': '{innovatorName} requested {amount} credits'
        },
        'CREDIT_REQUEST_APPROVED': {
            'title': 'Credits Approved',
            'description': 'Your request for {amount} credits has been approved'
        },
        'CREDIT_REQUEST_REJECTED': {
            'title': 'Credits Rejected',
            'description': 'Your request for {amount} credits was declined. Reason: {reason}'
        },
        'CREDIT_REQUEST_RECEIVED_COLLEGE': {
            'title': 'Credit Request from TTC',
            'description': '{ttcName} requested {amount} credits for their innovators'
        },
        
        # ========== IDEA MANAGEMENT ==========
        'IDEA_SUBMITTED': {
            'title': 'New Idea Submitted',
            'description': '{innovatorName} submitted a new idea "{ideaTitle}"'
        },
        'IDEA_VALIDATED': {
            'title': 'Idea Validated',
            'description': 'Your idea "{ideaTitle}" has been validated. Score: {score}'
        },
        'IDEA_APPROVED': {
            'title': 'Idea Approved',
            'description': 'Congratulations! Your idea "{ideaTitle}" has been approved'
        },
        'IDEA_REJECTED': {
            'title': 'Idea Needs Revision',
            'description': 'Your idea "{ideaTitle}" needs revision. Check feedback for details'
        },
        
        # ========== USER MANAGEMENT ==========
        'WELCOME': {
            'title': 'Welcome to Pragati',
            'description': 'Welcome {userName}! Complete your profile to get started'
        },
        'NEW_INNOVATOR_ASSIGNED': {
            'title': 'New Innovator Assigned',
            'description': 'Innovator {innovatorName} has been assigned to you'
        },
        'ACCOUNT_CREATED': {
            'title': 'Account Created',
            'description': 'Your account has been created. Login credentials sent to your email'
        },
        
        # ========== PSYCHOMETRIC ==========
        'PSYCHOMETRIC_COMPLETED': {
            'title': 'Psychometric Assessment Complete',
            'description': 'Your psychometric assessment is complete. Score: {score}'
        },
        'PSYCHOMETRIC_PENDING': {
            'title': 'Complete Psychometric Assessment',
            'description': 'Please complete your assessment to unlock all features'
        },
        'IDEA_SUBMITTED': {
            'title': 'New Idea Submitted',
            'description': '{innovatorName} submitted a new idea "{ideaTitle}"'
        },
        "TEAM_INVITE": {
        "title": "Team Invitation",
        "description": "{inviterName} invited you to join '{ideaTitle}'",
        "icon": "users",
        "priority": "high",
        "actionUrl": "/dashboard?tab=invitations"
        },
        
        "TEAM_INVITE_ACCEPTED": {
            "title": "Invitation Accepted",
            "description": "{memberName} accepted your invitation to join '{ideaTitle}'",
            "icon": "check-circle",
            "priority": "medium",
            "actionUrl": "/ideas/{ideaId}"
        },
        
        "TEAM_INVITE_REJECTED": {
            "title": "Invitation Declined",
            "description": "{memberName} declined your invitation to join '{ideaTitle}'",
            "icon": "x-circle",
            "priority": "low"
        },
    }
    
    @staticmethod
    def create_notification(user_id: str, notification_type: str, data: dict = None):
        """
        Create a new notification for a user
        
        Args:
            user_id: The user to notify
            notification_type: Type from NOTIFICATION_TYPES
            data: Dictionary containing placeholders for the message template
        
        Returns:
            The created notification document
        """
        if notification_type not in NotificationService.NOTIFICATION_TYPES:
            raise ValueError(f"Invalid notification type: {notification_type}")
        
        template = NotificationService.NOTIFICATION_TYPES[notification_type]
        
        # Format description with provided data
        description = template['description']
        if data:
            try:
                description = description.format(**data)
            except KeyError as e:
                print(f"Warning: Missing key {e} in notification data for type {notification_type}")
        
        notification = {
            '_id': ObjectId(),
            'userId': user_id,
            'type': notification_type,
            'title': template['title'],
            'description': description,
            'data': data or {},
            'read': False,
            'createdAt': datetime.now(timezone.utc)
        }
        
        notifications_coll.insert_one(notification)
        return notification
    
    @staticmethod
    def get_user_notifications(user_id: str, unread_only: bool = False, limit: int = 20):
        """
        Get notifications for a user
        
        Args:
            user_id: The user's ID
            unread_only: If True, only return unread notifications
            limit: Maximum number of notifications to return
        
        Returns:
            List of notification documents
        """
        query = {'userId': user_id}
        if unread_only:
            query['read'] = False
        
        return list(notifications_coll.find(query).sort('createdAt', -1).limit(limit))
    
    @staticmethod
    def mark_as_read(notification_id: str):
        """
        Mark a notification as read
        
        Args:
            notification_id: The notification's ID
        """
        notifications_coll.update_one(
            {'_id': notification_id},
            {'$set': {'read': True, 'readAt': datetime.now(timezone.utc)}}
        )
    
    @staticmethod
    def mark_all_as_read(user_id: str):
        """
        Mark all user notifications as read
        
        Args:
            user_id: The user's ID
        """
        notifications_coll.update_many(
            {'userId': user_id, 'read': False},
            {'$set': {'read': True, 'readAt': datetime.now(timezone.utc)}}
        )
    
    @staticmethod
    def get_unread_count(user_id: str) -> int:
        """
        Get count of unread notifications
        
        Args:
            user_id: The user's ID
        
        Returns:
            Number of unread notifications
        """
        return notifications_coll.count_documents({
            'userId': user_id,
            'read': False
        })
    
    @staticmethod
    def delete_notification(notification_id: str, user_id: str):
        """
        Delete a notification (with ownership check)
        
        Args:
            notification_id: The notification's ID
            user_id: The user's ID (for ownership verification)
        """
        notifications_coll.delete_one({
            '_id': notification_id,
            'userId': user_id
        })
    
    @staticmethod
    def clear_read_notifications(user_id: str):
        """
        Delete all read notifications for a user
        
        Args:
            user_id: The user's ID
        
        Returns:
            Number of deleted notifications
        """
        result = notifications_coll.delete_many({
            'userId': user_id,
            'read': True
        })
        return result.deleted_count
