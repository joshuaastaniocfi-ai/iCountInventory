# Standard library imports
import io
from datetime import datetime
from zoneinfo import ZoneInfo

# Third-party imports
from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify, send_file
from flask_login import login_required, current_user
import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment

# Local imports
from extensions import db
from models import RawItem, DailyEndingInventory, Requisition

invensync_bp = Blueprint('invensync', __name__, url_prefix='/user/invensync')


def _can_access():
    return current_user.is_authenticated and current_user.role in ('User', 'SYS-Admin')


def _to_float(val, default=0.0):
    if val is None or str(val).strip() == '':
        return default
    try:
        return float(val)
    except (ValueError, TypeError):
        return default


def _to_nullable_float(val):
    if val is None or str(val).strip() == '':
        return None
    try:
        return float(val)
    except (ValueError, TypeError):
        return None


def _parse_date(date_str):
    if date_str:
        try:
            return datetime.strptime(date_str.strip(), '%Y-%m-%d').date()
        except ValueError:
            pass
    return datetime.now(ZoneInfo("Asia/Manila")).date()


def _build_rows_for_date(target_date):
    """Merge RawItem master list with any saved DAILY ENDING INVENTORY rows for target_date."""
    if current_user.role == 'SYS-Admin' and current_user.company_id is None:
        raw_items = RawItem.query.order_by(RawItem.raw_material.asc()).all()
        saved_rows = DailyEndingInventory.query.filter_by(inventory_date=target_date).all()
    else:
        raw_items = RawItem.query.filter_by(company_id=current_user.company_id).order_by(RawItem.raw_material.asc()).all()
        saved_rows = DailyEndingInventory.query.filter_by(
            company_id=current_user.company_id,
            inventory_date=target_date
        ).all()

    by_raw_id = {r.raw_item_id: r for r in saved_rows if r.raw_item_id is not None}
    by_name = {r.raw_item_name.strip().lower(): r for r in saved_rows if r.raw_item_name}

    rows = []
    seen_saved_ids = set()
    seen_raw_names = set()
    for item in raw_items:
        raw_name = (item.raw_material or '').strip()
        raw_key = raw_name.lower()
        if not raw_key or raw_key in seen_raw_names:
            continue
        seen_raw_names.add(raw_key)

        saved = by_raw_id.get(item.id) or by_name.get(raw_key)
        if saved:
            seen_saved_ids.add(saved.id)
            rows.append({
                'id': saved.id,
                'raw_item_id': item.id,
                'raw_item_name': raw_name,
                'uom': item.uom or '',
                'beg': float(saved.beg or 0),
                'trans_in': float(saved.trans_in or 0),
                'trans_out': float(saved.trans_out or 0),
                'wastage': float(saved.wastage or 0),
                'sold': float(saved.sold or 0),
                'theoretical_ending': float(saved.theoretical_ending or 0),
                'actual_ending': float(saved.actual_ending) if saved.actual_ending is not None else None,
                'variance': float(saved.variance) if saved.variance is not None else None,
                'remarks': saved.remarks or '',
            })
        else:
            rows.append({
                'id': None,
                'raw_item_id': item.id,
                'raw_item_name': raw_name,
                'uom': item.uom or '',
                'beg': 0.0,
                'trans_in': 0.0,
                'trans_out': 0.0,
                'wastage': 0.0,
                'sold': 0.0,
                'theoretical_ending': 0.0,
                'actual_ending': None,
                'variance': None,
                'remarks': '',
            })

    for saved in saved_rows:
        if saved.id not in seen_saved_ids:
            rows.append({
                'id': saved.id,
                'raw_item_id': saved.raw_item_id,
                'raw_item_name': saved.raw_item_name or '',
                'uom': '',
                'beg': float(saved.beg or 0),
                'trans_in': float(saved.trans_in or 0),
                'trans_out': float(saved.trans_out or 0),
                'wastage': float(saved.wastage or 0),
                'sold': float(saved.sold or 0),
                'theoretical_ending': float(saved.theoretical_ending or 0),
                'actual_ending': float(saved.actual_ending) if saved.actual_ending is not None else None,
                'variance': float(saved.variance) if saved.variance is not None else None,
                'remarks': saved.remarks or '',
            })

    return rows


@invensync_bp.route('', methods=['GET'])
@login_required
def index():
    """Render the InvenSync DAILY ENDING INVENTORY page."""
    if not _can_access():
        flash('Access denied.', 'error')
        return redirect(url_for('main.dashboard'))

    target_date = _parse_date(request.args.get('date'))
    rows = _build_rows_for_date(target_date)

    pending_receiving_count = Requisition.query.filter(
        (Requisition.company_id == current_user.company_id) |
        (Requisition.destination_company_id == current_user.company_id),
        Requisition.status.in_(['Dispatched', 'dispatched', 'Partial', 'partial'])
    ).count() if current_user.company_id else 0

    return render_template(
        'user/invensync.html',
        inventory_date=target_date.strftime('%Y-%m-%d'),
        inventory_rows=rows,
        pending_receiving_count=pending_receiving_count,
    )


@invensync_bp.route('/save', methods=['POST'])
@login_required
def save_rows():
    """Upsert DAILY ENDING INVENTORY rows in invensync.db."""
    if not _can_access():
        return jsonify({'success': False, 'message': 'Access denied.'}), 403

    payload = request.get_json(silent=True) or {}
    target_date = _parse_date(payload.get('date'))
    rows = payload.get('rows') or []

    if not isinstance(rows, list):
        return jsonify({'success': False, 'message': 'Invalid rows payload.'}), 400

    now_ph = datetime.now(ZoneInfo("Asia/Manila"))
    saved_count = 0

    for r in rows:
        raw_item_id = r.get('raw_item_id')
        raw_item_name = (r.get('raw_item_name') or '').strip()
        if not raw_item_name:
            continue

        beg = _to_float(r.get('beg'), 0.0)
        actual_ending = _to_nullable_float(r.get('actual_ending'))
        remarks = (r.get('remarks') or '').strip()

        existing = None
        if raw_item_id is not None:
            existing = DailyEndingInventory.query.filter_by(
                company_id=current_user.company_id,
                inventory_date=target_date,
                raw_item_id=raw_item_id
            ).first()
        if not existing:
            existing = DailyEndingInventory.query.filter_by(
                company_id=current_user.company_id,
                inventory_date=target_date,
                raw_item_name=raw_item_name
            ).first()

        # Trans-In, Trans-Out, Wastage, and Sold are auto-synced from their respective modules
        trans_in = float(existing.trans_in or 0) if existing else _to_float(r.get('trans_in'), 0.0)
        trans_out = float(existing.trans_out or 0) if existing else _to_float(r.get('trans_out'), 0.0)
        wastage = float(existing.wastage or 0) if existing else _to_float(r.get('wastage'), 0.0)
        sold = float(existing.sold or 0) if existing else _to_float(r.get('sold'), 0.0)
        theoretical_ending = beg + trans_in - trans_out - wastage - sold
        variance = (actual_ending - theoretical_ending) if actual_ending is not None else None

        if existing:
            existing.beg = beg
            existing.trans_in = trans_in
            existing.trans_out = trans_out
            existing.wastage = wastage
            existing.sold = sold
            existing.theoretical_ending = theoretical_ending
            existing.actual_ending = actual_ending
            existing.variance = variance
            existing.remarks = remarks
            existing.updated_by = current_user.full_name
            existing.updated_at = now_ph
        else:
            db.session.add(DailyEndingInventory(
                company_id=current_user.company_id,
                inventory_date=target_date,
                raw_item_id=raw_item_id,
                raw_item_name=raw_item_name,
                beg=beg,
                trans_in=trans_in,
                trans_out=trans_out,
                wastage=wastage,
                sold=sold,
                theoretical_ending=theoretical_ending,
                actual_ending=actual_ending,
                variance=variance,
                remarks=remarks,
                updated_by=current_user.full_name,
                updated_at=now_ph,
            ))
        saved_count += 1

    db.session.commit()
    return jsonify({
        'success': True,
        'saved': saved_count,
        'message': f'Saved {saved_count} row(s) to DAILY ENDING INVENTORY ({target_date.strftime("%Y-%m-%d")}).'
    })


@invensync_bp.route('/export', methods=['GET'])
@login_required
def export_excel():
    """Export DAILY ENDING INVENTORY table to an Excel file."""
    if not _can_access():
        flash('Access denied.', 'error')
        return redirect(url_for('main.dashboard'))

    target_date = _parse_date(request.args.get('date'))
    q = (request.args.get('q') or '').strip().lower()
    rows = _build_rows_for_date(target_date)
    if q:
        rows = [r for r in rows if q in (r['raw_item_name'] or '').lower()]

    headers = [
        'Raw Item', 'Beg', 'Trans-In', 'Trans-Out', 'Wastage', 'Sold',
        'THEO', 'Actual Ending', 'Variance', 'Status', 'Remarks'
    ]
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = 'DAILY ENDING INVENTORY'

    ws.append(headers)
    header_fill = PatternFill(start_color='18181B', end_color='18181B', fill_type='solid')
    header_font = Font(bold=True, color='FFFFFF')
    for col_idx in range(1, len(headers) + 1):
        cell = ws.cell(row=1, column=col_idx)
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = Alignment(horizontal='left', vertical='center')

    for r in rows:
        var = r['variance']
        if var is None:
            status = ''
        elif var < 0:
            status = 'Short'
        elif var > 0:
            status = 'Over'
        else:
            status = 'Match'

        ws.append([
            r['raw_item_name'],
            r['beg'],
            r['trans_in'],
            r['trans_out'],
            r['wastage'],
            r['sold'],
            r['theoretical_ending'],
            r['actual_ending'] if r['actual_ending'] is not None else '',
            var if var is not None else '',
            status,
            r['remarks'],
        ])

    widths = [40, 12, 12, 12, 12, 12, 18, 16, 14, 12, 28]
    for idx, width in enumerate(widths, start=1):
        ws.column_dimensions[openpyxl.utils.get_column_letter(idx)].width = width

    output = io.BytesIO()
    wb.save(output)
    output.seek(0)

    return send_file(
        output,
        as_attachment=True,
        download_name=f'daily_ending_inventory_{target_date.strftime("%Y-%m-%d")}.xlsx',
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    )
