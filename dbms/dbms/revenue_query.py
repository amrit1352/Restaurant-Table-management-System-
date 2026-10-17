import sqlite3
import os

def check_revenue():
    try:
        db_path = os.path.join(os.path.dirname(__file__), 'restaurant.db')
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        query = "SELECT COALESCE(SUM(total_amount), 0) AS total_revenue FROM orders WHERE status = 'Paid';"
        cursor.execute(query)
        result = cursor.fetchone()[0]
        
        print(f"\n======================================")
        print(f"Total Revenue from Paid Orders: ₹{result}")
        print(f"======================================\n")
        
        conn.close()
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    check_revenue()
