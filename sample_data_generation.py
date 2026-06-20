import random
from datetime import datetime, timedelta
from database.db import engine, SessionLocal
from database.models import Base, Employee, ExpensePolicy, Transaction

# Reset database
Base.metadata.drop_all(bind=engine)
Base.metadata.create_all(bind=engine)

session = SessionLocal()

# ---------- 1. Employees (20) ----------
departments = ["Engineering", "Sales", "Marketing", "Finance", "Operations"]
risk_levels = ["low", "medium", "high"]
names = ["Alice", "Babu", "Charlie", "Diana", "Eve", "Frank", "Grace", "Hank", "Ravi", "Jack", "Kate", "Leo", "Mona", "Nate", "Olivia", 
"Divya", "Quinn", "Rachel", "Sam", "Mahi"]

employees = []
for i, name in enumerate(names):
    dept = random.choice(departments)
    if i in [5, 11, 19]: 
        tier = "high"
    elif i in [2, 8, 15, 17, 4]:
        tier = "medium"
    else:
        tier = "low"
    limit = random.choice([250, 600, 800, 1200, 1000])
    emp = Employee(
        id=f"E{i+100:03d}",
        name=name,
        department=dept,
        policy_limit=limit,
        risk_tier=tier,
        manager_slack_id=f"U{random.randint(100,999)}"
    )
    employees.append(emp)
    session.add(emp)

# ---------- 2. Policies (7 categories) ----------
categories = ["Office Supplies", "Meals", "Travel", "Software", "Hardware", "Marketing", "Other"]
policies = []
for cat in categories:
    if cat == "Travel":
        max_amt = 1500.0
        receipt = True
    elif cat == "Hardware":
        max_amt = 500.0
        receipt = True
    elif cat == "Software":
        max_amt = 350.0
        receipt = False
    elif cat == "Meals":
        max_amt = 50.0
        receipt = True
    elif cat == "Office Supplies":
        max_amt = 650.0
        receipt = False
    elif cat == "Marketing":
        max_amt = 600.0
        receipt = True
    else:
        max_amt = 200.0
        receipt = False
    pol = ExpensePolicy(category=cat, max_amount=max_amt, requires_receipt=receipt, note=f"Standard {cat} policy")
    policies.append(pol)
    session.add(pol)

session.commit()

# ---------- 3. Transactions (1200 rows over 15 months) ----------
merchants = {
    "Office Supplies": ["Staples", "Office Depot", "Amazon Business", "Best Buy"],
    "Meals": ["Chipotle", "Steakhouse", "Seafood Place", "Local Cafe"],
    "Travel": ["United Airlines", "Marriott", "Airbnb", "Uber"],
    "Software": ["Adobe", "Slack", "GitHub", "Atlassian"],
    "Hardware": ["Dell", "Apple", "Lenovo", "Newegg"],
    "Marketing": ["Facebook Ads", "Google Ads", "Billboard Inc", "Mailchimp"],
    "Other": ["Uber Eats", "FedEx", "WeWork", "Staples"]
}

start_date = datetime.now() - timedelta(days=457)  # 15 months ago
cancelled_ids = []

for i in range(1200):
    emp = random.choice(employees)
    cat = random.choice(categories)
    # Realistic amount distribution
    if cat == "Travel":
        amt = round(random.uniform(200, 1600), 2)
    elif cat == "Meals":
        amt = round(random.uniform(8, 80), 2)
    elif cat == "Office Supplies":
        amt = round(random.uniform(10, 702), 2)
    elif cat == "Software":
        amt = round(random.uniform(20, 360), 2)
    elif cat == "Hardware":
        amt = round(random.uniform(50, 600), 2)
    elif cat == "Marketing":
        amt = round(random.uniform(100, 900), 2)
    else:
        amt = round(random.uniform(5, 300), 2)
    
    # Random date within last 15 months
    days_ago = random.randint(0, 457)
    txn_date = start_date + timedelta(days=days_ago)
    
    merchant = random.choice(merchants[cat])
    
    # Flagging logic (approx 5-8% flagged)
    is_cancelled = False
    pol_max = policies[categories.index(cat)].max_amount
    if emp.risk_tier == "high" and random.random() < 0.05:
        is_cancelled = True
    elif amt > pol_max * 1.2:
        is_cancelled = True
    elif random.random() < 0.02:
        is_cancelled = True
    
    txn = Transaction(
        id=f"T{i+1000:04d}",
        employee_id=emp.id,
        date=txn_date,
        category=cat,
        amount=amt,
        merchant=merchant,
        status="cancelled" if is_cancelled else "completed",
        receipt_provided=random.choice([True, False])
    )
    session.add(txn)
    if is_cancelled:
        cancelled_ids.append(txn.id)

session.commit()
session.close()

print(f"✅ Generated {len(employees)} employees, {len(categories)} policies, 1200 transactions.")
print(f"🚩 cancelled transactions: {len(cancelled_ids)}")