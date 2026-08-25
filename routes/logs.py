# Standard library imports
from datetime import datetime
from zoneinfo import ZoneInfo

# Third-party imports
from flask import Blueprint, render_template, request, jsonify, flash, redirect, url_for
from flask_login import login_required, current_user

# Local imports
from extensions import db
from models import ActivityLog, Company
from helpers import user_redirect_to_requisition, sys_admin_required, admin_required, edit_delete_required

# Create blueprint with URL prefix as required by project specifications
logs = Blueprint('logs', __name__, url_prefix='/logs')


@logs.route('/activity_logs')
@login_required
@user_redirect_to_requisition
def view_logs():
    page = request.args.get('page', 1, type=int)
    per_page = 10  # Number of logs per page

    # Get all companies for SYS-Admin dropdown
    companies = []
    if current_user.role == 'SYS-Admin':
        companies = Company.query.all()

    # Build query based on filters
    # For Company-Admin and other non-SYS-Admin users, filter by company
    if current_user.role == 'SYS-Admin' and current_user.company_id is None:
        # SYS-Admin with no company can see all logs
        query = ActivityLog.query.order_by(ActivityLog.timestamp.desc())
    else:
        # Company-Admin and other admins can only see logs from their company
        query = ActivityLog.query.filter_by(company_id=current_user.company_id).order_by(ActivityLog.timestamp.desc())

    # Search filter
    search = request.args.get('q', '').strip()
    if search:
        query = query.filter(
            db.or_(
                ActivityLog.action.ilike(f'%{search}%'),
                ActivityLog.details.ilike(f'%{search}%')
            )
        )

    # Action type filter
    action = request.args.get('action', '').strip()
    if action:
        query = query.filter(ActivityLog.action == action)

    # Date filter
    date = request.args.get('date', '').strip()
    if date:
        try:
            filter_date = datetime.strptime(date, '%Y-%m-%d')
            # Create start and end of day (timezone-naive for database comparison)
            start_date = datetime.combine(filter_date.date(), datetime.min.time())
            end_date = datetime.combine(filter_date.date(), datetime.max.time())

            query = query.filter(
                ActivityLog.timestamp >= start_date,
                ActivityLog.timestamp <= end_date
            )
        except ValueError:
            pass  # Invalid date format, ignore filter

    # Company filter (only for SYS-Admin)
    company_filter = None
    if current_user.role == 'SYS-Admin':
        company_filter = request.args.get('company', '').strip()
        if company_filter:
            try:
                company_id = int(company_filter)
                query = query.filter(ActivityLog.company_id == company_id)
            except ValueError:
                pass  # Invalid company ID, ignore filter

    # Execute query with pagination
    pagination = query.paginate(page=page, per_page=per_page, error_out=False)
    logs_list = pagination.items

    # Format timestamps for display
    for log in logs_list:
        if log.timestamp:
            log.formatted_timestamp = log.timestamp.strftime('%Y-%m-%d %I:%M:%S %p')

    return render_template(
        'admin/logs.html',
        logs=logs_list,
        pagination=pagination,
        companies=companies,
        current_filters={
            'q': search,
            'action': action,
            'date': date,
            'company': company_filter
        }
    )


@logs.route('/delete_logs', methods=['POST'])
@login_required
@user_redirect_to_requisition
@edit_delete_required
def delete_logs():
    """Delete selected activity logs"""
    try:
        data = request.get_json()
        log_ids = data.get('log_ids', [])
        
        if not log_ids:
            return jsonify({'success': False, 'message': 'No logs selected for deletion'}), 400
        
        # Build query based on user role and company
        if current_user.role == 'SYS-Admin' and current_user.company_id is None:
            # SYS-Admin with no company can delete any logs
            logs_query = ActivityLog.query.filter(ActivityLog.id.in_(log_ids))
        else:
            # Company-Admin and other admins can only delete logs from their company
            logs_query = ActivityLog.query.filter(
                ActivityLog.id.in_(log_ids),
                ActivityLog.company_id == current_user.company_id
            )
        
        # Delete the selected logs
        deleted_count = logs_query.delete(synchronize_session=False)
        db.session.commit()
        
        flash(f'Successfully deleted {deleted_count} activity log(s)', 'success')
        return jsonify({
            'success': True, 
            'message': f'Successfully deleted {deleted_count} activity log(s)',
            'deleted_count': deleted_count
        })
        
    except Exception as e:
        db.session.rollback()
        flash(f'Error deleting logs: {str(e)}', 'error')
        return jsonify({'success': False, 'message': f'Error deleting logs: {str(e)}'}), 500


@logs.route('/delete_all_logs', methods=['POST'])
@login_required
@user_redirect_to_requisition
@edit_delete_required
def delete_all_logs():
    """Delete all activity logs"""
    try:
        # Get current filters to apply the same deletion criteria
        search = request.form.get('q', '').strip()
        action = request.form.get('action', '').strip()
        date = request.form.get('date', '').strip()
        
        # Build query based on current filters and user role/company
        if current_user.role == 'SYS-Admin' and current_user.company_id is None:
            # SYS-Admin with no company can delete any logs
            query = ActivityLog.query
        else:
            # Company-Admin and other admins can only delete logs from their company
            query = ActivityLog.query.filter(ActivityLog.company_id == current_user.company_id)
        
        if search:
            query = query.filter(
                db.or_(
                    ActivityLog.action.ilike(f'%{search}%'),
                    ActivityLog.details.ilike(f'%{search}%')
                )
            )
        
        if action:
            query = query.filter(ActivityLog.action == action)
            
        if date:
            try:
                filter_date = datetime.strptime(date, '%Y-%m-%d')
                start_date = datetime.combine(filter_date.date(), datetime.min.time())
                end_date = datetime.combine(filter_date.date(), datetime.max.time())
                query = query.filter(
                    ActivityLog.timestamp >= start_date,
                    ActivityLog.timestamp <= end_date
                )
            except ValueError:
                pass
        
        # Delete all filtered logs
        deleted_count = query.delete(synchronize_session=False)
        db.session.commit()
        
        flash(f'Successfully deleted {deleted_count} activity log(s)', 'success')
        return redirect(url_for('logs.view_logs'))
        
    except Exception as e:
        db.session.rollback()
        flash(f'Error deleting all logs: {str(e)}', 'error')
        return redirect(url_for('logs.view_logs'))