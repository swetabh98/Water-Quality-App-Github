from flask import Blueprint, render_template, redirect, url_for, flash, request
from flask_login import login_user, logout_user, login_required
from werkzeug.security import generate_password_hash, check_password_hash
import os

from ..models import db, User, Department
from ..forms import LoginForm, RegisterForm

auth_bp = Blueprint('auth', __name__)


def _is_vercel_demo_mode() -> bool:
    return bool(os.environ.get("VERCEL") or os.environ.get("WATER_QUALITY_DEMO_MODE"))


def _ensure_demo_admin_user() -> User:
    """
    Ensures Vercel demo login always has a user.

    Login shown to user:
      ID: admin
      Password: admin123

    Stored email:
      admin@demo.com
    """
    user = User.query.filter_by(email="admin@demo.com").first()
    if user is None:
        user = User(
            email="admin@demo.com",
            password=generate_password_hash("admin123"),
            role="admin",
        )
        db.session.add(user)
        db.session.commit()
        return user

    user.password = generate_password_hash("admin123")
    user.role = "admin"
    db.session.commit()
    return user


@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    form = LoginForm()

    # ------------------------------------------------------------------
    # Vercel demo login bypass
    # ------------------------------------------------------------------
    # The original LoginForm uses Email() validation, so typing "admin"
    # will never pass normal validation. This block intentionally runs
    # before form.validate_on_submit() and maps admin/admin123 to a real
    # stored demo email user.
    # ------------------------------------------------------------------
    if request.method == 'POST' and _is_vercel_demo_mode():
        login_id = (request.form.get('email') or '').strip().lower()
        password = request.form.get('password') or ''

        if login_id in {'admin', 'admin@demo.com'} and password == 'admin123':
            user = _ensure_demo_admin_user()
            login_user(user, remember=True, force=True)
            flash('Hi Admin!', 'success')
            return redirect(url_for('reports.dashboard'))

    if form.validate_on_submit():
        email = (form.email.data or '').strip().lower()
        user = User.query.filter_by(email=email).first()
        if user and check_password_hash(user.password, form.password.data):
            login_user(user, remember=True)

            username = user.email.split("@")[0].capitalize()
            flash(f"Hi {username}!", "success")

            return redirect(url_for('reports.dashboard'))

        flash('Invalid email or password.', 'danger')

    return render_template('login.html', form=form)


@auth_bp.route('/register', methods=['GET', 'POST'])
def register():
    form = RegisterForm()
    form.departments.choices = [(d.id, d.name) for d in Department.query.all()]

    if form.validate_on_submit():
        existing_user = User.query.filter_by(email=form.email.data).first()
        if existing_user:
            flash('That email address is already registered. Please use a different email or log in.', 'warning')
            return redirect(url_for('auth.register'))

        hashed_pw = generate_password_hash(form.password.data)
        new_user = User(
            email=form.email.data,
            password=hashed_pw,
            role='user'
        )

        selected_depts = Department.query.filter(Department.id.in_(form.departments.data)).all()
        new_user.departments.extend(selected_depts)

        db.session.add(new_user)
        db.session.commit()

        flash('Account created successfully. You can now log in.', 'success')
        return redirect(url_for('auth.login'))

    return render_template('register.html', form=form)


@auth_bp.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('auth.login'))
