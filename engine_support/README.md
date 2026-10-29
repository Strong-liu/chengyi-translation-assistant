# 百度翻译后端与英文专名保护

桌面默认使用百度大模型文本翻译（`service_mode=llm`），通过 `BAIDU_API_KEY` 鉴权，并用翻译指令指定学术风格。它与 `domain=academic` 的学术论文领域 API 是两种服务，凭据、开通条件和额度分别管理。程序不会在失败时改用其他翻译服务。

当前文本翻译直接通过 HTTPS 调用百度官方接口，不需要 trans-cli、Node.js 或额外的命令行程序。开发目录可能在 `bin/` 保留许可证、版本和校验信息，用于记录早期集成来源；旧 `trans.exe` 不属于当前运行依赖，不应进入源码仓库或新版安装包。

## 在线接口与响应完整性

API Key 模式调用百度官方客户端使用的端点：

```text
POST https://fanyi-api.baidu.com/ait/api/agent/text/translate
Authorization: Bearer <BAIDU_API_KEY>
Content-Type: application/json
```

JSON 请求包含 `q`、`from=en`、`to=zh` 和 `reference`。密钥仅放在请求头，不进入正文、命令行、日志或缓存。网络请求默认不读取系统代理环境变量；需要使用现有代理时可显式设置 `allow_system_proxy=true`。

百度可能将一次输入分成多个 `trans_result` 记录，即使输入很短也不能只取第一条。当前实现检查每条记录的 `src` 和 `dst`，按返回顺序连接所有 `src`，验证其覆盖整个请求的原文，再连接全部 `dst`。覆盖检查允许空白差异，其他源字符及顺序必须一致；缺失、重复、乱序、结构异常或非空原文对应空译文都会拒绝。原文覆盖校验用于防止响应被截断，不代替翻译质量审核。

早期 trans-cli 1.1.2 集成读取的 `translated` 字段只包含第一条结果，可能丢掉后续句子。当前实现不调用该程序，也不以它作为失败回退路径。

APPID 模式仍接入百度翻译开放平台的**领域文本翻译 API，`domain=academic`**：

- POST `https://fanyi-api.baidu.com/api/trans/vip/fieldtranslate`，表单 `application/x-www-form-urlencoded`。
- 参数为 `from=en`、`to=zh`、`domain=academic`。
- 签名为 UTF-8 编码 `appid + q + salt + domain + secret` 的 MD5 小写十六进制值。
- 需要对应的 APPID、密钥和学术领域服务权限；网页会员不能替代开放平台权限。

领域 API 的[官方接入文档](https://api.fanyi.baidu.com/product/123)和[百度官方客户端仓库](https://github.com/baidu-translate/trans-cli)可用于核对产品与历史客户端来源。

两种模式默认按最多 5500 UTF-8 字节无损分段，不切断术语标记。默认 QPS 为 1，可在账户权限允许范围内修改。HTTP 429/5xx、网络超时及支持的临时错误有限重试；LLM 模式每次请求最多尝试 3 次，APPID 模式最多 4 次。

LLM 路径中观察到可在同文重试后恢复的业务错误 `30000`，也纳入上述 3 次上限。它不属于认证或配额短路错误；持续失败时仍拒绝本段并保留原错误码。日志记录该码的错误说明时会隐藏当前凭据及完整请求文本，不把服务原始响应直接打印出来。

## 主程序调用约定

入口为 `engine_support/run_engine.py`，由内置 Python 在独立进程内运行 PDFMathTranslate/BabelDOC：

```text
runtime/python.exe engine_support/run_engine.py --input input.pdf --output output --config public_config.json --terms reviewed_terms.json --engine-dir engine
```

`--engine-dir` 可省略，依次识别环境变量 `PDFMT_ENGINE_DIR`、相邻的 `engine/` 和开发目录中相邻的 `PDFMathTranslate-v2.9.0/`。

环境变量：

- `BAIDU_API_KEY`：API Key 模式的凭据。
- `BAIDU_APP_ID`、`BAIDU_SECRET`：学术领域模式的 APPID 与密钥。
- `PDFMT_CACHE_DIR`：当前用户可写的缓存目录；未指定时放在本次输出目录的 `cache/` 下。
- `PDFMT_BABELDOC_ASSETS`：BabelDOC 资源根目录，内含 `models/`、`fonts/`、`cmap/`、`tiktoken/` 等子目录；程序不重写 `HOME`。

桌面主进程从 Windows 加密存储解密凭据后，仅通过子进程环境传递。环境变量优先于配置文件中的凭据字段。为兼容自动化，底层也接受配置文件中的 `baidu_api_key` 或 `baidu_app_id` / `baidu_secret`；桌面界面不应持久化这些明文字段。

API Key 模式的公开配置示例：

```json
{"service_mode":"llm","qps":1,"academic_domain":"academic","max_query_bytes":5500,"allow_system_proxy":false}
```

领域 API 使用 `"service_mode":"academic"`。直接运行底层入口且未填写 `service_mode` 时，配置加载器默认使用 `academic`；桌面应用会显式传入所选模式。

标准输出逐行包含 `PDFMT_EVENT ` 前缀及 JSON，事件包括 `backend`、`progress_start/update/end`、`finish` 或 `error`。其他引擎日志输出到 stderr。退出码 `0` 为成功，`2` 为失败。主程序必须同时检查退出码及 `finish` 事件，不能仅凭 PDF 文件存在判定成功。

翻译失败和导出错误分别计数，同一段翻译异常不会再被重复称为一处漏排。段落翻译失败、术语校验失败、导出错误或页数不一致均不能标记成功。认证、配额、权限等致命错误会锁定当前客户端，后续段落不再重复发网络请求，最终返回首个可读错误原因；瞬时错误不会被误锁定为永久失败。

正常输出保留 PDFMathTranslate 命名：

```text
<input-stem>.no_watermark.zh-CN.mono.pdf
<input-stem>.no_watermark.zh-CN.dual.pdf
translation_result.json
```

缺少必需凭据或本地配置不合法时不会调用网络翻译，也不会生成声称为百度译文的文件。

## 专名审核与有限恢复

主程序可在联网翻译前调用本地识别：

```python
from engine_support.term_protection import discover_protected_terms
policy = discover_protected_terms(pdf_path, custom_terms=["MyModel", "My Method"])
```

返回的完整对象包含 `terms`、`candidates`、`preserve_texts`、`reference_preserve_texts`、`preserve_references` 和 `reference_pages`。`candidates` 分为作者、期刊、模型方法和自定义词。界面应允许用户增删，再将**完整对象**保存为 `reviewed_terms.json` 并传给 `--terms`，以保留整段保护信息及参考文献开关语义。

也可运行：

```text
runtime/python.exe engine_support/run_engine.py --discover --input paper.pdf
```

`--discover` 不需要凭据，不调用在线接口。未传 `--terms` 时，翻译入口自动识别并在输出目录保存 `protected_terms.generated.json`。

候选来自 PDF 作者元数据、首页作者区域、正文 `Surname et al.`、参考文献作者、常见期刊、模型方法词表及缩写。首页识别会剔除上标，并利用字号等线索减少标题误识别为姓名。模型识别除了常见后缀，也识别 `CSBrain`、`CBraMod`、`LaBraM` 一类内部混合大小写名称。规则仍可能遗漏或误判，需要人工审核；用户明确保留的词会按源文大小写和连接符恢复。

参考文献默认整段保留英文。检测结合章节标题及后续文献内容，不再要求参考文献位于整份 PDF 的后半部分；遇到附录或补充材料标题时停止参考文献保护，让后续正文继续翻译。布局引擎对文献条目的拆分、合并也会与相邻原始文本块匹配。关闭 `preserve_references` 时会移除专属于参考列表的整段保护信息，作者区及期刊页眉的独立保护仍可生效。

正常路径在本机遮罩姓名、期刊、模型方法、原引擎公式标记、DOI、网址及邮箱，收到译文后逐个校验。每次请求的标记独立验证，随后恢复整段原词；丢失、重复或未知标记不能直接导出。

若完整响应仍改变标记，只对受影响的请求启用有限片段恢复：将未保护的文字片段单独送译，保护标记始终留在本地并按原位置插回。每个请求最多恢复 40 个含英文的未保护片段；仍逐次校验原文覆盖、空译文及残留标记，并拒绝应译正文未生成中文的恢复结果。达到上限或恢复失败时拒绝本段，不用整段英文替代译文。认证、配额和网络错误不进入该恢复路径。统计中的 `protection_retries`、`fragment_recoveries` 和 `requests` 可用于检查额外请求量。

## 缓存与验证

SQLite 缓存表为 `translations(cache_key TEXT PRIMARY KEY, value TEXT NOT NULL)`。键由服务类型、响应版本、语言、术语策略指纹和原文生成 SHA256；数据库保存译文，不保存密钥、APPID 或签名参数。词表及整段保护信息改变时，指纹也会变化。

当前 LLM 缓存版本为 `baidu-desktop-v3-source-coverage`。旧 CLI 可能在所有标记都出现于首句时，将截断译文误判为成功，因此全部旧 LLM 缓存必须隔离，不能仅因标记校验通过而复用。APPID 领域 API 原本就拼接完整数组，保留 `baidu-desktop-v2` 缓存版本。只有通过完整响应和术语恢复校验的结果才会写入当前缓存。

离线回归命令：

```text
runtime/python.exe -m unittest discover -s engine_support -p "test_*.py" -v
runtime/python.exe engine_support/run_engine.py --check-config --config public_config.json
```

单元测试使用自造短句和 mock，不发在线请求。它们覆盖多记录响应、源文覆盖、旧缓存隔离、术语恢复、致命错误短路、参考文献边界及候选识别。`offline_engine_smoke.py` 可用模拟译文验证真实引擎接线，默认写入被 Git 忽略的 `build/offline_engine_output/`。

`--check-config` 只做本地校验。`--test-connection` 会通过所选百度服务发送一条短句，可能计入账户额度。真实论文、诊断响应和运行日志应保存在 `build/` 或用户数据目录，不能作为公共源码测试夹具提交。
