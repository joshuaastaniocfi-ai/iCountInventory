#!/usr/bin/env python3
"""
Script to migrate data from inventory_old.db to inventory.db
Sets company_id to 1 for all records
"""

import sqlite3
import os

def migrate_data():
    """Migrate data from inventory_old.db to inventory.db"""
    
    # Define database paths
    instance_path = os.path.join(os.path.dirname(__file__), 'instance')
    old_db_path = os.path.join(instance_path, 'inventory_old.db')
    current_db_path = os.path.join(instance_path, 'inventory.db')
    
    # Check if databases exist
    if not os.path.exists(old_db_path):
        print(f"Old database not found at {old_db_path}")
        return False
        
    if not os.path.exists(current_db_path):
        print(f"Current database not found at {current_db_path}")
        return False
    
    # Connect to both databases
    old_conn = sqlite3.connect(old_db_path)
    current_conn = sqlite3.connect(current_db_path)
    old_cursor = old_conn.cursor()
    current_cursor = current_conn.cursor()
    
    try:
        # Get table names from old database
        old_cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
        old_tables = [table[0] for table in old_cursor.fetchall()]
        print(f"Tables in old database: {old_tables}")
        
        # Get table names from current database
        current_cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
        current_tables = [table[0] for table in current_cursor.fetchall()]
        print(f"Tables in current database: {current_tables}")
        
        # Process each table that exists in both databases
        for table_name in old_tables:
            if table_name in current_tables and table_name != 'sqlite_sequence':
                print(f"\nProcessing table: {table_name}")
                
                # Get column info for current table
                current_cursor.execute(f"PRAGMA table_info({table_name})")
                current_columns = [column[1] for column in current_cursor.fetchall()]
                print(f"Current table columns: {current_columns}")
                
                # Get data from old table
                old_cursor.execute(f"SELECT * FROM {table_name}")
                old_data = old_cursor.fetchall()
                
                if not old_data:
                    print(f"No data in {table_name} table in old database")
                    continue
                    
                # Get column info for old table
                old_cursor.execute(f"PRAGMA table_info({table_name})")
                old_columns = [column[1] for column in old_cursor.fetchall()]
                print(f"Old table columns: {old_columns}")
                
                # Clear current table data
                current_cursor.execute(f"DELETE FROM {table_name}")
                print(f"Cleared {current_cursor.rowcount} rows from {table_name}")
                
                # Prepare insert statement with company_id handling
                if 'company_id' in current_columns:
                    # For tables with company_id column, set it to 1
                    columns_to_insert = []
                    for col in current_columns:
                        if col == 'company_id':
                            columns_to_insert.append('1')
                        elif col in old_columns:
                            columns_to_insert.append(f":{col}")
                        else:
                            columns_to_insert.append('NULL')
                    
                    insert_sql = f"INSERT INTO {table_name} ({', '.join(current_columns)}) VALUES ({', '.join(columns_to_insert)})"
                    
                    # Insert data with company_id = 1
                    for row in old_data:
                        row_dict = dict(zip(old_columns, row))
                        try:
                            current_cursor.execute(insert_sql, row_dict)
                        except sqlite3.Error as e:
                            print(f"Error inserting row in {table_name}: {e}")
                            print(f"SQL: {insert_sql}")
                            print(f"Data: {row_dict}")
                else:
                    # For tables without company_id, insert normally
                    placeholders = ', '.join(['?' for _ in current_columns])
                    insert_sql = f"INSERT INTO {table_name} ({', '.join(current_columns)}) VALUES ({placeholders})"
                    
                    # Match columns and insert data
                    for row in old_data:
                        old_row_dict = dict(zip(old_columns, row))
                        new_row = []
                        for col in current_columns:
                            new_row.append(old_row_dict.get(col, None))
                        current_cursor.execute(insert_sql, new_row)
                
                print(f"Inserted {current_cursor.rowcount} rows into {table_name}")
        
        # Commit changes
        current_conn.commit()
        print("\nData migration completed successfully!")
        return True
        
    except Exception as e:
        print(f"Error during migration: {e}")
        current_conn.rollback()
        return False
    finally:
        old_conn.close()
        current_conn.close()

def main():
    print("Starting data migration from inventory_old.db to inventory.db...")
    print("Setting company_id to 1 for all records...")
    
    if migrate_data():
        print("\nMigration completed successfully!")
    else:
        print("\nMigration failed!")

if __name__ == "__main__":
    main()