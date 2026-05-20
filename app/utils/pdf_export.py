from flask import render_template, current_app
from xhtml2pdf import pisa
from io import BytesIO
import os

def generate_pdf_report(template_name, context):
    html = render_template(template_name, **context, os_path=os.getcwd())
    pdf_file = BytesIO()
    pisa_status = pisa.CreatePDF(html, dest=pdf_file)

    if pisa_status.err:
        return None
    pdf_file.seek(0)
    return pdf_file
