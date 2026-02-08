"""
数据库工具类
提供数据库的增删改查等基础操作
"""
import psycopg2
import psycopg2.extras
from psycopg2 import pool
import os
import sys
import uuid
from datetime import datetime
from typing import Optional, List, Dict, Any
from ..system import config


class PooledConnection:
    """
    连接池连接包装器
    拦截 close() 调用，将连接归还到连接池而不是真正关闭
    """
    def __init__(self, connection, pool_ref, return_callback):
        """
        Args:
            connection: 原始数据库连接
            pool_ref: 连接池引用
            return_callback: 归还连接的回调函数
        """
        self._connection = connection
        self._pool_ref = pool_ref
        self._return_callback = return_callback
        self._is_closed = False

    def close(self):
        """归还连接到连接池（而不是真正关闭）"""
        if not self._is_closed and self._connection:
            self._return_callback(self._connection)
            self._is_closed = True

    def __getattr__(self, name):
        """代理所有其他属性和方法到原始连接"""
        if name == 'close':
            return self.close
        return getattr(self._connection, name)

    def __enter__(self):
        """支持上下文管理器"""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """退出上下文时归还连接"""
        self.close()

    def cursor(self, cursor_factory=None):
        """创建游标，支持 cursor_factory 参数"""
        if cursor_factory:
            return self._connection.cursor(cursor_factory=cursor_factory)
        return self._connection.cursor()

    def rollback(self):
        """回滚事务"""
        if not self._is_closed:
            return self._connection.rollback()

    def commit(self):
        """提交事务"""
        if not self._is_closed:
            return self._connection.commit()


class DatabaseUtil:
    """数据库操作工具类"""

    # 类级别的连接池（所有实例共享）
    _connection_pool = None
    _pool_initialized = False

    def __init__(self):
        """初始化，确保数据库和连接池存在"""
        self._ensure_database()
        self._ensure_connection_pool()

    def _ensure_connection_pool(self):
        """确保连接池已初始化（线程安全）"""
        if not DatabaseUtil._pool_initialized:
            try:
                DatabaseUtil._connection_pool = pool.SimpleConnectionPool(
                    minconn=10,     # 最小连接数（支持100并发用户）
                    maxconn=50,     # 最大连接数（留有余量）
                    host=config.POSTGRES_HOST,
                    port=config.POSTGRES_PORT,
                    database=config.POSTGRES_DB,
                    user=config.POSTGRES_USER,
                    password=config.POSTGRES_PASSWORD
                )
                DatabaseUtil._pool_initialized = True
                print(f"[OK] 数据库连接池已初始化 (min: 10, max: 50) - 支持100+并发用户")
            except Exception as e:
                print(f"[ERROR] 连接池初始化失败: {e}", file=sys.stderr)
                raise

    def _get_connection(self):
        """从连接池获取数据库连接（内部方法）"""
        try:
            if not DatabaseUtil._connection_pool:
                raise Exception("连接池未初始化")
            raw_conn = DatabaseUtil._connection_pool.getconn()
            raw_conn.autocommit = False
            # 返回包装后的连接，close() 会自动归还到连接池
            return PooledConnection(
                connection=raw_conn,
                pool_ref=DatabaseUtil._connection_pool,
                return_callback=self._return_connection
            )
        except Exception as e:
            print(f"从连接池获取连接失败: {e}", file=sys.stderr)
            raise

    def _return_connection(self, conn):
        """归还连接到连接池"""
        try:
            if DatabaseUtil._connection_pool and conn:
                DatabaseUtil._connection_pool.putconn(conn)
        except Exception as e:
            print(f"归还连接失败: {e}", file=sys.stderr)

    def get_connection(self):
        """
        获取数据库连接（公共方法）
        返回的连接可以直接创建 RealDictCursor

        Returns:
            数据库连接对象

        Example:
            conn = db.get_connection()
            cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        """
        return self._get_connection()

    def _ensure_database(self):
        """确保数据库和表存在"""
        # 导入初始化模块
        from . import init_db
        init_db.check_and_init(verbose=False)  # 静默初始化，避免重复打印

    def execute_query(self, query: str, params: tuple = None, fetch: str = "all") -> Optional[Any]:
        """
        执行查询语句

        Args:
            query: SQL查询语句（使用 %s 作为占位符）
            params: 查询参数
            fetch: 获取结果的方式 ('all', 'one', None)

        Returns:
            查询结果
        """
        conn = self._get_connection()
        try:
            cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            if params:
                cursor.execute(query, params)
            else:
                cursor.execute(query)

            if fetch == "all":
                result = cursor.fetchall()
            elif fetch == "one":
                result = cursor.fetchone()
            else:
                result = None

            if query.strip().upper().startswith(('INSERT', 'UPDATE', 'DELETE')):
                conn.commit()

            return result
        except Exception as e:
            print(f"查询执行失败: {e}", file=sys.stderr)
            conn.rollback()
            raise
        finally:
            conn.close()  # 包装器会自动归还连接到连接池

    # ==================== 用户相关操作 ====================

    def create_user(self, username: str, password: str, email: str = None,
                    full_name: str = None, user_type: str = 'human', owner_id: str = None,
                    client_ip: str = None, server_ip: str = None, phone: str = None) -> str:
        """
        创建新用户

        Args:
            username: 用户名
            password: 密码
            email: 邮箱
            full_name: 全名
            user_type: 用户类型 ('human' 或 'ai')
            owner_id: 所有者ID (仅AI智能体需要)
            client_ip: 客户端IP地址
            server_ip: 服务器IP地址

        Returns:
            用户ID (UUID)
        """
        user_id = str(uuid.uuid4())
        query = '''
            INSERT INTO users (id, username, password, email, phone, full_name, user_type, owner_id, client_ip, server_ip)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        '''
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute(query, (user_id, username, password, email, phone, full_name, user_type, owner_id, client_ip, server_ip))
            conn.commit()
            return user_id
        except Exception as e:
            conn.rollback()
            raise
        finally:
            conn.close()  # 包装器会自动归还连接到连接池

    def get_user_by_username(self, username: str) -> Optional[Dict]:
        """根据用户名获取用户信息"""
        query = "SELECT * FROM users WHERE username = %s"
        result = self.execute_query(query, (username,), "one")
        return dict(result) if result else None

    def get_user_by_email(self, email: str) -> Optional[Dict]:
        """根据邮箱获取用户信息"""
        query = "SELECT * FROM users WHERE email = %s"
        result = self.execute_query(query, (email,), "one")
        return dict(result) if result else None

    def get_user_by_phone(self, phone: str) -> Optional[Dict]:
        """根据手机号获取用户信息"""
        query = "SELECT * FROM users WHERE phone = %s"
        result = self.execute_query(query, (phone,), "one")
        return dict(result) if result else None

    def get_user_by_id(self, user_id: int) -> Optional[Dict]:
        """根据用户ID获取用户信息"""
        query = "SELECT * FROM users WHERE id = %s"
        result = self.execute_query(query, (user_id,), "one")
        return dict(result) if result else None

    def get_all_users(self) -> List[Dict]:
        """获取所有用户"""
        query = "SELECT id, username, email, full_name, created_at FROM users ORDER BY created_at DESC"
        results = self.execute_query(query)
        return [dict(row) for row in results]

    def get_ai_agents_by_owner(self, owner_id: str) -> List[Dict]:
        """获取指定用户的所有AI智能体"""
        query = '''
            SELECT id, username, email, full_name, created_at
            FROM users
            WHERE user_type = 'ai' AND owner_id = %s
            ORDER BY created_at ASC
        '''
        results = self.execute_query(query, (owner_id,))
        return [dict(row) for row in results]

    def get_agent_settings(self, agent_id: str) -> Optional[Dict]:
        """获取AI智能体配置"""
        query = '''
            SELECT agent_id, system_prompt, work_dir, created_at, updated_at
            FROM agent_settings
            WHERE agent_id = %s
        '''
        result = self.execute_query(query, (agent_id,), "one")
        return dict(result) if result else None

    def upsert_agent_settings(
        self,
        agent_id: str,
        system_prompt: Optional[str] = None,
        work_dir: Optional[str] = None,
    ) -> None:
        """创建或更新AI智能体配置"""
        existing = self.get_agent_settings(agent_id) or {}
        prompt_value = system_prompt if system_prompt is not None else existing.get("system_prompt")
        work_dir_value = work_dir if work_dir is not None else existing.get("work_dir")

        query = '''
            INSERT INTO agent_settings (agent_id, system_prompt, work_dir, updated_at)
            VALUES (%s, %s, %s, CURRENT_TIMESTAMP)
            ON CONFLICT(agent_id) DO UPDATE SET
                system_prompt = excluded.system_prompt,
                work_dir = excluded.work_dir,
                updated_at = CURRENT_TIMESTAMP
        '''
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute(query, (agent_id, prompt_value, work_dir_value))
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()  # 包装器会自动归还连接到连接池

    def update_user(self, user_id: int, **kwargs) -> bool:
        """
        更新用户信息

        Args:
            user_id: 用户ID
            **kwargs: 要更新的字段

        Returns:
            是否更新成功
        """
        if not kwargs:
            return False

        # 添加更新时间
        kwargs['updated_at'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

        set_clause = ", ".join([f"{k} = %s" for k in kwargs.keys()])
        values = list(kwargs.values()) + [user_id]

        query = f"UPDATE users SET {set_clause} WHERE id = %s"

        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute(query, values)
            success = cursor.rowcount > 0
            conn.commit()
            return success
        except Exception as e:
            conn.rollback()
            raise
        finally:
            conn.close()  # 包装器会自动归还连接到连接池

    def delete_user(self, user_id: str) -> bool:
        """删除用户"""
        query = "DELETE FROM users WHERE id = %s"
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute(query, (user_id,))
            success = cursor.rowcount > 0
            conn.commit()
            return success
        except Exception as e:
            conn.rollback()
            raise
        finally:
            conn.close()  # 包装器会自动归还连接到连接池

    @staticmethod
    def close_all():
        """关闭所有连接池（应用关闭时调用）"""
        if DatabaseUtil._connection_pool:
            try:
                DatabaseUtil._connection_pool.closeall()
                print("[OK] 数据库连接池已关闭")
                DatabaseUtil._pool_initialized = False
            except Exception as e:
                print(f"[ERROR] 关闭连接池失败: {e}", file=sys.stderr)

    def close(self):
        """关闭数据库连接（由连接池管理）"""
        pass

# 测试代码
if __name__ == "__main__":
    # 测试数据库操作
    db = DatabaseUtil()

    print("测试用户操作...")
    # 创建测试用户
    try:
        user_id = db.create_user(
            username="testuser",
            password="123456",
            email="test@example.com",
            full_name="测试用户"
        )
        print(f"创建用户成功，ID: {user_id}")

        # 查询用户
        user = db.get_user_by_username("testuser")
        print(f"查询用户: {user}")

        # 查询所有用户
        users = db.get_all_users()
        print(f"所有用户数量: {len(users)}")

    except Exception as e:
        print(f"测试失败: {e}")
