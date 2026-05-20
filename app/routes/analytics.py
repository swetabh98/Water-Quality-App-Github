import re
from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_required, current_user
from collections import defaultdict
from datetime import datetime, timedelta
from sqlalchemy.orm import joinedload, selectinload
from urllib.parse import quote_plus, unquote_plus
from ..models import db, Department, Report, ReportSection

analytics_bp = Blueprint("analytics", __name__)

DEFAULT_ANALYTICS_DAYS = 30


from flask import current_app, jsonify
from app.utils.range import get_bulk_ranges
from ..models import Department

@analytics_bp.route("/analytics/api/ranges", methods=["POST"])
@login_required
def api_get_ranges():
    payload = request.get_json(silent=True) or {}
    dept_id   = payload.get("department_id")
    dept_name = payload.get("department_name")
    page      = payload.get("page") or payload.get("sheet")   # allow either key
    system    = payload.get("system") or payload.get("display_system")
    params    = payload.get("params") or []

    if not (dept_id or dept_name) or not params:
        return jsonify({"error": "department or params missing"}), 400

    if not dept_name and dept_id:
        dept = Department.query.get(dept_id)
        dept_name = dept.name if dept else None

    if not dept_name:
        return jsonify({"error": "invalid department"}), 400

    ranges = get_bulk_ranges(current_app.root_path, dept_name, page, system, params)
    return jsonify({"department": dept_name, "page": page, "system": system, "ranges": ranges})



@analytics_bp.route("/analytics", methods=["GET", "POST"])
@login_required
def analytics_home():
    departments = (
        current_user.departments
        if current_user.role != "admin"
        else Department.query.all()
    )
    if request.method == "POST":
        dept_id = request.form.get("department")
        if dept_id:
            return redirect(url_for("analytics.analytics_view", dept_id=dept_id))
    return render_template("analytics_select.html", departments=departments)



# ---------- DEBUG: inspect where JSON is read from and top-level structure ----------
@analytics_bp.route("/analytics/debug/range-structure", methods=["GET"])
@login_required
def debug_range_structure():
    from flask import current_app, jsonify
    import os
    from app.utils.range import _load_json, _json_path

    abs_path = _json_path(current_app.root_path)
    exists = os.path.exists(abs_path)
    sample = {}
    if exists:
        data = _load_json(abs_path)
        # show just small snippets to avoid dumping everything
        sample = {
            "top_keys": list(data.keys())[:10],
            "SMS-2": list(data.get("SMS-2", {}).keys())[:10],
            "SMS-3": list(data.get("SMS-3", {}).keys())[:10],
            "Rail Mill": list(data.get("Rail Mill", {}).keys())[:10],
            "Plate Mill": list(data.get("Plate Mill", {}).keys())[:10],
            "SPM": list(data.get("SPM", {}).keys())[:10],
            "Power Plant": list(data.get("Power Plant", {}).keys())[:10],
        }
    return jsonify({
        "abs_path_checked": abs_path,
        "exists": exists,
        "sample": sample
    })

# ---------- DEBUG: show exactly how the server normalizes and resolves a lookup ----------
# NOTE: give this a unique endpoint & path to avoid conflicts
@analytics_bp.route("/analytics/debug/resolve1", methods=["POST"], endpoint="analytics_debug_resolve1")
@login_required
def debug_resolve1():
    from flask import current_app, jsonify, request
    from app.utils.range import get_bulk_ranges, _norm
    payload = request.get_json(silent=True) or {}
    dept  = payload.get("department_name")
    page  = payload.get("page")
    system= payload.get("system")
    params= payload.get("params") or []
    ranges = get_bulk_ranges(current_app.root_path, dept, page, system, params)
    return jsonify({
        "input": {
            "department_name": dept, "page": page, "system": system, "params": params
        },
        "normalized": {
            "department_name": _norm(dept or ""),
            "page": _norm(page or ""),
            "system": _norm(system or ""),
            "params": {p: _norm(p) for p in params}
        },
        "result": ranges
    })





@analytics_bp.route("/analytics/view/<int:dept_id>")
@login_required
def analytics_view(dept_id):
    # --- Authorization
    if current_user.role != "admin" and dept_id not in [d.id for d in current_user.departments]:
        flash("You are not authorized to view this department's analytics.", "danger")
        return redirect(url_for("analytics.analytics_home"))

    # --- Base query
    department = Department.query.get_or_404(dept_id)
    query = Report.query.options(
        joinedload(Report.department),
        selectinload(Report.sections).selectinload(ReportSection.parameters),
    ).filter_by(department_id=dept_id)

    # --- Date filters
    start_date = request.args.get("start_date")
    end_date = request.args.get("end_date")

    # By default, Analytics shows the latest 1 month of data.
    if not start_date and not end_date:
        default_end = datetime.now().date()
        default_start = default_end - timedelta(days=DEFAULT_ANALYTICS_DAYS)
        start_date = default_start.strftime("%Y-%m-%d")
        end_date = default_end.strftime("%Y-%m-%d")

    if start_date:
        try:
            parsed_start = datetime.strptime(start_date, "%Y-%m-%d")
            query = query.filter(Report.sampling_time >= parsed_start)
        except Exception:
            flash("Invalid start date format", "danger")
    if end_date:
        try:
            parsed_end = datetime.strptime(end_date, "%Y-%m-%d") + timedelta(days=1)
            query = query.filter(Report.sampling_time < parsed_end)
        except Exception:
            flash("Invalid end date format", "danger")

    reports = query.order_by(Report.sampling_time.asc()).all()

    # --- Incoming selections (shared)
    selected_sheet = request.args.get("selected_sheet")
    selected_system = request.args.get("selected_system")
    if selected_sheet:
        selected_sheet = unquote_plus(selected_sheet)
    if selected_system:
        # user input may be encoded; normalize to plain text
        selected_system = unquote_plus(unquote_plus(selected_system))

    # =========================
    # === SMS-2 handling ======
    # =========================
    sms2_allowed_sheets = ["ICW & DCW Raw Water", "CCM & EAF SW"]
    sms2_data = defaultdict(lambda: defaultdict(lambda: defaultdict(lambda: {"labels": [], "values": []})))
    sms2_display_names = defaultdict(dict)

    if department.name.strip().lower() == "sms-2":
        sheet_prefix_map = {
            "ICW & DCW Raw Water": "icw_dcw",
            "CCM & EAF SW": "ccm_eaf",
        }

        for report in reports:
            # ISO-8601 for Chart.js time scale
            timestamp = report.sampling_time.strftime("%Y-%m-%dT%H:%M:%S")
            for section in report.sections:
                sheet_name = section.sheet_name.strip()
                if sheet_name not in sms2_allowed_sheets:
                    continue

                for p in section.parameters:
                    if not p.name or p.value is None:
                        continue

                    name_from_db = p.name.strip()
                    prefix_to_remove = sheet_prefix_map.get(sheet_name)
                    clean_name = name_from_db

                    # remove per-sheet prefix when present
                    if prefix_to_remove and name_from_db.startswith(prefix_to_remove + "_"):
                        clean_name = name_from_db.replace(f"{prefix_to_remove}_", "", 1)

                    # split "..._<param>" -> ["system", "param"]
                    parts = clean_name.rsplit("_", 1)
                    if len(parts) != 2:
                        continue

                    raw_system = parts[0].strip()
                    param_key = parts[1].strip()

                    # internal key (may look double-encoded if raw_system already contains %)
                    system_key = quote_plus(raw_system)

                    # store time series for this param
                    sms2_data[sheet_name][system_key][param_key]["labels"].append(timestamp)
                    sms2_data[sheet_name][system_key][param_key]["values"].append(float(p.value))

                    # build a human display name
                    display_name = unquote_plus(raw_system).replace("_", " ").upper()
                    sms2_display_names[sheet_name][system_key] = display_name

        # Helper: normalize for case/space-insensitive compare
        def normalize(s: str) -> str:
            return re.sub(r"\s+", "", s.strip().lower())

        # Map selected display name back to the internal system_key
        actual_system_key = ""
        if selected_sheet and selected_system:
            for system_key, display_name in sms2_display_names.get(selected_sheet, {}).items():
                to_compare = unquote_plus(display_name)
                if normalize(to_compare) == normalize(selected_system):
                    actual_system_key = system_key
                    break

        selected_sms2_chart_data = {}
        if actual_system_key:
            selected_sms2_chart_data = sms2_data.get(selected_sheet, {}).get(actual_system_key, {})

        return render_template(
            "analytics_view.html",
            department=department,
            chart_data={},                  # no department-average charts for SMS-2 path currently
            system_data={},
            rail_data={},
            spm_data={},
            power_plant_data={},
            sms2_data=dict(sms2_data),
            sms2_display_names=dict(sms2_display_names),
            selected_sheet=selected_sheet,
            selected_system=selected_system,
            selected_sms2_chart_data=selected_sms2_chart_data,
            start_date=start_date,
            end_date=end_date,
            system_labels={},
        )

    # =========================
    # === SMS-3 handling ======
    # =========================
    sms3_pages = [
        "ICW & DCW System",
        "Close Loop System (Primary System)",
        "Water Consumption",
    ]
    sms3_data = defaultdict(lambda: defaultdict(lambda: defaultdict(lambda: {"labels": [], "values": []})))
    sms3_display_names = defaultdict(dict)

    if department.name.strip().lower() == "sms-3":
        """
        Parameter names as saved by sms3_reports.py look like:
          sms3_icw_<SystemEncoded>_<Param>                 (e.g., sms3_icw_CT-1+%28EAF%29_pH)
          sms3_closeloop_<SystemEncoded>_<Param>           (e.g., sms3_closeloop_SOFT+WATER_TH)
          sms3_consumption_<SystemEncoded>_<Kind>          (Final/Initial/Consumption/Design)

        We will group them into 3 pages as required and chart numeric fields.
        """

        def detect_page_from_name(n: str) -> str:
            n = (n or "").lower()
            if n.startswith("sms3_icw"):
                return "ICW & DCW System"
            if n.startswith("sms3_closeloop"):
                return "Close Loop System (Primary System)"
            if n.startswith("sms3_consumption"):
                return "Water Consumption"
            return "ICW & DCW System"

        for report in reports:
            timestamp = report.sampling_time.strftime("%Y-%m-%dT%H:%M:%S")
            for section in report.sections:
                for p in section.parameters:
                    if not p.name or p.value is None:
                        continue

                    raw_name = p.name.strip()

                    page = detect_page_from_name(raw_name)
                    if page not in sms3_pages:
                        continue

                    # strip top-level prefix
                    if raw_name.startswith("sms3_icw_"):
                        rest = raw_name[len("sms3_icw_"):]
                    elif raw_name.startswith("sms3_closeloop_"):
                        rest = raw_name[len("sms3_closeloop_"):]
                    elif raw_name.startswith("sms3_consumption_"):
                        rest = raw_name[len("sms3_consumption_"):]
                    else:
                        continue

                    # system and param are separated by the last underscore
                    # (system may itself include underscores due to urlencode)
                    parts = rest.rsplit("_", 1)
                    if len(parts) != 2:
                        continue

                    system_encoded = parts[0].strip()
                    param_key = parts[1].strip()

                    # internal key
                    system_key = quote_plus(system_encoded)

                    # display name (decode the encoded system)
                    system_display = unquote_plus(system_encoded).replace("_", " ").upper()

                    # store the series
                    sms3_data[page][system_key][param_key]["labels"].append(timestamp)
                    sms3_data[page][system_key][param_key]["values"].append(float(p.value))
                    sms3_display_names[page][system_key] = system_display

        def normalize(s: str) -> str:
            return re.sub(r"\s+", "", (s or "").strip().lower())

        actual_system_key = ""
        if selected_sheet and selected_system:
            for sys_key, disp in sms3_display_names.get(selected_sheet, {}).items():
                if normalize(disp) == normalize(selected_system):
                    actual_system_key = sys_key
                    break

        selected_sms3_chart_data = {}
        if actual_system_key:
            selected_sms3_chart_data = sms3_data.get(selected_sheet, {}).get(actual_system_key, {})

        return render_template(
            "analytics_view.html",
            department=department,
            chart_data={},   # no department-average charts for SMS-3 path currently
            system_data={},
            rail_data={},
            spm_data={},
            power_plant_data={},
            sms3_data=dict(sms3_data),
            sms3_display_names=dict(sms3_display_names),
            selected_sheet=selected_sheet,
            selected_system=selected_system,
            selected_sms3_chart_data=selected_sms3_chart_data,
            start_date=start_date,
            end_date=end_date,
            system_labels={},
        )

    # ==============================
    # === Other Departments =========
    # ==============================
    chart_data = defaultdict(lambda: {"labels": [], "values": []})
    system_data = defaultdict(lambda: defaultdict(lambda: {"labels": [], "values": []}))
    rail_data = defaultdict(lambda: defaultdict(lambda: {"labels": [], "values": []}))
    spm_data = defaultdict(lambda: defaultdict(lambda: {"labels": [], "values": []}))
    power_plant_data = defaultdict(lambda: defaultdict(lambda: {"labels": [], "values": []}))

    dept_name = department.name.lower()
    is_plate = "plate" in dept_name
    is_rail = "rail" in dept_name
    is_spm = "spm" in dept_name
    is_power = "power" in dept_name

    for report in reports:
        timestamp = report.sampling_time.strftime("%Y-%m-%dT%H:%M:%S")
        for section in report.sections:
            for param in section.parameters:
                if not param.name or param.value is None or "_" not in param.name:
                    continue

                parts = param.name.strip().split("_")
                if is_rail:
                    if len(parts) >= 4 and parts[2].lower() == "mill":
                        system = "ICW Mill"
                        param_key = "_".join(parts[3:])
                    else:
                        system = parts[2].upper()
                        param_key = "_".join(parts[3:])
                    chart_dict = rail_data
                elif is_spm:
                    if len(parts) >= 3:
                        system = parts[1].upper()
                        param_key = "_".join(parts[2:])
                    else:
                        continue
                    chart_dict = spm_data
                elif is_power:
                    if len(parts) >= 4:
                        system = f"{parts[2]} {parts[3]}"
                        param_key = "_".join(parts[4:])
                    else:
                        continue
                    chart_dict = power_plant_data
                else:
                    system = parts[0].lower()
                    param_key = "_".join(parts[1:]).replace("-", " ").lower()
                    chart_dict = system_data

                value = round(float(param.value), 2)
                chart_dict[system][param_key]["labels"].append(timestamp)
                chart_dict[system][param_key]["values"].append(value)

    power_labels = {
        "Feed Water PP1": "Feed Water PP1",
        "Feed Water PP2X55": "Feed Water PP2X55",
        "Feed Water PH2X25": "Feed Water PH2X25",
        "Feed Water PP3x25": "Feed Water PP3x25",
        "Condensate Water PP1": "Condensate Water PP1",
        "Condensate Water PP2X55": "Condensate Water PP2X55",
        "Condensate Water PH2X25": "Condensate Water PH2X25",
        "Condensate Water PP3x25": "Condensate Water PP3x25",
        "Industrial Cooling Water PP1": "Industrial Cooling Water PP1",
        "Industrial Cooling Water PP2X55": "Industrial Cooling Water PP2X55",
        "Industrial Cooling Water PH2X25": "Industrial Cooling Water PH2X25",
        "Industrial Cooling Water PP3x25": "Industrial Cooling Water PP3x25",
    }

    return render_template(
        "analytics_view.html",
        department=department,
        chart_data={},
        system_data=system_data if is_plate else {},
        rail_data=rail_data if is_rail else {},
        spm_data=spm_data if is_spm else {},
        power_plant_data=power_plant_data if is_power else {},
        start_date=start_date,
        end_date=end_date,
        system_labels=power_labels if is_power else {},
    )

# ---------- DEBUG ONLY: quick health + resolver echo ----------

@analytics_bp.route("/analytics/debug/ping")
def debug_ping():
    from flask import jsonify, current_app
    return jsonify({
        "ok": True,
        "message": "analytics blueprint alive",
        "url_map": [str(r) for r in current_app.url_map.iter_rules() if "analytics" in str(r)]
    })

# Give this one a distinct path and endpoint as well.
@analytics_bp.route("/analytics/debug/resolve2", methods=["POST"], endpoint="analytics_debug_resolve2")
def debug_resolve2():
    """
    Echo what the range API will look up, including normalized keys.
    This does NOT read JSON files; it only shows the keys after our normalization.
    """
    from flask import request, jsonify, current_app
    from app.utils import range as rng

    p = request.get_json(silent=True) or {}
    dept = p.get("department_name") or ""
    page = p.get("page") or p.get("sheet") or ""
    system = p.get("system") or ""
    params = p.get("params") or []

    # show normalized forms exactly as get_bulk_ranges() will use
    norm = lambda s: rng._norm(s) if isinstance(s, str) else s
    out = {
        "raw": {"department": dept, "page": page, "system": system, "params": params},
        "normalized": {
            "department": norm(dept),
            "page": norm(page),
            "system": norm(system),
            "params": [norm(x) for x in params],
        },
        "json_abs_path": rng._json_path(current_app.root_path),
        "tip": "Ensure these normalized keys exist in param_ranges_clean.json at the right nesting level"
    }
    return jsonify(out)