# 发布与第三方资料说明

项目品牌：三文鱼AI。联系：WX：supersalmon。

## 本次公开范围

本仓库公开范围为维护者制作的工作台代码、说明，以及明确标记的模拟产品、包装、装载、费率、地点和预算汇率资料。它不包含客户原始邮件、客户附件、真实报价或客户联系方式。

公开可见不等于额外授予第三方资料的使用权。本仓库未自行附加 MIT、Apache 等开源许可，也没有声称取得客户原始资料的公开许可。如需商业使用、再分发或定制，请联系维护者确认适用范围。

## 模拟数据

- 预置运费、费率有效期、时效、供应商名称和预算汇率均用于演示。
- 模拟地址不是交运地址，演示货代 A／B 不是实际供应商背书。
- 包装确认标记、装载模板和大货模拟系数只表示本例中已配置的模拟规则，不代表真实公司审批、设备能力或实际承运承诺。
- 任何基于本 Demo 的真实业务使用，都需要替换并核对企业确认的资料。

## 外部方法参考

资料中的 DHL 链接仅指向官方计费重量方法说明。本仓库没有复制其完整网页、图片或价目表，相关商标归原权利人所有。方法参考不表示本项目与 DHL 存在合作、代理或认证关系。

## 第三方软件与字体

Python、Cloudflare Workers／Wrangler、ReportLab、XlsxWriter 及实际安装的其他依赖分别适用其原有许可。依赖清单和锁定版本以仓库配置为准；本说明不替代各依赖自身的许可文本。

本仓库包含 `assets/fonts/NotoSansSC-Regular.ttf`，由 Noto CJK 官方仓库的 `NotoSansSC-VF.ttf` 固定字重 `wght=400` 生成，未重画字形或做字符子集化。官方来源为 [Noto Sans SC 可变字体](https://github.com/googlefonts/noto-cjk/blob/main/Sans/Variable/TTF/Subset/NotoSansSC-VF.ttf)，原字体声明：

> © 2014-2021 Adobe (http://www.adobe.com/), with Reserved Font Name 'Source'.

字体按 [SIL Open Font License 1.1](assets/fonts/OFL.txt) 再分发。完整来源、转换方式与文件哈希见 [SOURCE.md](assets/fonts/SOURCE.md)。发布包没有包含本机系统字体或专有开发运行时。

维护者不会因本项目公开而变更第三方软件、字体、商标或外链内容的权利归属。

浏览器文件导出使用 jsPDF、jsPDF-AutoTable 和 ExcelJS；构建产物保留相关第三方许可声明，完整依赖版本见 package-lock.json。
