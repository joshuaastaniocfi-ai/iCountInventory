# Standard library imports
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

# Third-party imports
from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_user, logout_user, login_required, current_user
from flask_mail import Message

# Local imports
from extensions import db, mail
from models import User, Company
from helpers import get_redirect_url_for_user, log_activity

# Create blueprint
auth = Blueprint('auth', __name__)


@auth.route('/signup', methods=['GET', 'POST'])
def signup():
    # Get all companies for the dropdown
    companies = Company.query.all()
    
    if request.method == 'POST':
        full_name = request.form['full_name']
        username = request.form['username']
        email = request.form['email']
        company_id = request.form['company_id']
        password = request.form['password']

        if User.query.filter_by(username=username).first():
            flash('Username already exists', 'danger')
            return redirect(url_for('auth.signup'))

        if User.query.filter_by(email=email).first():
            flash('Email already exists', 'danger')
            return redirect(url_for('auth.signup'))

        new_user = User(
            full_name=full_name, 
            username=username, 
            email=email
        )
        
        # Special handling for SYS-Admin users
        if username == 'admin':
            new_user.role = 'SYS-Admin'
            new_user.email_verified = True  # SYS-Admin accounts are auto-verified
            new_user.company_id = None  # SYS-Admin has no company affiliation
        elif username == 'wh-admin':
            new_user.role = 'WH-Admin'
            new_user.email_verified = True  # WH-Admin accounts are auto-verified
            # Verify company exists
            company = Company.query.get(company_id)
            if not company:
                flash('Invalid company selected', 'danger')
                return redirect(url_for('auth.signup'))
            new_user.company_id = company_id
        else:
            new_user.role = 'User'
            new_user.email_verified = False
            # Verify company exists
            company = Company.query.get(company_id)
            if not company:
                flash('Invalid company selected', 'danger')
                return redirect(url_for('auth.signup'))
            new_user.company_id = company_id

        new_user.set_password(password)

        # Generate verification token for non-admin users
        if new_user.role not in ['SYS-Admin', 'WH-Admin']:
            token = new_user.generate_verification_token()

        db.session.add(new_user)
        db.session.commit()

        # Send email notification to admins
        admins = User.query.filter(User.role.in_(['SYS-Admin', 'WH-Admin'])).all()
        if admins:
            for admin in admins:
                msg = Message(
                    subject=f"[No Reply] New User Registration: {new_user.username}",
                    recipients=[admin.email],
                    body=f"A new user has registered:\n\nUsername: {new_user.username}\nFull Name: {new_user.full_name}\nEmail: {new_user.email}\nCompany: {company.name if company else 'N/A'}\n\nThis is an automated message. Please do not reply to this email."
                )
                mail.send(msg)

        # Send verification email for non-admin users
        if new_user.role not in ['SYS-Admin', 'WH-Admin']:
            try:
                verification_url = url_for('auth.verify_email', token=token, _external=True)
                msg = Message(
                    subject="[No Reply] Verify Your Email - iCount",
                    recipients=[email],
                    html=f"""
                    <div style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto;">
                        <div style="background-color: #4a5da7; color: white; padding: 20px; text-align: center;">
                            <h2>Welcome to iCount!</h2>
                        </div>
                        <div style="padding: 30px; background-color: #f8f9fa;">
                            <h3>Hi {full_name},</h3>
                            <p>Thank you for signing up for iCount. To complete your registration, please verify your email address by clicking the button below:</p>
                            
                            <div style="text-align: center; margin: 30px 0;">
                                <a href="{verification_url}" style="background-color: #4a5da7; color: white; padding: 12px 30px; text-decoration: none; border-radius: 5px; display: inline-block; font-weight: bold;">
                                    Verify Email Address
                                </a>
                            </div>
                            
                            <p>If the button doesn't work, you can copy and paste this link into your browser:</p>
                            <p style="word-break: break-all; color: #4a5da7;">{verification_url}</p>
                            
                            <p style="color: #666; font-size: 14px; margin-top: 30px;">
                                This verification link will expire in 24 hours. If you didn't create an account with iCount, please ignore this email.
                            </p>
                            
                            <p style="color: #666; font-size: 14px; margin-top: 20px; border-top: 1px solid #dee2e6; padding-top: 20px;">
                                <strong>⚠️ No Reply:</strong> This is an automated message. Please do not reply to this email.
                            </p>
                        </div>
                        <div style="background-color: #e9ecef; padding: 15px; text-align: center; color: #666; font-size: 12px;">
                            © 2025 iCount Inventory System. All rights reserved.
                        </div>
                    </div>
                    """
                )
                mail.send(msg)
                return render_template('auth/verification_pending.html', email=email)
            except Exception as e:
                flash(f'Account created but failed to send verification email: {str(e)}', 'warning')
                return redirect(url_for('auth.login'))
        else:
            # SYS-Admin users are auto-verified, redirect to login
            flash('SYS-Admin account created successfully. You can now log in.', 'success')
        return redirect(url_for('auth.login'))

    return render_template('auth/signup.html', companies=companies)


@auth.route('/verify_email/<token>')
def verify_email(token):
    user = User.query.filter_by(verification_token=token).first()
    
    if not user:
        flash('Invalid or expired verification link.', 'danger')
        return redirect(url_for('auth.login'))
    
    if user.email_verified:
        flash('Email already verified. You can log in.', 'info')
        return redirect(url_for('auth.login'))
    
    # Verify the user
    user.email_verified = True
    user.verification_token = None  # Clear the token after use
    db.session.commit()
    
    flash('Email successfully verified! You can now log in.', 'success')
    
    # Get redirect URL based on user role and device type
    redirect_url = get_redirect_url_for_user(user, request.headers.get('User-Agent', ''))
    return redirect(redirect_url)


@auth.route('/forgot_password', methods=['GET', 'POST'])
def forgot_password():
    if request.method == 'POST':
        email = request.form.get('email', '').strip()
        if not email:
            flash('Please provide your email.', 'warning')
            return redirect(url_for('auth.forgot_password'))

        user = User.query.filter_by(email=email).first()
        if not user:
            # Don't reveal if email exists for security
            flash('If an account exists with this email, you will receive a password reset link.', 'info')
            return redirect(url_for('auth.login'))

        # Generate reset token
        token = user.generate_verification_token()  # We'll reuse this method for reset tokens
        db.session.commit()

        try:
            reset_url = url_for('auth.reset_password', token=token, _external=True)
            msg = Message(
                subject="[No Reply] Reset Your Password - iCount",
                recipients=[user.email],
                html=f"""
                <div style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto;">
                    <div style="background-color: #4a5da7; color: white; padding: 20px; text-align: center;">
                        <h2>Reset Your Password</h2>
                    </div>
                    <div style="padding: 30px; background-color: #f8f9fa;">
                        <h3>Hi {user.full_name},</h3>
                        <p>You requested to reset your password. Click the button below to set a new password:</p>
                        <div style="text-align: center; margin: 30px 0;">
                            <a href="{reset_url}" style="background-color: #4a5da7; color: white; padding: 12px 30px; text-decoration: none; border-radius: 5px; display: inline-block; font-weight: bold;">
                                Reset Password
                            </a>
                        </div>
                        <p>If the button doesn't work, copy and paste this link into your browser:</p>
                        <p style="word-break: break-all; color: #4a5da7;">{reset_url}</p>
                        <p style="color: #666; font-size: 14px; margin-top: 30px;">
                            This password reset link will expire in 24 hours. If you didn't request a password reset, please ignore this email.
                        </p>
                        
                        <p style="color: #666; font-size: 14px; margin-top: 20px; border-top: 1px solid #dee2e6; padding-top: 20px;">
                            <strong>⚠️ No Reply:</strong> This is an automated message. Please do not reply to this email.
                        </p>
                    </div>
                    <div style="background-color: #e9ecef; padding: 15px; text-align: center; color: #666; font-size: 12px;">
                        © 2025 iCount Inventory System. All rights reserved.
                    </div>
                </div>
                """
            )
            mail.send(msg)
            flash('If an account exists with this email, you will receive a password reset link.', 'info')
            return redirect(url_for('auth.login'))
        except Exception as e:
            flash(f'Failed to send password reset email: {str(e)}', 'danger')
            return redirect(url_for('auth.forgot_password'))

    return render_template('auth/forgot_password.html')


@auth.route('/reset_password/<token>', methods=['GET', 'POST'])
def reset_password(token):
    # First verify the token
    user = User.query.filter_by(verification_token=token).first()
    if not user:
        flash('Invalid or expired password reset link.', 'danger')
        return redirect(url_for('auth.login'))

    if request.method == 'POST':
        password = request.form.get('password')
        # Update password and clear token (validation handled on client-side)
        user.set_password(password or '')
        user.verification_token = None
        db.session.commit()

        flash('Your password has been reset successfully. You can now log in.', 'success')
        return redirect(url_for('auth.login'))

    return render_template('auth/reset_password.html', token=token)


@auth.route('/resend_verification', methods=['GET', 'POST'])
def resend_verification():
    # Allow user to request a new verification email if not verified yet
    if request.method == 'POST':
        email = request.form.get('email', '').strip()
        if not email:
            flash('Please provide your email.', 'warning')
            return redirect(url_for('auth.resend_verification'))

        user = User.query.filter_by(email=email).first()
        if not user:
            flash('No account found with that email.', 'danger')
            return redirect(url_for('auth.resend_verification'))

        if user.email_verified:
            flash('Email already verified. You can log in.', 'info')
            return redirect(url_for('auth.login'))

        # Generate a fresh token and send email
        token = user.generate_verification_token()
        db.session.commit()

        try:
            verification_url = url_for('auth.verify_email', token=token, _external=True)
            msg = Message(
                subject="[No Reply] Verify Your Email - iCount",
                recipients=[user.email],
                html=f"""
                <div style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto;">
                    <div style="background-color: #4a5da7; color: white; padding: 20px; text-align: center;">
                        <h2>Verify your email</h2>
                    </div>
                    <div style="background-color: #f8f9fa;">
                        <h3>Hi {user.full_name},</h3>
                        <p>You requested a new verification link. Click the button below to verify your email address:</p>
                        <div style="text-align: center; margin: 30px 0;">
                            <a href="{verification_url}" style="background-color: #4a5da7; color: white; padding: 12px 30px; text-decoration: none; border-radius: 5px; display: inline-block; font-weight: bold;">
                                Verify Email Address
                            </a>
                        </div>
                        <p>If the button doesn't work, copy and paste this link into your browser:</p>
                        <p style="word-break: break-all; color: #4a5da7;">{verification_url}</p>
                        <p style="color: #666; font-size: 14px; margin-top: 30px;">This verification link will expire in 24 hours.</p>
                        
                        <p style="color: #666; font-size: 14px; margin-top: 20px; border-top: 1px solid #dee2e6; padding-top: 20px;">
                            <strong>⚠️ No Reply:</strong> This is an automated message. Please do not reply to this email.
                        </p>
                    </div>
                    <div style="background-color: #e9ecef; padding: 15px; text-align: center; color: #666; font-size: 12px;">
                        © 2025 iCount Inventory System. All rights reserved.
                    </div>
                </div>
                """
            )
            mail.send(msg)
            flash('A new verification email has been sent.', 'success')
            return render_template('auth/verification_pending.html', email=user.email)
        except Exception as e:
            flash(f'Failed to send verification email: {str(e)}', 'danger')
            return redirect(url_for('auth.resend_verification'))

    # GET: optional prefill from query string
    prefill_email = request.args.get('email', '').strip()
    return render_template('auth/resend_verification.html', email=prefill_email)


@auth.route('/login', methods=['GET', 'POST'])
def login():
    # If user is already logged in, redirect to dashboard
    if current_user.is_authenticated:
        return redirect(url_for('main.dashboard'))

    if request.method == 'POST':
        username = request.form['username'].strip()
        password = request.form['password']
        
        # First check if user exists
        user = User.query.filter_by(username=username).first()
        if not user:
            flash('Username not found', 'danger')
            return redirect(url_for('auth.login'))

        # Then check password
        if not user.check_password(password):
            flash('Incorrect password', 'danger')
            return redirect(url_for('auth.login'))

        # Check verification status
        if not user.email_verified:
            flash('Please verify your email address before logging in. Check your email for the verification link.', 'warning')
            return redirect(url_for('auth.login'))

        # Check banned status
        if getattr(user, 'is_banned', False):
            flash('Your account has been banned. You cannot access the system. Please contact your administrator.', 'danger')
            return redirect(url_for('auth.login'))

        # All checks passed, attempt login
        try:
            login_user(user)
            flash('Logged in successfully!', 'success')
            
            # Get redirect URL based on user role and device type
            redirect_url = get_redirect_url_for_user(user, request.headers.get('User-Agent', ''))
            return redirect(redirect_url)
                
        except Exception as e:
            flash(f'Login failed: {str(e)}', 'danger')
            return redirect(url_for('auth.login'))

    return render_template('auth/login.html')


@auth.route('/logout')
@login_required
def logout():
    logout_user()
    flash('You have been logged out.', 'info')
    return redirect(url_for('auth.login'))


@auth.route('/profile')
@login_required
def profile():
    return render_template('auth/profile.html')

