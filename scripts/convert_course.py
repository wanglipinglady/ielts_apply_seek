#!/usr/bin/env python3
"""
知识卡片转换脚本
将 Word 文档 (.docx) 转换为 JSON 和 Markdown 格式

用法:
    python convert_course.py <docx文件路径> [--output-dir <输出目录>]
    python convert_course.py courses/太空探索/Sentence01_太空探索_知识卡片.docx

输出:
    - content.json: 结构化数据（系统集成用）
    - content.md: Markdown 格式（阅读用）
    - meta.json: 元数据（需手动补充或从文件名提取）
"""

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Optional


def extract_topic_from_filename(filename: str) -> str:
    """从文件名提取主题"""
    # 匹配 "Sentence01_太空探索_知识卡片.docx" 格式
    match = re.search(r' Sentence?\d+_(.+?)_知识卡片', filename)
    if match:
        return match.group(1).strip()
    return Path(filename).stem


def parse_bold_runs(para) -> list[str]:
    """提取段落中的粗体文本"""
    bold_texts = []
    for run in para.runs:
        if run.bold and run.text.strip():
            bold_texts.append(run.text.strip())
    return bold_texts


def parse_phonetic(text: str) -> Optional[str]:
    """从文本中提取音标"""
    # 匹配 /kənˈsɪdərəbl/ 格式
    match = re.search(r'/([^/]+)/', text)
    if match:
        return match.group(0)  # 保留 /.../ 格式
    return None


def clean_html_tags(text: str) -> str:
    """清理 HTML 残留"""
    text = re.sub(r'<[^>]+>', '', text)
    text = re.sub(r'\s+', ' ', text)
    return text.strip()


class CardParser:
    """知识卡片解析器"""
    
    # 卡片标题映射
    CARD_PATTERNS = {
        r'卡片\s*(\d+)': 'card_header',
        r'核心例句': 'core_sentence',
        r'语法笔记': 'grammar',
        r'核心词表': 'vocabulary',
        r'主题归纳': 'theme_vocab',
        r'反驳.*词汇': 'refute_vocab',
        r'探索.*主题词汇|太空主题词汇': 'space_vocab',
        r'探索.*动词|探索类动词': 'explore_vocab',
        r'综合应用|雅思写作模板': 'writing_template',
        r'学习总结': 'summary',
    }
    
    def __init__(self, doc):
        self.doc = doc
        self.current_section = None
        self.current_card = None
        self.content = {
            "topic": "",
            "core_sentence": {},
            "grammar": {},
            "vocabulary": [],
            "theme_vocab": {},
            "refute_vocab": [],
            "space_vocab": [],
            "explore_vocab": [],
            "writing_template": {},
            "summary": {}
        }
        self._parse()
    
    def _parse(self):
        """解析文档"""
        # 先收集所有段落
        for para in self.doc.paragraphs:
            self._process_paragraph(para)
        
        # 再处理所有表格
        for table in self.doc.tables:
            table_data = self._parse_table(table)
            self._process_table(table_data)
    
    def _parse_table(self, table):
        """解析表格"""
        data = []
        for row in table.rows:
            row_data = [cell.text.strip() for cell in row.cells]
            data.append(row_data)
        return data
    
    def _process_table(self, table_data):
        """处理表格数据"""
        if not table_data:
            return
        
        # 检查是否是词汇表（包含 word/音标/释义列）
        header = table_data[0] if table_data else []
        
        if any('词' in h or 'word' in h.lower() for h in header):
            # 词汇表格式
            for row in table_data[1:]:
                if len(row) >= 2:
                    word_text = row[0]
                    meaning_text = row[1] if len(row) > 1 else ""
                    
                    # 提取单词和音标
                    word_match = re.match(r'([a-zA-Z\-]+)', word_text)
                    if word_match:
                        word = word_match.group(1)
                        phonetic = parse_phonetic(word_text)
                        
                        # 清理释义
                        meaning = re.sub(r'/[^/]+/', '', meaning_text).strip()
                        meaning = re.sub(r'^\d+\.\s*', '', meaning)
                        
                        entry = {
                            "word": word,
                            "phonetic": phonetic or "",
                            "meaning": meaning,
                            "memory": "",
                            "synonyms": []
                        }
                        
                        # 从后续列提取更多信息
                        if len(row) > 2:
                            entry["memory"] = row[2]
                        if len(row) > 3:
                            synonyms_text = row[3]
                            # 解析同义词列表
                            synonyms = re.findall(r'[a-zA-Z]+', synonyms_text)
                            entry["synonyms"] = synonyms
                        
                        if self.current_section == 'vocabulary':
                            self.content["vocabulary"].append(entry)
                        elif self.current_section in ['theme_vocab', 'space_vocab']:
                            self.content["theme_vocab"].setdefault(self.current_section, []).append(word)
    
    def _process_paragraph(self, para):
        """处理段落"""
        text = para.text.strip()
        if not text:
            return
        
        # 检测卡片标题
        for pattern, section in self.CARD_PATTERNS.items():
            if re.search(pattern, text, re.IGNORECASE):
                self.current_section = section
                
                # 提取主题（从第一个卡片标题）
                if section == 'card_header' and not self.content["topic"]:
                    # 尝试从文档标题提取
                    pass
                return
        
        # 根据当前 section 处理内容
        if self.current_section == 'core_sentence':
            self._parse_core_sentence(text)
        elif self.current_section == 'grammar':
            self._parse_grammar(text)
    
    def _parse_core_sentence(self, text):
        """解析核心例句"""
        if '英文原句' in text or '剑桥雅思' in text:
            # 提取英文原句
            match = re.search(r'[A-Z][^。]+?(?:civilisation|civilization)[^。]+?\.', text)
            if match:
                self.content["core_sentence"]["en"] = match.group(0).strip()
        
        if '中文翻译' in text or '译文' in text:
            # 提取中文翻译
            match = re.search(r'[，。；：].*?[\u4e00-\u9fff].*?。', text)
            if match:
                self.content["core_sentence"]["cn"] = match.group(0).strip()
    
    def _parse_grammar(self, text):
        """解析语法笔记"""
        if '本句主干' in text or '结构成分' in text:
            self.content["grammar"]["structure"] = text
        
        if '结构图示' in text or '💡' in text:
            # 提取结构图示
            match = re.search(r'\[.*\]', text)
            if match:
                self.content["grammar"]["diagram"] = match.group(0)


def convert_docx_to_json(docx_path: Path, output_dir: Optional[Path] = None) -> dict:
    """
    将 docx 文件转换为 JSON 和 Markdown 格式
    
    Args:
        docx_path: docx 文件路径
        output_dir: 输出目录，默认与 docx 同目录
    
    Returns:
        解析后的 content 字典
    """
    try:
        from docx import Document
    except ImportError:
        print("错误: 需要 python-docx 库")
        print("安装: pip install python-docx")
        sys.exit(1)
    
    if not docx_path.exists():
        print(f"错误: 文件不存在 - {docx_path}")
        sys.exit(1)
    
    if output_dir is None:
        output_dir = docx_path.parent
    
    # 确保输出目录存在
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # 读取文档
    doc = Document(docx_path)
    
    # 解析内容
    parser = CardParser(doc)
    
    # 提取主题
    topic = extract_topic_from_filename(docx_path.name)
    parser.content["topic"] = topic
    
    # 生成 content.json
    content_json_path = output_dir / "content.json"
    with open(content_json_path, 'w', encoding='utf-8') as f:
        json.dump(parser.content, f, ensure_ascii=False, indent=2)
    print(f"✓ 生成: {content_json_path}")
    
    # 生成 content.md
    md_content = generate_markdown(parser.content)
    content_md_path = output_dir / "content.md"
    with open(content_md_path, 'w', encoding='utf-8') as f:
        f.write(md_content)
    print(f"✓ 生成: {content_md_path}")
    
    # 生成 meta.json（从文件名提取基本信息）
    meta = {
        "id": f"course_{topic}",
        "topic": topic,
        "title": docx_path.stem,  # 文件名（不含扩展名）
        "source_file": docx_path.name,
        "version": "1.0",
        "created_at": "",
        "updated_at": ""
    }
    meta_json_path = output_dir / "meta.json"
    with open(meta_json_path, 'w', encoding='utf-8') as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)
    print(f"✓ 生成: {meta_json_path}")
    
    return parser.content


def generate_markdown(content: dict) -> str:
    """将内容转换为 Markdown 格式"""
    md = []
    
    # 标题
    md.append(f"# {content['topic']}\n")
    md.append(f"来源: {content.get('source', 'IELTS Buddy')}\n")
    
    # 核心例句
    if content.get('core_sentence'):
        cs = content['core_sentence']
        md.append("## 核心例句\n")
        if cs.get('en'):
            md.append(f"**英文:** {cs['en']}\n")
        if cs.get('cn'):
            md.append(f"**中文:** {cs['cn']}\n")
        md.append("\n")
    
    # 核心词汇
    if content.get('vocabulary'):
        md.append("## 核心词汇\n")
        md.append("| 单词 | 音标 | 释义 | 助记 |\n")
        md.append("|------|------|------|------|\n")
        for v in content['vocabulary']:
            md.append(f"| {v.get('word', '')} | {v.get('phonetic', '')} | {v.get('meaning', '')} | {v.get('memory', '')} |\n")
        md.append("\n")
    
    # 语法结构
    if content.get('grammar'):
        md.append("## 语法结构\n")
        g = content['grammar']
        if g.get('structure'):
            md.append(f"**结构:** {g['structure']}\n")
        if g.get('diagram'):
            md.append(f"**图示:** {g['diagram']}\n")
        md.append("\n")
    
    # 主题词汇
    if content.get('theme_vocab'):
        md.append("## 主题词汇\n")
        for category, words in content['theme_vocab'].items():
            md.append(f"### {category}\n")
            md.append(", ".join(words) + "\n\n")
    
    # 写作模板
    if content.get('writing_template'):
        md.append("## 写作模板\n")
        for usage, template in content['writing_template'].items():
            md.append(f"### {usage}\n")
            md.append(f"```\n{template}\n```\n\n")
    
    return "".join(md)


def main():
    parser = argparse.ArgumentParser(
        description="将知识卡片 Word 文档转换为 JSON 和 Markdown 格式",
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument('docx_file', nargs='?', help='Word 文档路径（使用 --all 时可省略）')
    parser.add_argument('--output-dir', '-o', type=Path, help='输出目录')
    parser.add_argument('--all', '-a', action='store_true', help='转换 courses/ 目录下所有 docx 文件')
    
    args = parser.parse_args()
    
    if args.all:
        # 批量转换
        courses_dir = Path('courses')
        if not courses_dir.exists():
            print(f"错误: courses/ 目录不存在")
            sys.exit(1)
        
        for docx_file in courses_dir.rglob('*.docx'):
            print(f"\n处理: {docx_file}")
            try:
                convert_docx_to_json(docx_file, docx_file.parent)
            except Exception as e:
                print(f"✗ 失败: {e}")
    elif args.docx_file:
        docx_path = Path(args.docx_file)
        convert_docx_to_json(docx_path, args.output_dir)
    else:
        parser.print_help()
        sys.exit(1)
    
    print("\n✓ 转换完成!")


if __name__ == "__main__":
    main()
