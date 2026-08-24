# 依赖关系（Dependencies）

> generated_by: nexus-mapper v2
> verified_at: 2026-08-23
> provenance: AST-backed (Python 198/198 files); Mermaid 节点 ID 与 `concept_model.json` 一致

---

## 图 1：System 级依赖（核心 5 + Domain 4）

```mermaid
flowchart TB
    subgraph EntryLayer[入口层]
        WEB["ielts-buddy-web-application<br/>FastAPI · 28 pages · 🔴19变更"]
        CLI["ielts-buddy-cli-application<br/>Click · 17组/65子命令"]
    end

    subgraph DomainLayer[领域层]
        DV["ielts-buddy-domain-vocab-learning"]
        DE["ielts-buddy-domain-exam-simulation"]
        DP["ielts-buddy-domain-prep-resources<br/>🆕 v3.8"]
        DS["ielts-buddy-domain-sync-daemon"]
    end

    subgraph ServiceLayer[服务层]
        SVC["ielts-buddy-service-layer<br/>26 services"]
    end

    subgraph FoundationLayer[基础层]
        PERSIST["ielts-buddy-persistence-layer<br/>SQLite+MySQL+Fallback 🔴16+11变更"]
        CORE["ielts-buddy-core-foundation<br/>Models·Config·Auth 🔴46+40 fan-in"]
    end

    subgraph TestLayer[测试层]
        TEST["ielts-buddy-tests-static-coverage<br/>86 modules · 24k 行"]
    end

    WEB --> SVC
    WEB --> PERSIST
    WEB --> CORE
    CLI --> SVC
    CLI --> PERSIST

    SVC --> PERSIST
    SVC --> CORE
    PERSIST --> CORE

    DV --> PERSIST
    DE --> PERSIST
    DE --> CORE
    DP --> PERSIST
    DS --> PERSIST

    TEST -.->|covers| WEB
    TEST -.->|covers| CLI
    TEST -.->|covers| SVC
    TEST -.->|covers| PERSIST

    classDef hotspot fill:#fee,stroke:#c33,stroke-width:2px
    classDef new fill:#efe,stroke:#393,stroke-width:2px
    class WEB,PERSIST,CORE hotspot
    class DP new
```

**关键观察**：
1. **无环依赖**：入口 → 服务 → 持久化 → 核心，单向。
2. **热点集中在 Web ↔ Persistence ↔ Core 三层**（main.py 19, sqlite_repo 16, mysql_repo 11, models 46 fan-in）。
3. **v3.8 新增**的 Domain `prep-resources` 仅依赖 Persistence，不触碰 Core — 干净的增量。

---

## 图 2：Hotspot 耦合对（git coupling ≥ 0.5）

```mermaid
flowchart LR
    MAIN["web/main.py<br/>🔴 19 变更"]
    BASE["web/templates/base.html<br/>13 变更 · coupling 1.00"]
    SQLITE["repositories/sqlite_repo.py<br/>🔴 16 变更"]
    MYSQL["repositories/mysql_repo.py<br/>11 变更"]
    AUTH["web/auth/repository.py<br/>40 fan-in · 7 变更"]
    INIT["scripts/init_mysql.sql<br/>10 变更"]
    MIG["scripts/migrate_v3_mysql_schema.py<br/>7 变更"]

    MAIN ---|13次共同提交| BASE
    MAIN ---|5次共同提交| AUTH
    MAIN ---|10次共同提交| SQLITE
    MAIN ---|5次共同提交| MYSQL
    SQLITE ---|twin| MYSQL
    MYSQL ---|5次共同提交| AUTH
    SQLITE ---|schema-bound| INIT
    SQLITE ---|schema-bound| MIG
    MYSQL ---|schema-bound| INIT
    MYSQL ---|schema-bound| MIG

    classDef high fill:#fee,stroke:#c33
    class MAIN,SQLITE,MYSQL high
```

**结论**：schema 变更时必须三处同步（`sqlite_repo` + `mysql_repo` + `scripts/init_mysql.sql` 或 `migrate_v3_mysql_schema.py`）。

---

## 图 3：模块 fan-in / fan-out 排名（前 8）

```mermaid
flowchart LR
    subgraph FanIn[Top fan-in — 最被依赖]
        M1["models<br/>46"]
        M2["auth.repository<br/>40"]
        M3["core.config<br/>27"]
        M4["vocab_service<br/>25"]
        M5["auth.deps<br/>25"]
    end

    subgraph FanOut[Top fan-out — 最依赖他人]
        F1["cli.py<br/>21"]
        F2["web.main<br/>11"]
        F3["routers.articles<br/>8"]
        F4["routers.listening<br/>8"]
        F5["routers.personal<br/>8"]
    end

    M4 --> PERSIST[("Persistence")]
    M2 --> PERSIST
    F1 --> M4
    F1 --> M2
    F2 --> M2
    F2 --> M4
    F2 --> PERSIST
    F3 --> PERSIST
    F4 --> PERSIST
    F5 --> PERSIST
```

**观察**：
- **cli.py** 是单点入口，import 21 个内部模块 — 拆 CLI 子模块时务必保证 cli.py 注册正确。
- **vocab_service + auth.repository** 是双向枢纽（高 fan-in 同时被多层调用）。
- 三个 v3.8 routers（articles / listening / personal）fan-out 对齐 8 — 标准化良好。

---

## 依赖分层约束（架构护栏）

| 上层 | 可以依赖 | 不可以依赖 |
| --- | --- | --- |
| Web / CLI 入口 | Service / Persistence / Core | 任何具体实现细节 |
| Service | Persistence / Core | 任何具体路由/CLI |
| Persistence (Protocol) | Core | 任何具体业务服务 |
| Core | （仅 stdlib + Pydantic + passlib + PyJWT） | 任何上层模块 |

**违反检查**（AST-backed）：
- 扫描所有 `import` 方向，**未发现反向依赖**（下层 import 上层）。
- `sync.py` 是唯一跨层 worker，它依赖 `fallback_repo` 而非 Service，保持层次一致。