from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from datetime import datetime

db = SQLAlchemy()

# ---------------- Association Table ----------------
user_departments = db.Table('user_departments',
    db.Column('user_id', db.Integer, db.ForeignKey('users.id'), primary_key=True),
    db.Column('department_id', db.Integer, db.ForeignKey('departments.id'), primary_key=True),
    db.Index('ix_user_departments_department_id', 'department_id')
)

# ---------------- Department ----------------
class Department(db.Model):
    __tablename__ = 'departments'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(64), unique=True, nullable=False)

    equipments = db.relationship('Equipment', backref='department', lazy=True)
    reports = db.relationship('Report', backref='department', lazy=True)
    users = db.relationship('User', secondary=user_departments, back_populates='departments')

# ---------------- Equipment ----------------
class Equipment(db.Model):
    __tablename__ = 'equipments'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(64), nullable=False)
    department_id = db.Column(db.Integer, db.ForeignKey('departments.id'), nullable=False, index=True)

# ---------------- User ----------------
class User(UserMixin, db.Model):
    __tablename__ = 'users'

    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password = db.Column(db.String(128), nullable=False)
    role = db.Column(db.String(20), default='user')

    reports = db.relationship('Report', backref='user', lazy=True)
    departments = db.relationship('Department', secondary=user_departments, back_populates='users')

# ---------------- Report ----------------
class Report(db.Model):
    __tablename__ = 'reports'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), index=True)
    department_id = db.Column(db.Integer, db.ForeignKey('departments.id'), index=True)
    equipment_id = db.Column(db.Integer, db.ForeignKey('equipments.id'), nullable=True, index=True)
    sampling_time = db.Column(db.DateTime, default=datetime.utcnow, index=True)

    __table_args__ = (
        db.Index('ix_reports_department_sampling_time', 'department_id', 'sampling_time'),
    )

    equipment = db.relationship('Equipment', backref='reports')
    sections = db.relationship('ReportSection', backref='report', lazy=True)

# ---------------- ReportSection ----------------
class ReportSection(db.Model):
    __tablename__ = 'report_sections'

    id = db.Column(db.Integer, primary_key=True)
    report_id = db.Column(db.Integer, db.ForeignKey('reports.id'), index=True)
    sheet_name = db.Column(db.String(64))

    parameters = db.relationship('ReportParameter', backref='section', lazy=True)

# ---------------- ReportParameter ----------------
class ReportParameter(db.Model):
    __tablename__ = 'report_parameters'

    id = db.Column(db.Integer, primary_key=True)
    section_id = db.Column(db.Integer, db.ForeignKey('report_sections.id'), index=True)
    name = db.Column(db.String(255))
    value = db.Column(db.Float)
    range_value = db.Column(db.Text)

# ---------------- ParameterRange ----------------
class ParameterRange(db.Model):
    __tablename__ = 'parameter_ranges'

    id = db.Column(db.Integer, primary_key=True)
    department_name = db.Column(db.String(64), nullable=False)
    sheet_name = db.Column(db.String(64), nullable=False)
    parameter_name = db.Column(db.String(255), nullable=False)
    range_value = db.Column(db.Text, nullable=False)