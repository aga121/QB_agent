# Queen_Bee / QB_agent

[在线体验](https://queenbeecai.com)

[简体中文](README.md) | [English](README.en.md)

## 简介

🚀 基于 Claude 智能体为内核打造的 Web 版智能体平台，性能强劲、任务完成效率高，并对企业复杂办公场景有很强的兼容性。💰 硬件成本被压到极低：16GB 内存可同时支撑数千人使用，尤其适合不愿重投入硬件、却希望拥有贯穿业务的智能中枢的中小企业。🧠 算力与硬件成本被显著压缩，1000 人规模企业每月仅需几百到几千元即可运行。⚙️ 内置 agent 智能回收机制与算法优化，使 1000 商业用户/企业的硬件成本低至几百元，算力开销极为节省，足以支撑日常工作。这一效果非常惊人。

## 功能

以 AI 编程为驱动，为非 IT 用户提供专业级智能体能力。支持文档与数据的生成、分析与自动化，包括：xlsx 分析计算、专业 docx 编写、精美网站与软件生成、邮件发送、定时任务、记忆与自进化等。面向日常业务场景也非常友好：财务分析、人事简历处理、浏览器自动化、画图设计、一键生成并部署官网、复杂任务处理、主动触发任务及各类分析。平台支持高并发，用户可同时并发使用智能体、Skill、MCP 与用户控制面板。作为高性能 Web 版产品，普通用户无需安装，访问即用，资源消耗极轻；支持在线预览与编辑 Office 文档，三言两语即可生成与分析文档，甚至产出并部署完整网站，生成速度极快。

基础功能界面（PNG）：

- 登录界面  
  ![登录界面](doc/images/1登录界面.png)
- 主界面  
  ![主界面](doc/images/2主界面.png)
- 用户控制面板  
  ![用户控制面板](doc/images/2用户控制面板.png)
- MCP 安装  
  ![MCP 安装](doc/images/3支持mcp安装.png)
- 支持 Skills  
  ![支持 Skills](doc/images/4支持skills.png)

智能体生成 Demo（GIF，点击查看）：

- [官网生成](doc/images/官网生成.gif)
- [文档生成样例](doc/images/文档生成样例.gif)
- [模块展示](doc/images/模块展示.gif)
- [画设计图](doc/images/画设计图.gif)
- [复杂设计图](doc/images/复杂设计图.gif)
- [各种生成案例](doc/images/各种生成案例.gif)

## 示例

- [媲美谷歌的研究模式生成示例](https://queenbeecai.com/html-page/9a2d5f22-57ef-4231-b76d-5cf9dbf90a20/%E5%A4%A7%E6%A8%A1%E5%9E%8B%E5%AD%A6%E4%B9%A0%E8%B5%84%E6%96%99/index.html)
- 一键艺术官网生成  
  ![一键艺术官网生成](doc/images/一键艺术官网生成.png)
- 专业文档图文生成  
  ![专业文档图文生成](doc/images/专业文档图文生成.png)
- 复杂 xlsx 生成  
  ![复杂 xlsx 生成](doc/images/复杂xlsx生成.png)
- 复杂图形生成方便学习  
  ![复杂图形生成方便学习](doc/images/复杂图形生成方便学习.png)
- 复杂论文 PDF 生成  
  ![复杂论文 PDF 生成](doc/images/复杂论文pdf生成.png)
- 网站系统生成并部署  
  ![网站系统生成并部署](doc/images/网站系统生成既部署.png)

## 运行要求

- CPU：4 核
- 内存：8 GB
- 硬盘：100 GB
- 模型（离线部署）：推荐 GLM 4.7，显存约 800 GB；量化后约 400 GB 显存即可
- 模型（非私有化部署）：推荐智普 AI 编程套餐或 MinMax 月付（几十元级别）
- 多用户场景：支持智能算法分配多个 API Key 作为算力池，稳定性更强

## 快速开始

将源码拉取/下载到服务器后，先到 `agent/backend/core/system/config.py` 填好 #必填1 #必填2，然后进入 `install` 目录执行 `start_install.sh`，即可一键部署使用。

## 配置说明

进入 `agent/backend/core/system/config.py`，将 #必填1 #必填2 配置完成即可。
 

## 技术目录

- Linux 内核 UID/GID 与 cgroup2
- Bash 包裹机制沙箱隔离（低内存开销）
- GLM Coding 模型驱动
- Agent 智能回收机制与算法优化


## 贡献指南

- TODO

## 许可证

Apache 2.0

如有问题请联系（电话）：17512089424  
微信号：`queenbeecai`  
抖音不定时分享教程（抖音号）：77263839168
