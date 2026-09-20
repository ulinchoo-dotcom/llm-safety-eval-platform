# Changelog

## v1.2（2026-09-21）

- 首次真实模型调用：deepseek-chat × 25 条（20 对抗 + 5 对照），ASR 0%、误伤 0%、通过率 100%。
- 关键发现：拒答规则信号在真实模型上召回仅 20%（4/20），实证 judge_gate 转人工的必要性。
- 产物：`reports/run-v1-deepseek-chat.json`、`reports/review-v1-deepseek.json`。

## v1.1（2026-09-21）

- 新增 50 条 v1 种子用例（`examples/seed-cases-v1.json`）：5 大类 × 8 攻击手法全覆盖的 40 条对抗用例 + 10 条近似误伤正常对照；作者自标，待双标。
- 完成首次完整闭环运行：50 用例 × 2 模拟模型，100 条结果逐条人工裁定（`reports/`）。
- 指标首跑：demo-safe ASR 0% / 严格通过率 20%；demo-overrefusal 通过率 80% / 误伤率 100%。详见 `reports/summary-v1.md`。

## v1.0（2026-09-20）

- 初始后端闭环：版本化风险分类（5 大类 23 子类 8 手法）、用例原子批量导入、LangGraph 模拟评测、人工复核、指标计算（ASR / 误伤率 / 拒答率 / Cohen's Kappa）、PostgreSQL 迁移与 CI。
