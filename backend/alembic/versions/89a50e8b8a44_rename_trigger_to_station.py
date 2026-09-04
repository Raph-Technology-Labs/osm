"""rename trigger to station

Revision ID: 89a50e8b8a44
Revises: fdad727971a1
Create Date: 2026-09-04 08:27:28.490026

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '89a50e8b8a44'
down_revision: Union[str, Sequence[str], None] = 'fdad727971a1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.drop_constraint('ck_session_trigger_type', 'part_sessions', type_='check')
    op.drop_constraint('ck_session_trigger_source', 'part_sessions', type_='check')

    op.alter_column('part_sessions', 'trigger_id', new_column_name='station_id')
    op.alter_column('part_sessions', 'trigger_type', new_column_name='station_type')
    op.alter_column('part_sessions', 'trigger_source', new_column_name='station_source')

    op.create_check_constraint(
        'ck_session_station_type', 'part_sessions', "station_type IN ('inspection','counting')"
    )
    op.create_check_constraint(
        'ck_session_station_source', 'part_sessions', "station_source IN ('simulation','plc','ui_button')"
    )

    op.alter_column('session_results', 'trigger_id', new_column_name='station_id')
    op.alter_column('session_results', 'trigger_fire_no', new_column_name='station_fire_no')


def downgrade() -> None:
    """Downgrade schema."""
    op.alter_column('session_results', 'station_fire_no', new_column_name='trigger_fire_no')
    op.alter_column('session_results', 'station_id', new_column_name='trigger_id')

    op.drop_constraint('ck_session_station_type', 'part_sessions', type_='check')
    op.drop_constraint('ck_session_station_source', 'part_sessions', type_='check')

    op.alter_column('part_sessions', 'station_source', new_column_name='trigger_source')
    op.alter_column('part_sessions', 'station_type', new_column_name='trigger_type')
    op.alter_column('part_sessions', 'station_id', new_column_name='trigger_id')

    op.create_check_constraint(
        'ck_session_trigger_type', 'part_sessions', "trigger_type IN ('inspection','counting')"
    )
    op.create_check_constraint(
        'ck_session_trigger_source', 'part_sessions', "trigger_source IN ('simulation','plc','ui_button')"
    )
