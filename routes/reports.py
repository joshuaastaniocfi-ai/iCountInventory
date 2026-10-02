from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import csv
import io

from flask import Blueprint, render_template, request, jsonify, send_file, flash, redirect, url_for
from flask_login import login_required, current_user
from sqlalchemy import desc, func

from extensions import db
from models import Product, WarehouseProductBatch, StoreProductBatch, ProductHistory, Requisition, ActivityLog, StockAudit
from helpers import user_redirect_to_requisition, admin_required, assign_company

reports = Blueprint('reports', __name__, url_prefix='/reports')


@reports.route('/')
@login_required
@user_redirect_to_requisition
def hub():
    now_ph = datetime.now(ZoneInfo("Asia/Manila"))
    thirty_days_ago = now_ph - timedelta(days=30)

    if current_user.role == 'SYS-Admin' and current_user.company_id is None:
        base_query = Product.query
        activity_query = ActivityLog.query
        req_query = Requisition.query
    else:
        base_query = Product.query.filter_by(company_id=current_user.company_id)
        activity_query = ActivityLog.query.filter_by(company_id=current_user.company_id)
        req_query = Requisition.query.filter_by(company_id=current_user.company_id)

    total_receiving = req_query.filter(
        Requisition.status.in_(['approved', 'Dispatched'])
    ).count()

    recent_activities = activity_query.order_by(ActivityLog.timestamp.desc()).limit(5).all()

    return render_template('shared/reports.html',
        now=now_ph,
        total_products=base_query.count(),
        total_activity_logs=activity_query.count(),
        total_requisitions=req_query.count(),
        pending_requisitions=req_query.filter_by(status='Pending').count(),
        total_receiving=total_receiving,
        recent_activities=recent_activities
    )


@reports.route('/export/csv')
@login_required
def export_csv():
    report_type = request.args.get('type', 'inventory')
    date_from = request.args.get('from')
    date_to = request.args.get('to')

    if current_user.role == 'SYS-Admin' and current_user.company_id is None:
        product_query = Product.query
        activity_query = ActivityLog.query
        req_query = Requisition.query
    else:
        product_query = Product.query.filter_by(company_id=current_user.company_id)
        activity_query = ActivityLog.query.filter_by(company_id=current_user.company_id)
        req_query = Requisition.query.filter_by(company_id=current_user.company_id)

    output = io.StringIO()
    writer = csv.writer(output)

    if report_type == 'inventory':
        writer.writerow(['Product Name', 'Barcode', 'Category', 'Quantity', 'UOM', 'Reorder Level', 'Status'])
        for p in product_query.order_by(Product.name).all():
            status = 'Out of Stock' if p.quantity == 0 else ('Low Stock' if p.is_low_stock else 'In Stock')
            writer.writerow([p.name, p.barcode, p.category or '', p.quantity, p.uom, p.reorder_level, status])

    elif report_type == 'activity':
        writer.writerow(['Date', 'Action', 'Details', 'User'])
        query = activity_query.order_by(ActivityLog.timestamp.desc())
        if date_from:
            query = query.filter(ActivityLog.timestamp >= datetime.fromisoformat(date_from))
        if date_to:
            query = query.filter(ActivityLog.timestamp <= datetime.fromisoformat(date_to) + timedelta(days=1))
        for log in query.all():
            writer.writerow([log.timestamp.strftime('%Y-%m-%d %I:%M %p'), log.action, log.details, log.user or ''])

    elif report_type == 'requisitions':
        writer.writerow(['ID', 'Date', 'Requested By', 'Branch', 'Status', 'Items Count'])
        query = req_query.order_by(Requisition.date_created.desc())
        if date_from:
            query = query.filter(Requisition.date_created >= datetime.fromisoformat(date_from))
        if date_to:
            query = query.filter(Requisition.date_created <= datetime.fromisoformat(date_to) + timedelta(days=1))
        for r in query.all():
            writer.writerow([r.id, r.date_created.strftime('%Y-%m-%d %I:%M %p'), r.requested_by, r.branch, r.status, len(r.items)])

    else:
        return jsonify({'success': False, 'message': 'Invalid report type'}), 400

    mem = io.BytesIO()
    mem.write(output.getvalue().encode('utf-8-sig'))
    mem.seek(0)
    return send_file(mem, mimetype='text/csv', as_attachment=True, download_name=f'{report_type}_report_{datetime.now().strftime("%Y%m%d")}.csv')


def determine_transaction_location(record):
    """Determine whether a transaction affects Warehouse, Store, or is a Transfer."""
    ref_type = (record.reference_type or '').lower()
    code = (record.trxn_code or '').upper()
    payee = (record.payee or '').upper()

    if 'RECV IN' in code or ref_type in ('receiving', 'receiving_optional', 'restore_store', 'store_wrong_count', 'store_damage_unloading', 'store_missing_post_delivery') or 'STORE LOSS' in code:
        return 'Store'
    elif ref_type in ('requisition', 'requisition_optional'):
        return 'Warehouse → Store'
    elif 'DELIVERY LOSS' in code or 'WH MISCOUNT' in code or 'WH DAMAGE' in code or 'WH OVERAGE' in code or 'SUPPLIER DEFECT' in code or ref_type in ('restore_warehouse', 'warehouse_miscount_charge', 'warehouse_over_dispatch', 'warehouse_damaged_prep', 'delivery_loss', 'delivery_spoilage', 'supplier_defect'):
        return 'Warehouse'
    elif ref_type == 'spoilage':
        if 'STORE' in payee:
            return 'Store'
        return 'Warehouse'
    elif ref_type in ('oth', 'batch', 'initial', 'removal'):
        return 'Warehouse'
    elif 'STORE' in payee or 'BRANCH' in payee:
        return 'Store'
    else:
        return 'Warehouse'


def determine_transaction_category(record):
    """Categorize transaction into human-readable types with semantic styling."""
    ref_type = (record.reference_type or '').lower()
    code = (record.trxn_code or '').upper()

    if ref_type == 'oth' or 'OTH' in (record.payee or '').upper():
        return 'On The House (OTH)'
    elif 'RECV IN' in code or ref_type in ('receiving', 'receiving_optional'):
        return 'Store Received'
    elif 'DELIVERY LOSS' in code or ref_type in ('delivery_loss', 'delivery_spoilage', 'damaged_loss', 'delivery_transit_loss'):
        return 'Delivery Loss'
    elif 'WH MISCOUNT' in code or ref_type == 'warehouse_miscount_charge':
        return 'WH Miscount'
    elif 'WH OVERAGE' in code or ref_type == 'warehouse_over_dispatch':
        return 'WH Over-Dispatch'
    elif 'WH DAMAGE' in code or ref_type == 'warehouse_damaged_prep':
        return 'WH Damage'
    elif 'COUNT CORRECTION' in code or ref_type == 'store_wrong_count':
        return 'Count Correction'
    elif 'STORE LOSS' in code or ref_type in ('store_damage_unloading', 'store_missing_post_delivery'):
        return 'Store Loss'
    elif 'STORE RECOVERY' in code or ref_type == 'restore_store':
        return 'Store Recovery'
    elif ref_type == 'restore_warehouse':
        return 'Warehouse Restored'
    elif 'SUPPLIER DEFECT' in code or ref_type == 'supplier_defect':
        return 'Supplier Defect'
    elif ref_type == 'spoilage':
        return 'Spoilage'
    elif ref_type == 'removal':
        return 'Removal'
    elif ref_type in ('requisition', 'requisition_optional'):
        return 'Requisition Release'
    elif code == 'TRANS IN' or (record.quantity_in and record.quantity_in > 0):
        return 'Stock In'
    elif code == 'TRANS OUT' or (record.quantity_out and record.quantity_out > 0):
        return 'Stock Out'
    else:
        return 'Adjustment'


def compute_ledger_records(company_id=None, product_id=None, location=None, trxn_type=None, date_from=None, date_to=None, search=None, sort_order='desc'):
    """
    Computes overall inventory movements with exact running balances.
    
    Mathematical Guarantee:
    Working backwards from each product's current real-time stock (`product.quantity`),
    the very latest transaction result is ALWAYS equal to current quantity right now.
    """
    if company_id:
        prod_query = Product.query.filter_by(company_id=company_id)
    else:
        prod_query = Product.query

    if product_id:
        prod_query = prod_query.filter_by(id=product_id)

    products = {p.id: p for p in prod_query.all()}
    if not products:
        return [], {
            'total_transactions': 0,
            'total_added': 0.0,
            'total_deducted': 0.0,
            'net_change': 0.0,
            'current_system_qty': 0.0,
            'total_warehouse_qty': 0.0,
            'total_store_qty': 0.0,
            'selected_product': None,
        }

    # Query all history records for these products
    hist_query = ProductHistory.query
    if company_id:
        hist_query = hist_query.filter(ProductHistory.company_id == company_id)

    if product_id:
        hist_query = hist_query.filter(ProductHistory.product_id == product_id)
    else:
        hist_query = hist_query.filter(ProductHistory.product_id.in_(products.keys()))

    # Order newest first to walk backwards from current quantity
    all_records = hist_query.order_by(ProductHistory.trxn_date.desc(), ProductHistory.id.desc()).all()

    product_records = {}
    for r in all_records:
        product_records.setdefault(r.product_id, []).append(r)

    processed_rows = []

    for pid, recs in product_records.items():
        prod = products.get(pid)
        if not prod:
            continue

        # Starting from current real-time stock
        current_balance = float(prod.quantity or 0.0)

        for r in recs:
            net = float(r.net_change or 0.0)
            qty_in = float(r.quantity_in or 0.0)
            qty_out = float(r.quantity_out or 0.0)

            # Ensure net_change consistency if not set
            if net == 0.0 and (qty_in > 0 or qty_out > 0):
                net = qty_in - qty_out

            bal_after = round(current_balance, 2)
            bal_before = round(bal_after - net, 2)

            loc = determine_transaction_location(r)
            cat = determine_transaction_category(r)

            processed_rows.append({
                'id': r.id,
                'product_id': prod.id,
                'product_name': prod.name,
                'product_barcode': prod.barcode,
                'product_uom': prod.uom or 'unit',
                'current_product_qty': round(float(prod.quantity or 0.0), 2),
                'current_warehouse_qty': round(float(prod.warehouse_qty or 0.0), 2),
                'current_store_qty': round(float(prod.store_qty or 0.0), 2),
                'trxn_date': r.trxn_date.strftime('%Y-%m-%d %H:%M:%S') if r.trxn_date else '',
                'trxn_date_display': r.trxn_date.strftime('%b %d, %Y %I:%M %p') if r.trxn_date else '',
                'trxn_code': r.trxn_code or '',
                'category': cat,
                'location': loc,
                'payee': r.payee or '—',
                'quantity_in': qty_in,
                'quantity_out': qty_out,
                'net_change': net,
                'balance_before': bal_before,
                'balance_after': bal_after,
                'reference_id': r.reference_id,
                'reference_type': r.reference_type or '',
            })

            current_balance = bal_before

    # Apply filters
    filtered = processed_rows

    if location and location != 'all':
        loc_l = location.lower()
        if loc_l == 'warehouse':
            filtered = [r for r in filtered if r['location'] == 'Warehouse']
        elif loc_l == 'store':
            filtered = [r for r in filtered if r['location'] == 'Store']
        elif loc_l == 'transfer':
            filtered = [r for r in filtered if '→' in r['location'] or 'Transfer' in r['location']]

    if trxn_type and trxn_type != 'all':
        type_l = trxn_type.lower()
        if type_l == 'in':
            filtered = [r for r in filtered if r['quantity_in'] > 0]
        elif type_l == 'out':
            filtered = [r for r in filtered if r['quantity_out'] > 0]
        else:
            filtered = [r for r in filtered if r['category'].lower() == type_l]

    if date_from:
        filtered = [r for r in filtered if r['trxn_date'] >= f"{date_from} 00:00:00"]

    if date_to:
        filtered = [r for r in filtered if r['trxn_date'] <= f"{date_to} 23:59:59"]

    if search:
        s = search.lower().strip()
        filtered = [r for r in filtered if (
            s in r['product_name'].lower() or
            s in r['product_barcode'].lower() or
            s in r['payee'].lower() or
            s in r['trxn_code'].lower() or
            s in r['reference_type'].lower() or
            s in r['category'].lower()
        )]

    # Sort
    if sort_order == 'asc':
        filtered.sort(key=lambda x: (x['trxn_date'], x['id']))
    else:
        filtered.sort(key=lambda x: (x['trxn_date'], x['id']), reverse=True)

    # Calculate summary metrics
    total_added = round(sum(r['quantity_in'] for r in filtered), 2)
    total_deducted = round(sum(r['quantity_out'] for r in filtered), 2)
    net_change = round(sum(r['net_change'] for r in filtered), 2)

    selected_product_info = None
    if product_id and product_id in products:
        sp = products[product_id]
        selected_product_info = {
            'id': sp.id,
            'name': sp.name,
            'barcode': sp.barcode,
            'uom': sp.uom or 'unit',
            'total_qty': round(float(sp.quantity or 0.0), 2),
            'warehouse_qty': round(float(sp.warehouse_qty or 0.0), 2),
            'store_qty': round(float(sp.store_qty or 0.0), 2),
        }

    summary = {
        'total_transactions': len(filtered),
        'total_added': total_added,
        'total_deducted': total_deducted,
        'net_change': net_change,
        'current_system_qty': round(sum(float(p.quantity or 0.0) for p in products.values()), 2),
        'total_warehouse_qty': round(sum(float(p.warehouse_qty or 0.0) for p in products.values()), 2),
        'total_store_qty': round(sum(float(p.store_qty or 0.0) for p in products.values()), 2),
        'selected_product': selected_product_info,
    }

    return filtered, summary


@reports.route('/ledger')
@reports.route('/ledger/<int:product_id>')
@reports.route('/transactions')
@login_required
def ledger(product_id=None):
    """Admin page displaying the product list and drill-down stock movement transaction ledger."""
    if current_user.role not in ('SYS-Admin', 'Company-Admin', 'WH-Admin'):
        flash('Access denied. Administrator privileges required.', 'danger')
        return redirect(url_for('main.dashboard'))

    company_id = current_user.company_id if current_user.role != 'SYS-Admin' else None

    # Get products list
    if company_id:
        prod_query = Product.query.filter_by(company_id=company_id)
    else:
        prod_query = Product.query

    products = prod_query.order_by(Product.name).all()

    # Query transaction counts per product
    tx_query = db.session.query(ProductHistory.product_id, func.count(ProductHistory.id))
    if company_id:
        tx_query = tx_query.filter(ProductHistory.company_id == company_id)
    tx_counts = dict(tx_query.group_by(ProductHistory.product_id).all())

    # Build detailed product summaries for the first page
    product_items = []
    total_warehouse_units = 0.0
    total_store_units = 0.0
    total_system_units = 0.0
    in_stock_count = 0
    low_stock_count = 0
    out_of_stock_count = 0

    for p in products:
        w_qty = float(p.warehouse_qty or 0.0)
        s_qty = float(p.store_qty or 0.0)
        t_qty = float(p.quantity or (w_qty + s_qty))

        total_warehouse_units += w_qty
        total_store_units += s_qty
        total_system_units += t_qty

        if t_qty <= 0:
            status = 'out_of_stock'
            status_label = 'Out of Stock'
            out_of_stock_count += 1
        elif p.is_low_stock:
            status = 'low_stock'
            status_label = 'Low Stock'
            low_stock_count += 1
        else:
            status = 'in_stock'
            status_label = 'In Stock'
            in_stock_count += 1

        product_items.append({
            'id': p.id,
            'name': p.name,
            'barcode': p.barcode,
            'account_title': p.account_title or '',
            'uom': p.uom or 'unit',
            'warehouse_qty': round(w_qty, 2),
            'store_qty': round(s_qty, 2),
            'quantity': round(t_qty, 2),
            'status': status,
            'status_label': status_label,
            'reorder_level': p.reorder_level or 0,
            'tx_count': tx_counts.get(p.id, 0),
        })

    initial_pid = product_id or request.args.get('product_id', type=int)

    summary_stats = {
        'total_products': len(products),
        'in_stock_count': in_stock_count,
        'low_stock_count': low_stock_count,
        'out_of_stock_count': out_of_stock_count,
        'total_warehouse_units': round(total_warehouse_units, 2),
        'total_store_units': round(total_store_units, 2),
        'total_system_units': round(total_system_units, 2),
    }

    return render_template(
        'reports/inventory_ledger.html',
        products=product_items,
        summary_stats=summary_stats,
        initial_product_id=initial_pid,
        current_user=current_user
    )


@reports.route('/api/ledger/product/<int:product_id>')
@login_required
def api_ledger_product(product_id):
    """API endpoint to get product details and ledger history for a single product."""
    if current_user.role not in ('SYS-Admin', 'Company-Admin', 'WH-Admin'):
        return jsonify({'success': False, 'message': 'Access denied.'}), 403

    company_id = current_user.company_id if current_user.role != 'SYS-Admin' else None
    
    if company_id:
        product = Product.query.filter_by(id=product_id, company_id=company_id).first_or_404()
    else:
        product = Product.query.get_or_404(product_id)

    location = request.args.get('location', 'all')
    trxn_type = request.args.get('type', 'all')
    date_from = request.args.get('from')
    date_to = request.args.get('to')
    search = request.args.get('search')
    sort_order = request.args.get('order', 'desc')

    records, summary = compute_ledger_records(
        company_id=company_id,
        product_id=product.id,
        location=location,
        trxn_type=trxn_type,
        date_from=date_from,
        date_to=date_to,
        search=search,
        sort_order=sort_order
    )

    return jsonify({
        'success': True,
        'product': {
            'id': product.id,
            'name': product.name,
            'barcode': product.barcode,
            'account_title': product.account_title or '',
            'uom': product.uom or 'unit',
            'warehouse_qty': round(float(product.warehouse_qty or 0.0), 2),
            'store_qty': round(float(product.store_qty or 0.0), 2),
            'quantity': round(float(product.quantity or 0.0), 2),
        },
        'records': records,
        'summary': summary,
        'total_count': len(records),
    })



@reports.route('/api/ledger')
@login_required
def api_ledger():
    """API endpoint providing filtered transaction ledger data with running balances."""
    if current_user.role not in ('SYS-Admin', 'Company-Admin', 'WH-Admin'):
        return jsonify({'success': False, 'message': 'Access denied.'}), 403

    company_id = current_user.company_id if current_user.role != 'SYS-Admin' else None
    product_id = request.args.get('product_id', type=int)
    location = request.args.get('location', 'all')
    trxn_type = request.args.get('type', 'all')
    date_from = request.args.get('from')
    date_to = request.args.get('to')
    search = request.args.get('search')
    sort_order = request.args.get('order', 'desc')
    page = request.args.get('page', 1, type=int)
    per_page_arg = request.args.get('per_page', '50')

    records, summary = compute_ledger_records(
        company_id=company_id,
        product_id=product_id,
        location=location,
        trxn_type=trxn_type,
        date_from=date_from,
        date_to=date_to,
        search=search,
        sort_order=sort_order
    )

    total_count = len(records)
    if per_page_arg == 'all':
        paged_records = records
        total_pages = 1
        per_page = total_count
    else:
        try:
            per_page = int(per_page_arg)
            if per_page <= 0:
                per_page = 50
        except ValueError:
            per_page = 50

        total_pages = max(1, (total_count + per_page - 1) // per_page)
        page = max(1, min(page, total_pages)) if total_count > 0 else 1
        start_idx = (page - 1) * per_page
        paged_records = records[start_idx:start_idx + per_page]

    return jsonify({
        'success': True,
        'records': paged_records,
        'summary': summary,
        'page': page,
        'per_page': per_page,
        'total_pages': total_pages,
        'total_count': total_count,
    })


@reports.route('/ledger/export')
@login_required
def export_ledger():
    """Download filtered inventory ledger as Excel-compatible CSV."""
    if current_user.role not in ('SYS-Admin', 'Company-Admin', 'WH-Admin'):
        flash('Access denied.', 'danger')
        return redirect(url_for('main.dashboard'))

    company_id = current_user.company_id if current_user.role != 'SYS-Admin' else None
    product_id = request.args.get('product_id', type=int)
    location = request.args.get('location', 'all')
    trxn_type = request.args.get('type', 'all')
    date_from = request.args.get('from')
    date_to = request.args.get('to')
    search = request.args.get('search')
    sort_order = request.args.get('order', 'desc')

    records, _ = compute_ledger_records(
        company_id=company_id,
        product_id=product_id,
        location=location,
        trxn_type=trxn_type,
        date_from=date_from,
        date_to=date_to,
        search=search,
        sort_order=sort_order
    )

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        'Transaction Date',
        'Product Name',
        'Barcode',
        'UOM',
        'Location',
        'Transaction Type',
        'Reference / Payee',
        'Quantity Added (+)',
        'Quantity Less (-)',
        'Net Change',
        'Resulting Balance (Qty)',
        'Current Live Stock',
    ])

    for r in records:
        writer.writerow([
            r['trxn_date'],
            r['product_name'],
            r['product_barcode'],
            r['product_uom'],
            r['location'],
            r['category'],
            r['payee'],
            f"+{r['quantity_in']:.2f}" if r['quantity_in'] > 0 else '0.00',
            f"-{r['quantity_out']:.2f}" if r['quantity_out'] > 0 else '0.00',
            f"{r['net_change']:+.2f}",
            f"{r['balance_after']:.2f}",
            f"{r['current_product_qty']:.2f}",
        ])

    mem = io.BytesIO()
    mem.write(output.getvalue().encode('utf-8-sig'))
    mem.seek(0)
    filename = f"inventory_ledger_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    return send_file(mem, mimetype='text/csv', as_attachment=True, download_name=filename)

