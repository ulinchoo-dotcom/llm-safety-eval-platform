# 技术决策

初版以一套 FastAPI 服务提供用例、模拟运行和人工复核接口。存储只有 PostgreSQL，没有 Redis。通过 asyncpg 连接池异步访问数据库；每次写入使用独立事务。迁移使用版本表和事务级咨询锁，支持首次启动与多实例重复启动。

用例输入由 Pydantic 严格校验。业务编号不可覆盖；运行快照包含完整用例、手册与 Prompt 版本。人工复核另表保存，查询时覆盖最终统计视图，不改写原始调用记录。此版本尚未允许将用例升级为 label_verified，避免在未建立双标体系前绕过验证。

LangGraph 节点为模型调用、规则信号和 Judge 准入检查。模型通过 Provider 协议接入。每模型令牌桶由应用持有，不因每次新建评测而重置。调用错误走独立路径，最多初始请求加三次重试。错误的用量与费用记为未知，不伪造零值。演示模型的零费用显式注明 simulated。

当前只有模拟适配器；Judge 准入节点固定转人工。这是可验证的基础行为，不等同于已实现 LLM-as-Judge。真实模型适配必须先落实模型、价格与版本配置、超时/429 分类重试、总预算、持久化任务和校准记录。

一次人工复核在运行行锁下写入，防止并发复核丢失完成状态。首次裁定不可覆盖；后续应引入有版本的复核修订与仲裁机制。共享本地 Token 只保护单人开发数据，不提供多人盲标隔离。多人版本须将身份绑定至认证主体。

前端规划为 React + Vite 标注台，在 M2 建设。当前通过 OpenAPI 文档与 HTTP API 操作，未制作静态假看板。

参考：

- [SQLAlchemy 关于并发会话隔离的说明](https://docs.sqlalchemy.org/en/20/orm/session_basics.html)（实现选用 asyncpg，同样按事务隔离连接）。
- [FastAPI 生命周期测试](https://fastapi.tiangolo.com/advanced/testing-events/)。
- [LangGraph StateGraph](https://reference.langchain.com/python/langgraph/graph/state)。
- [Pydantic 模型验证器](https://docs.pydantic.dev/latest/concepts/validators/)。
