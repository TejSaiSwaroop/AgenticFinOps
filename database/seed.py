from database.models import Base, Transaction, Employee, ExpensePolicy, Investigation
from datetime import datetime, timedelta
from database.db import engine, SessionLocal


def seed_data():
    Base.metadata.create_all(bind=engine)  # creates tables if they don't exist
    session = SessionLocal()
    if session.query(Employee).count() == 0:
        session.add_all([
            Employee(id="E456", name="Alice", policy_limit=200.0, risk_tier="low", manager_slack_id="U123"),
            Employee(id="E789", name="Bob", policy_limit=500.0, risk_tier="medium", manager_slack_id="U456"),
            Employee(id="E135", name="raj", policy_limit=120.0, risk_tier="medium", manager_slack_id="U234"),
            # ... add other employees (including new columns if any)
        ])

    if session.query(ExpensePolicy).count() == 0:
        session.add_all([
            ExpensePolicy(category="Office Supplies", max_amount=150.0, requires_receipt=False, note="Standard supplies"),
            ExpensePolicy(category="Meals", max_amount=50.0, requires_receipt=True, note="Client meals require receipt"),
            ExpensePolicy(category="Travel", max_amount=1000.0, requires_receipt=True, note="Airfare and hotel"),
        ])

    if session.query(Transaction).count() == 0:
        session.add_all([
            Transaction(id="T100", employee_id="E456", date=datetime.now()-timedelta(days=30), category="Office Supplies", amount=120.00, merchant="Staples", status="completed"),
            Transaction(id="T101", employee_id="E456", date=datetime.now()-timedelta(days=25), category="Meals", amount=45.00, merchant="Chipotle", status="completed"),
            Transaction(id="T102", employee_id="E456", date=datetime.now()-timedelta(days=20), category="Office Supplies", amount=145.00, merchant="Office Depot", status="completed"),
            Transaction(id="T103", employee_id="E456", date=datetime.now()-timedelta(days=15), category="Office Supplies", amount=148.00, merchant="Amazon Business", status="completed"),
            Transaction(id="T104", employee_id="E456", date=datetime.now()-timedelta(days=10), category="Travel", amount=850.00, merchant="United Airlines", status="flagged"),
            Transaction(id="T105", employee_id="E456", date=datetime.now()-timedelta(days=5), category="Office Supplies", amount=147.00, merchant="Staples", status="completed"),
            Transaction(id="T106", employee_id="E789", date=datetime.now()-timedelta(days=3), category="Meals", amount=55.00, merchant="Steakhouse", status="completed"),
            Transaction(id="T107", employee_id="E789", date=datetime.now()-timedelta(days=2), category="Meals", amount=62.00, merchant="Seafood Place", status="completed"),
        ])
    session.commit()
    session.close()

if __name__ == "__main__":
    seed_data()
    print("Database seeded.")