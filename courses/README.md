# 知识卡片课程目录

本目录存放雅思知识卡片内容，按主题组织。

## 目录结构

每个主题一个文件夹，包含：
- `meta.json` - 卡片元数据
- `content.json` - 结构化内容（系统集成用）
- `content.md` - Markdown 版（CLI 阅读用）
- `*.docx` - 原始文件（用户下载打印）

## 添加新课程

1. 在 `courses/` 下创建主题文件夹（如 `courses/太空探索/`）
2. 放入原始 `.docx` 文件
3. 运行转换脚本：
   ```bash
   python scripts/convert_course.py courses/太空探索/Sentence01_太空探索_知识卡片.docx
   ```

4. 运行后检查生成的文件：
   - `content.json` - 系统使用
   - `content.md` - 阅读使用
   - `meta.json` - 元数据（可能需要手动补充）

## 查看所有主题

```bash
python -c "import json; from pathlib import Path; [print(p.name) for p in Path('courses').iterdir() if p.is_dir()]"
```
