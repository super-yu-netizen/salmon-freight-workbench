# PDF 中文字体来源

- 官方项目：[Noto CJK](https://github.com/googlefonts/noto-cjk)。
- 下载源文件：[NotoSansSC-VF.ttf](https://raw.githubusercontent.com/googlefonts/noto-cjk/main/Sans/Variable/TTF/Subset/NotoSansSC-VF.ttf)。
- 官方许可：[Sans/LICENSE](https://raw.githubusercontent.com/googlefonts/noto-cjk/main/Sans/LICENSE)。本目录保留 [OFL.txt](OFL.txt)。
- 发布字体：`NotoSansSC-Regular.ttf`，用于生成含中文的 PDF 测算单。
- 原字体元数据版本：`Version 2.004;hotconv 1.0.118;makeotfexe 2.5.65603`。
- 原字体版权：© 2014-2021 Adobe (http://www.adobe.com/), with Reserved Font Name 'Source'.

固定字重的处理方式：

```python
from fontTools.ttLib import TTFont
from fontTools.varLib.instancer import instantiateVariableFont

font = TTFont("NotoSansSC-VF.ttf")
instantiateVariableFont(font, {"wght": 400}, inplace=True).save("NotoSansSC-Regular.ttf")
```

只将可变字体固定为字重 400，未重画字形、未做字符子集化，也未重命名字体内部的名称记录。字体仍适用 SIL Open Font License 1.1。仓库文件名 `Regular` 用于标识本项目选择的固定字重；内部名称可能沿用源可变字体的记录。

当前发布文件：

| 项目 | 值 |
|---|---|
| 字节数 | 10596232 |
| SHA256 | `0e22ce03fd3065a4e25ec7f225bc2063a5563b80ede9c12fd9cc180f2bd66d8a` |

来源记录日期：2026-10-28。下载来源为官方 `main` 分支的上述路径；未记录原下载时的提交 SHA，不将当前分支状态冒称为当时固定提交。
