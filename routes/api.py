# Standard library imports
import csv
import io
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

# Third-party imports
from flask import Blueprint, request, jsonify, send_file, flash, redirect, url_for, render_template
from flask_login import login_required, current_user

# Local imports
from extensions import db
from models import Product, WarehouseProductBatch, StoreProductBatch, ActivityLog, StockAudit, ProductHistory, BatchAudit, Notification
from helpers import user_redirect_to_requisition, log_activity, sys_admin_required, admin_required, is_mobile_device, get_redirect_url_for_user, assign_company, create_notification
from sqlalchemy import or_

# Create blueprint with URL prefix as required by project specifications
api = Blueprint('api', __name__, url_prefix='/api')


@api.route('/get_total_products')
@login_required
@admin_required
def get_total_products():
    """Get total number of products for audit progress tracking"""
    try:
        # Filter by company for Company-Admin users
        if current_user.role == 'SYS-Admin' and current_user.company_id is None:
            # SYS-Admin with no company can see all products
            total_products = Product.query.count()
        else:
            # Company-Admin and other admins can only see products from their company
            total_products = Product.query.filter_by(company_id=current_user.company_id).count()
        
        return jsonify({
            'success': True,
            'total_products': total_products
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@api.route('/stock_movements')
def api_stock_movements():
    """API endpoint to get stock movement data for different time periods"""
    period = request.args.get('period', 'month')
    
    # Get current time in PHT
    now = datetime.now(ZoneInfo("Asia/Manila"))
    
    # Calculate date range based on period
    if period == 'week':
        start_date = now - timedelta(days=7)
        date_format = '%a'  # Mon, Tue, Wed, etc.
    elif period == 'month':
        start_date = now - timedelta(days=30)
        date_format = '%b %d'  # Jan 01, Jan 02, etc.
    elif period == 'year':
        start_date = now - timedelta(days=365)
        date_format = '%b'  # Jan, Feb, Mar, etc.
    else:
        start_date = now - timedelta(days=30)
        date_format = '%b %d'
    
    try:
        # Get stock movements within the date range
        movements = ActivityLog.query.filter(
            ActivityLog.timestamp >= start_date,
            ActivityLog.action.in_(['Add Stock', 'Remove Stock'])
        ).order_by(ActivityLog.timestamp).all()
        
        # Group movements by date
        daily_data = {}
        current_date = start_date.date()
        
        while current_date <= now.date():
            daily_data[current_date] = {'added': 0, 'removed': 0}
            current_date += timedelta(days=1)
        
        # Process movements
        for movement in movements:
            move_date = movement.timestamp.date()
            if move_date in daily_data:
                if 'Add Stock' in movement.action:
                    # Extract quantity from movement details
                    try:
                        # Look for quantity in the details (e.g., "Added 50 units")
                        import re
                        quantity_match = re.search(r'(\d+(?:\.\d+)?)', movement.details)
                        if quantity_match:
                            quantity = float(quantity_match.group(1))
                            daily_data[move_date]['added'] += quantity
                        else:
                            daily_data[move_date]['added'] += 1  # Fallback to count if no quantity found
                    except:
                        daily_data[move_date]['added'] += 1  # Fallback to count
                elif 'Remove Stock' in movement.action:
                    # Extract quantity from movement details
                    try:
                        # Look for quantity in the details (e.g., "Removed 25 units")
                        import re
                        quantity_match = re.search(r'(\d+(?:\.\d+)?)', movement.details)
                        if quantity_match:
                            quantity = float(quantity_match.group(1))
                            daily_data[move_date]['removed'] += quantity
                        else:
                            daily_data[move_date]['removed'] += 1  # Fallback to count if no quantity found
                    except:
                        daily_data[move_date]['removed'] += 1  # Fallback to count
        
        # Prepare chart data
        labels = []
        added_data = []
        removed_data = []
        
        for date, data in daily_data.items():
            if period == 'week':
                labels.append(date.strftime('%a'))
            elif period == 'month':
                labels.append(date.strftime('%b %d'))
            else:  # year
                labels.append(date.strftime('%b'))
            
            added_data.append(data['added'])
            removed_data.append(data['removed'])
        
        return jsonify({
            'success': True,
            'labels': labels,
            'added_data': added_data,
            'removed_data': removed_data,
            'period': period
        })
        
    except Exception as e:
        return jsonify({
            'success': False,
            'message': str(e)
        }), 500


@api.route('/device-check')
def api_device_check():
    """API endpoint to check device compatibility"""
    user_agent = request.headers.get('User-Agent', '')
    is_mobile = is_mobile_device(user_agent)
    
    # Detect specific device types
    device_info = {
        'is_mobile': is_mobile,
        'user_agent': user_agent,
        'device_type': 'unknown'
    }
    
    if is_mobile:
        if 'android' in user_agent.lower():
            device_info['device_type'] = 'android'
        elif 'iphone' in user_agent.lower():
            device_info['device_type'] = 'iphone'
        elif 'ipad' in user_agent.lower():
            device_info['device_type'] = 'ipad'
        elif 'blackberry' in user_agent.lower():
            device_info['device_type'] = 'blackberry'
        elif 'windows phone' in user_agent.lower():
            device_info['device_type'] = 'windows_phone'
        else:
            device_info['device_type'] = 'mobile_other'
    
    return jsonify(device_info)


@api.route('/scanner-status')
@login_required
def api_scanner_status():
    """API endpoint to check scanner accessibility for current user"""
    user_agent = request.headers.get('User-Agent', '')
    is_mobile = is_mobile_device(user_agent)
    
    # Check user role
    if current_user.role not in ['SYS-Admin', 'WH-Admin']:
        return jsonify({
            'success': False,
            'message': 'Access denied. SYS-Admin or WH-Admin privileges required.',
            'code': 'INSUFFICIENT_PRIVILEGES'
        }), 403
    
    # Check device compatibility
    if not is_mobile:
        return jsonify({
            'success': False,
            'message': 'Scanner is only available on mobile devices.',
            'code': 'DESKTOP_NOT_SUPPORTED'
        }), 403
    
    return jsonify({
        'success': True,
        'message': 'Scanner is accessible',
        'user_role': current_user.role,
        'device_type': 'mobile',
        'scanner_url': url_for('scanner.mobile_scanner')
    })


@api.route('/expiring_products')
@login_required
def api_expiring_products():
    """API endpoint to get expiring products data for dashboard"""
    try:
        # Get view parameter (30days or 3months)
        view = request.args.get('view', '30days')
        
        # Get current time in PHT
        now = datetime.now(ZoneInfo("Asia/Manila"))
        today = now.date()
        
        # Calculate date range based on view
        if view == '3months':
            # For 3 months view, show products expiring within 90 days (but after 30 days to avoid redundancy)
            start_date = today + timedelta(days=30)
            end_date = today + timedelta(days=90)
            title = "Products Expiring in 31-90 Days"
        else:
            # For 30 days view, show products expiring within 30 days
            start_date = today
            end_date = today + timedelta(days=30)
            title = "Products Expiring in 30 Days"
        
        # Base queries based on user role
        if current_user.role == 'SYS-Admin' and current_user.company_id is None:
            # SYS-Admin with no company can see all data
            product_query = Product.query
        else:
            # Company-Admin and other admins can only see data from their company
            product_query = Product.query.filter_by(company_id=current_user.company_id)
        
        # Get expiring products
        expiring_products = product_query.join(WarehouseProductBatch).filter(
            WarehouseProductBatch.exp_date.between(start_date, end_date),
            WarehouseProductBatch.quantity > 0
        ).distinct().order_by(WarehouseProductBatch.exp_date).limit(5).all()
        
        # Format products data for JSON response
        products_data = []
        for product in expiring_products:
            # Get the earliest expiring batch for this product within the date range
            earliest_batch = min(
                [batch for batch in product.warehouse_batches 
                 if batch.exp_date >= start_date and batch.exp_date <= end_date and batch.quantity > 0],
                key=lambda x: x.exp_date
            )
            
            # Get expiring batches (limit to 3 for display)
            expiring_batches = [
                batch for batch in product.warehouse_batches 
                if batch.exp_date >= start_date and batch.exp_date <= end_date and batch.quantity > 0
            ][:3]
            
            products_data.append({
                'id': product.id,
                'name': product.name,
                'barcode': product.barcode,
                'company_id': product.company_id,
                'uom': product.uom,
                'quantity': product.quantity,
                'earliest_exp_date': earliest_batch.exp_date.strftime('%Y-%m-%d'),
                'days_left': (earliest_batch.exp_date - today).days,
                'expiring_batches': [
                    {
                        'quantity': batch.quantity,
                        'exp_date': batch.exp_date.strftime('%Y-%m-%d'),
                        'days_until': (batch.exp_date - today).days
                    }
                    for batch in expiring_batches
                ],
                'total_expiring_batches': len([
                    batch for batch in product.warehouse_batches 
                    if batch.exp_date >= start_date and batch.exp_date <= end_date and batch.quantity > 0
                ])
            })
        
        return jsonify({
            'success': True,
            'title': title,
            'products': products_data,
            'count': len(products_data),
            'view': view
        })
        
    except Exception as e:
        return jsonify({
            'success': False,
            'message': str(e)
        }), 500


@api.route('/check-redirect')
def api_check_redirect():
    """API endpoint to check what redirect URL a user would get"""
    user_agent = request.headers.get('User-Agent', '')
    is_mobile = is_mobile_device(user_agent)
    
    # Check if user is logged in
    if current_user.is_authenticated:
        redirect_url = get_redirect_url_for_user(current_user, user_agent)
        return jsonify({
            'success': True,
            'user_role': current_user.role,
            'is_mobile': is_mobile,
            'redirect_url': redirect_url,
            'redirect_route': redirect_url.split('/')[-1] if redirect_url else None
        })
    else:
        return jsonify({
            'success': False,
            'message': 'User not logged in',
            'is_mobile': is_mobile,
            'user_agent': user_agent[:100] + '...' if len(user_agent) > 100 else user_agent
        })


@api.route('/stock_audit')
@login_required
@user_redirect_to_requisition
def stock_audit():
    # Filter products by company for Company-Admin users
    if current_user.role == 'SYS-Admin' and current_user.company_id is None:
        # SYS-Admin with no company can see all products
        products = Product.query.order_by(Product.name).all()
    else:
        # Company-Admin and other admins can only see products from their company
        products = Product.query.filter_by(company_id=current_user.company_id).order_by(Product.name).all()
    return render_template('warehouse/stock_audit.html', products=products)


@api.route('/count_inventory_data')
@login_required
@user_redirect_to_requisition
def count_inventory_data():
    """Return all products with system quantities for the daily inventory count form."""
    if current_user.role == 'SYS-Admin' and current_user.company_id is None:
        products = Product.query.order_by(Product.name).all()
    else:
        products = Product.query.filter_by(company_id=current_user.company_id).order_by(Product.name).all()

    data = []
    for p in products:
        data.append({
            'id': p.id,
            'name': p.name,
            'uom': p.uom,
            'system_qty': p.quantity,
            'account_title': p.account_title
        })
    return jsonify({'success': True, 'products': data, 'count': len(data)})


@api.route('/submit_audit', methods=['POST'])
@login_required
@user_redirect_to_requisition
def submit_audit():
    data = request.get_json()
    audits = data.get('audits', [])
    verified_by = data.get('verified_by', 'Unknown')

    if not audits:
        return {'status': 'error', 'message': 'No audits provided.'}, 400

    batch_label = f"AUDIT-{datetime.utcnow().strftime('%Y%m%d-%H%M%S')}"

    for entry in audits:
        product_id = entry.get('product_id')
        recorded_qty = entry.get('recorded_quantity')
        actual_qty = entry.get('actual_quantity')

        if None in (product_id, recorded_qty, actual_qty):
            continue

        discrepancy = actual_qty - recorded_qty

        audit = StockAudit(
            product_id=product_id,
            recorded_quantity=recorded_qty,
            actual_quantity=actual_qty,
            discrepancy=discrepancy,
            verified_by=verified_by,
            batch_label=batch_label
        )
        
        # Assign company to the audit record
        # First try to get company_id from the product
        product = Product.query.get(product_id)
        if product and product.company_id:
            audit.company_id = product.company_id
        # If product doesn't have company_id, try to get it from current user
        elif hasattr(current_user, 'company_id') and current_user.company_id:
            audit.company_id = current_user.company_id
        else:
            # If neither product nor user has company_id, return an error
            return {'status': 'error', 'message': 'Unable to determine company for audit record.'}, 400

        db.session.add(audit)

    try:
        db.session.commit()
        
        # Log the activity
        log_activity(
            action="Stock Audit Submitted",
            details=f"Stock audit batch <strong>{batch_label}</strong> submitted by <strong>{verified_by}</strong>"
        )
        
        return {'status': 'success', 'message': 'Audit saved.', 'batch': batch_label}
    except Exception as e:
        db.session.rollback()
        return {'status': 'error', 'message': f'Failed to save audit: {str(e)}'}, 500


@api.route('/stock_audit_report')
@login_required
@user_redirect_to_requisition
def stock_audit_report():
    # Get parameters
    selected_batch = request.args.get('batch')
    start_date = request.args.get('start_date')
    end_date = request.args.get('end_date')
    status_filter = request.args.get('status')
    page = request.args.get('page', 1, type=int)
    per_page = 10  # Number of sessions per page
    
    # Get all batch labels with summary information
    # Filter by company for Company-Admin users
    if current_user.role == 'SYS-Admin' and current_user.company_id is None:
        # SYS-Admin with no company can see all audits
        base_query = db.session.query(StockAudit)
    else:
        # Company-Admin and other admins can only see audits from their company
        base_query = db.session.query(StockAudit).filter(StockAudit.company_id == current_user.company_id)
    
    # Apply date filtering to sessions list if dates are provided
    if start_date:
        start_datetime = datetime.strptime(start_date, '%Y-%m-%d')
        base_query = base_query.filter(StockAudit.timestamp >= start_datetime)
    
    if end_date:
        end_datetime = datetime.strptime(end_date, '%Y-%m-%d') + timedelta(days=1)
        base_query = base_query.filter(StockAudit.timestamp < end_datetime)
    
    # Apply status filtering if status is provided
    if status_filter:
        if status_filter == 'settled':
            # Filter for sessions where all audits are settled
            base_query = base_query.filter(StockAudit.is_settled == True)
        elif status_filter == 'pending':
            # Filter for sessions where at least one audit is not settled
            base_query = base_query.filter(StockAudit.is_settled == False)
    
    # Get total count for pagination
    total_sessions = (
        base_query
        .with_entities(StockAudit.batch_label)
        .group_by(StockAudit.batch_label)
        .count()
    )
    
    # Apply pagination to the main query
    batch_summary = (
        base_query
        .with_entities(
            StockAudit.batch_label,
            db.func.max(StockAudit.timestamp).label('latest_ts'),
            db.func.count(StockAudit.id).label('total_audits'),
            db.func.sum(db.case((StockAudit.discrepancy > 0, 1), else_=0)).label('over_count'),
            db.func.sum(db.case((StockAudit.discrepancy < 0, 1), else_=0)).label('short_count'),
            db.func.sum(db.case((StockAudit.discrepancy == 0, 1), else_=0)).label('matched_count'),
            db.func.sum(db.case((StockAudit.is_settled == True, 1), else_=0)).label('settled_count')
        )
        .group_by(StockAudit.batch_label)
        .order_by(db.desc('latest_ts'))
        .offset((page - 1) * per_page)
        .limit(per_page)
            .all()
        )

        # If a specific batch is selected, get detailed audits
    audits = []
    is_settled = False
    if selected_batch:
        # Filter by company for Company-Admin users
        if current_user.role == 'SYS-Admin' and current_user.company_id is None:
            # SYS-Admin with no company can see all audits
            query = StockAudit.query.filter_by(batch_label=selected_batch)
        else:
            # Company-Admin and other admins can only see audits from their company
            query = StockAudit.query.filter_by(batch_label=selected_batch, company_id=current_user.company_id)
        
        # Apply date filtering if dates are provided
        if start_date:
            start_datetime = datetime.strptime(start_date, '%Y-%m-%d')
            query = query.filter(StockAudit.timestamp >= start_datetime)
        
        if end_date:
            end_datetime = datetime.strptime(end_date, '%Y-%m-%d') + timedelta(days=1)
            query = query.filter(StockAudit.timestamp < end_datetime)
        
        audits = query.order_by(StockAudit.timestamp.desc()).all()
        
        # Check if all audits in this batch are settled
        if audits:
            is_settled = all(audit.is_settled for audit in audits)
            # Debug logging
            settled_count = sum(1 for audit in audits if audit.is_settled)
            print(f"DEBUG: Batch {selected_batch} - Total audits: {len(audits)}, Settled audits: {settled_count}, All settled: {is_settled}")
        else:
            is_settled = False

    # Create pagination object
    total_pages = (total_sessions + per_page - 1) // per_page
    pagination = type('Pagination', (), {
        'page': page,
        'pages': total_pages,
        'has_prev': page > 1,
        'has_next': page < total_pages,
        'prev_num': page - 1,
        'next_num': page + 1
    })()

    return render_template(
        "warehouse/stock_audit_report.html",
        audits=audits,
        batch_summary=batch_summary,
        selected_batch=selected_batch,
        is_settled=is_settled,
        start_date=start_date,
        end_date=end_date,
        status_filter=status_filter,
        pagination=pagination,
        current_filters={
            'start_date': start_date,
            'end_date': end_date,
            'status': status_filter
        }
    )



@api.route('/batch_stock_audit')
@login_required
@user_redirect_to_requisition
def batch_stock_audit():
    # Filter products by company for Company-Admin users
    if current_user.role == 'SYS-Admin' and current_user.company_id is None:
        # SYS-Admin with no company can see all products
        products = Product.query.order_by(Product.name).all()
    else:
        # Company-Admin and other admins can only see products from their company
        products = Product.query.filter_by(company_id=current_user.company_id).order_by(Product.name).all()
    
    # Get all batches for each product
    for product in products:
        product.warehouse_batches = WarehouseProductBatch.query.filter_by(product_id=product.id).all()
    
    return render_template('warehouse/batch_stock_audit.html', products=products)


@api.route('/submit_batch_audit', methods=['POST'])
@login_required
@user_redirect_to_requisition
def submit_batch_audit():
    data = request.get_json()
    audits = data.get('audits', [])
    verified_by = data.get('verified_by', 'Unknown')

    if not audits:
        return {'status': 'error', 'message': 'No audits provided.'}, 400

    # Generate batch label for grouping
    batch_label = f"BATCH-AUDIT-{datetime.now().strftime('%Y%m%d-%H%M%S')}"

    # Handle both dictionary and list formats for audits
    audit_items = []
    if isinstance(audits, dict):
        # Desktop format - dictionary of audits
        audit_items = list(audits.values())
    else:
        # Mobile format - list of audits
        audit_items = audits

    batch_audits = []
    for entry in audit_items:
        # Handle both desktop and mobile audit data formats
        product_id = entry.get('product_id') or entry.get('batch_product_id')
        product_name = entry.get('product_name')
        product_uom = entry.get('product_uom')
        batch_id = entry.get('batch_id')
        batch_barcode = entry.get('batch_barcode')
        exp_date = entry.get('exp_date')
        recorded_qty = entry.get('recorded_quantity')
        actual_qty = entry.get('actual_quantity')

        if None in (product_id, product_name, batch_id, batch_barcode, recorded_qty, actual_qty):
            continue

        discrepancy = actual_qty - recorded_qty

        # Convert exp_date string to Python date object if it's a string
        if isinstance(exp_date, str) and exp_date:
            try:
                exp_date = datetime.strptime(exp_date, '%Y-%m-%d').date()
            except ValueError:
                exp_date = None  # Set to None if date format is invalid
        elif not exp_date:
            exp_date = None  # Ensure exp_date is None if it's falsy

        # Create batch audit record
        batch_audit = BatchAudit(
            product_id=product_id,
            product_name=product_name,
            product_uom=product_uom,
            batch_id=batch_id,
            batch_barcode=batch_barcode,
            exp_date=exp_date,
            recorded_quantity=recorded_qty,
            actual_quantity=actual_qty,
            discrepancy=discrepancy,
            verified_by=verified_by,
            batch_label=batch_label  # Add batch_label for grouping
        )
        
        # Assign company to the batch audit record
        # First try to get company_id from the product
        product = Product.query.get(product_id)
        if product and product.company_id:
            batch_audit.company_id = product.company_id
        # If product doesn't have company_id, try to get it from current user
        elif hasattr(current_user, 'company_id') and current_user.company_id:
            batch_audit.company_id = current_user.company_id
        else:
            # If neither product nor user has company_id, return an error
            return {'status': 'error', 'message': 'Unable to determine company for batch audit record.'}, 400

        db.session.add(batch_audit)
        batch_audits.append(batch_audit)

    try:
        db.session.commit()
        
        # Log the audit activity
        log_activity(
            action="Batch Audit",
            details=f"Submitted batch audit with "
                    f"<span class='badge bg-info'>{len(batch_audits)} batches</span> "
                    f"verified by <strong>{verified_by}</strong>"
        )
        
        return {
            'status': 'success', 
            'message': f'Audit submitted successfully! {len(batch_audits)} batches audited.',
            'batch_label': batch_label
        }
    except Exception as e:
        db.session.rollback()
        return {'status': 'error', 'message': str(e)}, 500


@api.route('/batch_audit_report')
@login_required
@user_redirect_to_requisition
def batch_audit_report():
    """Desktop batch audit report route - shows all reports with status indicators"""
    # Get parameters
    page = request.args.get('page', 1, type=int)
    per_page = 10  # Number of sessions per page
    status_filter = request.args.get('status')  # 'all', 'pending', 'settled'
    search_query = request.args.get('q', '').strip()  # Search query
    date_from = request.args.get('date')  # Date from filter
    date_to = request.args.get('date_to')  # Date to filter
    
    # Get all batch labels with summary information for all audits
    # Filter by company for Company-Admin users
    if current_user.role == 'SYS-Admin' and current_user.company_id is None:
        # SYS-Admin with no company can see all audits
        base_query = db.session.query(BatchAudit)
    else:
        # Company-Admin and other admins can only see audits from their company
        base_query = db.session.query(BatchAudit).filter(
            BatchAudit.company_id == current_user.company_id
        )
    
    # Apply search filter
    if search_query:
        search_filter = or_(
            BatchAudit.batch_label.ilike(f'%{search_query}%'),
            BatchAudit.product_name.ilike(f'%{search_query}%')
        )
        base_query = base_query.filter(search_filter)
    
    # Apply date filters
    if date_from:
        date_from_obj = datetime.strptime(date_from, '%Y-%m-%d')
        base_query = base_query.filter(BatchAudit.audit_timestamp >= date_from_obj)
    
    if date_to:
        date_to_obj = datetime.strptime(date_to, '%Y-%m-%d')
        # Include the entire day by adding 1 day and setting time to 00:00:00
        date_to_obj = date_to_obj + timedelta(days=1)
        base_query = base_query.filter(BatchAudit.audit_timestamp < date_to_obj)
    
    # Apply status filtering if status is provided
    if status_filter and status_filter != 'all':
        if status_filter == 'pending':
            base_query = base_query.filter(BatchAudit.status == 'pending')
        elif status_filter == 'settled':
            base_query = base_query.filter(BatchAudit.status == 'settled')
    
    # Get total count for pagination
    total_sessions = (
        base_query
        .with_entities(BatchAudit.batch_label)
        .group_by(BatchAudit.batch_label)
        .count()
    )
    
    # Apply pagination to the main query
    batch_summary = (
        base_query
        .with_entities(
            BatchAudit.batch_label,
            db.func.max(BatchAudit.audit_timestamp).label('latest_ts'),
            db.func.count(BatchAudit.id).label('total_audits'),
            db.func.sum(db.case((BatchAudit.discrepancy > 0, 1), else_=0)).label('over_count'),
            db.func.sum(db.case((BatchAudit.discrepancy < 0, 1), else_=0)).label('short_count'),
            db.func.sum(db.case((BatchAudit.discrepancy == 0, 1), else_=0)).label('matched_count'),
            db.func.sum(db.case((BatchAudit.status == 'pending', 1), else_=0)).label('pending_count'),
            db.func.sum(db.case((BatchAudit.status == 'settled', 1), else_=0)).label('settled_count')
        )
        .group_by(BatchAudit.batch_label)
        .order_by(db.desc('latest_ts'))
        .offset((page - 1) * per_page)
        .limit(per_page)
        .all()
    )
    
    # Get all audits for the current page's batch labels
    batch_labels = [session.batch_label for session in batch_summary]
    if batch_labels:
        query = BatchAudit.query.filter(BatchAudit.batch_label.in_(batch_labels))
        # Filter by company for Company-Admin users
        if not (current_user.role == 'SYS-Admin' and current_user.company_id is None):
            query = query.filter(BatchAudit.company_id == current_user.company_id)
        
        # Apply search filter to detailed query as well
        if search_query:
            search_filter = or_(
                BatchAudit.batch_label.ilike(f'%{search_query}%'),
                BatchAudit.product_name.ilike(f'%{search_query}%')
            )
            query = query.filter(search_filter)
        
        # Apply date filters to detailed query as well
        if date_from:
            date_from_obj = datetime.strptime(date_from, '%Y-%m-%d')
            query = query.filter(BatchAudit.audit_timestamp >= date_from_obj)
        
        if date_to:
            date_to_obj = datetime.strptime(date_to, '%Y-%m-%d')
            # Include the entire day by adding 1 day and setting time to 00:00:00
            date_to_obj = date_to_obj + timedelta(days=1)
            query = query.filter(BatchAudit.audit_timestamp < date_to_obj)
        
        # Apply status filtering if status is provided
        if status_filter and status_filter != 'all':
            query = query.filter(BatchAudit.status == status_filter)
            
        audits = query.order_by(BatchAudit.audit_timestamp.desc()).all()
    else:
        audits = []
    
    # Group audits by batch_label for easier access in template
    audits_by_batch = {}
    for audit in audits:
        if audit.batch_label not in audits_by_batch:
            audits_by_batch[audit.batch_label] = []
        audits_by_batch[audit.batch_label].append(audit)
    
    # Create pagination object
    total_pages = (total_sessions + per_page - 1) // per_page
    pagination = type('Pagination', (), {
        'page': page,
        'pages': total_pages,
        'has_prev': page > 1,
        'has_next': page < total_pages,
        'prev_num': page - 1,
        'next_num': page + 1
    })()
    
    return render_template(
        "warehouse/batch_audit_report.html",
        batch_summary=batch_summary,
        audits_by_batch=audits_by_batch,
        pagination=pagination,
        status_filter=status_filter or 'all',
        search_query=search_query,
        date_from=date_from,
        date_to=date_to
    )





@api.route('/batch_audit_report_details/<batch_label>')
@login_required
@user_redirect_to_requisition
def batch_audit_report_details(batch_label):
    """Desktop batch audit report details route"""
    # Get detailed audits for the selected batch
    # Filter by company for Company-Admin users
    if current_user.role == 'SYS-Admin' and current_user.company_id is None:
        # SYS-Admin with no company can see all audits
        audits = BatchAudit.query.filter_by(batch_label=batch_label).order_by(BatchAudit.audit_timestamp.desc()).all()
    else:
        # Company-Admin and other admins can only see audits from their company
        audits = BatchAudit.query.filter_by(batch_label=batch_label, company_id=current_user.company_id).order_by(BatchAudit.audit_timestamp.desc()).all()
    
    # Check if this is an AJAX request for partial content
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        # Return only the partial template for AJAX requests (used in modals)
        return render_template(
            "warehouse/batch_audit_report_details_partial.html",
            audits=audits,
            batch_label=batch_label
        )
    else:
        # Return the full page template for direct requests
        return render_template(
            "warehouse/batch_audit_report_details.html",
            audits=audits,
            batch_label=batch_label
        )


@api.route('/print_batch_audit_report/<batch_label>')
@login_required
@user_redirect_to_requisition
def print_batch_audit_report(batch_label):
    """Print batch audit report"""
    # Get detailed audits for the selected batch
    # Filter by company for Company-Admin users
    if current_user.role == 'SYS-Admin' and current_user.company_id is None:
        # SYS-Admin with no company can see all audits
        audits = BatchAudit.query.filter_by(batch_label=batch_label).order_by(BatchAudit.audit_timestamp.desc()).all()
    else:
        # Company-Admin and other admins can only see audits from their company
        audits = BatchAudit.query.filter_by(batch_label=batch_label, company_id=current_user.company_id).order_by(BatchAudit.audit_timestamp.desc()).all()
    
    return render_template(
        "warehouse/print_batch_audit_report.html",
        audits=audits,
        batch_label=batch_label
    )


@api.route('/export_audit_csv/<batch>')
@login_required
@user_redirect_to_requisition
def export_audit_csv(batch):
    """Export audit data for a specific batch to CSV format"""
    try:
        # Get date range parameters
        start_date = request.args.get('start_date')
        end_date = request.args.get('end_date')
        
        query = StockAudit.query.filter_by(batch_label=batch)
        
        # Apply date filtering if dates are provided
        if start_date:
            start_datetime = datetime.strptime(start_date, '%Y-%m-%d')
            query = query.filter(StockAudit.timestamp >= start_datetime)
        
        if end_date:
            end_datetime = datetime.strptime(end_date, '%Y-%m-%d') + timedelta(days=1)
            query = query.filter(StockAudit.timestamp < end_datetime)
        
        # Filter by company for Company-Admin users
        if not (current_user.role == 'SYS-Admin' and current_user.company_id is None):
            # Company-Admin and other admins can only see audits from their company
            query = query.filter(StockAudit.company_id == current_user.company_id)
        
        audits = query.order_by(StockAudit.timestamp.desc()).all()

        if not audits:
            flash('No audit data found for this batch.', 'error')
            return redirect(url_for('api.stock_audit_report', batch=batch))
        
        # Validate that we have valid data
        valid_audits = [audit for audit in audits if audit.product is not None]
        if not valid_audits:
            flash('No valid audit data found for this batch.', 'error')
            return redirect(url_for('api.stock_audit_report', batch=batch))

        # Generate CSV
        output = io.StringIO()
        cw = csv.writer(output)
        
        # Write header
        cw.writerow([
            'Product Name', 'Barcode', 'UOM', 
            'System Qty', 'Actual Qty', 'Discrepancy', 
            'Verified By', 'Timestamp', 'Settled'
        ])
        
        # Write data
        for audit in valid_audits:
            cw.writerow([
                audit.product.name if audit.product else 'Unknown Product',
                audit.product.barcode if audit.product else '',
                audit.product.uom if audit.product else '',
                audit.recorded_quantity,
                audit.actual_quantity,
                audit.discrepancy,
                audit.verified_by,
                audit.timestamp.strftime('%Y-%m-%d %H:%M'),
                'Yes' if audit.is_settled else 'No'
            ])
        
        # Create response
        csv_content = output.getvalue()
        output.close()
        
        # Use make_response to create the response object
        from flask import make_response
        response = make_response(csv_content)
        response.headers['Content-Disposition'] = f'attachment; filename=Audit_Report_{batch}.csv'
        response.headers['Content-type'] = 'text/csv'
        
        # Log the export
        log_activity(
            action="Audit Export",
            details=f"Exported audit <strong>{batch}</strong> to CSV"
        )
        
        return response
        
    except Exception as e:
        flash(f'Error exporting audit: {str(e)}', 'error')
        return redirect(url_for('api.stock_audit_report', batch=batch))


@api.route('/settle_discrepancy/<batch>', methods=['POST'])
@login_required
@admin_required
@user_redirect_to_requisition
def settle_discrepancy(batch):
    """Settle audit discrepancies by adjusting batch quantities directly"""
    try:
        # Validate batch parameter
        if not batch or not isinstance(batch, str):
            flash('Invalid batch parameter.', 'error')
            return redirect(url_for('api.stock_audit_report'))
        
        # Filter by company for Company-Admin users
        if current_user.role == 'SYS-Admin' and current_user.company_id is None:
            # SYS-Admin with no company can see all audits
            audits = StockAudit.query.filter_by(batch_label=batch).all()
        else:
            # Company-Admin and other admins can only see audits from their company
            audits = StockAudit.query.filter_by(batch_label=batch, company_id=current_user.company_id).all()
        
        if not audits:
            flash('No audit data found for this batch.', 'error')
            return redirect(url_for('api.stock_audit_report', batch=batch))
        
        current_time = datetime.now(ZoneInfo("Asia/Manila"))
        total_discrepancies_settled = 0
        total_products_processed = 0
        settlement_summary = []
        
        # Process audits by product
        from collections import defaultdict
        product_audits = defaultdict(list)
        
        for audit in audits:
            product_audits[audit.product_id].append(audit)
        
        for product_id, product_audit_list in product_audits.items():
            # Get the product
            product = Product.query.get(product_id)
            if not product:
                continue
            
            total_products_processed += 1
            
            # Get all batches for this product
            batches = WarehouseProductBatch.query.filter_by(product_id=product_id).all()
            
            for audit in product_audit_list:
                if audit.is_settled:
                    continue
                
                # Calculate the adjustment needed
                adjustment = audit.discrepancy
                
                # Skip if adjustment is zero
                if adjustment == 0:
                    audit.is_settled = True
                    total_discrepancies_settled += 1
                    continue
                
                # For StockAudit, we don't have a specific batch_id, so we use the FEFO approach
                # Apply adjustment according to FEFO principles
                if adjustment > 0:
                    # OVERAGE: Add excess quantity to the first batch with quantity > 0 and earliest expiry
                    first_batch_with_qty = None
                    earliest_expiry = None
                    
                    for b in sorted(batches, key=lambda x: x.exp_date):
                        if b.quantity > 0:
                            first_batch_with_qty = b
                            earliest_expiry = b.exp_date
                            break
                    
                    if first_batch_with_qty:
                        # Store original quantity for history record
                        original_quantity = first_batch_with_qty.quantity
                        first_batch_with_qty.quantity += adjustment
                        settlement_summary.append(f"Added {adjustment} to batch expiring {earliest_expiry}")
                        
                        # Create ProductHistory record for TRANS IN
                        history_record = ProductHistory(
                            product_id=product.id,
                            trxn_date=current_time,
                            trxn_code='TRANS IN',
                            payee=f'Audit Adjustment - {batch}',
                            quantity_in=adjustment,
                            quantity_out=0.0,
                            net_change=adjustment,
                            reference_id=first_batch_with_qty.id,
                            reference_type='batch'
                        )
                        # Assign company to history record
                        history_record = assign_company(history_record)
                        db.session.add(history_record)
                        
                        # Update product quantities (adjustment was made to warehouse batches)
                        product.warehouse_qty += adjustment
                        product.warehouse_initial_qty = max(product.warehouse_initial_qty or 0, product.warehouse_qty)
                        product.quantity = product.warehouse_qty + product.store_qty
                        product.initial_quantity = product.quantity
                    
                    else:
                        settlement_summary.append(f"OVERAGE of {adjustment} for {product.name} but no batches with quantity found")
                
                elif adjustment < 0:
                    # SHORTAGE: Remove missing quantity from batches according to FEFO
                    shortage = abs(adjustment)
                    removed_qty = 0
                    
                    for b in sorted(batches, key=lambda x: x.exp_date):
                        if b.quantity > 0 and removed_qty < shortage:
                            deduct_amount = min(b.quantity, shortage - removed_qty)
                            b.quantity -= deduct_amount
                            removed_qty += deduct_amount
                            
                            # Create ProductHistory record for TRANS OUT
                            history_record = ProductHistory(
                                product_id=product.id,
                                trxn_date=current_time,
                                trxn_code='TRANS OUT',
                                payee=f'Audit Adjustment - {batch}',
                                quantity_in=0.0,
                                quantity_out=deduct_amount,
                                net_change=-deduct_amount,
                                reference_id=b.id,
                                reference_type='batch'
                            )
                            # Assign company to history record
                            history_record = assign_company(history_record)
                            db.session.add(history_record)
                    
                    # Update product quantities (shortage was deducted from warehouse batches)
                    product.warehouse_qty -= shortage
                    if product.warehouse_qty < 0:
                        product.warehouse_qty = 0
                    product.quantity = product.warehouse_qty + product.store_qty
                    product.initial_quantity = product.quantity
                    
                    settlement_summary.append(f"Removed {shortage} from {product.name} batches")
                
                # Mark audit as settled
                audit.is_settled = True
                total_discrepancies_settled += 1
        
        # Commit all changes
        db.session.commit()
        
        # Log the settlement activity
        log_activity(
            action="Audit Discrepancy Settlement",
            details=f"Settled <span class='badge bg-info'>{total_discrepancies_settled} discrepancies</span> "
                    f"for <span class='badge bg-info'>{total_products_processed} products</span> "
                    f"in batch <strong>{batch}</strong>"
        )
        
        # Flash summary of actions
        flash(f'Successfully settled {total_discrepancies_settled} discrepancies for {total_products_processed} products.', 'success')
        for item in settlement_summary:
            flash(f'- {item}', 'info')
        
        # Redirect back to the same batch view to show updated status
        return redirect(url_for('api.stock_audit_report', batch=batch))
        
    except Exception as e:
        db.session.rollback()
        flash(f'Error settling discrepancy: {str(e)}', 'error')
        return redirect(url_for('api.stock_audit_report', batch=batch))


@api.route('/settle_batch_audit_pending/<batch_label>', methods=['POST'])
@login_required
@admin_required  # Only sys admin and company admin can settle
@user_redirect_to_requisition
def settle_batch_audit_pending(batch_label):
    """Settle batch audit pending discrepancies by adjusting specific batch quantities directly"""
    try:
        # Validate batch_label parameter
        if not batch_label or not isinstance(batch_label, str):
            flash('Invalid batch label parameter.', 'error')
            return redirect(url_for('api.batch_audit_pending'))
        
        # Filter by company for Company-Admin users
        if current_user.role == 'SYS-Admin' and current_user.company_id is None:
            # SYS-Admin with no company can see all pending audits
            audits = BatchAudit.query.filter_by(batch_label=batch_label, status='pending').all()
        else:
            # Company-Admin and other admins can only see pending audits from their company
            audits = BatchAudit.query.filter_by(batch_label=batch_label, status='pending', company_id=current_user.company_id).all()
        
        if not audits:
            flash('No pending audit data found for this batch.', 'error')
            return redirect(url_for('api.batch_audit_pending'))
        
        current_time = datetime.now(ZoneInfo("Asia/Manila"))
        total_discrepancies_settled = 0
        total_products_processed = 0
        settlement_summary = []
        
        # Process audits by product
        from collections import defaultdict
        product_audits = defaultdict(list)
        
        for audit in audits:
            product_audits[audit.product_id].append(audit)
        
        for product_id, product_audit_list in product_audits.items():
            # Get the product
            product = Product.query.get(product_id)
            if not product:
                continue
            
            total_products_processed += 1
            
            for audit in product_audit_list:
                if audit.status != 'pending':
                    continue
                
                # Calculate the adjustment needed
                adjustment = audit.discrepancy
                
                # Skip if adjustment is zero
                if adjustment == 0:
                    audit.status = 'settled'
                    total_discrepancies_settled += 1
                    continue
                
                # Get the specific batch being audited
                batch = WarehouseProductBatch.query.get(audit.batch_id)
                if not batch:
                    settlement_summary.append(f"Batch {audit.batch_id} not found for {product.name}")
                    continue
                
                # Apply adjustment directly to the specific batch being audited
                if adjustment > 0:
                    # OVERAGE: Add excess quantity directly to the audited batch
                    batch.quantity += adjustment
                    settlement_summary.append(f"Added {adjustment} to batch #{batch.id} (expiring {batch.exp_date})")
                    
                    # Create ProductHistory record for TRANS IN
                    history_record = ProductHistory(
                        product_id=product.id,
                        trxn_date=current_time,
                        trxn_code='TRANS IN',
                        payee=f'Batch Audit Adjustment - {batch_label}',
                        quantity_in=adjustment,
                        quantity_out=0.0,
                        net_change=adjustment,
                        reference_id=batch.id,
                        reference_type='batch'
                    )
                    # Assign company to history record
                    history_record = assign_company(history_record)
                    db.session.add(history_record)
                    
                    # Update product total quantity
                    product.quantity += adjustment
                    
                    # Update product initial quantity to match current quantity
                    product.initial_quantity = product.quantity
                
                elif adjustment < 0:
                    # SHORTAGE: Remove missing quantity directly from the audited batch
                    shortage = abs(adjustment)
                    
                    # Check if batch has enough quantity
                    if batch.quantity >= shortage:
                        batch.quantity -= shortage
                        settlement_summary.append(f"Removed {shortage} from batch #{batch.id} (expiring {batch.exp_date})")
                        
                        # Create ProductHistory record for TRANS OUT
                        history_record = ProductHistory(
                            product_id=product.id,
                            trxn_date=current_time,
                            trxn_code='TRANS OUT',
                            payee=f'Batch Audit Adjustment - {batch_label}',
                            quantity_in=0.0,
                            quantity_out=shortage,
                            net_change=-shortage,
                            reference_id=batch.id,
                            reference_type='batch'
                        )
                        # Assign company to history record
                        history_record = assign_company(history_record)
                        db.session.add(history_record)
                        
                        # Update product total quantity
                        product.quantity -= shortage
                        
                        # Update product initial quantity to match current quantity
                        product.initial_quantity = product.quantity
                    else:
                        # Not enough quantity in batch, remove what's available
                        available_qty = batch.quantity
                        batch.quantity = 0
                        settlement_summary.append(f"Removed {available_qty} from batch #{batch.id} (expiring {batch.exp_date}) - Insufficient quantity for full adjustment")
                        
                        # Create ProductHistory record for TRANS OUT
                        history_record = ProductHistory(
                            product_id=product.id,
                            trxn_date=current_time,
                            trxn_code='TRANS OUT',
                            payee=f'Batch Audit Adjustment - {batch_label}',
                            quantity_in=0.0,
                            quantity_out=available_qty,
                            net_change=-available_qty,
                            reference_id=batch.id,
                            reference_type='batch'
                        )
                        # Assign company to history record
                        history_record = assign_company(history_record)
                        db.session.add(history_record)
                        
                        # Update product total quantity
                        product.quantity -= available_qty
                        
                        # Update product initial quantity to match current quantity
                        product.initial_quantity = product.quantity
                
                # Mark audit as settled
                audit.status = 'settled'
                total_discrepancies_settled += 1
        
        # Commit all changes
        db.session.commit()
        
        # Log the settlement activity
        log_activity(
            action="Batch Audit Pending Settlement",
            details=f"Settled <span class='badge bg-info'>{total_discrepancies_settled} discrepancies</span> "
                    f"for <span class='badge bg-info'>{total_products_processed} products</span> "
                    f"in batch <strong>{batch_label}</strong>"
        )
        
        # Flash summary of actions
        flash(f'Successfully settled {total_discrepancies_settled} discrepancies for {total_products_processed} products.', 'success')
        for item in settlement_summary:
            flash(f'- {item}', 'info')
        
        return redirect(url_for('api.batch_audit_pending'))
        
    except Exception as e:
        db.session.rollback()
        flash(f'Error settling batch audit pending: {str(e)}', 'error')
        return redirect(url_for('api.batch_audit_pending'))


@api.route('/batch_audit_pending')
@login_required
@user_redirect_to_requisition
def batch_audit_pending():
    """Desktop batch audit pending list route"""
    # Get parameters
    page = request.args.get('page', 1, type=int)
    per_page = 10  # Number of sessions per page
    
    # Get all batch labels with summary information for pending audits
    # Filter by company for Company-Admin users
    if current_user.role == 'SYS-Admin' and current_user.company_id is None:
        # SYS-Admin with no company can see all pending audits
        base_query = db.session.query(BatchAudit).filter_by(status='pending')
    else:
        # Company-Admin and other admins can only see pending audits from their company
        base_query = db.session.query(BatchAudit).filter_by(
            status='pending',
            company_id=current_user.company_id
        )
    
    # Get total count for pagination
    total_sessions = (
        base_query
        .with_entities(BatchAudit.batch_label)
        .group_by(BatchAudit.batch_label)
        .count()
    )
    
    # Apply pagination to the main query
    batch_summary = (
        base_query
        .with_entities(
            BatchAudit.batch_label,
            db.func.max(BatchAudit.audit_timestamp).label('latest_ts'),
            db.func.count(BatchAudit.id).label('total_audits'),
            db.func.sum(db.case((BatchAudit.discrepancy > 0, 1), else_=0)).label('over_count'),
            db.func.sum(db.case((BatchAudit.discrepancy < 0, 1), else_=0)).label('short_count'),
            db.func.sum(db.case((BatchAudit.discrepancy == 0, 1), else_=0)).label('matched_count')
        )
        .group_by(BatchAudit.batch_label)
        .order_by(db.desc('latest_ts'))
        .offset((page - 1) * per_page)
        .limit(per_page)
        .all()
    )
    
    # Get all audits for the current page's batch labels
    batch_labels = [session.batch_label for session in batch_summary]
    if batch_labels:
        if current_user.role == 'SYS-Admin' and current_user.company_id is None:
            # SYS-Admin with no company can see all pending audits
            audits = BatchAudit.query.filter(
                BatchAudit.status == 'pending',
                BatchAudit.batch_label.in_(batch_labels)
            ).order_by(BatchAudit.audit_timestamp.desc()).all()
        else:
            # Company-Admin and other admins can only see pending audits from their company
            audits = BatchAudit.query.filter(
                BatchAudit.status == 'pending',
                BatchAudit.company_id == current_user.company_id,
                BatchAudit.batch_label.in_(batch_labels)
            ).order_by(BatchAudit.audit_timestamp.desc()).all()
    else:
        audits = []
    
    # Group audits by batch_label for easier access in template
    audits_by_batch = {}
    for audit in audits:
        if audit.batch_label not in audits_by_batch:
            audits_by_batch[audit.batch_label] = []
        audits_by_batch[audit.batch_label].append(audit)
    
    # Create pagination object
    total_pages = (total_sessions + per_page - 1) // per_page
    pagination = type('Pagination', (), {
        'page': page,
        'pages': total_pages,
        'has_prev': page > 1,
        'has_next': page < total_pages,
        'prev_num': page - 1,
        'next_num': page + 1
    })()
    
    return render_template(
        "warehouse/batch_audit_pending_desktop.html",
        batch_summary=batch_summary,
        audits_by_batch=audits_by_batch,
        pagination=pagination
    )


@api.route('/batch_audit_pending_details/<batch_label>')
@login_required
@user_redirect_to_requisition
def batch_audit_pending_details(batch_label):
    """Desktop batch audit pending details route"""
    # Get detailed audits for the selected batch
    # Filter by company for Company-Admin users
    if current_user.role == 'SYS-Admin' and current_user.company_id is None:
        # SYS-Admin with no company can see all pending audits
        audits = BatchAudit.query.filter_by(batch_label=batch_label, status='pending').order_by(BatchAudit.audit_timestamp.desc()).all()
    else:
        # Company-Admin and other admins can only see pending audits from their company
        audits = BatchAudit.query.filter_by(batch_label=batch_label, status='pending', company_id=current_user.company_id).order_by(BatchAudit.audit_timestamp.desc()).all()
    
    # Check if this is an AJAX request for partial content
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        # Return only the partial template for AJAX requests (used in modals)
        return render_template(
            "warehouse/batch_audit_pending_details_partial.html",
            audits=audits,
            batch_label=batch_label
        )
    else:
        # Return the full page template for direct requests
        return render_template(
            "warehouse/batch_audit_pending_details.html",
            audits=audits,
            batch_label=batch_label
        )


@api.route('/delete_audit_batch/<batch_label>', methods=['POST'])
@login_required
@sys_admin_required
@user_redirect_to_requisition
def delete_audit_batch(batch_label):
    """Delete an audit batch by its batch label"""
    try:
        # Validate batch_label parameter
        if not batch_label or not isinstance(batch_label, str):
            return jsonify({'success': False, 'message': 'Invalid batch label parameter.'}), 400
        
        # Delete all StockAudit records with this batch_label
        # Filter by company for Company-Admin users
        if current_user.role == 'SYS-Admin' and current_user.company_id is None:
            # SYS-Admin with no company can delete all audits
            stock_audits = StockAudit.query.filter_by(batch_label=batch_label).all()
            batch_audits = BatchAudit.query.filter_by(batch_label=batch_label).all()
        else:
            # Company-Admin and other admins can only delete audits from their company
            stock_audits = StockAudit.query.filter_by(batch_label=batch_label, company_id=current_user.company_id).all()
            batch_audits = BatchAudit.query.filter_by(batch_label=batch_label, company_id=current_user.company_id).all()
        
        if not stock_audits and not batch_audits:
            return jsonify({'success': False, 'message': 'No audit data found for this batch label.'}), 404
        
        # Delete all matching records
        total_deleted = 0
        for audit in stock_audits:
            db.session.delete(audit)
            total_deleted += 1
            
        for audit in batch_audits:
            db.session.delete(audit)
            total_deleted += 1
        
        db.session.commit()
        
        # Log the deletion activity
        log_activity(
            action="Delete Audit Batch",
            details=f"Deleted audit batch <strong>{batch_label}</strong> with "
                    f"<span class='badge bg-info'>{total_deleted} records</span>"
        )
        
        return jsonify({
            'success': True, 
            'message': f'Successfully deleted audit batch {batch_label} with {total_deleted} records.'
        })
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': f'Error deleting audit batch: {str(e)}'}), 500


# ─── PRODUCT SEARCH API ──────────────────────────────────

@api.route('/search_products')
@login_required
def search_products():
    """Search products by name for optional product lookup"""
    q = request.args.get('q', '').strip()
    if not q:
        return jsonify({'success': False, 'message': 'Search query required'}), 400

    try:
        if current_user.role == 'SYS-Admin' and current_user.company_id is None:
            products = Product.query.filter(Product.name.ilike(f'%{q}%')).order_by(Product.name).limit(10).all()
        else:
            products = Product.query.filter(
                Product.name.ilike(f'%{q}%'),
                Product.company_id == current_user.company_id
            ).order_by(Product.name).limit(10).all()

        return jsonify({
            'success': True,
            'products': [{
                'id': p.id,
                'name': p.name,
                'uom': p.uom,
                'barcode': p.barcode,
                'stock': p.quantity
            } for p in products]
        })
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500


# ─── NOTIFICATION API ──────────────────────────────────────

@api.route('/notifications')
@login_required
def list_notifications():
    page = request.args.get('page', 1, type=int)
    per_page = 20
    query = Notification.query.filter_by(user_id=current_user.id)\
        .order_by(Notification.created_at.desc())
    pagination = query.paginate(page=page, per_page=per_page, error_out=False)
    return jsonify({
        'success': True,
        'notifications': [{
            'id': n.id,
            'title': n.title,
            'message': n.message,
            'type': n.type,
            'reference_type': n.reference_type,
            'reference_id': n.reference_id,
            'is_read': n.is_read,
            'created_at': n.created_at.isoformat()
        } for n in pagination.items],
        'total': pagination.total,
        'pages': pagination.pages,
        'current_page': page
    })


@api.route('/notifications/count')
@login_required
def notification_count():
    count = Notification.query.filter_by(user_id=current_user.id, is_read=False).count()
    return jsonify({'success': True, 'count': count})


@api.route('/notifications/mark-read/<int:notification_id>', methods=['POST'])
@login_required
def mark_notification_read(notification_id):
    notif = Notification.query.filter_by(id=notification_id, user_id=current_user.id).first()
    if not notif:
        return jsonify({'success': False, 'message': 'Notification not found'}), 404
    notif.is_read = True
    db.session.commit()
    return jsonify({'success': True})


@api.route('/notifications/mark-all-read', methods=['POST'])
@login_required
def mark_all_notifications_read():
    Notification.query.filter_by(user_id=current_user.id, is_read=False)\
        .update({'is_read': True})
    db.session.commit()
    return jsonify({'success': True})

