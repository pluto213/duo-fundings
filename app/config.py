"""数据库配置"""

import os

# ==================== 数据库配置 ====================
# 本地开发默认用 SQLite，上 AWS 改成 PostgreSQL
# 方式1: 修改下面的默认值
# 方式2: 设置环境变量 DATABASE_URL

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    # PostgreSQL（本地）
    "postgresql://plutoy:abc123@localhost:5432/duo_fundings"
)

# ==================== SQLAlchemy 配置 ====================
# echo=True 会打印 SQL 语句，调试用
DB_ECHO = os.getenv("DB_ECHO", "false").lower() == "true"
