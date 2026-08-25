from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import csv
import io

from flask import Blueprint, render_template, request, jsonify, send_file, flash, redirect, url_for
from flask_login import login_required, current_user
from sqlalchemy import desc

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
