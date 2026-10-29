# Standard library imports
import json
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

# Third-party imports
from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify, current_app
from flask_login import login_required, current_user
from flask_mail import Message

# Local imports
from extensions import db, mail
from models import Product, Requisition, RequisitionItem, RequisitionBatchDeduction, User, ProductHistory, Company, ReceivingRecord
from helpers import user_redirect_to_requisition, admin_required, sys_admin_required, log_activity, assign_company, create_notification

# Create blueprint with URL prefix as required by project specifications
requisitions = Blueprint('requisitions', __name__, url_prefix='/requisitions')


@requisitions.route('/store_inventory', methods=['GET'], endpoint='store_inventory')
@requisitions.route('/portal', methods=['GET'], endpoint='portal')
@requisitions.route('/store_portal', methods=['GET'], endpoint='store_portal')
@requisitions.route('/requisition_form', methods=['GET'], endpoint='requisition_form')
@login_required
def store_inventory():
    # Only allow User role to access store inventory / requisition form
    if current_user.role not in ['User']:
        flash('Access denied. Only regular users can submit requisitions.', 'error')
        return redirect(url_for('main.dashboard'))
    
    # Check for flash messages from login
    login_success = request.args.get('login_success', 'false')
    
    # Determine initial active panel:
    # If the user navigates directly to /requisitions/requisition_form, default to 'requisition' wizard
    # Otherwise, default to 'storeinv' or whatever ?panel= is requested
    panel = request.args.get('panel', '').strip()
    if not panel and request.path.endswith('/requisition_form'):
        panel = 'requisition'
    
    # Filter products by company for the user
    products = Product.query.filter_by(company_id=current_user.company_id).all()
    now = datetime.utcnow()
    
    # Fetch user's requisitions for history
    user_requisitions = Requisition.query\
        .filter_by(company_id=current_user.company_id)\
        .order_by(Requisition.date_created.desc()).all()
    
    # Serialize requisitions for JavaScript
    history_data = []
    for req in user_requisitions:
        items = []
        for item in req.items:
            items.append({
                'id': item.product_id,
                'name': item.product.name if item.product else 'Unknown',
                'qty': item.quantity,
                'uom': item.uom
            })
        history_data.append({
            'ref': f"REQ-{req.date_created.year}-{req.id:04d}" if req.date_created else f"REQ-{req.id:04d}",
            'date': req.date_created.strftime('%b %d, %Y') if req.date_created else '',
            'items': items,
            'urgency': 'normal',
            'status': req.status.lower() if req.status else 'pending'
        })
    
    # Calculate pending inbound shipments for receiving badge
    pending_receiving_count = Requisition.query.filter(
        (Requisition.company_id == current_user.company_id) |
        (Requisition.destination_company_id == current_user.company_id),
        Requisition.status.in_(['Dispatched', 'dispatched', 'Partial', 'partial'])
    ).count()

    return render_template('user/requisition_form.html', products=products, now=now, 
                         login_success=login_success, history_data=history_data,
                         initial_panel=panel, pending_receiving_count=pending_receiving_count)

# Backwards compatibility alias for function reference
portal = store_inventory
requisition_form = store_inventory


@requisitions.route('/submit_requisition', methods=['POST'])
@login_required
def submit_requisition():
    # Only allow User role to submit requisitions
    if current_user.role not in ['User']:
        return jsonify({'success': False, 'message': 'Access denied. Only regular users can submit requisitions.'}), 403
    
    requested_by = current_user.full_name
    contact_number = request.form.get('contact_number')
    branch = current_user.company.franchise_name if current_user.company and current_user.company.franchise_name else current_user.company.name if current_user.company else ''
    station = request.form.get('station', '')
    
    items = json.loads(request.form['items_json'])

    requisition = Requisition(requested_by=requested_by, status='Pending',
                            contact_number=contact_number, branch=branch, station=station)
    
    # Assign to current user's company
    requisition = assign_company(requisition)
    
    db.session.add(requisition)
    db.session.flush()

    for item in items:
        ri = RequisitionItem(
            requisition_id=requisition.id,
            product_id=item['product_id'],
            quantity=float(item['quantity']),
            uom=item['uom']
        )
        db.session.add(ri)

    db.session.commit()
    
    # Send email receipt to the user
    try:
        # Get user's email from the current user
        user_email = current_user.email
        
        # Prepare email content
        subject = f"Requisition Receipt - #{requisition.id} - Status: Pending"
        
        # Build items list for email
        items_html = ""
        total_items = 0
        for item in items:
            items_html += f"""
            <tr>
                <td>{item['product_name']}</td>
                <td>{item['quantity']} {item['uom']}</td>
            </tr>
            """
            total_items += 1
        
        # Create HTML email body
        html_body = f"""
        <div style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto;">
            <div style="background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white; padding: 20px; text-align: center; border-radius: 10px 10px 0 0;">
                <h1 style="margin: 0; font-size: 24px;">New Requisition Submitted</h1>
                <p style="margin: 10px 0 0 0; opacity: 0.9;">#{requisition.id} - Pending Approval</p>
            </div>
            
            <div style="padding: 20px; background: #f8f9fa; border-radius: 0 0 10px 10px;">
                <h2 style="color: #333; border-bottom: 2px solid #667eea; padding-bottom: 10px;">Requisition Details</h2>
                
                <div style="margin: 15px 0;">
                    <p><strong>Requisition ID:</strong> #{requisition.id}</p>
                    <p><strong>Requested By:</strong> {requisition.requested_by}</p>
                    <p><strong>Contact Number:</strong> {requisition.contact_number or 'N/A'}</p>
                    <p><strong>Franchise Name:</strong> {requisition.branch}</p>
                    <p><strong>Status:</strong> <span style="background: #ffc107; color: #000; padding: 3px 8px; border-radius: 12px; font-weight: bold;">{requisition.status}</span></p>
                    <p><strong>Date Submitted:</strong> {requisition.date_created.strftime('%Y-%m-%d %H:%M:%S')}</p>
                </div>
                
                <h3 style="color: #333; border-bottom: 1px solid #ddd; padding-bottom: 8px;">Items Requested ({total_items} items)</h3>
                <table style="width: 100%; border-collapse: collapse; margin: 15px 0;">
                    <thead>
                        <tr style="background: #e9ecef;">
                            <th style="padding: 10px; text-align: left; border: 1px solid #ddd;">Product</th>
                            <th style="padding: 10px; text-align: left; border: 1px solid #ddd;">Quantity</th>
                        </tr>
                    </thead>
                    <tbody>
                        {items_html}
                    </tbody>
                </table>
                
                <div style="background: #e3f2fd; padding: 15px; border-radius: 5px; margin: 20px 0;">
                    <p style="margin: 0; color: #1976d2;">
                        <strong>ℹ️ Next Steps:</strong> Your requisition is now pending approval. 
                        You will receive another email once it has been processed.
                    </p>
                </div>
                
                <p style="color: #666; font-size: 14px; margin-top: 20px; border-top: 1px solid #dee2e6; padding-top: 20px;">
                    <strong>⚠️ No Reply:</strong> This is an automated message. Please do not reply to this email.
                </p>
            </div>
            <div style="background-color: #e9ecef; padding: 15px; text-align: center; color: #666; font-size: 12px;">
                © 2025 iCount Inventory System. All rights reserved.
            </div>
        </div>
        """
        
        msg = Message(
            subject=subject,
            recipients=[user_email],
            html=html_body
        )
        mail.send(msg)
        
    except Exception as e:
        # Log the error but don't fail the requisition submission
        print(f"Failed to send email: {str(e)}")
    
    # Log the activity
    log_activity(
        action="Requisition Submitted",
        details=f"Requisition #{requisition.id} submitted by {current_user.full_name}"
    )
    
    return jsonify({'success': True, 'message': 'Requisition submitted successfully!', 'requisition_id': requisition.id})


@requisitions.route('/view_requisitions')
@login_required
@user_redirect_to_requisition
def view_requisitions():
    """Display all requisitions with pagination and filters"""
    page = request.args.get('page', 1, type=int)
    # Show all statuses by default; a specific status can still be selected
    # through the filter controls.
    status = request.args.get('status', 'all').strip() or 'all'

    search = request.args.get('q', '').strip()
    date_str = request.args.get('date', '').strip()
    per_page = current_app.config.get('REQUISITIONS_PER_PAGE', 10)
    
    # Base query: SYS-Admin can see all companies. Warehouse and company
    # admins are limited to their company, including transfer requests where
    # their company is the destination.
    if current_user.role == 'User':
        # Regular users can only see their own requisitions
        query = Requisition.query.filter_by(
            requested_by=current_user.full_name,
            company_id=current_user.company_id
        )
    elif current_user.role == 'SYS-Admin' and current_user.company_id is None:
        # Unassigned SYS-Admin can see all requisitions across all companies.
        query = Requisition.query
    else:
        # Company-scoped admins only see requests belonging to or destined for
        # their assigned company.
        query = Requisition.query.filter(
            db.or_(
                Requisition.company_id == current_user.company_id,
                Requisition.destination_company_id == current_user.company_id
            )
        )
    
    # Apply search filter if provided
    if search:
        like = f"%{search}%"
        query = query.filter(db.or_(
            Requisition.requested_by.ilike(like),
            Requisition.branch.ilike(like)  # This now contains franchise name
        ))

    # Apply date filter (single day, based on date created)
    if date_str:
        try:
            day_start = datetime.strptime(date_str, '%Y-%m-%d')
            query = query.filter(
                Requisition.date_created >= day_start,
                Requisition.date_created < day_start + timedelta(days=1)
            )
        except ValueError:
            date_str = ''

    # Status totals across all pages (before the status filter) for the summary cards
    status_counts = {}
    for st, cnt in (query.with_entities(Requisition.status, db.func.count(Requisition.id))
                    .group_by(Requisition.status).all()):
        key = (st or '').lower()
        if key == 'declined':
            key = 'rejected'
        status_counts[key] = status_counts.get(key, 0) + cnt
    total_count = sum(status_counts.values())

    # Apply status filter if provided.
    if status and status.lower() != 'all':
        query = query.filter_by(status=status)
    
    # Order by date created (newest first)
    query = query.order_by(Requisition.date_created.desc())
    
    # Paginate results
    pagination = query.paginate(
        page=page, 
        per_page=per_page, 
        error_out=False
    )
    
    requisitions = pagination.items
    
    # Get Philippines time using zoneinfo
    ph_time = datetime.now(ZoneInfo("Asia/Manila"))
    
    # Prepare current filters for pagination
    current_filters = {}
    if status:
        current_filters['status'] = status
    if search:
        current_filters['q'] = search
    if date_str:
        current_filters['date'] = date_str

    # Build serialized items data for approve modal
    requisitions_data = []
    for r in requisitions:
        items_data = [{
            'id': item.id,
            'product_id': item.product_id,
            'name': item.product.name if item.product else 'Unknown',
            'qty': item.quantity,
            'uom': item.uom,
            'stock': item.product.quantity if item.product else 0
        } for item in r.items if not getattr(item, 'is_optional', False)]
        requisitions_data.append({
            'id': r.id,
            'branch': r.branch or '',
            'status': r.status,
            'validated': r.validated,
            'items': items_data
        })

    import json as json_lib
    requisitions_json = json_lib.dumps(requisitions_data)

    return render_template(
        'user/requisitions.html', 
        requisitions=requisitions, 
        pagination=pagination,
        status=status,
        search=search,
        now=ph_time,
        current_filters=current_filters,
        requisitions_json=requisitions_json,
        status_counts=status_counts,
        total_count=total_count
    )


@requisitions.route('/update_status/<int:requisition_id>', methods=['POST'])
@login_required
@user_redirect_to_requisition
def update_status(requisition_id):
    new_status = request.form['status']
    requisition = Requisition.query.get_or_404(requisition_id)

    # If approving, mark requisition as validated
    if new_status == 'approved':
        requisition.validated = True

    # Handle stock deduction only if approving and currently pending
    if requisition.status == 'Pending' and new_status == 'approved':
        # Get delivery date and time from form if provided
        date_of_delivery_str = request.form.get('date_of_delivery')
        time_of_delivery_str = request.form.get('time_of_delivery')
        date_of_delivery = None
        
        if date_of_delivery_str and time_of_delivery_str:
            try:
                from datetime import datetime
                datetime_str = f"{date_of_delivery_str} {time_of_delivery_str}"
                date_of_delivery = datetime.strptime(datetime_str, '%Y-%m-%d %H:%M')
            except ValueError:
                flash('Invalid delivery date or time format.', 'error')
                return redirect(url_for('requisitions.view_requisitions'))
        elif date_of_delivery_str:
            try:
                from datetime import datetime
                date_of_delivery = datetime.strptime(date_of_delivery_str, '%Y-%m-%d')
            except ValueError:
                flash('Invalid delivery date format.', 'error')
                return redirect(url_for('requisitions.view_requisitions'))

        # ── Process regular items with editable released qty ──
        for req_item in requisition.items:
            if getattr(req_item, 'is_optional', False):
                continue

            product = req_item.product

            # Read released qty from form (defaults to requested qty)
            released_key = f'released_{req_item.id}'
            raw_released = request.form.get(released_key, '').strip()
            if raw_released:
                try:
                    release_qty = float(raw_released)
                except ValueError:
                    flash(f'Invalid released quantity for {product.name}.', 'error')
                    return redirect(url_for('requisitions.view_requisitions'))
                if release_qty < 0:
                    flash(f'Released quantity cannot be negative for {product.name}.', 'error')
                    return redirect(url_for('requisitions.view_requisitions'))
            else:
                release_qty = req_item.quantity

            if release_qty <= 0:
                continue  # skip items where nothing is released

            remaining_quantity = release_qty

            if product.warehouse_qty < release_qty:
                flash(f'Error: Not enough warehouse stock for {product.name}. Requested: {req_item.quantity}, Released: {release_qty}, Available in warehouse: {product.warehouse_qty}', 'error')
                return redirect(url_for('requisitions.view_requisitions'))

            warehouse_before = product.warehouse_qty

            batches = sorted(product.warehouse_batches, key=lambda x: x.exp_date)

            for batch in batches:
                if remaining_quantity <= 0:
                    break
                if batch.quantity > 0:
                    deduct_amount = min(batch.quantity, remaining_quantity)
                    batch.quantity = batch.quantity - deduct_amount
                    remaining_quantity -= deduct_amount

            # Transfer from warehouse to store
            product.warehouse_qty -= release_qty
            if product.warehouse_qty < 0:
                product.warehouse_qty = 0
            product.store_qty += release_qty
            product.store_initial_qty = product.store_qty
            product.quantity = product.warehouse_qty + product.store_qty

            # Record warehouse release quantity on the item
            req_item.released_quantity = release_qty

            # Create or update initial ReceivingRecord linked to this requisition
            rec = ReceivingRecord.query.filter_by(
                requisition_item_id=req_item.id,
                requisition_id=requisition.id
            ).first()
            if not rec:
                rec = ReceivingRecord(
                    requisition_item_id=req_item.id,
                    requisition_id=requisition.id,
                    released_qty=release_qty,
                    received_qty=0.0,
                    variance_qty=-release_qty,
                    variance_type='short',
                    company_id=requisition.company_id,
                    status='pending'
                )
                db.session.add(rec)
            else:
                rec.released_qty = release_qty
                rec.variance_qty = (rec.received_qty or 0.0) - release_qty

            db.session.add(
                RequisitionBatchDeduction(
                    requisition_item_id=req_item.id,
                    total_current_qty=warehouse_before,
                    requested_qty=req_item.quantity,
                    remaining_qty=product.warehouse_qty
                )
            )

            history_record = ProductHistory(
                product_id=req_item.product_id,
                trxn_date=datetime.now(ZoneInfo("Asia/Manila")),
                trxn_code='TRANS OUT',
                payee=requisition.branch or 'Unknown',
                quantity_in=0.0,
                quantity_out=release_qty,
                net_change=-release_qty,
                reference_id=requisition.id,
                reference_type='requisition'
            )
            history_record.company_id = requisition.company_id
            db.session.add(history_record)

        # ── Process optional items added during approval ──
        opt_idx = 0
        while True:
            pid_key = f'opt_product_id_{opt_idx}'
            rel_key = f'opt_released_{opt_idx}'

            raw_pid = request.form.get(pid_key, '').strip()
            if not raw_pid:
                break

            try:
                product_id = int(raw_pid)
            except (ValueError, TypeError):
                flash(f'Invalid product for optional item #{opt_idx + 1}.', 'error')
                return redirect(url_for('requisitions.view_requisitions'))

            raw_released = request.form.get(rel_key, '').strip()
            if not raw_released:
                opt_idx += 1
                continue

            try:
                opt_release_qty = float(raw_released)
            except ValueError:
                flash(f'Invalid released qty for optional item #{opt_idx + 1}.', 'error')
                return redirect(url_for('requisitions.view_requisitions'))

            if opt_release_qty <= 0:
                opt_idx += 1
                continue

            product = Product.query.get(product_id)
            if not product:
                flash(f'Product #{product_id} not found for optional item.', 'error')
                return redirect(url_for('requisitions.view_requisitions'))

            if product.quantity < opt_release_qty:
                flash(f'Not enough stock for optional item {product.name}. Released: {opt_release_qty}, Available: {product.quantity}', 'error')
                return redirect(url_for('requisitions.view_requisitions'))

            # Create optional RequisitionItem
            opt_item = RequisitionItem(
                requisition_id=requisition.id,
                product_id=product_id,
                quantity=opt_release_qty,
                released_quantity=opt_release_qty,
                uom=product.uom,
                is_optional=True,
            )
            db.session.add(opt_item)
            db.session.flush()

            # Create ReceivingRecord for optional item
            opt_rec = ReceivingRecord(
                requisition_item_id=opt_item.id,
                requisition_id=requisition.id,
                released_qty=opt_release_qty,
                received_qty=0.0,
                variance_qty=-opt_release_qty,
                variance_type='short',
                company_id=requisition.company_id,
                status='pending'
            )
            db.session.add(opt_rec)

            # Deduct stock
            remaining_opt = opt_release_qty
            opt_batches = sorted(product.warehouse_batches, key=lambda x: x.exp_date)
            for batch in opt_batches:
                if remaining_opt <= 0:
                    break
                if batch.quantity > 0:
                    deduct = min(batch.quantity, remaining_opt)
                    batch.quantity -= deduct
                    remaining_opt -= deduct

            product.quantity -= opt_release_qty

            # ProductHistory
            opt_history = ProductHistory(
                product_id=product_id,
                trxn_date=datetime.now(ZoneInfo("Asia/Manila")),
                trxn_code='TRANS OUT',
                payee=f"OPTIONAL-{requisition.branch or requisition.id}",
                quantity_in=0.0,
                quantity_out=opt_release_qty,
                net_change=-opt_release_qty,
                reference_id=requisition.id,
                reference_type='requisition_optional',
                company_id=requisition.company_id,
            )
            db.session.add(opt_history)

            opt_idx += 1

        # Set approval date and delivery date/time
        requisition.date_approved = datetime.now(ZoneInfo("Asia/Manila"))
        requisition.date_of_delivery = date_of_delivery

    # Update the status
    requisition.status = new_status
    db.session.commit()
    
    # Show flash message based on status
    if new_status == 'approved':
        flash(f'Requisition #{requisition.id} has been approved successfully!', 'success')
    else:
        flash(f'Requisition #{requisition.id} has been {new_status}.', 'warning')

    # Send email notification to the requester about status update
    try:
        # Find the requester by the requisition's company context. The branch
        # field is a branch/franchise label and is not guaranteed to match the
        # related company's name.
        user = User.query.filter(
            User.company_id == requisition.company_id,
            db.or_(
                User.full_name == requisition.requested_by,
                User.username == requisition.requested_by
            )
        ).first()
        
        if user and user.email:
            # Prepare email content based on status
            if new_status == 'approved':
                subject = f"Requisition #{requisition.id} - APPROVED!"
                body = f"""
Dear {requisition.requested_by},

Great news! Your requisition has been APPROVED.

REQUISITION DETAILS:
Requisition ID: #{requisition.id}
Date Submitted: {requisition.date_created.strftime('%B %d, %Y at %I:%M %p')}
Franchise Name: {requisition.branch}
Status: APPROVED
Approved On: {datetime.now(ZoneInfo("Asia/Manila")).strftime('%B %d, %Y at %I:%M %p')}

Expect a call or email from our team regarding delivery/pickup arrangements.

If you have any questions, please contact your administrator.

Thank you for using our inventory system.

Best regards,
iCount Inventory System
                """
            else:
                # Status is declined
                subject = f"Requisition #{requisition.id} - Status Update"
                body = f"""
Dear {requisition.requested_by},

Your requisition status has been updated.

REQUISITION DETAILS:
Requisition ID: #{requisition.id}
Date Submitted: {requisition.date_created.strftime('%B %d, %Y at %I:%M %p')}
Franchise Name: {requisition.branch}
Status: {new_status.title()}
Updated On: {datetime.now(ZoneInfo("Asia/Manila")).strftime('%B %d, %Y at %I:%M %p')}

REQUESTED ITEMS:
"""
                # Add items list
                for req_item in requisition.items:
                    body += f"• {req_item.product.name} - {req_item.quantity} {req_item.uom}\n"
                
                body += f"""

If you have any questions about this decision, please contact your administrator.

Thank you for using our inventory system.

Best regards,
iCount Inventory System
                """
            
            # Create and send email
            msg = Message(
                subject=subject,
                recipients=[user.email],
                body=body.strip(),
                sender=current_app.config['MAIL_DEFAULT_SENDER']
            )
            
            mail.send(msg)
            
    except Exception as e:
        # Log the error but don't fail the status update
        print(f"Failed to send status update email: {str(e)}")
        # You might want to log this error properly in production

    # Send in-app notification to the requester
    try:
        notif_user = User.query.filter(
            User.company_id == requisition.company_id,
            db.or_(
                User.full_name == requisition.requested_by,
                User.username == requisition.requested_by
            )
        ).first()
        if notif_user:
            if new_status == 'approved':
                create_notification(
                    user_id=notif_user.id,
                    title=f'Requisition #{requisition.id} Approved',
                    message=f'Your requisition for {len(requisition.items)} item(s) has been approved.',
                    type='success',
                    reference_type='requisition',
                    reference_id=requisition.id
                )
            else:
                create_notification(
                    user_id=notif_user.id,
                    title=f'Requisition #{requisition.id} {new_status.title()}',
                    message=f'Your requisition for {len(requisition.items)} item(s) has been {new_status}.',
                    type='danger' if new_status == 'declined' else 'warning',
                    reference_type='requisition',
                    reference_id=requisition.id
                )
    except Exception as e:
        print(f"Failed to create notification: {str(e)}")

    # Determine action label for logging
    action_label = "Approved" if new_status == "approved" else "Declined"

    # Log activity (clean and scalable format)
    log_activity(
        action=f"{action_label} Requisition",
        details=(
            f"Requisition <strong>#{requisition.id}</strong> by <strong>{requisition.requested_by}</strong> "
            f"was <strong>{action_label.lower()}</strong> with <strong>{len(requisition.items)} item(s)</strong>."
        )
    )

    return redirect(url_for('requisitions.view_requisitions'))


@requisitions.route('/dispatch/<int:requisition_id>', methods=['POST'])
@login_required
@user_redirect_to_requisition
def dispatch_requisition(requisition_id):
    """Mark an approved requisition as Dispatched (physically released from warehouse)."""
    requisition = Requisition.query.get_or_404(requisition_id)

    if requisition.status != 'approved':
        return jsonify({'success': False, 'message': 'Only approved requisitions can be dispatched.'}), 400

    if requisition.company_id != current_user.company_id and current_user.role != 'SYS-Admin':
        return jsonify({'success': False, 'message': 'Access denied.'}), 403

    requisition.status = 'Dispatched'
    db.session.commit()

    log_activity(
        action="Dispatched Requisition",
        details=f"Requisition <strong>#{requisition.id}</strong> by <strong>{requisition.requested_by}</strong> was <strong>dispatched</strong> from warehouse."
    )

    flash(f'Requisition #{requisition.id} marked as Dispatched.', 'success')
    return redirect(url_for('requisitions.view_requisitions'))


@requisitions.route('/print_delivery_form/<int:requisition_id>')
@login_required
@user_redirect_to_requisition
def print_delivery_form(requisition_id):
    requisition = Requisition.query.get_or_404(requisition_id)

    if requisition.status not in ('approved', 'Dispatched', 'Partial', 'Delivered'):
        return "Only approved or dispatched requisitions can be printed.", 403

    return render_template('shared/print_form.html', requisition=requisition)


@requisitions.route('/delete_requisition/<int:requisition_id>', methods=['POST'])
@login_required
@sys_admin_required
def delete_requisition(requisition_id):
    """Delete an approved requisition"""
    requisition = Requisition.query.get_or_404(requisition_id)
    
    if requisition.status not in ['approved', 'rejected', 'Dispatched', 'Partial', 'Delivered']:
        return jsonify({
            'success': False, 
            'message': 'Only approved, rejected, dispatched, or delivered requisitions can be deleted.'
        }), 400
    
    try:
        # Remove activity logging
        # log_activity(
        #     action="Deleted Requisition",
        #     details=(
        #         f"Requisition <strong>#{requisition.id}</strong> by <strong>{requisition.requested_by}</strong> "
        #         f"was <strong>deleted</strong> by admin <strong>{current_user.full_name}</strong>."
        #     )
        # )

        # Delete the requisition (cascade will handle related items)
        db.session.delete(requisition)
        db.session.commit()

        # Add flash message for normal form POSTs
        if request.accept_mimetypes.accept_html and not request.is_json:
            flash('Requisition deleted successfully.', 'success')
            return redirect(url_for('requisitions.view_requisitions'))

        return jsonify({
            'success': True,
            'message': 'Requisition deleted successfully.'
        })
        
    except Exception as e:
        db.session.rollback()
        print(f"Error deleting requisition: {str(e)}")
        return jsonify({
            'success': False,
            'message': 'An error occurred while deleting the requisition.'
        }), 500


# ═══════════════════════════════════════════════════════════════════
# WAREHOUSE ADMIN: INTER-COMPANY TRANSFER REQUISITION ROUTES
# ═══════════════════════════════════════════════════════════════════

def wh_admin_only(view_func):
    """Ensure only WH-Admin can access inter-company transfer requisitions"""
    from functools import wraps
    @wraps(view_func)
    def decorated_view(*args, **kwargs):
        if not current_user.is_authenticated:
            return redirect(url_for('auth.login'))
        if getattr(current_user, 'role', None) != 'WH-Admin':
            flash('Access denied. Only Warehouse Administrators can request inter-company product transfers.', 'error')
            return redirect(url_for('main.dashboard'))
        return view_func(*args, **kwargs)
    return decorated_view


@requisitions.route('/transfer_form', methods=['GET'])
@login_required
@wh_admin_only
def transfer_requisition_form():
    """Display the inter-company transfer requisition wizard for WH-Admin"""
    companies = Company.query.order_by(Company.name.asc()).all()
    if not companies:
        flash('No registered companies available for transfers.', 'warning')
        return redirect(url_for('requisitions.view_requisitions'))

    # Default from company (prefer current user's company or first company)
    default_from_id = current_user.company_id if current_user.company_id else companies[0].id
    default_to_id = None
    for c in companies:
        if c.id != default_from_id:
            default_to_id = c.id
            break

    initial_products = Product.query.filter_by(company_id=default_from_id).order_by(Product.name.asc()).all()
    now = datetime.now(ZoneInfo("Asia/Manila"))

    return render_template(
        'warehouse/transfer_requisition_form.html',
        companies=companies,
        default_from_id=default_from_id,
        default_to_id=default_to_id,
        initial_products=initial_products,
        now=now
    )


@requisitions.route('/api/company_products/<int:company_id>', methods=['GET'])
@login_required
@wh_admin_only
def get_company_products_api(company_id):
    """Return available products and warehouse stock for the selected source company"""
    company = Company.query.get_or_404(company_id)
    products = Product.query.filter_by(company_id=company_id).order_by(Product.name.asc()).all()

    product_list = []
    for p in products:
        product_list.append({
            'id': p.id,
            'name': p.name,
            'barcode': p.barcode or '',
            'uom': p.uom or 'unit',
            'category': p.account_title or 'General',
            'warehouse_qty': float(p.warehouse_qty or 0.0),
            'store_qty': float(p.store_qty or 0.0),
            'quantity': float(p.quantity or 0.0)
        })

    return jsonify({
        'success': True,
        'company': {
            'id': company.id,
            'name': company.name,
            'franchise_name': company.franchise_name or ''
        },
        'products': product_list
    })


@requisitions.route('/submit_transfer_requisition', methods=['POST'])
@login_required
@wh_admin_only
def submit_transfer_requisition():
    """Submit a company-to-company transfer requisition created by WH-Admin"""
    try:
        from_company_id = int(request.form.get('from_company_id'))
        to_company_id = int(request.form.get('to_company_id'))
    except (TypeError, ValueError):
        return jsonify({'success': False, 'message': 'Please select valid source and destination companies.'}), 400

    if from_company_id == to_company_id:
        return jsonify({'success': False, 'message': 'Source (From) company and Destination (To) company must be different.'}), 400

    from_company = Company.query.get(from_company_id)
    to_company = Company.query.get(to_company_id)
    if not from_company or not to_company:
        return jsonify({'success': False, 'message': 'One or both companies could not be found.'}), 404

    items_json = request.form.get('items_json')
    if not items_json:
        return jsonify({'success': False, 'message': 'No items selected for transfer.'}), 400

    try:
        items = json.loads(items_json)
    except Exception:
        return jsonify({'success': False, 'message': 'Invalid items format submitted.'}), 400

    if not items or len(items) == 0:
        return jsonify({'success': False, 'message': 'Please add at least one product with quantity > 0.'}), 400

    contact_number = request.form.get('contact_number', '').strip()
    transfer_date_str = request.form.get('transfer_date', '').strip()
    notes = request.form.get('notes', '').strip()
    station = request.form.get('station', '').strip() or 'Warehouse Transfer'

    date_of_delivery = None
    if transfer_date_str:
        try:
            date_of_delivery = datetime.strptime(transfer_date_str, '%Y-%m-%d')
        except Exception:
            pass

    branch_desc = f"Transfer: {from_company.name} -> {to_company.name}"

    try:
        requisition = Requisition(
            requested_by=current_user.full_name,
            status='Pending',
            contact_number=contact_number,
            branch=branch_desc,
            station=station,
            company_id=from_company_id,
            destination_company_id=to_company_id,
            requisition_type='transfer',
            date_of_delivery=date_of_delivery
        )
        db.session.add(requisition)
        db.session.flush()

        valid_items_count = 0
        for item in items:
            try:
                qty = float(item.get('quantity', 0))
            except (ValueError, TypeError):
                continue
            if qty <= 0:
                continue

            p_id = int(item['product_id'])
            product = Product.query.filter_by(id=p_id, company_id=from_company_id).first()
            if not product:
                continue

            ri = RequisitionItem(
                requisition_id=requisition.id,
                product_id=p_id,
                quantity=qty,
                uom=item.get('uom') or product.uom or 'unit'
            )
            db.session.add(ri)
            valid_items_count += 1

        if valid_items_count == 0:
            db.session.rollback()
            return jsonify({'success': False, 'message': 'No valid product quantities found in the request.'}), 400

        db.session.commit()

        # Log activity
        log_activity(
            action="Transfer Requisition Submitted",
            details=f"Transfer Requisition #{requisition.id} ({from_company.name} -> {to_company.name}) with {valid_items_count} items submitted by {current_user.full_name}"
        )

        # Notify admins
        try:
            create_notification(
                title="New Transfer Requisition",
                message=f"Warehouse Admin {current_user.full_name} submitted Transfer Requisition #{requisition.id} from {from_company.name} to {to_company.name}.",
                user_id=None,
                company_id=from_company_id,
                link=url_for('requisitions.view_requisitions')
            )
        except Exception as notif_err:
            print("Transfer notification error:", notif_err)

        return jsonify({
            'success': True,
            'message': f'Transfer Requisition #{requisition.id} successfully created!',
            'requisition_id': requisition.id
        })

    except Exception as e:
        db.session.rollback()
        print(f"Error submitting transfer requisition: {e}")
        return jsonify({'success': False, 'message': f'Server error: {str(e)}'}), 500
