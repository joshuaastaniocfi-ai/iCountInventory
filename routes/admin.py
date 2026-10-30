# Standard library imports
from datetime import datetime
from zoneinfo import ZoneInfo
from urllib.parse import urlparse, parse_qs, urlencode, urlunparse

# Third-party imports
from flask import Blueprint, render_template, request, redirect, url_for, flash, session
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
    role_filter = request.args.get('role', '').strip()
    status_filter = request.args.get('status', '').strip()
    company_filter = request.args.get('company_id', '').strip()

    # For SYS-Admin users with null company_id, show all users across all companies
    # For Company-Admin and other admins, show only users in their company
    if current_user.role == 'SYS-Admin' and current_user.company_id is None:
        base_query = User.query
    else:
        base_query = User.query.filter_by(company_id=current_user.company_id)

    # Compute overview stats across the base scope before filters are applied
    base_users = base_query.all()
    stats = {
        'total': len(base_users),
        'sys_admin': sum(1 for u in base_users if u.role == 'SYS-Admin'),
        'company_admin': sum(1 for u in base_users if u.role == 'Company-Admin'),
        'wh_admin': sum(1 for u in base_users if u.role == 'WH-Admin'),
        'purchaser': sum(1 for u in base_users if u.role == 'Purchaser'),
        'regular': sum(1 for u in base_users if u.role == 'User'),
        'unverified': sum(1 for u in base_users if not u.email_verified),
        'banned': sum(1 for u in base_users if getattr(u, 'is_banned', False)),
    }

    query = base_query
    if search:
        like = f"%{search}%"
        query = query.filter(db.or_(
            User.full_name.ilike(like),
            User.username.ilike(like),
            User.email.ilike(like),
            User.branch.ilike(like),
            User.role.ilike(like)
        ))

    if role_filter:
        if role_filter.lower() == 'admins':
            query = query.filter(User.role.in_(['SYS-Admin', 'Company-Admin']))
        else:
            query = query.filter(User.role == role_filter)

    if status_filter:
        if status_filter.lower() == 'banned':
            query = query.filter(User.is_banned == True)
        elif status_filter.lower() == 'unverified':
            query = query.filter(User.email_verified == False)
        elif status_filter.lower() == 'verified':
            query = query.filter(User.email_verified == True, User.is_banned == False)

    if company_filter and current_user.role == 'SYS-Admin' and current_user.company_id is None:
        try:
            cid = int(company_filter)
            query = query.filter(User.company_id == cid)
        except ValueError:
            pass

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
    total_pages = (total_users + per_page - 1) // per_page if total_users > 0 else 1
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

    current_filters = {}
    if search:
        current_filters['q'] = search
    if role_filter:
        current_filters['role'] = role_filter
    if status_filter:
        current_filters['status'] = status_filter
    if company_filter:
        current_filters['company_id'] = company_filter

    ph_time = datetime.now(ZoneInfo("Asia/Manila"))

    return render_template(
        'admin/admin_users.html',
        current_admin=current_admin,
        users=paginated_users,
        pagination=pagination,
        search=search,
        current_filters=current_filters,
        now=ph_time,
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
    user = User.query.get_or_404(user_id)

    # Permission check: SYS-Admin, or Company-Admin within company, or self
    if current_user.role == 'SYS-Admin':
        pass
    elif current_user.role == 'Company-Admin':
        if user.company_id != current_user.company_id and user.id != current_user.id:
            flash("You don't have permission to update usernames in other companies.", 'warning')
            return redirect(url_for('admin.admin_users'))
    elif current_user.id == user_id:
        pass
    else:
        flash("You don't have permission to update usernames.", 'warning')
        return redirect(url_for('admin.admin_users'))

    new_username = request.form.get('username', '').strip()
    if not new_username:
        flash('Username is required.', 'error')
        return redirect(url_for('admin.admin_users'))

    # Check if username is already taken by another user
    existing_user = User.query.filter_by(username=new_username).first()
    if existing_user and existing_user.id != user_id:
        flash(f'Username "{new_username}" is already in use by another user.', 'error')
        return redirect(url_for('admin.admin_users'))

    old_username = user.username
    user.username = new_username
    db.session.commit()

    log_activity('Update Username', f"Updated username for <strong>{old_username}</strong> to <strong>{new_username}</strong>.")
    flash(f'Username updated to "{new_username}" successfully.', 'success')
    return redirect(url_for('admin.admin_users'))


@admin.route('/users/<int:user_id>/password', methods=['POST'])
@login_required
@user_redirect_to_requisition
@edit_delete_required
def admin_update_password(user_id):
    user = User.query.get_or_404(user_id)

    # Permission check: SYS-Admin, or Company-Admin within company, or self
    if current_user.role == 'SYS-Admin':
        pass
    elif current_user.role == 'Company-Admin':
        if user.company_id != current_user.company_id and user.id != current_user.id:
            flash("You don't have permission to change passwords in other companies.", 'warning')
            return redirect(url_for('admin.admin_users'))
    elif current_user.id == user_id:
        pass
    else:
        flash("You don't have permission to change passwords.", 'warning')
        return redirect(url_for('admin.admin_users'))

    new_password = request.form.get('password', '').strip()
    if not new_password:
        flash('Password cannot be empty.', 'error')
        return redirect(url_for('admin.admin_users'))

    if len(new_password) < 6:
        flash('Password must be at least 6 characters long.', 'error')
        return redirect(url_for('admin.admin_users'))

    user.set_password(new_password)
    db.session.commit()

    log_activity('Update Password', f"Changed password for user <strong>{user.username}</strong>.")
    flash(f'Password updated successfully for {user.username}.', 'success')
    return redirect(url_for('admin.admin_users'))


@admin.route('/users/<int:user_id>/email', methods=['POST'])
@login_required
@user_redirect_to_requisition
@edit_delete_required
def admin_update_email(user_id):
    user = User.query.get_or_404(user_id)

    # Permission check: SYS-Admin, or Company-Admin within company, or self
    if current_user.role == 'SYS-Admin':
        pass
    elif current_user.role == 'Company-Admin':
        if user.company_id != current_user.company_id and user.id != current_user.id:
            flash("You don't have permission to update email addresses in other companies.", 'warning')
            return redirect(url_for('admin.admin_users'))
    elif current_user.id == user_id:
        pass
    else:
        flash("You don't have permission to update email addresses.", 'warning')
        return redirect(url_for('admin.admin_users'))

    new_email = request.form.get('email', '').strip()
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


@admin.route('/users/<int:user_id>/toggle_ban', methods=['POST'])
@login_required
@user_redirect_to_requisition
@edit_delete_required
def admin_toggle_ban(user_id):
    # Allow SYS-Admin and Company-Admin to toggle ban
    if current_user.role not in ['SYS-Admin', 'Company-Admin']:
        flash("You don't have permission to ban or unban users.", 'warning')
        return redirect(url_for('admin.admin_users'))

    # Prevent users from banning themselves
    if current_user.id == user_id:
        flash("You cannot ban your own account.", 'warning')
        return redirect(url_for('admin.admin_users'))

    user = User.query.get_or_404(user_id)

    # SYS-Admin accounts cannot be banned unless by another SYS-Admin
    if user.role == 'SYS-Admin' and current_user.role != 'SYS-Admin':
        flash("You do not have permission to ban a SYS-Admin account.", 'error')
        return redirect(url_for('admin.admin_users'))

    # For Company-Admin, ensure they can only modify users in their company
    if current_user.role == 'Company-Admin' and user.company_id != current_user.company_id:
        flash("You don't have permission to modify users in other companies.", 'warning')
        return redirect(url_for('admin.admin_users'))

    was_banned = getattr(user, 'is_banned', False)
    user.is_banned = not was_banned
    db.session.commit()

    action_label = "Unbanned" if was_banned else "Banned"
    log_activity(f"{action_label} User", f"Admin {current_user.username} {action_label.lower()} user <strong>{user.username}</strong> ({user.full_name}).")
    flash(f"User {user.username} has been {action_label.lower()} successfully.", 'success')
    return redirect(url_for('admin.admin_users'))


@admin.route('/users/<int:user_id>/companies', methods=['POST'])
@login_required
@user_redirect_to_requisition
@edit_delete_required
def admin_update_user_companies(user_id):
    # Only SYS-Admin can assign companies to users
    if current_user.role != 'SYS-Admin':
        flash("You don't have permission to modify user company assignments.", 'warning')
        return redirect(url_for('admin.admin_users'))
    
    user = User.query.get_or_404(user_id)
    
    company_ids = request.form.getlist('company_ids')
    primary_company_id = request.form.get('primary_company_id')
    
    selected_companies = []
    if company_ids:
        for cid in company_ids:
            try:
                c = Company.query.get(int(cid))
                if c and c not in selected_companies:
                    selected_companies.append(c)
            except (ValueError, TypeError):
                continue
    
    user.handled_companies = selected_companies
    
    if selected_companies:
        if primary_company_id:
            try:
                pid = int(primary_company_id)
                if any(c.id == pid for c in selected_companies):
                    user.company_id = pid
                else:
                    user.company_id = selected_companies[0].id
            except (ValueError, TypeError):
                user.company_id = selected_companies[0].id
        elif user.company_id not in [c.id for c in selected_companies]:
            user.company_id = selected_companies[0].id
    else:
        if user.role == 'SYS-Admin':
            user.company_id = None
        else:
            flash("Non-SYS-Admin users must be assigned to at least one company/warehouse.", "warning")
            return redirect(url_for('admin.admin_users'))
            
    db.session.commit()
    
    comp_names = ", ".join([c.franchise_name or c.name for c in selected_companies]) or "None"
    log_activity('Update User Companies', f"Updated warehouses handled for <strong>{user.username}</strong> ({user.full_name}): <strong>{comp_names}</strong>.")
    flash(f"Updated warehouses handled for {user.full_name}: {comp_names}.", 'success')
    return redirect(url_for('admin.admin_users'))


@admin.route('/switch_company/<int:company_id>', methods=['POST', 'GET'])
@login_required
def switch_company(company_id):
    company = Company.query.get_or_404(company_id)
    if current_user.role != 'SYS-Admin' and company_id not in current_user.all_company_ids:
        flash("You do not have access to this company/warehouse.", "error")
        return redirect(request.referrer or url_for('main.dashboard'))
    
    current_user.company_id = company_id
    db.session.commit()
    session['active_company_id'] = company_id
    flash(f"Switched active warehouse to {company.franchise_name or company.name}.", "success")

    ref = request.referrer
    if ref:
        parsed = urlparse(ref)
        qs = parse_qs(parsed.query)
        if 'company_id' in qs:
            qs['company_id'] = [str(company_id)]
            new_query = urlencode(qs, doseq=True)
            ref = urlunparse((parsed.scheme, parsed.netloc, parsed.path, parsed.params, new_query, parsed.fragment))
        return redirect(ref)

    return redirect(url_for('main.dashboard'))


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
        
        # Check for multiple company IDs
        company_ids = request.form.getlist('company_ids')
        selected_comps = []
        if company_ids:
            for cid in company_ids:
                try:
                    c = Company.query.get(int(cid))
                    if c and c not in selected_comps:
                        selected_comps.append(c)
                except (ValueError, TypeError):
                    continue

        # Special handling for SYS-Admin users
        if role == 'SYS-Admin':
            new_user.company_id = None
            if selected_comps:
                new_user.handled_companies = selected_comps
        else:
            if selected_comps:
                new_user.handled_companies = selected_comps
                new_user.company_id = selected_comps[0].id
            elif company_id:
                company = Company.query.get(company_id)
                if not company:
                    flash('Invalid company selected', 'error')
                    return redirect(url_for('admin.admin_users'))
                new_user.company_id = company_id
                new_user.handled_companies = [company]
            else:
                new_user.company_id = current_user.company_id
                if current_user.company:
                    new_user.handled_companies = [current_user.company]

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