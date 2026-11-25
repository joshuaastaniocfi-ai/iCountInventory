# Standard library imports
import io
import json
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from zoneinfo import ZoneInfo

# Third-party imports
from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify, send_file, current_app
from flask_login import login_required, current_user
import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment

# Local imports
from extensions import db
from models import PosSoldRecord, ProductRecipe, DailyEndingInventory, RawItem, Requisition, Company

pos_sold_bp = Blueprint('pos_sold', __name__)


def _can_access():
    return current_user.is_authenticated and current_user.role in ('User', 'SYS-Admin')


def _to_float(val, default=0.0):
    if val is None or str(val).strip() == '':
        return default
    try:
        return float(val)
    except (ValueError, TypeError):
        return default


def _parse_date(date_str):
    if date_str:
        try:
            return datetime.strptime(date_str.strip(), '%Y-%m-%d').date()
        except ValueError:
            pass
    return datetime.now(ZoneInfo("Asia/Manila")).date()


def _scoped_query():
    if current_user.role == 'SYS-Admin' and current_user.company_id is None:
        return PosSoldRecord.query
    return PosSoldRecord.query.filter_by(company_id=current_user.company_id)


def _upsert_pos_items(company_id, items, client_id, synced_by):
    """Upsert POS sold items into invensync.db pos_sold table and sync recipe sold to DAILY ENDING INVENTORY."""
    now_ph = datetime.now(ZoneInfo("Asia/Manila"))
    affected_dates = set()
    upserted = 0

    for row in items:
        row_date = _parse_date(row.get('date'))
        product_name = (row.get('product_name') or '').strip()
        if not product_name:
            continue

        pos_product_id = row.get('product_id')
        qty = _to_float(row.get('qty'), 0.0)
        amount = _to_float(row.get('amount'), 0.0)

        existing = None
        if pos_product_id is not None:
            existing = PosSoldRecord.query.filter_by(
                company_id=company_id,
                sold_date=row_date,
                pos_product_id=pos_product_id
            ).first()
        if not existing:
            existing = PosSoldRecord.query.filter_by(
                company_id=company_id,
                sold_date=row_date,
                product_name=product_name
            ).first()

        if existing:
            existing.product_name = product_name
            existing.pos_product_id = pos_product_id
            existing.qty = qty
            existing.amount = amount
            existing.client_id = client_id
            existing.synced_by = synced_by
            existing.synced_at = now_ph
        else:
            db.session.add(PosSoldRecord(
                company_id=company_id,
                sold_date=row_date,
                pos_product_id=pos_product_id,
                product_name=product_name,
                qty=qty,
                amount=amount,
                client_id=client_id,
                synced_by=synced_by,
                synced_at=now_ph,
            ))

        affected_dates.add(row_date)
        upserted += 1

    db.session.flush()

    # Sync raw material sold quantities to DAILY ENDING INVENTORY via product_recipes
    for target_date in affected_dates:
        sold_records = PosSoldRecord.query.filter_by(company_id=company_id, sold_date=target_date).all()
        recipes = ProductRecipe.query.filter_by(company_id=company_id).all()
        if not recipes:
            continue

        recipe_by_prod = {}
        for rec in recipes:
            pkey = (rec.product_name or '').strip().lower()
            recipe_by_prod.setdefault(pkey, []).append(rec)

        raw_sold_totals = {}
        for sr in sold_records:
            pkey = (sr.product_name or '').strip().lower()
            for rec in recipe_by_prod.get(pkey, []):
                rname = (rec.raw_material or '').strip()
                if not rname:
                    continue
                used_qty = float(sr.qty or 0) * float(rec.recipe_qty or 0)
                key = rname.lower()
                if key not in raw_sold_totals:
                    raw_sold_totals[key] = {'raw_item_id': rec.raw_item_id, 'raw_item_name': rname, 'sold': 0.0}
                raw_sold_totals[key]['sold'] += used_qty

        for data in raw_sold_totals.values():
            dei = DailyEndingInventory.query.filter_by(
                company_id=company_id,
                inventory_date=target_date,
                raw_item_name=data['raw_item_name']
            ).first()
            if dei:
                dei.sold = data['sold']
                dei.theoretical_ending = (
                    float(dei.beg or 0)
                    + float(dei.trans_in or 0)
                    - float(dei.trans_out or 0)
                    - float(dei.wastage or 0)
                    - float(dei.sold or 0)
                )
                if dei.actual_ending is not None:
                    dei.variance = float(dei.actual_ending) - dei.theoretical_ending
                dei.updated_by = synced_by
                dei.updated_at = now_ph
            elif data['sold'] > 0:
                db.session.add(DailyEndingInventory(
                    company_id=company_id,
                    inventory_date=target_date,
                    raw_item_id=data['raw_item_id'],
                    raw_item_name=data['raw_item_name'],
                    beg=0.0,
                    trans_in=0.0,
                    trans_out=0.0,
                    wastage=0.0,
                    sold=data['sold'],
                    theoretical_ending=-data['sold'],
                    actual_ending=None,
                    variance=None,
                    remarks='Synced from POS Sold',
                    updated_by=synced_by,
                    updated_at=now_ph,
                ))

    db.session.commit()
    return upserted


@pos_sold_bp.route('/user/pos-sold', methods=['GET'])
@login_required
def index():
    """Render the POS Sold page."""
    if not _can_access():
        flash('Access denied.', 'error')
        return redirect(url_for('main.dashboard'))

    target_date = _parse_date(request.args.get('date'))
    records = _scoped_query().filter(PosSoldRecord.sold_date == target_date).order_by(
        PosSoldRecord.qty.desc(), PosSoldRecord.product_name.asc()
    ).all()

    pending_receiving_count = Requisition.query.filter(
        (Requisition.company_id == current_user.company_id) |
        (Requisition.destination_company_id == current_user.company_id),
        Requisition.status.in_(['Dispatched', 'dispatched', 'Partial', 'partial'])
    ).count() if current_user.company_id else 0

    company_client_id = ''
    if current_user.company:
        company_client_id = (current_user.company.franchise_name or current_user.company.name or '').strip()

    return render_template(
        'user/pos_sold.html',
        sold_date=target_date.strftime('%Y-%m-%d'),
        pos_records=[r.to_dict() for r in records],
        pos_api_url=current_app.config.get('POS_SOLD_API_URL', ''),
        pos_client_id=company_client_id or current_app.config.get('POS_SOLD_CLIENT_ID', ''),
        has_api_key=bool(current_app.config.get('POS_SOLD_API_KEY')),
        pending_receiving_count=pending_receiving_count,
    )


@pos_sold_bp.route('/user/pos-sold/list', methods=['GET'])
@login_required
def list_records():
    if not _can_access():
        return jsonify({'success': False, 'message': 'Access denied.'}), 403

    target_date = _parse_date(request.args.get('date'))
    records = _scoped_query().filter(PosSoldRecord.sold_date == target_date).order_by(
        PosSoldRecord.qty.desc(), PosSoldRecord.product_name.asc()
    ).all()
    return jsonify({'success': True, 'items': [r.to_dict() for r in records], 'total': len(records)})


@pos_sold_bp.route('/user/pos-sold/clear', methods=['POST'])
@login_required
def clear_records():
    """Delete received POS sold records for the selected date (or all dates if date='all')."""
    if not _can_access():
        return jsonify({'success': False, 'message': 'Access denied.'}), 403

    payload = request.get_json(silent=True) or {}
    date_val = (payload.get('date') or '').strip()

    query = _scoped_query()
    if date_val and date_val != 'all':
        target_date = _parse_date(date_val)
        query = query.filter(PosSoldRecord.sold_date == target_date)

    deleted = query.delete(synchronize_session=False)
    db.session.commit()
    return jsonify({
        'success': True,
        'deleted': deleted,
        'message': f'Deleted {deleted} POS sold record(s).'
    })


@pos_sold_bp.route('/user/pos-sold/sync', methods=['POST'])
@login_required
def sync_from_pos():
    """Fetch live POS sold data from the configured external POS endpoint and save to invensync.db."""
    if not _can_access():
        return jsonify({'success': False, 'message': 'Access denied.'}), 403

    payload = request.get_json(silent=True) or {}
    pos_url = (payload.get('pos_url') or current_app.config.get('POS_SOLD_API_URL') or '').strip()
    api_key = (payload.get('api_key') or current_app.config.get('POS_SOLD_API_KEY') or '').strip()
    client_id = (payload.get('client_id') or current_app.config.get('POS_SOLD_CLIENT_ID') or 'Savore').strip()
    target_date = _parse_date(payload.get('date')).strftime('%Y-%m-%d')

    if not pos_url:
        return jsonify({'success': False, 'message': 'POS API URL is not configured.'}), 400
    if not api_key:
        return jsonify({'success': False, 'message': 'POS API Key is required. Set it in API Settings or .env.'}), 400

    params = urllib.parse.urlencode({
        'date': target_date,
        'client_id': client_id,
        'grouped': '1',
    })
    sep = '&' if '?' in pos_url else '?'
    full_url = f'{pos_url}{sep}{params}'

    req = urllib.request.Request(
        full_url,
        headers={
            'X-API-Key': api_key,
            'X-Client-Id': client_id,
            'Accept': 'application/json',
        },
        method='GET'
    )

    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            raw_body = resp.read().decode('utf-8')
            data = json.loads(raw_body)
    except urllib.error.HTTPError as err:
        err_msg = err.read().decode('utf-8', errors='ignore') if hasattr(err, 'read') else str(err)
        return jsonify({'success': False, 'message': f'POS returned HTTP {err.code}: {err_msg or err.reason}'}), 502
    except Exception as exc:
        return jsonify({'success': False, 'message': f'Could not reach POS API: {exc}'}), 502

    items = data.get('items') if isinstance(data, dict) else (data if isinstance(data, list) else [])
    if not isinstance(items, list):
        return jsonify({'success': False, 'message': 'Unexpected POS response format (expected items[]).'}), 502

    count = _upsert_pos_items(current_user.company_id, items, client_id, current_user.full_name)
    return jsonify({
        'success': True,
        'synced': count,
        'message': f'Synced {count} POS sold item(s) for {target_date}.'
    })


@pos_sold_bp.route('/api/pos-sold', methods=['POST'])
@pos_sold_bp.route('/api/pos-sold/receive', methods=['POST'])
def receive_webhook():
    """Inbound API endpoint to receive cumulative POS sold payload pushed from local POS."""
    expected_key = (current_app.config.get('POS_SOLD_API_KEY') or '').strip()
    provided_key = (
        request.headers.get('X-API-Key')
        or request.args.get('api_key')
        or ''
    ).strip()
    if not provided_key and request.headers.get('Authorization', '').startswith('Bearer '):
        provided_key = request.headers.get('Authorization', '')[7:].strip()

    if expected_key and provided_key != expected_key:
        return jsonify({'success': False, 'message': 'Unauthorized'}), 401

    payload = request.get_json(silent=True) or {}
    items = payload.get('items') if isinstance(payload, dict) else (payload if isinstance(payload, list) else [])
    if not isinstance(items, list):
        return jsonify({'success': False, 'message': 'Invalid items payload.'}), 400

    client_id = (
        request.headers.get('X-Client-Id')
        or (payload.get('client_id') if isinstance(payload, dict) else None)
        or current_app.config.get('POS_SOLD_CLIENT_ID', 'Savore')
    )

    company_id = payload.get('company_id') if isinstance(payload, dict) else None
    if company_id is None and client_id:
        comp = Company.query.filter(
            db.or_(
                db.func.lower(Company.name) == client_id.lower(),
                db.func.lower(Company.franchise_name) == client_id.lower()
            )
        ).first()
        if comp:
            company_id = comp.id
    if company_id is None:
        first_comp = Company.query.order_by(Company.id.asc()).first()
        company_id = first_comp.id if first_comp else 1

    # If payload specifies a date and items, ensure cumulative replacement for that date
    payload_date_str = payload.get('date') if isinstance(payload, dict) else None
    if payload_date_str:
        target_date = _parse_date(payload_date_str)
        for item in items:
            if isinstance(item, dict) and not item.get('date'):
                item['date'] = payload_date_str
        incoming_names = {(r.get('product_name') or '').strip().lower() for r in items if isinstance(r, dict) and (r.get('product_name') or '').strip()}
        existing_for_date = PosSoldRecord.query.filter_by(company_id=company_id, sold_date=target_date).all()
        for ex in existing_for_date:
            if (ex.product_name or '').strip().lower() not in incoming_names:
                db.session.delete(ex)

    count = _upsert_pos_items(company_id, items, client_id, 'POS Push')
    return jsonify({
        'success': True,
        'received': count,
        'client_id': client_id,
        'date': payload_date_str or '',
    })


@pos_sold_bp.route('/user/pos-sold/export', methods=['GET'])
@login_required
def export_excel():
    if not _can_access():
        flash('Access denied.', 'error')
        return redirect(url_for('main.dashboard'))

    target_date = _parse_date(request.args.get('date'))
    q = (request.args.get('q') or '').strip().lower()
    records = _scoped_query().filter(PosSoldRecord.sold_date == target_date).order_by(
        PosSoldRecord.qty.desc(), PosSoldRecord.product_name.asc()
    ).all()
    if q:
        records = [r for r in records if q in (r.product_name or '').lower()]

    headers = ['Date', 'Product ID', 'Product Name', 'Qty', 'Amount']
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = 'POS Sold'
    ws.append(headers)

    header_fill = PatternFill(start_color='18181B', end_color='18181B', fill_type='solid')
    header_font = Font(bold=True, color='FFFFFF')
    for col_idx in range(1, len(headers) + 1):
        cell = ws.cell(row=1, column=col_idx)
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = Alignment(horizontal='left', vertical='center')

    for r in records:
        ws.append([
            r.sold_date.strftime('%Y-%m-%d') if r.sold_date else '',
            r.pos_product_id or '',
            r.product_name or '',
            float(r.qty or 0),
            float(r.amount or 0),
        ])

    widths = [14, 14, 38, 12, 14]
    for idx, width in enumerate(widths, start=1):
        ws.column_dimensions[openpyxl.utils.get_column_letter(idx)].width = width

    output = io.BytesIO()
    wb.save(output)
    output.seek(0)
    return send_file(
        output,
        as_attachment=True,
        download_name=f'pos_sold_{target_date.strftime("%Y-%m-%d")}.xlsx',
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    )
