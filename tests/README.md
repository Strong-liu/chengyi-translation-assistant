# 测试说明

离线测试通过 `unittest` 运行，不会发送百度请求。API 测试在临时目录生成合成 PDF；测试用虚拟凭据与正式设置隔离。Windows DPAPI 凭据测试需在 Windows 上运行。

```powershell
python -m unittest discover -s engine_support -p "test_*.py"
python -m unittest discover -s tests -p "test_*.py"
```

## 可选完整引擎离线测试

已安装完整运行依赖并下载 BabelDOC 资源时，可验证真实 PDF 解析、翻译调度和排版流程。此测试使用合成 PDF 与模拟百度接口，不读取个人凭据，不调用真实翻译服务。

```powershell
python tests/engine_reference_smoke.py --assets packaging/deps/babeldoc
```

测试包含带编号和字间空格的参考文献标题、IEEE 格式文献、跨页文献及附录；验证所有文献原文保留、正文和附录仍进入翻译、旧任务关闭参考文献保护时也会自动跳过。结果写入 `build/engine-reference-smoke/`。

## 可选在线浏览器测试

此测试需要已启动的应用，以及该应用本机已配置的百度大模型翻译 Key。测试会调用真实百度服务，可能计入账户额度。

```powershell
npm ci
npx playwright install chromium
$env:PAPER_TRANSLATOR_PYTHON = (Resolve-Path .\.venv\Scripts\python.exe).Path
node tests/e2e_smoke.mjs http://127.0.0.1:8766
```

默认在 `build/e2e-fixtures/` 生成一页合成英文论文，测试上传、审核专名、翻译、双版本下载、作者和期刊名恢复、刷新及窄屏布局。截图、PDF 和结果写入 `build/e2e-results/`，不提交仓库。

可选环境变量：

- `PAPER_TRANSLATOR_PYTHON`：已安装 PyMuPDF 的 Python 可执行文件。
- `PLAYWRIGHT_CHROME_PATH`：已有 Chrome 的完整路径；不设置时使用 Playwright Chromium。
- `E2E_PDF_PATH`：自备测试 PDF，替代自动生成的合成文档。
- `E2E_EXPECTED_TERMS`：JSON 字符串数组，指定前页应保留的英文名称。
- `E2E_TIMEOUT_MS`：等待翻译完成的最长时间，默认 480000 毫秒。

请将真实论文及测试诊断保留在本地，避免提交个人文件或 API 凭据。
