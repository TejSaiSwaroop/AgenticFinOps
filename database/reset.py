# database/reset.py
from database.db import engine, SessionLocal
from database.models import Base
from database.seed import seed_data  # We'll move seeding into a function

def reset_database():
    # Drop all tables
    Base.metadata.drop_all(bind=engine)
    # Re-seed
    seed_data()
    print("Database wiped and reseeded successfully.")

if __name__ == "__main__":
    reset_database()