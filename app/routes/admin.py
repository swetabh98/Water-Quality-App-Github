from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_required, current_user

# --- Corrected Relative Import ---
from ..models import db, Department, Equipment

admin_bp = Blueprint('admin', __name__)

@admin_bp.route('/admin/manage', methods=['GET', 'POST'])
@login_required
def manage():
    if current_user.role != 'admin':
        flash("Access denied.", "danger")
        return redirect(url_for('reports.dashboard'))

    departments = Department.query.all()

    # Add new department
    if request.method == 'POST':
        new_dept = request.form.get('new_department')
        if new_dept:
            d = Department(name=new_dept.strip())
            db.session.add(d)
            db.session.commit()
            flash("Department added successfully.")
            return redirect(url_for('admin.manage'))

    return render_template("manage_dept_equip.html", departments=departments)

@admin_bp.route('/admin/delete_dept/<int:id>')
@login_required
def delete_dept(id):
    if current_user.role != 'admin':
        return redirect(url_for('reports.dashboard'))
    d = Department.query.get(id)
    db.session.delete(d)
    db.session.commit()
    return redirect(url_for('admin.manage'))

@admin_bp.route('/admin/add_equip/<int:dept_id>', methods=['POST'])
@login_required
def add_equipment(dept_id):
    name = request.form.get('equip_name')
    if name:
        eq = Equipment(name=name.strip(), department_id=dept_id)
        db.session.add(eq)
        db.session.commit()
    return redirect(url_for('admin.manage'))

@admin_bp.route('/admin/delete_equip/<int:equip_id>')
@login_required
def delete_equipment(equip_id):
    eq = Equipment.query.get(equip_id)
    db.session.delete(eq)
    db.session.commit()
    return redirect(url_for('admin.manage'))