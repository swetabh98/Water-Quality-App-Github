# sms3_reports.py

import json
import re
from flask import Blueprint, render_template, redirect, url_for, request, flash, send_file, current_app
from urllib.parse import unquote_plus
from collections import defaultdict
from datetime import datetime
from flask_login import login_required, current_user
from sqlalchemy.orm import joinedload, selectinload

from ..models import db, Department, Equipment, Report, ReportSection, ReportParameter
from ..utils.pdf_export import generate_pdf_report
from app.utils.email_notifications import send_report_notification  # ✅ Email import
from app.utils.range_notifications import handle_range_alerts  # ✅ Range alerts import

sms3_reports_bp = Blueprint('sms3_reports', __name__)


def _report_eager_options():
    """Common eager-loading options for report pages that read sections/parameters."""
    return (
        joinedload(Report.department),
        joinedload(Report.equipment),
        selectinload(Report.sections).selectinload(ReportSection.parameters),
    )

def _build_report_context(report):
    """Processes an already-loaded report into the template context."""
    all_params = {}
    for section in report.sections:
        for param in section.parameters:
            if param.name:
                display_value = param.range_value if param.range_value is not None else param.value
                all_params[param.name] = display_value

    return {"report": report, "params": all_params}


# --- Unified Helper function for all views ---
def _get_report_context(report_id):
    """Fetches a report and processes its parameters into a simple key-value dictionary."""
    report = Report.query.options(*_report_eager_options()).get_or_404(report_id)
    return _build_report_context(report)

# --- Route to Add a New Report ---
@sms3_reports_bp.route('/sms3/fill_report/<int:dept_id>/<int:equip_id>', methods=['GET', 'POST'])
@login_required
def fill_report_sms3(dept_id, equip_id):
    dept = Department.query.get_or_404(dept_id)
    equip = Equipment.query.get(equip_id) if equip_id != 0 else None
    datetime_now = datetime.now()

    if request.method == 'POST':
        report = Report(user_id=current_user.id, department_id=dept.id, equipment_id=equip.id if equip else None, sampling_time=datetime_now)
        db.session.add(report)
        db.session.flush()
        section = ReportSection(report_id=report.id, sheet_name="SMS-3 Report")
        db.session.add(section)
        db.session.flush()
        
        for key, value in request.form.items():
            if not value or not value.strip() or key == 'csrf_token':
                continue
            param_db_name = key.rsplit('_value', 1)[0]
            try:
                numeric_value, text_value = (float(value), None)
            except (ValueError, TypeError):
                numeric_value, text_value = (None, value)
            db.session.add(ReportParameter(section_id=section.id, name=param_db_name, value=numeric_value, range_value=text_value))

        db.session.commit()

        # ✅ Run range alerts only after the report is saved
        handle_range_alerts(report)  # emails only if any outliers

        send_report_notification(report, app=current_app, db=db, action="submitted")  # ✅ Email on submit
        flash("SMS-3 Report submitted successfully!", "success")
        return redirect(url_for('reports.summary'))

    return render_template("pages/sms3_report.html", department=dept, equipment=equip, sampling_time=datetime_now, existing_data={})

# --- Route to View an SMS-3 Report ---
@sms3_reports_bp.route('/sms3/report/<int:report_id>', endpoint='view_report_sms3')
@login_required
def view_report_sms3(report_id):
    context = _get_report_context(report_id)
    report = context['report']
    
    context['department'] = report.department
    context['equipment'] = report.equipment
    context['sampling_time'] = report.sampling_time
    context['existing_data'] = context.get('params', {})

    return render_template('pages/sms3_view.html', **context)

# --- Route to Edit an SMS-3 Report ---
@sms3_reports_bp.route('/sms3/report/<int:report_id>/edit', methods=['GET', 'POST'], endpoint='edit_report_sms3')
@login_required
def edit_report_sms3(report_id):
    report = Report.query.options(*_report_eager_options()).get_or_404(report_id)
    
    if current_user.role != 'admin' and report.department_id not in [d.id for d in current_user.departments]:
        flash("You are not authorized to edit this report.", "danger")
        return redirect(url_for('reports.summary'))

    if request.method == 'POST':
        section_ids = [s.id for s in report.sections]
        if section_ids:
            ReportParameter.query.filter(ReportParameter.section_id.in_(section_ids)).delete(synchronize_session=False)

        section = report.sections[0]
        for key, value in request.form.items():
            if not value or not value.strip() or key == 'csrf_token':
                continue
            param_db_name = key.rsplit('_value', 1)[0]
            try:
                numeric_value, text_value = (float(value), None)
            except (ValueError, TypeError):
                numeric_value, text_value = (None, value)
            db.session.add(ReportParameter(section_id=section.id, name=param_db_name, value=numeric_value, range_value=text_value))
        
        db.session.commit()
        send_report_notification(report, app=current_app, db=db, action="updated")  # ✅ Email on update
        flash(f"Report ID {report.id} updated successfully!", "success")
        return redirect(url_for('reports.summary'))

    context = _build_report_context(report)
    context['existing_data'] = context.get('params', {})
    context['department'] = report.department
    context['equipment'] = report.equipment
    context['sampling_time'] = report.sampling_time

    return render_template('pages/sms3_edit_form.html', **context)

# --- Route to Delete an SMS-3 Report ---
@sms3_reports_bp.route('/sms3/report/<int:report_id>/delete', methods=['POST'], endpoint='delete_report_sms3')
@login_required
def delete_report_sms3(report_id):
    report = Report.query.get_or_404(report_id)
    if current_user.role != 'admin' and report.department_id not in [d.id for d in current_user.departments]:
        flash("You are not authorized to delete this report.", "danger")
        return redirect(url_for('reports.summary'))
    db.session.delete(report)
    db.session.commit()
    flash(f"Report ID {report.id} has been deleted.", "success")
    return redirect(url_for('reports.summary'))

# --- Route to Download PDF for SMS-3 ---
@sms3_reports_bp.route('/sms3/report/<int:report_id>/pdf', endpoint='download_pdf_sms3')
@login_required
def download_pdf_sms3(report_id):
    context = _get_report_context(report_id)
    report = context['report']
    context['department'] = report.department
    context['equipment'] = report.equipment
    context['sampling_time'] = report.sampling_time
    context['params'] = context.get('params', {})  # ✅ Fixed key for PDF template

    try:
        pdf = generate_pdf_report("pages/sms3_pdf.html", context)
        if pdf:
            return send_file(pdf, as_attachment=True, download_name=f"SMS3_Report_{report_id}.pdf", mimetype='application/pdf')
    except Exception as e:
        flash("PDF generation failed: Template not found or error in template.", "danger")
    
    return redirect(url_for('sms3_reports.view_report_sms3', report_id=report_id))