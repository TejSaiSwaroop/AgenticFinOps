from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy import Column, String, Float, Boolean, DateTime, ForeignKey, Index
from datetime import datetime
from sqlalchemy.orm import relationship

Base = declarative_base()

class Employee(Base):
    __tablename__ = "employees"
    id = Column(String, primary_key=True)
    name = Column(String, nullable=False)
    policy_limit = Column(Float, nullable=False)
    risk_tier = Column(String, nullable=False)
    manager_slack_id = Column(String)

    transactions = relationship("Transaction", back_populates="employees")
    investigations = relationship("Investigation", back_populates="employees")

class ExpensePolicy(Base):
    __tablename__ = "expense_policies"
    category = Column(String, primary_key=True)
    max_amount = Column(Float, nullable=False)
    requires_receipt = Column(Boolean, default=False)
    note = Column(String)


class Transaction(Base):
    __tablename__ = "transactions"
    id = Column(String, primary_key=True)
    employee_id = Column(String, ForeignKey("employees.id", name = "fk_transaction_employee"), nullable=False)
    date = Column(DateTime, default=datetime.now)
    category = Column(String, ForeignKey("expense_policies.category", name = "fk_transaction_category"), nullable=False)
    amount = Column(Float, nullable=False)
    merchant = Column(String)
    status = Column(String, default="completed")  # completed, flagged, rejected
    receipt_provided = Column(Boolean, default=False)

    employees = relationship("Employee", back_populates="transactions")

class Investigation(Base):
    __tablename__ = "investigations"
    id = Column(String, primary_key=True)  # transaction_id
    employee_id = Column(String, ForeignKey("employees.id", name="fk_investigations_employee"), nullable=False)
    category = Column(String, ForeignKey("expense_policies.category", name = "fk_investigations_category"))
    amount = Column(Float)
    decision = Column(String)  # APPROVED, REJECTED, ESCALATED
    reasoning = Column(String)
    evidence_summary = Column(String)
    created_at = Column(DateTime, default=datetime.now)

    employees = relationship("Employee", back_populates="investigations")

# Index for the most common query pattern
Index('idx_trans_emp_date', Transaction.employee_id, Transaction.date)
Index('idx_inv_employee_id', Investigation.employee_id)