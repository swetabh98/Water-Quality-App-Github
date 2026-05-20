"""Add user_departments table

Revision ID: fc884803c686
Revises: 510e180baf1e
Create Date: 2025-08-05 16:02:09.023626
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


# revision identifiers, used by Alembic.
revision = 'fc884803c686'
down_revision = '510e180baf1e'
branch_labels = None
depends_on = None


def upgrade():
    # ✅ Only create the table if it doesn't already exist
    conn = op.get_bind()
    inspector = inspect(conn)
    if 'user_departments' not in inspector.get_table_names():
        op.create_table(
            'user_departments',
            sa.Column('user_id', sa.Integer(), nullable=False),
            sa.Column('department_id', sa.Integer(), nullable=False),
            sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
            sa.ForeignKeyConstraint(['department_id'], ['departments.id'], ondelete='CASCADE'),
            sa.PrimaryKeyConstraint('user_id', 'department_id')
        )

    # ✅ Drop 'department_id' column from 'users' table (if it exists)
    with op.batch_alter_table('users', schema=None) as batch_op:
        columns = [col['name'] for col in inspector.get_columns('users')]
        if 'department_id' in columns:
            batch_op.drop_column('department_id')


def downgrade():
    # ✅ Add 'department_id' back to 'users' table
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.add_column(sa.Column('department_id', sa.INTEGER(), nullable=True))
        batch_op.create_foreign_key(None, 'departments', ['department_id'], ['id'])

    # ✅ Drop the association table
    op.drop_table('user_departments')
