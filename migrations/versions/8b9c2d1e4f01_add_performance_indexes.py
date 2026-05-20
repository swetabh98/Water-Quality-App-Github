"""Add performance indexes for report loading

Revision ID: 8b9c2d1e4f01
Revises: fc884803c686
Create Date: 2026-05-18 00:00:00.000000
"""

from alembic import op
from sqlalchemy import inspect


# revision identifiers, used by Alembic.
revision = '8b9c2d1e4f01'
down_revision = 'fc884803c686'
branch_labels = None
depends_on = None


def _index_exists(inspector, table_name, index_name):
    return any(index.get('name') == index_name for index in inspector.get_indexes(table_name))


def _create_index_if_missing(inspector, index_name, table_name, columns, unique=False):
    if table_name not in inspector.get_table_names():
        return
    if not _index_exists(inspector, table_name, index_name):
        op.create_index(index_name, table_name, columns, unique=unique)


def _drop_index_if_exists(inspector, index_name, table_name):
    if table_name not in inspector.get_table_names():
        return
    if _index_exists(inspector, table_name, index_name):
        op.drop_index(index_name, table_name=table_name)


def upgrade():
    conn = op.get_bind()
    inspector = inspect(conn)

    _create_index_if_missing(inspector, 'ix_user_departments_department_id', 'user_departments', ['department_id'])
    _create_index_if_missing(inspector, 'ix_equipments_department_id', 'equipments', ['department_id'])

    _create_index_if_missing(inspector, 'ix_reports_user_id', 'reports', ['user_id'])
    _create_index_if_missing(inspector, 'ix_reports_department_id', 'reports', ['department_id'])
    _create_index_if_missing(inspector, 'ix_reports_equipment_id', 'reports', ['equipment_id'])
    _create_index_if_missing(inspector, 'ix_reports_sampling_time', 'reports', ['sampling_time'])
    _create_index_if_missing(inspector, 'ix_reports_department_sampling_time', 'reports', ['department_id', 'sampling_time'])

    _create_index_if_missing(inspector, 'ix_report_sections_report_id', 'report_sections', ['report_id'])
    _create_index_if_missing(inspector, 'ix_report_parameters_section_id', 'report_parameters', ['section_id'])


def downgrade():
    conn = op.get_bind()
    inspector = inspect(conn)

    _drop_index_if_exists(inspector, 'ix_report_parameters_section_id', 'report_parameters')
    _drop_index_if_exists(inspector, 'ix_report_sections_report_id', 'report_sections')

    _drop_index_if_exists(inspector, 'ix_reports_department_sampling_time', 'reports')
    _drop_index_if_exists(inspector, 'ix_reports_sampling_time', 'reports')
    _drop_index_if_exists(inspector, 'ix_reports_equipment_id', 'reports')
    _drop_index_if_exists(inspector, 'ix_reports_department_id', 'reports')
    _drop_index_if_exists(inspector, 'ix_reports_user_id', 'reports')

    _drop_index_if_exists(inspector, 'ix_equipments_department_id', 'equipments')
    _drop_index_if_exists(inspector, 'ix_user_departments_department_id', 'user_departments')
