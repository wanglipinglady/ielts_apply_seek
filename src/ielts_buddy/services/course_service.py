"""课程服务：管理知识卡片内容"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional


class CourseService:
    """知识卡片课程服务"""
    
    def __init__(self, courses_dir: Path | None = None) -> None:
        if courses_dir is None:
            # 获取项目根目录下的 courses 目录
            # 从 src/ielts_buddy/services/course_service.py 向上三级
            self._courses_dir = Path(__file__).resolve().parents[3] / "courses"
        else:
            self._courses_dir = courses_dir
    
    def list_courses(self) -> list[dict]:
        """列出所有课程"""
        courses = []
        if not self._courses_dir.exists():
            return courses
        
        for topic_dir in self._courses_dir.iterdir():
            if not topic_dir.is_dir():
                continue
            
            meta_path = topic_dir / "meta.json"
            content_path = topic_dir / "content.json"
            
            if not meta_path.exists():
                continue
            
            try:
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
                courses.append({
                    "topic": meta.get("topic", topic_dir.name),
                    "title": meta.get("title", ""),
                    "source": meta.get("source", ""),
                    "path": str(topic_dir)
                })
            except (json.JSONDecodeError, Exception):
                continue
        
        return sorted(courses, key=lambda x: x["topic"])
    
    def get_course(self, topic: str) -> Optional[dict]:
        """获取指定课程内容"""
        # 精确匹配目录名
        course_path = self._courses_dir / topic
        if not course_path.exists():
            # 尝试模糊匹配
            for d in self._courses_dir.iterdir():
                if d.is_dir() and topic in d.name:
                    course_path = d
                    break
            else:
                return None
        
        content_path = course_path / "content.json"
        meta_path = course_path / "meta.json"
        
        if not content_path.exists():
            return None
        
        try:
            content = json.loads(content_path.read_text(encoding="utf-8"))
            meta = {}
            if meta_path.exists():
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
            
            return {
                "topic": topic,
                "meta": meta,
                "content": content,
                "path": str(course_path)
            }
        except (json.JSONDecodeError, Exception):
            return None
    
    def get_markdown(self, topic: str) -> Optional[str]:
        """获取 Markdown 格式内容"""
        course_path = self._courses_dir / topic
        if not course_path.exists():
            for d in self._courses_dir.iterdir():
                if d.is_dir() and topic in d.name:
                    course_path = d
                    break
            else:
                return None
        
        md_path = course_path / "content.md"
        if md_path.exists():
            return md_path.read_text(encoding="utf-8")
        return None
    
    def get_docx_path(self, topic: str) -> Optional[Path]:
        """获取原始 docx 文件路径"""
        course_path = self._courses_dir / topic
        if not course_path.exists():
            for d in self._courses_dir.iterdir():
                if d.is_dir() and topic in d.name:
                    course_path = d
                    break
            else:
                return None
        
        # 查找 docx 文件
        for f in course_path.glob("*.docx"):
            return f
        return None
