#!/usr/bin/env python3
"""
Script to transfer reorder level data from inventory_old.db to inventory.db
"""

import sqlite3
import os
from contextlib import contextmanager

# Get the absolute path to the instance directory
instance_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'instance')
old_db_path = os.path.join(instance_dir, 'inventory_old.db')
new_db_path = os.path.join(instance_dir, 'inventory.db')

@contextmanager
def get_db_connection(db_path):
    """Context manager for database connections"""
    conn = sqlite3.connect(db_path)
    try:
        yield conn
    finally:
        conn.close()

def transfer_reorder_levels():
    """Transfer reorder level data from old database to new database"""
    print("Starting reorder level data transfer...")
    print(f"Old database: {old_db_path}")
    print(f"New database: {new_db_path}")
    
    # Check if both databases exist
    if not os.path.exists(old_db_path):
        print(f"Error: Old database file not found at {old_db_path}")
        return False
        
    if not os.path.exists(new_db_path):
        print(f"Error: New database file not found at {new_db_path}")
        return False
    
    try:
        # Connect to both databases
        with get_db_connection(old_db_path) as old_conn, get_db_connection(new_db_path) as new_conn:
            old_cursor = old_conn.cursor()
            new_cursor = new_conn.cursor()
            
            # Check if product table exists in both databases
            old_cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='product';")
            if not old_cursor.fetchone():
                print("Error: 'product' table not found in old database")
                return False
                
            new_cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='product';")
            if not new_cursor.fetchone():
                print("Error: 'product' table not found in new database")
                return False
            
            # Get all products from old database with reorder_level data
            old_cursor.execute("SELECT id, reorder_level FROM product WHERE reorder_level IS NOT NULL;")
            old_products = old_cursor.fetchall()
            
            print(f"Found {len(old_products)} products with reorder level data in old database")
            
            if not old_products:
                print("No reorder level data found in old database")
                return True
            
            # Transfer reorder level data to new database
            updated_count = 0
            for product_id, reorder_level in old_products:
                # Update the reorder_level in the new database
                new_cursor.execute(
                    "UPDATE product SET reorder_level = ? WHERE id = ?;",
                    (reorder_level, product_id)
                )
                
                if new_cursor.rowcount > 0:
                    updated_count += 1
                else:
                    print(f"Warning: Product with ID {product_id} not found in new database")
            
            # Commit changes
            new_conn.commit()
            
            print(f"Successfully updated {updated_count} products with reorder level data")
            return True
            
    except Exception as e:
        print(f"Error during transfer: {str(e)}")
        return False

if __name__ == "__main__":
    success = transfer_reorder_levels()
    if success:
        print("Reorder level data transfer completed successfully!")
    else:
        print("Reorder level data transfer failed!")