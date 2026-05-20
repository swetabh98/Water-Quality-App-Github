# In app/routes/reports.py

import re
import json
from flask import Blueprint, render_template, redirect, url_for, request, flash, send_file
from flask_login import login_required, current_user
from datetime import datetime, timedelta
from collections import defaultdict
from urllib.parse import unquote_plus

from sqlalchemy.orm import joinedload, selectinload

from ..models import db, Department, Equipment, Report, ReportSection, ReportParameter
from ..forms import ReportInitForm
from ..utils.pdf_export import generate_pdf_report
from app.utils.email_notifications import send_report_notification
from app.routes.sms3_reports import sms3_reports_bp

from app.utils.range_notifications import handle_range_alerts

reports_bp = Blueprint('reports', __name__)

DEFAULT_DASHBOARD_DAYS = 30


def _report_eager_options():
    """Common eager-loading options for report pages that read sections/parameters."""
    return (
        joinedload(Report.department),
        joinedload(Report.user),
        joinedload(Report.equipment),
        selectinload(Report.sections).selectinload(ReportSection.parameters),
    )

# --- Add Report Initializer ---
@reports_bp.route('/add_report', methods=['GET', 'POST'])
@login_required
def add_report():
    form = ReportInitForm()

    if current_user.role == 'admin':
        departments = Department.query.all()
    else:
        # ✅ users see only their departments in the add-report form
        departments = current_user.departments

    form.department.choices = [(d.id, d.name) for d in departments]

    if form.validate_on_submit():
        dept = Department.query.get(form.department.data)

        if dept.name == "SMS-2":
            return redirect(url_for('sms2_reports.fill_report_sms2', dept_id=dept.id, equip_id=0))
        elif dept.name == "Rail Mill":
            return redirect(url_for('rail_mill_reports.fill_report_rail_mill', dept_id=dept.id, equip_id=0))
        elif dept.name == "SMS-3":
            return redirect(url_for('sms3_reports.fill_report_sms3', dept_id=dept.id, equip_id=0))
        elif dept.name == "Power Plant":
            return redirect(url_for("power_plant_reports.fill_report_power_plant", dept_id=dept.id, equip_id=0))
        else:
            return redirect(url_for('reports.fill_report', dept_id=dept.id, equip_id=0))

    return render_template('add_report_init.html', form=form)


# --- Dashboard helper functions ---
def _dashboard_norm_token(value):
    return re.sub(r'[^a-z0-9]+', '', str(value or '').strip().lower())


def _dashboard_param_display(name):
    raw = str(name or '').strip()
    if not raw:
        return 'Unknown'

    alias = {
        'ph': 'pH',
        'tds': 'TDS',
        'th': 'TH',
        'hard': 'Hardness',
        'turbidity': 'Turbidity',
        'conductivity': 'Conductivity',
        'iron': 'Iron',
        'coc': 'COC',
        'po4': 'PO4',
        'ophosphate': 'O-Phosphate',
        'phosphate': 'Phosphate',
        'po43': 'PO4-3',
        'chloride': 'Chloride',
        'cl': 'Cl-',
        'sio2': 'SiO2',
        'silica': 'Silica',
        'n2h4': 'N2H4',
        'tss': 'TSS',
        'cah': 'CaH',
        'mgh': 'MgH',
        'palk': 'P-Alkalinity',
        'malk': 'M-Alkalinity',
        'palkalinity': 'P-Alkalinity',
        'malkalinity': 'M-Alkalinity',
        'oilgrease': 'Oil/Grease',
        'oilandgrease': 'Oil/Grease',
        'zinc': 'Zinc',
        'nitrite': 'Nitrite',
        'tbc': 'TBC',
        'srb': 'SRB',
        'thard': 'T.- Hard',
        'talk': 'T.- Hard',
        'thardness': 'T.- Hard',
        'cahard': 'Ca- Hard',
        'mghard': 'Mg- Hard',
        'alk': 'Alk.',
        'app': 'Appearance',
    }
    norm = _dashboard_norm_token(raw)
    return alias.get(norm, raw.replace('_', ' ').replace('-', '-').strip().title())


def _dashboard_extract_param_from_name(name, primary_params):
    name_text = str(name or '').strip()
    if not name_text:
        return None

    normalized_name = _dashboard_norm_token(name_text)
    best_match = None
    best_len = 0
    for key in primary_params:
        key_norm = _dashboard_norm_token(key)
        if not key_norm:
            continue
        if normalized_name.endswith(key_norm) or key_norm in normalized_name:
            if len(key_norm) > best_len:
                best_match = key
                best_len = len(key_norm)
    return best_match


def _dashboard_float(value):
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    try:
        text = str(value).strip()
        if not text:
            return None
        return float(text)
    except (TypeError, ValueError):
        return None


def _dashboard_rule_to_text(rule):
    if rule is None:
        return '-'
    if isinstance(rule, dict):
        pieces = []
        order = [('min', '>='), ('gte', '>='), ('gt', '>'), ('max', '<='), ('lte', '<='), ('lt', '<'), ('eq', '=')]
        for key, symbol in order:
            if key in rule and rule[key] not in (None, ''):
                pieces.append(f"{symbol} {rule[key]}")
        return ' and '.join(pieces) if pieces else str(rule)
    return str(rule)


def _dashboard_risk_level(compliance):
    if compliance >= 95:
        return 'Low'
    if compliance >= 90:
        return 'Medium'
    return 'High'


def _dashboard_risk_class(compliance):
    if compliance >= 95:
        return 'risk-low'
    if compliance >= 90:
        return 'risk-medium'
    return 'risk-high'


# --- Dashboard (ALL users see ALL departments) ---
@reports_bp.route('/dashboard')
@login_required
def dashboard():
    # Everyone sees all departments
    departments = Department.query.order_by(Department.name.asc()).all()
    dept_names = [d.name for d in departments]

    primary_params = [
        'pH', 'TH', 'CaH', 'MgH', 'TDS', 'Conductivity', 'Turbidity', 'TSS',
        'Iron', 'COC', 'PO4', 'O-Phosphate', 'Phosphate', 'Chloride', 'Nitrite',
        'P-Alk', 'M-Alk', 'P-Alkalinity', 'M-Alkalinity', 'Hard', 'Silica', 'SiO2', 'N2H4',
        'T.- Hard', 'Ca- Hard', 'Mg- Hard', 'Ca-H', 'Mg-H', 'Alk.', 'Cl-', 'PO4-3',
        'Oil/Grease', 'Zinc', 'TBC', 'SRB'
    ]

    start_date = request.args.get('start_date', '').strip()
    end_date = request.args.get('end_date', '').strip()
    using_default_date_range = not start_date and not end_date

    query = Report.query
    parsed_start = None
    parsed_end = None

    if using_default_date_range:
        parsed_end = datetime.now()
        parsed_start = parsed_end - timedelta(days=DEFAULT_DASHBOARD_DAYS)
        query = query.filter(Report.sampling_time >= parsed_start)
        start_date = parsed_start.strftime('%Y-%m-%d')
        end_date = parsed_end.strftime('%Y-%m-%d')
    else:
        if start_date:
            try:
                parsed_start = datetime.strptime(start_date, '%Y-%m-%d')
                query = query.filter(Report.sampling_time >= parsed_start)
            except Exception:
                flash('Invalid start date format. Please use YYYY-MM-DD.', 'warning')
                start_date = ''

        if end_date:
            try:
                parsed_end = datetime.strptime(end_date, '%Y-%m-%d')
                query = query.filter(Report.sampling_time <= parsed_end.replace(hour=23, minute=59, second=59))
            except Exception:
                flash('Invalid end date format. Please use YYYY-MM-DD.', 'warning')
                end_date = ''

    all_reports = (
        query.options(*_report_eager_options())
        .order_by(Report.sampling_time.asc())
        .all()
    )

    # Existing department average chart structure retained.
    grouped_data = defaultdict(lambda: defaultdict(list))

    dept_stats = {
        dn: {
            'department': dn,
            'reports': 0,
            'readings': 0,
            'checked': 0,
            'in_range': 0,
            'outliers': 0,
            'compliance': 0,
            'risk_level': 'No Data',
            'risk_class': 'risk-none',
        }
        for dn in dept_names
    }

    param_stats = defaultdict(lambda: {
        'parameter': '',
        'values': [],
        'outliers': 0,
        'checked': 0,
        'spikes': 0,
    })
    param_failure_by_dept = defaultdict(lambda: defaultdict(int))
    system_failure_counter = defaultdict(lambda: {'department': '', 'system': '', 'outliers': 0, 'param_counts': defaultdict(int)})
    outlier_by_dept = defaultdict(int)
    trend_bucket = defaultdict(lambda: defaultdict(lambda: defaultdict(list)))
    submission_dates = defaultdict(set)
    latest_alerts = []
    latest_report_time = None
    active_departments = set()

    try:
        from app.utils.range_notifications import check_only
    except Exception:
        check_only = None

    for report in all_reports:
        dept_name = report.department.name if report.department else 'Unknown'
        if dept_name not in dept_stats:
            dept_stats[dept_name] = {
                'department': dept_name,
                'reports': 0,
                'readings': 0,
                'checked': 0,
                'in_range': 0,
                'outliers': 0,
                'compliance': 0,
                'risk_level': 'No Data',
                'risk_class': 'risk-none',
            }
            dept_names.append(dept_name)

        dept_stats[dept_name]['reports'] += 1
        active_departments.add(dept_name)
        if report.sampling_time:
            latest_report_time = max(latest_report_time, report.sampling_time) if latest_report_time else report.sampling_time
            submission_dates[dept_name].add(report.sampling_time.date())

        per_report = defaultdict(list)
        report_numeric_entries = 0

        for section in report.sections:
            for p in section.parameters:
                val = _dashboard_float(p.value)
                if val is None:
                    continue

                report_numeric_entries += 1
                param_key = _dashboard_extract_param_from_name(p.name, primary_params)
                if param_key:
                    per_report[param_key].append(val)

        dept_stats[dept_name]['readings'] += report_numeric_entries

        # Average per report, then add to department bucket. This keeps the old dashboard logic's intent.
        for k, vals in per_report.items():
            if vals:
                grouped_data[k][dept_name].append(round(sum(vals) / len(vals), 2))

        # Use the same range checker/extractors used by alert emails so dashboard outliers match alerts.
        if check_only:
            try:
                range_result = check_only(report, dept_hint=dept_name)
            except Exception:
                range_result = {'outliers': [], 'not_found': [], 'count': 0}
        else:
            range_result = {'outliers': [], 'not_found': [], 'count': 0}

        checked_count = max(0, int(range_result.get('count', 0) or 0) - len(range_result.get('not_found', []) or []))
        outliers = range_result.get('outliers', []) or []
        outlier_count = len(outliers)
        in_range_count = max(0, checked_count - outlier_count)

        dept_stats[dept_name]['checked'] += checked_count
        dept_stats[dept_name]['in_range'] += in_range_count
        dept_stats[dept_name]['outliers'] += outlier_count
        outlier_by_dept[dept_name] += outlier_count

        outlier_keys = set()
        for item in outliers:
            system_name = str(item.get('system') or 'Unknown').strip() or 'Unknown'
            param_name = _dashboard_param_display(item.get('parameter') or 'Unknown')
            value = _dashboard_float(item.get('value'))
            rule_text = _dashboard_rule_to_text(item.get('rule'))
            outlier_keys.add((str(item.get('page') or ''), system_name, param_name, value))

            param_stats[param_name]['parameter'] = param_name
            param_stats[param_name]['outliers'] += 1
            param_failure_by_dept[dept_name][param_name] += 1

            system_key = (dept_name, system_name)
            system_failure_counter[system_key]['department'] = dept_name
            system_failure_counter[system_key]['system'] = system_name
            system_failure_counter[system_key]['outliers'] += 1
            system_failure_counter[system_key]['param_counts'][param_name] += 1

            latest_alerts.append({
                'time': report.sampling_time.strftime('%Y-%m-%d %H:%M') if report.sampling_time else '-',
                'department': dept_name,
                'system': system_name,
                'parameter': param_name,
                'value': round(value, 3) if value is not None else item.get('value'),
                'range': rule_text,
            })

        # Parameter trends and stability from extracted range-check rows.
        if check_only:
            try:
                from app.utils.ranges import get_extractor
                extractor = get_extractor(dept_name)
                extracted_rows = extractor(report) if extractor else []
            except Exception:
                extracted_rows = []
        else:
            extracted_rows = []

        for row in extracted_rows:
            value = _dashboard_float(row.get('value'))
            if value is None:
                continue
            param_name = _dashboard_param_display(row.get('parameter'))
            param_stats[param_name]['parameter'] = param_name
            param_stats[param_name]['values'].append(value)
            param_stats[param_name]['checked'] += 1
            if report.sampling_time:
                day_key = report.sampling_time.strftime('%Y-%m-%d')
                trend_bucket[param_name][dept_name][day_key].append(value)

    # Final averaging per department to build chart_data. Existing variable kept for compatibility.
    chart_data = {}
    for param_key, dept_values in grouped_data.items():
        labels = []
        values = []
        for dn in dept_names:
            labels.append(dn)
            raw_vals = dept_values.get(dn, [])
            avg = round(sum(raw_vals) / len(raw_vals), 2) if raw_vals else 0
            values.append(avg)
        if any(v > 0 for v in values):
            chart_data[param_key] = {'labels': labels, 'values': values}

    scorecard = []
    for dn in dept_names:
        stats = dept_stats.get(dn)
        if not stats:
            continue
        checked = stats['checked']
        compliance = round((stats['in_range'] / checked) * 100, 1) if checked else 0
        stats['compliance'] = compliance
        stats['risk_level'] = _dashboard_risk_level(compliance) if checked else 'No Data'
        stats['risk_class'] = _dashboard_risk_class(compliance) if checked else 'risk-none'
        scorecard.append(stats)

    scorecard_sorted = sorted(
        scorecard,
        key=lambda x: (
            0 if x['checked'] > 0 else 1,
            x['compliance'] if x['checked'] > 0 else 101,
            x['department']
        )
    )
    compliance_sorted = sorted([x for x in scorecard if x['checked'] > 0], key=lambda x: x['compliance'], reverse=True)
    attention_sorted = sorted([x for x in scorecard if x['checked'] > 0], key=lambda x: x['compliance'])

    total_reports = len(all_reports)
    total_readings = sum(x['readings'] for x in scorecard)
    total_checked = sum(x['checked'] for x in scorecard)
    total_outliers = sum(x['outliers'] for x in scorecard)
    total_in_range = sum(x['in_range'] for x in scorecard)
    compliance_percent = round((total_in_range / total_checked) * 100, 1) if total_checked else 0

    worst_department = attention_sorted[0]['department'] if attention_sorted else '-'
    failing_params_sorted = sorted(param_stats.values(), key=lambda x: x['outliers'], reverse=True)
    most_failing_parameter = failing_params_sorted[0]['parameter'] if failing_params_sorted and failing_params_sorted[0]['outliers'] else '-'

    kpi_cards = [
        {'label': 'Total Reports', 'value': total_reports, 'hint': 'Submitted reports in selected period'},
        {'label': 'Active Departments', 'value': len(active_departments), 'hint': 'Departments with at least one report'},
        {'label': 'Total Readings', 'value': total_readings, 'hint': 'Numeric parameter entries'},
        {'label': 'Out-of-Range Count', 'value': total_outliers, 'hint': 'Failed range checks'},
        {'label': 'Compliance %', 'value': f'{compliance_percent}%', 'hint': 'In-range / checked readings'},
        {'label': 'Worst Department', 'value': worst_department, 'hint': 'Lowest compliance'},
        {'label': 'Most Failing Parameter', 'value': most_failing_parameter, 'hint': 'Highest outlier count'},
        {'label': 'Latest Report Time', 'value': latest_report_time.strftime('%Y-%m-%d %H:%M') if latest_report_time else '-', 'hint': 'Dashboard freshness'},
    ]

    outlier_rows = sorted(scorecard, key=lambda row: row['outliers'], reverse=True)
    outlier_chart = {
        'labels': [x['department'] for x in outlier_rows],
        'values': [x['outliers'] for x in outlier_rows],
    }
    compliance_chart_rows = sorted([x for x in scorecard if x['checked'] > 0], key=lambda row: row['compliance'])
    compliance_chart = {
        'labels': [x['department'] for x in compliance_chart_rows],
        'values': [x['compliance'] for x in compliance_chart_rows],
    }

    heatmap_params = [p['parameter'] for p in failing_params_sorted if p['outliers'] > 0][:12]
    if not heatmap_params:
        heatmap_params = [p for p in primary_params[:8]]
    heatmap_data = []
    for dn in dept_names:
        row = {'department': dn, 'values': []}
        for pn in heatmap_params:
            row['values'].append(param_failure_by_dept[dn].get(pn, 0))
        heatmap_data.append(row)

    trend_charts = {}
    preferred_trends = ['pH', 'Conductivity', 'TDS', 'TH', 'Turbidity', 'Iron', 'COC']
    for param_name in preferred_trends:
        matching_key = None
        for existing in trend_bucket.keys():
            if _dashboard_norm_token(existing) == _dashboard_norm_token(param_name):
                matching_key = existing
                break
        if not matching_key:
            continue
        labels = sorted({day for dept_map in trend_bucket[matching_key].values() for day in dept_map.keys()})
        datasets = []
        for dn in dept_names:
            values = []
            for day in labels:
                vals = trend_bucket[matching_key][dn].get(day, [])
                values.append(round(sum(vals) / len(vals), 2) if vals else None)
            if any(v is not None for v in values):
                datasets.append({'label': dn, 'data': values})
        if labels and datasets:
            trend_charts[param_name] = {'labels': labels, 'datasets': datasets}

    ranking_cards = {
        'best': [
            {'department': x['department'], 'compliance': x['compliance']}
            for x in compliance_sorted[:3]
        ],
        'attention': [
            {'department': x['department'], 'compliance': x['compliance']}
            for x in attention_sorted[:3]
        ],
    }

    worst_systems = []
    for item in system_failure_counter.values():
        param_counts = item['param_counts']
        worst_param = max(param_counts.items(), key=lambda kv: kv[1])[0] if param_counts else '-'
        worst_systems.append({
            'department': item['department'],
            'system': item['system'],
            'outliers': item['outliers'],
            'worst_parameter': worst_param,
        })
    worst_systems = sorted(worst_systems, key=lambda x: x['outliers'], reverse=True)[:10]
    worst_system_chart = {
        'labels': [f"{x['department']} - {x['system']}" for x in worst_systems],
        'values': [x['outliers'] for x in worst_systems],
    }

    latest_alerts = sorted(latest_alerts, key=lambda x: x['time'], reverse=True)[:15]

    stability_rows = []
    for item in param_stats.values():
        vals = item['values']
        if not vals:
            continue
        avg_val = sum(vals) / len(vals)
        variance = sum((v - avg_val) ** 2 for v in vals) / len(vals) if len(vals) > 1 else 0
        std_dev = variance ** 0.5
        spike_count = sum(1 for v in vals if abs(v - avg_val) > (2 * std_dev)) if std_dev > 0 else 0
        stability_rows.append({
            'parameter': item['parameter'],
            'avg': round(avg_val, 2),
            'min': round(min(vals), 2),
            'max': round(max(vals), 2),
            'std_dev': round(std_dev, 2),
            'spikes': spike_count,
            'outliers': item['outliers'],
        })
    stability_rows = sorted(stability_rows, key=lambda x: (x['outliers'], x['std_dev']), reverse=True)[:15]

    # Daily report submission compliance assumes one expected submission per department per calendar day.
    if parsed_start and parsed_end:
        span_start = parsed_start.date()
        span_end = parsed_end.date()
    elif all_reports:
        report_dates = [r.sampling_time.date() for r in all_reports if r.sampling_time]
        span_start = min(report_dates) if report_dates else datetime.now().date()
        span_end = max(report_dates) if report_dates else datetime.now().date()
    else:
        span_start = datetime.now().date()
        span_end = datetime.now().date()

    expected_days = max(1, (span_end - span_start).days + 1)
    submission_compliance = []
    for dn in dept_names:
        submitted = len(submission_dates.get(dn, set()))
        expected = expected_days
        missing = max(0, expected - submitted)
        pct = round((submitted / expected) * 100, 1) if expected else 0
        submission_compliance.append({
            'department': dn,
            'expected': expected,
            'submitted': submitted,
            'missing': missing,
            'submission_pct': pct,
        })

    daily_counts_map = defaultdict(lambda: defaultdict(int))
    all_days = set()
    for report in all_reports:
        if report.sampling_time:
            day = report.sampling_time.strftime('%Y-%m-%d')
            dept_name = report.department.name if report.department else 'Unknown'
            all_days.add(day)
            daily_counts_map[day][dept_name] += 1
    daily_labels = sorted(all_days)
    daily_report_chart = {
        'labels': daily_labels,
        'datasets': [
            {'label': dn, 'data': [daily_counts_map[day].get(dn, 0) for day in daily_labels]}
            for dn in dept_names
            if any(daily_counts_map[day].get(dn, 0) for day in daily_labels)
        ]
    }
    submission_chart = {
        'labels': [x['department'] for x in submission_compliance],
        'values': [x['submission_pct'] for x in submission_compliance],
    }

    return render_template(
        'dashboard.html',
        chart_data=chart_data,
        kpi_cards=kpi_cards,
        scorecard=scorecard_sorted,
        outlier_chart=outlier_chart,
        compliance_chart=compliance_chart,
        heatmap_params=heatmap_params,
        heatmap_data=heatmap_data,
        trend_charts=trend_charts,
        ranking_cards=ranking_cards,
        worst_systems=worst_systems,
        worst_system_chart=worst_system_chart,
        latest_alerts=latest_alerts,
        stability_rows=stability_rows,
        submission_compliance=submission_compliance,
        daily_report_chart=daily_report_chart,
        submission_chart=submission_chart,
        start_date=start_date,
        end_date=end_date,
    )

# --- Fill Report for Plate Mill and SPM ---
@reports_bp.route('/fill_report/<int:dept_id>/<int:equip_id>', methods=['GET', 'POST'])
@login_required
def fill_report(dept_id, equip_id):
    dept = Department.query.get_or_404(dept_id)
    equip = (
        Equipment.query.filter_by(department_id=dept.id).first()
        if equip_id == 0 else Equipment.query.get_or_404(equip_id)
    )
    datetime_now = datetime.now()

    if dept.name == "Plate Mill":
        if request.method == 'POST':
            report = Report(
                user_id=current_user.id,
                department_id=dept.id,
                equipment_id=equip.id if equip else None,
                sampling_time=datetime_now
            )
            db.session.add(report)
            db.session.flush()

            section = ReportSection(report_id=report.id, sheet_name="Plate Mill Report")
            db.session.add(section)
            db.session.flush()

            params_to_save = defaultdict(lambda: defaultdict(str))

            for key, value in request.form.items():
                if not (key.endswith("_value") or key.endswith("_range")):
                    continue
                param_name = "_".join(key.split('_')[:-1])
                if key.endswith('_value'):
                    params_to_save[param_name]['value'] = value
                elif key.endswith('_range'):
                    params_to_save[param_name]['range'] = value

            for name, data in params_to_save.items():
                try:
                    val = float(data.get('value')) if data.get('value') and data.get('value').strip() else None
                except (ValueError, TypeError):
                    val = None
                param = ReportParameter(
                    section_id=section.id,
                    name=name,
                    value=val,
                    range_value=data.get('range')
                )
                db.session.add(param)

            db.session.commit()

            # Run range alerts only after the report is saved
            handle_range_alerts(report)  # runs only after save; emails only if any outliers

            from flask import current_app
            send_report_notification(report, current_app, db, action="submitted")

            flash("Plate Mill Report submitted successfully!", "success")
            return redirect(url_for('reports.dashboard'))

        return render_template("pages/plate_mill.html", department=dept, equipment=equip, sampling_time=datetime_now)

    elif dept.name == "SPM":
        return redirect(url_for("spm_reports.fill_report_spm", dept_id=dept.id, equip_id=equip.id if equip else 0))

    else:
        flash(f"Reporting templates for {dept.name} are not available in this section.", "warning")
        return redirect(url_for('reports.dashboard'))


# --- View Report ---
@reports_bp.route('/report/<int:report_id>')
@login_required
def view_report(report_id):
    report = Report.query.options(*_report_eager_options()).get_or_404(report_id)

    if report.department.name == "SMS-2":
        return redirect(url_for('sms2_reports.view_report_sms2', report_id=report.id))

    if current_user.role != 'admin' and report.department_id not in [d.id for d in current_user.departments]:
        flash("Unauthorized access", "danger")
        return redirect(url_for('reports.dashboard'))

    processed_data = defaultdict(lambda: defaultdict(dict))
    alias_map = {
        "M-Alk": "M-Alkalinity"
    }

    if report.department.name == "Plate Mill" and report.sections:
        for param in report.sections[0].parameters:
            parts = param.name.split('_')
            if len(parts) >= 2:
                system_key = f"{parts[0]}_{parts[1]}"
                param_key = "_".join(parts[2:])
                # Fix M-Alk → M-Alkalinity
                param_key = alias_map.get(param_key, param_key)

                if "LIMIT" in system_key:
                    processed_data[param_key][system_key] = {'range': param.range_value}
                else:
                    processed_data[param_key][system_key] = {'value': param.value}

    return render_template('view_report.html', report=report, processed_data=processed_data)


# --- Edit Report ---
@reports_bp.route('/report/<int:report_id>/edit', methods=['GET', 'POST'])
@login_required
def edit_report(report_id):
    report = Report.query.options(*_report_eager_options()).get_or_404(report_id)

    # Authorization
    if current_user.role != 'admin' and report.department_id not in [d.id for d in current_user.departments]:
        flash("You are not authorized to edit this report.", "danger")
        return redirect(url_for('reports.summary'))

    # Redirect SMS-2 to its own handler (optional)
    if report.department.name == "SMS-2":
        flash("Editing for SMS-2 reports is handled in its own section.", "info")
        return redirect(url_for('sms2_reports.view_report_sms2', report_id=report.id))

    # Plate Mill edit
    if report.department.name == "Plate Mill":
        if request.method == 'POST':
            # Clear existing parameters
            for section in report.sections:
                ReportParameter.query.filter_by(section_id=section.id).delete()

            section = report.sections[0]  # Plate Mill has only one section
            params_to_save = defaultdict(lambda: defaultdict(str))

            for key, value in request.form.items():
                if not (key.endswith("_value") or key.endswith("_range")):
                    continue
                param_name = key.rsplit('_', 1)[0]
                if key.endswith('_value'):
                    params_to_save[param_name]['value'] = value
                elif key.endswith('_range'):
                    params_to_save[param_name]['range'] = value

            for name, data in params_to_save.items():
                try:
                    val = float(data.get('value')) if data.get('value') and data.get('value').strip() else None
                except (ValueError, TypeError):
                    val = None
                param = ReportParameter(
                    section_id=section.id,
                    name=name,
                    value=val,
                    range_value=data.get('range')
                )
                db.session.add(param)

            db.session.commit()

            from flask import current_app
            send_report_notification(report, current_app, db, action="edited")

            flash('Report has been updated successfully!', "success")
            return redirect(url_for('reports.summary'))

        # GET: prefilled form
        existing_data = {param.name: param for param in report.sections[0].parameters}
        return render_template("pages/plate_mill_edit.html",
                               report=report,
                               existing_data=existing_data)

    flash("Unknown department. Cannot edit.", "danger")
    return redirect(url_for('reports.summary'))


# --- Delete Report ---
@reports_bp.route('/report/<int:report_id>/delete', methods=['POST'])
@login_required
def delete_report(report_id):
    report = Report.query.get_or_404(report_id)

    if current_user.role != 'admin' and report.department_id not in [d.id for d in current_user.departments]:
        flash("You are not authorized to delete this report.", "danger")
        return redirect(url_for('reports.summary'))

    db.session.delete(report)
    db.session.commit()

    flash(f"Report ID {report.id} has been deleted.", "success")
    return redirect(url_for('reports.summary'))


# --- Download PDF (Plate Mill)
@reports_bp.route('/report/<int:report_id>/pdf')
@login_required
def download_pdf(report_id):
    report = Report.query.options(*_report_eager_options()).get_or_404(report_id)

    if report.department.name == "SMS-2":
        return redirect(url_for('sms2_reports.download_pdf_sms2', report_id=report.id))

    if current_user.role != 'admin' and report.department_id not in [d.id for d in current_user.departments]:
        flash("Unauthorized access", "danger")
        return redirect(url_for('reports.view_report', report_id=report.id))

    processed_data = defaultdict(lambda: defaultdict(dict))
    context = {"report": report}

    if report.department.name == "Plate Mill" and report.sections:
        for param in report.sections[0].parameters:
            parts = param.name.split('_')
            if len(parts) >= 2:
                system_key = f"{parts[0]}_{parts[1]}"
                param_key = "_".join(parts[2:])
                if 'range' not in processed_data[param_key][system_key]:
                    processed_data[param_key][system_key] = {'value': None, 'range': None}
                if "LIMIT" in system_key:
                    processed_data[param_key][system_key]['range'] = param.range_value
                else:
                    processed_data[param_key][system_key]['value'] = param.value

    context["processed_data"] = processed_data

    pdf = generate_pdf_report("pdf/plate_mill_pdf.html", context)
    if pdf:
        return send_file(pdf, as_attachment=True, download_name=f"Report_{report.id}.pdf", mimetype='application/pdf')
    else:
        flash("PDF generation failed.", "danger")
        return redirect(url_for('reports.view_report', report_id=report.id))


# --- Summary ---
@reports_bp.route('/summary')
@login_required
def summary():
    base_query = Report.query.options(*_report_eager_options())

    if current_user.role == 'admin':
        reports = base_query.order_by(Report.sampling_time.desc()).limit(50).all()
    else:
        dept_ids = [d.id for d in current_user.departments]
        reports = (
            base_query.filter(Report.department_id.in_(dept_ids))
            .order_by(Report.sampling_time.desc())
            .limit(50)
            .all()
        )

    plate_mill_data, sms2_data, sms3_data, rail_mill_data, spm_data, power_plant_data = [], [], [], [], [], []

    # Define the columns for each report type
    all_pm_params = set()
    sms2_params = ['pH', 'TH', 'CaH', 'MgH', 'TDS', 'Conductivity', 'Turbidity', 'TSS', 'Iron', 'COC', 'PO4']
    sms3_params = ['pH', 'TH', 'Conductivity', 'TDS', 'Iron', 'COC']
    rail_mill_params = ['pH', 'TH', 'Conductivity', 'TDS', 'Iron', 'COC']
    spm_params = ['pH', 'TH', 'Conductivity', 'TDS', 'Iron', 'COC']
    power_plant_params = ['pH', 'Hard', 'Conductivity', 'SiO2', 'N2H4', 'T.- Hard', 'Ca- Hard', 'Mg- Hard', 'Alk.', 'TDS', 'Cl-', 'Turbidity', 'PO4-3', 'COC']

    for r in reports:
        base = {
            "ID": r.id,
            "Department": r.department.name,
            "User": r.user.email,
            "Date": r.sampling_time.strftime('%Y-%m-%d')
        }

        dept_name = r.department.name.strip()

        if dept_name == "Plate Mill":
            pm_row = base.copy()
            if r.sections:
                for p in r.sections[0].parameters:
                    all_pm_params.add(p.name.strip())
                    pm_row[p.name.strip()] = p.value
            plate_mill_data.append(pm_row)

        elif dept_name == "SMS-2":
            sms_row = base.copy()
            for p_key in sms2_params:
                sms_row[p_key] = None
            for sec in r.sections:
                for p in sec.parameters:
                    for key in sms2_params:
                        if key.lower() in p.name.lower():
                            sms_row[key] = p.value
                            break
            sms2_data.append(sms_row)

        elif dept_name == "SMS-3":
            sms3_row = base.copy()
            for p_key in sms3_params:
                sms3_row[p_key] = None
            if r.sections:
                for p in r.sections[0].parameters:
                    for key in sms3_params:
                        if p.name.lower().endswith(key.lower()):
                            sms3_row[key] = p.value if p.value is not None else p.range_value
                            break
            sms3_data.append(sms3_row)

        elif dept_name == "Rail Mill":
            rail_row = base.copy()
            for p_key in rail_mill_params:
                rail_row[p_key] = None
            if r.sections:
                for p in r.sections[0].parameters:
                    for key in rail_mill_params:
                        if p.name.lower().endswith(key.lower()):
                            rail_row[key] = p.value if p.value is not None else p.range_value
                            break
            rail_mill_data.append(rail_row)

        elif dept_name == "SPM":
            spm_row = base.copy()
            for p_key in spm_params:
                spm_row[p_key] = None
            if r.sections:
                for p in r.sections[0].parameters:
                    for key in spm_params:
                        if p.name.lower().endswith(key.lower()):
                            spm_row[key] = p.value if p.value is not None else p.range_value
                            break
            spm_data.append(spm_row)

        elif dept_name == "Power Plant":
            pp_row = base.copy()
            for p_key in power_plant_params:
                pp_row[p_key] = None
            if r.sections:
                for p in r.sections[0].parameters:
                    for key in power_plant_params:
                        clean_key = key.lower().replace("-", "").replace(" ", "")
                        param_name = p.name.lower().replace("_", "").replace("-", "").replace(" ", "")
                        if clean_key in param_name:
                            pp_row[key] = p.value if p.value is not None else p.range_value
                            break
            power_plant_data.append(pp_row)

    return render_template(
        "summary.html",
        plate_mill=plate_mill_data,
        sms2_reports=sms2_data,
        sms3_reports=sms3_data,
        rail_mill_reports=rail_mill_data,
        spm_reports=spm_data,
        power_plant_reports=power_plant_data,
        parameters=sorted(list(all_pm_params)),
        sms2_params=sms2_params,
        sms3_params=sms3_params,
        rail_mill_params=rail_mill_params,
        spm_params=spm_params,
        power_plant_params=power_plant_params
    )