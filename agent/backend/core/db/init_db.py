"""
数据库初始化脚本
负责创建数据库和表结构
"""
import psycopg2
import psycopg2.extras
import os
import sys
import uuid
from datetime import datetime
from ..system import config
from ..system.logging_setup import setup_logging

setup_logging()

def create_connection():
    """创建数据库连接"""
    try:
        conn = psycopg2.connect(
            host=config.POSTGRES_HOST,
            port=config.POSTGRES_PORT,
            database=config.POSTGRES_DB,
            user=config.POSTGRES_USER,
            password=config.POSTGRES_PASSWORD
        )
        conn.autocommit = False
        return conn
    except Exception as e:
        print(f"创建数据库连接失败: {e}", file=sys.stderr)
        sys.exit(1)

def create_users_table(cursor):
    """创建用户表"""
    # 创建用户表
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id TEXT PRIMARY KEY,  -- 使用UUID作为主键
            username TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            email TEXT UNIQUE,
            phone TEXT UNIQUE,
            full_name TEXT,
            avatar_url TEXT,
            is_active BOOLEAN DEFAULT TRUE,
            user_type TEXT DEFAULT 'human' CHECK (user_type IN ('human', 'ai')),
            owner_id TEXT,
            client_ip TEXT,  -- 客户端IP地址（浏览器访问的IP）
            server_ip TEXT,  -- 服务器IP地址
            agent_status TEXT DEFAULT '离线',  -- 智能体状态：'空闲', '繁忙', '离线', '销毁'
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (owner_id) REFERENCES users (id)
        )
    ''')

    # 创建用户索引
    cursor.execute('''
        CREATE INDEX IF NOT EXISTS idx_users_username ON users(username)
    ''')
    cursor.execute('''
        CREATE INDEX IF NOT EXISTS idx_users_email ON users(email)
    ''')
    cursor.execute('''
        CREATE INDEX IF NOT EXISTS idx_users_phone ON users(phone)
    ''')
    cursor.execute('''
        CREATE INDEX IF NOT EXISTS idx_users_owner_id ON users(owner_id)
    ''')
    cursor.execute('''
        CREATE INDEX IF NOT EXISTS idx_users_type ON users(user_type)
    ''')
    cursor.execute('''
        CREATE INDEX IF NOT EXISTS idx_users_client_ip ON users(client_ip)
    ''')
    cursor.execute('''
        CREATE INDEX IF NOT EXISTS idx_users_server_ip ON users(server_ip)
    ''')

    print("✅ 用户表创建完成")

def create_sms_verification_codes_table(cursor):
    """创建短信验证码表（单表设计）"""
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS sms_verification_codes (
            id TEXT PRIMARY KEY,
            phone TEXT NOT NULL,
            code TEXT NOT NULL,
            expires_at TIMESTAMP NOT NULL,
            sent_at TIMESTAMP NOT NULL,
            verified BOOLEAN DEFAULT FALSE,
            verified_at TIMESTAMP,
            client_ip TEXT,
            user_agent TEXT,
            fingerprint TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    # 创建索引
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_sms_codes_phone ON sms_verification_codes(phone)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_sms_codes_expires_at ON sms_verification_codes(expires_at)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_sms_codes_sent_at ON sms_verification_codes(sent_at)')
    print("✅ 短信验证码表创建完成")

def create_sub_pro_table(cursor):
    """创建会员订阅表"""
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS sub_pro (
            id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL UNIQUE,
            phone TEXT NOT NULL,
            membership_type TEXT,  -- 'monthly', 'quarterly', 'yearly'
            membership_level TEXT DEFAULT 'pro',  -- 'lite', 'pro', 'max'
            start_date TIMESTAMP NOT NULL,
            end_date TIMESTAMP NOT NULL,
            is_active BOOLEAN DEFAULT TRUE,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users (id)
        )
    ''')
    # 创建索引
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_sub_pro_user_id ON sub_pro(user_id)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_sub_pro_phone ON sub_pro(phone)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_sub_pro_end_date ON sub_pro(end_date)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_sub_pro_is_active ON sub_pro(is_active)')
    print("✅ 会员订阅表创建完成")

def create_user_set_table(cursor):
    """创建用户设置表"""
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS user_set (
            id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL UNIQUE,
            port_start INT NOT NULL,
            port_end INT NOT NULL,
            storage_quota_bytes BIGINT NOT NULL,
            settings JSONB DEFAULT '{}'::jsonb,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users (id)
        )
    ''')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_user_set_user_id ON user_set(user_id)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_user_set_port_range ON user_set(port_start, port_end)')
    print("✅ 用户设置表创建完成")

def create_quota_usage_table(cursor):
    """创建配额使用记录表"""
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS quota_usage (
            id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            window_start TIMESTAMP NOT NULL,
            message_count INT DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(user_id, window_start)
        )
    ''')
    # 创建索引
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_quota_usage_user_time ON quota_usage(user_id, window_start)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_quota_usage_window_start ON quota_usage(window_start)')
    print("✅ 配额使用记录表创建完成")

def create_api_keys_table(cursor):
    """创建模型 API Key 配置表"""
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS api_keys (
            id TEXT PRIMARY KEY,
            membership_type TEXT NOT NULL DEFAULT 'no' CHECK (membership_type IN ('no', 'lite', 'pro', 'max', 'all')),
            base_url TEXT NOT NULL,
            auth_token TEXT NOT NULL,
            description TEXT,
            model_name TEXT,
            priority INT DEFAULT 0,
            status TEXT DEFAULT 'active',
            error TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_api_keys_membership ON api_keys(membership_type)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_api_keys_status ON api_keys(status)')
    print("✅ 模型 API Key 表创建完成")

def seed_api_keys(cursor):
    """初始化默认 API Key 数据"""
    cursor.execute(
        f'''
        INSERT INTO api_keys
        (id, membership_type, base_url, auth_token, description, model_name, priority, status, error, created_at, updated_at)
        VALUES
        ('cbecfc5c-6417-4f02-b551-713377ff1b64', 'pro', 'https://open.bigmodel.cn/api/anthropic', '{config.LLM_KEY}', 'main key', 'glm', 5, 'active', NULL, '2026-01-06 21:34:38.148', '2026-01-06 21:34:38.148'),
        ('cbecfc5c-6417-4f02-b551-713377ff1b68', 'max', 'https://open.bigmodel.cn/api/anthropic', '{config.LLM_KEY}', 'main key', 'glm', 5, 'active', NULL, '2026-01-06 21:34:38.148', '2026-01-06 21:34:38.148'),
        ('cbecfc5c-6417-4f02-b551-713377ff1b69', 'max', 'https://open.bigmodel.cn/api/anthropic', '{config.LLM_KEY}', 'main key', 'glm', 5, 'active', NULL, '2026-01-06 21:34:38.148', '2026-01-06 21:34:38.148'),
        ('cbecfc5c-6417-4f02-b551-713377ff1b67', 'no', 'https://open.bigmodel.cn/api/anthropic', '{config.LLM_KEY}', 'main key', 'glm', 5, 'active', NULL, '2026-01-06 21:34:38.148', '2026-01-06 21:34:38.148'),
        ('cbecfc5c-6417-4f02-b551-713377ff1b65', 'pro', 'https://open.bigmodel.cn/api/anthropic', '{config.LLM_KEY}', 'main key', 'glm', 5, 'active', NULL, '2026-01-06 21:34:38.148', '2026-01-06 21:34:38.148'),
        ('cbecfc5c-6417-4f02-b551-713377ff1b66', 'no', 'https://open.bigmodel.cn/api/anthropic', '{config.LLM_KEY}', 'main key', 'glm', 6, 'active', NULL, '2026-01-06 21:34:38.148', '2026-01-06 21:34:38.148')
        ON CONFLICT (id) DO NOTHING
        '''
    )

def init_database():
    """
    初始化数据库和所有表
    每次启动时都会检查并创建需要的表
    """
    try:
        conn = create_connection()
        cursor = conn.cursor()

        # 创建所有表
        create_users_table(cursor)
        create_friendship_table(cursor)
        create_chat_sessions_table(cursor)
        create_chat_messages_table(cursor)
        create_agent_settings_table(cursor)
        create_skills_table(cursor)
        create_skill_reactions_table(cursor)
        create_skill_categories_table(cursor)
        create_skill_installs_table(cursor)
        create_prompt_templates_table(cursor)
        create_memory_units_table(cursor)
        create_mcps_table(cursor)
        create_sms_verification_codes_table(cursor)
        create_user_set_table(cursor)
        create_api_keys_table(cursor)
        seed_api_keys(cursor)

        # 提交所有更改
        conn.commit()

        # 打印数据库信息
        print(f"数据库初始化成功: PostgreSQL@{config.POSTGRES_HOST}:{config.POSTGRES_PORT}/{config.POSTGRES_DB}")

        # 显示表信息
        cursor.execute("""
            SELECT table_name
            FROM information_schema.tables
            WHERE table_schema = 'public'
            AND table_type = 'BASE TABLE'
        """)
        tables = cursor.fetchall()
        print(f"已创建的表: {[t[0] for t in tables]}")

    except Exception as e:
        print(f"数据库初始化失败: {e}", file=sys.stderr)
        if 'conn' in locals():
            conn.rollback()
        sys.exit(1)
    finally:
        if 'conn' in locals():
            conn.close()

# 添加一个标志避免重复初始化
_initialized = False

def check_tables_exist(conn):
    """
    检查所有必需的表是否存在

    Args:
        conn: 数据库连接对象

    Returns:
        list: 缺失的表名列表
    """
    cursor = conn.cursor()

    # 查询所有存在的表（PostgreSQL）
    cursor.execute("""
        SELECT table_name
        FROM information_schema.tables
        WHERE table_schema = 'public'
        AND table_type = 'BASE TABLE'
    """)
    existing_tables = {row[0] for row in cursor.fetchall()}

    # 定义必需的表
    required_tables = {
        'users',
        'friendships',
        'chat_sessions',
        'chat_messages',
        'agent_settings',
        'skills',
        'skill_reactions',
        'skill_categories',
        'skill_installs',
        'prompt_templates',
        'memory_units',
        'mcps',
        'sms_verification_codes',
        'sub_pro',
        'user_set',
        'quota_usage',
        'api_keys',
        'task_custom_mcp',
    }

    # 找出缺失的表
    missing_tables = required_tables - existing_tables

    return list(missing_tables)

def check_and_init(verbose=True):
    """
    检查数据库和表是否存在，如果不存在则初始化

    Args:
        verbose: 是否打印详细信息
    """
    global _initialized

    # 如果已经初始化过，且不需要详细信息，直接返回
    if _initialized and not verbose:
        return

    # 尝试连接数据库并检查表
    try:
        conn = create_connection()
        missing_tables = check_tables_exist(conn)

        if missing_tables:
            if verbose:
                print(f"数据库存在，但缺少表: {missing_tables}")
                print("开始创建缺失的表...")

            cursor = conn.cursor()

            # 根据缺失的表创建对应的表
            if 'users' in missing_tables:
                create_users_table(cursor)
            if 'friendships' in missing_tables:
                create_friendship_table(cursor)
            if 'chat_sessions' in missing_tables:
                create_chat_sessions_table(cursor)
            if 'chat_messages' in missing_tables:
                create_chat_messages_table(cursor)
            if 'agent_settings' in missing_tables:
                create_agent_settings_table(cursor)
            if 'skills' in missing_tables:
                create_skills_table(cursor)
            if 'skill_reactions' in missing_tables:
                create_skill_reactions_table(cursor)
            if 'skill_categories' in missing_tables:
                create_skill_categories_table(cursor)
            if 'skill_installs' in missing_tables:
                create_skill_installs_table(cursor)
            if 'prompt_templates' in missing_tables:
                create_prompt_templates_table(cursor)
            if 'memory_units' in missing_tables:
                create_memory_units_table(cursor)
            if 'mcps' in missing_tables:
                create_mcps_table(cursor)
            if 'sms_verification_codes' in missing_tables:
                create_sms_verification_codes_table(cursor)
            if 'sub_pro' in missing_tables:
                create_sub_pro_table(cursor)
            if 'user_set' in missing_tables:
                create_user_set_table(cursor)
            if 'quota_usage' in missing_tables:
                create_quota_usage_table(cursor)
            if 'api_keys' in missing_tables:
                create_api_keys_table(cursor)
                seed_api_keys(cursor)
            if 'task_custom_mcp' in missing_tables:
                create_task_custom_mcp_table(cursor)

            conn.commit()

            if verbose:
                print("✅ 所有缺失的表已创建完成")
        else:
            if verbose:
                print(f"数据库已连接: PostgreSQL@{config.POSTGRES_HOST}:{config.POSTGRES_PORT}/{config.POSTGRES_DB}")
                print("所有必需的表都已存在")

        _initialized = True
        conn.close()

    except Exception as e:
        print(f"数据库连接或检查失败: {e}", file=sys.stderr)
        print(f"请确认 PostgreSQL 容器正在运行:")
        print(f"  docker run -d --name pgsql-container-5618 -p 5618:5432 \\")
        print(f"    -e POSTGRES_PASSWORD=844700 \\")
        print(f"    -e POSTGRES_USER=root \\")
        print(f"    -e POSTGRES_DB=queen \\")
        print(f"    postgres:16")
        sys.exit(1)

def create_friendship_table(cursor):
    """创建好友关系表"""
    # 创建好友关系表
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS friendships (
            id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            friend_id TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'accepted', 'blocked')),
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users (id),
            FOREIGN KEY (friend_id) REFERENCES users (id),
            UNIQUE(user_id, friend_id)
        )
    ''')

    # 创建好友关系索引
    cursor.execute('''
        CREATE INDEX IF NOT EXISTS idx_friendships_user_id ON friendships(user_id)
    ''')
    cursor.execute('''
        CREATE INDEX IF NOT EXISTS idx_friendships_friend_id ON friendships(friend_id)
    ''')
    cursor.execute('''
        CREATE INDEX IF NOT EXISTS idx_friendships_status ON friendships(status)
    ''')

    print("✅ 好友关系表创建完成")

def create_chat_sessions_table(cursor):
    """创建聊天会话表"""
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS chat_sessions (
            id TEXT PRIMARY KEY,  -- 会话ID
            user_id TEXT NOT NULL,  -- 发起会话的用户ID
            ai_agent_id TEXT NOT NULL,  -- AI智能体ID
            title TEXT,  -- 会话标题（可选）
            session_claude_id TEXT,  -- Claude SDK的会话ID
            is_active BOOLEAN DEFAULT TRUE,  -- 会话是否活跃
            last_message_at TIMESTAMP,  -- 最后一条消息时间
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users (id),
            FOREIGN KEY (ai_agent_id) REFERENCES users (id)
        )
    ''')

    # 创建索引
    cursor.execute('''
        CREATE INDEX IF NOT EXISTS idx_chat_sessions_user_id ON chat_sessions(user_id)
    ''')
    cursor.execute('''
        CREATE INDEX IF NOT EXISTS idx_chat_sessions_ai_agent_id ON chat_sessions(ai_agent_id)
    ''')
    cursor.execute('''
        CREATE INDEX IF NOT EXISTS idx_chat_sessions_is_active ON chat_sessions(is_active)
    ''')
    cursor.execute('''
        CREATE INDEX IF NOT EXISTS idx_chat_sessions_last_message_at ON chat_sessions(last_message_at)
    ''')

    print("✅ 聊天会话表创建完成")

def create_chat_messages_table(cursor):
    """创建聊天消息表"""
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS chat_messages (
            id TEXT PRIMARY KEY,
            session_id TEXT NOT NULL,
            sequence_number INTEGER NOT NULL,  -- 消息序号
            sender_id TEXT NOT NULL,  -- 发送者ID（用户或AI）
            sender_type TEXT NOT NULL CHECK (sender_type IN ('human', 'ai')),
            content TEXT NOT NULL,
            message_type TEXT DEFAULT 'text' CHECK (message_type IN ('text', 'image', 'file')),
            metadata TEXT,  -- 额外的元数据（JSON格式）
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (session_id) REFERENCES chat_sessions (id),
            FOREIGN KEY (sender_id) REFERENCES users (id)
        )
    ''')

    # 创建索引
    cursor.execute('''
        CREATE INDEX IF NOT EXISTS idx_chat_messages_session_id ON chat_messages(session_id)
    ''')
    cursor.execute('''
        CREATE INDEX IF NOT EXISTS idx_chat_messages_sender_id ON chat_messages(sender_id)
    ''')
    cursor.execute('''
        CREATE INDEX IF NOT EXISTS idx_chat_messages_sender_type ON chat_messages(sender_type)
    ''')
    cursor.execute('''
        CREATE INDEX IF NOT EXISTS idx_chat_messages_created_at ON chat_messages(created_at)
    ''')
    cursor.execute('''
        CREATE INDEX IF NOT EXISTS idx_chat_messages_session_sequence ON chat_messages(session_id, sequence_number)
    ''')

    print("✅ 聊天消息表创建完成")


def create_skills_table(cursor):
    """创建技能表"""
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS skills (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            description TEXT,
            content TEXT,
            skill_path TEXT,
            public_path TEXT,
            category TEXT,
            images_json TEXT,
            like_count INTEGER DEFAULT 0,
            dislike_count INTEGER DEFAULT 0,
            author_id TEXT NOT NULL,
            agent_id TEXT,
            session_id TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (author_id) REFERENCES users (id)
        )
    ''')
    cursor.execute('''
        CREATE INDEX IF NOT EXISTS idx_skills_author_id ON skills(author_id)
    ''')
    cursor.execute('''
        CREATE INDEX IF NOT EXISTS idx_skills_created_at ON skills(created_at)
    ''')
    print("✅ 技能表创建完成")


def create_skill_reactions_table(cursor):
    """创建技能点赞点踩表"""
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS skill_reactions (
            id TEXT PRIMARY KEY,
            skill_id TEXT NOT NULL,
            user_id TEXT NOT NULL,
            action TEXT NOT NULL CHECK (action IN ('like', 'dislike')),
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(skill_id, user_id),
            FOREIGN KEY (skill_id) REFERENCES skills (id),
            FOREIGN KEY (user_id) REFERENCES users (id)
        )
    ''')
    cursor.execute('''
        CREATE INDEX IF NOT EXISTS idx_skill_reactions_skill ON skill_reactions(skill_id)
    ''')
    cursor.execute('''
        CREATE INDEX IF NOT EXISTS idx_skill_reactions_user ON skill_reactions(user_id)
    ''')
    print("✅ 技能点赞点踩表创建完成")

def create_skill_categories_table(cursor):
    """创建技能分类表"""
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS skill_categories (
            id TEXT PRIMARY KEY,
            name TEXT UNIQUE NOT NULL
        )
    ''')
    cursor.execute('''
        CREATE INDEX IF NOT EXISTS idx_skill_categories_name ON skill_categories(name)
    ''')
    # 从配置文件读取默认分类
    default_categories = config.DEFAULT_SKILL_CATEGORIES
    for name in default_categories:
        cursor.execute(
            "INSERT INTO skill_categories (id, name) VALUES (%s, %s) ON CONFLICT (name) DO NOTHING",
            (str(uuid.uuid4()), name),
        )
    print("✅ 技能分类表创建完成")


def create_skill_installs_table(cursor):
    """创建技能安装映射表"""
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS skill_installs (
            id TEXT PRIMARY KEY,
            skill_id TEXT NOT NULL,
            agent_id TEXT NOT NULL,
            user_id TEXT NOT NULL,
            installed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(skill_id, agent_id, user_id),
            FOREIGN KEY (skill_id) REFERENCES skills (id),
            FOREIGN KEY (user_id) REFERENCES users (id)
        )
    ''')
    cursor.execute('''
        CREATE INDEX IF NOT EXISTS idx_skill_installs_agent ON skill_installs(agent_id)
    ''')
    cursor.execute('''
        CREATE INDEX IF NOT EXISTS idx_skill_installs_user ON skill_installs(user_id)
    ''')
    cursor.execute('''
        CREATE INDEX IF NOT EXISTS idx_skill_installs_skill ON skill_installs(skill_id)
    ''')
    print("✅ 技能安装映射表创建完成")


def create_prompt_templates_table(cursor):
    """创建提示词模板表"""
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS prompt_templates (
            id TEXT PRIMARY KEY,
            owner_id TEXT,
            name TEXT NOT NULL,
            content TEXT NOT NULL,
            tags TEXT,
            is_official BOOLEAN DEFAULT FALSE,
            usage_count INTEGER DEFAULT 0,
            like_count INTEGER DEFAULT 0,
            dislike_count INTEGER DEFAULT 0,
            last_used_at TIMESTAMP,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (owner_id) REFERENCES users (id)
        )
    ''')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_prompt_templates_owner_id ON prompt_templates(owner_id)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_prompt_templates_official ON prompt_templates(is_official)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_prompt_templates_usage ON prompt_templates(usage_count)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_prompt_templates_last_used ON prompt_templates(last_used_at)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_prompt_templates_created_at ON prompt_templates(created_at)')
    print("✅ 提示词模板表创建完成")


def create_memory_units_table(cursor):
    """创建知识库记忆表"""
    cursor.execute('''
        CREATE EXTENSION IF NOT EXISTS vector
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS memory_units (
            id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            memory_type TEXT NOT NULL,
            title TEXT,
            content TEXT NOT NULL,
            content_tsv tsvector,
            embedding vector(512),
            status SMALLINT DEFAULT 1,
            is_public SMALLINT DEFAULT 0,
            created_at TIMESTAMPTZ DEFAULT now(),
            updated_at TIMESTAMPTZ DEFAULT now(),
            FOREIGN KEY (user_id) REFERENCES users (id)
        )
    ''')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_memory_units_user_id ON memory_units(user_id)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_memory_units_status ON memory_units(status)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_memory_units_public ON memory_units(is_public)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_memory_units_tsv ON memory_units USING GIN (content_tsv)')
    cursor.execute('''
        CREATE INDEX IF NOT EXISTS idx_memory_units_embedding
        ON memory_units USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100)
    ''')
    cursor.execute('''
        CREATE OR REPLACE FUNCTION memory_units_tsv_trigger() RETURNS trigger AS $$
        BEGIN
            NEW.content_tsv := to_tsvector('simple', coalesce(NEW.title, '') || ' ' || coalesce(NEW.content, ''));
            NEW.updated_at := now();
            RETURN NEW;
        END
        $$ LANGUAGE plpgsql;
    ''')
    cursor.execute('''
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'trg_memory_units_tsv') THEN
                CREATE TRIGGER trg_memory_units_tsv
                BEFORE INSERT OR UPDATE ON memory_units
                FOR EACH ROW EXECUTE FUNCTION memory_units_tsv_trigger();
            END IF;
        END$$;
    ''')
    print("✅ 记忆表创建完成")


def create_task_custom_mcp_table(cursor):
    """创建定时任务表"""
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS task_custom_mcp (
            id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            agent_id TEXT NOT NULL,
            session_id TEXT NOT NULL,
            task_name TEXT NOT NULL,
            task_description TEXT,
            task_message TEXT,
            schedule_type TEXT NOT NULL CHECK (schedule_type IN ('cron', 'date')),
            cron_expr TEXT,
            run_at TIMESTAMP,
            status TEXT NOT NULL DEFAULT 'pending',
            last_run_at TIMESTAMP,
            next_run_at TIMESTAMP,
            last_error TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users (id)
        )
    ''')
    cursor.execute('''
        CREATE INDEX IF NOT EXISTS idx_task_custom_mcp_user ON task_custom_mcp(user_id)
    ''')
    cursor.execute('''
        CREATE INDEX IF NOT EXISTS idx_task_custom_mcp_status ON task_custom_mcp(status)
    ''')
    cursor.execute('''
        CREATE INDEX IF NOT EXISTS idx_task_custom_mcp_next_run ON task_custom_mcp(next_run_at)
    ''')
    print("✅ 定时任务表创建完成")



def create_agent_settings_table(cursor):
    """创建AI智能体配置表"""
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS agent_settings (
            agent_id TEXT PRIMARY KEY,
            system_prompt TEXT,
            work_dir TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (agent_id) REFERENCES users (id)
        )
    ''')

    cursor.execute('''
        CREATE INDEX IF NOT EXISTS idx_agent_settings_agent_id ON agent_settings(agent_id)
    ''')

    print("✅ AI智能体配置表创建完成")

def create_mcps_table(cursor):
    """创建MCP配置表"""
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS mcps (
            id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            name TEXT NOT NULL,
            mcp_type TEXT NOT NULL DEFAULT 'http',
            url TEXT NOT NULL,
            headers TEXT,
            env TEXT,
            command TEXT,
            args TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users (id)
        )
    ''')
    cursor.execute('''
        CREATE INDEX IF NOT EXISTS idx_mcps_user_id ON mcps(user_id)
    ''')
    cursor.execute('''
        CREATE INDEX IF NOT EXISTS idx_mcps_name ON mcps(name)
    ''')
    print("✅ MCP配置表创建完成")

if __name__ == "__main__":
    # 直接运行此脚本时初始化数据库
    check_and_init()
