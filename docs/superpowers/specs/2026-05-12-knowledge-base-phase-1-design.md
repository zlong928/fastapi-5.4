# 个人知识库系统 - 第一阶段设计文档

**日期：** 2026-05-12  
**阶段：** Phase 1：上传 + 解析 + 详情页  
**状态：** 等待审批

---

## 1. 产品目标

### 愿景
把一年内在微信收藏、浏览器书签、随手截图里散落的资料，打进一个能上传、能分类、能搜索、能回顾的地方。

### 第一阶段目标
实现核心闭环：**用户上传文件 → 系统自动解析 → 查看详情页**

用户可以：
- 上传 PDF / Markdown / TXT 文件
- 实时看到解析进度和状态
- 查看解析后的纯文本内容
- 重试失败的解析
- 删除不需要的文档

---

## 2. 数据模型设计

### 2.1 documents 表

存储文档元信息和解析结果。

```python
class Document(Base):
    __tablename__ = "documents"
    
    id: int                          # 主键
    user_id: int                     # 用户 ID，关联 users 表
    title: str                       # 文档标题（初始为原始文件名，可修改）
    original_filename: str           # 原始上传文件名
    stored_filename: str             # 服务器存储的安全文件名（UUID.ext）
    original_file_path: str          # 文件相对路径（uploads/{user_id}/{yyyy}/{mm}/{uuid}.ext）
    file_size: int                   # 文件大小（字节）
    mime_type: str                   # MIME 类型
    source_type: str                 # 文件类型：pdf / markdown / txt
    
    parsed_text: Optional[str]       # 解析后的纯文本
    status: str                      # 状态：pending / processing / parsed / failed / deleted
    error_message: Optional[str]     # 失败原因（status=failed 时有值）
    
    created_at: datetime             # 创建时间（上传时）
    updated_at: datetime             # 更新时间（状态改变时）
    uploaded_at: datetime            # 上传时间
    parsed_at: Optional[datetime]    # 解析成功时间
    
    user: relationship               # 关联 User
    events: relationship             # 关联 DocumentEvent
    chunks: relationship             # 关联 Chunk
```

**设计说明：**
- `user_id` 保证用户隔离
- `status` 预留完整状态机（pending → processing → parsed 或 failed）
- `error_message` 便于前端展示失败原因
- `parsed_at` 用于追踪解析性能
- `original_file_path` 存相对路径，便于后续迁移

---

### 2.2 document_events 表

记录文档生命周期事件，便于操作审计和日志展示。

```python
class DocumentEvent(Base):
    __tablename__ = "document_events"
    
    id: int                          # 主键
    document_id: int                 # 文档 ID
    user_id: int                     # 用户 ID（冗余，便于按用户查询）
    event_type: str                  # 事件类型
    message: str                     # 事件描述
    metadata: Optional[str]          # JSON 格式的扩展信息
    created_at: datetime             # 事件发生时间
    
    document: relationship            # 关联 Document
```

**事件类型（第一阶段）：**
- `uploaded` — 文件上传成功
- `parse_started` — 开始解析
- `parse_succeeded` — 解析成功
- `parse_failed` — 解析失败
- `retry_started` — 开始重新解析
- `deleted` — 文档删除（软删除）

**metadata 示例：**
```json
{
  "parse_failed": { "error": "PDF 损坏" },
  "retry_started": { "retry_count": 1 },
  "deleted": { "reason": "用户手动删除" }
}
```

---

### 2.3 chunks 表

为未来 RAG / AI 问答预留。当前只做表结构，不填充数据。

```python
class Chunk(Base):
    __tablename__ = "chunks"
    
    id: int                          # 主键
    document_id: int                 # 文档 ID
    chunk_index: int                 # 块索引（从 0 开始）
    chunk_text: str                  # 块内容
    
    embedding: Optional[bytes]       # 向量（当前为 None，预留给未来 AI 模型）
    token_count: Optional[int]       # Token 数量（当前为 None）
    
    created_at: datetime             # 创建时间
    
    document: relationship            # 关联 Document
```

**设计说明：**
- 当前解析完成后不生成 chunks
- 预留 `embedding` 字段给向量化
- 预留 `token_count` 给 LLM token 计费
- 后续可添加 `batch_id` 关联批量向量化任务

---

## 3. 文件存储设计

### 3.1 文件路径结构

```
uploads/
├── {user_id}/
│   ├── 2026/
│   │   ├── 05/
│   │   │   ├── abc123de-4567-89ab-cdef-0123456789ab.pdf
│   │   │   ├── def456ab-7890-cdef-0123-456789abcdef.md
│   │   │   └── ghi789cd-abcd-ef01-2345-6789abcdef01.txt
│   │   └── 04/
│   │       └── ...
│   └── ...
└── ...
```

**规则：**
- 按 `user_id` 隔离，防止用户间数据泄露
- 按年月分层，便于清理和备份
- 文件名使用 UUID + 原扩展名，避免碰撞和路径穿越
- 数据库存相对路径 `uploads/{user_id}/{yyyy}/{mm}/{uuid}.{ext}`

### 3.2 文件安全处理

```python
# 伪代码
def safe_store_file(user_id: int, original_filename: str, file_content: bytes) -> str:
    """
    安全存储文件，返回相对路径。
    """
    # 1. 校验文件名和扩展名
    ext = validate_filename(original_filename)
    
    # 2. 生成安全文件名
    stored_filename = f"{uuid.uuid4()}.{ext}"
    
    # 3. 生成目录路径（按年月）
    now = datetime.now()
    dir_path = f"uploads/{user_id}/{now.year:04d}/{now.month:02d}"
    
    # 4. 创建目录
    os.makedirs(dir_path, exist_ok=True)
    
    # 5. 写入文件
    file_path = os.path.join(dir_path, stored_filename)
    with open(file_path, 'wb') as f:
        f.write(file_content)
    
    # 6. 返回数据库存储的相对路径
    return os.path.join(dir_path, stored_filename)
```

---

## 4. 文档解析流程

### 4.1 状态流转图

```
pending
   ↓
processing
   ↓
┌─────────────┬──────────────┐
↓             ↓
parsed        failed
   ↓             ↓
(查看详情)    (可重试)
```

**状态说明：**
- `pending` — 文件已上传，等待解析
- `processing` — 正在解析中
- `parsed` — 解析成功，`parsed_text` 已填充
- `failed` — 解析失败，`error_message` 已填充
- `deleted` — 用户删除，软删除

### 4.2 解析流程（同步处理）

```python
def parse_document(document_id: int) -> Document:
    """
    解析文档。当前同步执行，但架构为异步预留。
    """
    document = db.get(Document, document_id)
    
    # 1. 状态改为 processing，记录事件
    document.status = "processing"
    db.add_event(document_id, "parse_started", "开始解析")
    db.commit()
    
    try:
        # 2. 根据文件类型解析
        file_path = get_upload_dir() / document.original_file_path
        
        if document.source_type == "pdf":
            parsed_text = parse_pdf(file_path)
        elif document.source_type == "markdown":
            parsed_text = parse_markdown(file_path)
        elif document.source_type == "txt":
            parsed_text = parse_txt(file_path)
        
        # 3. 保存解析结果
        document.parsed_text = parsed_text
        document.status = "parsed"
        document.parsed_at = datetime.now(timezone.utc)
        db.add_event(document_id, "parse_succeeded", "解析成功")
        db.commit()
        
    except Exception as e:
        # 4. 失败处理
        document.status = "failed"
        document.error_message = str(e)
        db.add_event(document_id, "parse_failed", f"解析失败：{str(e)}")
        db.commit()
    
    return document
```

### 4.3 解析器实现

```python
# app/services/document_parser.py

def parse_pdf(file_path: str) -> str:
    """使用 pypdf 提取 PDF 文本。"""
    import pypdf
    text = ""
    with open(file_path, 'rb') as f:
        reader = pypdf.PdfReader(f)
        for page in reader.pages:
            text += page.extract_text()
    return text.strip()

def parse_markdown(file_path: str) -> str:
    """读取 Markdown 文件。"""
    with open(file_path, 'r', encoding='utf-8') as f:
        return f.read().strip()

def parse_txt(file_path: str) -> str:
    """读取 TXT 文件。"""
    with open(file_path, 'r', encoding='utf-8') as f:
        return f.read().strip()
```

---

## 5. API 设计

### 5.1 上传单个文件

**端点：** `POST /documents/upload`

**请求：**
```
Content-Type: multipart/form-data

file: <PDF/Markdown/TXT 文件>
title: "可选：自定义标题" （可省略，默认为文件名）
```

**响应（200）：**
```json
{
  "id": 1,
  "user_id": 1,
  "title": "我的 PDF",
  "original_filename": "my-pdf.pdf",
  "source_type": "pdf",
  "status": "parsed",
  "parsed_text": "...",
  "created_at": "2026-05-12T10:00:00Z",
  "parsed_at": "2026-05-12T10:00:02Z"
}
```

**错误响应（400）：**
```json
{
  "detail": "Unsupported file type. Only PDF, Markdown, and TXT are allowed."
}
```

---

### 5.2 批量上传文件

**端点：** `POST /documents/batch-upload`

**请求：**
```
Content-Type: multipart/form-data

files: [<file1>, <file2>, ...]
```

**响应（200）：**
```json
{
  "documents": [
    { "id": 1, "status": "parsed", ... },
    { "id": 2, "status": "failed", "error_message": "..." }
  ]
}
```

---

### 5.3 文档列表

**端点：** `GET /documents`

**查询参数：** （第一阶段先不做搜索和筛选）
- `skip: int = 0`
- `limit: int = 20`

**响应（200）：**
```json
{
  "total": 100,
  "items": [
    {
      "id": 1,
      "title": "我的 PDF",
      "source_type": "pdf",
      "status": "parsed",
      "file_size": 512000,
      "created_at": "2026-05-12T10:00:00Z",
      "parsed_at": "2026-05-12T10:00:02Z"
    }
  ]
}
```

---

### 5.4 文档详情

**端点：** `GET /documents/{document_id}`

**响应（200）：**
```json
{
  "id": 1,
  "user_id": 1,
  "title": "我的 PDF",
  "original_filename": "my-pdf.pdf",
  "source_type": "pdf",
  "status": "parsed",
  "file_size": 512000,
  "mime_type": "application/pdf",
  "parsed_text": "...",
  "created_at": "2026-05-12T10:00:00Z",
  "uploaded_at": "2026-05-12T10:00:00Z",
  "parsed_at": "2026-05-12T10:00:02Z"
}
```

---

### 5.5 重试解析

**端点：** `POST /documents/{document_id}/retry-parse`

**请求：** 无

**响应（200）：**
```json
{
  "id": 1,
  "status": "parsed",
  "parsed_text": "...",
  "parsed_at": "2026-05-12T10:00:05Z"
}
```

**错误响应（400）：**
```json
{
  "detail": "Document is not in failed state, cannot retry."
}
```

---

### 5.6 软删除

**端点：** `DELETE /documents/{document_id}`

**请求：** 无

**响应（200）：**
```json
{
  "id": 1,
  "status": "deleted"
}
```

---

### 5.7 文档事件日志

**端点：** `GET /documents/{document_id}/events`

**响应（200）：**
```json
{
  "events": [
    {
      "id": 1,
      "event_type": "uploaded",
      "message": "文件上传成功",
      "created_at": "2026-05-12T10:00:00Z"
    },
    {
      "id": 2,
      "event_type": "parse_started",
      "message": "开始解析",
      "created_at": "2026-05-12T10:00:01Z"
    },
    {
      "id": 3,
      "event_type": "parse_succeeded",
      "message": "解析成功",
      "metadata": { "char_count": 5000 },
      "created_at": "2026-05-12T10:00:02Z"
    }
  ]
}
```

---

## 6. 前端页面设计

### 6.1 上传页面（/upload）

**功能：**
- 显示上传区域（支持拖拽或点击选择）
- 支持单个或批量选择
- 显示选中文件列表和文件类型校验提示
- 显示上传进度
- 上传成功后显示每个文件的状态（pending → processing → parsed 或 failed）
- 可以点击已上传文件进入详情页
- 可以点击失败文件重试

**UI 示例：**
```
┌─────────────────────────────────┐
│ 拖拽文件到这里或点击选择        │
│ 支持 PDF, Markdown, TXT         │
└─────────────────────────────────┘

选中文件：
- [ ] my-pdf.pdf (512 KB) - 待上传
- [ ] note.md (8 KB) - 待上传

[上传按钮]

上传队列：
| 文件名 | 类型 | 状态 | 操作 |
|--------|------|------|------|
| my-pdf.pdf | pdf | pending | - |
| note.md | md | processing | - |
| old-note.txt | txt | parsed | 查看详情 |
| bad-file.pdf | pdf | failed | 重试 |
```

---

### 6.2 文档列表页（/documents）

**功能：**
- 展示所有文档列表（按创建时间倒序）
- 显示文档标题、文件类型、状态、上传时间
- 支持点击进入详情页
- 支持删除（软删除，需确认）

**UI 示例：**
```
我的文档（共 3 个）

| 标题 | 类型 | 状态 | 上传时间 | 操作 |
|------|------|------|---------|------|
| 我的 PDF | pdf | parsed | 2026-05-12 | 详情 删除 |
| 项目笔记 | md | parsed | 2026-05-11 | 详情 删除 |
| 草稿 | txt | failed | 2026-05-10 | 详情 删除 |
```

---

### 6.3 文档详情页（/documents/{id}）

**功能：**
- 显示文档元信息（标题、文件名、文件大小、类型、状态）
- 显示 parsed_text（如果状态为 parsed）
- 显示失败原因（如果状态为 failed）
- 显示操作日志（timeline）
- 支持修改标题
- 支持重试解析（如果 status = failed）
- 支持删除

**UI 示例：**
```
┌────────────────────────────────┐
│ 我的 PDF                       │
│ 原始文件：my-pdf.pdf           │
│ 文件大小：512 KB               │
│ 文件类型：PDF                  │
│ 状态：✓ 已解析                 │
│                                │
│ [修改标题] [重试] [删除]       │
└────────────────────────────────┘

解析内容：
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
本文介绍了...（纯文本预览）

...

操作日志：
┌──────┬──────────────────────────┐
│ 时间 │ 事件                     │
├──────┼──────────────────────────┤
│ 10:00│ 文件上传成功             │
│ 10:01│ 开始解析                 │
│ 10:02│ 解析成功                 │
└──────┴──────────────────────────┘
```

---

## 7. 项目结构更新

### 新增文件

```
app/
├── models/
│   ├── document.py              # Document 模型
│   ├── document_event.py        # DocumentEvent 模型
│   ├── chunk.py                 # Chunk 模型（预留）
│   └── __init__.py              # 导出所有模型
│
├── schemas/
│   ├── document.py              # Document Pydantic schemas
│   ├── document_event.py        # Event schemas
│   └── __init__.py
│
├── services/
│   ├── document_service.py      # 文档业务逻辑
│   ├── document_parser.py       # PDF/MD/TXT 解析
│   ├── file_storage.py          # 文件存储和安全
│   └── event_logger.py          # 事件日志记录
│
├── api/routes/
│   ├── documents.py             # 文档 API 端点
│   ├── events.py                # 事件 API（可选）
│   └── __init__.py
│
├── db/
│   ├── migrations/              # Alembic 迁移
│   │   ├── env.py
│   │   ├── script.py.mako
│   │   └── versions/
│   │       └── 001_create_documents_tables.py
│   └── session.py               # 已有，不改动

docs/
└── superpowers/
    └── specs/
        └── 2026-05-12-knowledge-base-phase-1-design.md
```

---

## 8. 数据库迁移计划

### 第一阶段迁移文件

创建 Alembic 迁移：`001_create_documents_tables.py`

**包含操作：**
1. 创建 `documents` 表
2. 创建 `document_events` 表
3. 创建 `chunks` 表
4. 添加外键约束
5. 添加索引（user_id, status, created_at）

---

## 9. 验收标准

完成后需要满足：

- [ ] 能上传 PDF / Markdown / TXT 文件
- [ ] 上传后自动解析，状态显示为 pending → processing → parsed
- [ ] 解析失败时状态为 failed，显示错误原因
- [ ] 可以重试失败的解析
- [ ] 可以查看文档详情页，看到 parsed_text
- [ ] 可以查看操作日志（timeline）
- [ ] 可以软删除文档（status = deleted）
- [ ] 数据按 user_id 隔离，不同用户看不到彼此数据
- [ ] 文件存储在文件系统，使用 UUID 安全命名
- [ ] 原始文件路径存相对路径，易于迁移
- [ ] chunks 表已建，为未来 RAG 预留
- [ ] 后端代码清晰分层（models, schemas, services）
- [ ] API 返回 Pydantic schemas
- [ ] 前端能跑通完整闭环（上传 → 解析 → 详情）
- [ ] 项目可正常启动，现有功能（认证、OAuth）不受影响
- [ ] 所有表和关键服务有基础测试

---

## 10. 后续迭代计划

**第二阶段：** 标签系统 + 资料集系统
- 添加 tags, document_tags, collections, document_collections 表
- 实现标签 CRUD 和关联
- 实现资料集 CRUD 和文档关联

**第三阶段：** 全文搜索 + 组合筛选
- 实现 SQLite FTS5 搜索
- 支持关键词 + 标签 + 文件类型 + 状态 + 上传时间 + 资料集组合筛选

**第四阶段：** RAG / AI 问答
- 填充 chunks 表
- 生成向量（embedding）
- 实现 RAG 搜索和 AI 问答

---

## 11. 技术栈

- **后端框架：** FastAPI
- **ORM：** SQLAlchemy 2.0
- **数据库：** SQLite
- **文件处理：** pypdf（PDF）、原生读文件（MD/TXT）
- **用户认证：** JWT + OAuth（现有）
- **前端框架：** React + Vite（复用现有）
- **数据库迁移：** Alembic

---

## 12. 风险评估和缓解

| 风险 | 影响 | 缓解方案 |
|------|------|--------|
| PDF 解析失败 | 用户体验差 | 使用可靠的 pypdf 库，提供清晰错误信息，支持重试 |
| 文件大小限制 | 上传大文件卡顿 | 限制上传大小（如 100 MB），前端提示 |
| 文件存储空间 | 磁盘满 | 监控上传目录大小，定期清理已删除文件 |
| 并发上传冲突 | 数据不一致 | SQLite 原生支持行级锁，UUID 避免命名冲突 |
| 用户隔离漏洞 | 数据泄露 | 所有查询加 user_id 过滤，单元测试验证 |

---

## 13. 配置和部署

### 环境变量

```bash
# .env

# 上传文件目录（默认 ./uploads）
UPLOAD_DIR=./uploads

# 单个文件大小限制（字节，默认 100 MB）
MAX_FILE_SIZE=104857600

# 批量上传文件数限制（默认 10）
MAX_BATCH_FILES=10
```

### 目录创建

启动时自动创建 `./uploads` 目录，确保文件存储位置可写。

---

## 14. 测试计划

### 单元测试

- 文档解析器（PDF/MD/TXT）
- 文件存储和安全处理
- 事件日志记录
- 权限隔离（user_id）

### 集成测试

- 上传单个文件 → 自动解析 → 查看详情
- 上传批量文件 → 查看状态
- 失败重试 → 验证成功
- 软删除 → 验证不再出现

### 前端测试

- 上传页面拖拽和选择
- 列表页面分页
- 详情页面修改和操作
- 权限隔离（登出后看不到数据）

---

## 结论

这个设计在最小增量的基础上，实现了完整的上传→解析→查看闭环，并为后续的标签、资料集、搜索、RAG 功能预留了扩展空间。代码结构清晰，易于维护和迭代。
