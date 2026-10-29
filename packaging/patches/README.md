# BabelDOC 0.6.4 兼容修补

`babeldoc-0.6.4-typesetting.py` 为 BabelDOC 0.6.4 对应的可读源码，保留其 AGPL 许可。相对上游，修补了段落框重叠时错误缩短可用高度，以及中英文混排行高低于主字体 em 高度的问题。

`../patch_runtime.py` 在构建运行环境时将此固定版本源文件复制到 BabelDOC，并使 `const.py` 支持 `BABELDOC_CACHE_DIR`。该脚本先检查版本，重复运行不会重复插入补丁。

源码：[BabelDOC](https://github.com/funstory-ai/BabelDOC)，版本 0.6.4；版权归其贡献者所有。补丁应用于分发副本或开发虚拟环境，不修改系统 Python。
