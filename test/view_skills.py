#!/usr/bin/env python3
import sys
import os
sys.path.append('.')

from database.db_connection import get_db_connection

def view_skills():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM skills')
    skills = cursor.fetchall()
    
    print('技能表结构:')
    cursor.execute('PRAGMA table_info(skills)')
    columns = cursor.fetchall()
    for col in columns:
        print(f"  {col[1]} ({col[2]})")
    
    print('\n所有技能:')
    for skill in skills:
        print(f"  ID:{skill[0]} - {skill[1]} - {skill[2]}")
        if len(skill) > 5:  # 有新字段
            print(f"    公式:{skill[5]} 冷却:{skill[4]} 效果:{skill[6]}")
    
    conn.close()

if __name__ == "__main__":
    view_skills()
