# In app/cli.py

import click
from flask.cli import with_appcontext
from werkzeug.security import generate_password_hash
from .models import db, User
from flask import current_app

@click.command('init-db')
@with_appcontext
def init_db_command():
    """Drops all tables, creates new ones, and adds admin users. Protected by a password."""

    # 1. Ask for the password first
    password = click.prompt(
        "Please enter the reset password to proceed", hide_input=True, confirmation_prompt=False
    )

    # 2. Check the password
    if password != current_app.config.get("RESET_DB_PASSWORD"):
        click.echo("Incorrect password. Database reset cancelled.")
        return

    # 3. If password is correct, reset the database
    click.echo("Password accepted. Resetting database and creating admin users...")
    db.drop_all()
    db.create_all()
    
    # 4. Create the default admin users
    admins = [
        'swetabh.sinha@jindalsteel.com',
        'lalit.goyal@jindalsteel.com'
    ]

    for email in admins:
        if not User.query.filter_by(email=email).first():
            new_admin = User(
                email=email,
                password=generate_password_hash('CAC2025'), # For production, use a more secure password
                role='admin'
            )
            db.session.add(new_admin)
            click.echo(f"✅ Admin user created: {email}")

    db.session.commit()
    click.echo("✅ Database has been initialized with admin users.")
