# Git Forensics — Git 热点与耦合分析

> generated_by: nexus-mapper v2
> verified_at: 2026-07-16
> provenance: git_detective.py (90 days analysis)

## 分析概况

| 指标 | 值 |
|------|-----|
| 分析周期 | 90 天 |
| 总提交数 | 8 |
| 提交作者数 | 2 |
| 热点文件数 | 21 |
| 耦合对数 | 21 |

## 热点文件（按变更次数排序）

| 排名 | 文件路径 | 变更次数 | 风险等级 |
|------|----------|----------|----------|
| 1 | `src/ielts_buddy/services/grading_service.py` | 3 | low |
| 2 | `src/ielts_buddy/services/exam_service.py` | 2 | low |
| 3 | `src/ielts_buddy/services/personal_vocab_service.py` | 2 | low |
| 4 | `src/ielts_buddy/services/recommend_service.py` | 2 | low |
| 5 | `src/ielts_buddy/services/report_service.py` | 2 | low |
| 6 | `src/ielts_buddy/services/review_service.py` | 2 | low |
| 7 | `src/ielts_buddy/services/stats_service.py` | 2 | low |
| 8 | `src/ielts_buddy/core/models.py` | 2 | low |
| 9 | `src/ielts_buddy/cli.py` | 2 | low |
| 10 | `pyproject.toml` | 2 | low |
| 11 | `src/ielts_buddy/commands/grade.py` | 2 | low |
| 12 | `README.md` | 2 | low |

## 耦合对分析

### 强耦合组（coupling_score = 1.0）

所有 7 个核心服务之间存在 `coupling_score=1.0` 的完全耦合：

| 服务 A | 服务 B | 共同变更次数 | 耦合分数 |
|--------|--------|--------------|----------|
| exam_service | grading_service | 2 | 1.0 |
| exam_service | personal_vocab_service | 2 | 1.0 |
| exam_service | recommend_service | 2 | 1.0 |
| exam_service | report_service | 2 | 1.0 |
| exam_service | review_service | 2 | 1.0 |
| exam_service | stats_service | 2 | 1.0 |
| grading_service | personal_vocab_service | 2 | 1.0 |
| grading_service | recommend_service | 2 | 1.0 |
| grading_service | report_service | 2 | 1.0 |
| grading_service | review_service | 2 | 1.0 |
| grading_service | stats_service | 2 | 1.0 |
| personal_vocab_service | recommend_service | 2 | 1.0 |
| personal_vocab_service | report_service | 2 | 1.0 |
| personal_vocab_service | review_service | 2 | 1.0 |
| personal_vocab_service | stats_service | 2 | 1.0 |
| recommend_service | report_service | 2 | 1.0 |
| recommend_service | review_service | 2 | 1.0 |
| recommend_service | stats_service | 2 | 1.0 |
| report_service | review_service | 2 | 1.0 |
| report_service | stats_service | 2 | 1.0 |
| review_service | stats_service | 2 | 1.0 |

### 耦合解释

**高耦合原因推断**:
1. 这些服务可能是同时开发的功能模块
2. 可能共享相似的数据模型或接口
3. 在开发周期中可能由同一开发者批量修改

**风险评估**:
- 所有变更均为 low 风险（变更次数 ≤ 3）
- 高耦合不等于高风险，但意味着修改时需要全面测试

## 风险评估

| 风险等级 | 文件数 | 说明 |
|----------|--------|------|
| high | 0 | 无高风险文件 |
| medium | 0 | 无中风险文件 |
| low | 21 | 所有文件变更次数 ≤ 3 |

## 证据缺口

- 提交历史较短（8次提交），统计分析意义有限
- 2 位作者的贡献比例未知
- 无法确定耦合是否来自真实功能依赖还是开发习惯
