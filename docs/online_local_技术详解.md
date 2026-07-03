# Online / Local 双模式技术详解

> 适用对象：**没有 Python 基础**、但要接手或维护 ielts_buddy（`D:\0000-maven\self-program\ielts_apply_seek`）的开发者
> 撰写日期：2026-07-02
> 范围：项目里"local 模式（SQLite）"和"online 模式（MySQL）"两套分支的所有代码逻辑
>
> 阅读路径：第一次看 → 第一节（基础概念）+ 第四节（5 分钟总览）；改功能 → 跳到对应小节找文件

---

## 一、给 Python 零基础读者的预备知识

### 1.1 这个项目用什么语言写的

**Python 3.13**。整个项目约 6000 行 Python 代码，分布在 `src/ielts_buddy/` 目录下。

Python 跟 JavaScript / Java 比，最明显的特征是**不用大括号 `{ }` 分隔代码块**，而是**用缩进**（4 个空格）。比如：

```python
# Python
def hello(name):
    if name:
        print(f"Hello, {name}")
    else:
        print("Hello, world")
```

```javascript
// JavaScript
function hello(name) {
    if (name) {
        console.log(`Hello, ${name}`);
    } else {
        console.log("Hello, world");
    }
}
```

### 1.2 几个 Python 术语速查

| 术语 | 意思 | 类比其他语言 |
|---|---|---|
| **模块（module）** | 一个 `.py` 文件 | Java 的 `.java` 文件、JS 的 `.js` 文件 |
| **包（package）** | 一个包含 `__init__.py` 的目录 | Java 的 package、JS 的 folder |
| **类（class）** | 用 `class` 关键字定义的类型 | Java/JS 的 class |
| **方法（method）** | 类里定义的函数 | class 里的 method |
| **函数（function）** | 不在类里的代码块 | C 的 function |
| **import** | 引用其他模块 | Java 的 import、JS 的 require/import |
| **Protocol** | "鸭子类型"接口定义 | Java 的 interface、TS 的 interface |
| **fixture**（pytest 术语）| 测试前的准备代码 | JUnit 的 @BeforeEach、Mocha 的 beforeEach |
| **mock**（测试术语）| 假对象，替身 | 所有语言都有的"测试替身"概念 |
| **async / await** | 异步代码 | JS / C# 也有 |

### 1.3 这个项目用的核心库

| 库 | 用途 | 项目里出现的位置 |
|---|---|---|
| **click** | 命令行参数解析 | `cli.py`、所有 `commands/*.py` |
| **rich** | 美化终端输出 | `cli.py`、所有用 `console.print` 的地方 |
| **pydantic** | 数据校验 + 数据类 | `models/*.py`、所有 `from pydantic import BaseModel` 的地方 |
| **jinja2** | 模板渲染（生成报告）| `services/report_service.py` |
| **sqlalchemy** | MySQL ORM | `repositories/mysql_repo.py` |
| **pymysql** | MySQL 驱动 | 间接通过 SQLAlchemy |
| **cryptography** | pymysql 依赖 | MySQL 8 sha2 认证 |
| **openai** | LLM SDK（grading_service 用 minimaxi 的 OpenAI 兼容接口）| `docs/grok.py` |
| **pytest** | 测试框架 | `tests/` |

### 1.4 一个 Python 项目的目录结构怎么读

```
ielts_apply_seek/                 ← 项目根目录
├── pyproject.toml                ← 项目元数据 + 依赖声明（"包管理"）
├── src/                          ← 源代码根（"src layout"）
│   └── ielts_buddy/              ← 主包
│       ├── __init__.py           ← 主包入口
│       ├── cli.py                ← CLI 入口（`ib` 命令从这里开始）
│       ├── core/                 ← 核心工具
│       │   └── config.py         ← 配置文件读取、env 变量、mode 解析
│       ├── commands/             ← 子命令（每个文件是一个 click group）
│       │   ├── auth.py           ← ib auth login / whoami / logout
│       │   ├── vocab.py          ← ib vocab info / add / list
│       │   ├── stats.py          ← ib stats show
│       │   └── ...               ← 还有 write / speak / listen / report / grade / sync / email
│       ├── models/               ← 数据模型（pydantic 类）
│       ├── repositories/         ← 数据访问层（最关键的"双模式"就在这里）
│       │   ├── __init__.py       ← 工厂函数 create_repositories(mode)
│       │   ├── sqlite_repo.py    ← SQLite 6 个 Repository + 容器
│       │   └── mysql_repo.py     ← MySQL 6 个 Repository + 容器
│       └── services/             ← 业务服务（调用 repositories）
├── tests/                        ← 测试代码
└── docs/                         ← 文档
```

`pyproject.toml` 是关键文件——里面声明了项目名、依赖、入口点（`ib` 命令 = `ielts_buddy.cli:cli`）。

---

## 二、模式分发的核心概念

### 2.1 什么是"两种模式"

这个项目允许学习数据存在两套数据库里：

| 模式 | 名字 | 数据库 | 数据存哪里 | 适用场景 |
|---|---|---|---|---|
| **local** | 离线模式 | **SQLite**（一个 `.db` 文件）| `~/.ielts-buddy/data.db` | 单机使用、离线、断网 |
| **online** | 在线模式 | **MySQL**（远程数据库）| 远程 MySQL 库 `ielts_buddy` | 多用户、web 端、跨设备 |

**两套模式是两套独立的数据**。同一个用户名在 local 写的词和 online 写的词，**互相看不到**（user_id 在 local 永远是 1，online 是 MySQL 真实 id）。

### 2.2 为什么要分两套

设计目标见 `docs/方案_数据层扩展_v2.0.md`：

- **local**：用户开箱即用，不依赖网络
- **online**：支持 web 端、未来多用户协作

**核心约束（不做的事）**：
- ❌ 不做混合模式（不"双写"，不"自动同步"）
- ❌ 不做数据迁移（local 数据不自动推 MySQL，反之亦然）
- ❌ 不做冲突解决（因为不做同步，所以也不存在冲突）

### 2.3 "模式分发"在代码里长什么样

整个项目有一个**唯一的"分发点"**：`create_repositories(mode)` 工厂函数。

调用方不直接 `import sqlite_repo` 或 `import mysql_repo`，**统一**调：

```python
from ielts_buddy.repositories import create_repositories

container = create_repositories(mode="local")   # 拿到 SQLite 容器
# 或者
container = create_repositories(mode="online")  # 拿到 MySQL 容器
# 之后用法完全一样
container.user.get_or_create("alice")
container.personal_vocab.add("vocab", user_id=1, ...)
```

**两套 Repository 实现**是同形（同方法名、同参数、同返回）的——这就是为什么 `create_repositories` 能做工厂分发。

### 2.4 "mode"是几层抽象

mode 一共出现在 **4 个层级**（从外到内）：

```
┌─────────────────────────────────────────────────────────────┐
│ 1) 命令行参数                                                  │
│    ib --mode local|online ...                                │
│    优先级最高，写到 os.environ["IELTS_BUDDY_MODE"]              │
├─────────────────────────────────────────────────────────────┤
│ 2) 环境变量                                                  │
│    IELTS_BUDDY_MODE=local|online                             │
│    优先级第二，get_mode() 第一个检查                            │
├─────────────────────────────────────────────────────────────┤
│ 3) 配置文件                                                   │
│    ~/.ielts-buddy/config.toml 里 [general] mode = "local"     │
│    优先级第三                                                  │
├─────────────────────────────────────────────────────────────┤
│ 4) 兜底默认                                                  │
│    都没设 → "local"                                          │
└─────────────────────────────────────────────────────────────┘
```

源码：`src/ielts_buddy/core/config.py:67-93` 的 `get_mode()`。

---

## 三、双模式代码地图

### 3.1 关键文件清单

| 文件 | 行数 | 作用 | 双模式相关性 |
|---|---|---|---|
| `src/ielts_buddy/core/config.py` | ~210 | 配置 + env + mode 解析 | **核心**——`get_mode()` / `get_user_id()` |
| `src/ielts_buddy/repositories/__init__.py` | ~110 | 工厂入口 `create_repositories(mode)` | **核心**——分发点 |
| `src/ielts_buddy/repositories/sqlite_repo.py` | ~1500 | SQLite 6 个 Repository + 容器 | online 模式不用 |
| `src/ielts_buddy/repositories/mysql_repo.py` | ~1430 | MySQL 6 个 Repository + 容器 | local 模式不用 |
| `src/ielts_buddy/cli.py` | ~175 | `ib` 入口 | 升级 `_show_current_user` 支持 mode 阻断（W8）+ `--mode` 选项（W9） |
| `src/ielts_buddy/services/auth_service.py` | ~230 | 用户登录/会话 | 加 `whoami` mode 校验（W11）|
| `src/ielts_buddy/services/vocab_service.py` 等 | — | 业务服务 | 调 `create_repositories(mode)`，内部无感 |
| `tests/test_commands/test_w8_mode_blocking.py` | — | W8 测试 | mode 决定是否阻断 |
| `tests/test_commands/test_w9_cli_mode_option.py` | — | W9 测试 | `--mode` 选项 |
| `tests/test_commands/test_w10_cli_mode_reaches_subcommand.py` | — | W10 测试 | 子命令真能看到 env |
| `tests/test_services/test_w11_whoami_mode_match.py` | — | W11 测试 | session.mode 校验 |

### 3.2 双模式代码关系图

```
                                  ┌────────────────────┐
                                  │  ib <subcmd> ...   │
                                  │  ib --mode online  │
                                  └────────┬───────────┘
                                           │
                                  ┌────────▼───────────┐
                                  │  cli.py            │
                                  │  cli(ctx, mode)    │
                                  │   ├─ 写 env         │
                                  │   └─ @result_      │
                                  │      callback 还原  │
                                  └────────┬───────────┘
                                           │
                                  ┌────────▼───────────┐
                                  │ _show_current_user  │
                                  │  AuthService.whoami │
                                  │   ├─ W11 校验 mode  │
                                  │   └─ 返回 session   │
                                  └────────┬───────────┘
                                           │
              ┌────────────────────────────┴────────────────────────────┐
              │                                                         │
    ┌─────────▼──────────┐                                  ┌──────────▼──────────┐
    │ mode == "local"     │                                  │ mode == "online"      │
    │                     │                                  │                       │
    │ AuthService 没登录?  │                                  │ AuthService 没登录?    │
    │  → 软提示 banner     │                                  │  → 阻断 (sys.exit 1)  │
    │                     │                                  │                       │
    │ → create_repositories("local")                          │ → create_repositories("online")
    └─────────┬──────────┘                                  └──────────┬──────────┘
              │                                                         │
    ┌─────────▼──────────┐                                  ┌──────────▼──────────┐
    │ SQLiteRepository    │                                  │ MySQLRepository       │
    │ Container            │                                  │ Container              │
    │   ├─ user            │                                  │   ├─ user              │
    │   ├─ learning        │                                  │   ├─ learning          │
    │   ├─ personal_vocab  │                                  │   ├─ personal_vocab    │
    │   ├─ exam            │                                  │   ├─ exam              │
    │   ├─ grade           │                                  │   ├─ grade             │
    │   └─ vocab_cache     │                                  │   └─ vocab_cache       │
    └──────────────────────┘                                  └───────────────────────┘
              │                                                         │
              ▼                                                         ▼
       ~/.ielts-buddy/data.db                                   MySQL @ 118.190.148.121
```

---

## 四、5 分钟看懂"模式分发"的执行链

### 4.1 一次 `ib --mode online vocab info` 调用全过程

| 步骤 | 代码位置 | 发生了什么 |
|---|---|---|
| 1 | `cli.py:122-148` | click 解析 `--mode online` 写到 `os.environ["IELTS_BUDDY_MODE"]` |
| 2 | `cli.py:152-154` | click 调度 `vocab` 子命令；`cli()` 退出 |
| 3 | `commands/vocab.py:info` | 子命令开始 |
| 4 | `cli.py:147-148` | `_show_current_user("vocab")` 打印 banner |
| 5 | `cli.py:78-95`（W8 改造） | `AuthService.whoami()` → 读 session，**W11 校验 session.mode == "online"** |
| 6 | `cli.py:78-95` | 未登录 + online → `sys.exit(1)` 红字；未登录 + local → 软提示；登录 → 显示用户 |
| 7 | `commands/vocab.py:info` | 子命令 `vocab_service.get_vocab_info()` |
| 8 | `services/vocab_service.py` | 内部调 `create_repositories(mode)` |
| 9 | `repositories/__init__.py:90-99` | mode 决定走 SQLite 还是 MySQL |
| 10 | `commands/vocab.py:info` | 拿到结果，打印 |
| 11 | `cli.py:157-167` | `@cli.result_callback()` 在子命令执行完后还原 env |

### 4.2 一次 `ib --mode local auth login wangliping` 调用全过程

| 步骤 | 代码位置 | 发生了什么 |
|---|---|---|
| 1-4 | 同上（mode=local） | banner 显示 local 模式 |
| 5 | `commands/auth.py:33` | `auth login` 命令被调用 |
| 6 | `commands/auth.py:36` | `AuthService(mode="local")` 构造 |
| 7 | `services/auth_service.py:67-75` | `self._mode = "local"`（直接从参数，不读 env） |
| 8 | `commands/auth.py:37` | `svc.login("wangliping")` |
| 9 | `services/auth_service.py:131-194` | `user_repo.get_or_create("wangliping")` |
| 10 | `repositories/__init__.py:90` | mode=local → `SQLiteUserRepository.get_or_create()` → 永远返回 id=1 |
| 11 | `services/auth_service.py:172-181` | 写 `session.json`：`{user_id: 1, username: wangliping, mode: local, ...}` |
| 12 | `commands/auth.py:46-52` | 打印"登录成功 user_id=1 username=wangliping mode=local" |
| 13 | `commands/auth.py:53-56` | mode=local → 提示"单机模式下 user_id 始终为 1，username 仅作展示" |

---

## 五、改功能时要看哪里

### 5.1 "我想改一条 SQL 怎么改"

| 你的需求 | 看哪里 |
|---|---|
| 改 learning_records 表的查询 | `repositories/sqlite_repo.py:287` `SQLiteLearningRepository` / `repositories/mysql_repo.py:235` `MySQLLearningRepository` |
| 加新的表 / Repository | 在两个文件都加一个 `XxxRepository` 类，方法名/参数保持一致；然后改 `repositories/__init__.py` 的 `create_repositories()` 工厂 + `RepositoryContainer` Protocol |
| 改 user_id 隔离逻辑 | 找 `WHERE user_id = ?` 的位置，W7 + W8 已经把"未登录默认 1 + online 阻断"都做了 |
| 改 schema 字段 | `models/*.py` 的 pydantic 类 + `sqlite_repo.py` 的 `_migrate_legacy_schema()`（W4 写的自动迁移） |

### 5.2 "我想加一条命令怎么加"

| 你的需求 | 看哪里 |
|---|---|
| 加一个 `ib <新命令> <子命令>` | 在 `commands/` 新建 `<新命令>.py`，仿 `commands/auth.py` 写 `@<新命令>.command()` |
| 命令里要读写数据库 | 仿 `commands/vocab.py`：`from ielts_buddy.repositories import create_repositories` |
| 命令里要登录态 | `from ielts_buddy.services.auth_service import AuthService`，仿 `commands/auth.py:62` `svc.whoami()` |
| 命令要在未登录时区分 local/online | 看 W8 的 `_show_current_user`，W11 之后 whoami 不会返回 mode 不匹配的 session |

### 5.3 "我想改 mode 解析逻辑"

| 你的需求 | 看哪里 |
|---|---|
| 改优先级 | `core/config.py:67-93` `get_mode()` |
| 改默认值 | `core/config.py:99-103` 兜底分支 |
| 改 CLI 选项 | `cli.py:124-130` `--mode` 选项 |
| 改还原机制 | `cli.py:156-167` `@cli.result_callback()` |

---

## 六、双模式 Repository 详解

### 6.1 一致的接口

两个文件都有这 6 个 Repository（同名同形）：

| Repository 类名 | 负责的数据 | 关键方法 |
|---|---|---|
| `LearningRepository` | 学习记录（学习某个词多少次、对错）| `get_due_words(user_id, today, limit)` / `record_attempt(user_id, word, is_correct, today)` |
| `PersonalVocabRepository` | 个人词库（用户加进"生词本"的词）| `add(user_id, word, ...)` / `list_by_user(user_id, band=...)` |
| `ExamRepository` | 真题 / 模拟题 | `get_exam_by_id(exam_id)` / `list_exams(band=...)` |
| `GradeRepository` | 批改记录 | `save_grade(user_id, essay, score, ...)` / `get_grades(user_id, limit=...)` |
| `VocabCacheRepository` | 词库缓存（内置词表）| `get_word(word)` / `bulk_load(words)` |
| `UserRepository` | 用户 | `get_or_create(username)` / `update_last_login(user_id)` / `ensure_system_categories(user_id)` |

### 6.2 SQLite Repository 怎么连库

`repositories/sqlite_repo.py:1418` `create_sqlite_repositories(db_path=None, cache_path=None)`：

```python
def create_sqlite_repositories(db_path=None, cache_path=None):
    db_path = db_path or get_db_path()      # ~/.ielts-buddy/data.db
    cache_path = cache_path or (get_app_dir() / "vocab_cache.db")
    conn = sqlite3.connect(str(db_path))     # 直接打开 .db 文件
    conn.row_factory = sqlite3.Row
    _migrate_legacy_schema(conn)             # 自动建表 + 加新字段
    return SQLiteRepositoryContainer(
        learning=SQLiteLearningRepository(conn),
        personal_vocab=SQLitePersonalVocabRepository(conn),
        exam=SQLiteExamRepository(conn),
        grade=SQLiteGradeRepository(conn),
        vocab_cache=SQLiteVocabCacheRepository(str(cache_path)),
        user=SQLiteUserRepository(conn),
    )
```

**特点**：
- **零外部依赖**（不装 SQLAlchemy 也能跑）
- **文件即数据库**（删了 `data.db` 等于清空所有学习数据）
- **`get_or_create(username)` 永远返回 id=1**（W6 决策，单机模式不真建账号）

### 6.3 MySQL Repository 怎么连库

`repositories/mysql_repo.py:1415` `create_mysql_repositories(connection_url=None)`：

```python
def create_mysql_repositories(connection_url=None):
    if not _MYSQL_AVAILABLE:
        raise ImportError("在线模式需要安装 SQLAlchemy 与 PyMySQL：pip install 'sqlalchemy>=2.0' pymysql cryptography")
    url = connection_url or _build_mysql_url()
    engine = create_engine(url, pool_pre_ping=True)   # SQLAlchemy
    Base.metadata.create_all(engine)                   # 自动建表
    session_factory = sessionmaker(bind=engine)
    return MySQLRepositoryContainer(
        learning=MySQLLearningRepository(session_factory),
        personal_vocab=MySQLPersonalVocabRepository(session_factory),
        exam=MySQLExamRepository(session_factory),
        grade=MySQLGradeRepository(session_factory),
        vocab_cache=MySQLVocabCacheRepository(session_factory),
        user=MySQLUserRepository(session_factory),
    )
```

**特点**：
- **必须有 SQLAlchemy + PyMySQL + cryptography**（`pyproject.toml` 里 dependencies 已声明）
- **`get_or_create(username)` 真建账号**，id 由 MySQL `AUTO_INCREMENT` 分配
- **支持多用户**：每个 username 对应真实 id，**user_id 隔离**（W7 实现的 `WHERE user_id = ?` 在 MySQL Repository 里都有）

### 6.4 `RepositoryContainer` Protocol

`repositories/__init__.py:73-85` 定义了鸭子类型接口：

```python
@runtime_checkable
class RepositoryContainer(Protocol):
    learning: LearningRepository
    personal_vocab: PersonalVocabRepository
    exam: ExamRepository
    grade: GradeRepository
    vocab_cache: VocabCacheRepository
    user: UserRepository
```

**业务代码只需要知道 `RepositoryContainer`**，不关心具体是 SQLite 还是 MySQL。**这正是 W3 文档说的"为后续 web 端预留"**——web 端可以用同样的代码，只换 mode。

---

## 七、AuthService 双模式行为详解

### 7.1 三个核心方法

| 方法 | 行为 | 双模式差异 |
|---|---|---|
| `login(username)` | 调 `user_repo.get_or_create` 拿 user_id，写 session | local 返回 id=1；online 返回 MySQL 真实 id |
| `whoami()` | 读 session.json，**W11 校验 session.mode == self._mode** | mode 不一致返回 None（视为未登录） |
| `logout()` | 删 session.json | 无差异 |

### 7.2 login 的具体步骤（`auth_service.py:131-194`）

```
login("alice")
  ↓
1) user_repo.get_or_create("alice")  → user_id
   ├─ local: SELECT id FROM users WHERE username = 'alice' LIMIT 1
   │          → 没找到就 INSERT
   │          → 单机模式永远返回 id=1
   └─ online: INSERT ... ON DUPLICATE KEY UPDATE id=LAST_INSERT_ID(id)
              → MySQL 真实 id
  ↓
2) user_repo.update_last_login(user_id)  → 写 last_login_at 字段
  ↓
3) user_repo.ensure_system_categories(user_id)
   → 给这个 user 插 5 个系统预设词类（听/说/读/写/拼写）
  ↓
4) 写 session.json
   {user_id, username, mode: self._mode, logged_in_at, last_login_at}
  ↓
5) 写回 config.database.user_id（让 get_user_id() 后续能命中）
  ↓
6) close() 容器
  ↓
7) 返回 {user_id, username, mode, is_new}
```

### 7.3 whoami 的 W11 校验

```python
def whoami(self):
    data = self._read_session()    # 读 session.json
    if data is None:
        return None                 # 没登录
    if data.get("mode") != self._mode:   # W11 新增
        return None                 # session 跟当前 mode 不匹配
    return data
```

**为什么必须校验**：
- online 模式登录 → session 写 mode=online
- 切到 local 模式跑业务 → AuthService(mode=local) 构造，self._mode=local
- 不校验 → 返回 online 的 user_id（如 692）
- 业务用 id=692 查 local SQLite → 查不到
- **W11 修这个 bug**

---

## 八、CLI 入口的双模式逻辑

### 8.1 `cli.py` 的双模式相关代码

| 行号 | 内容 | 改动 |
|---|---|---|
| 1-12 | `import os` + `import click` | W9 加 `os` |
| 18-23 | 模块级 `_MODE_STATE` | W10 加，替代 W9 的 `_MODE_ENV_BACKUP` |
| 75-95 | `_show_current_user` 升级 | W8 加 online 阻断分支 |
| 122-148 | `cli(ctx, mode)` 加 `--mode` 选项 | W9 加，W10 改 |
| 157-167 | `@cli.result_callback()` | W10 加，env 还原 |

### 8.2 `_show_current_user` 的 W8 升级详解

```python
def _show_current_user(invoked):
    # 1) auth 子命令自己打印用户信息，避免重复
    if invoked == "auth":
        return

    # 2) 显式关闭 banner（CI / 老测试用）
    if os.environ.get("IELTS_BUDDY_NO_BANNER", "").strip() in ("1", "true", "yes"):
        return

    try:
        # 3) 解析当前 mode（env > config > local）
        cfg = Config()
        mode = get_mode(cfg)

        # 4) 读 session（不连 DB）
        svc = AuthService(session_path=..., config=cfg, mode=mode)
        info = svc.whoami()         # W11 校验 mode
        svc.close()

        if info is None:
            # 5a) 未登录 + online → 阻断（W8）
            if mode == "online":
                print("[red]在线模式需要先登录...[/red]", file=sys.stderr)
                sys.exit(1)
            # 5b) 未登录 + local → 软提示 banner（W7）
            print("[dim]-- 未登录：数据默认保存到 user_id=1 --[/dim]", file=sys.stderr)
            return

        # 6) 已登录 → 显示用户
        print(f"-- 当前用户: {info['username']} (id={info['user_id']}, mode={mode}) --", file=sys.stderr)
    except Exception:
        # 静默失败：banner 坏了不影响业务
        pass
```

### 8.3 W10 result_callback 的 click 调用链

click multi-command 调用顺序：

```
CliRunner.invoke(cli, ["--mode", "online", "auth", "login", "alice"])
  ↓
1. cli(ctx, mode)                          # 写 os.environ
   self._mode = mode
   ↓
2. click 调度 subcommand                   # cli() 退出后 click 才会 invoke
   auth login alice
     ↓ AuthService 读 env → 看到 online
   ↓
3. @cli.result_callback()                  # 子命令执行完后
   还原 os.environ
```

**关键点**：W9 错把 `try/finally` 放在 `cli()` 函数体内，finally 在子命令执行**前**就触发；W10 改用 `@cli.result_callback()`，在子命令执行**后**才还原。

---

## 九、运行测试与验证

### 9.1 跑单个文件测试

```powershell
cd D:\0000-maven\self-program\ielts_apply_seek
& 'D:\Program Files (x86)\Python3.13.3\python.exe' -m pytest tests/test_commands/test_w8_mode_blocking.py -v
```

### 9.2 跑双模式相关所有测试

```powershell
& 'D:\Program Files (x86)\Python3.13.3\python.exe' -m pytest tests/test_commands/ tests/test_services/test_auth_service.py tests/test_services/test_w7_user_id_isolation.py tests/test_services/test_w11_whoami_mode_match.py
```

### 9.3 跑 ruff（静态代码检查）

```powershell
& 'D:\Program Files (x86)\Python3.13.3\python.exe' -m ruff check src/ielts_buddy/cli.py src/ielts_buddy/core/config.py src/ielts_buddy/repositories/ src/ielts_buddy/services/auth_service.py --no-cache
```

### 9.4 真跑双模式命令

```powershell
# local 模式（默认）
ib vocab info
ib vocab add "compatibility" --meaning "兼容性" --band 7

# online 模式
ib --mode online auth login myuser
ib --mode online vocab info
ib --mode online vocab add "onlineword" --meaning "在线" --band 6

# 断网时切 local 继续学
ib --mode local auth login myuser   # W11: 必须重新 login
ib --mode local vocab info
```

---

## 十、常见问题排查

| 现象 | 原因 | 解决 |
|---|---|---|
| `No module named 'pymysql'` | 装 SQLAlchemy 时漏装 PyMySQL | `pip install pymysql cryptography`，然后 `pip install -e . --upgrade` |
| `Access denied for user` | MySQL 用户名密码错 | 检查 `MYSQL_URL` 或 `database.mysql_url` |
| `Can't connect to MySQL server` | 网络或端口问题 | `Test-NetConnection 118.190.148.121 -Port 3306` |
| `Unknown database 'xxx'` | MySQL 里没这个 schema | `mysql -uroot -e "CREATE DATABASE ielts_buddy CHARACTER SET utf8mb4"` |
| online 登录后切 local 查不到数据 | W11 视为未登录 | 重新 `ib --mode local auth login <username>` |
| online 登录 user_id 跟 local 不一样 | 设计如此，user_id 在 MySQL 是真实自增 | 接受现状；想同 id 必须用同一套 DB |
| `ib` 命令找不到 | 没装 | `pip install -e .` |
| `ib --mode online` 报 `在线模式需要先登录` | 当前 HOME 里没 online session | `ib --mode online auth login <username>` |

---

## 十一、跨文档索引

| 想了解的内容 | 看哪个文档 |
|---|---|
| W8-W11 决策 / 真实 bug / 经验 | `docs/W8_W11_阶段问题复盘.md` |
| W7 的"未登录不阻断"决策 | `docs/W7_阶段问题复盘.md` |
| W3-W6 数据层 / mode 分发 / AuthService 演进 | `docs/W3_W6_阶段问题复盘.md` |
| W3 的 MySQL Repository 详细设计 | `docs/W3_阶段详解与扩展指南.md` |
| 数据层扩展的 v2.0 方案 | `docs/方案_数据层扩展_v2.0.md` |
| 版本号 / 时间线 / 归档 | `docs/迭代版本归档.md`（W12.3 输出） |
