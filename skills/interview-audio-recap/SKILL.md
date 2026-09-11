---
name: interview-audio-recap
description: 面试录音本地转写与复盘。当用户提供面试/会议录音文件（m4a/mp3/wav 等）并要求"解析/转写/复盘"时触发。全流程本地运行不上传外部服务，产出带时间戳的转写文本 + 结构化复盘报告（逐题评分/短板清单/下一步行动）。含并行转写提速方案与踩坑记录。
agent_created: true
---

# 面试录音转写与复盘

## 适用场景
用户提供面试录音（微信语音 m4a / 手机录音 mp3 / wav），要求解析内容、转写文字、复盘表现。

## 环境准备（一次性）

**关键：必须用国内 pip 镜像**，PyPI 官方源实测卡死 16 分钟无进展。

```bash
# 1) 建独立 venv（用托管 Python）
"C:/Users/l32524/.workbuddy/binaries/python/versions/3.13.12/python.exe" -m venv "C:/Users/l32524/.venv-whisper"

# 2) 用清华源安装（1-2 分钟完成；官方源会卡死）
"C:/Users/l32524/.venv-whisper/Scripts/python.exe" -m pip install faster-whisper \
  -i https://pypi.tuna.tsinghua.edu.cn/simple --progress-bar off --timeout 60
```

依赖：faster-whisper 1.2.1（含 ctranslate2/av/onnxruntime/tokenizers）

## 转写流程

### 1) 先探测音频时长
```python
import av
c = av.open(path)
print(c.duration/1000000/60, '分钟')
```

### 2) 选择转写策略（关键决策）

| 音频时长 | 策略 | 预计耗时 |
|---|---|---|
| < 10 分钟 | 单进程 small，beam_size=5 | 2-5 分钟 |
| 10-60 分钟 | **分段并行**（4 段 × 3 线程 + beam_size=1） | 15-25 分钟 |
| > 60 分钟 | 分段并行（6-8 段 × 2 线程） | 30-50 分钟 |

**血泪教训**：单进程 8 线程跑 47 分钟音频只有 0.53x 实时（全量需 88 分钟）。改为 4 段并行 + 贪心解码后降到 20.5 分钟，**提速 4 倍**。

### 3) 运行并行转写脚本

见 `scripts/transcribe_parallel.py`。核心参数：
- `N_SEG = 4`（段数）、`THREADS_PER = 3`（每段线程，两者乘积 ≈ CPU 核数）
- `beam_size=1`（贪心解码，比 beam_size=5 快 2-3 倍，对话场景质量损失可接受）
- `vad_filter=True`（过滤静音，进一步提速）
- `initial_prompt` 传入场景描述可提升专有名词识别率

**模型缓存**：设置 `HF_ENDPOINT=https://hf-mirror.com` 加速下载；small 模型约 480MB，首次加载含下载约 160 秒。

### 4) 转写文本处理
- 输出格式：`[MM:SS] 文本`
- 常见识别错误需人工校正：人名、技术名词（如 "Rose GS"→Node.js、"MangoDB"→MongoDB、"费特一批"→fitap）
- 代码题/看题环节转写质量差（面试官与候选人看屏幕不说话），需结合上下文推断

## 复盘分析框架

按以下 7 节产出 HTML 报告：

1. **面试概况** —— 形式/时长/语言/技术栈/整体评价 + **与预判的差异**（重点！实际考察方向常与 JD 和准备方向不符）
2. **流程时间轴** —— 按时间段还原（自我介绍/背景追问/基础题/代码题/项目深挖/反问），标注各段时长占比 → **时长占比揭示考察重心**
3. **逐题表现评分** —— 表格：问题 | 表现（好/中/差）| 点评与优化答案。末尾统计"好X/中Y/差Z"
4. **面试官透露的关键信息** —— 业务方向、技术栈、团队规模（比 JD 更真实，可修正此前调研偏差）
5. **暴露的短板清单** —— 按优先级排序，每条附改进动作
6. **可复用的经验** —— 3 条通用规律（如"自我介绍必须主动抛规模数字""基础题要能举例""答不上来时的正确姿势"）
7. **下一步行动** —— 按时间粒度（今晚/明天/本周）

## 落地动作（复盘后必做）

1. 复盘 HTML 存入工作区，加入「学习中心.html」导航
2. 更新「求职复习进度中枢.md」的**面试记录表**（追加行：日期/公司/轮次/被问题目/复盘待补）
3. git 提交推送（注意：可能与远程分叉，需先 fetch 分析再 merge）
4. 若暴露出知识短板 → 同步更新对应学习手册或复习计划

## 踩坑记录

| 问题 | 现象 | 解决 |
|---|---|---|
| PyPI 官方源慢 | pip install 卡 16 分钟无输出 | 换清华源 `-i https://pypi.tuna.tsinghua.edu.cn/simple` |
| 单进程转写太慢 | 47min 音频需 88 分钟 | 分段并行 + beam_size=1 |
| 沙箱文件视图不一致 | Write 的文件 bash 看不到 | 用 heredoc 内联执行，或 dangerouslyDisableSandbox |
| 后台任务无输出 | `\| tail -8` 缓冲导致看不到进度 | 不加 tail，直接输出 |
| mvhd 找不到 | 微信 m4a 解析不出时长 | 用 av 库读 `c.duration` |

## 隐私提示
面试录音含公司/面试官信息，**转写与复盘全流程本地运行，不上传任何外部服务**；转写文本存 `.workbuddy/`（已被 .gitignore 排除）。
