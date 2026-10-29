# Third-party software and resources

This distribution contains open-source components and bundled model/font resources. The corresponding license files remain under `runtime/Lib/site-packages/*.dist-info/`, and collected license texts are provided under `THIRD_PARTY_LICENSES/`. PDFMathTranslate source is included under `engine/pdf2zh_next/`. BabelDOC and the additional Python dependencies are included as readable installed packages under `runtime/Lib/site-packages/`. The local application and engine-support source files are shipped with the executable launcher.

- PDFMathTranslate 2.9.0: GNU Affero General Public License v3.0; upstream https://github.com/PDFMathTranslate-next/PDFMathTranslate-next ; license in `engine/LICENSE`.
- BabelDOC 0.6.4: upstream https://github.com/funstory-ai/BabelDOC ; license and source in the installed BabelDOC package and its distribution metadata. The cache-directory compatibility change and paragraph-gap correction are present in this distribution's readable source.
- CPython 3.12: license text in `PYTHON_LICENSE.txt`; upstream https://www.python.org/ .
- Baidu translation service: the application calls the official HTTPS text translation endpoints directly. Service access is supplied by the end user's account. No Baidu CLI executable is required or distributed by version 0.3.0.
- Microsoft Visual C++ runtime: official Microsoft-signed AMD64 app-local runtime files; license in `MICROSOFT_VC_RUNTIME_LICENSE.rtf`; official download https://aka.ms/vs/17/release/vc_redist.x64.exe . These files are deployed beside the bundled Python executable, not installed into Windows system folders.
- Noto, Source Han, LXGW WenKai, Klee One, and Maru Buri font resources: copyright and license records extracted from each bundled font are in `FONT_LICENSES.txt`; the SIL Open Font License 1.1 text is in `THIRD_PARTY_LICENSES/SIL-OFL-1.1.txt`. NAVER's Maru Buri license information is at https://help.naver.com/service/30016/contents/18088?osType=PC .
- DocLayout-YOLO model and accompanying BabelDOC CMap/tiktoken resources: distributed with the BabelDOC asset metadata and used for local PDF layout recognition/tokenization, not as an online translation model.
- FastAPI, Uvicorn, NumPy, SciPy, OpenCV, ONNX Runtime, PyMuPDF, FontTools and other runtime packages: see their installed package distribution metadata and licenses.

The Inno Setup compiler and extraction tooling are build-only tools and are not part of the installed runtime. The installer is built with Inno Setup 6.4.3 from its official signed distribution: https://github.com/jrsoftware/issrc/releases/tag/is-6_4_3 .

No API keys, user settings, translation-history databases, or personal PDF inputs are included in this installation payload. Baidu translation API access is configured by the end user after installation. Online service use is subject to the user's own service account and current provider terms.
