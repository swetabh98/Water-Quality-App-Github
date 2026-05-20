##app/utils/email_notifications.py

import os
import smtplib
from flask import url_for, current_app
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.application import MIMEApplication
from email.utils import formataddr
from sqlalchemy import inspect as sqlalchemy_inspect
from app.models import User, Department, Report
from app.utils.pdf_export import generate_pdf_report
from app import db

SENDER_EMAIL = "noreply.digital@jindalsteel.com"
SENDER_NAME = "Water Quality App"
SMTP_SERVER = "172.17.1.17"
SMTP_PORT = 25

# --- Jindal branding (matches base.css colours; does not affect logic) --------
BRAND_LOGO_URL = os.environ.get(
    "JINDAL_LOGO_URL",
    "https://www.jindalsteel.com/themes/custom/jindalsteel/logo.svg"
)

BRAND_NAME = "Jindal Steel"
APP_NAME = "Water Quality App"

BRAND_COLOR_SAFFRON = os.environ.get("JINDAL_BRAND_SAFFRON", "#f47b20")
BRAND_COLOR_SAFFRON_SOFT = os.environ.get("JINDAL_BRAND_SAFFRON_SOFT", "#fff1e6")
BRAND_COLOR_SPRING_GREEN = os.environ.get("JINDAL_BRAND_SPRING_GREEN", "#4cb848")
BRAND_COLOR_SPRING_GREEN_SOFT = os.environ.get("JINDAL_BRAND_SPRING_GREEN_SOFT", "#eef9ec")
BRAND_COLOR_GREY = os.environ.get("JINDAL_BRAND_GREY", "#5e5f5e")
BRAND_COLOR_GREY_SOFT = os.environ.get("JINDAL_BRAND_GREY_SOFT", "#f3f4f2")
BRAND_COLOR_WHITE = os.environ.get("JINDAL_BRAND_WHITE", "#ffffff")

BRAND_COLOR_BURGUNDY = os.environ.get("JINDAL_BRAND_BURGUNDY", "#8c3f4c")
BRAND_COLOR_MOSS_GREEN = os.environ.get("JINDAL_BRAND_MOSS_GREEN", "#8ca55d")
BRAND_COLOR_TWILIGHT_BLUE = os.environ.get("JINDAL_BRAND_TWILIGHT_BLUE", "#466684")
BRAND_COLOR_DARK_PEACH = os.environ.get("JINDAL_BRAND_DARK_PEACH", "#d68e5e")
BRAND_COLOR_OYSTER_GREEN = os.environ.get("JINDAL_BRAND_OYSTER_GREEN", "#8c8c6b")
BRAND_COLOR_SKY_BLUE = os.environ.get("JINDAL_BRAND_SKY_BLUE", "#2ca7d4")

BRAND_COLOR_TEXT = os.environ.get("JINDAL_BRAND_TEXT", "#2f3430")
BRAND_COLOR_MUTED = os.environ.get("JINDAL_BRAND_MUTED", "#6d706d")
BRAND_COLOR_LINE = os.environ.get("JINDAL_BRAND_LINE", "rgba(94, 95, 94, 0.18)")
BRAND_COLOR_BG = os.environ.get("JINDAL_BRAND_BG", "#fbfaf6")

BRAND_FONT_STACK = os.environ.get(
    "JINDAL_BRAND_FONT",
    "Poppins, Arial, Helvetica, sans-serif"
)

def _extract_report_id(report_or_id):
    if isinstance(report_or_id, int):
        return report_or_id

    try:
        report_id = getattr(report_or_id, "id", None)
        if report_id is not None:
            return report_id
    except Exception:
        pass

    try:
        identity = sqlalchemy_inspect(report_or_id).identity
        if identity:
            return identity[0]
    except Exception:
        pass

    return None

def _brand_logo_url() -> str:
    """
    Prefer the local static logo at app/static/images/jindal_steel_logo.{png,svg,jpg,jpeg,gif}.
    Fall back to BRAND_LOGO_URL if not found or if url_for/current_app not available.
    """
    try:
        static_dir = os.path.join(current_app.root_path, "static", "images")
        for ext in (".png", ".svg", ".jpg", ".jpeg", ".gif"):
            fname = f"jindal_steel_logo{ext}"
            if os.path.exists(os.path.join(static_dir, fname)):
                return url_for("static", filename=f"images/{fname}", _external=True)
    except Exception:
        pass
    return BRAND_LOGO_URL

def _email_from_header() -> str:
    return formataddr((SENDER_NAME, SENDER_EMAIL))

def send_report_notification(report, app, db, action="submitted"):
    with app.app_context():
        report_id = _extract_report_id(report)

        if not report_id:
            print("❌ Email sending failed: report ID could not be resolved.")
            return

        report = db.session.get(Report, report_id)

        if not report:
            print(f"⚠️ Report not found for ID: {report_id}")
            return

        # ✅ FIX: Support users with multiple departments
        dept_users = (
            db.session.query(User)
            .join(User.departments)
            .filter(Department.id == report.department_id)
            .all()
        )

        admins = User.query.filter_by(role='admin').all()
        # ⛔ Exclude Lalit from recipients
        recipients = set(
            user.email
            for user in dept_users + admins
            if user.email and user.email.lower() != "lalit.goyal@jindalsteel.com"
        )
        # ⛔ Also exclude if the report submitter is Lalit
        if getattr(report, "user", None) and getattr(report.user, "email", None):
            if report.user.email.lower() != "lalit.goyal@jindalsteel.com":
                recipients.add(report.user.email)

        if not recipients:
            print(f"⚠️ No recipients found for report ID: {report.id}")
            return

        dept_name = (report.department.name or "").lower()

        # ✅ Route and template selection
        if "sms-2" in dept_name:
            route_name = 'sms2_reports.view_report_sms2'
            pdf_template = "pages/sms_pdf.html"
        elif "sms-3" in dept_name:
            route_name = 'sms3_reports.view_report_sms3'
            pdf_template = "pages/sms_pdf.html"
        elif "plate" in dept_name:
            route_name = 'reports.view_report'
            pdf_template = "pdf/platemill_pdf.html"
        elif "rail" in dept_name:
            route_name = 'rail_mill_reports.view_report_rail_mill'
            pdf_template = "pages/rail_mill_pdf.html"
        elif "spm" in dept_name:
            route_name = 'spm_reports.view_report_spm'
            pdf_template = "pages/spm_pdf.html"
        elif "power" in dept_name:
            route_name = 'power_plant_reports.view_report_power_plant'
            pdf_template = "pages/power_plant_pdf.html"
        else:
            route_name = 'reports.view_report'
            pdf_template = "pages/report_pdf_template.html"

        try:
            report_url = url_for(route_name, report_id=report.id, _external=True)
        except Exception as e:
            print(f"⚠️ URL generation failed for report ID {report.id}: {e}")
            report_url = "#"

        subject = f"📊 Report {action.title()} – {report.department.name} (ID: {report.id})"

        logo_url = _brand_logo_url()
        submitted_by = getattr(getattr(report, "user", None), "email", "Unknown User")
        sampling_time = report.sampling_time.strftime('%Y-%m-%d %H:%M:%S')

        html_body = f"""
        <!DOCTYPE html>
        <html>
        <head>
          <meta charset="utf-8">
          <meta http-equiv="x-ua-compatible" content="ie=edge">
          <meta name="viewport" content="width=device-width, initial-scale=1.0">
          <title>{subject}</title>
          <link href="https://fonts.googleapis.com/css2?family=Poppins:wght@400;500;600;700;800;900&display=swap" rel="stylesheet">
        </head>
        <body style="margin:0;padding:0;background:{BRAND_COLOR_BG};font-family:{BRAND_FONT_STACK};color:{BRAND_COLOR_TEXT};">
          <table role="presentation" cellspacing="0" cellpadding="0" border="0" width="100%" style="background:linear-gradient(135deg,#ffffff 0%,#fffaf3 42%,#f4faef 100%);">
            <tr>
              <td align="center" style="padding:28px 12px;">
                <table role="presentation" cellspacing="0" cellpadding="0" border="0" width="720" style="max-width:720px;width:100%;background:#ffffff;border-radius:24px;overflow:hidden;border:1px solid rgba(94,95,94,0.16);box-shadow:0 18px 44px rgba(94,95,94,0.16);">

                  <tr>
                    <td style="padding:0;height:7px;background:linear-gradient(90deg,{BRAND_COLOR_SAFFRON} 0%,{BRAND_COLOR_DARK_PEACH} 30%,{BRAND_COLOR_GREY} 58%,{BRAND_COLOR_SPRING_GREEN} 100%);"></td>
                  </tr>

                  <tr>
                    <td style="padding:24px 26px 18px 26px;background:linear-gradient(135deg,#ffffff 0%,{BRAND_COLOR_SAFFRON_SOFT} 50%,{BRAND_COLOR_SPRING_GREEN_SOFT} 100%);">
                      <table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0">
                        <tr>
                          <td valign="middle" style="width:88px;">
                            <div style="width:74px;height:74px;border-radius:20px;background:#ffffff;border:1px solid rgba(94,95,94,0.14);box-shadow:0 12px 28px rgba(94,95,94,0.12);display:inline-block;text-align:center;">
                              <img src="{logo_url}" alt="{BRAND_NAME} logo" width="54" style="display:block;height:auto;border:0;margin:20px auto 0 auto;max-width:54px;">
                            </div>
                          </td>
                          <td valign="middle" style="padding-left:14px;">
                            <div style="font-size:12px;font-weight:900;letter-spacing:0.16em;text-transform:uppercase;color:{BRAND_COLOR_SAFFRON};line-height:1.3;">
                              {BRAND_NAME}
                            </div>
                            <div style="font-size:28px;font-weight:900;letter-spacing:-0.04em;line-height:1.08;color:{BRAND_COLOR_GREY};margin-top:4px;">
                              {APP_NAME}
                            </div>
                            <div style="font-size:13px;font-weight:700;color:{BRAND_COLOR_MUTED};margin-top:7px;">
                              Advanced Report Notification
                            </div>
                          </td>
                          <td valign="middle" align="right" style="padding-left:12px;">
                            <span style="display:inline-block;padding:10px 14px;border-radius:999px;background:#ffffff;border:1px solid rgba(76,184,72,0.30);color:{BRAND_COLOR_GREY};font-size:13px;font-weight:900;white-space:nowrap;">
                              ● Report {action.title()}
                            </span>
                          </td>
                        </tr>
                      </table>
                    </td>
                  </tr>

                  <tr>
                    <td style="padding:24px 26px 8px 26px;background:#ffffff;">
                      <p style="margin:0 0 10px 0;font-size:15px;line-height:1.7;color:{BRAND_COLOR_TEXT};">Hello,</p>
                      <p style="margin:0 0 18px 0;font-size:15px;line-height:1.7;color:{BRAND_COLOR_TEXT};">
                        A water quality report has been <strong style="color:{BRAND_COLOR_SAFFRON};">{action}</strong>. The summary is shown below for quick review.
                      </p>

                      <table role="presentation" cellspacing="0" cellpadding="0" border="0" width="100%" style="margin:0 0 18px 0;">
                        <tr>
                          <td width="33.33%" style="padding:0 7px 0 0;">
                            <div style="border:1px solid rgba(244,123,32,0.24);border-radius:18px;background:{BRAND_COLOR_SAFFRON_SOFT};padding:16px 16px;min-height:94px;">
                              <div style="font-size:12px;font-weight:900;letter-spacing:0.08em;text-transform:uppercase;color:{BRAND_COLOR_MUTED};">Report ID</div>
                              <div style="font-size:26px;font-weight:900;color:{BRAND_COLOR_GREY};line-height:1.1;margin-top:8px;">{report.id}</div>
                            </div>
                          </td>
                          <td width="33.33%" style="padding:0 7px;">
                            <div style="border:1px solid rgba(76,184,72,0.24);border-radius:18px;background:{BRAND_COLOR_SPRING_GREEN_SOFT};padding:16px 16px;min-height:94px;">
                              <div style="font-size:12px;font-weight:900;letter-spacing:0.08em;text-transform:uppercase;color:{BRAND_COLOR_MUTED};">Department</div>
                              <div style="font-size:18px;font-weight:900;color:{BRAND_COLOR_GREY};line-height:1.2;margin-top:8px;">{report.department.name}</div>
                            </div>
                          </td>
                          <td width="33.33%" style="padding:0 0 0 7px;">
                            <div style="border:1px solid rgba(70,102,132,0.24);border-radius:18px;background:#f5f8fb;padding:16px 16px;min-height:94px;">
                              <div style="font-size:12px;font-weight:900;letter-spacing:0.08em;text-transform:uppercase;color:{BRAND_COLOR_MUTED};">Status</div>
                              <div style="font-size:18px;font-weight:900;color:{BRAND_COLOR_TWILIGHT_BLUE};line-height:1.2;margin-top:8px;">{action.title()}</div>
                            </div>
                          </td>
                        </tr>
                      </table>

                      <table border="0" cellpadding="0" cellspacing="0" width="100%" role="presentation" style="border-collapse:separate;border-spacing:0;border:1px solid rgba(94,95,94,0.16);border-radius:18px;overflow:hidden;margin:0 0 20px 0;background:#ffffff;">
                        <tbody style="font-size:14px;">
                          <tr>
                            <td style="padding:14px 16px;background:{BRAND_COLOR_GREY_SOFT};width:170px;border-bottom:1px solid rgba(94,95,94,0.14);font-weight:900;color:{BRAND_COLOR_GREY};">Submitted By</td>
                            <td style="padding:14px 16px;border-bottom:1px solid rgba(94,95,94,0.14);color:{BRAND_COLOR_TEXT};">{submitted_by}</td>
                          </tr>
                          <tr>
                            <td style="padding:14px 16px;background:{BRAND_COLOR_GREY_SOFT};width:170px;border-bottom:1px solid rgba(94,95,94,0.14);font-weight:900;color:{BRAND_COLOR_GREY};">Sample Time</td>
                            <td style="padding:14px 16px;border-bottom:1px solid rgba(94,95,94,0.14);color:{BRAND_COLOR_TEXT};">{sampling_time}</td>
                          </tr>
                          <tr>
                            <td style="padding:14px 16px;background:{BRAND_COLOR_GREY_SOFT};width:170px;font-weight:900;color:{BRAND_COLOR_GREY};">Application</td>
                            <td style="padding:14px 16px;color:{BRAND_COLOR_TEXT};">{APP_NAME}</td>
                          </tr>
                        </tbody>
                      </table>

                      <div style="text-align:center;margin:26px 0 18px 0;">
                        <a href="{report_url}" target="_blank" rel="noopener" style="display:inline-block;padding:14px 24px;border-radius:999px;background:linear-gradient(135deg,{BRAND_COLOR_SAFFRON},{BRAND_COLOR_DARK_PEACH});color:#ffffff;text-decoration:none;font-size:14px;font-weight:900;box-shadow:0 12px 28px rgba(244,123,32,0.22);">
                          View Report
                        </a>
                      </div>

                      <p style="margin:18px 0 0 0;font-size:12px;line-height:1.6;color:{BRAND_COLOR_MUTED};text-align:center;">
                        This notification was generated automatically by {APP_NAME}.
                      </p>
                    </td>
                  </tr>

                  <tr>
                    <td style="padding:18px 26px 24px 26px;background:#ffffff;">
                      <div style="height:1px;background:rgba(94,95,94,0.14);margin-bottom:16px;"></div>
                      <table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0">
                        <tr>
                          <td style="font-size:12px;color:{BRAND_COLOR_MUTED};font-weight:700;">
                            © {BRAND_NAME}. All rights reserved.
                          </td>
                          <td align="right" style="font-size:12px;color:{BRAND_COLOR_MUTED};font-weight:800;">
                            Water Quality Monitoring
                          </td>
                        </tr>
                      </table>
                    </td>
                  </tr>

                </table>
              </td>
            </tr>
          </table>
        </body>
        </html>
        """

        message = MIMEMultipart()
        message['From'] = _email_from_header()
        message['To'] = ", ".join(recipients)
        message['Subject'] = subject
        message.attach(MIMEText(html_body, "html"))

        try:
            context = report.get_context_dict() if hasattr(report, 'get_context_dict') else {}
            context.update({
                'report': report,
                'department': report.department,
                'equipment': report.equipment,
                'sampling_time': report.sampling_time,
                'params': context.get('params', {})
            })

            # ✅ For Plate Mill
            if "plate" in dept_name:
                from app.routes.reports import get_processed_plate_data
                context["processed_data"] = get_processed_plate_data(report)

            # ✅ For Rail Mill, SPM, Power Plant
            if "rail" in dept_name or "spm" in dept_name or "power" in dept_name:
                context["params"] = {}
                for section in report.sections:
                    for param in section.parameters:
                        if param.name:
                            context["params"][param.name] = (
                                param.range_value if param.range_value is not None else param.value
                            )

            pdf_file = generate_pdf_report(pdf_template, context)
            if pdf_file:
                part = MIMEApplication(pdf_file.read(), _subtype="pdf")
                part.add_header('Content-Disposition', 'attachment', filename=f"Report_{report.id}.pdf")
                message.attach(part)
        except Exception as e:
            print(f"⚠️ PDF attachment failed: {e}")

        try:
            with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as server:
                server.sendmail(SENDER_EMAIL, list(recipients), message.as_string())
            print(f"✅ Email ({action}) sent with PDF to {len(recipients)} recipients for report ID {report.id}.")
        except Exception as e:
            print(f"❌ Email sending failed for report ID {report.id}: {e}")