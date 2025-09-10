"""
添加角色行动次数系统

该迁移添加：
1. actions_per_turn: 每回合可行动次数（默认1）
2. current_actions: 当前剩余行动次数（默认等于actions_per_turn）
"""

def upgrade(connection):
    cursor = connection.cursor()
    
    # 添加行动次数字段
    cursor.execute("""
        ALTER TABLE characters 
        ADD COLUMN actions_per_turn INTEGER DEFAULT 1
    """)
    
    cursor.execute("""
        ALTER TABLE characters 
        ADD COLUMN current_actions INTEGER DEFAULT 1
    """)
    
    # 为现有角色设置默认值
    cursor.execute("""
        UPDATE characters 
        SET actions_per_turn = 1, current_actions = 1 
        WHERE actions_per_turn IS NULL OR current_actions IS NULL
    """)
    
    connection.commit()
    print("✅ 已添加角色行动次数系统")

def downgrade(connection):
    cursor = connection.cursor()
    
    # 删除行动次数字段
    cursor.execute("ALTER TABLE characters DROP COLUMN actions_per_turn")
    cursor.execute("ALTER TABLE characters DROP COLUMN current_actions")
    
    connection.commit()
    print("✅ 已移除角色行动次数系统")
