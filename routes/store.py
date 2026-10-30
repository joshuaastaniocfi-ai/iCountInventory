# Standard library imports
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

# Third-party imports
from flask import Blueprint, render_template, jsonify, request, flash, redirect, url_for
from flask_login import login_required, current_user
from sqlalchemy import or_, desc, func

# Local imports
from extensions import db
from models import Product, StockAudit, Requisition, ActivityLog, StoreProductBatch, StoreProduction, ProductHistory
from helpers import log_activity, assign_company, generate_barcode

# Create blueprint
store = Blueprint('store', __name__, url_prefix='/store')


@store.route('/dashboard')
@login_required
def store_dashboard():
    """Store-side dashboard with inventory stats, charts, and activity."""
    now_ph = datetime.now(ZoneInfo('Asia/Manila'))
    today = now_ph.date()

    # Product query scoped to company
    if current_user.role == 'SYS-Admin' and current_user.company_id is None:
        product_query = Product.query
    else:
        product_query = Product.query.filter_by(company_id=current_user.company_id)

    # ── Stats ──
    total_products = product_query.count()
    products_with_store_stock = product_query.filter(Product.store_qty > 0).count()
    store_q = product_query.with_entities(db.func.coalesce(db.func.sum(Product.store_qty), 0)).scalar()

    # Low stock in store
    store_low_stock = product_query.filter(
        Product.store_qty > 0,
        Product.reorder_level > 0,
        Product.store_qty <= Product.reorder_level
    ).count()

    # Out of store stock
    store_out_of_stock = product_query.filter(Product.store_qty == 0).count()

    # Pending requisitions by this user
    my_pending = Requisition.query.filter_by(
        requested_by=current_user.full_name,
        status='Pending',
        company_id=current_user.company_id
    ).count() if current_user.company_id else 0

    # ── Chart: Store vs Warehouse stock (top 10 products) ──
    top_products = product_query.filter(
        (Product.store_qty > 0) | (Product.warehouse_qty > 0)
    ).order_by((Product.store_qty + Product.warehouse_qty).desc()).limit(10).all()

    chart_labels = [p.name[:18] for p in top_products]
    chart_store = [p.store_qty for p in top_products]
    chart_warehouse = [p.warehouse_qty for p in top_products]

    # ── Chart: Store stock by account title (pie) ──
    account_totals = db.session.query(
        Product.account_title,
        db.func.coalesce(db.func.sum(Product.store_qty), 0)
    ).filter(Product.store_qty > 0)
    if current_user.company_id:
        account_totals = account_totals.filter(Product.company_id == current_user.company_id)
    account_totals = account_totals.group_by(Product.account_title).order_by(
        db.func.sum(Product.store_qty).desc()
    ).limit(8).all()

    account_labels = [a[0] or 'Uncategorized' for a in account_totals]
    account_values = [float(a[1]) for a in account_totals]

    # ── Low stock table (store side) ──
    low_stock_products = product_query.filter(
        Product.store_qty > 0,
        Product.reorder_level > 0,
        Product.store_qty <= Product.reorder_level
    ).order_by(Product.store_qty.asc()).limit(10).all()

    # ── My recent requisitions ──
    my_requisitions = Requisition.query.filter_by(
        company_id=current_user.company_id
    ).filter(
        Requisition.requested_by == current_user.full_name
    ).order_by(Requisition.date_created.desc()).limit(5).all() if current_user.company_id else []

    # ── Recent activity ──
    recent_logs = ActivityLog.query.filter_by(
        company_id=current_user.company_id
    ).order_by(ActivityLog.timestamp.desc()).limit(8).all() if current_user.company_id else []

    # ── Store inventory top movers (highest store qty) ──
    in_stock_products = product_query.filter(Product.store_qty > 0).order_by(
        Product.store_qty.desc()
    ).limit(10).all()

    return render_template('store/dashboard.html',
        now=now_ph,
        total_products=total_products,
        products_with_store_stock=products_with_store_stock,
        total_store_qty=store_q,
        store_low_stock=store_low_stock,
        store_out_of_stock=store_out_of_stock,
        my_pending=my_pending,
        chart_labels=chart_labels,
        chart_store=chart_store,
        chart_warehouse=chart_warehouse,
        account_labels=account_labels,
        account_values=account_values,
        low_stock_products=low_stock_products,
        my_requisitions=my_requisitions,
        recent_logs=recent_logs,
        in_stock_products=in_stock_products,
    )


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
        st_recorded = entry.get('store_recorded_qty', recorded_qty)
        st_actual = entry.get('store_actual_qty', actual_qty)

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


# ═══════════════════════════════════════════════════════════════════════════
# STORE PRODUCTION FEATURE
# ═══════════════════════════════════════════════════════════════════════════

PRODUCTION_CONFIG = [
    {"name": "Arroz Al Cuba", "formula": "1order=175grams", "grams": 175, "unit_type": "order"},
    {"name": "Bistek Tagalog", "formula": "1order=100grams", "grams": 100, "unit_type": "order"},
    {"name": "Boneless Bangus", "formula": "1order=150grams", "grams": 150, "unit_type": "order"},
    {"name": "Boneless Barbq", "formula": "1order=150grams", "grams": 150, "unit_type": "order"},
    {"name": "Buffalo wings 6pcs", "formula": "1order=6pcs", "grams": None, "pieces": 6, "unit_type": "order"},
    {"name": "Buffalo wings 8pcs", "formula": "1order=8pcs", "grams": None, "pieces": 8, "unit_type": "order"},
    {"name": "CHIX CORDON BLEU", "formula": "1order=250grams", "grams": 250, "unit_type": "order"},
    {"name": "Chix Grilled/Rosemary", "formula": "1order=100grams", "grams": 100, "unit_type": "order"},
    {"name": "Cris Fish Fil", "formula": "1order=200grams", "grams": 200, "unit_type": "order"},
    {"name": "Famous Sisig", "formula": "1order=100grams", "grams": 100, "unit_type": "order"},
    {"name": "Lechon Kawali", "formula": "1order=200grams", "grams": 200, "unit_type": "order"},
    {"name": "Porkchop", "formula": "1order=380grams", "grams": 380, "unit_type": "order"},
    {"name": "Ribeye Tapsilog", "formula": "1order = 120grams", "grams": 120, "unit_type": "order"},
    {"name": "Salpicao", "formula": "1order=130grams", "grams": 130, "unit_type": "order"},
    {"name": "Shrimp Gambas", "formula": "1order=100grams", "grams": 100, "unit_type": "order"},
    {"name": "Fried Chicken 2pcs", "formula": "1order=2pcs", "grams": None, "pieces": 2, "unit_type": "order"},
    {"name": "Fried Chicken 4pcs", "formula": "1order=4pcs", "grams": None, "pieces": 4, "unit_type": "order"},
    {"name": "KIDDIE PATTIES", "formula": "1pc", "grams": None, "pieces": 1, "unit_type": "piece"},
    {"name": "REGULAR PATTIES", "formula": "1pc", "grams": None, "pieces": 1, "unit_type": "piece"},
    {"name": "Phillys", "formula": "1order=70grams", "grams": 70, "unit_type": "order"},
    {"name": "Shrimp Pomodoro", "formula": "1order=40grams", "grams": 40, "unit_type": "order"}
]

ALLOWED_PRODUCTION_NAMES = {item["name"].lower(): item for item in PRODUCTION_CONFIG}


def get_allowed_production_products(company_id=None):
    """Retrieve and format the exact 21 allowed production products for the current company."""
    query = Product.query
    if company_id:
        query = query.filter(or_(Product.company_id == company_id, Product.company_id.is_(None)))

    all_prods = query.all()
    prod_map = {}
    for p in all_prods:
        clean = p.name.strip().lower()
        if clean in ALLOWED_PRODUCTION_NAMES and clean not in prod_map:
            prod_map[clean] = p

    items = []
    for cfg in PRODUCTION_CONFIG:
        p = prod_map.get(cfg["name"].lower())
        if p:
            items.append({
                "id": p.id,
                "name": p.name,
                "barcode": p.barcode or '',
                "formula": cfg["formula"],
                "grams": cfg["grams"],
                "pieces": cfg.get("pieces"),
                "unit_type": cfg["unit_type"],
                "store_qty": float(p.store_qty or 0.0),
                "uom": p.uom or 'piece/s',
                "display_label": f"{p.name} ({cfg['formula']})"
            })
    return items


@store.route('/production', methods=['GET'])
@login_required
def production():
    """Store-side Production Dashboard & Log."""
    if current_user.role not in ['User', 'SYS-Admin', 'Company-Admin', 'WH-Admin']:
        flash('Access denied to store production.', 'danger')
        return redirect(url_for('main.dashboard'))

    now_ph = datetime.now(ZoneInfo('Asia/Manila'))
    today_date = now_ph.date()
    today_str = today_date.strftime('%Y-%m-%d')

    company_id = current_user.company_id if current_user.role != 'SYS-Admin' else None

    # Available allowed products (strictly the 21 items)
    allowed_products = get_allowed_production_products(company_id)

    # Filtering parameters
    date_from = request.args.get('date_from', '').strip()
    date_to = request.args.get('date_to', '').strip()
    filter_prod_id = request.args.get('product_id', '').strip()
    search = request.args.get('search', '').strip()

    query = StoreProduction.query
    if company_id:
        query = query.filter(or_(StoreProduction.company_id == company_id, StoreProduction.company_id.is_(None)))

    if filter_prod_id:
        try:
            query = query.filter(StoreProduction.product_id == int(filter_prod_id))
        except ValueError:
            pass

    if date_from:
        try:
            d_from = datetime.strptime(date_from, '%Y-%m-%d').date()
            query = query.filter(StoreProduction.production_date >= d_from)
        except ValueError:
            pass

    if date_to:
        try:
            d_to = datetime.strptime(date_to, '%Y-%m-%d').date()
            query = query.filter(StoreProduction.production_date <= d_to)
        except ValueError:
            pass

    if search:
        s_term = f"%{search}%"
        query = query.filter(or_(
            StoreProduction.product_name.ilike(s_term),
            StoreProduction.batch_code.ilike(s_term),
            StoreProduction.notes.ilike(s_term)
        ))

    records = query.order_by(desc(StoreProduction.production_date), desc(StoreProduction.id)).all()

    # KPI Metrics
    base_co_query = StoreProduction.query
    if company_id:
        base_co_query = base_co_query.filter(or_(StoreProduction.company_id == company_id, StoreProduction.company_id.is_(None)))

    today_records = base_co_query.filter(StoreProduction.production_date == today_date).all()
    today_count = len(today_records)
    today_qty_sum = round(sum(r.quantity for r in today_records), 2)
    today_grams_sum = round(sum((r.total_yield_grams or 0.0) for r in today_records), 1)
    total_records_count = base_co_query.count()

    # Products with zero or low store stock
    low_stock_count = sum(1 for p in allowed_products if p["store_qty"] <= 0)

    return render_template(
        'store/production.html',
        allowed_products=allowed_products,
        records=records,
        today_str=today_str,
        today_count=today_count,
        today_qty_sum=today_qty_sum,
        today_grams_sum=today_grams_sum,
        total_records_count=total_records_count,
        low_stock_count=low_stock_count,
        date_from=date_from,
        date_to=date_to,
        filter_prod_id=filter_prod_id,
        search=search,
        now=now_ph
    )


@store.route('/production/submit', methods=['POST'])
@login_required
def submit_production():
    """Submit a store production entry and deduct quantities from store stock."""
    if current_user.role not in ['User', 'SYS-Admin', 'Company-Admin', 'WH-Admin']:
        msg = 'Access denied. You do not have permission to submit store production.'
        if request.is_json:
            return jsonify({'success': False, 'message': msg}), 403
        flash(msg, 'danger')
        return redirect(url_for('store.production'))

    if request.is_json:
        data = request.get_json(silent=True) or {}
    else:
        data = request.form or {}

    raw_date = data.get('production_date')
    now_ph = datetime.now(ZoneInfo('Asia/Manila'))

    if raw_date:
        try:
            prod_date = datetime.strptime(str(raw_date).strip(), '%Y-%m-%d').date()
        except ValueError:
            prod_date = now_ph.date()
    else:
        prod_date = now_ph.date()

    # Parse items list (supports single item or array of items)
    items_data = data.get('items')
    if not items_data:
        # Fallback to single product fields
        p_id = data.get('product_id')
        qty = data.get('quantity')
        notes = data.get('notes', '')
        if p_id and qty:
            items_data = [{'product_id': p_id, 'quantity': qty, 'notes': notes}]
        else:
            items_data = []

    if not items_data:
        msg = 'No production items provided.'
        if request.is_json:
            return jsonify({'success': False, 'message': msg}), 400
        flash(msg, 'danger')
        return redirect(url_for('store.production'))

    batch_code = f"PRD-{now_ph.strftime('%Y%m%d%H%M%S')}"
    created_records = []
    log_summaries = []

    try:
        for idx, item_entry in enumerate(items_data):
            prod_id_raw = item_entry.get('product_id')
            qty_raw = item_entry.get('quantity')
            notes = (item_entry.get('notes') or '').strip()

            if not prod_id_raw or not qty_raw:
                continue

            try:
                prod_id = int(prod_id_raw)
                quantity = float(qty_raw)
                if quantity <= 0:
                    raise ValueError()
            except (ValueError, TypeError):
                continue

            product = Product.query.get(prod_id)
            if not product:
                continue

            # Validate that product is one of the 21 allowed production products
            clean_name = product.name.strip().lower()
            if clean_name not in ALLOWED_PRODUCTION_NAMES:
                continue

            cfg = ALLOWED_PRODUCTION_NAMES[clean_name]

            # Store stock calculation (deduct quantity)
            store_qty_before = float(product.store_qty or 0.0)
            store_qty_after = max(0.0, store_qty_before - quantity)
            product.store_qty = store_qty_after
            product.quantity = float(product.warehouse_qty or 0.0) + product.store_qty

            # FIFO deduction from store batches if present
            store_batches = StoreProductBatch.query.filter_by(product_id=product.id)\
                .filter(StoreProductBatch.quantity > 0)\
                .order_by(StoreProductBatch.exp_date.asc(), StoreProductBatch.id.asc()).all()
            rem = quantity
            for b in store_batches:
                if rem <= 0:
                    break
                take = min(b.quantity, rem)
                b.quantity -= take
                rem -= take

            total_yield_grams = (quantity * cfg['grams']) if cfg.get('grams') else None

            prod_record = StoreProduction(
                batch_code=batch_code,
                production_date=prod_date,
                product_id=product.id,
                product_name=product.name,
                portion_formula=cfg['formula'],
                quantity=quantity,
                unit_type=cfg.get('unit_type', 'order'),
                total_yield_grams=total_yield_grams,
                store_qty_before=store_qty_before,
                store_qty_after=store_qty_after,
                produced_by=current_user.id,
                notes=notes,
                created_at=now_ph,
                company_id=product.company_id or getattr(current_user, 'company_id', None)
            )
            db.session.add(prod_record)
            db.session.flush()

            # Record in ProductHistory
            history = ProductHistory(
                product_id=product.id,
                trxn_date=now_ph,
                trxn_code='TRANS OUT',
                payee=f"Store Production ({batch_code})",
                quantity_out=quantity,
                net_change=-quantity,
                reference_type='production',
                reference_id=prod_record.id,
                created_at=now_ph,
                company_id=product.company_id or getattr(current_user, 'company_id', None)
            )
            db.session.add(history)

            created_records.append(prod_record)
            unit_lbl = cfg.get('unit_type', 'order')
            yield_str = f" ({total_yield_grams}g total)" if total_yield_grams else ""
            log_summaries.append(f"{quantity} {unit_lbl} of {product.name}{yield_str}")

        if not created_records:
            db.session.rollback()
            msg = 'No valid production entries could be processed. Please check selected products and quantities.'
            if request.is_json:
                return jsonify({'success': False, 'message': msg}), 400
            flash(msg, 'danger')
            return redirect(url_for('store.production'))

        db.session.commit()

        log_activity(
            action="Store Production",
            details=f"Recorded store production batch <strong>{batch_code}</strong> by <strong>{current_user.full_name or current_user.username}</strong>: "
                    + ", ".join(log_summaries)
        )

        success_msg = f"Store production #{batch_code} recorded successfully! {len(created_records)} item(s) deducted from store inventory."
        if request.is_json:
            return jsonify({
                'success': True,
                'message': success_msg,
                'batch_code': batch_code,
                'count': len(created_records)
            })
        flash(success_msg, 'success')
        return redirect(url_for('store.production'))

    except Exception as e:
        db.session.rollback()
        err_msg = f"Failed to record production: {str(e)}"
        if request.is_json:
            return jsonify({'success': False, 'message': err_msg}), 500
        flash(err_msg, 'danger')
        return redirect(url_for('store.production'))


@store.route('/production/<batch_code>/slip')
@login_required
def production_slip(batch_code):
    """Render a printable slip / summary for a store production batch."""
    records = StoreProduction.query.filter_by(batch_code=batch_code).order_by(StoreProduction.id.asc()).all()
    if not records:
        flash('Production batch not found.', 'danger')
        return redirect(url_for('store.production'))

    first_rec = records[0]
    total_qty = sum(r.quantity for r in records)
    total_grams = sum((r.total_yield_grams or 0.0) for r in records)

    return render_template(
        'store/production_slip.html',
        batch_code=batch_code,
        records=records,
        first_rec=first_rec,
        total_qty=total_qty,
        total_grams=total_grams,
        now=datetime.now(ZoneInfo('Asia/Manila'))
    )


@store.route('/production/<int:id>/delete', methods=['POST'])
@login_required
def delete_production(id):
    """Delete a production record and restore deducted store stock."""
    if current_user.role not in ['SYS-Admin', 'Company-Admin', 'User']:
        return jsonify({'success': False, 'message': 'Access denied.'}), 403

    record = StoreProduction.query.get_or_404(id)
    product = Product.query.get(record.product_id)

    if product:
        product.store_qty = float(product.store_qty or 0.0) + record.quantity
        product.quantity = float(product.warehouse_qty or 0.0) + product.store_qty

    # Remove related ProductHistory
    ProductHistory.query.filter_by(reference_type='production', reference_id=record.id).delete()

    db.session.delete(record)
    db.session.commit()

    log_activity(
        action="Store Production Deleted",
        details=f"Deleted store production #{record.id} ({record.quantity} of {record.product_name}) and restored store stock."
    )

    return jsonify({'success': True, 'message': f'Production record #{id} removed and store stock restored.'})

