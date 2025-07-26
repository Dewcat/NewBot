import sqlite3

conn = sqlite3.connect('data/simplebot.db')
cursor = conn.cursor()
cursor.execute('SELECT id, name, effects FROM skills WHERE effects != "{}" AND effects IS NOT NULL')
skills = cursor.fetchall()

print("当前技能的状态效果定义:")
for skill in skills:
    print(f'ID: {skill[0]}, Name: {skill[1]}, Effects: {skill[2]}')

conn.close()
