"""
Automated Fix Script for Pragati API Authorization Issues
Fixes:
1. Missing parentheses on @requires_auth decorators
2. Missing 'individual_innovator' role in @requires_role decorators
3. Adds super_admin bypass logic to manual authorization checks
"""

import re
import os
from pathlib import Path

def fix_requires_auth_parentheses(content):
    """
    Fix @requires_auth without parentheses -> @requires_auth()
    """
    # Pattern: @requires_auth followed by newline (not @requires_auth())
    pattern = r'@requires_auth(?!\()'
    replacement = r'@requires_auth()'

    fixed_content = re.sub(pattern, replacement, content)

    count = len(re.findall(pattern, content))
    return fixed_content, count

def add_individual_innovator_role(content):
    """
    Add 'individual_innovator' to @requires_role(['innovator']) lists
    """
    changes = 0

    # Pattern 1: @requires_role(['innovator']) without individual_innovator
    pattern1 = r"""@requires_role\(\[\s*['"]innovator['"]\s*\]\)"""
    if re.search(pattern1, content):
        content = re.sub(
            pattern1,
            "@requires_role(['innovator', 'individual_innovator'])",
            content
        )
        changes += len(re.findall(pattern1, content))

    # Pattern 2: @requires_role(["innovator"]) with double quotes
    pattern2 = r'@requires_role\(\[\s*"innovator"\s*\]\)'
    if re.search(pattern2, content):
        content = re.sub(
            pattern2,
            '@requires_role(["innovator", "individual_innovator"])',
            content
        )
        changes += len(re.findall(pattern2, content))

    # Pattern 3: Multi-role lists that include innovator but not individual_innovator
    # Example: ['innovator', 'ttc_coordinator'] -> ['innovator', 'individual_innovator', 'ttc_coordinator']
    pattern3 = r"""@requires_role\(\[([^\]]*['"]innovator['"][^\]]*)\]\)"""
    matches = re.finditer(pattern3, content)

    for match in matches:
        role_list = match.group(1)
        # Check if individual_innovator is NOT in the list
        if 'individual_innovator' not in role_list:
            # Add it after 'innovator'
            new_role_list = role_list.replace(
                "'innovator'", 
                "'innovator', 'individual_innovator'"
            ).replace(
                '"innovator"',
                '"innovator", "individual_innovator"'
            )
            content = content.replace(match.group(0), f"@requires_role([{new_role_list}])")
            changes += 1

    return content, changes

def add_super_admin_bypass(content):
    """
    Add super_admin bypass to manual authorization checks
    """
    changes = 0

    # Pattern: Functions with authorization logic that check caller_role
    # Look for: if caller_role == 'innovator': or if caller_role in ['innovator', ...]

    # Find authorization check blocks
    patterns = [
        # Pattern 1: if caller_role == 'innovator':
        (r"""(\s+)if caller_role == ['"]innovator['"]:""",
         r"\1# ✅ Super admin bypass\n\1if caller_role == 'super_admin':\n\1    pass  # Allow all operations\n\1elif caller_role in ['innovator', 'individual_innovator']:"),

        # Pattern 2: if caller_role in ['innovator', ...]
        (r"""(\s+)if caller_role in \[([^\]]*['"]innovator['"][^\]]*)\]:""",
         lambda m: f"{m.group(1)}# ✅ Super admin bypass\n{m.group(1)}if caller_role == 'super_admin':\n{m.group(1)}    pass  # Allow all operations\n{m.group(1)}elif caller_role in [{m.group(2)}]:")
    ]

    # Apply patterns cautiously - only if super_admin not already present
    for pattern, replacement in patterns:
        matches = list(re.finditer(pattern, content))
        for match in matches:
            # Check if super_admin is already in this authorization block
            # Look 10 lines above for super_admin check
            start_pos = max(0, match.start() - 500)
            context = content[start_pos:match.start()]

            if "super_admin" not in context:
                if callable(replacement):
                    content = content[:match.start()] + replacement(match) + content[match.end():]
                else:
                    content = content[:match.start()] + re.sub(pattern, replacement, match.group(0)) + content[match.end():]
                changes += 1

    return content, changes

def fix_route_conflicts_users_py(content):
    """
    Fix route conflicts in users.py
    """
    changes = 0

    # Fix: GET / with user_id parameter -> GET /<user_id>
    pattern = r"""@users_bp\.route\(['"]\/['"], methods=\[['"]GET['"]\]\)\s+@requires_auth\s+def get_user_by_id\(user_id\):"""
    if re.search(pattern, content):
        replacement = "@users_bp.route('/<user_id>', methods=['GET'])\n@requires_auth()\ndef get_user_by_id(user_id):"
        content = re.sub(pattern, replacement, content)
        changes += 1

    return content, changes

def fix_route_conflicts_ideas_py(content):
    """
    Fix route conflicts in ideas.py
    """
    changes = 0

    # Fix: /user/ -> /user/<user_id>
    pattern = r"""@ideas_bp\.route\(['"]\/user\/['"], methods=\[['"]GET['"]\]\)"""
    if re.search(pattern, content):
        replacement = "@ideas_bp.route('/user/<user_id>', methods=['GET'])"
        content = re.sub(pattern, replacement, content)
        changes += 1

    return content, changes

def process_file(filepath):
    """
    Process a single Python file
    """
    print(f"\n📄 Processing: {filepath}")

    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            original_content = f.read()

        content = original_content
        total_changes = 0

        # Apply fixes
        content, auth_changes = fix_requires_auth_parentheses(content)
        if auth_changes > 0:
            print(f"   ✅ Fixed {auth_changes} @requires_auth decorators")
            total_changes += auth_changes

        content, role_changes = add_individual_innovator_role(content)
        if role_changes > 0:
            print(f"   ✅ Added 'individual_innovator' to {role_changes} endpoints")
            total_changes += role_changes

        # File-specific fixes
        filename = os.path.basename(filepath)

        if filename == 'users.py':
            content, conflict_changes = fix_route_conflicts_users_py(content)
            if conflict_changes > 0:
                print(f"   ✅ Fixed {conflict_changes} route conflicts in users.py")
                total_changes += conflict_changes

        elif filename == 'ideas.py':
            content, conflict_changes = fix_route_conflicts_ideas_py(content)
            if conflict_changes > 0:
                print(f"   ✅ Fixed {conflict_changes} route conflicts in ideas.py")
                total_changes += conflict_changes

        # Save if changes were made
        if content != original_content:
            # Create backup
            backup_path = f"{filepath}.backup"
            with open(backup_path, 'w', encoding='utf-8') as f:
                f.write(original_content)
            print(f"   💾 Backup saved: {backup_path}")

            # Write fixed content
            with open(filepath, 'w', encoding='utf-8') as f:
                f.write(content)

            print(f"   ✅ Applied {total_changes} fixes to {filename}")
            return True
        else:
            print(f"   ℹ️  No changes needed")
            return False

    except Exception as e:
        print(f"   ❌ Error processing {filepath}: {e}")
        return False

def main():
    """
    Main function to process all route files
    """
    print("="*80)
    print("🔧 AUTOMATED FIX SCRIPT FOR PRAGATI API")
    print("="*80)

    # Define route files to process
    route_files = [
        'app/routes/ideas.py',
        'app/routes/users.py',
        'app/routes/teams.py',
        'app/routes/credits.py',
        'app/routes/mentors.py',
        'app/routes/reports.py',
        'app/routes/admin.py',
        'app/routes/coordinator.py',
        'app/routes/principal.py',
        'app/routes/psychometric.py',
        'app/routes/dashboard.py',
        'app/routes/analytics.py',
        'app/routes/audit.py',
        'app/routes/search.py',
        'app/routes/notifications.py',
    ]

    # Also fix middleware
    middleware_files = [
        'app/middleware/auth.py',
    ]

    all_files = route_files + middleware_files

    processed = 0
    modified = 0

    for filepath in all_files:
        if os.path.exists(filepath):
            if process_file(filepath):
                modified += 1
            processed += 1
        else:
            print(f"\n⚠️  File not found: {filepath}")

    print("\n" + "="*80)
    print(f"✅ PROCESSING COMPLETE")
    print(f"   Processed: {processed} files")
    print(f"   Modified: {modified} files")
    print(f"   Unchanged: {processed - modified} files")
    print("="*80)

    print("\n📋 NEXT STEPS:")
    print("1. Review the changes in each file")
    print("2. Run your test suite")
    print("3. Test super_admin and individual_innovator access")
    print("4. If issues occur, restore from .backup files")
    print("\n⚠️  IMPORTANT: All original files backed up with .backup extension")

if __name__ == '__main__':
    main()