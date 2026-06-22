"""updating agent_status for consistency and fixing foreign key

Revision ID: 9268a5771bb1
Revises: c87d7755382a
Create Date: 2026-06-20 23:37:22.364572

"""
from alembic import op
import sqlalchemy as sa

revision = '9268a5771bb1'
down_revision = 'c87d7755382a'
branch_labels = None
depends_on = None

def upgrade():
    # 1. Create new table with corrected foreign key, NOT NULLs, and index
    op.execute("""
        CREATE TABLE transactions_new (
            id VARCHAR PRIMARY KEY NOT NULL,
            employee_id VARCHAR NOT NULL,
            date DATETIME,
            category VARCHAR NOT NULL,
            amount FLOAT NOT NULL,
            merchant VARCHAR NOT NULL,
            receipt_provided BOOLEAN,
            transaction_status VARCHAR NOT NULL,
            agent_decision VARCHAR NOT NULL,
            HIL_status VARCHAR,
            CONSTRAINT fk_transaction_employee FOREIGN KEY (employee_id) REFERENCES employees(id),
            CONSTRAINT fk_transaction_category FOREIGN KEY (category) REFERENCES expense_policies(category),
            CHECK (transaction_status IN ('completed','flagged','pending_review','cancelled','failed')),
            CHECK (agent_decision IN ('pending','approved','rejected','escalated')),
            CHECK (HIL_status IS NULL OR HIL_status IN ('approved','rejected'))
        )
    """)

    # 2. Copy data, backfilling agent_decision based on transaction_status
    op.execute("""
        INSERT INTO transactions_new 
            (id, employee_id, date, category, amount, merchant, receipt_provided,
             transaction_status, agent_decision, HIL_status)
        SELECT
            id, employee_id, date, category, amount, merchant, receipt_provided,
            transaction_status,
            CASE
                WHEN transaction_status = 'completed' THEN 'approved'
                WHEN transaction_status = 'cancelled' THEN 'rejected'
                ELSE 'pending'
            END,
            HIL_status
        FROM transactions
    """)

    # 3. Create the composite index on the new table
    op.execute("CREATE INDEX idx_trans_emp_date ON transactions_new (employee_id, date)")

    # 4. Swap tables
    op.execute("DROP TABLE transactions")
    op.execute("ALTER TABLE transactions_new RENAME TO transactions")

def downgrade():
    # Recreate the old schema (without NOT NULL, without index, with old foreign key)
    op.execute("""
        CREATE TABLE transactions_old (
            id VARCHAR PRIMARY KEY,
            employee_id VARCHAR NOT NULL,
            date DATETIME,
            category VARCHAR NOT NULL,
            amount FLOAT NOT NULL,
            merchant VARCHAR,
            receipt_provided BOOLEAN,
            transaction_status VARCHAR,
            agent_decision VARCHAR,
            HIL_status VARCHAR,
            CONSTRAINT fk_transaction_employee FOREIGN KEY (employee_id) REFERENCES employees(id),
            CHECK (transaction_status IN ('completed','flagged','pending_review','cancelled','failed')),
            CHECK (agent_decision IN ('pending','approved','rejected','escalated')),
            CHECK (HIL_status IS NULL OR HIL_status IN ('approved','rejected'))
        )
    """)
    op.execute("""
        INSERT INTO transactions_old
            (id, employee_id, date, category, amount, merchant, receipt_provided,
             transaction_status, agent_decision, HIL_status)
        SELECT
            id, employee_id, date, category, amount, merchant, receipt_provided,
            transaction_status, 'pending', HIL_status
        FROM transactions
    """)
    op.execute("DROP TABLE transactions")
    op.execute("ALTER TABLE transactions_old RENAME TO transactions")