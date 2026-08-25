# Standard library imports
from datetime import datetime

# Third-party imports
from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_required, current_user

# Local imports
from extensions import db
from models import User, ActivityLog, Company
from helpers import user_redirect_to_requisition, admin_required, sys_admin_required, edit_delete_required, log_activity

# Create blueprint with URL prefix as required by project specifications
admin = Blueprint('admin', __name__, url_prefix='/admin')


@admin.route('/users')
@login_required
@user_redirect_to_requisition
@admin_required
def admin_users():
    page = request.args.get('page', 1, type=int)
    per_page = 10
    search = request.args.get('q', '').strip()

    # For SYS-Admin users with null company_id, show all users across all companies
    # For Company-Admin and other admins, show only users in their company
    if current_user.role == 'SYS-Admin' and current_user.company_id is None:
        query = User.query
    else:
        query = User.query.filter_by(company_id=current_user.company_id)
        
    if search:
        like = f"%{search}%"
        query = query.filter(db.or_(
            User.full_name.ilike(like),
            User.username.ilike(like),
            User.email.ilike(like),
            User.branch.ilike(like),
            User.role.ilike(like)
        ))

    all_users = query.all()

    # Separate current admin and other users
    current_admin = None
    other_users = []

    for user in all_users:
        if user.id == current_user.id:
            current_admin = user
        else:
            other_users.append(user)

    # Sort other users alphabetically by full name
    other_users.sort(key=lambda x: x.full_name.lower())

    # Pagination logic
    total_users = len(other_users)
    total_pages = (total_users + per_page - 1) // per_page  # Ceiling division
    if page < 1:
        page = 1
    elif page > total_pages and total_pages > 0:
        page = total_pages

    start_idx = (page - 1) * per_page
    end_idx = start_idx + per_page
    paginated_users = other_users[start_idx:end_idx]

    pagination = type('Pagination', (), {
        'items': paginated_users,
        'page': page,
        'per_page': per_page,
        'total': total_users,
        'pages': total_pages,
        'has_prev': page > 1,
        'has_next': page < total_pages,
        'prev_num': page - 1 if page > 1 else None,
        'next_num': page + 1 if page < total_pages else None
    })()

    # Stats for the overview cards (computed over the full visible set)
    stats = {
        'total': len(all_users),
        'sys_admin': sum(1 for u in all_users if u.role == 'SYS-Admin'),
        'company_admin': sum(1 for u in all_users if u.role == 'Company-Admin'),
        'wh_admin': sum(1 for u in all_users if u.role == 'WH-Admin'),
        'purchaser': sum(1 for u in all_users if u.role == 'Purchaser'),
        'regular': sum(1 for u in all_users if u.role == 'User'),
        'unverified': sum(1 for u in all_users if not u.email_verified),
    }

    return render_template(
        'admin/admin_users.html',
        current_admin=current_admin,
        users=paginated_users,
        pagination=pagination,
        search=search,
        companies=Company.query.all(),
        stats=stats
    )


@admin.route('/users/<int:user_id>/role', methods=['POST'])
@login_required
@user_redirect_to_requisition
@edit_delete_required
def admin_update_role(user_id):
    # Allow SYS-Admin and Company-Admin to update roles
    # Company-Admin can only update roles of users in their company
    if current_user.role not in ['SYS-Admin', 'Company-Admin']:
        flash("You don't have permission to change user roles.", 'warning')
        return redirect(url_for('admin.admin_users'))
    
    # Prevent users from changing their own role
    if current_user.id == user_id:
        flash("You cannot change your own role.", 'warning')
        return redirect(url_for('admin.admin_users'))

    user = User.query.get_or_404(user_id)
    
    # For Company-Admin, ensure they can only modify users in their company
    if current_user.role == 'Company-Admin' and user.company_id != current_user.company_id:
        flash("You don't have permission to change roles for users in other companies.", 'warning')
        return redirect(url_for('admin.admin_users'))

    new_role = request.form.get('role')
    if not new_role or new_role not in ('User', 'WH-Admin', 'SYS-Admin', 'Purchaser', 'Company-Admin'):
        flash('Invalid role selected.', 'error')
        return redirect(url_for('admin.admin_users'))

    old_role = user.role
    user.role = new_role
    db.session.commit()

    log_activity('Change User Role', f"Changed role for <strong>{user.username}</strong> from <strong>{old_role}</strong> to <strong>{new_role}</strong>.")
    flash('User role updated.', 'success')
    return redirect(url_for('admin.admin_users'))


@admin.route('/users/<int:user_id>/username', methods=['POST'])
@login_required
@user_redirect_to_requisition
@edit_delete_required
def admin_update_username(user_id):
    # Only allow admins to update their own username
    if current_user.id != user_id:
        flash("You can only update your own username.", 'warning')
        return redirect(url_for('admin.admin_users'))

    user = User.query.get_or_404(user_id)
    new_username = request.form.get('username')

    if not new_username:
        flash('Username is required.', 'error')
        return redirect(url_for('admin.admin_users'))

    # Check if username is already taken by another user
    existing_user = User.query.filter_by(username=new_username).first()
    if existing_user and existing_user.id != user_id:
        flash('Username is already in use by another user.', 'error')
        return redirect(url_for('admin.admin_users'))

    old_username = user.username
    user.username = new_username
    db.session.commit()

    log_activity('Update Username', f"Updated username for <strong>{old_username}</strong> to <strong>{new_username}</strong>.")
    flash('Username updated successfully.', 'success')
    return redirect(url_for('admin.admin_users'))


@admin.route('/users/<int:user_id>/email', methods=['POST'])
@login_required
@user_redirect_to_requisition
@edit_delete_required
def admin_update_email(user_id):
    # Only allow admins to update their own email
    if current_user.id != user_id:
        flash("You can only update your own email address.", 'warning')
        return redirect(url_for('admin.admin_users'))

    user = User.query.get_or_404(user_id)
    new_email = request.form.get('email')

    if not new_email:
        flash('Email address is required.', 'error')
        return redirect(url_for('admin.admin_users'))

    # Check if email is already taken by another user
    existing_user = User.query.filter_by(email=new_email).first()
    if existing_user and existing_user.id != user_id:
        flash('Email address is already in use by another user.', 'error')
        return redirect(url_for('admin.admin_users'))

    old_email = user.email
    user.email = new_email
    db.session.commit()

    log_activity('Update Email', f"Updated email for <strong>{user.username}</strong> from <strong>{old_email}</strong> to <strong>{new_email}</strong>.")
    flash('Email address updated successfully.', 'success')
    return redirect(url_for('admin.admin_users'))


@admin.route('/users/<int:user_id>/delete', methods=['POST'])
@login_required
@user_redirect_to_requisition
@edit_delete_required
def admin_delete_user(user_id):
    # Allow SYS-Admin and Company-Admin to delete users
    # Company-Admin can only delete users in their company
    if current_user.role not in ['SYS-Admin', 'Company-Admin']:
        flash("You don't have permission to delete users.", 'warning')
        return redirect(url_for('admin.admin_users'))
    
    # Prevent users from deleting their own account
    if current_user.id == user_id:
        flash('You cannot delete your own account.', 'warning')
        return redirect(url_for('admin.admin_users'))

    user = User.query.get_or_404(user_id)
    
    # For Company-Admin, ensure they can only delete users in their company
    if current_user.role == 'Company-Admin' and user.company_id != current_user.company_id:
        flash("You don't have permission to delete users in other companies.", 'warning')
        return redirect(url_for('admin.admin_users'))

    username = user.username
    db.session.delete(user)
    db.session.commit()

    log_activity('Delete User', f"Deleted user account <strong>{username}</strong>.")
    flash('User account deleted.', 'success')
    return redirect(url_for('admin.admin_users'))


@admin.route('/add_user', methods=['POST'])
@login_required
@edit_delete_required
def add_user():
    """Add a new user"""
    try:
        full_name = request.form['full_name'].strip()
        username = request.form['username'].strip()
        email = request.form['email'].strip()
        branch = request.form['branch'].strip()
        role = request.form['role']
        password = request.form['password']
        company_id = request.form.get('company_id')  # Get company_id if provided

        # Validate required fields
        if not all([full_name, username, email, branch, role, password]):
            flash('All fields are required', 'error')
            return redirect(url_for('admin.admin_users'))

        # Check if username or email already exists
        existing_user = User.query.filter(
            db.or_(
                User.username == username,
                User.email == email
            )
        ).first()
        
        if existing_user:
            if existing_user.username == username:
                flash('Username already exists', 'error')
            else:
                flash('Email already exists', 'error')
            return redirect(url_for('admin.admin_users'))

        # Create new user
        new_user = User(
            full_name=full_name,
            username=username,
            email=email,
            branch=branch,
            role=role
        )
        
        # Special handling for SYS-Admin users
        if role == 'SYS-Admin':
            new_user.company_id = None  # SYS-Admin has no company affiliation
        # Company-Admin should be assigned to a company like other admins
        elif role == 'Company-Admin':
            # For Company-Admin users, assign to specified company or current user's company
            if company_id:
                # Verify company exists
                company = Company.query.get(company_id)
                if not company:
                    flash('Invalid company selected', 'error')
                    return redirect(url_for('admin.admin_users'))
                new_user.company_id = company_id
            else:
                # Assign to current user's company
                new_user.company_id = current_user.company_id
        else:
            # For non-SYS-Admin users, assign to specified company or current user's company
            if company_id:
                # Verify company exists
                company = Company.query.get(company_id)
                if not company:
                    flash('Invalid company selected', 'error')
                    return redirect(url_for('admin.admin_users'))
                new_user.company_id = company_id
            else:
                # Assign to current user's company
                new_user.company_id = current_user.company_id

        # Set password
        new_user.set_password(password)

        # Admin-created users are auto-verified
        new_user.email_verified = True

        db.session.add(new_user)
        db.session.commit()

        flash(f'User {full_name} added successfully!', 'success')
        
        # Log the activity
        log_activity(
            action="User Added",
            details=f"Added user: {full_name} ({username}) with role {role}"
        )

    except Exception as e:
        db.session.rollback()
        flash(f'Error adding user: {str(e)}', 'error')
        log_activity(
            action="User Add Error",
            details=f"Failed to add user: {str(e)}"
        )

    return redirect(url_for('admin.admin_users'))