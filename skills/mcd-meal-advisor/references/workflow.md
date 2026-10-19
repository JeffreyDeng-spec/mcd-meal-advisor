# 运行文件与工具流程

以下路径相对当前工作目录，`SKILL` 表示本技能目录。私有文件放 `.local/`。不要将真实响应写入公开 examples 或 docs。

## 输入 bundle

```json
{
  "mode": "live",
  "captured_at": "2026-10-19T13:00:00+08:00",
  "store": {"storeCode": "来自门店查询", "storeName": "来自查询", "address": "来自查询", "businessStatus": true},
  "request": {
    "budget_cents": 3000,
    "required": [{"terms": ["菜单内明确名称或类别"], "quantity": 1}],
    "excluded": [], "preferred": [], "pinned_codes": [], "allow_extras": false
  },
  "menu": {"structuredContent": {"success": true, "code": 200, "data": {}}},
  "details": {},
  "store_coupons": {"structuredContent": {"success": true, "code": 200, "data": []}},
  "stock": {"structuredContent": {"success": true, "code": 200, "data": {"coupons": [], "currentPage": 1, "totalPages": 1}}}
}
```

上面只描述结构，不能直接当真实结果。`menu`、`details[productCode]`、`store_coupons`、`stock` 必须替换为原始工具返回。菜单与 details 不解析营销文案。stock 翻页成功后合并，末页 currentPage 与 totalPages 保持正确；未完整读取的保留末页前状态让报告标明部分结果。若券接口失败，省略对应键，不能用空成功响应冒充。菜单或详情业务失败要先处理；缺少详情的商品不参与候选。

`required` 是多个需求组，每组可用 `codes`（精确）或 `terms`（名称/官方分类子串）表达，`quantity` 是真实份数。同一餐品不能同时满足两个需求组。优先用明确名称或 code；不要把“鸡肉”和“汉堡”拆成两组表达一个鸡肉汉堡。`excluded` 匹配名称及官方类别，包括套餐子项。`pinned_codes` 要求指定餐品保留。需要餐具时显式传 `need_tableware: true`，否则保持官方默认；v1 不支持特调和随单购买会员。

## 生成和记录报价

```sh
python3 "$SKILL/scripts/advisor.py" prepare --input .local/bundle.json --output .local/run.json
python3 "$SKILL/scripts/advisor.py" next --run .local/run.json
```

`next` 输出 `candidate_id`、完整 `fingerprint`、`tool` 和 `arguments`。只对该 arguments 调一次原生 `calculate-price`，不重组商品或省略套餐轮次。将完整响应写到 `.local/quote-01.json`，然后：

```sh
python3 "$SKILL/scripts/advisor.py" record --run .local/run.json --candidate 候选ID --fingerprint 原指纹 --response .local/quote-01.json
```

网络或限流没有返回业务响应时，用同一 ID/指纹和 `--error transport_failure` 记录。记录前不得再次 next；失败名额也计入 20 次上限。存储的是实际官方根商品编码及数量；核价响应根餐品列表不一致、业务失败、缺金额都不会进入推荐。

```sh
python3 "$SKILL/scripts/advisor.py" report --run .local/run.json --output .local/meal-report.html
```

网页只导出已验证的展示字段，完整券码不会进入报告。即便在本机，也不要分享整个 `.local`。

## 局部修改

修改文件 `.local/change.json`：

```json
{"replacements": [{"from_code": "原单品或套餐子项code", "to_code": "真实可售替代code"}]}
```

先把新查到的详情加入 run 的 snapshot.products[code].detail；商品必须原本在所选门店菜单里。保持其他 snapshot 字段及需求不变；若快照超过15分钟，重新获取并 prepare。

```sh
python3 "$SKILL/scripts/advisor.py" revise --run .local/run.json --candidate 候选ID --patch .local/change.json --output .local/revision-1.json
```

修改只匹配一个位置，套餐只允许换成该轮官方 choices 里的选项。不明确换哪一份时先问用户。新 run 没有旧报价，需要重新 next/record/report。旧报告用于回看，不证明新餐单的价格。

## 能力边界

- 搜索有上限：每个需求取最多5个单品，单品组合最多150种，套餐默认项及单轮替换最多16种，最终最多20个核价任务；不保证全局最优。
- 套餐内未单卖的商品 code 不凭名字归一为其他 code。不同购买结构的同一内容也不用于计算纯券收益。
- 原生 MCP 的字段与业务状态优先；当前支持结构化响应和唯一可解析的 JSON 文本信封，不支持仅凭自然语言正文猜测成功。
- 所有客户端响应仍由 AI 保存传递；指纹用于防止错配及本地修改后误用，不是服务端签名，不能证明被人为伪造输入的真实性。
