# app/routes/search.py

from flask import Blueprint, request, jsonify
from app.middleware.auth import requires_auth
from app.database.mongo import users_coll, ideas_coll, db
from app.utils.validators import clean_doc
from datetime import datetime, timezone

search_bp = Blueprint('search', __name__, url_prefix='/api/search')


@search_bp.route('/global', methods=['GET'])
@requires_auth()
def global_search():
    """
    Global search across users, ideas, colleges, mentors
    Query params:
    - q: search query (required)
    - type: filter by type (optional) - users, ideas, colleges, mentors, all
    - limit: results per category (default: 5)
    """
    caller_id = request.user_id
    caller_role = request.user_role
    
    query = request.args.get('q', '').strip()
    search_type = request.args.get('type', 'all')
    limit = int(request.args.get('limit', 5))
    
    if not query:
        return jsonify({
            'success': True,
            'data': {
                'users': [],
                'ideas': [],
                'colleges': [],
                'mentors': []
            },
            'query': '',
            'total': 0
        }), 200
    
    if len(query) < 2:
        return jsonify({'error': 'Query must be at least 2 characters'}), 400
    
    results = {
        'users': [],
        'ideas': [],
        'colleges': [],
        'mentors': []
    }
    
    # Build regex for case-insensitive search
    regex_pattern = {'$regex': query, '$options': 'i'}
    
    # ====================================================================
    # 1. SEARCH USERS
    # ====================================================================
    if search_type in ['all', 'users']:
        user_query = {
            'isDeleted': {'$ne': True}
        }
        
        # Role-based filtering
        if caller_role in ['innovator', 'individual_innovator']:
            # Innovators can only see mentors and team members
            user_query['$and'] = [
                {
                    '$or': [
                        {'name': regex_pattern},
                        {'email': regex_pattern}
                    ]
                },
                {'role': {'$in': ['internal_mentor', 'mentor', 'team_member']}}
            ]
        elif caller_role == 'ttc_coordinator':
            # TTC can see users they created OR from their college
            ttc = users_coll.find_one({'_id': caller_id}, {'collegeId': 1})
            user_query['$and'] = [
                {
                    '$or': [
                        {'name': regex_pattern},
                        {'email': regex_pattern}
                    ]
                },
                {
                    '$or': [
                        {'createdBy': caller_id},
                        {'collegeId': ttc.get('collegeId')} if ttc and ttc.get('collegeId') else {}
                    ]
                }
            ]
        elif caller_role == 'college_admin':
            # College admin sees ALL users from their college
            user_query['$and'] = [
                {
                    '$or': [
                        {'name': regex_pattern},
                        {'email': regex_pattern}
                    ]
                },
                {'collegeId': caller_id}
            ]
        else:
            # Super admin - see all
            user_query['$or'] = [
                {'name': regex_pattern},
                {'email': regex_pattern}
            ]
        
        users_cursor = users_coll.find(
            user_query,
            {'password': 0}  # Only exclude password
        ).limit(limit)
        
        results['users'] = [clean_doc(user) for user in users_cursor]
    
    # ====================================================================
    # 2. SEARCH IDEAS
    # ====================================================================
    if search_type in ['all', 'ideas']:
        idea_query = {
            'isDeleted': {'$ne': True}
        }
        
        search_conditions = [
            {'title': regex_pattern},
            {'concept': regex_pattern},
            {'domain': regex_pattern}
        ]
        
        # Role-based filtering
        if caller_role in ['innovator', 'individual_innovator']:
            # Innovators see their own ideas + shared ideas
            idea_query['$and'] = [
                {'$or': search_conditions},
                {
                    '$or': [
                        {'innovatorId': caller_id},
                        {'sharedWith': caller_id}
                    ]
                }
            ]
        elif caller_role == 'ttc_coordinator':
            # TTC sees ideas from their innovators
            innovator_ids = list(users_coll.distinct(
                '_id',
                {'createdBy': caller_id, 'role': {'$in': ['innovator', 'individual_innovator']}}
            ))
            idea_query['$and'] = [
                {'$or': search_conditions},
                {'innovatorId': {'$in': innovator_ids}}
            ]
        elif caller_role == 'college_admin':
            # College admin sees ideas from their college
            innovator_ids = list(users_coll.distinct(
                '_id',
                {'collegeId': caller_id, 'role': {'$in': ['innovator', 'individual_innovator']}}
            ))
            idea_query['$and'] = [
                {'$or': search_conditions},
                {'innovatorId': {'$in': innovator_ids}}
            ]
        elif caller_role in ['internal_mentor', 'mentor']:
            # Mentors see ideas they're mentoring
            idea_query['$and'] = [
                {'$or': search_conditions},
                {'mentorId': caller_id}
            ]
        else:
            # Super admin sees all
            idea_query['$or'] = search_conditions
        
        ideas_cursor = ideas_coll.find(idea_query).sort('submittedAt', -1).limit(limit)
        
        ideas_list = []
        for idea in ideas_cursor:
            idea_doc = clean_doc(idea)
            # Enrich with innovator name
            innovator = users_coll.find_one(
                {'_id': idea.get('innovatorId')},
                {'name': 1}
            )
            if innovator:
                idea_doc['innovatorName'] = innovator.get('name')
            ideas_list.append(idea_doc)
        
        results['ideas'] = ideas_list
    
    # ====================================================================
    # 3. SEARCH COLLEGES
    # ====================================================================
    if search_type in ['all', 'colleges'] and caller_role in ['super_admin', 'college_admin']:
        college_query = {
            'role': 'college_admin',
            'isDeleted': {'$ne': True},
            '$or': [
                {'collegeName': regex_pattern},
                {'email': regex_pattern}
            ]
        }
        
        colleges_cursor = users_coll.find(
            college_query,
            {'password': 0}  # Only exclude password
        ).limit(limit)
        
        results['colleges'] = [clean_doc(college) for college in colleges_cursor]
    
    # ====================================================================
    # 4. SEARCH MENTORS
    # ====================================================================
    if search_type in ['all', 'mentors']:
        mentor_query = {
            'role': {'$in': ['internal_mentor', 'mentor']},
            'isDeleted': {'$ne': True},
            'isActive': True
        }
        
        search_conditions = [
            {'name': regex_pattern},
            {'email': regex_pattern},
            {'expertise': regex_pattern},
            {'organization': regex_pattern}
        ]
        
        # Role-based filtering for internal mentors
        if caller_role in ['innovator', 'individual_innovator']:
            # Show internal mentors from same TTC
            innovator = users_coll.find_one({'_id': caller_id}, {'ttcCoordinatorId': 1})
            if innovator and innovator.get('ttcCoordinatorId'):
                mentor_query['$and'] = [
                    {'$or': search_conditions},
                    {'ttcCoordinatorId': innovator['ttcCoordinatorId']}
                ]
            else:
                mentor_query['$or'] = search_conditions
        elif caller_role == 'ttc_coordinator':
            # Show mentors created by this TTC
            mentor_query['$and'] = [
                {'$or': search_conditions},
                {'ttcCoordinatorId': caller_id}
            ]
        elif caller_role == 'college_admin':
            # Show mentors from their college
            mentor_query['$and'] = [
                {'$or': search_conditions},
                {'collegeId': caller_id}
            ]
        else:
            # Super admin sees all
            mentor_query['$or'] = search_conditions
        
        mentors_cursor = users_coll.find(
            mentor_query,
            {'password': 0}  # Only exclude password
        ).limit(limit)
        
        results['mentors'] = [clean_doc(mentor) for mentor in mentors_cursor]
    
    # Calculate total results
    total = sum(len(results[key]) for key in results)
    
    return jsonify({
        'success': True,
        'data': results,
        'query': query,
        'total': total,
        'searchType': search_type
    }), 200


@search_bp.route('/suggestions', methods=['GET'])
@requires_auth()
def search_suggestions():
    """
    Quick search suggestions (autocomplete)
    Query params:
    - q: search query
    - limit: max suggestions (default: 5)
    """
    query = request.args.get('q', '').strip()
    limit = int(request.args.get('limit', 5))
    
    if len(query) < 2:
        return jsonify({'success': True, 'suggestions': []}), 200
    
    regex_pattern = {'$regex': f'^{query}', '$options': 'i'}
    
    suggestions = []
    
    # Get user name suggestions
    users = users_coll.find(
        {'name': regex_pattern, 'isDeleted': {'$ne': True}},
        {'name': 1, 'role': 1}
    ).limit(limit)
    
    for user in users:
        suggestions.append({
            'type': 'user',
            'label': user.get('name'),
            'value': user['_id'],
            'role': user.get('role')
        })
    
    # Get idea title suggestions
    ideas = ideas_coll.find(
        {'title': regex_pattern, 'isDeleted': {'$ne': True}},
        {'title': 1}
    ).limit(limit)
    
    for idea in ideas:
        suggestions.append({
            'type': 'idea',
            'label': idea.get('title'),
            'value': idea['_id']
        })
    
    return jsonify({
        'success': True,
        'suggestions': suggestions[:limit]
    }), 200
