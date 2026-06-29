"""课程管理命令"""

import click
from pathlib import Path

from ielts_buddy.services.course_service import CourseService


@click.group()
def course():
    """知识卡片课程管理"""
    pass


@course.command("list")
def list_courses():
    """列出所有课程"""
    svc = CourseService()
    courses = svc.list_courses()
    
    if not courses:
        click.echo("暂无课程。请先在 courses/ 目录下添加知识卡片。")
        return
    
    click.echo(f"\n📚 知识卡片课程列表（共 {len(courses)} 个主题）\n")
    click.echo(f"{'主题':<20} {'标题':<30} {'来源':<15}")
    click.echo("-" * 65)
    
    for c in courses:
        topic = c["topic"][:18]
        title = c["title"][:28] if c["title"] else ""
        source = c["source"][:13] if c["source"] else ""
        click.echo(f"{topic:<20} {title:<30} {source:<15}")


@course.command("show")
@click.argument("topic")
def show_course(topic: str):
    """显示课程内容"""
    svc = CourseService()
    
    # 尝试获取 Markdown 格式，直接 cat 文件
    md = svc.get_markdown(topic)
    if md:
        import sys
        sys.stdout.write(md)
        return
    
    # 退回到 JSON 格式
    course_data = svc.get_course(topic)
    if not course_data:
        click.echo(f"错误: 课程 '{topic}' 不存在", err=True)
        return
    
    content = course_data["content"]
    meta = course_data["meta"]
    
    click.echo(f"\n# {content.get('topic', topic)}\n")
    
    if meta.get("source"):
        click.echo(f"来源: {meta['source']}\n")
    
    # 核心例句
    if content.get("core_sentence"):
        cs = content["core_sentence"]
        click.echo("## 核心例句\n")
        if cs.get("en"):
            click.echo(f"英文: {cs['en']}")
        if cs.get("cn"):
            click.echo(f"中文: {cs['cn']}")
        click.echo()
    
    # 词汇
    if content.get("vocabulary"):
        click.echo("## 核心词汇\n")
        for v in content["vocabulary"]:
            word = v.get("word", "")
            phonetic = v.get("phonetic", "")
            meaning = v.get("meaning", "")
            click.echo(f"  • {word} {phonetic} - {meaning}")
        click.echo()
    
    # 写作模板
    if content.get("writing_template"):
        click.echo("## 写作模板\n")
        for usage, template in content["writing_template"].items():
            click.echo(f"\n### {usage}:\n{template}")
        click.echo()


@course.command("download")
@click.argument("topic")
@click.option("--path", "-p", default=".", help="下载到指定目录")
def download_course(topic: str, path: str):
    """下载课程原始文件"""
    svc = CourseService()
    docx_path = svc.get_docx_path(topic)
    
    if not docx_path:
        click.echo(f"错误: 课程 '{topic}' 的原始文件不存在", err=True)
        return
    
    import shutil
    dest = Path(path) / docx_path.name
    shutil.copy2(docx_path, dest)
    click.echo(f"✓ 已下载到: {dest}")


# 别名命令
@course.command("ls")
def ls_alias():
    """列出所有课程（list 的别名）"""
    list_courses()


@course.command("info")
@click.argument("topic")
def course_info(topic: str):
    """显示课程详细信息"""
    svc = CourseService()
    course_data = svc.get_course(topic)
    
    if not course_data:
        click.echo(f"错误: 课程 '{topic}' 不存在", err=True)
        return
    
    meta = course_data["meta"]
    content = course_data["content"]
    
    click.echo(f"\n📖 {meta.get('title', topic)}\n")
    click.echo(f"主题: {meta.get('topic', '')}")
    click.echo(f"来源: {meta.get('source', '')}")
    click.echo(f"标签: {', '.join(meta.get('tags', []))}")
    click.echo(f"版本: {meta.get('version', '')}")
    click.echo()
    
    # 词汇统计
    vocab = content.get("vocabulary", [])
    click.echo(f"核心词汇: {len(vocab)} 个")
    
    # 主题词汇统计
    theme_vocab = content.get("theme_vocab", {})
    total_theme = sum(len(words) for words in theme_vocab.values())
    click.echo(f"主题词汇: {total_theme} 个（{len(theme_vocab)} 个分类）")
    
    # 模板
    templates = content.get("writing_template", {})
    if templates:
        click.echo(f"写作模板: {len(templates)} 个")
