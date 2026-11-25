from flask import Blueprint, url_for
from flask_login import login_required
from models import WastageSpoilageRecord
from routes.movement_sheet import handle_index, handle_list, handle_submit, handle_delete, handle_export

wastage_spoilage_bp = Blueprint('wastage_spoilage', __name__, url_prefix='/user/wastage-spoilage')


@wastage_spoilage_bp.route('', methods=['GET'])
@login_required
def index():
    return handle_index(WastageSpoilageRecord, {
        'active_page': 'wastage_spoilage',
        'page_title': 'Wastage / Spoilage',
        'page_subtitle': 'Enter wastage & spoilage quantities & costs',
        'page_icon': 'fa-triangle-exclamation',
        'index_url': url_for('wastage_spoilage.index'),
        'list_url': url_for('wastage_spoilage.list_records'),
        'submit_url': url_for('wastage_spoilage.submit_records'),
        'delete_base': '/user/wastage-spoilage/delete/',
        'export_url': url_for('wastage_spoilage.export_excel'),
    })


@wastage_spoilage_bp.route('/list', methods=['GET'])
@login_required
def list_records():
    return handle_list(WastageSpoilageRecord)


@wastage_spoilage_bp.route('/submit', methods=['POST'])
@login_required
def submit_records():
    return handle_submit(WastageSpoilageRecord, 'wastage', 'Wastage / Spoilage')


@wastage_spoilage_bp.route('/delete/<int:record_id>', methods=['POST'])
@login_required
def delete_record(record_id):
    return handle_delete(WastageSpoilageRecord, 'wastage', record_id)


@wastage_spoilage_bp.route('/export', methods=['GET'])
@login_required
def export_excel():
    return handle_export(WastageSpoilageRecord, 'Wastage Spoilage', 'wastage_spoilage')
