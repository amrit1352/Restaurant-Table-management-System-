import sqlite3

def inspect():
    try:
        conn = sqlite3.connect('restaurant.db')
        cursor = conn.cursor()
        
        # Get all tables
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
        tables = [t[0] for t in cursor.fetchall()]
        
        print("=== Tables in restaurant.db ===")
        for table in tables:
            print(f"\nTable: {table}")
            # Get schema for each table
            cursor.execute(f"PRAGMA table_info({table});")
            columns = cursor.fetchall()
            for col in columns:
                print(f"  - {col[1]} ({col[2]})")
                
        conn.close()
    except Exception as e:
        print(f"Error reading database: {e}")

if __name__ == "__main__":
    inspect()
