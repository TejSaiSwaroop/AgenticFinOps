from database.db import engine
from sqlalchemy import text
import json

def run_sql_query(query: str):
    """Executes a raw SQL query and prints results."""
    try: 
        with engine.connect() as conn:
            result = conn.execute(text(query))
            # Fetch all rows
            rows = result.fetchall()
            # Convert each row to a dictionary
            columns = result.keys()  # column names
            data = [dict(zip(columns, row)) for row in rows]
            return data

    except Exception as e:
        return json.dumps(str(e))
