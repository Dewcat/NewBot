#!/usr/bin/env python3
import sys
import os
sys.path.append('.')

from database.db_connection import get_db_connection

conn = get_db_connection()
cursor = conn.cursor()
cursor.execute('SELECT name, health, max_health, attack, defense FROM characters ORDER BY id DESC LIMIT 5')
print('最近的角色数据:')
for row in cursor.fetchall():
    print(f'{row[0]}: health={row[1]}, max_health={row[2]}, attack={row[3]}, defense={row[4]}')
conn.close()
