#!/usr/bin/env python3
"""
运行数据库迁移的脚本
"""

import sys
import os
import logging

# 设置日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# 添加项目根目录到路径
sys.path.append('.')

try:
    from database.db_migration import run_migrations
    print("开始运行数据库迁移...")
    run_migrations()
    print("数据库迁移完成！")
except Exception as e:
    print(f"迁移失败: {e}")
    import traceback
    traceback.print_exc()
