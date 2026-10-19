# 参赛提交记录

公开源码已经上传，2026-10-19 13:53:11（北京时间）已提交官方报名 Issue。当前等待系统校验，不将提交等同报名成功。

报名 Issue：https://github.com/M-China/mcd-developer-innovation-challenge/issues/882

发布包：https://github.com/JeffreyDeng-spec/mcd-meal-advisor/releases/tag/v0.1.0

公开仓库已通过无登录克隆验证；克隆后53项 Python 测试、JavaScript 测试及离线演示运行通过。发布包只包含已跟踪的公开文件，真实响应和完整券码没有上传。

项目名称：麦麦点餐参谋

项目地址：https://github.com/JeffreyDeng-spec/mcd-meal-advisor

项目简介：面向想在预算内选餐、比较套餐和判断手中优惠券是否适用的单人到店取餐用户。通过麦当劳官方 MCP 读取当前门店菜单和券、构造候选并官方核价，提供最多三种不同餐单。在聊天中局部换餐后重新核价，在本地单文件报告中比较实付、餐品差异与已验证券收益。复用客户端现有模型和 MCP，无需新增模型密钥。本版不下单、不领券、不兑换积分。

## 展示流程

1. 说出预算、必选、不要的餐品与偏好；首次搜索商圈后自行选店。
2. 读取真实菜单和当前券包，比较单点、套餐和单券候选。
3. 打开本地报告，看整单官方价格、预算余额和不同内容的差别。
4. 查看持有／门店可用／餐单适用，以及同购买结构的真实券收益。
5. 复制方案修改请求回到聊天，保留原要求并重新核价。
6. 展示过期报价只供回看，以及无预算内方案时的明确缺口。

公开演示 `docs/demo.html` 使用合成数据。真实验收证据概述见 `docs/VALIDATION.md`，账号响应、券码和 Token 不公开。未实际使用 WorkBuddy，不申请依赖其真实使用记录的专项材料。

官方材料依据：[活动规则](https://github.com/M-China/mcd-developer-innovation-challenge/blob/main/activityGuidelines.md)。官方声明保留原文；以官方 Issue 的实际自动回复确认报名状态。
