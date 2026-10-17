import sqlite3

def run_query():
    try:
        import os
        db_path = os.path.join(os.path.dirname(__file__), 'restaurant.db')
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        query = """
        SELECT order_items.order_id, menu.item_name, menu.price, order_items.quantity
        FROM order_items
        JOIN menu ON order_items.item_id = menu.item_id;
        """
        
        cursor.execute(query)
        rows = cursor.fetchall()
        
        print(f"\n{'order_id':<10} | {'item_name':<25} | {'price':<10} | {'quantity':<10}")
        print("-" * 65)
        
        for row in rows:
            print(f"{str(row[0]):<10} | {str(row[1]):<25} | {str(row[2]):<10} | {str(row[3]):<10}")
            
        conn.close()
    except Exception as e:
        print(f"Error reading database: {e}")

if __name__ == "__main__":
    run_query()
