# Standard library imports
import json
from datetime import datetime
from zoneinfo import ZoneInfo

# Third-party imports
from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify, current_app
from flask_login import login_required, current_user
from flask_mail import Message

# Local imports
from extensions import db, mail
from models import Product, Requisition, RequisitionItem, RequisitionBatchDeduction, User, ProductHistory, Company
from helpers import user_redirect_to_requisition, admin_required, sys_admin_required, log_activity, assign_company, create_notification

# Create blueprint with URL prefix as required by project specifications
requisitions = Blueprint('requisitions', __name__, url_prefix='/requisitions')


@requisitions.route('/requisition_form', methods=['GET'])
@login_required
def requisition_form():
    # Only allow User role to access requisition form
    if current_user.role not in ['User']:
        flash('Access denied. Only regular users can submit requisitions.', 'error')
        return redirect(url_for('main.dashboard'))
    
    # Check for flash messages from login
    login_success = request.args.get('login_success', 'false')
    
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
    
    return render_template('user/requisition_form.html', products=products, now=now, 
                         login_success=login_success, history_data=history_data)


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
    status = request.args.get('status', '').strip()
    search = request.args.get('q', '').strip()
    per_page = current_app.config.get('REQUISITIONS_PER_PAGE', 10)
    
    # Base query - modified to allow SYS-Admin to see all requisitions
    if current_user.role == 'User':
        # Regular users can only see their own requisitions
        query = Requisition.query.filter_by(
            requested_by=current_user.full_name,
            company_id=current_user.company_id
        )
    elif current_user.role == 'SYS-Admin':
        # SYS-Admin can see all requisitions across all companies
        query = Requisition.query
    else:
        # Other admins (WH-Admin, Company-Admin) can see all requisitions in their company
        query = Requisition.query.filter_by(company_id=current_user.company_id)
    
    # Apply status filter if provided
    if status:
        query = query.filter_by(status=status)
    
    # Apply search filter if provided
    if search:
        like = f"%{search}%"
        query = query.filter(db.or_(
            Requisition.requested_by.ilike(like),
            Requisition.branch.ilike(like)  # This now contains franchise name
        ))
    
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
        requisitions_json=requisitions_json
    )


@requisitions.route('/update_status/<int:requisition_id>', methods=['POST'])
@login_required
@user_redirect_to_requisition
def update_status(requisition_id):
    new_status = request.form['status']
    requisition = Requisition.query.get_or_404(requisition_id)

    # If trying to approve and requisition is not validated, prevent approval
    if new_status == 'approved' and not requisition.validated:
        flash(f'Error: Requisition #{requisition.id} must be validated through scanning before approval.', 'error')
        return redirect(url_for('requisitions.view_requisitions'))

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

            if product.quantity < release_qty:
                flash(f'Error: Not enough stock for {product.name}. Requested: {req_item.quantity}, Released: {release_qty}, Available: {product.quantity}', 'error')
                return redirect(url_for('requisitions.view_requisitions'))

            total_before_deduction = product.quantity

            batches = sorted(product.batches, key=lambda x: x.exp_date)

            for batch in batches:
                if remaining_quantity <= 0:
                    break
                if batch.quantity > 0:
                    deduct_amount = min(batch.quantity, remaining_quantity)
                    batch.quantity = batch.quantity - deduct_amount
                    remaining_quantity -= deduct_amount

            product.quantity = product.quantity - release_qty

            db.session.add(
                RequisitionBatchDeduction(
                    requisition_item_id=req_item.id,
                    total_current_qty=total_before_deduction,
                    requested_qty=req_item.quantity,
                    remaining_qty=product.quantity
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
                uom=product.uom,
                is_optional=True,
            )
            db.session.add(opt_item)
            db.session.flush()

            # Deduct stock
            remaining_opt = opt_release_qty
            opt_batches = sorted(product.batches, key=lambda x: x.exp_date)
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
        # Find the user who submitted the requisition
        # Since we only have the name, we'll try to find by name and company
        user = User.query.join(Company).filter(
            User.full_name == requisition.requested_by,
            Company.name == requisition.branch  # branch now contains franchise name
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
        notif_user = User.query.join(Company).filter(
            User.full_name == requisition.requested_by,
            Company.name == requisition.branch
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