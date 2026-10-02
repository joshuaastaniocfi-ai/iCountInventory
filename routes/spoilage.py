# Standard library imports
from datetime import datetime
import json
import os
import uuid
from zoneinfo import ZoneInfo
import csv
import io

# Third-party imports
from flask import (
    Blueprint, render_template, request, jsonify, flash, redirect,
    url_for, current_app, Response
)
from flask_login import login_required, current_user
from werkzeug.utils import secure_filename
from sqlalchemy import desc, or_

# Local imports
from extensions import db
from models import (
    Product, Spoilage, WarehouseProductBatch, StoreProductBatch,
    ProductHistory, User, ActivityLog
)
from helpers import log_activity, create_notification

# Allowed extensions for image uploads
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'webp'}

# Create blueprint
spoilage = Blueprint('spoilage', __name__, url_prefix='/spoilage')


def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


def get_spoilage_upload_dir():
    upload_dir = os.path.join(current_app.root_path, 'static', 'uploads', 'spoilage')
    os.makedirs(upload_dir, exist_ok=True)
    return upload_dir


def check_spoilage_access():
    """Ensure user has a permitted role to view/declare spoilage."""
    return current_user.is_authenticated and current_user.role in [
        'SYS-Admin', 'WH-Admin', 'Company-Admin', 'User'
    ]


@spoilage.route('/')
@login_required
def spoilage_records():
    """View list of spoilage declarations with search, filters, and summary stats."""
    if not check_spoilage_access():
        flash("You do not have permission to view spoilage records.", "error")
        return redirect(url_for('main.dashboard'))

    # Base query scoped by company
    query = Spoilage.query
    if not (current_user.role == 'SYS-Admin' and current_user.company_id is None):
        query = query.filter(Spoilage.company_id == current_user.company_id)

    # Role-based default visibility:
    # WH-Admin only sees warehouse spoilage unless company admin / sys admin
    # User (store) only sees store spoilage
    selected_side = request.args.get('side', '').strip().lower()
    if current_user.role == 'WH-Admin':
        query = query.filter(Spoilage.side == 'warehouse')
        selected_side = 'warehouse'
    elif current_user.role == 'User':
        query = query.filter(Spoilage.side == 'store')
        selected_side = 'store'
    elif selected_side in ['warehouse', 'store']:
        query = query.filter(Spoilage.side == selected_side)

    # Search filter
    search = request.args.get('search', '').strip()
    if search:
        search_like = f"%{search}%"
        query = query.join(Product).join(User, Spoilage.declared_by == User.id).filter(
            or_(
                Product.name.ilike(search_like),
                Product.barcode.ilike(search_like),
                User.full_name.ilike(search_like),
                Spoilage.reason.ilike(search_like),
                Spoilage.remarks.ilike(search_like)
            )
        )

    # Date range filters
    start_date_str = request.args.get('start_date', '').strip()
    end_date_str = request.args.get('end_date', '').strip()

    if start_date_str:
        try:
            start_date = datetime.strptime(start_date_str, '%Y-%m-%d')
            query = query.filter(Spoilage.created_at >= start_date)
        except ValueError:
            pass

    if end_date_str:
        try:
            end_date = datetime.strptime(end_date_str, '%Y-%m-%d').replace(hour=23, minute=59, second=59)
            query = query.filter(Spoilage.created_at <= end_date)
        except ValueError:
            pass

    # Order newest first
    records = query.order_by(desc(Spoilage.created_at)).all()

    # Pre-calculate summary statistics for this company
    base_stats_query = Spoilage.query
    if not (current_user.role == 'SYS-Admin' and current_user.company_id is None):
        base_stats_query = base_stats_query.filter(Spoilage.company_id == current_user.company_id)

    total_records = base_stats_query.count()
    wh_records_count = base_stats_query.filter(Spoilage.side == 'warehouse').count()
    store_records_count = base_stats_query.filter(Spoilage.side == 'store').count()

    total_wh_qty = db.session.query(
        db.func.coalesce(db.func.sum(Spoilage.quantity), 0.0)
    ).filter(
        Spoilage.side == 'warehouse',
        (Spoilage.company_id == current_user.company_id) if current_user.company_id else True
    ).scalar() or 0.0

    total_store_qty = db.session.query(
        db.func.coalesce(db.func.sum(Spoilage.quantity), 0.0)
    ).filter(
        Spoilage.side == 'store',
        (Spoilage.company_id == current_user.company_id) if current_user.company_id else True
    ).scalar() or 0.0

    # Get products for declaration modal dropdown
    if current_user.role == 'SYS-Admin' and current_user.company_id is None:
        products = Product.query.order_by(Product.name.asc()).all()
    else:
        products = Product.query.filter_by(company_id=current_user.company_id).order_by(Product.name.asc()).all()

    now_ph = datetime.now(ZoneInfo("Asia/Manila"))

    return render_template(
        'spoilage/index.html',
        records=records,
        products=products,
        now=now_ph,
        total_records=total_records,
        wh_records_count=wh_records_count,
        store_records_count=store_records_count,
        total_wh_qty=round(total_wh_qty, 2),
        total_store_qty=round(total_store_qty, 2),
        selected_side=selected_side,
        search=search,
        start_date=start_date_str,
        end_date=end_date_str
    )


@spoilage.route('/api/product-info/<int:product_id>')
@login_required
def api_product_info(product_id):
    """Return product details, warehouse stock, store stock, and active batches with exp dates."""
    if not check_spoilage_access():
        return jsonify({'status': 'error', 'message': 'Access denied'}), 403

    product = Product.query.get(product_id)
    if not product:
        return jsonify({'status': 'error', 'message': 'Product not found'}), 404

    if current_user.company_id and product.company_id != current_user.company_id:
        return jsonify({'status': 'error', 'message': 'Product does not belong to your company'}), 403

    # Active warehouse batches
    wh_batches = []
    for b in product.warehouse_batches:
        if b.quantity > 0:
            wh_batches.append({
                'id': b.id,
                'exp_date': b.exp_date.strftime('%Y-%m-%d') if b.exp_date else None,
                'quantity': b.quantity,
                'sub_barcode': b.sub_barcode or ''
            })
    wh_batches.sort(key=lambda x: x['exp_date'] or '9999-12-31')

    # Active store batches
    st_batches = []
    for b in product.store_batches:
        if b.quantity > 0:
            st_batches.append({
                'id': b.id,
                'exp_date': b.exp_date.strftime('%Y-%m-%d') if b.exp_date else None,
                'quantity': b.quantity,
                'sub_barcode': b.sub_barcode or ''
            })
    st_batches.sort(key=lambda x: x['exp_date'] or '9999-12-31')

    return jsonify({
        'status': 'success',
        'product': {
            'id': product.id,
            'name': product.name,
            'barcode': product.barcode,
            'uom': product.uom or 'units',
            'warehouse_qty': product.warehouse_qty,
            'store_qty': product.store_qty,
            'total_qty': product.quantity,
            'station': product.station or '',
            'warehouse_batches': wh_batches,
            'store_batches': st_batches
        }
    })


@spoilage.route('/api/record/<int:spoilage_id>')
@login_required
def api_spoilage_detail(spoilage_id):
    """Return detailed JSON for a spoilage record."""
    if not check_spoilage_access():
        return jsonify({'status': 'error', 'message': 'Access denied'}), 403

    record = Spoilage.query.get(spoilage_id)
    if not record:
        return jsonify({'status': 'error', 'message': 'Record not found'}), 404

    if current_user.company_id and record.company_id != current_user.company_id:
        return jsonify({'status': 'error', 'message': 'Access denied'}), 403

    images_urls = [
        url_for('static', filename=f'uploads/spoilage/{img}')
        for img in record.image_list
    ]

    return jsonify({
        'status': 'success',
        'record': {
            'id': record.id,
            'product_name': record.product.name if record.product else 'Unknown',
            'product_barcode': record.product.barcode if record.product else '',
            'uom': record.product.uom if record.product else 'units',
            'side': record.side,
            'quantity': record.quantity,
            'declaration_date': (record.declaration_date or record.created_at.date()).strftime('%Y-%m-%d') if (record.declaration_date or record.created_at) else None,
            'exp_date': record.exp_date.strftime('%Y-%m-%d') if record.exp_date else None,
            'reason': record.reason or 'Unspecified',
            'remarks': record.remarks or '',
            'images': images_urls,
            'declared_by': record.user.full_name if record.user else 'Unknown',
            'declared_by_role': record.user.role if record.user else '',
            'created_at': record.created_at.strftime('%Y-%m-%d %I:%M %p') if record.created_at else ''
        }
    })


@spoilage.route('/declare', methods=['POST'])
@login_required
def declare_spoilage():
    """Declare a product for spoilage, upload images, deduct inventory, and record history."""
    if not check_spoilage_access():
        return jsonify({'status': 'error', 'message': 'Permission denied.'}), 403

    is_ajax = (
        request.headers.get('X-Requested-With') == 'XMLHttpRequest' or
        request.accept_mimetypes.best_match(['application/json', 'text/html']) == 'application/json'
    )

    try:
        product_id = request.form.get('product_id')
        quantity_str = request.form.get('quantity')
        declaration_date_str = request.form.get('declaration_date', '').strip()
        exp_date_str = request.form.get('exp_date', '').strip()
        reason = request.form.get('reason', '').strip()
        remarks = request.form.get('remarks', '').strip()

        # ── 1. Validate required basic fields ──
        if not product_id:
            msg = 'Product is required.'
            return jsonify({'status': 'error', 'message': msg}), 400 if is_ajax else flash(msg, 'error') or redirect(url_for('spoilage.spoilage_records'))

        # Robust quantity parsing: handle single or multiple form values
        qty_list = request.form.getlist('quantity')
        quantity_str = None
        for q in reversed(qty_list):
            if q and str(q).strip():
                quantity_str = str(q).strip()
                break
        if not quantity_str:
            quantity_str = (request.form.get('quantity') or '').strip()

        try:
            quantity = float(quantity_str)
            if quantity <= 0:
                raise ValueError()
        except (TypeError, ValueError):
            msg = f"Quantity must be a positive number greater than zero."
            return jsonify({'status': 'error', 'message': msg}), 400 if is_ajax else flash(msg, 'error') or redirect(url_for('spoilage.spoilage_records'))

        # ── 2. Determine side based on user role ──
        # WH-Admin -> warehouse
        # Store (User) -> store
        # Company-Admin / SYS-Admin -> chosen option (warehouse or store)
        if current_user.role == 'WH-Admin':
            side = 'warehouse'
        elif current_user.role == 'User':
            side = 'store'
        elif current_user.role in ['Company-Admin', 'SYS-Admin']:
            side = request.form.get('side', '').strip().lower()
            if side not in ['warehouse', 'store']:
                msg = 'Please choose whether the spoilage is from Warehouse or Store inventory.'
                return jsonify({'status': 'error', 'message': msg}), 400 if is_ajax else flash(msg, 'error') or redirect(url_for('spoilage.spoilage_records'))
        else:
            return jsonify({'status': 'error', 'message': 'Unauthorized role.'}), 403

        # ── 3. Find and validate product ──
        product = Product.query.get(product_id)
        if not product:
            msg = 'Product not found.'
            return jsonify({'status': 'error', 'message': msg}), 404 if is_ajax else flash(msg, 'error') or redirect(url_for('spoilage.spoilage_records'))

        if current_user.company_id and product.company_id != current_user.company_id:
            msg = 'You cannot declare spoilage for products in other companies.'
            return jsonify({'status': 'error', 'message': msg}), 403 if is_ajax else flash(msg, 'error') or redirect(url_for('spoilage.spoilage_records'))

        # ── 4. Validate inventory sufficiency on the chosen side ──
        if side == 'warehouse':
            if product.warehouse_qty < quantity:
                msg = f"Insufficient warehouse stock for '{product.name}'. Requested: {quantity} {product.uom}, Available: {product.warehouse_qty} {product.uom}."
                return jsonify({'status': 'error', 'message': msg}), 400 if is_ajax else flash(msg, 'error') or redirect(url_for('spoilage.spoilage_records'))
        elif side == 'store':
            if product.store_qty < quantity:
                msg = f"Insufficient store stock for '{product.name}'. Requested: {quantity} {product.uom}, Available: {product.store_qty} {product.uom}."
                return jsonify({'status': 'error', 'message': msg}), 400 if is_ajax else flash(msg, 'error') or redirect(url_for('spoilage.spoilage_records'))

        # ── 5. Parse declaration date and expiry date (if provided) ──
        parsed_decl_date = now_ph.date() if 'now_ph' in locals() else datetime.now(ZoneInfo("Asia/Manila")).date()
        if declaration_date_str:
            try:
                parsed_decl_date = datetime.strptime(declaration_date_str, '%Y-%m-%d').date()
            except ValueError:
                pass

        parsed_exp_date = None
        if exp_date_str:
            try:
                parsed_exp_date = datetime.strptime(exp_date_str, '%Y-%m-%d').date()
            except ValueError:
                pass

        # ── 6. Handle Image Uploads (Images are REQUIRED per specification) ──
        files = request.files.getlist('images')
        # Also check fallback key 'image'
        if not files or not any(f and f.filename for f in files):
            files = request.files.getlist('image')

        valid_files = [f for f in files if f and f.filename and allowed_file(f.filename)]
        if not valid_files:
            msg = 'At least one photo/image is required as proof of spoiled items.'
            return jsonify({'status': 'error', 'message': msg}), 400 if is_ajax else flash(msg, 'error') or redirect(url_for('spoilage.spoilage_records'))

        upload_dir = get_spoilage_upload_dir()
        saved_filenames = []
        now_ts = int(datetime.now().timestamp())

        for f in valid_files:
            orig_name = secure_filename(f.filename)
            ext = orig_name.rsplit('.', 1)[1].lower() if '.' in orig_name else 'jpg'
            new_filename = f"spoil_{product.id}_{now_ts}_{uuid.uuid4().hex[:8]}.{ext}"
            file_dest = os.path.join(upload_dir, new_filename)
            f.save(file_dest)
            saved_filenames.append(new_filename)

        now_ph = datetime.now(ZoneInfo("Asia/Manila"))

        # ── 7. Deduct from system inventory & batches ──
        if side == 'warehouse':
            product.warehouse_qty -= quantity
            if product.warehouse_qty < 0:
                product.warehouse_qty = 0
            product.quantity = product.warehouse_qty + product.store_qty

            # Deduct from WarehouseProductBatch
            remaining_to_deduct = quantity
            if parsed_exp_date:
                matching_batches = WarehouseProductBatch.query.filter_by(
                    product_id=product.id,
                    exp_date=parsed_exp_date
                ).filter(WarehouseProductBatch.quantity > 0).all()

                for b in matching_batches:
                    if remaining_to_deduct <= 0:
                        break
                    deduct_amt = min(b.quantity, remaining_to_deduct)
                    b.quantity -= deduct_amt
                    remaining_to_deduct -= deduct_amt

            if remaining_to_deduct > 0:
                other_batches = WarehouseProductBatch.query.filter_by(
                    product_id=product.id
                ).filter(WarehouseProductBatch.quantity > 0).order_by(WarehouseProductBatch.exp_date.asc()).all()

                for b in other_batches:
                    if remaining_to_deduct <= 0:
                        break
                    deduct_amt = min(b.quantity, remaining_to_deduct)
                    b.quantity -= deduct_amt
                    remaining_to_deduct -= deduct_amt

        elif side == 'store':
            product.store_qty -= quantity
            if product.store_qty < 0:
                product.store_qty = 0
            product.quantity = product.warehouse_qty + product.store_qty

            # Deduct from StoreProductBatch (if active store batches exist)
            remaining_to_deduct = quantity
            if parsed_exp_date:
                matching_batches = StoreProductBatch.query.filter_by(
                    product_id=product.id,
                    exp_date=parsed_exp_date
                ).filter(StoreProductBatch.quantity > 0).all()

                for b in matching_batches:
                    if remaining_to_deduct <= 0:
                        break
                    deduct_amt = min(b.quantity, remaining_to_deduct)
                    b.quantity -= deduct_amt
                    remaining_to_deduct -= deduct_amt

            if remaining_to_deduct > 0:
                other_batches = StoreProductBatch.query.filter_by(
                    product_id=product.id
                ).filter(StoreProductBatch.quantity > 0).order_by(StoreProductBatch.exp_date.asc()).all()

                for b in other_batches:
                    if remaining_to_deduct <= 0:
                        break
                    deduct_amt = min(b.quantity, remaining_to_deduct)
                    b.quantity -= deduct_amt
                    remaining_to_deduct -= deduct_amt

        product.last_updated = now_ph

        # ── 8. Create Spoilage record ──
        spoilage_entry = Spoilage(
            product_id=product.id,
            side=side,
            quantity=quantity,
            exp_date=parsed_exp_date,
            declaration_date=parsed_decl_date,
            reason=reason or 'Spoilage',
            remarks=remarks,
            images=json.dumps(saved_filenames),
            declared_by=current_user.id,
            company_id=product.company_id,
            created_at=now_ph
        )
        db.session.add(spoilage_entry)
        db.session.flush()

        # ── 9. Record in ProductHistory (TRANS OUT) ──
        history_record = ProductHistory(
            product_id=product.id,
            trxn_date=now_ph,
            trxn_code='TRANS OUT',
            payee=f"Spoilage ({side.capitalize()}) - {reason or 'Damaged/Expired'}",
            quantity_in=0.0,
            quantity_out=quantity,
            net_change=-quantity,
            reference_id=spoilage_entry.id,
            reference_type='spoilage',
            created_at=now_ph,
            company_id=product.company_id
        )
        db.session.add(history_record)

        # ── 10. Log Activity ──
        log_activity(
            action="Declare Spoilage",
            details=(
                f"Declared spoilage of <strong>{quantity} {product.uom}</strong> for "
                f"<strong>{product.name}</strong> from <strong>{side.capitalize()}</strong>.<br>"
                f"Reason: {reason or 'Unspecified'} | Photos: {len(saved_filenames)} attached."
            )
        )

        # ── 11. Send Notifications to Admins ──
        try:
            if current_user.role in ['WH-Admin', 'User']:
                admins = User.query.filter_by(
                    company_id=product.company_id,
                    role='Company-Admin'
                ).all()
                for admin_u in admins:
                    if admin_u.id != current_user.id:
                        create_notification(
                            user_id=admin_u.id,
                            title=f"Spoilage Declared: {product.name}",
                            message=f"{current_user.full_name} ({current_user.role}) declared {quantity} {product.uom} spoiled from {side.capitalize()} inventory.",
                            type='warning',
                            reference_type='spoilage',
                            reference_id=spoilage_entry.id
                        )
        except Exception:
            pass

        # ── 12. Commit ──
        db.session.commit()

        success_msg = f"Spoilage of {quantity} {product.uom} declared successfully. Inventory deducted from {side.capitalize()}."
        if is_ajax:
            return jsonify({
                'status': 'success',
                'message': success_msg,
                'spoilage_id': spoilage_entry.id,
                'side': side,
                'new_warehouse_qty': product.warehouse_qty,
                'new_store_qty': product.store_qty,
                'new_total_qty': product.quantity
            })
        else:
            flash(success_msg, 'success')
            return redirect(url_for('spoilage.spoilage_records'))

    except Exception as e:
        db.session.rollback()
        err_msg = f"Failed to declare spoilage: {str(e)}"
        if is_ajax:
            return jsonify({'status': 'error', 'message': err_msg}), 500
        else:
            flash(err_msg, 'error')
            return redirect(url_for('spoilage.spoilage_records'))


@spoilage.route('/export')
@login_required
def export_spoilage():
    """Export spoilage records to CSV for audit and reporting."""
    if not check_spoilage_access():
        flash("Access denied.", "error")
        return redirect(url_for('main.dashboard'))

    query = Spoilage.query
    if not (current_user.role == 'SYS-Admin' and current_user.company_id is None):
        query = query.filter(Spoilage.company_id == current_user.company_id)

    side = request.args.get('side', '').strip().lower()
    if current_user.role == 'WH-Admin':
        query = query.filter(Spoilage.side == 'warehouse')
    elif current_user.role == 'User':
        query = query.filter(Spoilage.side == 'store')
    elif side in ['warehouse', 'store']:
        query = query.filter(Spoilage.side == side)

    records = query.order_by(desc(Spoilage.created_at)).all()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        'ID', 'Date of Declaration', 'Logged At', 'Product Name', 'Barcode', 'Inventory Side',
        'Quantity Spoiled', 'UOM', 'Expiry Date', 'Reason', 'Remarks',
        'Declared By', 'Role', 'Images Count'
    ])

    for r in records:
        writer.writerow([
            r.id,
            (r.declaration_date or r.created_at.date()).strftime('%Y-%m-%d') if (r.declaration_date or r.created_at) else '',
            r.created_at.strftime('%Y-%m-%d %H:%M:%S') if r.created_at else '',
            r.product.name if r.product else '',
            r.product.barcode if r.product else '',
            r.side.capitalize(),
            r.quantity,
            r.product.uom if r.product else '',
            r.exp_date.strftime('%Y-%m-%d') if r.exp_date else 'N/A',
            r.reason or '',
            r.remarks or '',
            r.user.full_name if r.user else '',
            r.user.role if r.user else '',
            len(r.image_list)
        ])

    csv_data = output.getvalue()
    filename = f"spoilage_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"

    return Response(
        csv_data,
        mimetype='text/csv',
        headers={'Content-Disposition': f'attachment; filename={filename}'}
    )
