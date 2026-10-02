<div align="center">

# Hanaikada 花筏

[English](README.md) | 简体中文

</div>

浏览、搜索和管理你用 **Stable Diffusion WebUI**、**ComfyUI** 和 **InvokeAI** 生成的图片，
可以使用网页界面，也可以使用命令行。

Hanaikada（“花筏”：漂浮在水面上的花瓣）读取各平台写入图片的生成数据——WebUI 的 infotext、
ComfyUI 的工作流、InvokeAI 的元数据以及 NovelAI 的注释——把它们整理成统一的记录并建立索引，
让你可以：

- **浏览** WebUI、ComfyUI 和 InvokeAI 的输出文件夹（或任意文件夹）：快速的虚拟化网格，带文件夹
  封面、排序、展开“此处以下全部内容”的平铺视图，以及按平台、模型和采样器筛选。新图片一写入就会出现。
- **查看** 全屏图片，支持缩放、平移、幻灯片、胶片条，以及信息面板：提示词和每一项参数、与上一张
  图片相比的变化、每一个原始数据块（把 ComfyUI 工作流下载为 `.json` 即可拖回 ComfyUI）和 EXIF。
- **搜索** 提示词文本（三元组全文索引）、反向提示词、文件名、模型、LoRA、种子、步数、CFG、尺寸、
  方向、日期和标签；搜索条件保存在 URL 中。
- **标签**：为图片添加自己的标签和收藏，同时还有从元数据派生的标签（提示词、LoRA、模型、采样器、
  尺寸、InvokeAI 看板）。
- **管理文件**：移动、复制、重命名、删除（移入回收站）和上传，附属文件跟随图片，索引跟随每一次
  变更。可将选中的图片打包为 zip 下载。
- **对比** 两张图片，带滑块和提示词差异；查看**统计**：贡献热力图、每月图片数量，以及你最常用的
  模型、采样器和 LoRA。

设计、约定和已知缺陷见 [AGENTS.md](AGENTS.md)。

## 安装

```bash
python -m pip install hanaikada
hanaikada --help
```

需要 Python 3.10 或更新版本。网页界面已打包在安装包内，不需要 Node。

支持 Pydantic v1 和 v2（v1 需要 Python 3.10–3.13 和 `fastapi<0.126`）。

## 开始使用

```bash
hanaikada root add ~/stable-diffusion-webui     # 自动识别布局：sd-webui
hanaikada root add ~/ComfyUI                     # comfyui
hanaikada root add ~/invokeai                    # invokeai
hanaikada webui                                  # 在后台扫描并打开浏览器
```

根目录可以是安装文件夹，也可以是其中的某个输出文件夹。Hanaikada 从 WebUI 的 `config.json`
读取它的输出文件夹，使用 ComfyUI 的 `output/`（需要时还有 `temp/`），以及 InvokeAI 的
`outputs/images/` 连同它的缩略图和（只读的）看板。

## 命令行

```text
hanaikada
├── webui                    启动服务器并打开网页界面（--host --port --no-open --no-scan）
├── version | env
├── config  show | get | set | path
├── root    list | add <path> [--layout] [--name] [--no-index] | remove <id>
├── scan    [--root] [--path] [--full] [--reparse] [--wait]
├── ls      [<root:path>] --sort --asc --limit --recursive --all-roots
├── info    <file | root:path> [--raw]            解析单张图片；不需要索引
├── search  [text] --in --regex --platform --model --sampler --seed --tag --any-tag --not-tag ...
├── tag     list | add | remove | apply | unapply | show
├── export  <paths...> --what infotext|workflow|metadata --to <dir>
├── move | copy <src...> <dst>    rename <path> <new-name>    delete <paths...>    mkdir <path>
└── thumbs  generate | clear
```

路径的写法是 `<root-id>:<相对路径>`，或者根目录内的磁盘路径。所有列表类命令都接受 `--json`，
输出与 API 返回相同的记录；`--debug` 在每一级命令上都可用。网页界面的服务器运行时，
`hanaikada scan` 会把扫描交给它执行。

```bash
hanaikada info ~/Downloads/ComfyUI_00042_.png            # 这张图片是怎么生成的？
hanaikada search "cherry blossoms" --platform comfyui --json
hanaikada search --model animagineXL --min-steps 30 --tag favorite
hanaikada export 1a2b3c4d:output/ComfyUI_00042_.png --what workflow --to ./workflows
```

设置保存在数据目录的 `settings.toml` 中（`hanaikada config path`），任何一项都可以用环境变量固定，
例如 `HANAIKADA_SERVER__PORT=8000`。

## 嵌入

```python
from hanaikada import HanaikadaServer, ImageRoot

server = HanaikadaServer(
    data_dir="./hanaikada-data",
    image_roots=[ImageRoot("/srv/ComfyUI", name="ComfyUI")],
    lock_image_roots=True,        # 用户不能添加、修改或移除文件夹
    combined_view=True,           # 在浏览页提供“全部文件夹”；设置中显示为已锁定
    port=0,                       # 任意空闲端口
    api_prefix="/images",         # 避免与宿主自己的路由冲突
)
url = server.start()              # http://127.0.0.1:54123/images
server.stop()
```

## 安全

服务器默认监听 `127.0.0.1`，并检查每个请求的 `Host` 和 `Origin`。要监听其他地址，请先设置访问令牌
（`hanaikada config set server.access_token <secret>`）。不会读取或写入你添加的根目录之外的任何
内容，也不会覆盖任何文件。

## 开发

```bash
pip install -e ".[dev]"
python scripts/dev.py web-install
python scripts/dev.py dev          # 同时启动 API 和 Vite，支持热重载
python scripts/dev.py check        # CI 运行的内容
```

## 许可证

GPL-3.0。
