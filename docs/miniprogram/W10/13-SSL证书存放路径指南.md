# SSL 证书存放路径指南（2026-09-29）

> **场景**：用户问 SSL 证书应该放 `/etc/ssl/certs/` 还是新建目录。
> **结论**：按域名分子目录放 `/etc/nginx/ssl/<domain>/`。

---

## 1. 系统目录（不要动）

### `/etc/ssl/certs/`

- **用途**：CA 根证书 + 中间证书池（系统用来验证别人的证书）
- **管理**：apt 包管理维护
- **风险**：你手动放进去的文件，apt upgrade 时可能被改名 / 删除 / 加软链覆盖
- **文件名规则**：hash 命名（如 `1234abcd.0`），不是按域名组织

### `/etc/ssl/private/`

- **用途**：系统级服务（Postfix / Dovecot）的私钥
- **管理**：apt 包管理维护
- **风险**：同上

### `/usr/local/share/ca-certificates/`

- **用途**：用户自定义 CA 证书
- **管理**：`update-ca-certificates` 命令
- **适用**：如果你自己签了 CA 证书给团队用

**这些目录都是给系统信任链用的，不是放你的网站证书的。**

---

## 2. 网站证书的正确位置

### 行业标准

| 项目 | 路径 |
|---|---|
| Let's Encrypt（certbot）| `/etc/letsencrypt/live/<domain>/` |
| Nginx 官方推荐 | `/etc/nginx/ssl/<domain>/` |
| Apache | `/etc/apache2/ssl/<domain>/` |
| Mozilla | `/etc/ssl/certs/<domain>/`（带子目录） |

### 推荐目录结构

```
/etc/nginx/ssl/
├── README.md                          ← 维护说明
│
├── wanglipingresume.com/              ← 主域名证书
│   ├── wanglipingresume.com.pem       ← 证书
│   ├── wanglipingresume.com.key       ← 私钥（chmod 600）
│   └── chain.pem                       ← 证书链（如果有）
│
├── ielts.wanglipingresume.com/        ← 雅思子域名证书
│   ├── ielts.wanglipingresume.com.pem
│   ├── ielts.wanglipingresume.com.key
│   └── chain.pem
│
└── blog.wanglipingresume.com/         ← 未来博客域名
    └── ...
```

---

## 3. 为什么这样组织

| 好处 | 说明 |
|---|---|
| **隔离** | 每个域名独立，`ls /etc/nginx/ssl/` 一眼看出有哪些 |
| **权限清晰** | `chmod 600 /etc/nginx/ssl/<domain>/*.key` 只影响一个域名 |
| **续期方便** | 1 年后续期只需替换一个目录 |
| **备份简单** | `tar czf backup.tgz /etc/nginx/ssl/<domain>/` |
| **不污染系统** | 不影响 apt 升级 |
| **Nginx 配置直观** | `ssl_certificate /etc/nginx/ssl/wanglipingresume.com/...pem;` |

---

## 4. 文件权限规范

```bash
# 目录：755（root 可写，其他可读）
sudo chmod 755 /etc/nginx/ssl/wanglipingresume.com

# 证书：644（所有人都能读，nginx worker 通常以 www-data / nobody 跑）
sudo chmod 644 /etc/nginx/ssl/wanglipingresume.com/wanglipingresume.com.pem

# 私钥：600（只有 root 能读）
sudo chmod 600 /etc/nginx/ssl/wanglipingresume.com/wanglipingresume.com.key

# 所有者：root
sudo chown -R root:root /etc/nginx/ssl/wanglipingresume.com/
```

---

## 5. 上传证书的命令模板

### 一次性命令（推荐）

```bash
# 在 Mac 上传
scp -i ~/Downloads/你的密钥.pem \
  ~/Downloads/<证书压缩包>.zip \
  admin@118.190.148.121:/tmp/

# 在 ECS 上
cd /tmp
unzip <证书压缩包>.zip
sudo mkdir -p /etc/nginx/ssl/wanglipingresume.com
sudo mv wanglipingresume.com.pem wanglipingresume.com.key /etc/nginx/ssl/wanglipingresume.com/
sudo chmod 600 /etc/nginx/ssl/wanglipingresume.com/wanglipingresume.com.key
sudo chmod 644 /etc/nginx/ssl/wanglipingresume.com/wanglipingresume.com.pem
sudo rm -rf /tmp/<证书压缩包>.zip  # 清理临时文件
```

### 验证

```bash
ls -la /etc/nginx/ssl/wanglipingresume.com/
# 输出:
# total 16
# drwxr-xr-x 3 root root 4096 Sep 29 12:00 .
# drwxr-xr-x 8 root root 4096 Sep 29 12:00 ..
# -rw-r--r-- 1 root root 4123 Sep 29 12:00 wanglipingresume.com.pem
# -rw------- 1 root root 1704 Sep 29 12:00 wanglipingresume.com.key
```

### Nginx 配置

```nginx
ssl_certificate     /etc/nginx/ssl/wanglipingresume.com/wanglipingresume.com.pem;
ssl_certificate_key /etc/nginx/ssl/wanglipingresume.com/wanglipingresume.com.key;
```

---

## 6. 常见误区

| ❌ 错 | ✅ 对 |
|---|---|
| 证书放 `/etc/ssl/certs/` | 放 `/etc/nginx/ssl/<domain>/` |
| 所有证书放同一个目录 | 按域名分子目录 |
| 私钥 `chmod 644` | 私钥 `chmod 600` |
| 证书用 `cp` 到 `/tmp/` 留着 | 用 `mv` 移走（不留备份） |
| 证书路径里有空格或中文 | 全英文无空格 |
| 多人共用一个私钥文件 | 每个域名独立 key |

---

## 7. 续期流程

证书1年到期后：

```bash
# 1. 下载新证书（阿里云控制台）
# 2. 在 ECS 上 scp 上传
scp -i ~/key.pem new.zip admin@118.190.148.121:/tmp/

# 3. 替换文件
cd /tmp && unzip new.zip
sudo cp wanglipingresume.com.pem wanglipingresume.com.key \
  /etc/nginx/ssl/wanglipingresume.com/
# 注意：用 cp（不是 mv），保留旧证书作备份
sudo chmod 600 /etc/nginx/ssl/wanglipingresume.com/wanglipingresume.com.key

# 4. 测试 + reload
sudo nginx -t
sudo systemctl reload nginx

# 5. 清理
rm /tmp/wanglipingresume.com.* /tmp/new.zip
```

---

## 8. 一句话总结

> **按域名分子目录放 `/etc/nginx/ssl/<domain>/`**，私钥 `chmod 600`，证书 `chmod 644`，所有者 root，Nginx 配置里写完整路径。**永远不要把网站证书放到 `/etc/ssl/certs/` 或 `/etc/ssl/private/`**。
<!-- v1.1 -->



---

## 9. 常见 Shell 转义坑（部署时必看）

### 9.1 `!` 历史扩展问题

**症状**：
```bash
$ echo "<!DOCTYPE html>"
-bash: !DOCTYPE: event not found
```

**原因**：bash 里 `!` 是历史扩展符（调用历史命令），即使在双引号里也会触发。

**解决**：用 heredoc **单引号** 版本：

```bash
# 正确写法（带引号的 EOF）
sudo tee /var/www/personal/index.html <<'EOF'
<!DOCTYPE html>
<html>
...
</html>
EOF

# 错误写法（双引号或无引号 EOF 仍会触发历史扩展）
sudo tee /var/www/personal/index.html <<EOF
<!DOCTYPE html>   # 报错！
EOF
```

**关键点**：**`<<'EOF'` 引号包 EOF**，这样整个 heredoc 内容不做任何变量/历史扩展。

### 9.2 其他常见转义坑

| 字符 | 在双引号里 | 在 heredoc 无引号 | 在 heredoc `<<'EOF'` | 解决 |
|------|----------|------------------|---------------------|------|
| `!` | 历史扩展 ❌ | 历史扩展 ❌ | 字面量 ✅ | 用单引号 |
| `$` | 变量扩展 | 变量扩展 | 字面量 ✅ | 用单引号或 `\$` |
| `` ` `` | 命令替换 | 命令替换 | 字面量 ✅ | 用单引号 |
| `\` | 转义符 | 转义符 | 字面量（但不转义） | 看具体场景 |
| `"` | 字符串结束 | 字面量 | 字面量 ✅ | 双引号里用 `"` |

### 9.3 写 HTML / JSON / SQL 时的金科玉律

**永远用单引号 heredoc**：
```bash
cat > file.html <<'EOF'
<!DOCTYPE html>
<html>
  <p>$variable 不会被扩展</p>
  <p>`command` 不会被执行</p>
</html>
EOF
```

**或者用 printf**（更可移植）：
```bash
printf '%s\n' '这是字面量文本' '$variable 不会扩展' '!history 不会触发' > file.txt
```

### 9.4 部署禁用 write 模式

临时禁用 bash 历史扩展：
```bash
set +H  # 关闭历史扩展（本次 session）
# 现在 echo "!" 不会触发
```

永久禁用（写入 ~/.bashrc）：
```bash
echo 'set +H' >> ~/.bashrc
```

但更推荐用**单引号 heredoc**，不会影响其他 shell 操作。

<!-- v3.1 -->
