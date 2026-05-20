from flask import Blueprint, render_template, redirect, url_for, request, flash, send_file, current_app
from flask_login import login_required, current_user
from sqlalchemy.orm import joinedload, selectinload
from collections import defaultdict
from datetime import datetime
from ..models import db, Department, Equipment, Report, ReportSection, ReportParameter
from ..utils.pdf_export import generate_pdf_report
from app.utils.email_notifications import send_report_notification
from app.utils.range_notifications import handle_range_alerts  # ✅ Range alerts import

power_plant_reports_bp = Blueprint("power_plant_reports", __name__)


def _report_eager_options():
    """Common eager-loading options for report pages that read sections/parameters."""
    return (
        joinedload(Report.department),
        joinedload(Report.equipment),
        selectinload(Report.sections).selectinload(ReportSection.parameters),
    )

# --- Helper function ---
def _build_context(report):
    params = {}
    for section in report.sections:
        for p in section.parameters:
            if p.name:
                display_value = p.range_value if p.range_value else p.value
                params[p.name] = display_value
    return {
        "report": report,
        "department": report.department,
        "equipment": report.equipment,
        "sampling_time": report.sampling_time,
        "params": params
    }


def _get_context(report_id):
    report = Report.query.options(*_report_eager_options()).get_or_404(report_id)
    return _build_context(report)

# --- Add Report ---
@power_plant_reports_bp.route('/power_plant/fill_report/<int:dept_id>/<int:equip_id>', methods=['GET', 'POST'])
@login_required
def fill_report_power_plant(dept_id, equip_id):
    dept = Department.query.get_or_404(dept_id)
    equip = Equipment.query.get(equip_id) if equip_id != 0 else None
    now = datetime.now()

    if request.method == 'POST':
        report = Report(user_id=current_user.id, department_id=dept.id,
                        equipment_id=equip.id if equip else None, sampling_time=now)
        db.session.add(report)
        db.session.flush()

        section = ReportSection(report_id=report.id, sheet_name="Power Plant Report")
        db.session.add(section)
        db.session.flush()

        for key, value in request.form.items():
            if not value or key == "csrf_token":
                continue
            param_name = key.replace("_value", "")
            try:
                numeric_val = float(value)
                db.session.add(ReportParameter(section_id=section.id, name=param_name, value=numeric_val))
            except ValueError:
                db.session.add(ReportParameter(section_id=section.id, name=param_name, range_value=value))

        db.session.commit()

        # ✅ Run range alerts only after the report is saved
        handle_range_alerts(report)  # emails only if any outliers

        try:
            send_report_notification(report, current_app._get_current_object(), db, action="submitted")
        except Exception as e:
            print(f"❌ Email send failed: {e}")

        flash("Power Plant Report submitted successfully!", "success")
        return redirect(url_for('reports.summary'))

    return render_template("pages/power_plant_report.html", department=dept,
                           equipment=equip, sampling_time=now, existing_data={})

# --- View Report ---
@power_plant_reports_bp.route('/power_plant/report/<int:report_id>')
@login_required
def view_report_power_plant(report_id):
    context = _get_context(report_id)
    return render_template("pages/power_plant_view.html", **context)

# --- Edit Report ---
@power_plant_reports_bp.route('/power_plant/report/<int:report_id>/edit', methods=['GET', 'POST'])
@login_required
def edit_report_power_plant(report_id):
    report = Report.query.options(*_report_eager_options()).get_or_404(report_id)
    if current_user.role != 'admin' and report.department_id not in [d.id for d in current_user.departments]:
        flash("Unauthorized access", "danger")
        return redirect(url_for('reports.summary'))

    if request.method == 'POST':
        section_ids = [s.id for s in report.sections]
        if section_ids:
            ReportParameter.query.filter(ReportParameter.section_id.in_(section_ids)).delete(synchronize_session=False)
        section = report.sections[0]
        for key, value in request.form.items():
            if not value or key == "csrf_token":
                continue
            param_name = key.replace("_value", "")
            try:
                numeric_val = float(value)
                db.session.add(ReportParameter(section_id=section.id, name=param_name, value=numeric_val))
            except ValueError:
                db.session.add(ReportParameter(section_id=section.id, name=param_name, range_value=value))
        db.session.commit()

        try:
            send_report_notification(report, current_app._get_current_object(), db, action="updated")
        except Exception as e:
            print(f"❌ Email send failed: {e}")

        flash("Report updated successfully.", "success")
        return redirect(url_for('reports.summary'))

    # ✅ Extract existing data
    existing_data = {}
    for section in report.sections:
        for p in section.parameters:
            existing_data[p.name] = p.value if p.value is not None else p.range_value

    context = _build_context(report)
    context["existing_data"] = existing_data  # ✅ Add to template context

    return render_template("pages/power_plant_edit.html", **context)

# --- Delete Report ---
@power_plant_reports_bp.route('/power_plant/report/<int:report_id>/delete', methods=["POST"])
@login_required
def delete_report_power_plant(report_id):
    report = Report.query.get_or_404(report_id)
    if current_user.role != 'admin' and report.department_id not in [d.id for d in current_user.departments]:
        flash("Unauthorized", "danger")
        return redirect(url_for('reports.summary'))
    db.session.delete(report)
    db.session.commit()
    flash("Report deleted successfully.", "success")
    return redirect(url_for('reports.summary'))

# --- Export PDF ---
@power_plant_reports_bp.route('/power_plant/report/<int:report_id>/pdf')
@login_required
def download_pdf_power_plant(report_id):  # ✅ Renamed this function
    context = _get_context(report_id)
    pdf = generate_pdf_report("pages/power_plant_pdf.html", context)
    if pdf:
        return send_file(pdf, as_attachment=True, download_name=f"PowerPlant_Report_{report_id}.pdf", mimetype='application/pdf')
    else:
        flash("PDF generation failed", "danger")
        return redirect(url_for('power_plant_reports.view_report_power_plant', report_id=report_id))