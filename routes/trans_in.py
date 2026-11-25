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
from models import RawItem, TransInRecord, DailyEndingInventory, Requisition

trans_in_bp = Blueprint('trans_in', __name__, url_prefix='/user/trans-in')


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


def _scoped_trans_in_query():
    if current_user.role == 'SYS-Admin' and current_user.company_id is None:
        return TransInRecord.query
    return TransInRecord.query.filter_by(company_id=current_user.company_id)


def _raw_items_list():
    if current_user.role == 'SYS-Admin' and current_user.company_id is None:
        items = RawItem.query.order_by(RawItem.raw_material.asc()).all()
    else:
        items = RawItem.query.filter_by(company_id=current_user.company_id).order_by(RawItem.raw_material.asc()).all()

    seen = set()
    unique = []
    for item in items:
        name = (item.raw_material or '').strip()
        key = name.lower()
        if not key or key in seen:
            continue
        seen.add(key)
        unique.append({'id': item.id, 'raw_material': name, 'uom': item.uom or ''})
    return unique


def _build_sheet_rows(target_date):
    """Return only saved trans_in rows for target_date (empty list if none yet)."""
    saved_rows = _scoped_trans_in_query().filter(
        TransInRecord.trans_date == target_date
    ).order_by(TransInRecord.id.asc()).all()

    return [
        {
            'id': r.id,
            'raw_item_id': r.raw_item_id,
            'raw_item_name': r.raw_item_name or '',
            'uom': r.uom or '',
            'qty': float(r.qty or 0),
            'cost': float(r.cost or 0),
            'total_cost': float(r.total_cost or 0),
            'remarks': r.remarks or '',
        }
        for r in saved_rows
    ]


def _set_daily_ending_trans_in(company_id, trans_date, raw_item_id, raw_item_name, exact_qty):
    """Set DAILY ENDING INVENTORY.trans_in to exact_qty for (company_id, trans_date, raw_item)."""
    existing = None
    if raw_item_id is not None:
        existing = DailyEndingInventory.query.filter_by(
            company_id=company_id,
            inventory_date=trans_date,
            raw_item_id=raw_item_id
        ).first()
    if not existing:
        existing = DailyEndingInventory.query.filter_by(
            company_id=company_id,
            inventory_date=trans_date,
            raw_item_name=raw_item_name
        ).first()

    now_ph = datetime.now(ZoneInfo("Asia/Manila"))
    if existing:
        existing.trans_in = exact_qty
        existing.theoretical_ending = (
            float(existing.beg or 0)
            + exact_qty
            - float(existing.trans_out or 0)
            - float(existing.wastage or 0)
            - float(existing.sold or 0)
        )
        if existing.actual_ending is not None:
            existing.variance = float(existing.actual_ending) - existing.theoretical_ending
        existing.updated_by = current_user.full_name
        existing.updated_at = now_ph
    elif exact_qty > 0:
        db.session.add(DailyEndingInventory(
            company_id=company_id,
            inventory_date=trans_date,
            raw_item_id=raw_item_id,
            raw_item_name=raw_item_name,
            beg=0.0,
            trans_in=exact_qty,
            trans_out=0.0,
            wastage=0.0,
            sold=0.0,
            theoretical_ending=exact_qty,
            actual_ending=None,
            variance=None,
            remarks='',
            updated_by=current_user.full_name,
            updated_at=now_ph,
        ))


@trans_in_bp.route('', methods=['GET'])
@login_required
def index():
    """Render the Excel-like Trans-In Purchases sheet."""
    if not _can_access():
        flash('Access denied.', 'error')
        return redirect(url_for('main.dashboard'))

    target_date = _parse_date(request.args.get('date'))
    rows = _build_sheet_rows(target_date)

    pending_receiving_count = Requisition.query.filter(
        (Requisition.company_id == current_user.company_id) |
        (Requisition.destination_company_id == current_user.company_id),
        Requisition.status.in_(['Dispatched', 'dispatched', 'Partial', 'partial'])
    ).count() if current_user.company_id else 0

    return render_template(
        'user/trans_in.html',
        trans_date=target_date.strftime('%Y-%m-%d'),
        sheet_rows=rows,
        raw_items=_raw_items_list(),
        pending_receiving_count=pending_receiving_count,
    )


@trans_in_bp.route('/list', methods=['GET'])
@login_required
def list_records():
    if not _can_access():
        return jsonify({'success': False, 'message': 'Access denied.'}), 403

    target_date = _parse_date(request.args.get('date'))
    rows = _build_sheet_rows(target_date)
    return jsonify({'success': True, 'items': rows, 'total': len(rows)})


@trans_in_bp.route('/submit', methods=['POST'])
@login_required
def submit_purchases():
    """Save/finalize Trans-In purchase sheet for the selected date and sync DAILY ENDING INVENTORY."""
    if not _can_access():
        return jsonify({'success': False, 'message': 'Access denied.'}), 403

    payload = request.get_json(silent=True) or {}
    trans_date = _parse_date(payload.get('date'))
    items = payload.get('items') or []

    if not isinstance(items, list):
        return jsonify({'success': False, 'message': 'Invalid items payload.'}), 400

    now_ph = datetime.now(ZoneInfo("Asia/Manila"))
    raw_lookup = {r['raw_material'].lower(): r for r in _raw_items_list()}

    # Track previous items on this date so deleted rows also zero out DAILY ENDING INVENTORY.trans_in
    prev_rows = _scoped_trans_in_query().filter(TransInRecord.trans_date == trans_date).all()
    prev_names = {(r.raw_item_id, (r.raw_item_name or '').strip()) for r in prev_rows}

    _scoped_trans_in_query().filter(TransInRecord.trans_date == trans_date).delete(synchronize_session=False)

    saved_count = 0
    new_names = set()

    # Validate all non-empty rows have both qty > 0 and cost > 0 before saving
    for row in items:
        raw_name = (row.get('raw_item_name') or '').strip()
        if not raw_name:
            continue
        qty = _to_float(row.get('qty'), 0.0)
        cost = _to_float(row.get('cost'), 0.0)
        if qty <= 0 or cost <= 0:
            return jsonify({
                'success': False,
                'message': f'"{raw_name}" is missing Qty or Cost (both must be greater than 0).'
            }), 400

    for row in items:
        raw_item_id = row.get('raw_item_id')
        raw_name = (row.get('raw_item_name') or '').strip()
        if not raw_name:
            continue

        matched = raw_lookup.get(raw_name.lower())
        raw_item_id = matched['id'] if matched else row.get('raw_item_id')
        uom = (row.get('uom') or (matched['uom'] if matched else '')).strip()
        qty = _to_float(row.get('qty'), 0.0)
        cost = _to_float(row.get('cost'), 0.0)
        remarks = (row.get('remarks') or '').strip()
        total_cost = qty * cost

        db.session.add(TransInRecord(
            company_id=current_user.company_id,
            trans_date=trans_date,
            raw_item_id=raw_item_id,
            raw_item_name=raw_name,
            qty=qty,
            uom=uom,
            cost=cost,
            total_cost=total_cost,
            remarks=remarks,
            created_by=current_user.full_name,
            created_at=now_ph,
        ))
        _set_daily_ending_trans_in(current_user.company_id, trans_date, raw_item_id, raw_name, qty)
        new_names.add((raw_item_id, raw_name))
        saved_count += 1

    # Zero out any previously saved items for this date that were removed from the grid
    for old_id, old_name in prev_names:
        if (old_id, old_name) not in new_names and old_name:
            _set_daily_ending_trans_in(current_user.company_id, trans_date, old_id, old_name, 0.0)

    db.session.commit()
    return jsonify({
        'success': True,
        'submitted': saved_count,
        'message': f'Finalized {saved_count} Trans-In item(s) for {trans_date.strftime("%Y-%m-%d")}.'
    })


@trans_in_bp.route('/delete/<int:record_id>', methods=['POST'])
@login_required
def delete_record(record_id):
    """Delete a saved Trans-In record from invensync.db and sync DAILY ENDING INVENTORY."""
    if not _can_access():
        return jsonify({'success': False, 'message': 'Access denied.'}), 403

    rec = _scoped_trans_in_query().filter_by(id=record_id).first()
    if not rec:
        return jsonify({'success': False, 'message': 'Record not found.'}), 404

    trans_date = rec.trans_date
    company_id = rec.company_id
    raw_item_id = rec.raw_item_id
    raw_item_name = rec.raw_item_name

    db.session.delete(rec)
    db.session.flush()

    remaining_qty = db.session.query(
        db.func.coalesce(db.func.sum(TransInRecord.qty), 0.0)
    ).filter(
        TransInRecord.company_id == company_id,
        TransInRecord.trans_date == trans_date,
        TransInRecord.raw_item_name == raw_item_name
    ).scalar() or 0.0

    _set_daily_ending_trans_in(company_id, trans_date, raw_item_id, raw_item_name, float(remaining_qty))
    db.session.commit()
    return jsonify({'success': True, 'message': f'Deleted "{raw_item_name}" from database.'})


@trans_in_bp.route('/export', methods=['GET'])
@login_required
def export_excel():
    if not _can_access():
        flash('Access denied.', 'error')
        return redirect(url_for('main.dashboard'))

    target_date = _parse_date(request.args.get('date'))
    q = (request.args.get('q') or '').strip().lower()
    rows = _build_sheet_rows(target_date)
    if q:
        rows = [r for r in rows if q in (r['raw_item_name'] or '').lower()]

    headers = ['Date', 'Raw Item', 'UOM', 'Qty', 'Cost', 'Total Cost', 'Remarks']
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = 'Trans-In'
    ws.append(headers)

    header_fill = PatternFill(start_color='18181B', end_color='18181B', fill_type='solid')
    header_font = Font(bold=True, color='FFFFFF')
    for col_idx in range(1, len(headers) + 1):
        cell = ws.cell(row=1, column=col_idx)
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = Alignment(horizontal='left', vertical='center')

    date_str = target_date.strftime('%Y-%m-%d')
    for r in rows:
        ws.append([
            date_str,
            r['raw_item_name'],
            r['uom'],
            r['qty'],
            r['cost'],
            r['total_cost'],
            r['remarks'],
        ])

    widths = [14, 42, 12, 12, 14, 14, 28]
    for idx, width in enumerate(widths, start=1):
        ws.column_dimensions[openpyxl.utils.get_column_letter(idx)].width = width

    output = io.BytesIO()
    wb.save(output)
    output.seek(0)
    return send_file(
        output,
        as_attachment=True,
        download_name=f'trans_in_{date_str}.xlsx',
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    )
