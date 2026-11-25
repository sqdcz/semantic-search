# semantic-search

Windows 本地文件语义搜索工具。按 `Win+Alt+S` 唤起搜索框，用自然语言找文件——不只是文件名匹配，还能理解意思。

![license](https://img.shields.io/badge/license-MIT-blue.svg) ![platform](https://img.shields.io/badge/platform-Windows%2010%2F11-blue.svg)

## 它解决什么问题

Everything 按文件名搜索很快，但你想找"上次那个讲显卡驱动的文档"时，如果文件名不含这些词就搜不到。这个工具把两条路合起来：

- **关键词召回**：Everything SDK（文件名/路径）+ Windows Search 索引（文件内容）
- **语义重排**：EmbeddingGemma 300M 把查询和候选文件转成 768 维向量，按语义相似度排序
- **混合评分**：65% 语义 + 35% 关键词

全部本地运行，不联网上传任何文件内容。

## 功能

- `Win+Alt+S` 全局热键唤起，`Win+S` 保持系统原生搜索不变
- 系统托盘常驻，右键可开关机自启、退出
- 输入即搜，↑↓ 选择，Enter 打开，Ctrl+C 复制路径
- 首次启动自动下载模型和依赖（国内高速源，约 320MB）
- 模型缺失或未就绪时自动降级为纯关键词搜索，不会崩

## 快速开始

### 方式一：直接用 exe（推荐）

1. 从 Releases 下载 `SemanticSearch.exe`，放到任意文件夹
2. 双击运行，托盘出现放大镜图标
3. 按 `Win+Alt+S` 搜索
4. 首次运行会自动下载模型和依赖到 exe 同目录的 `bin/`，约 320MB，耐心等几分钟

开机自启：托盘右键 → 勾选"开机自启"。

### 方式二：源码运行

需要 Python 3.8+（带 tkinter）。

```bash
git clone https://github.com/sqdcz/semantic-search.git
cd semantic-search
pip install pyinstaller pystray pywin32 pillow
python scripts/setup_deps.py     # 下载模型和依赖
python scripts/app.py            # 启动
```

打包成 exe：

```bash
python -m PyInstaller --noconfirm scripts/SemanticSearch.spec
# 产物在 dist/SemanticSearch.exe
```

## 技术栈

| 组件 | 用途 |
| --- | --- |
| EmbeddingGemma 300M (Q8_0) | 文本嵌入，768 维，支持 100+ 语言 |
| llama.cpp | CPU 推理，OpenAI 兼容 embeddings API |
| Everything SDK | 毫秒级文件名/路径索引 |
| Windows Search (OLE DB) | 文件内容全文检索 |
| pystray + ctypes RegisterHotKey | 系统托盘与全局热键 |
| PyInstaller | 单文件 exe 打包 |

## 目录结构

```
semantic-search/
├── scripts/
│   ├── app.py                  # 主程序：托盘 + 热键 + 服务管理
│   ├── search_core.py          # 混合搜索核心
│   ├── everything_client.py    # Everything SDK 封装
│   ├── setup_deps.py           # 依赖自动下载
│   └── SemanticSearch.spec     # PyInstaller 配置
├── bin/                        # 运行时依赖（不入库，自动下载）
│   ├── embeddinggemma-300M-Q8_0.gguf
│   ├── llama-server.exe + DLLs
│   └── Everything64.dll
└── README.md
```

## 常见问题

**热键没反应**：确认托盘有图标；若被其他软件占用 `Win+Alt+S`，右键托盘"打开搜索"。

**结果相关度是整数**：语义服务未就绪，当前是纯关键词模式。运行 `python scripts/setup_deps.py` 补全依赖。

**Everything 相关错误**：需要安装 [Everything](https://www.voidtools.com/) 并保持运行。

## License

本项目代码为 MIT License。注意运行时下载的 **EmbeddingGemma 模型** 遵循 Google 的 Gemma Terms of Use，**llama.cpp** 与 **Everything** 各有其独立许可，使用时请自行遵守相应条款。
