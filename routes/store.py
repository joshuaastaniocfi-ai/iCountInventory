# Standard library imports
from datetime import datetime
from zoneinfo import ZoneInfo

# Third-party imports
from flask import Blueprint, render_template, jsonify, request
from flask_login import login_required, current_user

# Local imports
from extensions import db
from models import Product, StockAudit
from helpers import log_activity, assign_company

# Create blueprint
store = Blueprint('store', __name__, url_prefix='/store')


@store.route('/inventory_count')
@login_required
def inventory_count():
    """Store-side inventory counting page — accessible to all authorized roles."""
    # All roles can view inventory counts; only User role can submit counts
    if current_user.role not in ['User', 'WH-Admin', 'Company-Admin', 'SYS-Admin']:
        from flask import flash, redirect
        flash('Access denied.', 'error')
        return redirect('/dashboard')

    now = datetime.now(ZoneInfo("Asia/Manila"))
    return render_template('store/inventory_count.html', now=now, user_role=current_user.role)


@store.route('/count_inventory_data')
@login_required
def count_inventory_data():
    """Return all products for the store-side daily count form."""
    from models import Product

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
            'warehouse_qty': p.warehouse_qty,
            'store_qty': p.store_qty,
            'account_title': p.account_title
        })
    return jsonify({'success': True, 'products': data, 'count': len(data)})


@store.route('/submit_count', methods=['POST'])
@login_required
def submit_count():
    """Submit inventory count — only User role can submit counts."""
    if current_user.role != 'User':
        return jsonify({'status': 'error', 'message': 'Only Users can submit inventory counts.'}), 403

    from datetime import datetime as dt

    data = request.get_json()
    audits = data.get('audits', [])
    verified_by = data.get('verified_by', current_user.full_name)

    if not audits:
        return jsonify({'status': 'error', 'message': 'No counts provided.'}), 400

    batch_label = f"STORE-AUDIT-{dt.utcnow().strftime('%Y%m%d-%H%M%S')}"
    created = 0

    for entry in audits:
        product_id = entry.get('product_id')
        recorded_qty = entry.get('recorded_quantity', 0)
        actual_qty = entry.get('actual_quantity', 0)

        if product_id is None:
            continue

        # Warehouse vs Store breakdown
        wh_recorded = entry.get('warehouse_recorded_qty', 0)
        wh_actual = entry.get('warehouse_actual_qty', wh_recorded)
        st_recorded = entry.get('store_recorded_qty', 0)
        st_actual = entry.get('store_actual_qty', st_recorded)

        discrepancy = actual_qty - recorded_qty

        audit = StockAudit(
            product_id=product_id,
            recorded_quantity=recorded_qty,
            actual_quantity=actual_qty,
            discrepancy=discrepancy,
            warehouse_recorded_qty=wh_recorded,
            warehouse_actual_qty=wh_actual,
            store_recorded_qty=st_recorded,
            store_actual_qty=st_actual,
            verified_by=verified_by,
            batch_label=batch_label
        )

        # Assign company from product or current user
        product = Product.query.get(product_id)
        if product and product.company_id:
            audit.company_id = product.company_id
        elif current_user.company_id:
            audit.company_id = current_user.company_id
        else:
            continue

        db.session.add(audit)
        created += 1

    if created == 0:
        return jsonify({'status': 'error', 'message': 'No valid counts to submit.'}), 400

    try:
        db.session.commit()
        log_activity(
            action="Store Inventory Count",
            details=f"Store count batch <strong>{batch_label}</strong> submitted by <strong>{verified_by}</strong> — "
                    f"<span class='badge bg-info'>{created} products</span> counted"
        )
        return jsonify({'status': 'success', 'message': 'Count submitted.', 'batch': batch_label, 'count': created})
    except Exception as e:
        db.session.rollback()
        return jsonify({'status': 'error', 'message': str(e)}), 500
