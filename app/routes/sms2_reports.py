import json
import re
from flask import Blueprint, render_template, redirect, url_for, request, flash, send_file, current_app
from urllib.parse import unquote_plus
from collections import defaultdict
from datetime import datetime
from flask_login import login_required, current_user
from sqlalchemy.orm import joinedload, selectinload
from app.utils.email_notifications import send_report_notification
from app.utils.range_notifications import handle_range_alerts  # ✅ added

from ..models import db, Department, Equipment, Report, ReportSection, ReportParameter
from ..utils.pdf_export import generate_pdf_report

sms2_reports_bp = Blueprint('sms2_reports', __name__)


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
                # Use the raw name from the DB as the key to match templates
                all_params[param.name] = display_value

    return {"report": report, "params": all_params}


# --- Unified Helper function for all views (Web, PDF, Edit) ---
def _get_report_context(report_id):
    """Fetches a report and processes its parameters into a simple key-value dictionary."""
    report = Report.query.options(*_report_eager_options()).get_or_404(report_id)
    return _build_report_context(report)

# --- Route to Add a New Report ---
@sms2_reports_bp.route('/sms2/fill_report/<int:dept_id>/<int:equip_id>', methods=['GET', 'POST'])
@login_required
def fill_report_sms2(dept_id, equip_id):
    dept = Department.query.get_or_404(dept_id)
    equip = Equipment.query.filter_by(department_id=dept.id).first() if equip_id == 0 else Equipment.query.get_or_404(equip_id)
    datetime_now = datetime.now()
    sheets = { "ICW & DCW Raw Water": "icw_dcw.html", "CCM & EAF SW": "ccm_eaf.html", "Softwater Make-up": "softwater_makeup.html", "Spray O&G": "spray_og.html", "HRSCC Report": "hrscc_report.html" }

    if request.method == 'POST':
        report = Report(user_id=current_user.id, department_id=dept.id, equipment_id=equip.id if equip else None, sampling_time=datetime_now)
        db.session.add(report)
        db.session.flush()
        sheet_sections = {name: ReportSection(report_id=report.id, sheet_name=name) for name in sheets}
        for section in sheet_sections.values(): db.session.add(section)
        db.session.flush()
        sheet_name_map = { "icw_dcw": "ICW & DCW Raw Water", "ccm_eaf": "CCM & EAF SW", "softwater_makeup": "Softwater Make-up", "spray_og": "Spray O&G", "hrscc_report": "HRSCC Report" }
        for key, value in request.form.items():
            if not value or not value.strip() or key == 'csrf_token': continue
            sheet_key = next((prefix for prefix in sheet_name_map if key.startswith(prefix)), None)
            if not sheet_key: continue
            target_sheet_name = sheet_name_map[sheet_key]
            section_id = sheet_sections[target_sheet_name].id
            param_db_name = key.rsplit('_value', 1)[0]
            try: numeric_value, text_value = (float(value), None)
            except (ValueError, TypeError): numeric_value, text_value = (None, value)
            db.session.add(ReportParameter(section_id=section_id, name=param_db_name, value=numeric_value, range_value=text_value))
        db.session.commit()

        # ✅ Run range alerts only after the report is saved
        handle_range_alerts(report)  # emails only if any outliers

        # Existing submission notification
        # ✅ After committing the SMS-2 report
        from app.utils.email_notifications import send_report_notification
        from flask import current_app

        send_report_notification(report, current_app, db, action="submitted")
        flash("SMS-2 Report submitted successfully!", "success")
        return redirect(url_for('sms2_reports.summary_sms2'))

        
        flash("SMS-2 Report submitted successfully!", "success")
        return redirect(url_for('reports.summary'))
    return render_template('add_report_form.html', department=dept, equipment=equip, sampling_time=datetime_now, sheets=sheets, existing_data={})

# --- Route to View a Report (Corrected) ---
@sms2_reports_bp.route('/sms2/report/<int:report_id>', endpoint='view_report_sms2')
@login_required
def view_report_sms2(report_id):
    """Displays a single report using the unified context helper."""
    context = _get_report_context(report_id)
    return render_template('view_report.html', **context)

# --- Route to Download PDF ---
@sms2_reports_bp.route('/sms2/report/<int:report_id>/pdf', endpoint='download_pdf_sms2')
@login_required
def download_pdf_sms2(report_id):
    """Generates a PDF of the report."""
    context = _get_report_context(report_id)
    pdf = generate_pdf_report("report_pdf_template.html", context)
    if pdf:
        return send_file(pdf, as_attachment=True, download_name=f"Report_{context['report'].id}.pdf", mimetype='application/pdf')
    else:
        flash("PDF generation failed.", "danger")
        return redirect(url_for('sms2_reports.view_report_sms2', report_id=report_id))

# --- Route to Edit a Report ---
@sms2_reports_bp.route('/sms2/report/<int:report_id>/edit', methods=['GET', 'POST'], endpoint='edit_report_sms2')
@login_required
def edit_report_sms2(report_id):
    """Handles editing an existing SMS-2 report."""
    report = Report.query.options(*_report_eager_options()).get_or_404(report_id)
    if current_user.role != 'admin' and report.department_id not in [d.id for d in current_user.departments]:
        flash("You are not authorized to edit this report.", "danger")
        return redirect(url_for('reports.summary'))
    if request.method == 'POST':
        for section in report.sections:
            ReportParameter.query.filter_by(section_id=section.id).delete()
        sheet_sections = {s.sheet_name: s.id for s in report.sections}
        sheet_name_map = { "icw_dcw": "ICW & DCW Raw Water", "ccm_eaf": "CCM & EAF SW", "softwater_makeup": "Softwater Make-up", "spray_og": "Spray O&G", "hrscc_report": "HRSCC Report" }
        for key, value in request.form.items():
            if not value or not value.strip() or key == 'csrf_token': continue
            sheet_key = next((prefix for prefix in sheet_name_map if key.startswith(prefix)), None)
            if not sheet_key: continue
            target_sheet_name = sheet_name_map[sheet_key]
            section_id = sheet_sections[target_sheet_name]
            param_db_name = key.rsplit('_value', 1)[0]
            try: numeric_value, text_value = (float(value), None)
            except (ValueError, TypeError): numeric_value, text_value = (None, value)
            db.session.add(ReportParameter(section_id=section_id, name=param_db_name, value=numeric_value, range_value=text_value))
        db.session.commit()
        send_report_notification(report, current_app, db, action="edited")
        flash(f"Report ID {report.id} has been updated successfully!", "success")
        return redirect(url_for('reports.summary'))
    
    context = _build_report_context(report)
    context['sheets'] = { "ICW & DCW Raw Water": "icw_dcw.html", "CCM & EAF SW": "ccm_eaf.html", "Softwater Make-up": "softwater_makeup.html", "Spray O&G": "spray_og.html", "HRSCC Report": "hrscc_report.html" }
    context['existing_data'] = context.get('params', {})
    context['department'] = report.department
    context['equipment'] = report.equipment
    context['sampling_time'] = report.sampling_time
    return render_template('edit_report_form.html', **context)

# --- Route to Delete a Report ---
@sms2_reports_bp.route('/sms2/report/<int:report_id>/delete', methods=['POST'], endpoint='delete_report_sms2')
@login_required
def delete_report_sms2(report_id):
    """Deletes an SMS-2 report."""
    report = Report.query.get_or_404(report_id)
    if current_user.role != 'admin' and report.department_id not in [d.id for d in current_user.departments]:
        flash("You are not authorized to delete this report.", "danger")
        return redirect(url_for('reports.summary'))
    db.session.delete(report)
    db.session.commit()
    flash(f"Report ID {report.id} has been deleted.", "success")
    return redirect(url_for('reports.summary'))

# --- Route for SMS-2 Summary Page (Placeholder) ---
@sms2_reports_bp.route('/sms2/summary', endpoint='summary_sms2')
@login_required
def summary_sms2():
    """Redirects to the main summary page."""
    return redirect(url_for('reports.summary'))