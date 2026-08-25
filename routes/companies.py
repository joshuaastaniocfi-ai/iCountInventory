# Standard library imports
from datetime import datetime
from zoneinfo import ZoneInfo
import os
from werkzeug.utils import secure_filename

# Third-party imports
from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify, current_app
from flask_login import login_required, current_user

# Local imports
from extensions import db
from models import Company, User
from helpers import sys_admin_required, log_activity

# Create blueprint with URL prefix as required by project specifications
companies = Blueprint('companies', __name__, url_prefix='/companies')

# Define allowed extensions (moved outside of app context)
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif'}

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


@companies.route('/companies')
@login_required
@sys_admin_required
def view_companies():
    """Display all companies"""
    companies = Company.query.all()
    stats = {
        'companies': len(companies),
        'users': User.query.count(),
        'with_logo': sum(1 for c in companies if c.logo),
    }
    return render_template('admin/companies.html', companies=companies, stats=stats)


@companies.route('/add_company', methods=['POST'])
@login_required
@sys_admin_required
def add_company():
    """Add a new company"""
    # Define UPLOAD_FOLDER within application context
    UPLOAD_FOLDER = os.path.join(current_app.root_path, 'static', 'company_logos')
    
    try:
        name = request.form['name'].strip()
        franchise_name = request.form.get('franchise_name', '').strip()
        
        # Validate required fields
        if not name:
            flash('Company name is required', 'error')
            return redirect(url_for('companies.view_companies'))
        
        # Check if company already exists
        existing_company = Company.query.filter_by(name=name).first()
        if existing_company:
            flash('Company with this name already exists', 'error')
            return redirect(url_for('companies.view_companies'))
        
        # Create new company
        new_company = Company(name=name, franchise_name=franchise_name if franchise_name else None)
        db.session.add(new_company)
        db.session.flush()  # Get the ID without committing
        
        # Handle logo upload if provided
        logo_path = None
        if 'logo' in request.files:
            file = request.files['logo']
            if file and file.filename != '' and allowed_file(file.filename):
                # Save the file with a secure filename that includes company ID to avoid conflicts
                filename = secure_filename(file.filename)
                # Add company ID prefix to avoid filename conflicts
                name_without_ext, ext = os.path.splitext(filename)
                filename = f"{name_without_ext}_company_{new_company.id}{ext}"
                filepath = os.path.join(UPLOAD_FOLDER, filename)
                file.save(filepath)
                
                # Save relative path
                logo_path = f"company_logos/{filename}"
                new_company.logo = logo_path
        
        db.session.commit()
        
        flash(f'Company "{name}" added successfully!', 'success')
        
        # Log the activity
        log_activity(
            action="Company Added",
            details=f"Added company: {name}"
        )
        
    except Exception as e:
        db.session.rollback()
        flash(f'Error adding company: {str(e)}', 'error')
        log_activity(
            action="Company Add Error",
            details=f"Failed to add company: {str(e)}"
        )
    
    return redirect(url_for('companies.view_companies'))


@companies.route('/edit_company/<int:company_id>', methods=['POST'])
@login_required
@sys_admin_required
def edit_company(company_id):
    """Edit an existing company"""
    # Define UPLOAD_FOLDER within application context
    UPLOAD_FOLDER = os.path.join(current_app.root_path, 'static', 'company_logos')
    
    try:
        company = Company.query.get_or_404(company_id)
        
        name = request.form['name'].strip()
        franchise_name = request.form.get('franchise_name', '').strip()
        
        # Validate required fields
        if not name:
            flash('Company name is required', 'error')
            return redirect(url_for('companies.view_companies'))
        
        # Check if another company already exists with this name
        existing_company = Company.query.filter(Company.name == name, Company.id != company_id).first()
        if existing_company:
            flash('Company with this name already exists', 'error')
            return redirect(url_for('companies.view_companies'))
        
        # Store old logo path for deletion if needed
        old_logo_path = company.logo
        
        # Update company details
        company.name = name
        company.franchise_name = franchise_name if franchise_name else None
        
        # Handle logo upload if provided
        if 'logo' in request.files:
            file = request.files['logo']
            if file and file.filename != '' and allowed_file(file.filename):
                # Delete old logo if it exists
                if old_logo_path:
                    old_file_path = os.path.join(UPLOAD_FOLDER, os.path.basename(old_logo_path))
                    if os.path.exists(old_file_path):
                        os.remove(old_file_path)
                
                # Save the new file with a secure filename that includes company ID to avoid conflicts
                filename = secure_filename(file.filename)
                # Add company ID prefix to avoid filename conflicts
                name_without_ext, ext = os.path.splitext(filename)
                filename = f"{name_without_ext}_company_{company.id}{ext}"
                filepath = os.path.join(UPLOAD_FOLDER, filename)
                file.save(filepath)
                
                # Save relative path
                logo_path = f"company_logos/{filename}"
                company.logo = logo_path
            elif not file.filename:
                # If no new file was uploaded, keep the existing logo
                company.logo = old_logo_path
        else:
            # If no file input was provided, keep the existing logo
            company.logo = old_logo_path
        
        db.session.commit()
        
        flash(f'Company "{name}" updated successfully!', 'success')
        
        # Log the activity
        log_activity(
            action="Company Updated",
            details=f"Updated company: {name}"
        )
        
    except Exception as e:
        db.session.rollback()
        flash(f'Error updating company: {str(e)}', 'error')
        log_activity(
            action="Company Update Error",
            details=f"Failed to update company: {str(e)}"
        )
    
    return redirect(url_for('companies.view_companies'))


@companies.route('/delete_company/<int:company_id>', methods=['POST'])
@login_required
@sys_admin_required
def delete_company(company_id):
    """Delete a company"""
    # Define UPLOAD_FOLDER within application context
    UPLOAD_FOLDER = os.path.join(current_app.root_path, 'static', 'company_logos')
    
    try:
        # Prevent deletion of default company or current user's company
        if company_id == current_user.company_id:
            flash('Cannot delete your own company', 'error')
            return redirect(url_for('companies.view_companies'))
        
        company = Company.query.get_or_404(company_id)
        
        # Check if company has users (prevent deletion if it does)
        user_count = User.query.filter_by(company_id=company_id).count()
        if user_count > 0:
            flash(f'Cannot delete company with {user_count} users. Reassign users first.', 'error')
            return redirect(url_for('companies.view_companies'))
        
        # Delete company logo if it exists
        if company.logo:
            logo_path = os.path.join(UPLOAD_FOLDER, os.path.basename(company.logo))
            if os.path.exists(logo_path):
                os.remove(logo_path)
        
        # Delete the company
        company_name = company.name
        db.session.delete(company)
        db.session.commit()
        
        flash(f'Company "{company_name}" deleted successfully!', 'success')
        
        # Log the activity
        log_activity(
            action="Company Deleted",
            details=f"Deleted company: {company_name}"
        )
        
    except Exception as e:
        db.session.rollback()
        flash(f'Error deleting company: {str(e)}', 'error')
        log_activity(
            action="Company Delete Error",
            details=f"Failed to delete company: {str(e)}"
        )
    
    return redirect(url_for('companies.view_companies'))