from flask_wtf import FlaskForm
from wtforms import StringField, PasswordField, SubmitField, SelectField, SelectMultipleField
from wtforms.validators import DataRequired, Email, EqualTo, Length

# ---------------- User Registration Form ----------------
class RegisterForm(FlaskForm):
    email = StringField('Email', validators=[DataRequired(), Email()])
    password = PasswordField('Password', validators=[
        DataRequired(), Length(min=6, message="Password must be at least 6 characters")
    ])
    confirm = PasswordField('Confirm Password', validators=[
        DataRequired(), EqualTo('password', message='Passwords must match')
    ])
    
    # ✅ Multi-select dropdown instead of checkboxes
    departments = SelectMultipleField('Departments', coerce=int, validators=[DataRequired()])
    
    submit = SubmitField('Register')

# ---------------- User Login Form ----------------
class LoginForm(FlaskForm):
    email = StringField('Email', validators=[DataRequired(), Email()])
    password = PasswordField('Password', validators=[DataRequired()])
    submit = SubmitField('Login')

# ---------------- Add Report Initialization ----------------
class ReportInitForm(FlaskForm):
    department = SelectField('Department', coerce=int, validators=[DataRequired()])
    submit = SubmitField('Start Report')

# ---------------- Department Selection for Analytics ----------------
class DepartmentSelectionForm(FlaskForm):
    department = SelectField('Department', coerce=int, validators=[DataRequired()])
    submit = SubmitField('View Analytics')