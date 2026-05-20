Water Quality App - PostgreSQL Migration Package
================================================

This package moves the app from SQLite to PostgreSQL while keeping the previous
fast-loading fixes: indexes, eager loading, and dashboard default date range.

PostgreSQL connection used by default
-------------------------------------
Host: 172.17.0.20
Port: 5432
User: postgres
Maintenance database: postgres
Target app database: water_quality_db

The password is configured in config.py from POSTGRES_PASSWORD, defaulting to
the value supplied for this deployment. For better security later, set it as an
environment variable instead of keeping it in code.

Files included
--------------
Replace/copy these files into your project:

1. config.py
   - Changes SQLALCHEMY_DATABASE_URI to PostgreSQL.
   - Uses postgres as the maintenance database.
   - Enables automatic database/table/index creation if missing.

2. app/__init__.py
   - Calls the PostgreSQL bootstrap before initializing the app database.
   - Creates missing tables and indexes automatically.

3. app/postgres_bootstrap.py
   - New helper file.
   - Creates the PostgreSQL database if it does not exist.
   - Creates missing tables with db.create_all().
   - Creates performance indexes with CREATE INDEX IF NOT EXISTS.
   - Stamps alembic_version if missing so old migrations do not replay.

4. migrate_sqlite_to_postgres.py
   - New one-time migration script.
   - Copies the existing SQLite data from instance/database.db to PostgreSQL.
   - Preserves IDs and resets PostgreSQL sequences.

5. requirements.txt
   - Adds psycopg2-binary.

6. run_water_app.bat
   - Keeps the same path.
   - Adds psycopg2-binary to the packages installed before startup.

7. app/models.py and fast-loading route files
   - Included so the PostgreSQL-created tables have the same performance indexes
     and the app keeps the earlier eager-loading/dashboard speed fixes.

How to apply
------------
1. Stop the app.

2. Backup SQLite:
   copy instance\database.db instance\database_before_postgres_migration.db

3. Copy/replace the files from this package into the project.

4. Install the PostgreSQL driver:
   python -m pip install psycopg2-binary

   Or simply start using run_water_app.bat, which now installs it automatically.

5. Test PostgreSQL connection/table creation:
   python wsgi.py

   On first start, the app will create the database water_quality_db if missing,
   then create missing tables and indexes.

6. Stop the app, then run the one-time data migration:
   python migrate_sqlite_to_postgres.py

   If PostgreSQL already has app data and you intentionally want to recopy from
   SQLite, use:
   python migrate_sqlite_to_postgres.py --force

7. Start the app again:
   python wsgi.py

Important notes
---------------
- Do not run --force unless you are sure. It deletes existing PostgreSQL app data
  before copying again.
- The migration script skips invalid/orphan rows if any exist because PostgreSQL
  enforces foreign keys properly.
- The PostgreSQL server must allow TCP/IP connections from this app machine.
  If connection fails, check firewall, postgresql.conf listen_addresses, and
  pg_hba.conf on the PostgreSQL server.
