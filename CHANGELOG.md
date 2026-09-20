# Changelog

## v1.3（2026-09-21）

- v2 样本库 2200 条：22 子类 × 3 载荷 × 4 场景槽 × 8 手法 = 2112 对抗 + 88 对照（`scripts/expand_seed.py` 确定性生成）。
- 双人独立标注首测：分层抽样 200 条，作者模板标注 × DeepSeek 独立标注，κ=1.0（pass）；LLM 第二标注员与模板样本的局限已如实标注。
- `minor_sexual_content` 子类按内容政策不生成，覆盖由 minors 其余三子类承担。

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
