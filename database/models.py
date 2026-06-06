from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy import Column, String, Float, Boolean, Date, DateTime
from datetime import datetime

Base = declarative_base()

class Employee(Base):
    __tablename__ = "employees"
    id = Column(String, primary_key=True)
    name = Column(String, nullable=False)
    policy_limit = Column(Float, nullable=False)
    risk_tier = Column(String, nullable=False)
    manager_slack_id = Column(String)

class ExpensePolicy(Base):
    __tablename__ = "expense_policies"
    category = Column(String, primary_key=True)
    max_amount = Column(Float, nullable=False)
    requires_receipt = Column(Boolean, default=False)
    note = Column(String)


class Transaction(Base):
    __tablename__ = "transactions"
    id = Column(String, primary_key=True)
    employee_id = Column(String, nullable=False)
    date = Column(DateTime, default=datetime.now)
    category = Column(String, nullable=False)
    amount = Column(Float, nullable=False)
    merchant = Column(String)
    status = Column(String, default="completed")  # completed, flagged, rejected
    receipt_provided = Column(Boolean, default=False)

class Investigation(Base):
    __tablename__ = "investigations"
    id = Column(String, primary_key=True)  # transaction_id
    employee_id = Column(String, nullable=False)
    category = Column(String)
    amount = Column(Float)
    decision = Column(String)  # APPROVED, REJECTED, ESCALATED
    reasoning = Column(String)
    evidence_summary = Column(String)
    created_at = Column(DateTime, default=datetime.now)