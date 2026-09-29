#!/usr/bin/env python3
"""
.env 文件 # 不是注释 - 一键修复脚本

为什么会踩这个坑:
    .env 文件的 # 不是注释（如 `K=v#comment`，# 是值的一部分）
    写文件时如果不小心在 KEY=VALUE 后面加了 # xxx，python-dotenv 会把整个
    `v#xxx` 当成值。

修复方法:
    1. 直接在 vim 里手动编辑（最稳）
    2. 用这个 Python 脚本（一键）
"""

import re
import sys

if len(sys.argv) < 2:
    print("用法: python3 strip_env_comments.py <path-to-.env>")
    print("例:   sudo python3 strip_env_comments.py /opt/ielts_apply_seek/.env")
    sys.exit(1)

ENV_FILE = sys.argv[1]

# 备份
import shutil
BACKUP = ENV_FILE + ".bak"
shutil.copy2(ENV_FILE, BACKUP)
print(f"已备份到: {BACKUP}")

# 处理
with open(ENV_FILE, 'r', encoding='utf-8') as f:
    lines = f.readlines()

new_lines = []
fixed_count = 0
for line in lines:
    # 如果有 # 在 KEY=VALUE 后面，删掉 # 及其后的所有内容
    # 但要保留以 # 开头的整行注释行（虽然 .env 不识别，但保留无害）
    stripped = line.rstrip('\n')
    if stripped and not stripped.lstrip().startswith('#'):
        # 找第一个 #（但跳过 = 之前的位置）
        eq_idx = stripped.find('=')
        if eq_idx > 0:
            hash_idx = stripped.find('#', eq_idx)
            if hash_idx > 0:
                # 删除 # 后所有内容
                stripped = stripped[:hash_idx].rstrip()
                fixed_count += 1
    new_lines.append(stripped + '\n')

with open(ENV_FILE, 'w', encoding='utf-8') as f:
    f.writelines(new_lines)

print(f"修复完成: 清理了 {fixed_count} 行 # 后内容")
print()

# 验证
print("=== 修复后内容（只显示非空行） ===")
with open(ENV_FILE, 'r', encoding='utf-8') as f:
    for line in f:
        if line.strip():
            print(line.rstrip())

# 验证 SECRET 长度
print()
print("=== 关键值长度检查 ===")
for line in new_lines:
    if line.startswith("IELTS_BUDDY_WECHAT_SECRET="):
        val = line.split("=", 1)[1].strip()
        print(f"  WECHAT_SECRET 长度: {len(val)} (期望: 32)")
        if len(val) == 32:
            print(f"  ✅ 长度正确")
        else:
            print(f"  ⚠️ 长度异常（可能仍有 # 残留）")
    if line.startswith("IELTS_BUDDY_WECHAT_APPID="):
        val = line.split("=", 1)[1].strip()
        print(f"  WECHAT_APPID 长度: {len(val)} (期望: 18)")
        if len(val) == 18:
            print(f"  ✅ 长度正确")
# v1 -->

