# 📘 学习手册 04 · Node.js 专属

> 配套《面试八股复习计划》第 3 节 1-40 题
> 你的主场——目标不是"学"，是把日常经验组织成**能讲清楚的面试答案**
> 模板：**一句话结论 → 详细解释 → 面试话术/例题**
> 投伍柒必乐/商云科汇/芯动/必来屋前必过

---

## ⚡ 事件循环与异步（1-5 题）

### 1. Node.js 事件循环有几个阶段？
**一句话结论**：6 个阶段轮转：timers → pending callbacks → idle/prepare → poll → check → close callbacks。
**详细解释**：
- **timers**：执行 setTimeout/setInterval 到期的回调
- **pending callbacks**：系统操作回调（如 TCP 错误）
- **idle/prepare**：内部使用
- **poll**：核心阶段——获取新 I/O 事件，处理回调；有定时器到期就执行，否则阻塞等待
- **check**：setImmediate 回调
- **close**：socket 关闭回调
- 每轮结束检查微任务队列（Promise、nextTick）
**话术/例题**：背 6 阶段 + "poll 是核心"，追问"setTimeout(0) 和 setImmediate 谁先？"→ 在 poll 阶段外 setImmediate 先，在 I/O 回调里 setImmediate 先（场景相关）。

### 2. process.nextTick 与 setImmediate 的区别？
**一句话结论**：nextTick 是"当前操作结束后立即执行"（优先级最高，先于 Promise），setImmediate 在下一次循环的 check 阶段执行。
**详细解释**：
- nextTick 属于微任务但优先级高于 Promise（先执行完所有 nextTick 再执行 Promise）
- setImmediate 是宏任务，等下一轮 check 阶段
- 递归 nextTick 会饿死事件循环（死循环），要谨慎
**话术/例题**：一句话"nextTick 插队最先跑，setImmediate 排队到 check 阶段"。追问：`process.nextTick(()=>{})` 和 `Promise.resolve().then()` 谁先？→ nextTick 先。

### 3. libuv 是什么？线程池默认大小？
**一句话结论**：libuv 是 Node 的跨平台异步 I/O 库（事件循环实现者），线程池默认 4 个线程（UV_THREADPOOL_SIZE 可调）。
**详细解释**：
- 事件循环由 libuv 驱动；文件系统操作、DNS 查询、加密（crypto）、zlib 压缩等**没有原生异步 API 的操作**走线程池
- 网络 I/O（TCP/UDP）不走线程池，用系统 epoll/kqueue（非阻塞）
- 默认 UV_THREADPOOL_SIZE=4，可通过环境变量调到更大
**话术/例题**：能说出"fs 和 crypto 走线程池，网络不走"就是懂行。追问：大量 fs 操作为什么慢？→ 线程池只有 4 个线程，排队。

### 4. 宏任务 vs 微任务执行顺序？
**一句话结论**：每执行一个宏任务，先把当前所有微任务清空，再进下一个宏任务。
**详细解释**（经典题，直接背输出顺序）：
```js
console.log('1');                       // 1 同步
setTimeout(()=>console.log('2'), 0);    // 宏任务
Promise.resolve().then(()=>console.log('3')); // 微任务
process.nextTick(()=>console.log('4')); // nextTick（最优先微任务）
// 输出：1, 4, 3, 2
```
**话术/例题**：背"同步 → nextTick → Promise → setTimeout"输出顺序，面试必考一题，练熟 5 个变体。

### 5. Node.js 单线程为什么能扛高并发？
**一句话结论**：事件驱动 + 非阻塞 I/O，线程不等待 I/O，一个线程处理海量并发连接。
**详细解释**：请求进来后发起 I/O（数据库/文件/网络），**不阻塞**，I/O 完成后回调进入事件循环；线程空出来了继续接新请求。对比 Java 一个请求一个线程（线程池有限，等待 I/O 时占着线程）。
**话术/例题**："I/O 密集场景单线程事件驱动优于多线程阻塞模型"，追问"CPU 密集任务怎么办？"→ worker_threads 子进程分担。

---

## 📦 Stream / Buffer / 内存（6-9 题）

### 6. 什么是 Stream？背压机制？
**一句话结论**：Stream 是流式处理数据（分块，不一次性加载内存）；背压是消费者慢时暂停生产防内存爆炸。
**详细解释**：
- 四种：Readable（读）、Writable（写）、Duplex（双工）、Transform（转换）
- 管道：`readable.pipe(writable)`，内部自动处理背压（读太快写不动时暂停）
- 手动处理：监听 'data' 时要手动判断 `write() 返回值` 和 'drain' 事件
- 场景：大文件传输、日志流、gzip 压缩流
**话术/例题**："pipe 帮你处理背压，手写 data 事件要自己管 drain"。追问：上传大文件为什么用 stream？→ 一次性读内存会 OOM。

### 7. Buffer 与二进制数据？
**一句话结论**：Buffer 是 Node 处理二进制数据的类，本质是 V8 堆外的原生内存分配。
**详细解释**：
- `Buffer.from(str, 'utf8')` 字符串转 Buffer，`.toString()` 转回
- Buffer 分配在**堆外**（Node 内存统计 external），避免 V8 堆限制；小 Buffer 走内存池，>8KB 单独分配
- 与 TypedArray（Uint8Array）同源，可互相转换
**话术/例题**："堆外内存 + 内存池"两个词显深度。追问：TCP 粘包用 Buffer 怎么处理？→ 拼包 + 按协议长度/分隔符拆包。

### 8. Node.js 内存模型与内存泄漏排查？
**一句话结论**：V8 堆（新生代/老生代）+ 堆外内存；泄漏常见于全局变量、闭包、事件监听器、定时器未清理。
**详细解释**：
- `--inspect` + Chrome DevTools 内存快照（heap snapshot）对比两次快照找增长对象
- 命令：`node --max-old-space-size=4096` 调堆上限；`process.memoryUsage()` 查看
- 常见泄漏：全局缓存无限增长、未 removeListener、setInterval 未 clear、闭包持有大对象
**话术/例题**：讲一个真实排查（结合你 RRM 的 OOM 排查经验：rrmcompute 内存 5Gi→5.5Gi 调整案例）。追问：heapdump 怎么分析？→ 比较快照差异找 Retained Size 大的对象。

### 9. cluster 模块 vs worker_threads？
**一句话结论**：cluster 是多进程（每个进程独立 V8 实例，适合 CPU 密集/高并发，IPC 通信）；worker_threads 是同进程多线程（共享内存，适合并行计算，省内存）。
**详细解释**：
- cluster：master 进程 fork 多个 worker，共享端口（内部负载均衡）；pm2 cluster 模式就是它
- worker_threads：真正共享内存（SharedArrayBuffer）、消息传递；Node 12+ 稳定
- 选型：web 服务扩容用 cluster；CPU 密集计算（加密/图像）用 worker_threads
**话术/例题**："cluster 扛并发，worker_threads 干计算"。追问：pm2 的 cluster 模式原理？→ 就是 cluster 模块封装，+进程守护自动重启。

---

## 🛠️ 框架与工程（10-14 题）

### 10. Express 中间件机制？洋葱模型？
**一句话结论**：中间件是请求处理链上的函数（req,res,next），按注册顺序执行，next() 进入下一个，类似洋葱（请求进来一层层深入，响应一层层返回）。
**详细解释**：
- 用法：`app.use()` 全局中间件（鉴权/日志/CORS）、`app.get('/x', mw, handler)` 路由级
- 控制流：调用 next() 才继续；不调用则挂起；next(err) 跳到错误中间件
- 洋葱模型（Koa 更典型）：`请求 → 中间件1前 → 中间件2前 → handler → 中间件2后 → 中间件1后 → 响应`
- 对比：Koa 用 async/await 原生支持，Express 回调式（5.x 支持 Promise）
**话术/例题**："中间件=管道 + 洋葱顺序"，能画出来就满分。追问：鉴权中间件怎么写？→ next() 前查 token，失败 res.status(401)。

### 11. NestJS 核心：DI、装饰器、模块化？
**一句话结论**：NestJS 是 TS 优先的企业级框架，核心是模块化（Module）+ 依赖注入（Provider）+ 装饰器定义控制器/服务。
**详细解释**：
- Module：组织单元（Controller + Provider + 导入导出），`@Module({controllers, providers, imports, exports})`
- DI：构造函数注入，`@Injectable()` 装饰的服务类可注入；默认单例
- Controller：`@Controller('user')` + `@Get(':id')` + `@Param()`
- 中间件/守卫/拦截器/管道：AOP 机制（Guard 鉴权、Pipe 校验、Interceptor 日志）
- TypeORM/Mongoose 集成、配置模块、异常过滤器
**话术/例题**：伍柒必乐要求 NestJS，重点准备"DI 是什么/为什么"（解耦、可测试）+ 装饰器原理（就是函数）。追问：Nest 和 Express 关系？→ Nest 基于 Express/ Fastify 之上的一层抽象。

### 12. GraphQL vs REST？
**一句话结论**：REST 按资源定 URL，GraphQL 一个端点按需查字段，解决"过度获取/接口爆炸"。
**详细解释**：
- REST 问题：字段冗余（返回用不到的数据）、多端适配（App/Web 各写接口）、版本管理难
- GraphQL：Schema 定义类型、Query 查询 / Mutation 修改、按需取字段、单请求多数据源聚合
- 代价：服务端复杂度（resolver、N+1 查询）、缓存困难、学习成本
- 选型：前端多变/字段多端差异大用 GraphQL；简单 CRUD 用 REST
**话术/例题**：伍柒必乐要求 GraphQL，讲清"按需取字段 + 聚合多资源"两个卖点。追问：N+1 问题？→ DataLoader 批量加载。

### 13. Node.js 接口鉴权？JWT 原理？
**一句话结论**：JWT（Header.Payload.Signature）三段式 token，服务端不存状态（无状态鉴权），签名防篡改。
**详细解释**：
- 流程：登录验证 → 签发 token（payload 含 uid/过期时间，HS256 签名）→ 客户端存（localStorage/Header）→ 每次请求带 Authorization: Bearer xxx → 服务端验签解析
- 优点：无状态、分布式友好、天然跨端
- 缺点：无法主动注销、payload 明文（别放敏感信息）、过期时间要合理
- 配合刷新：access token（短，如 15min）+ refresh token（长，换新）
- 安全：密钥保密、HTTPS 传输、HttpOnly Cookie 存（防 XSS 偷）
**话术/例题**：讲 JWT 三段结构 + "验签不查库"。追问：JWT 被泄露怎么办？→ 短有效期 + 黑名单 + 更换密钥。项目里你们怎么鉴权？（可结合 cloudapGroupAPI 权限体系）

### 14. PM2 / Docker 部署 Node.js？优雅退出？
**一句话结论**：PM2 管进程（守护/负载/日志/自动重启），Docker 管环境（镜像/隔离/编排），优雅退出让在途请求处理完再关。
**详细解释**：
- PM2：`pm2 start app.js -i max`（cluster 多进程）、`pm2 reload` 零停机、日志轮转、开机自启
- Docker：多阶段构建（build 装依赖 → 精简运行镜像）、非 root 用户、`NODE_ENV=production`
- 优雅退出：监听 SIGTERM → 停止接收新请求 → 等 in-flight 完成 → 关闭 server → 退出；配合 K8s 滚动更新（terminationGracePeriodSeconds）
- 健康检查：/healthz 端点 + K8s 探针（liveness/readiness）
**话术/例题**：结合你们 K8s 部署经验讲（Pod 滚动更新、探针配置）。追问：K8s 滚动更新为什么旧 Pod 没退干净？→ 探针/优雅退出超时问题，这正是你 RRM 微服务的实战点。

---

## 🗄️ MongoDB / Redis（15-18 题）

### 15. MongoDB 聚合管道原理？分库分表策略？
**一句话结论**：聚合管道（$match/$group/$sort…）在服务端分阶段处理数据；分片用片键把数据分布到多台。
**详细解释**：
- 聚合：`db.col.aggregate([{$match},{ $group:{_id, ...} },{ $sort }])`——类似 Unix 管道，每个阶段产出文档流
- 分库分表（分片）：MongoDB 原生 sharding——mongos 路由 → 按**片键**（如 taskId/apSN）把数据分到多个 shard；chunk 自动迁移
- 结合你们 RRM：clbDetail/optHistory 集合按 {taskId, apSN, RI} 建索引、按任务维度分片，避免单集合热点
**话术/例题**：讲聚合管道"阶段流" + 你们分片键的选择理由。追问：分片键怎么选？→ 查询最频繁字段 + 分布均匀 + 不可变。

### 16. MongoDB 索引与查询优化？WiredTiger？
**一句话结论**：B+树索引（单字段/复合/唯一/TTL），WiredTiger 是默认存储引擎（文档级锁 + WiredTiger 缓存 + Snapshot 隔离）。
**详细解释**：
- 索引：复合索引最左前缀、覆盖索引（只查索引字段不回文档）、TTL 索引（过期自动删，适合日志）
- 慢查询：explain() 看 plan，重点关注是否走索引（IXSCAN vs COLLSCAN）、nReturned/executionTime
- WiredTiger：B+树存储、文档级并发控制（MVCC）、WAL（journal）、压缩（snappy/zlib）、LRU 缓存
- 优化：索引命中 > 限制返回字段（projection）> 分页用 _id 游标 > 避免 $or 全扫
**话术/例题**：结合你们 optHistory 按时间查+taskId 查的场景讲索引设计。追问：Mongo 和 MySQL 选型？→ 文档模型灵活/水平扩展原生 vs 关系约束/事务强，RRM 上报数据用 Mongo（结构多变、量大）。

### 17. Redis 分布式锁 + 集群模式？
**一句话结论**：SETNX+EX+唯一值+Lua 释放（详见手册 03），集群选哨兵（HA）或 Cluster（扩容）。
**详细解释**：见《学习手册 03》第 6、7 题，这里补一点 Node 侧：`ioredis` 封装 `set(key, val, 'EX', ttl, 'NX')`，释放用 Lua（`if get==val then del`）；redlock 库做多节点。
**话术/例题**：结合 RRM 分布式调优任务防重入（多个 rrm 微服务实例并发触发同一 AP 调优时用锁串行化）。

### 18. 数据库与缓存一致性？
**一句话结论**：Cache Aside：先写库再删缓存，binlog 订阅兜底，TTL 兜底（详见手册 03 第 5、9 题）。
**详细解释**：Node 侧工程：Mongo 变更 → 删 Redis key；或用 Mongo change stream / Canal 监听变更异步失效缓存。
**话术/例题**：你们的配置中心缓存怎么做一致性？（可讲配置变更 → 版本号 → 各服务拉新）。

---

## 📨 消息队列（19-21 题）

### 19. Kafka 消费者组/分区/offset？如何保证不丢不重？
**一句话结论**：Topic 分分区，消费者组内分区被组内成员分摊消费；offset 记录消费位置；不丢=生产端 ack + 消费端手动提交，不重=幂等。
**详细解释**：
- 分区：Topic 数据按 key 哈希/轮询分到多个 partition，并行消费
- 消费者组：同组消费者分摊分区（一个分区只被组内一个消费者消费），组间广播
- offset：消费位置，存在 __consumer_offsets 主题；提交策略（自动/手动）
- **不丢消息**：生产端 `acks=all`（等副本确认）+ 重试；消费端先处理业务再提交 offset（at-least-once）
- **不重复**：at-least-once 必然可能重复 → 消费幂等（唯一业务 id 去重，如调优结果按 taskId+时间去重）
- 重平衡（rebalance）：消费者增减触发分区重分配，期间停止消费
**话术/例题**：结合你们 RRM 上报链路（设备调优结果 → Kafka → 入库）讲"先写库后提交 offset"防丢。追问：重复消息怎么办？→ 幂等表/业务去重。

### 20. Kafka 与 RabbitMQ 选型？消息顺序性？
**一句话结论**：Kafka 高吞吐/日志/回溯，RabbitMQ 灵活路由/低延迟/可靠性；顺序性=单分区+按 key 路由。
**详细解释**：
| 维度 | Kafka | RabbitMQ |
|---|---|---|
| 模型 | 分区日志，拉模式 | 队列+交换机，推模式 |
| 吞吐 | 极高（百万级） | 中（万级） |
| 路由 | 按 key 到分区 | 交换机绑定（topic/direct/fanout）|
| 顺序 | 分区内有序 | 单队列有序 |
| 回溯 | 支持（offset 可重置） | 消费即删 |
| 场景 | 大数据/日志/流处理 | 业务消息/复杂路由 |
- 顺序性：Kafka 把同一 key（如同一 AP）路由到同一分区 + 单消费者 → 有序
**话术/例题**：你们 Kafka 消费者组配置（RRM 上报按 AP 维度 hash 到分区保序）就是现成案例。

### 21. 消息幂等性方案？
**一句话结论**：消费端用唯一 ID 去重（幂等表/Redis setnx/业务字段唯一约束）。
**详细解释**：
- 方案 1：消费前查幂等表（业务 ID 唯一）——存在即跳过
- 方案 2：Redis `SETNX bizId 1`，成功才处理
- 方案 3：数据库唯一索引兜底（重复插入报错忽略）
- 方案 4：业务天然幂等（如"设置调优参数"重复设置结果一致）
**话术/例题**：你们 optHistory 如果重复上报怎么防？（按 taskId+AP+批次去重）。

---

## ☸️ K8s / Docker（22-25 题）

### 22. Pod/Deployment/Service/Ingress 职责？
**一句话结论**：Pod 最小调度单位、Deployment 管副本和滚动更新、Service 提供稳定访问入口（ClusterIP）、Ingress 七层路由（域名/路径 → Service）。
**详细解释**：
- Pod：一个或多个容器共享网络/存储；K8s 最小单位
- Deployment：声明期望副本数，控制 ReplicaSet 滚动升级/回滚
- Service：Pod 是临时的（IP 会变），Service 提供稳定 VIP + 负载均衡（iptables/IPVS），类型：ClusterIP/NodePort/LoadBalancer
- Ingress：七层（HTTP/HTTPS）路由，域名+路径 → Service；nginx ingress controller 实现
- 附加：ConfigMap/Secret 配置注入、HPA 自动扩缩、PV/PVC 存储
**话术/例题**：画出"用户 → Ingress → Service → Pod"链路（这就是你们 RRM 微服务的访问路径）。

### 23. HPA 原理？存活/就绪探针区别？
**一句话结论**：HPA 按指标（CPU/自定义）自动调整副本数；liveness 决定重启，readiness 决定是否接流量。
**详细解释**：
- HPA：HorizontalPodAutoscaler 监控指标 → 计算 desiredReplicas → 调 Deployment 副本；指标源 metrics-server/Prometheus 自定义
- livenessProbe：失败 → 重启容器（救活卡死进程）
- readinessProbe：失败 → 从 Service 摘除（不接新流量，启动慢/依赖未就绪时用）
- startupProbe：启动期专用（避免慢启动被 liveness 误杀）
**话术/例题**：你们 rrmcompute 高量任务内存涨 → HPA/资源配额怎么配？（结合 5Gi→5.5Gi 调优、requests/limits 概念）。

### 24. Docker 镜像分层原理？容器与虚拟机区别？
**一句话结论**：镜像由只读层叠加（UnionFS），层可复用；容器共享宿主机内核（进程隔离），虚拟机有独立内核（硬件虚拟化）。
**详细解释**：
- 分层：Dockerfile 每条指令一层，基础镜像+依赖+源码分层；层只增不改 → 缓存复用、镜像小
- 容器：namespace（隔离 PID/网络/文件系统）+ cgroups（限制 CPU/内存），秒级启动
- 虚拟机：Hypervisor + 完整 Guest OS，隔离强但重（GB 级、秒级到分钟级）
- 多阶段构建：builder 装依赖 → 拷贝产物到精简镜像（node:slim 替代 node:full）
**话术/例题**：你们 RRM 镜像怎么瘦身？（多阶段构建 + alpine/slim + 非 root）。追问：镜像层为什么能复用？→ Docker 按层缓存，Dockerfile 顺序影响构建缓存命中。

### 25. ConfigMap/Secret 管理配置？
**一句话结论**：ConfigMap 存非敏感配置（明文），Secret 存敏感信息（base64+加密可选），通过环境变量/挂载注入 Pod。
**详细解释**：
- ConfigMap：`kubectl create cm app-config --from-file=...`；注入方式：env、envFrom、volume 挂载
- Secret：类似但 base64（非加密，要配合加密选项/外部方案）；类型：Opaque/tls/docker-registry
- 更新：env 注入不热更新（重启生效），volume 挂载可热更新
- 结合你们：RRM 配置中心其实就是 ConfigMap 之上的管理平台（统一管理 → 生成 → 校验 → 下发）
**话术/例题**：你们配置中心一键部署怎么做的？（生成 ConfigMap → kubectl apply → 滚动更新）。

---

## 🔗 微服务与分布式（26-30 题）

### 26. 微服务拆分原则？服务发现？
**一句话结论**：按业务域（DDD）拆、按团队边界拆、独立部署独立扩展；服务发现让服务互相找到（注册中心）。
**详细解释**：
- 拆分原则：单一职责、高内聚低耦合、按限界上下文、数据独立（每个服务自己的库）、按扩展需求拆
- 服务发现：注册中心（Consul/etcd/Nacos）——服务启动注册、心跳续约、客户端拉取/订阅
- 对比 K8s：K8s 的 Service/DNS 就是服务发现（rrmcontrol.rrmserver.svc.cluster.local）
**话术/例题**：你们 4 个微服务怎么拆的？（rrmcontrol 调度 / rrmserver 查询 / rrmcompute 计算 / aioptimize AI——按职责拆）为什么拆？（独立扩缩容、故障隔离）。

### 27. 分布式事务方案？
**一句话结论**：强一致用 2PC（少用），最终一致性用 Saga/本地消息表/事务消息，业务优先本地事务+消息兜底。
**详细解释**：
- 2PC/3PC：预提交+提交，强一致但阻塞、性能差，多数不用
- **本地消息表**：业务表和消息表同库事务，消息表轮询投递 MQ——简单可靠
- **事务消息**：RocketMQ 半消息（先发半消息 → 本地事务 → 确认/回滚），Kafka 无原生支持
- **Saga**：长事务拆成多步+补偿（正向各服务本地事务，失败逆向补偿）——适合跨服务
- 方案选择：资金类强一致用 TCC；一般业务本地消息表/事务消息最常用
**话术/例题**：你们调优链路（下发→计算→上报→生效）跨服务怎么做一致性？（可讲：链路状态机 + 超时重试 + 最终一致，不追求强事务）。

### 28. 熔断 / 限流 / 降级？
**一句话结论**：熔断=下游故障时快速失败保护（Circuit Breaker），限流=控制进入流量（令牌桶/漏桶），降级=故障时返回兜底数据。
**详细解释**：
- 熔断：连续失败 N 次 → 打开（直接拒绝）→ 半开（试探放行）→ 成功关闭；实现：Hystrix/Resilience4j/sentinel
- 限流：令牌桶（匀速放行、可突刺）/ 漏桶（恒定速率）；单机 vs 分布式（Redis 计数器/滑动窗口）
- 降级：超时降级（返回默认值）、失败降级（缓存兜底）、开关降级（配置中心控制功能开关）
**话术/例题**：你们设备上报高峰怎么防下游 DB 被打爆？（限流 + 批量入库 + 削峰）。追问：令牌桶和漏桶区别？→ 令牌桶允许突发，漏桶恒速。

### 29. 链路追踪原理？
**一句话结论**：traceId 贯穿整条调用链，span 记录每跳信息（耗时/服务/状态），上报汇聚成调用拓扑。
**详细解释**：
- traceId：请求入口生成，透传（HTTP header / MQ 消息头）给后续服务
- span：每个服务的一段处理（父 span → 子 span），含开始/结束时间、tags、logs
- 采集：客户端 SDK → 上报 collector（Jaeger/Zipkin/OpenTelemetry）→ 存储 → UI 展示瀑布图
- 无侵入方案：OpenTelemetry 自动埋点（中间件注入）
**话术/例题**：你们 4 微服务排查慢链路怎么做？（手动日志 traceId 关联 / 未来上 OTel）。追问：没有链路系统时怎么排查？→ 日志 grep traceId 串联（你们现网排查就常干这个）。

### 30. 接口幂等性（防重复提交）？
**一句话结论**：同一请求执行多次结果一致；用幂等键（前端生成 idempotency-key）+ Redis SETNX 判重。
**详细解释**：
- 场景：支付重试、表单重复提交、MQ 重投
- 方案：幂等键（请求头带唯一 ID）→ Redis SETNX 记录 → 已存在直接返回上次结果；或数据库唯一约束；或状态机（状态已变更直接返回成功）
- 注意：SETNX 要带过期时间防 key 堆积
**话术/例题**：你们调优指令重复下发怎么防？（按 taskId 幂等：已生效直接返回成功）。

---

## 🌐 网络（31-34 题，你的强项）

### 31. WebSocket 与 HTTP 长轮询？心跳机制？
**一句话结论**：WebSocket 是 TCP 上的全双工长连接（一次握手后双向实时推送）；长轮询是伪实时（请求挂着等数据）；心跳保活防断线。
**详细解释**：
- 握手：HTTP Upgrade: websocket（101 状态码）→ 切到 WS 协议
- 对比长轮询：长轮询每次都要重建 HTTP 请求，开销大；WS 一次连接持续用
- 心跳：客户端定时发 ping，服务端回 pong；超时未收到判定断线 → 重连（网络中间设备会掐空闲连接）
- 断线重连 + 消息补偿：重连后补拉离线消息（避免心跳断了丢数据）
**话术/例题**：你们 WebSocket+netconf 下发链路就是案例（云端 → AC 设备长连接下发指令）。追问：断线期间指令怎么办？→ 离线队列 + 重连补偿。

### 32. netconf 协议与 YANG 模型？
**一句话结论**：NETCONF 是网络设备配置管理协议（XML 传输 + YANG 建模），支持全量配置下发与增量编辑。
**详细解释**：
- 架构：客户端 ↔ 设备 NETCONF 服务（SSH 通道，port 830）
- 操作：get（读配置）、edit-config（改配置）、copy-config、commit、validate
- YANG：数据建模语言，定义配置树（容器/叶子/列表）；netconf 报文的 schema 就是 YANG
- 对比 SNMP：NETCONF 更现代（结构化 XML、事务性、回滚），适合云管理平台
**话术/例题**：你们云端到 AC 下发调优参数就是 netconf edit-config + YANG 定义参数模型——这是通信厂（中兴/锐捷/鼎桥）面试的差异化亮点，往深里讲。

### 33. node-ffi 调用 C 库的原理与注意事项？
**一句话结论**：node-ffi 通过 FFI（外部函数接口）在 JS 里直接调用 .so/.dll 中的 C 函数，运行时加载动态库 + 内存布局映射。
**详细解释**：
- 原理：dlopen 加载动态库 → 描述函数签名（参数/返回类型）→ 调用时按 ABI 约定传参（内存指针映射）
- 数据类型映射：int/char*/struct → number/Buffer/结构体描述
- 注意事项：指针生命周期（Buffer 别被 GC 回收）、内存释放（C 库分配的要调 free）、线程（C 函数阻塞会卡住 libuv 线程）、类型不匹配会段错误
- 替代方案：N-API 写 C++ addon（更稳，正式方案）、koffi（新一代 FFI）
**话术/例题**：你们 RRM 用 node-ffi 调 C 算法库（信道扫描计算）——讲"Buffer 传参 + 释放内存"的踩坑最有说服力。追问：为什么不用纯 JS 重写？→ 算法库是 C 写的且性能敏感，FFI 免移植。

### 34. TCP 粘包/拆包？如何解决？
**一句话结论**：TCP 是字节流无消息边界，多个消息粘一起（粘包）或一个消息被拆开（拆包）；用定长/分隔符/长度头解决。
**详细解释**：
- 原因：Nagle 算法合并小包；接收缓冲区一次性读多个包
- 解决：
  1. 定长消息（固定字节数，不足补齐）
  2. 分隔符（如 \r\n，HTTP 用）
  3. **长度头**（4 字节长度 + 内容，最常用，netty/自定义协议都用）
  4. 应用层协议封帧
- Buffer 端：Node 侧要自己拼包（把不完整的包暂存，凑够长度再处理）
**话术/例题**：你们设备上报协议怎么封帧？（长度头方案）。追问：Netty 的 LengthFieldBasedFrameDecoder 原理？→ 按长度字段自动拆帧（通信厂爱问）。

---

## 🛡️ 安全（35-37 题）

### 35. XSS / CSRF 原理与防御？
**一句话结论**：XSS 是注入恶意脚本（偷 cookie/伪造操作），CSRF 是利用浏览器自动带 cookie 伪造用户请求；XSS 靠转义过滤，CSRF 靠 token/同源校验。
**详细解释**：
- XSS：存储型（评论里存脚本）/反射型（URL 参数注入）/DOM 型；防御：输出转义、CSP、HttpOnly Cookie
- CSRF：用户在已登录状态下访问恶意网站，恶意网站发请求（浏览器自动带 cookie）完成转账等操作；防御：CSRF Token（自定义头）、SameSite Cookie、验证码
- 关系：XSS 能偷 token 绕过 CSRF 防御，所以 XSS 优先防
**话术/例题**：HttpOnly 为什么能防 XSS 偷 cookie？→ JS 读不到。你们的控制台管理平台做过哪些安全？（登录态、权限、接口鉴权）。

### 36. OAuth2 授权码流程？与 JWT 关系？
**一句话结论**：OAuth2 是授权框架（第三方拿授权码换 token 访问资源），JWT 是 token 格式，两者配合用。
**详细解释**：
- 授权码流程：用户访问第三方 → 跳转授权服务器登录 → 授权 → 回跳带 code → 第三方用 code 换 access_token → 带 token 访问资源服务器
- 角色：资源所有者（用户）、客户端（第三方 App）、授权服务器、资源服务器
- 简化：Authorization Code + PKCE（移动端）/ 客户端凭证（服务间）
- 与 JWT：JWT 可作 access_token 的格式（自包含）；OAuth2 管"授权流程"，JWT 管"凭证形态"
**话术/例题**：讲清"OAuth 管怎么授权，JWT 管 token 长什么样"。追问：为什么不直接给第三方我们的账号密码？→ 权限最小化 + 可撤销。

### 37. SQL 注入 / 越权防护？
**一句话结论**：SQL 注入=拼接用户输入进 SQL 被执行；越权=水平（改他人 ID 查别人数据）/垂直（普通用户调管理接口）；SQL 用参数化，越权靠后端鉴权+数据归属校验。
**详细解释**：
- SQL 注入：`WHERE id='1' OR '1'='1'`；防御：参数化查询（ORM/预编译）、白名单校验、最小权限 DB 账号
- 水平越权：只校验登录没校验"数据属于谁" → 查别人订单；防御：查询强制带 user_id 条件
- 垂直越权：前端藏按钮没用，后端要校验角色权限（RBAC）
**话术/例题**：后端为什么不能只依赖前端控制？（可绕过）。你们接口怎么防水平越权？（数据按租户/用户隔离查询）。

---

## 🧠 系统设计（38-40 题）

### 38. 设计一个分布式配置中心？
**一句话结论**：配置存储（DB）+ 版本管理 + 下发通道（推送/拉取）+ 客户端 SDK，核心是"改配置不重启、变更可追踪"。
**详细解释**（对应你们 RRM 配置中心）：
- 存储：配置项表（key-value + 版本号 + 环境/服务维度）
- 变更流程：编辑 → 校验（JSON 语法/值域）→ 发布（版本 +1）→ 推送（WebSocket/长轮询）或客户端定时拉取对比版本
- 客户端：启动拉全量 + 运行中监听变更（长轮询 /watch）
- 回滚：按版本回滚（你们做了）
- 高可用：配置存 DB + 本地缓存副本兜底
**话术/例题**：直接把你们配置中心的设计讲出来（统一管理 → 一键部署生成 ConfigMap → 自动校验 → 回滚），这是高级岗的拿分题。

### 39. 设计一个物联网设备数据上报系统？
**一句话结论**：接入层（协议适配/鉴权）→ 消息队列削峰 → 消费处理（校验/去重/入库）→ 存储（时序化）→ 监控告警。
**详细解释**（对应你们 RRM 上报链路）：
- 接入：设备 → 网关/直连，支持多协议（MQTT/HTTP/自定义 TCP），设备认证（token/证书）
- 削峰：Kafka 缓冲海量上报（你们 wlan_apcomp_lb 就是消息源）
- 处理：校验格式 → 幂等去重（taskId+设备）→ 业务处理 → 入库（MongoDB 按时间分片）
- 存储：时序数据考虑 TSDB；索引设计（taskId+apSN+RI）
- 稳定性：消费积压监控、失败重试、死信队列、告警
**话术/例题**：这就是你们 RRM 上报链路（设备 → Kafka → 消费 → MongoDB），把真实架构讲清楚 + 一个故障复盘（如消费积压怎么发现的）。

### 40. LLM 应用开发与 Agent/DAG 工作流？
**一句话结论**：LLM 应用 = Prompt + 工具调用（Function Calling）+ 上下文管理；Agent 用工作流编排多步 LLM 调用。
**详细解释**：
- 基础：Prompt 工程（角色/示例/输出约束）、RAG（检索增强，先查知识库再让 LLM 答）、Function Calling（LLM 输出结构化调用指令，代码执行后回填）
- Agent：LLM 做"大脑"决策 → 调用工具（搜索/查库/执行命令）→ 观察结果 → 循环；ReAct 模式
- DAG 工作流：多步骤编排（节点=LLM 调用/工具/条件分支），并行与依赖管理，可重试可观察
- 工程化：token 成本控制、流式输出、超时重试、结果缓存、评估（LLM 输出质量）
**话术/例题**：如果你做过 personalAgent/智能体项目可以讲；没有就讲"对 LLM 应用的理解 + 设计一个客服/运维智能体"（结合你 Oasis 云平台运维场景：设备问题自动诊断）。追问：Function Calling 原理？→ 定义工具 schema → LLM 输出参数 JSON → 校验执行。

---

## 📝 本章自测（闭卷）

1. 写出事件循环 6 阶段 + nextTick/setImmediate 区别 + 一段代码的输出顺序
2. Stream 背压是什么？pipe 和手写 data 事件的区别
3. cluster vs worker_threads 各自适用场景
4. NestJS 的 Module/Provider/Controller 三件套 + DI 好处
5. JWT 三段结构 + 为什么无状态 + 两个缺点
6. Kafka 如何保证不丢/不重？顺序性怎么保证
7. 画 K8s 访问链路（Ingress→Service→Pod）+ 两种探针区别
8. 熔断/限流/降级各是什么，各举一例
9. WebSocket 心跳 + 断线补偿（结合你的下发链路）
10. netconf 的 get/edit-config 是干什么的（通信厂必答）

> 完成自测后回《面试八股复习计划》勾选 Node.js 40 题
