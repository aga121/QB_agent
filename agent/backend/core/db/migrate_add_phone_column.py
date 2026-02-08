"""
数据库迁移脚本：为 users 表添加 phone 列
"""
import psycopg2
import sys
from ..system import config
from ..system.logging_setup import setup_logging

setup_logging()

def migrate_add_phone_column():
    """为 users 表添加 phone 列（如果不存在）"""
    try:
        conn = psycopg2.connect(
            host=config.POSTGRES_HOST,
            port=config.POSTGRES_PORT,
            database=config.POSTGRES_DB,
            user=config.POSTGRES_USER,
            password=config.POSTGRES_PASSWORD
        )
        conn.autocommit = False
        cursor = conn.cursor()

        # 检查 phone 列是否存在
        cursor.execute("""
            SELECT column_name
            FROM information_schema.columns
            WHERE table_name = 'users'
            AND column_name = 'phone'
        """)
        result = cursor.fetchone()

        if result:
            print("✅ users 表已有 phone 列，无需迁移")
        else:
            print("⚠️  users 表缺少 phone 列，开始添加...")

            # 添加 phone 列
            cursor.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS phone TEXT UNIQUE")

            # 创建索引
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_users_phone ON users(phone)")

            conn.commit()
            print("✅ 成功为 users 表添加 phone 列")

        # 显示表结构
        cursor.execute("""
            SELECT column_name, data_type, is_nullable
            FROM information_schema.columns
            WHERE table_name = 'users'
            ORDER BY ordinal_position
        """)
        print("\n📋 users 表结构:")
        for row in cursor.fetchall():
            print(f"  - {row[0]}: {row[1]} (nullable: {row[2]})")

        conn.close()
        print("\n✅ 迁移完成！")

    except Exception as e:
        print(f"❌ 迁移失败: {e}", file=sys.stderr)
        if 'conn' in locals():
            conn.rollback()
        sys.exit(1)

if __name__ == "__main__":
    migrate_add_phone_column()
