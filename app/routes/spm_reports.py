import json
import re
from flask import Blueprint, render_template, redirect, url_for, request, flash, send_file
from urllib.parse import unquote_plus
from collections import defaultdict
from datetime import datetime
from flask_login import login_required, current_user
from sqlalchemy.orm import joinedload, selectinload
from flask import current_app

from ..models import db, Department, Equipment, Report, ReportSection, ReportParameter
from ..utils.pdf_export import generate_pdf_report
from app.utils.range_notifications import handle_range_alerts  # ✅ Range alerts import

spm_reports_bp = Blueprint('spm_reports', __name__)


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


def _get_report_context(report_id):
    """Fetches a report and processes its parameters into a simple key-value dictionary."""
    report = Report.query.options(*_report_eager_options()).get_or_404(report_id)
    return _build_report_context(report)

# --- Route to Add a New Report ---
@spm_reports_bp.route('/spm/fill_report/<int:dept_id>/<int:equip_id>', methods=['GET', 'POST'])
@login_required
def fill_report_spm(dept_id, equip_id):
    dept = Department.query.get_or_404(dept_id)
    equip = Equipment.query.get(equip_id) if equip_id != 0 else None
    datetime_now = datetime.now()

    if request.method == 'POST':
        report = Report(user_id=current_user.id, department_id=dept.id, equipment_id=equip.id if equip else None, sampling_time=datetime_now)
        db.session.add(report)
        db.session.flush()
        section = ReportSection(report_id=report.id, sheet_name="SPM Report")
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

        try:
            from app.utils.email_notifications import send_report_notification
            send_report_notification(report, current_app._get_current_object(), db, action="submitted")
        except Exception as e:
            print(f"❌ Failed to send email for SPM report {report.id}: {e}")

        flash("SPM Report submitted successfully!", "success")
        return redirect(url_for('reports.summary'))

    return render_template("pages/spm_report.html", department=dept, equipment=equip, sampling_time=datetime_now, existing_data={})

# --- Route to View a SPM Report ---
@spm_reports_bp.route('/spm/report/<int:report_id>', endpoint='view_report_spm')
@login_required
def view_report_spm(report_id):
    context = _get_report_context(report_id)
    report = context['report']
    context['department'] = report.department
    context['equipment'] = report.equipment
    context['sampling_time'] = report.sampling_time
    context['existing_data'] = context.get('params', {})
    return render_template('pages/spm_view.html', **context)

# --- Route to Edit a SPM Report ---
@spm_reports_bp.route('/spm/report/<int:report_id>/edit', methods=['GET', 'POST'], endpoint='edit_report_spm')
@login_required
def edit_report_spm(report_id):
    report = Report.query.options(*_report_eager_options()).get_or_404(report_id)

    if current_user.role != 'admin' and report.department_id not in [d.id for d in current_user.departments]:
        flash("You are not authorized to edit reports for this department.", "danger")
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

        try:
            from app.utils.email_notifications import send_report_notification
            send_report_notification(report, current_app._get_current_object(), db, action="updated")
        except Exception as e:
            print(f"❌ Failed to send email for updated SPM report {report.id}: {e}")

        flash(f"Report ID {report.id} updated successfully!", "success")
        return redirect(url_for('reports.summary'))

    context = _build_report_context(report)
    context['existing_data'] = context.get('params', {})
    context['department'] = report.department
    context['equipment'] = report.equipment
    context['sampling_time'] = report.sampling_time

    return render_template('pages/spm_edit.html', **context)

# --- Route to Delete a SPM Report ---
@spm_reports_bp.route('/spm/report/<int:report_id>/delete', methods=['POST'], endpoint='delete_report_spm')
@login_required
def delete_report_spm(report_id):
    report = Report.query.get_or_404(report_id)
    if current_user.role != 'admin' and report.department_id not in [d.id for d in current_user.departments]:
        flash("You are not authorized to delete reports for this department.", "danger")
        return redirect(url_for('reports.summary'))
    db.session.delete(report)
    db.session.commit()
    flash(f"Report ID {report.id} has been deleted.", "success")
    return redirect(url_for('reports.summary'))

# --- Route to Download PDF for SPM Report ---
@spm_reports_bp.route('/spm/report/<int:report_id>/pdf', endpoint='pdf_report_spm')
@login_required
def pdf_report_spm(report_id):
    context = _get_report_context(report_id)
    pdf = generate_pdf_report("pages/spm_pdf.html", context)

    if not pdf:
        flash("Failed to generate PDF", "danger")
        return redirect(url_for('spm_reports.view_report_spm', report_id=report_id))

    filename = f"SPM_Report_{report_id}.pdf"
    return send_file(pdf, as_attachment=True, download_name=filename, mimetype='application/pdf')