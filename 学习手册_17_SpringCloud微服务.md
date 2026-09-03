# 📘 学习手册 17 · Spring Cloud 微服务（Java 岗硬门槛）

> 来源：同事 Java 面试侧重点——"**微服务框架必须有使用经验**"
> ⚠️ 你的情况：微服务经验是 **Node.js 自研架构**，不是 Spring Cloud。本册两手抓：① 补 Spring Cloud 全家桶知识 ② 学会把 Node 经验"转译"成 Java 面试官听得懂的话
> 模板：**一句话结论 → 详细解释 → 面试话术/例题**

---

## 1. Spring Cloud 全家桶总览
**一句话结论**：注册中心（Nacos/Eureka）+ 网关（Gateway）+ 远程调用（OpenFeign）+ 负载均衡（LoadBalancer）+ 熔断限流（Sentinel）+ 配置中心（Nacos Config）+ 链路追踪（Micrometer）+ 分布式事务（Seata）。
**详细解释**：
| 组件 | 职责 | 类比你的 Node.js 经验 |
|---|---|---|
| **注册中心** Nacos/Eureka | 服务注册与发现、健康检查 | 你 K8s 的 Service/DNS 服务发现（同一概念） |
| **网关** Gateway | 统一入口、路由、鉴权、限流 | 你 API 网关/nginx 前置 |
| **服务调用** OpenFeign | 声明式 HTTP 调用 | 你内部服务间 REST/消息调用 |
| **负载均衡** Spring Cloud LoadBalancer | 客户端负载（轮询等） | nginx/K8s Service 负载 |
| **熔断降级** Sentinel/Hystrix | 故障隔离、限流 | 你手册 04 的熔断限流（通用） |
| **配置中心** Nacos Config | 动态配置、热更新 | **你亲手做过配置中心！直接对应** |
| **链路追踪** Micrometer Tracing | traceId 贯穿 | 你手册 04 链路追踪题 |
| **事务** Seata | 分布式事务 | 你 Saga/最终一致性经验 |

**话术/例题**："Spring Cloud 是 Java 微服务全家桶，组件职责我在 Node.js 微服务里都有对等实践"——这句话是你的通关钥匙。

## 2. 注册中心：Nacos vs Eureka
**一句话结论**：Nacos 支持 AP（临时实例）+ CP（持久实例）双模型、自带配置中心，国产主流；Eureka 纯 AP、已停更。
**详细解释**：
- **服务注册**：服务启动向注册中心注册 IP:端口，心跳续约，下线摘除
- **服务发现**：消费方从注册中心拉取服务列表（定时拉取 + 订阅推送）
- **Nacos**：阿里巴巴开源，**注册+配置二合一**，支持临时/持久实例，控制台好用 → 国内新项目主流
- **Eureka**：Netflix，AP 模型（可用性优先，允许短暂不一致），2.0 停更 → 老项目
- 对比：ZooKeeper/etcd 是 CP（一致性优先，leader 选举）
**话术/例题**：背"Nacos=注册+配置、AP/CP 双模型"。追问：注册中心挂了服务还能调吗？→ 消费方有本地缓存列表，短暂可用（AP 的意义）。

## 3. 配置中心（Nacos Config）
**一句话结论**：配置统一管理 + 动态刷新（不用重启），本地缓存兜底。
**详细解释**：
- 流程：配置存 Nacos → 客户端启动拉全量 + 长轮询监听变更 → 配置变更推送/客户端拉取 → 动态刷新（@RefreshScope）
- 环境隔离：namespace（环境）+ group + dataId（服务粒度）
- **这是你的强项**：你主导过 RRM 配置中心（统一管理→一键部署生成 ConfigMap→自动校验→回滚）——**Spring Cloud 面试官问配置中心，你直接讲你真实做过的**，把 ConfigMap 换成 Nacos 说即可
**话术/例题**："配置中心我做过生产级的"——展开讲你的设计（版本/校验/回滚），这是全场的差异点。

## 4. 服务调用与负载均衡：OpenFeign
**一句话结论**：OpenFeign 声明式接口调用（像调本地方法），内置负载均衡（Spring Cloud LoadBalancer）。
**详细解释**：
- Feign 流程：定义接口 + 注解 → 动态代理生成 HTTP 调用 → 结合注册中心拿实例列表 → 负载均衡选实例
- 对比 RestTemplate：Feign 声明式（写接口就行），RestTemplate 手动拼 URL
- 负载均衡策略：轮询/权重/最小连接/一致性哈希（可配）
- 超时与重试：connectTimeout/readTimeout、重试策略（幂等才重试）
**话术/例题**：一句"声明式 HTTP 客户端 + 客户端负载均衡"。追问：Feign 底层用什么 HTTP 客户端？→ 默认 OkHttp/HttpClient 可切换。

## 5. 网关：Spring Cloud Gateway
**一句话结论**：统一流量入口，路由转发 + 过滤器（鉴权/日志/限流/灰度），基于 WebFlux 响应式。
**详细解释**：
- 路由：断言（Path/Host/Method）→ 转发到下游服务
- 过滤器：Global Filter（全局，鉴权）、Gateway Filter（路由级）
- 对比 Zuul 1.x：Gateway 非阻塞（WebFlux/Netty），Zuul1 是 Servlet 阻塞式 → 新项目用 Gateway
- 能力：限流（Redis RateLimiter 令牌桶）、跨域、统一异常、灰度发布（权重路由）
**话术/例题**：一句"网关 = 路由 + 过滤器链"。追问：网关和 nginx 区别？→ nginx 七层转发到网关/直接服务，网关做业务级路由鉴权限流，可 nginx→Gateway→微服务三层。

## 6. 熔断限流降级：Sentinel vs Hystrix
**一句话结论**：Sentinel（阿里）资源级控制、控制台可视化、主流；Hystrix（Netflix）线程池隔离、已停更。
**详细解释**：
- 熔断：连续失败/慢调用超阈值 → 熔断（快速失败）→ 半开试探 → 恢复
- 限流：QPS 阈值、并发线程数；算法：计数器/滑动窗口/令牌桶/漏桶（Sentinel 默认滑动窗口）
- 降级：异常比例/RT 超阈值 → 走 fallback（返回兜底）
- 规则持久化：推送到 Nacos
- 关联：你手册 04 第 28 题（熔断限流降级）讲的通用概念完全适用
**话术/例题**："Sentinel 资源 + 规则 + 控制台"。追问：Sentinel 和 Hystrix 区别？→ Sentinel 基于滑动窗口、支持实时监控控制台、规则可动态推送；Hystrix 线程池隔离、代码侵入大。

## 7. 链路追踪（Spring Cloud Sleuth/Micrometer Tracing）
**一句话结论**：traceId 贯穿全链路 + span 记录每跳，上报 Zipkin/Jaeger 展示调用拓扑和耗时。
**详细解释**：
- 集成：引入依赖 → 日志自动带 traceId → 上报 Zipkin
- 结合你：你 Node.js 4 微服务排查靠日志 grep traceId 串联（手册 04 第 29 题），Java 侧就是 Sleuth+Zipkin 自动化版
**话术/例题**：能讲"traceId 透传原理 + 你们实际排查方式"即可，自动化工具是锦上添花。

## 8. 分布式事务：Seata
**一句话结论**：Seata AT 模式（自动补偿，默认推荐）/TCC（手动）/Saga（长事务），解决跨服务数据一致。
**详细解释**：
- AT：一阶段本地事务+undo log 记录，二阶段全局提交/回滚（自动反向 SQL 补偿）——对业务无侵入
- TCC：Try-Confirm-Cancel 手动三段（强一致场景）
- Saga：长事务拆步 + 逆向补偿（你 Node 经验里的 Saga/最终一致性思想一致）
- 使用场景：订单+库存+账户跨服务
**话术/例题**：结合手册 04 第 27 题（分布式事务方案）一起答——AT 像"自动版本地消息表+Saga 组合"。追问：什么时候不需要分布式事务？→ 能通过最终一致性/消息补偿解决的场景，避免过度设计。

## 9. 微服务拆分与踩坑（结合你的真实经验）
**一句话结论**：按业务域拆 + 数据独立 + 独立部署；坑：分布式事务、链路排查、配置管理、版本兼容。
**详细解释**：
- 拆分原则你做过（RRM 按职责拆 4 服务），Java 面试可直接复用你的拆分解读
- Java 微服务踩坑：服务间调用超时链式放大（A 调 B 超时拖垮 A）→ 超时+熔断；配置散落 → 配置中心；日志无 traceId → 链路追踪
- 版本兼容：接口加字段不删字段、灰度发布
**话术/例题**："拆服务我做过、坑我也踩过（超时放大/配置散落/排查难）"——用真实经验讲，Java 面试官认架构思路。

## 10. 【关键】"你有没有微服务框架使用经验？"怎么答
**一句话结论**：诚实说主力是 Node.js 自研微服务 + Spring Cloud 已系统学习，然后**把架构通用性讲透**。
**回答模板**：
> "我的微服务生产经验主要建立在自研 Node.js 架构上——主导过 4 个微服务的拆分与重构（调度/查询/计算/AI 优化），覆盖了注册发现（K8s Service/DNS）、消息解耦（Kafka）、配置中心（自研，支持版本/回滚/热更）、熔断限流（手动实现+Redis 分布式锁）这些核心问题，**微服务的拆分原则、分布式一致性、运维体系是语言无关的**。
> Spring Cloud 我系统学过（Nacos/Gateway/OpenFeign/Sentinel），它解决的问题我在生产里都真实处理过，只是落地语言不同。给我 2-4 周我能直接上手业务。"

**追问应对**："具体用过 Nacos 吗？"→ 诚实："生产用的是 K8s+DNS 服务发现，Nacos 是同类方案的 Java 实现，我在学习环境完整跑通过注册+配置中心"——**不要编生产经验**，用"概念对等 + 学习验证"表述。

## 11. Node.js 微服务 vs Spring Cloud 对照速查
**一句话结论**：概念全同构，把"你干过的"翻译成"Java 词"，就是你的经验证明。
**对照表（背熟）**：
| 能力 | 你做过的（Node） | Spring Cloud 对应 |
|---|---|---|
| 服务发现 | K8s Service/DNS | Nacos/Eureka |
| 配置中心 | 自研配置中心（生成 ConfigMap） | Nacos Config |
| 消息解耦 | Kafka/RabbitMQ | MQ（RabbitMQ/RocketMQ/Kafka） |
| 负载均衡 | K8s Service + nginx | LoadBalancer/Gateway |
| 熔断限流 | 手动 + Redis 锁 | Sentinel |
| 网关 | nginx/自定义中间层 | Spring Cloud Gateway |
| 链路排查 | 日志 grep traceId | Sleuth/Zipkin |
| 分布式锁 | Redis SETNX+Lua | Redisson |
| 分布式事务 | 幂等 + 最终一致 | Seata |

**话术**：面试官问任何一个组件，先答组件职责，再补"这个能力我在 Node 生产里有对等实践（举一个具体场景）"，最后说"Spring Cloud 具体 API 我已学习，上手快"。

## 12. 软素质问题（H3C 培训文化：勤奋 / 迎难而上 / 客户第一）
**一句话结论**：每个价值观准备一个真实小故事，套用"背景-行动-结果"。
**故事模板**：
- **勤奋**："RRM WiFi7 项目时间紧，我连续 3 周每天加班到 10 点梳理 4 个微服务调用链，提前一周完成 6GHz 全链路改造方案"
- **迎难而上**："接手无文档的遗留系统，1 个月从零理清逻辑并独立维护，每周处理 1+ 线上问题没出过大事故"（这就是你真实经历）
- **客户第一**："客户反馈 AI 调优结果不信任，我主导重构为设备侧计算模式提升实时性，最终适配现网 98% 组网，解决了客户核心痛点"
- 如果对方是 H3C/华为系：强调奋斗者文化、结果导向、团队协作
**话术**：每个故事 30-45 秒，数据结尾（98%、每周1+、提前 1 周）。

## 📝 本章自测（闭卷）
1. 说出 Spring Cloud 八大组件一句话职责
2. Nacos vs Eureka（AP/CP、是否含配置中心）
3. OpenFeign 调用流程 + 负载均衡策略
4. Gateway 与 nginx 的分工
5. Sentinel 三种规则（熔断/限流/降级）+ 算法
6. Seata AT 模式原理（undo log 补偿）
7. 【必背】"你有没有微服务框架使用经验"完整回答
8. 把"配置中心/K8s 服务发现/Redis 锁"翻译成 Spring Cloud 词汇
9. 三个软素质故事各 30 秒

> 完成自测后，把第 10、11 题的回答练到脱稿——这是 Java 岗通关关键
