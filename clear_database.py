#!/usr/bin/env python3
"""
清空数据库中的角色和技能数据
"""
import sys
import os

# 添加src目录到路径
sys.path.append(os.path.join(os.path.dirname(__file__), 'src'))

from database.db_connection import get_db_connection
import logging

# 设置日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def clear_database():
    """清空数据库中的角色和技能数据"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # 显示清空前的数据统计
        cursor.execute("SELECT COUNT(*) FROM characters")
        char_count = cursor.fetchone()[0]
        logger.info(f"清空前角色数量: {char_count}")
        
        cursor.execute("SELECT COUNT(*) FROM skills")
        skill_count = cursor.fetchone()[0]
        logger.info(f"清空前技能数量: {skill_count}")
        
        # 清空相关表的数据
        tables_to_clear = [
            'character_status_effects',  # 角色状态效果
            'character_emotion_effects', # 角色情感效果
            'emotion_level_history',     # 情感等级历史
            'emotion_coin_log',          # 情感硬币日志
            'character_skills',          # 角色技能关联
            'characters',                # 角色
            'skills'                     # 技能
        ]
        
        for table in tables_to_clear:
            try:
                cursor.execute(f"SELECT COUNT(*) FROM {table}")
                count = cursor.fetchone()[0]
                if count > 0:
                    cursor.execute(f"DELETE FROM {table}")
                    logger.info(f"✓ 已清空表 {table}，删除了 {count} 条记录")
                else:
                    logger.info(f"✓ 表 {table} 已经为空")
            except Exception as e:
                logger.warning(f"清空表 {table} 时出错: {e}")
        
        # 重置自增ID
        reset_tables = [
            'characters',
            'skills', 
            'character_status_effects',
            'character_emotion_effects',
            'emotion_level_history',
            'emotion_coin_log',
            'character_skills'
        ]
        
        for table in reset_tables:
            try:
                cursor.execute(f"DELETE FROM sqlite_sequence WHERE name='{table}'")
                logger.info(f"✓ 已重置表 {table} 的自增ID")
            except Exception as e:
                logger.warning(f"重置表 {table} 自增ID时出错: {e}")
        
        # 提交更改
        conn.commit()
        
        # 显示清空后的统计
        cursor.execute("SELECT COUNT(*) FROM characters")
        char_count_after = cursor.fetchone()[0]
        logger.info(f"清空后角色数量: {char_count_after}")
        
        cursor.execute("SELECT COUNT(*) FROM skills")
        skill_count_after = cursor.fetchone()[0]
        logger.info(f"清空后技能数量: {skill_count_after}")
        
        conn.close()
        logger.info("🎉 数据库清空完成！")
        
    except Exception as e:
        logger.error(f"清空数据库时出错: {e}")
        if 'conn' in locals():
            conn.rollback()
            conn.close()
        raise

if __name__ == "__main__":
    print("⚠️  警告：此操作将清空数据库中的所有角色和技能数据！")
    confirm = input("确认继续吗？输入 'YES' 确认: ")
    
    if confirm == 'YES':
        clear_database()
    else:
        print("操作已取消。")
