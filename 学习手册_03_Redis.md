# 📘 学习手册 03 · Redis

> 配套《面试八股复习计划》第 2 节 Redis + PDF 第 66-70 页
> 结构：**概念（常显）→ 面试官会怎么问（常显）→ 答案与原理（点开）→ 拓展 + 追问 + 项目锚点**
> Java 岗必考；本文按「能扛住追问」标准编写，含可执行 redis-cli 命令、Lua 脚本与 Java 代码

---

## 1. Redis 为什么快 + 单线程模型

:::概念
四个原因叠加：**纯内存操作 + 单线程执行命令（无锁无切换）+ epoll I/O 多路复用 + 高度优化的底层数据结构**。
记忆钩子：**瓶颈在 IO 不在 CPU → 单线程够用；单线程又白送两个礼物：无锁、命令天然原子。**
:::

:::提问
- Redis 为什么这么快？
- 单线程为什么能扛住高并发？不怕 CPU 打满吗？
- 6.0 的多线程是怎么回事？命令执行也并行了？
- 哪些操作会阻塞 Redis 主线程？线上遇到过卡顿吗？
- 单线程怎么保证命令原子性？和「事务」是一回事吗？
:::

:::答案
### 快的四个来源

| 来源 | 具体机制 | 量级 |
|---|---|---|
| 纯内存 | 读写不落盘，持久化异步 | 内存随机读约 100ns，SSD 随机读约 100μs（差 1000 倍） |
| 单线程命令执行 | 无线程切换、无锁竞争、无死锁 | 上下文切换约 1~5μs |
| epoll 多路复用 | 一个线程监听上万 fd，就绪才处理 | 无连接数上限（select 有 1024 限制） |
| 数据结构 | SDS、listpack、跳表、渐进式 rehash | `ZSCORE` O(1)、`ZRANGEBYSCORE` O(logN+M) |

### 单线程到底指什么

准确表述：**「命令执行」是单线程，「IO、持久化、异步释放」不是。** 这一点答错就露馅。

| 线程/进程 | 干什么 | 什么时候有 |
|---|---|---|
| 主线程 | 接收命令、执行命令、写回复 | 一直 |
| `bio_close_file` | 异步关闭文件、`UNLINK` 释放内存 | lazy free 触发时 |
| `bio_aof_fsync` | AOF 每秒 fsync | `appendfsync everysec` |
| `bio_lazy_free` | 异步释放大对象内存 | 4.0+，配 `lazyfree-*` |
| 子进程 | `BGSAVE` / `BGREWRITEAOF` | fork 出来的，与主线程并行 |
| IO 线程（6.0+） | 只做 socket 读和写（解析/执行仍在主线程） | `io-threads 4` 才启用 |

### 6.0 多线程 I/O 的真实边界

```bash
# 查看当前配置
redis-cli CONFIG GET io-threads
# io-threads
# 1                       # 默认 1 = 关闭多线程

# 开启（建议 4 核以上再开，最大 8）
redis-cli CONFIG SET io-threads 4
redis-cli CONFIG SET io-threads-do-reads yes   # 默认 no，只多线程写，开了才多线程读
redis-cli CONFIG REWRITE                        # 落盘，否则重启失效
```

**关键结论：多线程只负责「把网络数据读进来 / 把结果写出去」，命令解析和命令执行永远在主线程串行。** 所以「Redis 6.0 变多线程了，原子性没了吗」这个追问，答案是没变。作者开多线程的原因是网卡从 1G 升到 10G/25G，单线程在 `read()/write()` 系统调用和协议解析上成了瓶颈，不是因为命令执行慢。

### 为什么会阻塞——面试高频

| 命令/操作 | 复杂度 | 阻塞原因 | 替代方案 |
|---|---|---|---|
| `KEYS *` | O(N) | 遍历全库，N 大时秒级阻塞 | `SCAN 0 MATCH k:* COUNT 1000` |
| `FLUSHALL` / `FLUSHDB` | O(N) | 释放所有 key 的内存 | 4.0+ 加 `ASYNC`：`FLUSHALL ASYNC` |
| `DEL` 大 key | — | 释放几百万元素内存 | `UNLINK`（4.0+） |
| `HGETALL` / `SMEMBERS` 大 key | O(N) | 一次性构造大回复，缓冲区和带宽双爆 | `HSCAN` / `SSCAN` 游标迭代 |
| `SORT`、`ZUNIONSTORE` 大集合 | O(N logN) | CPU 密集 | 业务侧排序，或加 limit |
| `SAVE`（非 BGSAVE） | O(N) | 主线程写全量 RDB | 永远用 `BGSAVE` |
| Lua 脚本里的大循环 | — | 脚本期间不处理任何命令 | 拆脚本、限循环次数 |
| `MONITOR` | — | 复制所有命令给监控客户端 | 别在生产长挂 |
| fork（BGSAVE/AOF 重写） | — | 复制页表时阻塞主线程 | 见第 5、7 题 |
| AOF `appendfsync always` | — | 每个写命令都等 fsync 落盘 | `everysec` |

### 命令原子性与事务的区别

**单条命令天然原子**（单线程执行，中间不会被插入）——这是免费送的。但**多条命令不是原子的**，`GET` 完再 `SET` 中间可能被其他客户端插进来。要跨命令原子必须用 `MULTI/EXEC` 或 Lua（见第 17 题）。

```bash
# 确认原子性的经典场景：INCR 不会丢更新
redis-cli SET counter 0
redis-cli INCR counter          # 1000 个客户端并发 INCR，结果一定是 1000
# 等价于单线程里「读-加-写」三步永不被打断
```

### 卡顿排查第一现场

```bash
redis-cli --latency                 # 持续采样基准延迟（本地应 < 1ms）
redis-cli --latency-history         # 分时段看延迟分布
redis-cli --intrinsic-latency 100   # 排除 Redis，先看机器本身有没有卡（100 秒采样）
redis-cli SLOWLOG GET 10            # 慢查询
redis-cli INFO commandstats         # 按命令统计调用次数与总耗时，找 CPU 消耗大户
redis-cli LATENCY HISTORY event     # 延迟事件（需先设 latency-monitor-threshold）
```
:::

:::拓展
**hz 参数决定定时任务的精度**

`hz` 默认 10，即每秒 10 次 `serverCron`（每 100ms 一次）——过期 key 的定期删除、渐进式 rehash 的时间片、客户端超时检测都在这个循环里。`hz` 调大（如 100）会让过期 key 清理更及时、但 CPU 空转更多；Redis 4.0+ 默认 `dynamic-hz yes`，空闲时自动降到低频率省电。

**epoll vs select vs poll**（Linux 下 Redis 用的是 `ae_epoll.c`）

| | select | poll | epoll |
|---|---|---|---|
| fd 上限 | 1024（`FD_SETSIZE`） | 无 | 无 |
| 每次调用 | 全量拷贝 fd 数组 + O(n) 遍历 | 全量 O(n) | 红黑树注册一次，就绪链表只返回就绪 fd，O(1) |
| 触发方式 | LT | LT | LT / ET |

Redis 用 **LT（水平触发）**：只要 socket 缓冲区还有数据，下次 `epoll_wait` 还会返回它，代码简单不易漏读。Nginx 默认 ET（要求一次读完，配合非阻塞循环）。

**6.0 之前 Redis 就有一个「后台线程」**：`bgwrite`/`fsync` 相关的 bio 线程从 4.0 就有了，只是不做网络 IO。所以别把「6.0 首次引入多线程」当成准确表述。
:::

:::追问
**Q：既然单线程，那 Redis 是怎么处理几万个连接同时发请求的？**
epoll 把「等数据」这件事交给了内核：主线程只在 `epoll_wait` 上阻塞，谁的数据到了就绪链表里有谁。事件循环里逐个处理已就绪的 socket，处理完再回到 `epoll_wait`。所以是「一个线程轮转处理 N 个就绪连接」，而不是「一个线程一直等着某个连接」。连接数上限取决于 `maxclients`（默认 10000）和文件描述符 `ulimit -n`。

**Q：单线程下 CPU 打满一般是什么原因？**
按概率排序：① 大 key 上的 O(N) 命令（`HGETALL`/`SMEMBERS`/`KEYS`）；② 大量小命令的网络往返（RTT 主导，属于 IO 型打满，用 Pipeline 合并）；③ 过期 key 集中到期（大量 key 同一秒过期 → `activeExpireCycle` 反复采样）；④ Lua 脚本里有重循环；⑤ fork 频繁（`latest_fork_usec` 高）。用 `INFO commandstats` 看哪个命令 `usec_per_call` 异常。

**Q：`io-threads` 设多少合适？**
不超过 CPU 核数减 1，且不超过 8（配置上限）。Redis 官方给的参考：4 核设 2~3，8 核设 6。IO 线程只在网络吞吐真的成为瓶颈（如 10Gbps 以上网卡或大 value 场景）才有效；普通业务开了没收益反而多线程调度开销。**8.0 起改成 `io-threads` 上限 8 仍在，另外新增了 `io-threads-do-reads` 的默认行为调整**——面试只需答到「6.0 多线程只做网络读写」这一层。
:::

:::锚点
你的 rrmcontrol 是 Node.js 单线程模型 —— **这和 Redis 单线程是同一个设计哲学**：事件循环 + 非阻塞 IO，把「等 IO」交给内核。区别是 Node 里一旦有 CPU 密集代码（比如大 JSON 的序列化/反序列化）就会阻塞整个事件循环，跟 Redis 里跑 `KEYS *` 是同一类事故。

你项目最真实的对应场景：rrmcontrol 的调优任务 scheduler **每 60s 触发一次**，如果这个 tick 里同步做了大量 MongoDB 查询 + Kafka 发送，pod 就会周期性「卡一下」——这跟 Redis 的 `serverCron` 每 100ms 干一次活（过期删除、渐进式 rehash）是同一个结构。

面试话术：「我在 Node.js 里长期做单线程事件循环的服务，很熟悉『一条慢命令拖垮整个进程』的形态。所以我在用 Redis 时天然会避开 `KEYS`、`HGETALL` 大 key 这类操作，全部改用 `SCAN` 系游标迭代——这不是背八股，是踩过同款坑的本能。」
:::

---

## 2. 五大基础类型的底层数据结构

:::概念
String→**SDS**；List→**quicklist**（双向链表 + 每节点 listpack）；Hash/ZSet 小数据→**listpack**、大数据→**hashtable + 跳表**；Set→**intset / listpack / hashtable**。
记忆钩子：**「小数据用连续内存的 listpack 省空间，长大了自动升级成哈希表/跳表省时间——Redis 的编码是随大小动态切换的。」**
:::

:::提问
- String 的底层是什么？为什么不用 C 的 char\*？
- ziplist 和 listpack 什么区别？为什么 7.0 要换掉 ziplist？
- ZSet 为什么用跳表不用红黑树？
- 什么是渐进式 rehash？
- 同一个类型怎么会有好几种编码？
:::

:::答案
### 五种类型的编码切换全表

| 类型 | 小数据编码 | 大数据编码 | 切换阈值（默认） |
|---|---|---|---|
| String | int（能转数字）/ embstr（≤44 字节） | raw（SDS） | `append` 后长度 > 44 → raw |
| List | listpack | quicklist | `list-max-listpack-size -2`（每节点 8KB） |
| Hash | listpack | hashtable | `hash-max-listpack-entries 128`、`hash-max-listpack-value 64`（Redis 7.0 前是 `hash-max-ziplist-*`） |
| Set | intset（全整数）/ listpack | hashtable | `set-max-intset-entries 512`、`set-max-listpack-entries 128` |
| ZSet | listpack | skiplist + hashtable | `zset-max-listpack-entries 128`、`zset-max-listpack-value 64` |

查看实际编码：

```bash
redis-cli rpush mylist a b c
redis-cli object encoding mylist        # listpack
redis-cli rpush mylist $(seq 1 200)     # 撑大
redis-cli object encoding mylist        # quicklist

redis-cli hset h f1 v1
redis-cli object encoding h             # listpack
redis-cli config set hash-max-listpack-entries 2 && redis-cli hset h f2 v2
redis-cli object encoding h             # hashtable（超阈值立即转）
```

### SDS（简单动态字符串）

```c
struct sdshdr8 {
    uint8_t  len;      // 已用长度
    uint8_t  alloc;    // 已分配容量（不含头和 \0）
    unsigned char flags;  // 低 3 位标识类型（sdshdr5/8/16/32/64）
    char     buf[];    // 数据，仍以 \0 结尾（兼容 C 函数）
};
```

5 种头（`sdshdr5/8/16/32/64`）按字符串长度选最小的，**短字符串不浪费 8 字节存长度**。

**为什么不用 C 字符串（`char *`）—— 四点**

| C 字符串的问题 | SDS 的解决 |
|---|---|
| 取长度要 `strlen()` O(N) | 存 `len` 字段，`STRLEN` O(1) |
| 以 `\0` 判断结尾，存不了二进制 | 按 `len` 判断，**二进制安全**（可存图片/序列化对象/`\0`） |
| 拼接前要手动检查容量，易缓冲区溢出 | 拼接前自动检查 `alloc`，不够就扩容 |
| 每次修改都可能 `realloc` + 拷贝 | **空间预分配**（`len<1MB` 时 `alloc=2*len`；`≥1MB` 时多给 1MB）+ **惰性释放**（缩短不立即还内存，留着下次用） |

### ziplist → listpack：解决「级联更新」

**ziplist 的结构**：一整块连续内存，每个节点是 `<prevlen, encoding, data>`。`prevlen` 记录**前一个节点的长度**，1 字节（<254）或 5 字节。

**级联更新的坑**：往中间插入一个长度 254 字节的元素 → 它后面那个节点的 `prevlen` 从 1 字节被迫扩成 5 字节 → 该节点总长变了 → 再后面一个节点的 `prevlen` 又可能被迫扩展……**一次插入引发整条链的连锁重分配**，最坏 O(N²)。

**listpack 的解法**：每个节点存 `<encoding, data, backlen>`，`backlen` 记录**自身**的长度（变长编码，最多 5 字节，仍支持从后往前遍历），**不存前驱长度**，级联更新彻底消失。

```bash
# 7.0 里这两种编码的实际面貌
redis-cli config get hash-max-listpack-entries   # 7.0+ 用 listpack 命名
redis-cli object encoding small_hash             # listpack
# 6.x 及以前
# hash-max-ziplist-entries / zset-max-ziplist-entries
```

### 跳表（skiplist）：为什么不用红黑树

```c
#define ZSKIPLIST_MAXLEVEL 32      /* 最大层数 */
#define ZSKIPLIST_P 0.25           /* 每层晋升概率 */

typedef struct zskiplistNode {
    sds ele;                        /* 成员 */
    double score;                   /* 分值，排序依据 */
    struct zskiplistNode *backward; /* 后退指针，支持 ZREVRANGE */
    struct zskiplistLevel {
        struct zskiplistNode *forward;
        unsigned long span;         /* 跨度，用于 ZRANK 算排名 */
    } level[];
} zskiplistNode;
```

**跳表的四个优势**

| 维度 | 跳表 | 红黑树 |
|---|---|---|
| 范围查询 `ZRANGEBYSCORE` | 底层是有序链表，**找到起点顺序走**即可，天然契合 | 需要中序遍历 + 迭代器维护，实现复杂 |
| 插入/删除 | 只改局部指针，**无旋转** | 需要旋转再平衡，代码路径多 |
| 排名 `ZRANK` | 节点带 `span`，查找过程中累加即可 O(logN) | 需要额外维护子树 size 字段 |
| 实现难度 | 约几百行 | 平衡逻辑易写错 |
| 内存 | 平均每节点 1.33 个指针（p=0.25） | 每节点固定 3 指针 + 颜色位 |

**注意：Redis 的 ZSet 是「跳跃表 + 字典」两个结构并用**，不是二选一——字典提供 `ZSCORE` 的 O(1)（member→score），跳表提供有序范围查询（score→member）。用两种结构换两种查询的最优复杂度，代价是内存。

### 渐进式 rehash（重点，必背）

Redis 的 `dict` 有两个哈希表：**`ht[0]`（当前）+ `ht[1]`（扩容目标）**，加一个 `rehashidx` 游标。

```
扩容触发条件（dict_can_resize）：
  负载因子 >= 1  且 无 BGSAVE/BGREWRITEAOF  → 扩容到 >= used*2 的最小 2^n
  负载因子 >= 5  （不管有没有 fork）        → 强制扩容
  负载因子 < 0.1 且无持久化子进程           → 缩容

渐进式过程：
  ① 为 ht[1] 分配空间，rehashidx = 0
  ② 每次增/删/查/改都顺带把 ht[0][rehashidx] 这个桶的全部节点搬到 ht[1]，rehashidx++
  ③ serverCron 每 100ms 抽出 1ms 专门做搬迁（rehash 时间片）
  ④ rehashidx == -1 时结束：释放 ht[0]，ht[1] 变成新 ht[0]
```

**查找/删除/更新时两个表都要查**（先查 `ht[0]`，找不到再查 `ht[1]`）；**新增只写 `ht[1]`**，保证 `ht[0]` 的键只减不增，rehash 一定收敛。

```bash
# 观察 rehash 状态
redis-cli info memory | grep rehash
redis-cli debug htstats 0     # 需要 debug 命令被启用，能看到 rehashidx
```

**为什么必须渐进**：一次搬 100 万个 key 会阻塞主线程几百毫秒，redis 宁可拉长到几秒钟分散搬运。
:::

:::拓展
**一个 Hash 存字段还是拆成多个 String？—— 内存账要算清**

| 方案 | 优点 | 缺点 |
|---|---|---|
| 一个 Hash 存整对象 | 字段级读写、省内存（小 hash 用 listpack，几乎没有 overhead） | 大 hash 会变成 hashtable；单 key 热点集中 |
| 每字段一个 String | 粒度细、可单独过期 | 每个 key 都有 dictEntry + redisObject + SDS 头，**内存放大 3~10 倍** |

经验值：用 `String` 存 `user:1001:name` 这种散 key，100 万个 key 大约要 100MB+；换成 `user:1001` 一个 Hash 存所有字段，同样的数据可能只要 20~30MB。**Redis 是内存数据库，key 的数量本身就是成本。**

**`OBJECT ENCODING` 是排查神器**：线上看到一个 Hash 内存异常大，先 `OBJECT ENCODING` 看编码——如果本该是 listpack 的大 hash 变成了 hashtable，说明它超过了 128 个字段或某个 value 超了 64 字节。

**listpack 也有硬伤**：它是连续内存，**插入/删除中间元素要 memmove 后半段**。这就是为什么 List 没人从中间插，只用 `LPUSH`/`RPOP`。而 List 的 `LINSERT`（在某个元素前后插入）在 listpack 节点里是 O(N)。
:::

:::追问
**Q：Hash 的字段数为 129 时发生了什么？**
立即从 listpack 转成 hashtable：**遍历整块 listpack，把每个 field/value 转成 dictEntry 插进哈希表，然后释放 listpack**。这是一次 O(N) 操作，且在主线程完成。**所以「刚好卡在阈值上下反复横跳」是性能陷阱**（加一个字段转 hashtable，删一个字段**不会**转回 listpack——编码转换是单向的、不可逆的）。设计时要么明显小于 128，要么干脆按哈希表预算内存。

**Q：跳表的层数是怎么决定的？**
插入时循环 `while (random() < 0.25) level++`，最大 32 层。期望层数 1/(1-0.25) = 1.33。**期望查询复杂度 O(log N)**，实际节点数 100 万时最高层大约 10 层。

**Q：intset 和 listpack 存 Set 有什么区别？**
`intset` 是**有序的整数数组**（二分查找 O(logN)），且会按元素大小升级（`int16`→`int32`→`int64`，升级不可逆）。一旦插入非整数元素，`intset` 立即转 `listpack`（7.0 前是转 `hashtable`）。所以 `SADD tags 1 2 3` 存的是 intset，`SADD tags 1 a` 直接变 listpack。

**Q：为什么 String 有 `embstr` 和 `raw` 两种？**
`embstr` 把 `redisObject` 头和 SDS **分配在同一块连续内存**里（一次 malloc），只用于 ≤44 字节的字符串，读的时候 CPU 缓存友好。超过 44 字节就变成 `raw`（两次 malloc，头和数据分开）。**44 = 64 - 16（redisObject 大小）- 3（SDS 头）- 1（\0）**——这个数字面试常被追问。
:::

:::锚点
你从 Node.js 转 Java，Redis 数据结构的选型是必须补的课。一个和你工作直接相关的例子：

**RRM 的调优任务状态**在 rrmcontrol 里如果用 Redis 存，选择是这样的——
- 存「某个场所的调优任务锁」→ **String**（`SET task:lock:{siteId} uuid NX PX 60000`），因为只需要一个标记；
- 存「某 AP 的最新调优结果快照」→ **Hash**（字段级更新，避免整体序列化再反序列化，省带宽）；
- 存「按时间排序的待执行任务」→ **ZSet**（`score` = 执行时间戳），轮询 `ZRANGEBYSCORE key 0 now LIMIT 0 10` 取到期任务，比 List 更灵活（可以按分数范围取、可以删单个任务 `ZREM`）；
- 存「已上报的 AP 序列号去重」→ 更好的选择是 **HyperLogLog**（只算基数）或 **Bitmap**（如果能映射成连续 ID），而不是 Set——Set 存 100 万个 32 字节的序列号要 32MB+，HLL 固定 12KB。

**如果你没在项目里真的用过这些结构**，面试时就诚实说：「我们缓存主要是 String 和 Hash，ZSet 我做延时队列的思路是通的但项目里没用上。」——编造「我们用 ZSet 做了百万级排行榜」这种经历，被追问分片、内存占用、`ZRANGE` 复杂度时必翻车。
:::

---

## 3. 数据类型选型与高级类型

:::概念
五种基础类型之外，4 种「省内存/专用」类型值得掌握：**Bitmap（位统计）、HyperLogLog（基数估算，12KB 估 2^64）、GEO（地理位置）、Stream（消息队列）**。
记忆钩子：**「Bitmap 省到 1 bit，HLL 省到 12KB 且允许 0.81% 误差，Stream 是 Redis 唯一带 ACK 的结构。」**
:::

:::提问
- 怎么用 Redis 做签到 / UV 统计 / 排行榜 / 延时队列 / 限流？
- HyperLogLog 原理是什么？为什么只要 12KB？
- Bitmap 和 Set 存用户 ID 怎么选？
- 让你设计一个「每天 1000 万次请求的接口限流」，用 Redis 怎么做？
:::

:::答案
### 选型速查表

| 需求 | 选型 | 关键命令 | 复杂度/成本 |
|---|---|---|---|
| 计数、缓存对象、分布式锁 | String | `INCR` / `SET NX PX` | O(1) |
| 存对象、字段级更新 | Hash | `HSET` / `HINCRBY` | O(1) |
| 简单队列（先进先出） | List | `LPUSH` + `BRPOP` | O(1) |
| 最新 N 条列表、固定长度 | List | `LPUSH` + `LTRIM 0 99` | O(1) |
| 去重、标签、共同好友 | Set | `SADD` / `SINTER` | O(1) / O(N*M) |
| 排行榜、延时队列、带权队列 | ZSet | `ZADD` / `ZRANGEBYSCORE` | O(logN) |
| 用户签到、活跃统计（连续 ID） | Bitmap | `SETBIT` / `BITCOUNT` | O(1) / O(N/8) |
| UV 去重（允许 0.81% 误差） | HyperLogLog | `PFADD` / `PFCOUNT`（`PFMERGE` 合并） | O(1)，固定 12KB |
| 附近的人、距离排序 | GEO | `GEOADD` / `GEOSEARCH` | O(logN) |
| 可靠消息队列（消费组 + ACK） | Stream | `XADD` / `XREADGROUP` / `XACK` | O(1) / O(logN) |

```bash
# 排行榜（ZSet）——注意用 ZREMRANGEBYRANK 保 Top N，防止无限增长
redis-cli zadd rank 100 alice 250 bob 180 carol
redis-cli zrevrange rank 0 9 WITHSCORES          # Top 10
redis-cli zscore rank bob                        # O(1)，靠的是内部那个 dict
redis-cli zrank rank bob                         # O(logN)，靠 skiplist 的 span
redis-cli zremrangebyrank rank 0 -1001           # 只保留分数最高的 1000 个

# 延时队列（ZSet，score = 到期时间戳）
redis-cli zadd delay_queue $(date -d '+5 seconds' +%s) '{"taskId":"t1"}'
redis-cli zrangebyscore delay_queue 0 $(date +%s) LIMIT 0 10
redis-cli zrem delay_queue '{"taskId":"t1"}'     # 取出后删（要先删再处理，防重复）

# 签到（Bitmap，offset = 一年中的第几天），1 个用户 1 年只占 46 字节
redis-cli setbit sign:u1001 0 1                  # 第 1 天签到
redis-cli setbit sign:u1001 364 1                # 第 365 天签到
redis-cli bitcount sign:u1001                    # 全年签到天数
redis-cli bitcount sign:u1001 0 2                # 只统计第 3 字节（8 天）内的
redis-cli bitop and dest sign:u1001 sign:u1002   # 连续签到用户求交集

# UV 统计（HyperLogLog）
redis-cli pfadd uv:20260918 user1 user2 user3
redis-cli pfcount uv:20260918                    # 约 3
redis-cli pfmerge uv:week uv:20260917 uv:20260918  # 合并多天

# GEO
redis-cli geoadd city 116.40 39.90 "北京" 121.47 31.23 "上海"
redis-cli geosearch city FROMLONLAT 116.40 39.90 BYRADIUS 100 km ASC
```

### HyperLogLog 为什么这么省

**原理**：把每个元素哈希成 64 位，看哈希值二进制里**第一个 1 出现在第几位**。随机性下，如果观测到的最大前导零位数是 k，说明大约处理了 `2^k` 个元素。为降低方差，HLL 用 16384 个桶（每个 6 bit 存 k），各桶取调和平均 → 标准差约 `1.04/√16384 ≈ 0.81%`。16384 × 6 bit = 98304 bit = **12KB**，固定不增长。

**代价**：只能算基数，**不能判断某个元素是否存在**（没有 `PFEXISTS`）、不能列出元素、给定基数下限不精确。

| 方案 | 100 万 UV 的内存 | 能否判断存在 | 误差 |
|---|---|---|---|
| Set | 约 30~60MB | 能 | 0 |
| Bitmap（ID 连续） | 约 125KB（100 万 bit） | 能 | 0 |
| HyperLogLog | **12KB** | 不能 | 0.81% |

### 限流三种实现

```bash
# 方案一：固定窗口计数（最简单，有临界问题）
#   INCR + EXPIRE 不是原子的，必须用 Lua（见第 17 题）

# 方案二：滑动窗口（ZSet 存请求时间戳）
#   ZREMRANGEBYSCORE key 0 (now - window)   清掉窗口外的
#   ZCARD key                                计数
#   ZADD key now requestId
#   EXPIRE key window

# 方案三：令牌桶 / 滑动窗口 Lua（生产推荐，单脚本原子）
```

```lua
-- 固定窗口限流：KEYS[1]=限流key  ARGV[1]=窗口秒数  ARGV[2]=最大请求数
-- 返回 1 放行，0 拒绝
local current = redis.call('INCR', KEYS[1])
if current == 1 then
    redis.call('EXPIRE', KEYS[1], ARGV[1])   -- 只在第一次设置，避免每次都续期
end
if current > tonumber(ARGV[2]) then
    return 0
end
return 1
```

```bash
redis-cli --eval rate_limit.lua rate:api:u1001 , 60 100
```

### 四个「不要用 Redis 做」的坑

1. **不要用 List 做需要 ACK 的任务队列**——`BRPOP` 弹出后进程崩溃，这条消息就丢了（除非用 `LMOVE` 做「处理中队列」再 `LREM`，即可靠队列模式）。
2. **不要用 Hash 的字段做无限增长**——比如「每个用户一个 Hash 存历史记录」，字段只增不减，最终变 hashtable + 内存爆。要设上限（`HDEL` 老的、或改成 ZSet 按时间淘汰）。
3. **不要把大对象序列化后塞 String**——1MB 的 value 会让网络、fork COW、慢查询全部变差。超过 10KB 就该考虑拆分。
4. **不要用 `KEYS` / `FLUSHALL` / `SMEMBERS`（大集合）生产直接调**。
:::

:::拓展
**Stream 的核心概念（唯一带 ACK 的结构，5.0+）**

| 概念 | 对应命令 | 说明 |
|---|---|---|
| 消息 | `XADD stream * field value` | `*` 让 Redis 生成时间戳 ID（`毫秒-序号`） |
| 消费组 | `XGROUP CREATE stream g1 0` | 多个组各自独立消费全量消息 |
| 读新消息 | `XREADGROUP GROUP g1 c1 COUNT 10 BLOCK 2000 STREAMS stream >` | `>` 表示只要没投递过的 |
| ACK | `XACK stream g1 <id>` | 确认处理完，从 PEL 里移除 |
| 查未确认 | `XPENDING stream g1` | 哪些消息已投递未 ACK |
| 认领 | `XCLAIM stream g1 c2 60000 <id>` | 消费者挂了，把超时未 ACK 的消息转给别人 |
| 截断 | `XTRIM stream MAXLEN ~ 1000000` | 控制内存 |

`XCLAIM` + `XPENDING` 一起用才等于 Kafka 的「消费位点 + 重平衡」，这也是 Redis Stream 能当轻量 MQ 的原因。但**没有死信队列、没有分区、单 key 无法横向扩展**——数据量大时还是 Kafka（见第 18 题）。

**限流的另一条路**：Redisson 提供了现成的 `RRateLimiter`（基于 Lua 的令牌桶），Java 侧一行 `tryAcquire()` 就行；Spring Cloud Gateway 也有 `RequestRateLimiter` + Redis。**面试问限流，先答算法（固定窗口 / 滑动窗口 / 令牌桶 / 漏斗），再答实现（Redis + Lua 原子），最后答分布式一致性（多实例共享同一个 Redis key）。**
:::

:::追问
**Q：ZSet 做排行榜，100 万成员占多少内存？**
每个成员约 跳表节点（score 8 + backward 8 + level 数组约 1.33×16 ≈ 21 字节 + ele 指针 8）≈ 45 字节，加 dictEntry（约 24 字节）+ SDS 头 + 成员本身。粗略估 100 字节/成员 → **约 100MB**。这个量级估算能力比背命令有用得多——面试官问「一个 ZSet 能放多少」，你要能立刻反算出量级。

**Q：Bitmap 的 offset 很大怎么办？**
`SETBIT key 1000000000 1` 会**立即分配 125MB**（offset/8）。所以 Bitmap 只适合「ID 密集且上限可控」的场景（如用户 ID 递增）。如果用户 ID 是雪花算法生成的 19 位数字，直接当 offset 会瞬间打爆内存——要先做一层「ID → 连续序号」的映射，或者换 HyperLogLog。

**Q：`PFCOUNT` 为什么是近似值？**
HLL 不做精确去重，只统计「哈希值的最大前导零位数」，用概率反推基数。误差 0.81%，但 `PFCOUNT` 是 O(1)（读 16384 个桶算调和平均）。`PFMERGE` 是把多个 HLL 的桶逐位取 max，O(N) 但 N=16384 常数。

**Q：为什么 `SETBIT`/`GETBIT` 也能做去重，跟 Set 怎么选？**
Bitmap 只适合**元素本身可以映射成整数偏移**的场景（用户 ID、日期序号）。Set 存的是字符串，通用但每条要几十字节。判断依据一句话：**「这个元素能不能变成一个不太大的整数」——能就用 Bitmap，不能就用 Set 或 HLL。**
:::

:::锚点
你的 RRM 业务里有两个天然适合这些结构的场景（**只讲你有依据的，别编**）：

① **AP 在线/离线状态统计**：RRM 要统计某场所下在线的 AP 数量。如果 AP 有连续的内部编号，用 Bitmap `SETBIT online:{siteId} apIndex 1`，`BITCOUNT` 一次拿到在线数——1 万个 AP 只要 1.25KB。**这比用 Set 存 AP 序列号省一个数量级内存**（Set 里每个序列号字符串至少 40+ 字节）。

② **调优任务去重/互斥**：你项目里 scheduler 每 60s 触发一次、多 pod 部署，用 Redis 做任务互斥。这里最该注意的是**锁的 key 设计**——按场所维度拆（`rrm:tuning:lock:{siteId}`）而不是一个全局大锁，否则所有场所的调优全部串行，scheduler 的 60s 周期一超时就会堆积。

**Java 侧对照（补课内容）**：Spring Data Redis 里 `StringRedisTemplate.opsForValue().setIfAbsent(key, val, Duration.ofSeconds(30))` 就是 `SET NX PX`；Redisson 里 `redissonClient.getLock(name).tryLock(0, 30, TimeUnit.SECONDS)`。注意 `opsForValue` / `opsForHash` / `opsForZSet` 的命名直接对应五种数据类型，用哪个 `opsFor` 就对应哪个 Redis 结构。
:::

---

## 4. 过期删除策略与内存淘汰

:::概念
两套**完全不同**的机制，必须先分清：
- **过期删除**：key 到期了怎么清 → **惰性删除 + 定期删除**（不是定时器，Redis 里没有「每个 key 一个定时器」这种东西）。
- **内存淘汰**：内存到 `maxmemory` 了删谁 → **8 种 `maxmemory-policy`**。
记忆钩子：**「过期看 TTL，淘汰看内存；过期是省空间，淘汰是保命。」**
:::

:::提问
- 过期 key 是怎么删的？为什么不用定时器？
- `maxmemory-policy` 有哪几种？你们线上设的哪个？
- Redis 的 LRU 是精确 LRU 吗？
- LFU 和 LRU 区别？什么场景用 LFU？
- `maxmemory` 该设多少？
:::

:::答案
### 两套机制对照

| | 过期删除 | 内存淘汰 |
|---|---|---|
| 触发条件 | key 的 TTL 到期 | `used_memory > maxmemory` |
| 作用对象 | **设了 `EXPIRE` 的 key** | 按策略选，可能是所有 key |
| 机制 | 惰性删除 + 定期删除 | 8 种 `maxmemory-policy` |
| 配置 | `EXPIRE` / `PEXPIRE` / `EXPIREAT` | `maxmemory`、`maxmemory-policy`、`maxmemory-samples` |
| 不做会怎样 | 内存里躺着一堆死数据 | 写入报错（`noeviction`）或 OOM 被系统杀 |

### 惰性删除 + 定期删除

```bash
redis-cli config get hz                          # 默认 10，即每秒 10 次 serverCron
redis-cli config get maxmemory-policy
redis-cli config get maxmemory
```

**惰性删除**：每次读写 key 前调 `expireIfNeeded()`——如果发现已过期，**从库删掉并返回 nil**。
优点：零额外开销；缺点：**如果一个过期 key 再也不被访问，它就永远躺在内存里**。

**定期删除**（`activeExpireCycle`，跑在 `serverCron` 里，即每 100ms 一次）：
1. 从设了过期时间的 key 中**随机抽 20 个**（`ACTIVE_EXPIRE_CYCLE_LOOKUPS_PER_LOOP`）
2. 删掉其中已过期的
3. **如果过期比例 > 25%，立刻再来一轮**（防止过期 key 堆积）
4. 单次执行时间不超过 25% 的 CPU 时间（`ACTIVE_EXPIRE_CYCLE_SLOW_TIME_PERC`），超时就退出让主线程干活
5. Redis 会对每个 db 轮询，不是只扫 db0

**为什么不用定时器**：100 万个 key 每个带一个定时器 = 100 万个定时器对象 + 高频触发，CPU 直接爆炸。**随机抽样 + 比例自适应**是 O(1) 内存、可控 CPU 的工程折中。

**主从的过期语义（高频追问）**：**从节点不主动删除过期 key**——它只等主节点发来的 `DEL`。从节点读到过期 key 时会返回 nil（3.2+，逻辑判断），但**内存里那份数据还在**。3.2 之前从库会读到过期数据。所以看到从库 `used_memory` 比主库高、`expired_keys` 为 0，是正常的。

### 8 种淘汰策略

```bash
redis-cli config get maxmemory-policy
redis-cli config get maxmemory-samples     # 默认 5
redis-cli config get maxmemory-clients     # 客户端输出缓冲的限制（7.0+）
```

| 策略 | 候选集 | 算法 | 适用 |
|---|---|---|---|
| `noeviction` | — | **不淘汰，写入直接报错** | **默认值**；不可丢数据的场景 |
| `allkeys-lru` | 所有 key | 近似 LRU | **通用推荐**：纯缓存场景 |
| `allkeys-lfu` (4.0+) | 所有 key | 近似 LFU | 有稳定热点（热搜、商品详情） |
| `allkeys-random` | 所有 key | 随机 | 访问概率均匀时（少见） |
| `volatile-lru` | 只有设了 TTL 的 | 近似 LRU | 缓存 + 持久数据混存，只淘汰缓存的 |
| `volatile-lfu` (4.0+) | 只有设了 TTL 的 | 近似 LFU | 同上 + 热点保护 |
| `volatile-random` | 只有设了 TTL 的 | 随机 | 少用 |
| `volatile-ttl` | 只有设了 TTL 的 | **剩余 TTL 最短优先** | 少用（等价于最早过期的先删） |

**`volatile-*` 的致命细节**：如果所有 key 都没设 TTL，`volatile-lru` 退化成 `noeviction` —— **内存满了直接报错 `OOM command not allowed when used memory > 'maxmemory'`**。这是生产事故的常见原因（有人把 `allkeys-lru` 改成 `volatile-lru` 却没给 key 加 TTL）。

### 近似 LRU 的实现细节

Redis 不维护双向链表（那样每个对象的指针开销 + 每次访问都要移动链表，成本太高），而是：

1. 每个 `redisObject` 的 24 bit `lru` 字段存**最后一次访问的时间戳**（秒级精度，来自 `server.lruclock`）
2. 淘汰时**随机采样 `maxmemory-samples` 个 key**（默认 5）
3. 选其中最久未访问的删掉

3.0 引入了 **eviction pool**（淘汰池，默认 16 个）：采样到的 key 按空闲时间插入池中排序，命中时从池里挑最老的淘汰。这样即使单次采样不准，多次采样累积后也能逼近真实 LRU。

**`maxmemory-samples` 的效果**：5 时已「非常接近」精确 LRU（Redis 官方给的测试结论）；10 更接近，但 CPU 消耗增加；3 明显劣化。**默认 5 是性价比最优，一般不用改。**

### LFU 的实现细节（4.0+）

24 bit `lru` 字段被拆成两半：

```
┌──────────── 24 bit lru 字段（LFU 模式）────────────┐
│  16 bit ldt（last decrement time，分钟精度）        │
│   8 bit logc（对数计数器，0~255）                   │
└────────────────────────────────────────────────────┘
```

**计数增长（不是每访问 +1）**：
- `counter < 5`（`LFU_INIT_VAL`）→ 每访问都 +1
- `counter >= 5` → 概率 `1/(counter × lfu-log-factor + 1)` 才 +1。`lfu-log-factor` 默认 10 → counter=5 时概率 1/51，counter=10 时 1/101

**为什么要对数**：如果线性增长，一个被访问过 100 万次的历史热点永远无法被淘汰，新热点永远进不来。对数计数让计数增长越来越慢（counter 上限 255），**给新热点留出追赶的空间**。

**计数衰减**：`ldt` 记录上次衰减时间，超过 `lfu-decay-time`（默认 1 分钟）后按「过了几个分钟」把 counter 减去相应值。

```bash
redis-cli config set maxmemory-policy allkeys-lfu
redis-cli config set lfu-log-factor 10        # 默认 10，越大计数增长越慢
redis-cli config set lfu-decay-time 1         # 默认 1 分钟衰减一次
redis-cli object freq mykey                   # 查看当前 LFU 计数（需策略为 lfu）
redis-cli --hotkeys                           # 采样找出热点 key（需 lfu 策略）
```

### maxmemory 设多少

**原则：给「非数据内存」留出余量，而不是吃满物理内存。**

| 内存构成 | 说明 |
|---|---|
| 数据本身 | `used_memory` 的主要部分 |
| 复制缓冲区 | 主从复制期间暂存待发命令，`client-output-buffer-limit replica` |
| 客户端输出缓冲 | 慢客户端积压的回复，`client-output-buffer-limit normal` |
| AOF 缓冲区 | `AOF_FSYNC` 期间待写命令 |
| **fork 的 COW 开销** | BGSAVE / AOF 重写期间最坏可能翻倍 |

**经验值：`maxmemory` 设为可用内存的 60%~70%**，且**容器环境必须参考 limit 而不是宿主机内存**。

```bash
# 容器里（假设 limit 2Gi）
redis-cli config set maxmemory 1280mb        # 约 60%
redis-cli config set maxmemory-policy allkeys-lru
redis-cli config set maxmemory-samples 5
redis-cli config set lazyfree-lazy-eviction yes   # 淘汰时异步释放，避免阻塞
redis-cli config rewrite

redis-cli info memory | grep -E "used_memory_human|used_memory_rss_human|maxmemory_human|mem_fragmentation_ratio|evicted_keys"
```

**`mem_fragmentation_ratio` = `used_memory_rss` / `used_memory`**：1.0~1.5 正常；>1.5 碎片严重（可开 `activedefrag yes`）；**< 1 说明操作系统把 Redis 内存换到了 swap，性能已经崩了**（这是最危险的信号，比 OOM 更隐蔽）。
:::

:::拓展
**淘汰是「静默」发生的——没监控就会丢数据**

`INFO stats` 里的 `evicted_keys` 是**累计被淘汰的 key 数量**。如果它一直涨，说明缓存在持续被清，命中率下降、DB 压力上升，但**应用层完全无感**（表现为「缓存还是通的，只是经常 miss」）。

```bash
redis-cli info stats | grep -E "evicted_keys|expired_keys|keyspace_hits|keyspace_misses"
# 命中率 = keyspace_hits / (keyspace_hits + keyspace_misses)，低于 90% 要查原因
```

**这就是 `noeviction` 为什么危险也为什么安全**：它是默认值，好处是「绝不悄悄丢你的数据」（宁可报错），坏处是「缓存场景下会直接让业务写失败」。**纯缓存场景必须显式改成 `allkeys-lru`，别用默认值上线。**

**`lazyfree` 家族（4.0+）——决定「删除」是否阻塞主线程**

| 配置 | 默认 | 作用 |
|---|---|---|
| `lazyfree-lazy-eviction` | no | 内存淘汰时异步释放 |
| `lazyfree-lazy-expire` | no | 过期删除时异步释放（大 key 过期不阻塞） |
| `lazyfree-lazy-server-del` | no | `RENAME`/`MOVE` 等隐式删除时异步 |
| `lazyfree-lazy-user-del` | no | **设 yes 后 `DEL` 等效 `UNLINK`** |
| `lazyfree-lazy-user-flush` | no | `FLUSHALL`/`FLUSHDB` 默认异步（8.0 起为 yes） |

**把后四个都设成 `yes` 是高内存 Redis 的常规操作**——但 `lazyfree-lazy-user-del yes` 会改变 `DEL` 的语义（不再保证立即释放内存），需要有监控配合，否则「删了 key 内存没降」会引发误判。
:::

:::追问
**Q：一个 key 设了 1 小时过期，但一直没人访问，它什么时候被删？**
两种可能：① 定期删除的随机采样抽到了它（概率性，但 `activeExpireCycle` 在过期 key 占比高时会加速）；② 内存达到 `maxmemory` 触发淘汰（如果策略是 `volatile-*`）。**最坏情况是它一直占着内存直到被采样到**。如果业务依赖「过期就必然马上释放」，那是不成立的——**Redis 的过期是「最终删除」，不是「准点删除」**。要精确控制内存，用 `volatile-ttl` 策略或业务侧主动删。

**Q：`EXPIRE` 和 `EXPIREAT` / `PEXPIRE` 的区别？**
`EXPIRE key 60` 是相对秒；`PEXPIRE` 相对毫秒；`EXPIREAT key <unix秒>` 是绝对时间戳。**跨时区/跨机器场景用 `EXPIREAT` 更安全**。还有 `EXPIRE key 60 NX`（只在不带过期时设置，7.0+）、`XX`（只在已带过期时设置）、`GT`/`LT`（只在更大/更小时设置）——这几个选项在「不希望覆盖已有 TTL」时很有用。

**Q：主库删了 key，从库为什么还占着内存？**
因为从库只在收到主库的 `DEL` 后才删。主库通过惰性删除或定期删除发现过期时，会**显式向从库传播一条 `DEL`**（4.0 前是 `DEL`，之后一致）。如果从库曾经是从别的主库切过来的、或者复制的 backlog 有缺口，就可能残留。排查从库内存异常时，先对比 `dbsize` 和 `INFO replication` 的 offset 差。

**Q：`volatile-lru` 里「设了 TTL 的 key」被删光了会怎样？**
**退化成 `noeviction`，写入报错。** 这是 `volatile-*` 系列最容易被忽略的行为，也是面试很喜欢问的细节。所以「缓存 + 持久数据混存」这个看起来优雅的设计，实际运维成本很高——更好的做法是**缓存实例和数据实例物理隔离**（不同 DB 不够，要用不同实例）。
:::

:::锚点
你项目里 Redis 是**腾讯云 Redis（`10.11.2.65:6379`，现网 oasis.h3c.com）**——托管实例有两个和自建不同的点，面试时讲出来很加分：

① **`maxmemory` 由云厂商按规格设定，你大概率无权改 `maxmemory-policy`**。所以「内存不够」时的处置手段不是调淘汰策略，而是**控制 key 的数量和大小**（TTL 设计、避免大 key、拆分维度）——这才是你能实际动手的地方。面试可以这么讲：「云 Redis 的淘汰策略是固定的，所以我更关注写入侧的治理：每个缓存 key 必带 TTL，并且控制单个 key 的元素数量上限。」

② **`evicted_keys` 是云 Redis 必须盯的指标**。托管实例内存满了会静默淘汰，你在应用侧只能看到「缓存命中率下降」。排查路径是：`INFO stats` 的 `evicted_keys` 涨 → 反查是哪类 key 占内存大（`--bigkeys`）→ 加 TTL 或拆分。

**「key 数量本身就是成本」这条经验，在你的 RRM 场景里非常具体**：如果一个场所几千个 AP、每个 AP 一个独立的 key（如 `ap:{sn}:status`），那几万个场所就是几千万个 key——内存里光 dictEntry + redisObject + SDS 头就要几个 GB。**改成按场所聚合的 Hash（`apstatus:{siteId}` 里 field=AP 序列号）能把内存降一个数量级**，这就是第 2 题那个「Hash 存对象 vs 散 String」的内存账在真实业务上的落地。
:::

---
## 5. RDB 持久化（快照 + fork + COW）

:::概念
RDB = **某一时刻的全量二进制快照**。`BGSAVE` 会 **fork 一个子进程**去写文件，主进程继续服务；靠 **写时复制（COW）** 让子进程看到一份「冻结」的内存视图。
记忆钩子：**「RDB 是照片，快、小、恢复快，但两张照片之间的东西没了；fork 是拍照的代价，内存越大越贵。」**
:::

:::提问
- RDB 是怎么生成的？`SAVE` 和 `BGSAVE` 区别？
- fork 会阻塞主线程吗？阻塞多久？
- 什么是写时复制（COW）？内存会翻倍吗？
- RDB 相关配置有哪些？
:::

:::答案
### 默认配置与命令

```bash
redis-cli config get save
# save
# 3600 1 300 100 60 10000
#    ^^^^ ^  ^^^ ^^^ ^^ ^^^^^
#    3600秒内≥1次修改  300秒内≥10次修改  60秒内≥10000次修改 → 触发 BGSAVE

redis-cli config get dbfilename      # dump.rdb
redis-cli config get dir             # /var/lib/redis（快照实际落盘目录）
redis-cli config get rdbcompression  # yes，用 LZF 压缩字符串（CPU 换体积）
redis-cli config get rdbchecksum     # yes，CRC64 校验（改文件会启动失败）
redis-cli config get stop-writes-on-bgsave-error   # yes（重要，见下）
redis-cli config get rdb-del-sync-files             # no
```

```bash
# 手动触发
redis-cli SAVE        # 主线程同步执行，全库阻塞 —— 生产禁用
redis-cli BGSAVE      # fork 子进程异步执行 —— 正确姿势
redis-cli LASTSAVE    # 上次成功保存的 unix 时间戳

# 观察 fork 耗时（关键指标）
redis-cli INFO stats | grep latest_fork_usec
# latest_fork_usec:2451        ← 微秒，2451μs ≈ 2.4ms，健康

redis-cli INFO persistence
# rdb_changes_since_last_save:12
# rdb_bgsave_in_progress:0
# rdb_last_save_time:1758170000
# rdb_last_bgsave_status:ok
# rdb_last_cow_size:1638400    ← 上次 BGSAVE 期间 COW 额外占用的字节
```

### BGSAVE 全流程

```
主线程调用 BGSAVE
   │
   ├─ ① fork()：创建子进程，复制页表（这一步在主线程，阻塞来源）
   │
   ├─ ② 主线程立刻返回继续处理请求
   │     子进程遍历内存，把数据写成临时文件 temp-<pid>.rdb
   │
   ├─ ③ 期间主线程有写操作 → 触发 COW
   │     被写的页：内核复制一份给子进程用，主线程改自己那份
   │     → 子进程始终看到「fork 那一刻」的一致视图
   │
   └─ ④ 子进程写完后原子 rename 成 dump.rdb，用信号通知主线程
         主线程更新 dirty 计数器、记录 lastsave
```

### fork 到底阻塞多久

**`fork()` 本身不复制内存数据，只复制页表** —— 这是理解 COW 的关键。阻塞时长取决于：

| 影响因素 | 说明 |
|---|---|
| **页表大小** | 每 4KB 内存一个页表项，每项 8 字节（64 位）→ **1GB 内存约 2MB 页表** |
| 内存分配器 | jemalloc 的元数据越多，fork 越慢 |
| 是否开启 THP（透明大页） | **开启后页表项变少、fork 变快，但 COW 时一复制就是一整页 2MB** → 反而更慢，Redis 官方建议关掉 |
| 虚拟内存 overcommit | `vm.overcommit_memory=1` 必须设，否则 fork 可能直接失败 |

**经验值**：1GB 内存的 fork 约 1~3ms；10GB 约 20~50ms；**50GB 可能到几百毫秒**。用 `INFO stats` 的 `latest_fork_usec` 实测，别猜。

### COW 会让内存「翻倍」吗

**不会翻倍，但要留余量。** 理论最坏情况是「fork 后所有页都被写过」→ 内存翻倍；实际情况取决于**写入量和写入分布**：

- 只写少数 key → 只复制少数页 → 增量很小
- 全库大量写入（如大批量导入、`FLUSHALL` 后重建）→ COW 页多 → 内存涨得快

**这就是 `maxmemory` 只设 60%~70% 的原因之一** —— 剩下 30% 就是给 COW、复制缓冲、客户端缓冲的预算。

```bash
redis-cli INFO persistence | grep rdb_last_cow_size
# 实时观察当前 COW 占用（BGSAVE 进行中才有意义）
redis-cli INFO memory | grep -E "used_memory_human|used_memory_peak_human|mem_fragmentation_ratio"
```

### `stop-writes-on-bgsave-error`：一个真实的生产陷阱

默认 `yes`。含义是：**如果最近一次后台保存失败（比如磁盘满、目录无写权限、fork 失败），Redis 会拒绝所有写命令**，返回 `MISCONF Errors writing to the RDB file`。

好处：防止你毫不知情地跑在一个「持久化已经坏掉」的实例上。
坏处：**磁盘一满，整个写链路挂了，比丢快照更严重**。

线上处置：
```bash
redis-cli INFO persistence | grep rdb_last_bgsave_status   # 看是不是 err
redis-cli INFO persistence | grep rdb_last_bgsave_status   # 排查磁盘
df -h
# 短期恢复（确认不依赖 RDB 时可接受）
redis-cli CONFIG SET stop-writes-on-bgsave-error no
# 长期：清理磁盘 / 挂更大盘 / 关掉不必要的 save 规则
```

### 一个 RDB 文件的内部结构

```
REDIS0011           ← 魔数 "REDIS" + 版本号
FA <40字节>          ← 辅助字段：redis-ver / redis-bits / ctime / used-mem / repl-id
FE 00               ← SELECTDB 0（切换到 db0）
FB <size> <expire>  ← 键类型 + 过期时间 + 长度编码 + key + value ...
FE 01               ← SELECTDB 1
...
FF                  ← EOF 结束标记
<8字节 CRC64>        ← 校验和（rdbchecksum yes 时）
```

**为什么写临时的 `temp-<pid>.rdb` 再 rename**：`rename()` 在同一个文件系统上是原子操作——**要么是旧快照、要么是新快照，不会出现「写了一半」的破损 RDB**。这是持久化文件更新的通用套路，跟 AOF 重写换文件是同一个思路。
:::

:::拓展
**RDB 的优缺点（对比表）**

| | RDB | 说明 |
|---|---|---|
| 文件体积 | **小**（二进制 + LZF 压缩） | 同样的数据，AOF 可能大 3~10 倍 |
| 恢复速度 | **快**（直接读入内存，不用重放命令） | 对比 AOF 要逐条执行命令 |
| 数据丢失 | **多**（两次快照之间的写全丢） | 最坏丢 `save` 间隔内的全部数据 |
| fork 开销 | 有，且与内存大小正相关 | 大内存实例必须监控 `latest_fork_usec` |
| 实时性 | 差 | 不适合当唯一持久化手段 |
| 适用 | **备份/灾备、主从全量同步** | `BGSAVE` 出的 RDB 直接发给从节点 |

**RDB 是主从全量同步的载体**：从节点第一次连上去，主节点就是 `BGSAVE` 出一个 RDB 发过去（6.0 + `repl-diskless-sync yes` 时可以不落盘，直接走 socket）。所以 RDB 的 fork 开销在主从场景下更常见。

**`vm.overcommit_memory=1` 为什么必须设**：Linux 默认 `overcommit_memory=0`（启发式判断），fork 一个「虚拟内存等于总内存」的进程可能被拒 → `BGSAVE` 直接失败 → 触发 `stop-writes-on-bgsave-error` 拒写。Redis 启动日志会明确警告：

```
WARNING overcommit_memory is set to 0! Background save may fail under low memory condition.
```

```bash
# 临时
sysctl vm.overcommit_memory=1
# 永久
echo "vm.overcommit_memory = 1" >> /etc/sysctl.conf

# 同时建议关掉透明大页
echo never > /sys/kernel/mm/transparent_hugepage/enabled
```
:::

:::追问
**Q：`SAVE` 和 `BGSAVE` 能同时存在吗？**
不能。如果已经有子进程在 `BGSAVE`/`BGREWRITEAOF`，新的 `BGSAVE` 直接被拒绝（返回 `Background save already in progress`）。AOF 重写和 RDB 保存也不能同时进行——Redis 会让 AOF 重写排队等 BGSAVE 结束。**所以「save 规则 + AOF 重写」同时触发时，实际是串行做的。**

**Q：fork 失败会怎样？**
`fork` 返回错误（通常是内存不足或 overcommit 限制）→ `BGSAVE` 失败 → `rdb_last_bgsave_status:err` → 因为 `stop-writes-on-bgsave-error yes`，**所有写命令被拒**。日志里是 `Can't save in background: fork: Cannot allocate memory`。排查方向：① 设 `vm.overcommit_memory=1`；② 内存是否已经接近物理上限；③ 是不是有别的进程在抢内存。

**Q：RDB 文件能直接看内容吗？**
不能直接看，但可以离线分析。工具：`redis-rdb-tools`（Python）、**`rdb-cli` / `rdr`（Go，更快，支持 `rdr show -k <key>` 和 `rdr keys`）**。**离线分析 RDB 是发现大 key 最安全的方式**（不占用线上资源，见第 14 题）：

```bash
# 用 Go 版 rdb-cli：统计各类型 key 数量、内存占用 Top N、找出大 key
rdr keys dump.rdb --memory > keys.csv
rdr show dump.rdb -k user:1001
rdr json dump.rdb > all.json
```

**Q：`save ""` 是什么？**
关闭自动 RDB 保存（只在显式 `BGSAVE` 或主从同步时才生成）。**纯缓存实例的常见配置** —— 既然数据可以重建，就不需要定时快照的 fork 开销。反过来，**如果这台实例会当主节点供从节点同步，完全关掉 RDB 会让人有点心虚**：虽然全量同步时主节点会主动 `BGSAVE`，但日常没有备份。折中是留一条低频规则，比如 `save 3600 1`。
:::

:::锚点
你们现网 Redis 是**腾讯云托管实例**——`SAVE`/`BGSAVE`/`CONFIG SET save` 这些命令在托管实例上**通常被禁用或改由控制台配置**。这反而是个可以展示理解深度的点：

面试话术：「我们用的是云 Redis，持久化策略由控制台配，我不能直接跑 `BGSAVE`。但我很关注两个间接指标：`rdb_last_bgsave_status`（确认快照没失败）和 `latest_fork_usec`（确认 fork 没成为卡顿源）。**这个判读习惯是从 rrmcompute 的 OOM 排查里带出来的——那次的教训是『资源类问题必须看数字，不能靠猜』。**」

**另外一个可以主动提的对比**：你们 RRM 的数据主存是 MongoDB（`10.11.2.140:27017`），Redis 只是缓存层。所以 Redis 上「丢了能不能重建」的答案是**能**——MongoDB 是事实来源，Redis 是可重建的加速层。**这个定位决定了 Redis 上不需要 AOF `always` 这种重持久化配置**，这也是第 7 题「按数据重要性分级选型」的直接依据。面试官问「你们 Redis 丢数据了怎么办」，这个答案比任何配置参数都更有说服力。
:::

---

## 6. AOF 持久化与重写（含混合持久化）

:::概念
AOF = **把每条写命令按顺序追加到文件**，恢复时**重放**这些命令。三种刷盘策略 `always / everysec / no` 决定丢数据的窗口。
记忆钩子：**「RDB 存结果，AOF 存过程；存过程更安全但更慢更胖，所以需要『重写』来减肥。」**
:::

:::提问
- AOF 是什么？和 RDB 比有什么优劣？
- `appendfsync` 三种策略怎么选？为什么会丢 1 秒数据？
- AOF 重写是怎么做的？fork 期间的新命令怎么办？
- 什么是混合持久化？为什么恢复更快？
- AOF 文件损坏了怎么修？
:::

:::答案
### 配置与命令

```bash
redis-cli config get appendonly           # no（默认！要手动开）
redis-cli config get appendfilename       # appendonly.aof（7.0+ 变成多文件）
redis-cli config get appendfsync          # everysec
redis-cli config get no-appendfsync-on-rewrite   # no
redis-cli config get auto-aof-rewrite-percentage # 100
redis-cli config get auto-aof-rewrite-min-size   # 67108864（64mb）
redis-cli config get aof-use-rdb-preamble        # yes（4.0+，混合持久化）
redis-cli config get aof-timestamp-enabled       # no（7.0+，AOF 里插时间注释）

redis-cli BGREWRITEAOF                    # 手动触发重写
redis-cli INFO persistence
# aof_enabled:1
# aof_rewrite_in_progress:0
# aof_last_bgrewrite_status:ok
# aof_last_write_status:ok
# aof_current_size:1048576
# aof_base_size:1048576
# aof_pending_rewrite:0
# aof_buffer_length:0
# aof_delayed_fsync:0          ← >0 说明主线程被 fsync 阻塞过，危险信号
```

### 三种刷盘策略的真实语义

| 策略 | 行为 | 最多丢多少 | QPS 影响 |
|---|---|---|---|
| `always` | **每条写命令**都调 `fsync()` 等落盘后才回复客户端 | 0（单机不丢） | 降到几百~几千，受磁盘 IOPS 限制 |
| `everysec` | 主线程只 `write()` 到缓冲区，**后台 bio 线程每秒 `fsync` 一次** | **1 秒** | 几乎无影响（推荐默认） |
| `no` | 只 `write()`，什么时候 `fsync` 交给操作系统 | 最多 30 秒（Linux 脏页回写默认） | 最快，但不可控 |

**`everysec` 的一个隐藏问题**：如果上一次 `fsync` 还没完成（磁盘慢/卡住），主线程会**阻塞等待**（最多 2 秒，`aof_delayed_fsync` 计数 +1），然后继续。所以 `aof_delayed_fsync > 0` 是「磁盘拖慢了 Redis」的实证。

```bash
redis-cli INFO persistence | grep aof_delayed_fsync
# aof_delayed_fsync:3     ← 出现过 3 次 fsync 阻塞，要查磁盘 IO
```

### AOF 的写入流程

```
客户端发来 SET k v
   │
   ├─ ① 主线程执行命令，修改内存
   ├─ ② 把命令按 RESP 协议追加到 aof_buf 缓冲区（内存）
   ├─ ③ 事件循环每轮结束前（beforeSleep）：
   │     write() 把 aof_buf 写进内核页缓存
   │     ├─ always   → 立刻 fsync() 等落盘
   │     ├─ everysec → 交给 bio_aof_fsync 后台线程每秒做一次
   │     └─ no       → 不管，交给 OS
   └─ ④ 回复客户端
```

**关键点：命令「先执行、后写 AOF」** —— 所以 AOF 里记录的是**实际生效的命令**（不是客户端原始命令）。比如 `SETEX k 100 v` 在 AOF 里可能变成 `SET k v` + `PEXPIREAT k <时间戳>`；`INCR` 在 AOF 里就是 `INCR`（不是 `SET k 42`）。**这也是 5.0 之后「效果复制」的思路**（见第 17 题 Lua 部分）。

### AOF 重写：怎么给文件「减肥」

**核心思想：不读旧 AOF，而是直接看当前内存状态，生成一份「能重建这份数据的最短命令序列」。**

```
例：对同一个 key 执行了 100 次 INCR counter
   旧 AOF：100 条 INCR
   重写后：1 条 SET counter 100

例：对同一个 list 执行了 10000 次 RPUSH
   旧 AOF：10000 条命令
   重写后：1 条 RPUSH list v1 v2 ... v10000（或按 64 个元素一批拆成多条）
```

**重写期间的新命令怎么办（高频追问）**：

```
① 主进程 fork 出子进程
② 子进程根据内存快照写新的 AOF 到临时文件
③ 同时，主进程把新来的写命令同时写入两个地方：
      - 旧的 aof_buf（保证旧 AOF 仍然完整，万一重写失败可回退）
      - aof_rewrite_buf（专门攒给新 AOF 用）
④ 子进程写完，通知主进程
⑤ 主进程把 aof_rewrite_buf 的内容追加到新 AOF 文件末尾
⑥ rename() 原子替换旧 AOF，新 AOF 生效
```

**第 ⑤ 步是关键**：把「子进程写快照期间产生的新命令」补到新 AOF 尾部，保证不丢——这跟 RDB 主从全量同步时「复制缓冲区补发期间的命令」是同一个套路。

**自动触发条件（两个必须同时满足）**：
```
① 当前 AOF 大小 / 上次重写后的大小 > auto-aof-rewrite-percentage (100%)
② 当前 AOF 大小 > auto-aof-rewrite-min-size (64mb)
```
所以 AOF 从 1MB 涨到 2MB 不会触发（不满足 ②），从 64MB 涨到 128MB 才会。

### 混合持久化（4.0+，强烈推荐）

```bash
redis-cli config get aof-use-rdb-preamble
# aof-use-rdb-preamble
# yes                          ← 4.0+ 默认开
```

开启后，**AOF 重写生成的新 AOF 文件前半部分是 RDB 格式的内容，后半部分是增量命令**：

```
┌─────────────── appendonly.aof ───────────────┐
│  前半部分：RDB 格式的二进制快照（当前内存状态）│
│  ~~~~~~~~ RDB 格式 ~~~~~~~~                    │
├───────────────────────────────────────────────┤
│  后半部分：重写期间及之后的增量命令（RESP 文本）│
│  INCR counter                                  │
│  HSET user:1 name alice                        │
└───────────────────────────────────────────────┘
```

**收益**：恢复时先加载 RDB 部分（**极快，不用重放几百万条命令**），再重放尾部少量增量。**既有 RDB 的恢复速度，又有 AOF 的数据安全性** —— 这是「既要又要」的正确答案。

**Redis 7.0 的 multi-part AOF**：AOF 从「单文件」改成「一个 base 文件 + 多个 incr 文件 + 一个 manifest 清单」：

```
appendonlydir/
├── appendonly.aof.1.base.rdb      ← 基准（RDB 格式，混合持久化）
├── appendonly.aof.1.incr.aof      ← 增量命令
├── appendonly.aof.2.incr.aof
└── appendonly.aof.manifest        ← 清单，记录哪些文件组成当前 AOF
```

**为什么改**：旧单文件方案在重写切换的瞬间要处理「文件句柄切换 + 缓冲区补齐」的原子性问题，实现复杂且容易出错（历史上出过 AOF 切换丢失数据的 bug）。multi-part 用 manifest 文件做原子切换，`rename` 的粒度更小更安全，同时也**支持「重写期间不阻塞、增量文件滚动」**。

### AOF 损坏修复

```bash
# 检查 AOF 文件
redis-check-aof appendonly.aof
# AOF analyzed: size=1234, ok_up_to=1234, diff=0
# AOF is valid

# 截断到最后一条完整命令（会丢掉损坏点之后的数据）
redis-check-aof --fix appendonly.aof
# 交互确认后：会把文件截断到最后一个完整命令处
```

**注意**：`--fix` 是**有损修复**，会丢掉损坏点之后的所有命令。生产上要先备份原文件（`cp appendonly.aof appendonly.aof.bak`）再修。文件损坏的常见原因：磁盘满导致 `write` 只写了一半、机器断电、`fsync` 期间宕机。
:::

:::拓展
**RDB vs AOF 全维度对比（背这张表）**

| 维度 | RDB | AOF | 混合持久化（4.0+） |
|---|---|---|---|
| 存什么 | 全量数据快照 | 写命令序列 | RDB 头 + 增量命令 |
| 文件体积 | **小** | 大（3~10 倍） | 中（接近 RDB） |
| 恢复速度 | **快** | 慢（要逐条重放） | **快**（加载 RDB 部分） |
| 数据丢失 | 多（丢一个 save 周期） | **少**（everysec 丢 1 秒） | 少（≈everysec） |
| 写性能影响 | 周期性 fork 抖动 | `everysec` 几乎无影响 | 同 AOF |
| 磁盘 IO 习惯 | 突发大量写 | 持续少量写 | 持续写 + 周期大块 |
| 可读性 | 二进制不可读 | **文本，可读可改** | 前段不可读 |
| 适用 | 备份、灾备、主从全量 | 数据安全优先 | **生产默认推荐** |

**AOF 文件能手动改吗**：能，因为它是 RESP 文本协议。比如误执行了 `FLUSHALL` 且还没重写，可以停掉 Redis、编辑 AOF 删掉那条 `FLUSHALL`、重启恢复。**这是 AOF 相比 RDB 的唯一「可手术」优势**——但操作前必须备份，且 Redis 7.0 的多文件 AOF 里要改的是 `.incr.aof` 文件。

**`no-appendfsync-on-rewrite`**：默认 `no`，即「AOF 重写期间仍然每秒 fsync」。设成 `yes` 表示重写期间不 fsync（**因为子进程在大量写磁盘，fsync 会互相争抢导致阻塞**），代价是重写期间如果宕机可能丢最多 30 秒数据。**这是「性能 vs 安全」的一个明确取舍点**，高写入量 + 磁盘慢的实例可以考虑设 `yes`。
:::

:::追问
**Q：既然开了 AOF，RDB 还需要吗？**
需要，但目的变了：**RDB 不再承担「防止丢数据」的职责（AOF 干这个），而是承担「快速灾难恢复」的职责**。两个典型用途：① 出故障时用最近一次的 RDB 快速拉起一个实例；② 主从全量同步时主节点 `BGSAVE` 出来的 RDB 直接发给从节点。**很多生产实例的配置是：`appendonly yes` + `aof-use-rdb-preamble yes` + 保留低频 RDB（如 `save 3600 1`）。**

**Q：AOF 重写期间，主进程内存会涨吗？**
会，两个来源：① `aof_rewrite_buf`（重写期间积压的新命令，重写越久积压越多）；② fork 的 COW 页。所以 **「AOF 重写耗时 × 写入速率」就是缓冲区大小的上界**。如果 AOF 重写很慢（大内存 + 慢磁盘）同时写入量很大，缓冲区可能到几百 MB，这也要算进 `maxmemory` 的余量里。

**Q：AOF 重写会不会阻塞主线程？**
**fork 那一瞬间阻塞**（同 RDB），重写本身不阻塞。但有一个例外：**第 ⑤ 步「把 aof_rewrite_buf 追加到新 AOF」是主线程做的** —— 如果积压了几百 MB，这一步会有明显停顿（这也是 Redis 7.0 改 multi-part AOF 的动机之一）。排查方式是看 `INFO persistence` 里的 `aof_rewrite_in_progress` 和 `aof_pending_rewrite`。

**Q：`appendfsync always` 真的不丢数据吗？**
单机不丢（数据已经 fsync 到磁盘），但有两个前提：① `fsync` 返回成功；② **磁盘缓存是 write-through 的**。有些云盘/RAID 卡带电池缓存，`fsync` 返回后数据其实还在缓存里，断电仍可能丢。**要做到真正不丢，需要 `fsync` + 存储层 `O_DIRECT`/关闭写缓存 + 副本**。所以「金融级不丢数据」不会只靠 Redis 的 `always`，而是靠多副本 + 上层补偿。**面试能主动说出这一点，是明显的深度加分。**
:::

:::锚点
你项目里 Redis 是缓存层（真实数据在 MongoDB `10.11.2.140:27017`），所以持久化配置的正确结论是：

**「缓存型实例不需要 AOF `always`。我们的定位是 Redis 挂了可以从 MongoDB 重建，所以持久化的价值主要是『减少冷启动时的缓存击穿』——真正的风险不是丢缓存，而是 Redis 重启瞬间的缓存全空导致 DB 被打爆。」**

这个视角的转换很关键：**从「怎么不丢数据」转到「重启后怎么不把 DB 打穿」**。对应的措施是：
1. 如果开了持久化（RDB/AOF），重启后缓存能快速预热；
2. 但**更可靠的是启动时的「限流预热」** —— 别让重启后的第一波流量直接全部穿透到 MongoDB；
3. 生产上给热点 key 加随机 TTL（第 10 题），避免「重启后所有 key 同时失效」。

**面试话术**：「我做过的最接近持久化的排查是 rrmcompute 的 OOM——那次学到的是『内存类问题必须看实时指标而不是看配置』。同样地，看 Redis 持久化我不会只看配置，会看 `rdb_last_bgsave_status`、`aof_last_write_status`、`aof_delayed_fsync` 这三个状态位，因为它们直接反映『持久化到底有没有在正常工作』。」——**诚实、具体、有方法论**，比背一堆参数强。
:::

---

## 7. 持久化选型与 fork 阻塞治理

:::概念
选型只问一个问题：**「这份数据丢了，能不能重建？」**
能重建（纯缓存）→ 可以不持久化；不能重建但能容忍 1 秒 → `AOF everysec` + 混合持久化；一秒都不能丢 → `AOF always` + 多副本 + 上层补偿。
记忆钩子：**「先给数据定级，再选持久化；fork 是绕不开的成本，只能管理不能消除。」**
:::

:::提问
- 你们线上 Redis 用什么持久化策略？为什么？
- 什么时候开 AOF，什么时候不开？
- fork 阻塞怎么排查和治理？
- 大内存实例的持久化有什么坑？
:::

:::答案
### 分级选型表

| 数据等级 | 典型场景 | 配置 | 能丢多少 |
|---|---|---|---|
| **纯缓存** | 页面缓存、热点数据、DB 前置缓存 | `appendonly no` + `save ""` | 全丢也能重建 |
| **缓存 + 轻状态** | 分布式锁、限流计数、去重标记 | `appendonly no` 或 `everysec` | 锁丢失可接受（会重试） |
| **业务数据** | 会话、购物车、任务队列 | `appendonly yes` + `everysec` + `aof-use-rdb-preamble yes` | ≤1 秒 |
| **关键数据** | 订单、账务、库存扣减 | **不应该只放 Redis** —— 用 DB 做事实来源 | — |

**最重要的一条**：**不要把 Redis 当唯一数据源**。Redis 的持久化再强也是单机 + 异步复制，**主从切换会丢数据**（见第 15 题）。真正需要强一致的场景，DB 是事实来源，Redis 只是加速层。

### 生产配置模板

```bash
# 场景 A：纯缓存实例（推荐给 RRM 这类「MongoDB 是事实来源」的场景）
appendonly no
save ""                     # 关掉自动 RDB，省掉 fork 开销
maxmemory 1280mb
maxmemory-policy allkeys-lru

# 场景 B：需要快速恢复的缓存实例
appendonly yes
appendfsync everysec
aof-use-rdb-preamble yes
auto-aof-rewrite-percentage 100
auto-aof-rewrite-min-size 64mb
no-appendfsync-on-rewrite no
save 3600 1                 # 低频 RDB 做灾备

# 场景 C：数据安全优先
appendonly yes
appendfsync always          # 或 everysec + 上层补偿
aof-use-rdb-preamble yes
stop-writes-on-bgsave-error yes
```

### fork 阻塞的完整治理清单

**① 先测出真实数字**

```bash
redis-cli INFO stats | grep latest_fork_usec
# latest_fork_usec:8302         ← 8.3ms，可接受
# latest_fork_usec:186000       ← 186ms，需要治理

redis-cli INFO persistence | grep rdb_last_cow_size
redis-cli --latency-history          # 看是否有周期性尖刺（周期 = save 间隔或 AOF 重写）
redis-cli --intrinsic-latency 100    # 排除机器本身的干扰
```

**② 七个治理手段**

| 手段 | 具体做法 | 效果 |
|---|---|---|
| 控制单实例内存 | 大内存拆成多个实例（如 32GB → 4×8GB） | **最有效**，fork 时间与页表大小成正比 |
| 关闭 THP | `echo never > /sys/kernel/mm/transparent_hugepage/enabled` | 避免 COW 复制 2MB 大页 |
| 设 overcommit | `vm.overcommit_memory=1` | 防止 fork 直接失败 |
| 减少 fork 频率 | 关掉不必要的 `save` 规则；`aof-rewrite` 阈值调大 | 减少周期性抖动 |
| 错峰执行 | **在低峰期手动 `BGREWRITEAOF`**，避开 `save` 规则的触发点 | 把抖动挪到影响小的时间窗 |
| 用从节点做持久化 | 主节点关 RDB，从节点开 `save` | 主节点不受 fork 影响 |
| 换用无盘同步 | `repl-diskless-sync yes` | 主从全量同步不走磁盘，减少 IO 争抢 |

**③ 从节点做持久化（生产常用架构）**

```
主节点：appendonly no, save ""    ← 只服务读，不受 fork 影响
从节点：appendonly yes, save 900 1 ← 承担持久化职责
```
**代价**：主节点没有本地快照，故障时只能靠从节点数据重建。要配合「从节点必须实时跟上」的监控（`master_link_status:up`、offset 差 < 阈值）。

### 内存与持久化的容量规划

```bash
# 观察这三个数（不只是 used_memory）
redis-cli INFO memory | grep -E "used_memory_human|used_memory_rss_human|used_memory_peak_human"
# used_memory_human:1.85G           Redis 认为自己用了多少
# used_memory_rss_human:2.41G       操作系统看到的物理内存（含碎片、COW）
# used_memory_peak_human:3.02G      **历史峰值**——这是规划容量的关键数字
```

**容量公式（经验值）**：
```
需要的内存 ≈ maxmemory / 0.7    （给 fork COW + 复制缓冲 + 客户端缓冲留 30%）
且 maxmemory ≤ 物理内存 × 0.7
```

**如果 `used_memory_peak` 已经接近物理内存上限**，那不在持久化上做治理，先得治理**内存本身**（大 key、key 数量、TTL 设计）。这是第 14 题的内容。
:::

:::拓展
**无盘复制（diskless replication）**

```bash
redis-cli config get repl-diskless-sync        # 6.0 起默认 yes
redis-cli config get repl-diskless-sync-delay  # 默认 5（秒）
redis-cli config get repl-diskless-load        # disabled / on-empty-db / swapdb
```

`repl-diskless-sync yes` 时，主节点 **fork 子进程后直接把 RDB 数据写进从节点的 socket**，不落磁盘。好处：省掉一次磁盘写 + 一次磁盘读（大内存实例上这个开销很大）。`repl-diskless-sync-delay 5` 是「等 5 秒看看还有没有别的从节点要同步，一起发」，避免每个从节点都 fork 一次。

`repl-diskless-load` 控制从节点收到无盘 RDB 后怎么处理：`disabled`（先落盘再加载，安全但慢）、`on-empty-db`（直接往空库加载，省一次落盘）、`swapdb`（先加载到新 db 再原子切换）。

**`aof-timestamp-enabled`（7.0+）**

```bash
redis-cli config set aof-timestamp-enabled yes
# 会在 AOF 里插入 `#TS:1758170000` 这样的注释行，记录命令的时间点
```
好处：**AOF 从「一条命令流」变成「带时间线的事件流」**，可以用 `redis-check-aof` 看出某段时间写了什么，也方便做「恢复到某个时间点」的定制工具。代价是文件略大、旧版 Redis 不认这些注释（加载时会跳过 `#` 开头的行）。

**一个真实事故模式**：`stop-writes-on-bgsave-error yes` + 磁盘满 = **写全挂**。这个组合在容器环境特别容易踩——Pod 挂的 PV 很小（比如 1Gi），RDB 文件涨到 900MB 加上 AOF 就满了。**面试里讲「我排查过 Redis 写失败吗」，如果你没有真实案例，就说「我了解这个配置的副作用，所以会同时监控磁盘水位」**，别编。
:::

:::追问
**Q：Redis 重启后恢复是怎么走的？**
按顺序：① 如果 `appendonly yes` → **优先加载 AOF**（因为 AOF 通常更完整）；② 否则加载 RDB。**注意：AOF 开启时 RDB 文件会被忽略**（除非 AOF 不存在）。加载过程中 Redis **不会响应任何请求**（此时状态是 `loading`，`INFO` 里能看到 `loading:1`），所以恢复时间直接影响可用性。大实例的恢复优化手段：用混合持久化（AOF 前段是 RDB，加载快）、或者直接上从节点做故障转移。

**Q：怎么判断 AOF 重写是不是拖慢了主线程？**
三个信号：① `INFO persistence` 的 `aof_delayed_fsync > 0`（fsync 阻塞过）；② `aof_rewrite_in_progress:1` 持续很久（说明子进程写得慢，磁盘不行）；③ `rdb_last_cow_size` 异常大（说明重写期间写入量大，COW 开销高）。**三者同时出现，基本可以断定「磁盘是瓶颈」**，处置就是换更快盘、降写入量、或者从节点承担持久化。

**Q：为什么大内存实例要拆成多个？**
因为 fork 的开销（页表大小）、RDB 的生成时间、恢复时间、AOF 重写时间**全部与内存大小正相关**，而且是**单实例串行**的。32GB 拆成 4×8GB 后：fork 时间近似变成 1/4、恢复时间 1/4、而且**故障影响面变成 1/4**（挂一个只丢 1/4 的缓存）。代价是要管理 4 个实例、客户端要分片。**这也是 Redis Cluster 存在的理由之一**（见第 16 题）。

**Q：`BGSAVE` 期间如果这条命令来了怎么办？**
正常执行。**主线程在 fork 之后一直是自由的**，所有读写照常处理，只是写操作会触发 COW。这也是为什么「fork 之后主线程卡住」这个说法是错的——**卡住的是 fork() 那一瞬间**，之后主线程完全正常，代价是 COW 的内存增长。
:::

:::锚点
**这是一个可以直接拿来做项目叙事的点。**你所在的环境是 K8s + 腾讯云 Redis：

**① 你们不需要在 Redis 上做「数据不丢」的设计 —— 因为 MongoDB 是事实来源。**这句话本身就是最好的工程判断展示。面试官问「你们 Redis 怎么保证数据不丢」，正确答法是：「我们不追求，因为 Redis 在我们架构里是可重建的加速层，事实来源是 MongoDB。**真正的风险是 Redis 整体不可用时，MongoDB 扛不住穿透流量**，所以我们的重点在缓存降级和限流，不在持久化。」

**② fork 阻塞这个点，你有更贴近的类比：rrmcompute 的 OOM。**那次故障的本质是「进程的资源占用超出了容器预算」——fork COW 也是同一类问题：**fork 时不额外占内存，但 fork 之后的写入会持续吃 COW 内存，最后可能超过预算**。所以处置思路完全一致：**给峰值留余量**（内存 5Gi → 5.5GiB 是同一个动作）。

面试话术：「我理解 fork 的成本不是『fork 那一刻』，而是『fork 之后 COW 带来的持续内存增长』。这跟我们排查 rrmcompute OOM 时得出的结论一样——**容器里的内存是一个总和预算，任何只算一部分的做法都会翻车**。所以规划 Redis 时我会看 `used_memory_peak` 而不是 `used_memory`。」

**③ `write after end` 那个故障也有相关性。**rrmcontrol 在国际环境反复重启、报 `write after end`，根因是 Node.js 的连接生命周期管理缺陷（连接已关闭还在写）。**Redis 客户端也有同款坑**：Node.js 的 `ioredis` 连接被服务端 `timeout` 断掉后，如果客户端没处理 `error`/`reconnect` 事件，后续命令全部报 `write after end` 类的错误。**面试时如果聊到「你排过最难的问题」，这两个可以串成一个叙事：连接生命周期 + 多 pod + 中间件超时，是我们这套架构里反复出现的故障模式。**
:::

---

## 8. 缓存穿透（查询不存在的数据）

:::概念
穿透 = **请求查的数据在缓存和 DB 里都不存在**，每次都要打到 DB。缓存不但没挡住，还多绕了一层。
记忆钩子：**「穿透打的是『不存在的 key』——缓存里没有，DB 里也没有，所以永远 miss。」**
:::

:::提问
- 什么是缓存穿透？和击穿什么区别？
- 布隆过滤器原理是什么？为什么说「一定不在」是准的？
- 空值缓存有什么坑？
- 线上遇到恶意刷不存在的 ID 怎么处理？
:::

:::答案
### 与击穿、雪崩的区别（先定位）

| | 穿透 | 击穿 | 雪崩 |
|---|---|---|---|
| 打的是什么 | **不存在的 key** | **刚过期的热点 key** | **大量 key 同时失效 / Redis 挂了** |
| 缓存有没有 | 从来没有 | 有过，刚过期 | 有，但集体没了 |
| DB 里有吗 | **没有** | 有 | 有 |
| 单次影响 | 每个请求都打 DB | 瞬间并发打 DB | DB 直接被压垮 |
| 核心方案 | 布隆过滤器 + 空值缓存 | 互斥锁重建 + 逻辑过期 | 随机 TTL + 多级缓存 + 熔断 |

**一句话区分**：「穿透是**数据本身不存在**，击穿是**数据存在但缓存刚没**，雪崩是**缓存大面积同时失效**。」

### 防护一：参数校验（最便宜，先做）

```java
public UserDTO getUser(Long userId) {
    if (userId == null || userId <= 0) {
        return null;              // 直接拒绝，不查缓存也不查 DB
    }
    if (String.valueOf(userId).length() > 19) {
        return null;              // 防超长 ID 攻击
    }
    // ... 走缓存
}
```

**覆盖面**：能挡掉「`id=-1`、`id=999999999999999`」这类明显的爬虫/扫描流量。**成本几乎为零，必须做，但它挡不住「合法格式但不存在」的 ID（如 `id=12345678`）。**

### 防护二：布隆过滤器

**原理**：用一个 m bit 的位数组 + k 个独立哈希函数。

```
写入元素 x：
  h1(x)%m → 位置 3      置 1
  h2(x)%m → 位置 17     置 1
  h3(x)%m → 位置 10086  置 1

判断元素 y：
  三个位置**全为 1** → 「可能存在」（有误判）
  任意一位为 0     → 「**一定不存在**」（100% 准确）
```

**为什么「一定不存在」是准的**：只要有一个位置是 0，说明没有任何元素把这个位置置 1，那 y 必然没被写入过。反过来，三个位置都被别的元素置成了 1，就会误判为「可能存在」——这叫**假阳性**，布隆过滤器**不会假阴性**。

```bash
# 使用 RedisBloom 模块（云 Redis 需要开通/加载该模块）
redis-cli BF.RESERVE user:bloom 0.01 1000000
#  参数：误判率 0.01（1%）、预期元素数 1000000
#  返回 OK（Redis 会自动算需要多少 bit 和几个哈希函数）

redis-cli BF.ADD user:bloom 1001
redis-cli BF.EXISTS user:bloom 1001     # 1（可能存在）
redis-cli BF.EXISTS user:bloom 9999     # 0（一定不存在）

redis-cli BF.MADD user:bloom 1002 1003 1004
redis-cli BF.MEXISTS user:bloom 1002 1005   # 1 0

redis-cli BF.INFO user:bloom
# Capacity / Size / Number of filters / Number of items inserted / Expansion rate
```

**位数组大小的估算公式**（面试能说出这个公式就是加分）：
```
m = -n·ln(p) / (ln2)²        n=预期元素数，p=误判率
k = (m/n)·ln2                最优哈希函数个数

例：n=100 万，p=0.01
   m ≈ 9.6M bit ≈ 1.2MB
   k ≈ 7
```
**注意：100 万元素、1% 误判率，只要 1.2MB。**这是布隆过滤器最惊人的性价比（对比 Set 存 100 万个 ID 要几十 MB）。

**布隆过滤器的四个坑**：

| 坑 | 说明 | 对策 |
|---|---|---|
| **不能删除元素** | 把位翻回 0 会影响其他元素的判断 | 用 **Counting Bloom Filter**（每位计数，RedisBloom 的 `BF.INSERT` 不支持，需要 `CMS`/`TopK` 或自实现）；或者**定期重建** |
| **误判率随插入量上升** | 超过 `capacity` 后误判率飙升 | 估算容量时留 2~3 倍余量；`BF.INFO` 看 `Number of items inserted` |
| **需要预热** | 布隆过滤器必须预先装入所有合法 ID | 启动/定时任务从 DB 全量加载（增量用 binlog/Canal 同步） |
| **数据删除后布隆过滤器不同步** | DB 里删了 ID，布隆里还在 → 继续放行 → 继续打 DB | 可以接受（DB 返回空后走空值缓存）；或用**可删除**的变种 |

**分布式一致性**：多个应用实例必须共用同一个 Redis 里的布隆过滤器（`BF.ADD` 到 Redis），不能各自在 JVM 里维护一份——否则「A 实例加的 ID，B 实例不认」。

**本地布隆过滤器的选择（Java 侧）**：Guava 的 `BloomFilter` 是进程内的，优点是零网络开销，缺点是**多实例不一致 + 容量固定不可扩容 + 重启重新预热**。**推荐用 Redis 的（分布式一致），本地只作为二级加速**。

### 防护三：空值缓存

```java
public UserDTO getUserWithNullCache(Long userId) {
    String key = "user:" + userId;
    String cached = stringRedisTemplate.opsForValue().get(key);
    if (cached != null) {
        return EMPTY_MARKER.equals(cached) ? null : JSON.parseObject(cached, UserDTO.class);
    }
    UserDTO user = userMapper.selectById(userId);
    if (user == null) {
        // 关键：缓存空值，TTL 要短（防内存被大量无效 key 占满）
        stringRedisTemplate.opsForValue()
            .set(key, EMPTY_MARKER, Duration.ofSeconds(60));
        return null;
    }
    stringRedisTemplate.opsForValue()
        .set(key, JSON.toJSONString(user), Duration.ofMinutes(30));
    return user;
}
```

**空值缓存的三个坑**：

1. **TTL 必须短（30~120 秒）**。原因：如果 DB 里后来**真的插入了这条数据**，长 TTL 的「空值」会让业务一直读不到（数据不一致窗口 = 空值 TTL）。短 TTL 把窗口限制住。
2. **内存会被大量无效 key 占满**。攻击者用随机 ID 刷 → 每个都缓存一个空值 → Redis 内存爆（还可能触发 LRU 淘汰掉真正的热点 key）。**对策**：① 空值 TTL 短；② 配合限流（同一 IP 的 miss 次数阈值）；③ 空值 key 用独立的命名前缀 + 更激进的淘汰策略。
3. **`EMPTY_MARKER` 必须是一个业务上不可能出现的值**（比如 `"__NULL__"`），不能直接用 `null` 或者空字符串——否则分不清「缓存里是空值」和「缓存里没有这个 key」。**这是面试官很喜欢追的细节。**

### 防护四：限流（防恶意攻击）

穿透很多时候是**攻击行为**，纯技术方案防不住流量本身：

```lua
-- 对同一来源的「未命中」计数限流
-- KEYS[1]=rate:miss:{sourceIp}  ARGV[1]=窗口秒  ARGV[2]=最大 miss 次数
local n = redis.call('INCR', KEYS[1])
if n == 1 then
    redis.call('EXPIRE', KEYS[1], ARGV[1])
end
if n > tonumber(ARGV[2]) then
    return 0        -- 超限，直接拒绝（不再查 DB）
end
return 1
```

配合网关层（Nginx / Spring Cloud Gateway）的 IP 维度限流，效果更好。
:::

:::拓展
**完整方案的分层结构（面试答这个顺序，条理清晰）**

| 层 | 手段 | 挡住什么 |
|---|---|---|
| 1. 网关层 | IP 限流、黑名单、WAF | 明显的扫描/CC 攻击 |
| 2. 应用层 | 参数校验（ID 格式、范围） | 非法参数 |
| 3. 缓存层（前） | **布隆过滤器** | 不存在的 key（99% 挡在这里） |
| 4. 缓存层（后） | **空值缓存（短 TTL）** | 布隆误判漏过来 + 新删除的数据 |
| 5. 监控层 | 命中率告警（`keyspace_misses` 突增） | 事后发现 |

**监控指标**——穿透的最佳发现方式是命中率：

```bash
redis-cli INFO stats | grep -E "keyspace_hits|keyspace_misses"
# keyspace_hits:9876543
# keyspace_misses:912345          ← miss 占比超过 10% 要查原因
# 命中率 = hits / (hits + misses)
```

**`keyspace_misses` 突然飙升**是最典型的穿透信号。但要注意：**正常的缓存预热期 miss 也会高**，要看趋势而不是绝对值。

**布隆过滤器的替代品：Cuckoo Filter（布谷鸟过滤器）**

RedisBloom 提供 `CF.RESERVE` / `CF.ADD` / `CF.EXISTS` / `CF.DEL`——**支持删除**，且空间效率比布隆过滤器略好。代价是**存在「插入失败」的可能**（两个哈希位置都被占且踢不动时需要扩容），且**假阳性率稍高**。选型：**需要删除就用 Cuckoo，不需要就用 Bloom（更简单）**。

**另一种思路：缓存预热 + 白名单**。如果合法 ID 集合是封闭的（比如「所有已注册的设备序列号」），可以直接用 Set 存白名单（`SISMEMBER` 判断）。**代价是内存**：100 万个 20 字节的序列号要 30MB+，而布隆过滤器只要 1.2MB。**「内存换准确率」还是「准确率换内存」，这是个明确的取舍点，面试可以说出来。**
:::

:::追问
**Q：布隆过滤器里说有，但 DB 里其实没有，怎么办？**
这就是**假阳性**。处理方式：**照常查 DB**，DB 返回空 → 走空值缓存（短 TTL）→ 下次直接从缓存拿到空值，不再打 DB。**所以布隆过滤器不要求 100% 准确，它只要把绝大部分不存在的请求挡掉就够了**，剩下的交给空值缓存兜底。**这就是为什么「布隆 + 空值缓存」是成对出现的方案。**

**Q：DB 里删了数据，布隆过滤器怎么同步？**
布隆过滤器**不支持删除**，所以：
1. **什么都不做**（推荐）：布隆里还有这个 ID，请求放行 → 查到 DB 是空 → 空值缓存兜住。**代价是「已删除 ID」的请求会持续打 DB 一段时间**（直到下一次重建布隆过滤器）。
2. **定期重建**：每天/每小时从 DB 全量重建（`BF.RESERVE` 新 key → `BF.MADD` → `RENAME`）。**重建期间要有新旧双过滤器**（新 key 先建好再原子 rename）。
3. **用 Cuckoo Filter**（`CF.DEL` 支持删除），代价是插入可能失败 + 误判率略高。
4. **用位图 + 计数器**（Counting Bloom），每个位置用 4 bit 计数，删除时 -1。代价是内存涨 4 倍。

**Q：为什么不用 `null` 或空字符串做空值标记？**
因为 `RedisTemplate.get()` 对不存在的 key 返回 `null`，对存了 `""` 的 key 返回 `""`。如果你用 `""` 或 `null` 语义去判断，就分不清「key 不存在（要查 DB）」和「key 存在但是空值（直接返回 null）」——**结果就是每次都查 DB，空值缓存完全失效**。所以必须用**特殊哨兵值**（`"__NULL__"`、`"$NULL$"` 之类），业务上不可能出现的字符串。

**Q：`BF.RESERVE` 的误判率设多少合适？**
`0.01`（1%）是常见起点。误判率越低 → 需要的 bit 数越多。从 1% 降到 0.1%，内存大约涨 50%（因为 `m ∝ ln(1/p)`）。**误判率直接换算成本是「打 DB 的额外流量」**：1% 误判率意味着每 100 万个被拦住的请求里有 1 万个漏到 DB——这个量级通常完全可以接受。**别为了把小概率降到更低而多花几倍内存。**
:::

:::锚点
**这个点我必须诚实说：你在项目里没有真实的布隆过滤器实战。**所以面试策略是**主动降级到「方法论 + 类比」**，而不是编造：

面试话术：「缓存穿透的问题是**数据不存在所以永远 miss**，布隆过滤器用 bitmap + 多哈希做到『一定不在』100% 准确。**我们项目里 Redis 主要做缓存和分布式锁，没有上布隆过滤器——因为我们的查询都是按场所/AP 这些有明确维度的 key，参数校验能覆盖。如果要做，我会优先在网关层加 IP 维度的 miss 限流，再上布隆过滤器，因为限流的成本更低、见效更快。**」

**这个回答的杀伤力在于「为什么不上」比「怎么用」更能体现判断力** —— 布隆过滤器需要全量预热 + 定期重建 + 多副本一致，是有运维成本的。**在参数校验已经能挡住大部分无效请求的场景下，不引入它是正确的工程决策。**

**如果想找一个真实的类比**：你们 RRM 里「查询某个 AP 的调优记录」，AP 序列号是**有明确来源的**（设备上报过才存在）。这本质上就是一种天然的「白名单」——如果请求的序列号不在「已注册设备」集合里，直接返回空就行，根本不需要布隆过滤器。**面试时说出「我们的 ID 空间是封闭的、可枚举的，所以参数校验就够了」，比硬套布隆过滤器更有说服力。**

**Java 补课（如果面试官追问实现）**：Redis 侧用 `RedisBloom` 的 `BF.ADD`/`BF.EXISTS`，Spring Data Redis 通过 `RedisTemplate.execute(RedisScript.of(...))` 执行 `BF.*` 命令（Spring Data Redis 没有为布隆过滤器提供原生 API，要用 `execute` 加自定义脚本或直接调命令）；本地侧用 Guava `BloomFilter.create(Funnels.longFunnel(), 1000000L, 0.01)`。**能说出「Spring Data Redis 没有原生布隆过滤器 API，要用 RedisScript 执行」这个细节，就证明不是背的。**
:::

---

## 9. 缓存击穿（热点 key 过期）

:::概念
击穿 = **一个被高并发访问的热点 key 突然过期**，瞬间所有请求同时发现 miss → 全部去查 DB 重建 → DB 被打穿。
记忆钩子：**「击穿是『一个 key 的锅』——数据在 DB 里是有的，只是缓存刚没，而重建它的那一刻被几万个请求同时撞上了。」**
:::

:::提问
- 什么是缓存击穿？和穿透、雪崩区别？
- 怎么解决击穿？互斥锁和逻辑过期哪个好？
- 互斥锁重建的完整代码怎么写？
- 逻辑过期方案返回旧数据，业务能接受吗？
:::

:::答案
### 两种方案的本质差异

| | 互斥锁重建 | 逻辑过期 |
|---|---|---|
| 思路 | **只让一个线程去重建，其他线程等待** | **value 里带逻辑过期时间，过期后返回旧值，异步重建** |
| 请求是否阻塞 | **阻塞**（要等重建完） | **不阻塞**（立即返回旧数据） |
| 数据一致性 | 强（拿到的一定是新数据） | **弱**（可能返回过期数据） |
| 实现复杂度 | 中（要处理锁失败、重试、双重检查） | 高（要维护异步线程池、内存队列） |
| 适用 | 对一致性要求高、能接受短暂等待 | **高并发 + 能容忍旧数据**（如商品详情、排行榜） |
| 风险 | 大量线程阻塞 → 线程池耗尽 | 异步重建失败 → 一直返回旧数据 |

**一句话选型**：「**能容忍旧数据就用逻辑过期（不阻塞），不能容忍就用互斥锁（阻塞但准）。**

### 方案一：互斥锁重建（完整 Java 代码）

**核心思路：缓存 miss 时，用 `SET NX` 抢锁，抢到的去查 DB 并回填缓存，没抢到的短暂 sleep 后重试（重试时缓存大概率已经好了）。**

```java
public UserDTO getUserWithMutex(Long userId) {
    String cacheKey = "user:" + userId;
    // ① 第一次查缓存
    String cached = stringRedisTemplate.opsForValue().get(cacheKey);
    if (cached != null) {
        return JSON.parseObject(cached, UserDTO.class);
    }

    // ② 没命中，尝试抢锁重建
    String lockKey = "lock:user:" + userId;
    String lockValue = UUID.randomUUID().toString();
    Boolean locked = stringRedisTemplate.opsForValue()
            .setIfAbsent(lockKey, lockValue, Duration.ofSeconds(10));

    if (Boolean.TRUE.equals(locked)) {
        try {
            // ③ 双重检查：抢到锁之后再查一次缓存
            //    因为可能在你排队等锁的这段时间，别人已经重建好了
            cached = stringRedisTemplate.opsForValue().get(cacheKey);
            if (cached != null) {
                return JSON.parseObject(cached, UserDTO.class);
            }
            // ④ 查 DB 并回填
            UserDTO user = userMapper.selectById(userId);
            if (user == null) {
                stringRedisTemplate.opsForValue()
                        .set(cacheKey, "__NULL__", Duration.ofSeconds(60));
                return null;
            }
            stringRedisTemplate.opsForValue()
                    .set(cacheKey, JSON.toJSONString(user), Duration.ofMinutes(30));
            return user;
        } finally {
            // ⑤ 释放锁：必须用 Lua 保证「比对 + 删除」原子
            unlock(lockKey, lockValue);
        }
    } else {
        // 没抢到锁：短暂 sleep 后重试（别无限重试，会打爆线程池）
        try {
            Thread.sleep(50);
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
        }
        // 重试读缓存（此时大概率已经有值了）
        cached = stringRedisTemplate.opsForValue().get(cacheKey);
        if (cached != null) {
            return JSON.parseObject(cached, UserDTO.class);
        }
        // 兜底：直接查 DB（不做缓存重建，避免锁等待堆积）
        return userMapper.selectById(userId);
    }
}

private static final String UNLOCK_LUA =
    "if redis.call('get', KEYS[1]) == ARGV[1] then " +
    "  return redis.call('del', KEYS[1]) " +
    "else return 0 end";

private void unlock(String key, String value) {
    stringRedisTemplate.execute(
        new DefaultRedisScript<>(UNLOCK_LUA, Long.class),
        Collections.singletonList(key), value);
}
```

**必须讲清楚的四个细节（面试官会追）**：

1. **为什么抢到锁后还要再查一次缓存（第 ③ 步）**——**双重检查**。在「你发现 miss」到「你抢到锁」之间可能有几十毫秒，别的线程可能已经重建好了。不查的话会重复查 DB。
2. **为什么没抢到锁要直接返回旧数据或者查 DB（兜底），而不是死等**——如果重建很慢（DB 慢查询），几万个线程全在 sleep 等待 → **Tomcat 线程池被占满** → 整个服务不可用。**「缓存击穿的方案本身变成雪崩」是这个方案最大的风险**，必须有超时/兜底。
3. **锁的 TTL 要大于重建耗时**，否则锁过期了重建还没完成，又会有第二个线程进来重建（虽然不会出错，但失去了互斥意义）。
4. **释放锁一定要用 Lua**（见第 12 题），`GET` 完再 `DEL` 中间可能锁已过期被别人拿到，你会删掉别人的锁。

**Python/Node 版本的等价写法**（你是 Node 出身，可以拿来做对比）：

```javascript
// ioredis 版本
const locked = await redis.set(lockKey, lockValue, 'PX', 10000, 'NX');
if (locked === 'OK') {
  try {
    // 双重检查 + 查 DB + 回填
  } finally {
    await redis.eval(UNLOCK_LUA, 1, lockKey, lockValue);
  }
}
```

### 方案二：逻辑过期（不阻塞，返回旧值）

**核心思路：缓存里永远不放「会过期的 key」，而是放一个「带 expireTime 字段的 value」。判断过期不看 Redis TTL，看 value 里的时间戳。发现逻辑过期就返回旧值 + 异步重建。**

```java
/** 包装类：value + 逻辑过期时间 */
@Data
public class RedisData {
    private LocalDateTime expireTime;
    private Object data;
}
```

```java
private static final ExecutorService REBUILD_POOL =
        Executors.newFixedThreadPool(10);

public UserDTO getUserWithLogicalExpire(Long userId) {
    String cacheKey = "user:" + userId;
    String json = stringRedisTemplate.opsForValue().get(cacheKey);

    // ① 缓存里根本没有 → 走互斥锁或不缓存（这是穿透问题，不是击穿）
    if (json == null) {
        return loadFromDbAndCache(userId);
    }

    RedisData redisData = JSON.parseObject(json, RedisData.class);
    // ② 逻辑未过期 → 直接返回
    if (redisData.getExpireTime().isAfter(LocalDateTime.now())) {
        return JSON.parseObject(JSON.toJSONString(redisData.getData()), UserDTO.class);
    }

    // ③ 逻辑已过期 → 先抢锁，抢到的开异步线程重建，抢不到的直接返回旧值
    String lockKey = "lock:user:" + userId;
    Boolean locked = stringRedisTemplate.opsForValue()
            .setIfAbsent(lockKey, "1", Duration.ofSeconds(10));
    if (Boolean.TRUE.equals(locked)) {
        REBUILD_POOL.submit(() -> {          // 异步重建，不阻塞当前请求
            try {
                UserDTO user = userMapper.selectById(userId);
                RedisData newData = new RedisData();
                newData.setData(user);
                newData.setExpireTime(LocalDateTime.now().plusMinutes(30));
                // 注意：这里**不设 Redis TTL**（或设一个很长的兜底 TTL）
                stringRedisTemplate.opsForValue()
                        .set(cacheKey, JSON.toJSONString(newData));
            } finally {
                unlock(lockKey, "1");
            }
        });
    }
    // ④ 无论抢没抢到锁，都**立即返回旧数据**
    return JSON.parseObject(JSON.toJSONString(redisData.getData()), UserDTO.class);
}
```

**关键工程细节**：

| 细节 | 做法 |
|---|---|
| **key 永不过期** | 逻辑过期方案里 Redis 的 TTL 设为 `-1`（不过期），或设一个很长的 TTL 作为兜底。**如果设了短 TTL，就退化成了击穿问题本身** |
| **异步线程池必须隔离** | 重建逻辑用**独立的线程池**，不能和业务共用；要设队列长度和拒绝策略，防止重建任务堆积 |
| **重建失败要有退避** | 如果 DB 一直失败，每次请求都触发重建 → 打爆 DB。要加「最近失败过就跳过重建」的标记（比如 30 秒内不再尝试） |
| **缓存预热** | 逻辑过期的缓存必须**提前预热进去**（否则 key 不存在，要走穿透逻辑）——常用启动时或定时任务加载热点数据 |

### 方案三：热点 key 永不过期（最简单）

对少数的超级热点（如首页配置、活动规则）**设 `TTL = -1`（永不过期）**，由**后台定时任务或配置变更事件**主动更新缓存。缺点：更新有延迟（取决于刷新周期），且需要额外的刷新机制。
:::

:::拓展
**「热点 key」是怎么被发现的**

你不知道哪个 key 是热点，就没法针对它做保护。三种发现方式：

```bash
# ① 需要 maxmemory-policy = allkeys-lfu，统计访问频率
redis-cli config set maxmemory-policy allkeys-lfu
redis-cli --hotkeys
# [00.00%] Hot key 'user:1001' found so far with counter 156
# [00.00%] Hot key 'config:home' found so far with counter 132

# ② 单个 key 的访问次数（LFU 策略下）
redis-cli object freq user:1001        # 12

# ③ 业务侧埋点：在应用层统计每个 key 的访问量，定期上报监控
```

**`--hotkeys` 的原理**：`SCAN` 全库 + 对每个 key 读 `OBJECT FREQ`，所以是**采样**，且会遍历全库（对大实例有压力）。**生产上更推荐用业务埋点 + 监控**（如 Java 侧用 AOP 统计热点，或接入京东 hotkey 这类热点探测中间件）。

**热点 key 的第二重风险：Cluster 下的数据倾斜**

如果某个 key 是超级热点（比如 `config:global`），在 Redis Cluster 里它只在一个节点的一个槽上 → **那一个节点的 CPU/带宽被打满，其他节点闲着**。这叫**热点倾斜**，扩容也解决不了（因为槽位是固定的）。

对策：**把热点 key 复制成 N 份**（`config:global:0` ~ `config:global:9`），客户端随机选一个读。代价是**写的时候要写 N 份**（或者只做主从读副本 + 定时刷新）。

**这个思路和你们 Kafka 的 partition 设计是同一类问题**：Kafka 里如果所有消息都用同一个 key，就全进一个 partition，消费端也一样倾斜。**跨中间件的同构问题，面试时主动串起来讲很加分。**
:::

:::追问
**Q：互斥锁方案的锁 TTL 设多长？**
**要大于「DB 查询 + 序列化 + 回填缓存」的 P99 耗时，建议设 3~10 秒**。设太短（如 1 秒）：DB 慢查询时锁提前过期，又会有新线程进来重建（虽然结果不会错，但互斥失去意义，DB 仍会被打）。设太长（如 60 秒）：如果抢到锁的线程挂了（进程被 kill），锁要 60 秒才释放，这期间所有请求都拿不到锁 → 全部走兜底查 DB。**所以要配「兜底：拿不到锁就直接查 DB，但限流」**。

**Q：为什么不用 `synchronized` 或者 JVM 锁？**
因为**应用是多实例部署的**（你们 rrmcontrol 就是多 pod），JVM 锁只能锁住单个实例内的线程，跨实例无效。每个 pod 都会有一个线程去重建，等于锁没用。**这就是「本地锁 → 分布式锁」的必然升级路径**，也是面试官想听的那句话。反过来说：**如果你是单实例部署，`synchronized` + 双重检查就够了**，没必要上 Redis 锁。

**Q：逻辑过期返回旧数据，业务上怎么接受？**
关键是**明确「能容忍多久的旧数据」**。比如商品详情页，用户看到 30 秒前的价格完全没问题；但**库存扣减、余额查询不能这么玩**（那是强一致场景，不能靠缓存）。所以：
- 逻辑过期只用在**读多写少 + 可容忍延迟**的展示类数据；
- 强一致场景**不要缓存，或者用「缓存只做降级」**（Redis 挂了就报错，不能返回旧值）。

**这个「什么数据可以缓存、什么数据不能」的判断，比会写代码更重要。**面试官问「你怎么决定一个接口要不要加缓存」，答「看数据的一致性强要求和更新频率」比答「Redis 快就加」高一个层次。

**Q：如果大量不同的热点 key 同时过期呢？**
那就不是击穿而是**雪崩**了（第 10 题）。区分点在于：击穿的方案是「针对单个 key 做互斥重建」，雪崩要的是「**让它们不要同时过期**」（随机 TTL）+「**Redis 挂了怎么办**」（多级缓存、熔断）。**一个 1000 QPS 的热点 key 过期是击穿；10000 个各自 1 QPS 的 key 同时过期也是击穿叠加，但根因是 TTL 设计，处置手段是随机化 TTL。**这个边界能被面试官追问，要能说清。
:::

:::锚点
**诚实的项目定位**：你没有在项目里写过互斥锁重建缓存的代码，但你有**更贴近实战的两个东西**——

**① 你项目的调优任务互斥锁，就是同一套机制的业务化。**rrmcontrol 的 scheduler 每 60s 触发一次，多 pod 部署，必须用 Redis 锁保证只有一个 pod 真正执行调优。**这里的锁语义和「缓存击穿互斥锁」完全一样**：抢到锁的干活，没抢到的跳过。区别只是「没抢到锁后做什么」——缓存场景是 sleep 重试读缓存，任务场景是**直接跳过本次 tick**（因为 60 秒后还会再触发）。

**面试话术**：「我们 scheduler 每 60 秒触发一次调优任务，多 pod 部署，用 Redis 的 `SET NX PX` 做互斥。**这里有个和缓存击穿不一样的关键设计：没抢到锁的 pod 是直接跳过，不是等待重试。**因为任务是周期性的，本 tick 不做下个 tick 还会来，等待只会让多个 pod 的线程全部挂着。**这个取舍的思路和『击穿场景下拿不到锁要兜底查 DB 而不是死等』是同一个道理——不能因为一个锁把线程池拖死。**」

**② 你排查过 rrmcontrol 的 `write after end` 反复重启，这是「连接/锁的生命周期」类问题。**多 pod + Redis 锁的组合下，最常见的坑就是**pod 被 kill 时锁没释放**（没有 finally / 进程被 SIGKILL 来不及执行 finally）。对策是：① 锁**必须带 TTL**（这样 pod 被杀最多脏一个 TTL 的时间）；② 长任务用**看门狗续期**（第 12 题）；③ 或者用「锁 + 任务状态标记」双保险，让下一个 pod 能识别出「这个锁是僵死任务的」。

**如果面试官问「你写过缓存击穿的代码吗」**，正确答法是：「没有专门写过击穿的防护代码，我的理解是从分布式锁那套机制迁移过来的——**击穿的互斥锁重建，本质就是『拿锁去重建一个共享资源』，和我们多 pod 间用 Redis 锁保证任务不重复执行是同一个模式**。区别只在失败路径的处理。」**承认 + 建立关联 + 说清差异**，比背一段代码可信得多。
:::

---
## 10. 缓存雪崩（大面积失效）

:::概念
雪崩 = **大量 key 在同一时刻失效，或 Redis 整体不可用**，流量全部压到 DB，DB 被打垮 → 连锁反应到整个系统。
记忆钩子：**「击穿是『一个 key 的锅』，雪崩是『一群 key 的锅』或者『缓存这层没了』——前者治 TTL，后者治架构。」**
:::

:::提问
- 什么是缓存雪崩？怎么解决？
- 你们线上怎么防止大量 key 同时过期？
- Redis 整个挂掉怎么办？怎么保证 DB 不被打穿？
- 多级缓存怎么设计？本地缓存的一致性问题怎么处理？
:::

:::答案
### 两种情况，两套解法

| 情况 | 根因 | 解法 |
|---|---|---|
| **A. 大量 key 同时过期** | TTL 设置相同（如统一 30 分钟），一批数据同时写入 → 同时过期 | **随机 TTL**、错峰预热、永不过期 + 后台刷新 |
| **B. Redis 整体不可用** | 单点故障、网络分区、被限流/封禁、实例被打满 | **多级缓存 + 熔断降级 + 限流 + 高可用架构** |

**面试时必须把这两种分开讲**——很多人只答「加随机值」，那是只解决了 A，**B 才是真正会打垮系统的那个**。

### 解法 A：随机 TTL（一行代码的事，但要说清原理）

```java
// 错误做法：所有 key 都是固定的 30 分钟
// 业务批量预热 10 万个 key → 30 分钟后这 10 万个 key 同时过期 → 雪崩
redisTemplate.opsForValue().set(key, value, Duration.ofMinutes(30));

// 正确做法：基础 TTL + 随机扰动
public static Duration randomTtl(int baseSeconds) {
    int random = ThreadLocalRandom.current().nextInt(0, baseSeconds / 5);  // 20% 抖动
    return Duration.ofSeconds(baseSeconds + random);
}
// 30 分钟 → 1800 ~ 2160 秒之间的随机值

redisTemplate.opsForValue().set(key, value, randomTtl(1800));
```

**抖动幅度怎么定**：一般取基础 TTL 的 **10%~30%**。抖动太小（1%）不足以打散；抖动太大（100%）会导致缓存命中率波动大。**关键是让「同一批写入的 key」的过期时间散布在一个时间窗内，而不是一秒钟内。**

**配套手段**：
- **错峰预热**：批量加载数据时，按 key 分批写入并 sleep，天然错开
- **永不过期 + 后台刷新**：热点数据设 `TTL=-1`，用定时任务/事件驱动刷新（见第 9 题逻辑过期）
- **写缓存时不要「同一时刻全量重写」**：比如定时任务每 5 分钟全量刷新 → 改成增量刷新或分批刷新

### 解法 B：多级缓存

```
请求
  │
  ├─ ① 本地缓存（进程内：Caffeine / Guava Cache / 简单 ConcurrentHashMap）
  │     命中 → 直接返回（纳秒级，无网络）
  │     ↓ miss
  ├─ ② Redis（分布式缓存）
  │     命中 → 返回（亚毫秒级）
  │     ↓ miss
  ├─ ③ 熔断判断：Redis 是否可用？
  │     不可用 → 返回降级数据 / 兜底值（**不打 DB**）
  │     ↓ 可用
  └─ ④ 查 DB（MongoDB / MySQL）+ 回填 Redis 和本地缓存
```

**本地缓存选型（Java 侧）**：

| 方案 | 特点 | 适用 |
|---|---|---|
| `ConcurrentHashMap` | 无淘汰、无过期，**必须自己管** | 配置类、几乎不变的字典数据 |
| **Caffeine** | W-TinyLFU 淘汰算法，性能最好的 JVM 本地缓存 | **推荐** |
| Guava Cache | 老牌，功能全，性能略逊于 Caffeine | 维护老项目 |
| Ehcache | 支持堆外/磁盘持久化 | 大数据量、需要落盘 |

```java
// Caffeine 配置示例
LoadingCache<String, UserDTO> localCache = Caffeine.newBuilder()
        .maximumSize(10_000)                          // 最多 1 万个条目（防内存泄漏）
        .expireAfterWrite(Duration.ofSeconds(30))     // 本地 TTL 要**远短于** Redis TTL
        .refreshAfterWrite(Duration.ofSeconds(10))
        .recordStats()                                // 开启命中率统计，便于监控
        .build(key -> userMapper.selectById(key));
```

**本地缓存的 TTL 必须远短于 Redis 的 TTL** —— 因为本地缓存**无法被集中失效**。

### 本地缓存的一致性问题（高频追问）

**根因**：本地缓存在每个 JVM 里，写数据时删 Redis 容易（一次 `DEL`），但删掉 10 个 pod 的内存缓存做不到。

| 方案 | 做法 | 生效延迟 |
|---|---|---|
| **短 TTL 兜底**（最简单） | 本地 TTL 设 5~30 秒 | 最坏滞后一个 TTL |
| **消息广播失效** | 写数据后发 Redis Pub/Sub 或 MQ，所有实例订阅并清本地缓存 | 毫秒~秒级 |
| **版本号/时间戳** | 缓存 value 里带版本号，读的时候比对 Redis 里的全局版本，不一致就重载 | 一次额外查询 |
| **Canal/CDC 广播** | 订阅 DB binlog，广播给所有实例失效 | 秒级 |

```java
// 广播失效的骨架（Redis Pub/Sub）
// 写侧
redisTemplate.convertAndSend("cache:invalidate", "user:" + userId);

// 读侧（每个实例都订阅这个频道）
@Bean
RedisMessageListenerContainer listenerContainer(RedisConnectionFactory factory) {
    RedisMessageListenerContainer container = new RedisMessageListenerContainer();
    container.setConnectionFactory(factory);
    container.addMessageListener((message, pattern) -> {
        String key = new String(message.getBody());
        localCache.invalidate(key);      // 清掉本地缓存
    }, new ChannelTopic("cache:invalidate"));
    return container;
}
```

**注意 Pub/Sub 的可靠性问题**：**消息不是持久化的**，订阅者掉线期间的消息会丢。所以**必须有短 TTL 兜底**（上面表格的第一项），Pub/Sub 只是「加速一致性」而不是保证一致性。

### 解法 B 补充：熔断降级

**核心思想：Redis 挂了的时候，宁可直接返回降级数据，也不能让流量打到 DB。**

```java
// 伪代码：带熔断的读缓存逻辑
public UserDTO getUser(Long userId) {
    try {
        String cached = stringRedisTemplate.opsForValue().get("user:" + userId);
        if (cached != null) return parse(cached);
    } catch (Exception e) {
        // Redis 异常 → 检查熔断器状态
        if (circuitBreaker.isOpen()) {
            return getDegradedValue(userId);     // 直接返回降级值，不打 DB
        }
        // 熔断器未打开 → 允许少量请求探路（打 DB），但要限流
    }
    return loadFromDbWithRateLimit(userId);
}
```

**Java 侧实现**：Resilience4j（推荐，轻量）、Sentinel（阿里，带控制台）、Hystrix（已停止维护）。**面试提到 Sentinel/Resilience4j 并在简历里写「做过服务治理」时，要能说清「熔断的三种状态：关闭 → 打开 → 半开」**。

### 解法 B 补充：限流（保护 DB 的最后一道闸）

```lua
-- 令牌桶限流的简化实现（保护 DB 的并发查询）
-- KEYS[1]=limiter  ARGV[1]=速率(个/秒)  ARGV[2]=桶容量  ARGV[3]=当前时间戳(微秒)
local rate = tonumber(ARGV[1])
local capacity = tonumber(ARGV[2])
local now = tonumber(ARGV[3])

local bucket = redis.call('HMGET', KEYS[1], 'tokens', 'ts')
local tokens = tonumber(bucket[1]) or capacity
local lastTs = tonumber(bucket[2]) or now

-- 按时间差补充令牌
local delta = math.max(0, now - lastTs) / 1000000
tokens = math.min(capacity, tokens + delta * rate)

if tokens >= 1 then
    tokens = tokens - 1
    redis.call('HMSET', KEYS[1], 'tokens', tokens, 'ts', now)
    return 1                     -- 放行
else
    redis.call('HMSET', KEYS[1], 'tokens', tokens, 'ts', now)
    return 0                     -- 拒绝
end
```

**降级的具体形态**（面试要能举出业务化的例子）：
- 返回**默认值**（如空的推荐列表、默认配置）
- 返回**静态兜底数据**（预置在内存里的降级值）
- 返回**友好错误**（「系统繁忙，请稍后重试」而不是 500）
- **异步化**：把请求丢进队列稍后处理，前端返回「处理中」

### Redis 高可用（治本）

| 方案 | 恢复时间 | 说明 |
|---|---|---|
| 单机 | 挂到人工恢复 | 不可接受 |
| 主从 | 挂到人工切换 | 只能防数据丢失 |
| **主从 + 哨兵** | **秒级~十几秒** | 自动故障转移（第 16 题） |
| **Cluster** | 秒级 | 分片 + 自动故障转移 |
| 云托管 Redis | 秒级 | 腾讯云/阿里云自动主从切换 |

**注意：高可用解决的是「Redis 挂了能自动恢复」，但不解决「恢复的那十几秒里 DB 被打穿」** —— 这两件事必须同时做。
:::

:::拓展
**雪崩的完整防护体系（面试按这个顺序答最有条理）**

| 层次 | 手段 | 解决什么 |
|---|---|---|
| 1. 预防 | **随机 TTL**、错峰预热、永不过期 | 防「同时过期」 |
| 2. 兜底 | 多级缓存（本地 + Redis） | Redis 挂了还能扛一部分 |
| 3. 保护 | **熔断降级** | 不打 DB，快速失败 |
| 4. 限流 | 令牌桶 / 信号量 | DB 只能承受 N 并发，多的一律拒 |
| 5. 高可用 | 哨兵 / Cluster / 云托管 | Redis 尽快恢复 |
| 6. 监控 | 命中率、`evicted_keys`、DB QPS 告警 | 早发现 |

**「缓存命中率」是最重要的监控指标**

```bash
redis-cli INFO stats | grep -E "keyspace_hits|keyspace_misses|evicted_keys"
# 命中率 = hits / (hits + misses)；低于 90% 要排查
# evicted_keys 持续增长 = 内存不够在持续淘汰，命中率必然下降
```

**一个常被忽略的雪崩诱因：Redis 内存满了开始淘汰**

如果 `maxmemory-policy` 是 `allkeys-lru` 且内存长期打满，Redis 会**持续淘汰 key**。这时：
- 被淘汰的 key 下次访问 miss → 重新查 DB 回填 → 又被淘汰 → **循环打 DB**
- 表现就是「缓存看起来正常，但 DB QPS 异常高」

**这是比「Redis 挂掉」更隐蔽的雪崩形态**，因为它不会报错。排查方式：看 `evicted_keys` 的增速 + 缓存命中率趋势。**面试里主动说出这个场景，说明你真的看过监控。**

**Redis 客户端的连接池也是个坑**：Redis 慢（不是挂）的时候，客户端的连接池会被占满，导致**所有依赖 Redis 的接口全部阻塞**，看起来像「整个服务挂了」。所以：
- 连接池要设**超时**（`timeout`：连接超时、读超时、命令超时）
- Lettuce/Jedis 都要配**命令级超时**（如 500ms），不能让请求无限等
- 这也是「Redis 挂了怎么不影响主流程」的答案之一：**超时 + 降级**
:::

:::追问
**Q：本地缓存的容量怎么定？**
**必须设上限**，否则就是内存泄漏。三个参数一起定：
- `maximumSize`：根据「单条数据大小 × 热点数量」估算，且要算进容器内存预算
- `expireAfterWrite` / `expireAfterAccess`：本地 TTL 建议 5~30 秒
- `softValues()` 或 `weakValues()`：让 GC 在内存紧张时能回收（**但会带来 GC 波动，慎用**）

**关键的取舍**：本地缓存是**用内存换延迟**。你项目里 rrmcompute 已经因为 OOM 从 5Gi 调到 5.5GiB 了，**再加一层本地缓存必须把这部分内存算进容器 limit**，否则又是一次 OOMKilled。**这个「任何缓存都要算进内存预算」的认知，是从 OOM 故障里带出来的，讲出来特别有说服力。**

**Q：为什么用「随机 TTL」而不是「统一在凌晨 3 点刷新」？**
统一刷新有两个问题：① 刷新瞬间仍然有大量 key 同时失效（只是挪到了低峰期，但低峰期的流量也不小）；② 如果刷新失败（Redis 抖动），所有 key 都过期了，全部穿透。**随机 TTL 是把失效时间打散，从根本上避免「同一时刻大批量失效」这个现象**。两者可以叠加：随机 TTL 做基础，错峰刷新做补充。

**Q：Redis 主从切换期间的十几秒，请求怎么办？**
**这十几秒就是靠熔断降级扛过去的。**具体：
1. 客户端连不上 Redis → 触发超时（**必须配超时，否则线程全部挂住**）
2. 熔断器打开 → 直接返回降级值，不打 DB
3. 少量「探路」请求打 DB（限流），确认 DB 能扛
4. Redis 恢复 → 熔断器半开 → 试探成功 → 关闭 → 恢复正常

**关键点：如果没有熔断，这十几秒的所有请求都会打 DB，DB 被打垮后即使 Redis 恢复了，系统也起不来**（因为 DB 还在恢复中）。**这就是「雪崩」的完整因果链：缓存失效 → DB 被打垮 → 即使缓存恢复也服务不了。**

**Q：多级缓存会不会让「数据更新后各层不一致」的时间变长？**
会。链路上每一层都有滞后：**本地缓存（短 TTL 或广播失效）→ Redis（主动删）→ DB（事实来源）**。所以设计原则是：
- **写路径只更新 DB + 删 Redis**，本地缓存靠**短 TTL 自然过期**（或广播失效加速）；
- **本地缓存的 TTL 必须最短**（秒级），因为它最难失效；
- **强一致的数据不要放本地缓存**（比如余额、库存）。

**一句话总结**：「多级缓存是把『一致性』换成了『可用性』，所以只放在能容忍不一致的数据上。」
:::

:::锚点
**这个点你有非常强的项目素材，而且是「反向」的素材——你们的 Redis 挂了，MongoDB 直接暴露在流量下。**

**① RRM 的真实依赖结构**：rrmcontrol（Node.js + Kafka + Redis + MongoDB）里，Redis 做缓存和分布式协调，**MongoDB（`10.11.2.140:27017`）是事实来源**。如果腾讯云 Redis（`10.11.2.65:6379`）抖动或不可用：
- 缓存全部 miss → 查询直接压到 MongoDB
- **分布式锁失效 → 多 pod 的 scheduler 同时触发调优任务 → 重复调优 + 任务量翻 N 倍**
- 这两个叠加，就是教科书式的雪崩

**面试话术（这段可以直接用）**：「我们架构里 Redis 有两个职责：缓存和分布式协调。**Redis 不可用的后果不只是『查询变慢』，更严重的是『分布式锁失效导致多个 pod 重复触发调优任务』——这会让后端计算量瞬间翻倍。**所以对我们来说，Redis 的降级策略不能只考虑读缓存，还要考虑锁失效时的兜底：比如在本地加一层『本 pod 最近是否执行过该场所的任务』的记忆，或者用任务状态表做二次校验，避免重复触发。」

**这个回答的杀手锏是：指出了「Redis 不只是缓存」这个架构判断。**大多数候选人只会背「加随机 TTL」，你能说出「锁失效引发重复计算」这种二级故障，层次立刻不同。

**② 随机 TTL 在你这里是刚需**：RRM 里「场所配置」「AP 调优策略」这类数据如果被批量预热，**必须加随机抖动**，否则统一过期时正好撞上 MongoDB 被压垮，形成叠加故障。

**③ 诚实的部分**：你项目里**没有**做过 Caffeine 多级缓存、没有配过熔断器。所以面试时不要编。**正确的说法是**：「我们目前是单层 Redis 缓存，没有做本地缓存，因为我们的服务是多 pod 部署，本地缓存的一致性维护成本比较高。**如果要做，我会优先考虑 Caffeine + 短 TTL（10 秒）+ Redis Pub/Sub 广播失效这个组合，而不是直接上强一致性方案。**」

**④ 你有一个真正的「限流/保护」经验可以迁移**：rrmcompute 现网 OOM 的处置里包含「限制任务并发度」——**这和「限流保护 DB」是同一个思路**：承认下游容量有限，主动在上游做背压。面试时把这个类比说出来，就证明你不是在背方案，而是真的理解「保护下游」这件事。

**⑤ 转 Java 的补课提醒**：Java 侧的 `RedisTemplate` 默认**没有配超时**（`LettuceConnectionFactory` 要显式设 `RedisCommandTimeoutOptions` 或 `TimeoutOptions`），这是从 Node.js 转过来最容易忽略的点——**Node.js 的 ioredis 默认会重连且有超时，Java 的 Lettuce 默认是「命令无限等待」**。面试官如果问「你怎么保证 Redis 挂了不影响主流程」，答「配置命令级超时 + 熔断降级」比答「加随机 TTL」更贴题。
:::

---

## 11. 缓存与数据库的一致性

:::概念
工业界共识方案：**Cache Aside（旁路缓存）——写操作「先更新 DB，再删缓存」**，配合延迟双删 / binlog 订阅兜底，追求**最终一致性**而不是强一致。
记忆钩子：**「写 DB 后删缓存（不是更新缓存），删失败有兜底，短暂不一致可以接受。」**
:::

:::提问
- 怎么保证缓存和数据库的一致性？
- 为什么是删缓存而不是更新缓存？
- 先删缓存再更新 DB 行不行？先更新 DB 再删缓存有没有问题？
- 延迟双删是什么？延迟多久？
- 有没有更强的方案？
:::

:::答案
### 为什么是「删缓存」而不是「更新缓存」

| | 删缓存（Delete） | 更新缓存（Update/Set） |
|---|---|---|
| 计算成本 | 低（不需要算新值，下次 miss 才重建） | 高（每次写都要算 cache value，可能算了一堆没人读的） |
| 并发安全 | 删是**幂等**的，删两次等价删一次 | **两个并发写可能乱序**：A 写 DB→算 value，B 写 DB→算 value，B 先 set 缓存、A 后 set → **缓存是 A 的旧值** |
| 缓存 value 是聚合结果时 | 天然正确（下次读时重算） | 需要精确重算（比如「用户订单数」要重新 count） |

**核心原因**：**删是幂等的、更新不是**。并发场景下，「更新缓存」会因为执行顺序不确定而写入旧值，而「删」无论如何都不会写坏数据。

### 四种组合的竞态分析（必背的表）

| 顺序 | 是否有问题 | 场景 |
|---|---|---|
| 先更新 DB，再更新缓存 | **有问题** | 并发下缓存可能被旧值覆盖（上表） |
| 先删缓存，再更新 DB | **有问题** | 删完、DB 还没更新时，读请求进来 → 查到**旧值**DB → 回填缓存 → **缓存里是旧值且长期有效** |
| **先更新 DB，再删缓存** | **基本安全**（推荐） | 极端情况：读请求在「更新 DB 前」查到旧值，在「删缓存后」才回填 → 缓存是旧值。但要求读操作比写操作还慢（读查 DB 慢 + 网络延迟），**概率极低** |
| 先更新 DB，再删缓存 + 延迟双删 | **更安全** | 覆盖上面那个极端情况 |

**为什么「先删缓存再更新 DB」更危险**：它的失败窗口是**「删缓存 → DB 更新完成」之间**，这段时间内所有读请求都会回填旧值，**且这个旧值会一直留在缓存里**（直到 TTL 到期）。而「先更新 DB 再删缓存」的失败窗口是「读请求读 DB 到写缓存之间」这一段毫秒级的时间，且要求读请求恰好跨越写请求，概率小得多。

### 推荐方案：Cache Aside + 延迟双删

```
写操作：
  ① 更新数据库
  ② 删除缓存
  ③ 延迟 500ms~1s（异步）
  ④ 再次删除缓存          ← 这一步是「双删」的第二删

读操作：
  ① 查缓存，命中直接返回
  ② 未命中 → 查 DB
  ③ 回填缓存（带随机 TTL）
  ④ 返回
```

```java
public void updateUser(UserDTO user) {
    // ① 更新 DB
    userMapper.updateById(user);
    // ② 删缓存
    stringRedisTemplate.delete("user:" + user.getId());
    // ③ 延迟双删：交给延迟队列/定时任务，不要在主线程 sleep
    delayQueue.offer(new DelayTask("user:" + user.getId(), 800, TimeUnit.MILLISECONDS));
}

// 延迟队列的执行体
public void handleDelayDelete(String cacheKey) {
    stringRedisTemplate.delete(cacheKey);
}
```

**为什么第二次删除能覆盖问题窗口**：第二次删除在「第一次删缓存」之后 800ms 执行。如果在这 800ms 内有读请求回填了旧值，第二次删除会把它清掉，下次读时重新从 DB 加载正确值。

**延迟时间怎么定**：**要大于「一次读请求的完整耗时」**（读 DB + 序列化 + 回填缓存），一般取 **500ms ~ 1s**。太短覆盖不住，太长会导致「正常的新数据也被删掉一次」（无害，只是多一次 miss）。

**实现细节**：
- **绝对不要在业务线程里 `Thread.sleep(800)`** —— 会占住 Tomcat 线程。要用：`ScheduledExecutorService`、Redis 的 ZSet 延时队列、RocketMQ 的延迟消息、RocketMQ/Kafka 定时消息。
- **延长 TTL 兜底**：即便双删也漏了，TTL 到了会自动纠正。**所以缓存一定要设 TTL，这是最后一道防线。**

### 最强方案：订阅 binlog（Canal）

**思路：删缓存不靠应用代码，而是靠「DB 数据变更事件」驱动。**应用只管写 DB，一个独立的组件订阅 binlog 并把变更事件投递到 MQ，消费者负责删缓存。

```
应用 ──write──> MySQL/MongoDB
                    │
                    ├── binlog / oplog
                    ▼
                 Canal（伪装成从库，订阅 binlog）
                    │
                    ▼
                  Kafka（可靠传输、可回溯）
                    │
                    ▼
                 缓存删除消费者 → DEL Redis key
                    │
                    └─ 删除失败 → 重试（指数退避）→ 进死信队列 → 告警
```

**优势**：
1. **解耦**：业务代码不需要关心缓存，只管写 DB
2. **不丢事件**：binlog 是 DB 的持久化日志，应用就算删缓存失败，Canal 也能捕获（因为事件源是 DB 而不是应用）
3. **可重试 + 可回溯**：Kafka 保证至少一次投递，消费者可以重放
4. **多消费者**：同一个变更事件可以同时触发「删缓存」「更新搜索索引」「发通知」

**代价**：多一套 Canal + MQ 的运维成本，且**有秒级延迟**（binlog → Canal → Kafka → 消费者）。

**这个方案和你现有技术栈非常契合**——你们本来就有 Kafka（`10.11.2.111:9092`）。**面试时可以说**：「如果要做 binlog 订阅方案，我们不需要额外引入 MQ，因为 Kafka 已经在了，只需要加 Canal。**这是我判断『这个方案在我们环境里落地成本不高』的依据。**」

### 更强但更重：读也加锁 / 分布式读写锁

如果业务真的不能容忍任何脏读，可以：
- **写时加分布式锁**，读也加分布式锁（读的时候禁止写）——代价是性能急剧下降
- **用 `WATCH` / 乐观锁**：读的时候 `WATCH` key，回填前检查是否被改过
- **干脆不缓存**（强一致数据不该缓存）

**结论：绝大多数业务不需要走到这一步。**面试就答「最终一致性 + 秒级容忍」，如果面试官追问「不能容忍怎么办」，答「那就说明这个数据不该做缓存，或者在缓存层之上做版本号校验」。

### 一致性的兜底三件套

| 兜底 | 作用 | 实现 |
|---|---|---|
| **TTL** | 最终一定会纠正 | 所有缓存都设 TTL（带随机抖动） |
| **删除重试** | 应对删除失败（网络抖动/Redis 短暂不可用） | MQ 重试 + 指数退避 + 死信队列 + 告警 |
| **binlog 订阅** | 不依赖应用主动删，避免「代码漏删」 | Canal + Kafka |
:::

:::拓展
**「延迟双删」的两个变种**

| 变种 | 做法 | 适用 |
|---|---|---|
| **双删** | 更新 DB 前删一次 + 更新 DB 后删一次 | 更保守，覆盖「先删缓存后更新 DB」那类回填窗口 |
| **延迟双删（主流）** | 更新 DB → 删缓存 → 延迟后再删一次 | 覆盖「读请求跨越写请求」的窗口 |

**双删的「第一删」有没有必要**：在「先更新 DB 再删缓存」的策略里**没必要**（因为删之前缓存里的值可能是新的也可能是旧的，但更新 DB 后一定会删）。所以主流做法是「更新 DB → 删缓存 → 延迟再删」这个三步。

**主从复制延迟对一致性的影响（容易忽略）**

如果 DB 是主从架构且**读走从库**：

```
① 写请求更新主库（成功）
② 删缓存
③ 读请求 miss → 查**从库**（复制还没完成）→ 读到旧值 → 回填缓存 → 缓存脏了
```

**这个问题的窗口是「主从复制延迟」，可能几十毫秒到几秒**，比单机场景的窗口大得多。对策：
- **写完读主库**（关键数据强制走主库，见「读写分离」的常见约定）
- **延迟双删的时间要覆盖主从延迟**
- **binlog 方案要订阅主库的 binlog**（或者监控从库的复制延迟）

**这个点面试官很喜欢问**，因为它把「缓存一致性」和「DB 主从复制」串起来了。

**能不能用 Lua 脚本保证「读 DB + 回填缓存」的原子性？**
不能 —— **Lua 在 Redis 里执行，访问不了 DB**。Lua 只能保证「多个 Redis 命令」的原子性，不能把 DB 操作也包进来。**所以「缓存和 DB 的强一致」在技术上是不成立的**（除非用两阶段提交，代价极高）。**这句话是这道题的题眼。**
:::

:::追问
**Q：为什么说「缓存与 DB 的强一致」做不到？**
因为**两个系统无法原子提交**。要把「写 DB」和「删缓存」做成一个原子操作，需要跨系统的分布式事务（两阶段提交/三阶段提交），代价极高（性能、可用性都下降）。所以工程上选择**最终一致**：接受一个短暂的窗口，靠 TTL 和重试保证最终收敛。**这就是 CAP 理论在缓存场景的体现——为了可用性和性能，放弃强一致。**

**Q：延迟双删的第二次删除失败了怎么办？**
必须有重试。分级策略：
1. **内存延迟队列重试**（进程内，简单但进程挂了就没）
2. **MQ 重试**（RocketMQ/Kafka，可靠，推荐）——带指数退避（1s、2s、4s...），重试 N 次后进死信队列
3. **死信队列 + 告警**（人工介入或定时补偿任务）
4. **最终兜底**：TTL 到期自动纠正

**注意：重试也必须幂等** —— 删缓存天然幂等，所以只要保证「消息不丢」就行（至少一次投递）。

**Q：如果缓存删了但业务还没提交事务呢？**
这是「先删缓存再更新 DB」+ 事务的组合坑：
```
① 开启事务
② 删缓存
③ 更新 DB（事务未提交，其他连接还读到旧值）
④ 提交事务
```
在 ③ 到 ④ 之间，其他读请求会读到**旧值**并回填缓存。**对策：删缓存必须在事务提交之后**。用 `TransactionSynchronizationManager.registerSynchronization()` 注册 `afterCommit` 回调，或者把删缓存交给「订阅 binlog」的方案（binlog 只在提交后才产生）。**这是 Spring 事务 + 缓存的一个经典坑，面试说出来很加分。**

**Q：你们用的是「先更新 DB 再删缓存」还是别的？**
**千万不要编。**如果你没有真的做过缓存一致性设计，就说：「我们项目的 Redis 主要做缓存和分布式锁，缓存一致性上我做的是最基本的『写库后删缓存 + 所有 key 带随机 TTL』。**延迟双删和 Canal 我知道原理，但没有在生产落地过。**」——这个回答诚实，而且显示了「知道边界」。**编造 Canal 落地经验，被追问 Canal 的配置、MQ 的重试策略、死信队列的处置时必然穿帮。**
:::

:::锚点
**这段要非常克制，因为你的项目没有做「DB 与缓存一致性」的高级设计。**面试策略是**用你的真实架构做定性判断，而不是假装做过优化**：

**① 你的「缓存」和「一致性」的真实关系**：RRM 里 MongoDB 是事实来源，Redis 做缓存。**而且你们的业务特性是「写少读多」**——场所配置、AP 策略这类数据变更频率低，被大量读取。**这正是缓存最理想的场景，也正是「偶尔读到旧值」代价最低的场景。**

面试话术：「我们的数据是配置类、策略类的，写频率很低，所以一致性窗口带来的业务影响很小。**我做的最基本的两件事是：所有缓存 key 强制带 TTL，以及写操作后删缓存。**没有上延迟双删，因为评估下来收益不明显而复杂度上升——**多出来的那 800ms 延迟窗口，在我们的业务里不构成实际问题。**」

**② 「写少读多所以缓存收益高」这个判断，是你从 RRM 业务里真正能拿出的论据。**面试官问「你怎么判断一个接口该不该加缓存」，可以答：「**看读写比和写频率。我们场所配置的读远多于写，且写之后对一致性的要求是秒级可容忍，所以缓存收益远大于风险。**反过来，如果是频繁变更的数据，缓存只会制造一致性问题。」

**③ 关于「先更新 DB 再删缓存」在你环境里的一个具体风险**：你们的 Node.js 服务里如果用 `await` 串行「写 MongoDB → 删 Redis」，**如果第一步成功第二步失败（网络抖动），缓存就脏了**。所以必须保证「删缓存失败不能影响主流程」+「有 TTL 兜底」。

面试话术：「我们的 Node.js 代码里写库和删缓存是两步异步操作。**我的处理原则是：删缓存失败只记日志告警，不让写操作失败**——因为写操作成功才是业务的核心，缓存脏了有 TTL 兜底。**如果反过来让写操作因为删缓存失败而回滚，那就本末倒置了。**」**这个「什么操作可以失败、什么不可以」的优先级判断，是工程成熟度的体现。**
:::

---

## 12. 分布式锁（SET NX PX + Lua 释放 + 看门狗）

:::概念
一条能扛住追问的完整答案：**`SET key value NX PX ttl` 原子加锁 → value 存唯一标识防止误删 → 释放必须用 Lua 保证「比对+删除」原子 → 长任务靠看门狗续期 → 主从切换会丢锁这个缺陷要有意识。**
记忆钩子：**「NX 防并发、PX 防死锁、唯一值防误删、Lua 保证原子——四个缺一个都是 bug。」**
:::

:::提问
- 怎么用 Redis 实现分布式锁？
- 为什么释放锁要用 Lua 脚本？
- 锁过期了但业务没执行完怎么办？
- Redis 锁在什么情况下会失效？
- Redis 锁和 ZooKeeper 锁怎么选？
:::

:::答案
### 从「错误写法」讲到「正确写法」（面试叙事顺序）

**① 最原始的错误写法**

```bash
# 错误 1：SETNX 不带过期 → 客户端崩溃后锁永久不释放，死锁
redis-cli SETNX lock:order 1

# 错误 2：SETNX + EXPIRE 分两步 → 两步之间宕机，又变死锁
redis-cli SETNX lock:order 1
redis-cli EXPIRE lock:order 30
```

**为什么要合并成一条命令**：`SETNX` 和 `EXPIRE` 之间窗口虽小但客观存在，进程被 kill / 网络断开 / 机器掉电都会导致 `EXPIRE` 没执行 → **锁永久存在**。所以要**用一条原子命令同时完成「不存在才设」和「设置过期」**。

**② 正确的基础写法**

```bash
# SET key value NX PX milliseconds —— 一条命令，原子
# NX: 只有 key 不存在时才设置（Not eXists）
# PX: 过期时间（毫秒），也有 EX（秒）
redis-cli SET lock:order "uuid-abc-123" NX PX 30000
# OK          → 加锁成功
# (nil)       → 加锁失败，锁被别人持有

# 查看锁的剩余 TTL
redis-cli TTL lock:order
redis-cli GET lock:order
```

**`value` 必须存唯一标识（如 `UUID + 线程ID`）**，不能存 `1` 或者 `"locked"`。原因见下一节。

**③ 释放锁：为什么必须用 Lua**

**错误写法（有严重 bug）**：

```bash
# 危险！两步之间可能锁已过期
if (GET lock:order == myValue) {
    DEL lock:order        ← 此时锁可能已经过期并被别人拿走了
}
```

**具体事故场景（一定要能讲出来）**：

```
时刻  客户端 A                          客户端 B
────────────────────────────────────────────────────────
T1    加锁成功（TTL 30s）
T2    执行一个 35 秒的慢查询
T3    （无操作，锁在 T30 时自动过期）
T30   锁过期
T31                                      加锁成功（B 拿到锁）
T32   A 执行完，准备释放锁
T32   A 检查发现 "GET lock 是我的值"？
      —— 不是！此时 value 是 B 的值，A 如果直接 DEL，就删掉了 B 的锁
T33                                      此时 B 的锁被删了，C 又能拿到锁 → 互斥失效
```

**所以「比对 + 删除」两步必须在同一个原子操作里**，而 Redis 里能保证这一点的就是 Lua：

```lua
-- unlock.lua：只有 value 是自己时才删
if redis.call('get', KEYS[1]) == ARGV[1] then
    return redis.call('del', KEYS[1])
else
    return 0
end
```

```bash
# 执行
redis-cli --eval unlock.lua lock:order , uuid-abc-123

# 或者用 EVAL 内联
redis-cli EVAL "if redis.call('get', KEYS[1]) == ARGV[1] then return redis.call('del', KEYS[1]) else return 0 end" 1 lock:order uuid-abc-123
```

**为什么 Lua 能保证原子**：Redis 单线程执行命令，**执行整段 Lua 脚本期间不会处理其他客户端的命令**——所以 `get` 和 `del` 之间没有任何插入的机会（见第 17 题）。

**④ 完整的 Java 实现（不依赖 Redisson）**

```java
public class RedisDistributedLock {
    private final StringRedisTemplate redis;
    private static final String UNLOCK_LUA =
        "if redis.call('get', KEYS[1]) == ARGV[1] then " +
        "  return redis.call('del', KEYS[1]) " +
        "else return 0 end";

    /** 加锁：返回锁的唯一标识，失败返回 null */
    public String tryLock(String lockKey, long ttlMillis) {
        String requestId = UUID.randomUUID() + ":" + Thread.currentThread().getId();
        Boolean ok = redis.opsForValue()
                .setIfAbsent(lockKey, requestId, Duration.ofMillis(ttlMillis));
        return Boolean.TRUE.equals(ok) ? requestId : null;
    }

    /** 解锁 */
    public boolean unlock(String lockKey, String requestId) {
        Long result = redis.execute(
                new DefaultRedisScript<>(UNLOCK_LUA, Long.class),
                Collections.singletonList(lockKey), requestId);
        return result != null && result == 1L;
    }

    /** 使用模板 */
    public void doWithLock(String lockKey, Runnable task) {
        String requestId = tryLock(lockKey, 30_000);
        if (requestId == null) {
            throw new IllegalStateException("获取锁失败: " + lockKey);
        }
        try {
            task.run();
        } finally {
            unlock(lockKey, requestId);      // ★ finally 保证一定释放
        }
    }
}
```

**注意 `finally` 释放锁**——这是最简单也最容易忘的点。你们 rrmcontrol 那个 `write after end` 反复重启的故障，本质就是**资源的生命周期管理缺陷**（连接已关闭还在用）。**锁忘记释放是同一类问题**，只是表现形式不同。

### 看门狗（Watchdog）：解决「业务没跑完锁就过期」

**问题**：锁 TTL 设 30 秒，但业务跑了 40 秒 → 锁在第 30 秒过期 → 别的客户端拿到锁 → **两个客户端同时执行临界区代码**（互斥被破坏）。而且如果业务真的执行完了想释放锁，`GET` 发现 value 变了（不是自己的），释放失败 → 锁要等新的持有者释放。

**Redisson 的看门狗机制**：

```java
// Redisson 用法
@Autowired private RedissonClient redissonClient;

RLock lock = redissonClient.getLock("lock:order:1001");
try {
    // tryLock(waitTime, leaseTime, unit)
    //   waitTime = 0  → 不等待，立即返回（拿不到就 false）
    //   leaseTime = -1 → **启用看门狗**（不指定租期）
    boolean acquired = lock.tryLock(0, -1, TimeUnit.SECONDS);
    if (!acquired) {
        return;  // 没拿到锁
    }
    // ... 业务逻辑，可以跑任意长时间
} catch (InterruptedException e) {
    Thread.currentThread().interrupt();
} finally {
    if (lock.isHeldByCurrentThread()) {     // ★ 必须判断是不是自己持有的
        lock.unlock();
    }
}

// 指定了 leaseTime 则**不启用看门狗**，锁到期就不再续期
// boolean acquired = lock.tryLock(0, 30, TimeUnit.SECONDS);
```

**看门狗的工作机制**：

| 项 | 默认值 | 配置 |
|---|---|---|
| 看门狗超时时间 | **30 秒** | `lockWatchdogTimeout` |
| 续期间隔 | **超时时间的 1/3 = 10 秒** | 固定比例 |
| 续期方式 | 定时任务（`Timeout`）+ Lua 脚本（检查 value 是自己的才续期） | `renewExpiration()` |
| 触发条件 | **「不指定 leaseTime」时才启用** | 指定了就不续期 |

**续期的 Lua 脚本逻辑**（Redisson 内部）：
```lua
-- 只有 value 还是自己的（说明锁没被别人抢走）才续期
if redis.call('hexists', KEYS[1], ARGV[2]) == 1 then
    return redis.call('pexpire', KEYS[1], ARGV[1])
else
    return 0
end
```

**看门狗的隐患（面试的深度分水岭）**：
1. **客户端进程被 kill（SIGKILL）** → 定时任务消失 → 锁在最多 30 秒后过期。**这是可接受的**（正是 TTL 的意义）。
2. **客户端长时间 GC / STW** → 续期定时器没跑 → 锁过期 → 别的客户端拿到锁 → **原来的客户端 GC 结束后继续执行临界区** → 互斥失效。**这是 Redis 锁原理上无法解决的问题**（详见第 13 题）。

### 可重入锁（Redisson 用 Hash 实现）

普通的 `SET NX` 锁**不可重入**：同一个线程第二次获取同一个锁会失败（因为 key 已存在）。

Redisson 用 **Hash 结构**实现可重入：

```
KEY: lock:order:1001
  ├── field = "UUID:threadId"  →  value = 重入次数
  └── 例如: "a1b2c3d4:42" → 2

加锁（Lua）：field 存在 → hincrby 计数 +1 并续期
              field 不存在 → hset 计数=1 并设置 TTL
解锁（Lua）：field 存在 → hincrby 计数 -1
             计数 > 0 → 续期（不删 key）
             计数 = 0 → hdel + del key
```

**为什么要 `UUID:threadId` 而不是只用 `threadId`**：不同 JVM 的线程 ID 可能相同，所以必须加客户端唯一标识（UUID）区分。

### 锁的几个关键参数怎么定

| 参数 | 怎么定 | 说明 |
|---|---|---|
| **锁 TTL** | 用看门狗时不用管；不用看门狗时 = 业务 P99 耗时 × 2 | TTL 是在「宕机后锁多久释放」和「业务超时被抢锁」之间的取舍 |
| **等待时间（waitTime）** | 秒级。0 = 立即失败 | 太长会导致线程堆积 |
| **锁的粒度** | **按业务实体拆分**（`lock:order:1001` 而不是 `lock:order`） | 粒度太大会串行化所有请求 |
| **锁的 key 命名** | `lock:<业务>:<实体ID>` | 便于排查 |
| **失败策略** | 快速失败 > 阻塞等待 | 阻塞等锁会占住 Tomcat 线程 |

```bash
# 排查锁问题的常用命令
redis-cli GET lock:order:1001           # 看是谁持有
redis-cli TTL lock:order:1001           # 看剩余 TTL
redis-cli --scan --pattern "lock:*" | head -50   # 看有哪些锁（注意用 scan 不用 keys）
redis-cli --scan --pattern "lock:*" | wc -l      # 看锁的总数（判断是否泄漏）
```
:::

:::拓展
**Redis 锁的四个失效场景（面试最爱挖的深度）**

| 场景 | 后果 | 缓解 |
|---|---|---|
| **主从切换丢锁** | 主节点 `SET NX` 成功但还没同步到从节点就宕机 → 从节点提升 → 新客户端能拿到同一把锁 → **两个客户端同时持锁** | `WAIT` 命令、Redlock、改用 ZooKeeper/etcd |
| **GC/STW 停顿** | 客户端持锁期间 STW 超过 TTL → 锁过期 → 别人拿到锁 → 原客户端恢复后继续执行 → **两个客户端同时持锁** | 无法根治；用 fencing token 让下游校验 |
| **时钟跳变** | NTP 校时导致锁 TTL 计算异常 | 用 `PX` 相对时间（Redis 内部用相对过期，影响小）；Redlock 影响大 |
| **锁被误删** | 没用 Lua 或没存唯一值 | Lua + 唯一标识 |

**`WAIT` 命令（Redis 3.0+）——「提高锁的可靠性」的一个技巧**

```bash
redis-cli SET lock:order "uuid-123" NX PX 30000
redis-cli WAIT 1 100
# 返回实际同步成功的副本数
# WAIT numreplicas timeout(ms)
```

`WAIT 1 100` 表示「等待至少 1 个副本确认，最多等 100ms」。**这能降低（不是消除）主从切换丢锁的概率**：如果 `SET` 还没同步就切换了，`WAIT` 会超时返回 0，客户端可以视作加锁失败并重试。**代价是每次加锁多一次同步往返（延迟增加）。**

**Redis 锁 vs ZooKeeper 锁 vs 数据库锁**

| 维度 | Redis 锁 | ZooKeeper 锁 | DB 唯一索引 / `SELECT FOR UPDATE` |
|---|---|---|---|
| 原理 | `SET NX` + TTL | 临时顺序节点 + watch | 唯一约束 / 行锁 |
| 性能 | **高**（内存操作） | 中（写要过半确认） | 低 |
| 一致性 | **弱**（主从切换可能丢锁） | **强**（ZAB 协议，写需过半） | 强（DB 事务保证） |
| 锁释放 | TTL 自动（但可能提前释放） | **会话断开自动删除临时节点**（天然安全） | 事务结束/连接断开自动释放 |
| 阻塞等待 | 要自己轮询（或 Redisson 的 Pub/Sub 通知） | **watch 机制天然支持排队** | `SELECT FOR UPDATE` 天然阻塞 |
| 可重入 | 要自己实现（Redisson 用 Hash） | 要自己实现 | 靠事务 |
| 实现复杂度 | 低 | 中 | 低 |
| 适用 | **高并发、能容忍极小概率失效** | **强互斥、不容忍双持锁** | 单库、低频、强一致 |

**面试选型话术**：「**绝大多数业务用 Redis 锁就够了**，因为它快、实现简单，而且『极小概率的双持锁』在业务上通常可以容忍（比如重复调优只是浪费资源，不会造成数据错误）。**如果业务是『双持锁会导致资金错误』这种级别，就要用 ZooKeeper/etcd 或者数据库的唯一约束**——用性能换确定性。」

**这个判断力的关键**：**不是「Redis 锁不安全所以要用 ZK」，而是「看双持锁的业务后果是否能容忍」。**绝大多数场景能容忍，所以 Redis 锁是主流选择。
:::

:::追问
**Q：锁的 TTL 设 30 秒，业务跑了 40 秒，最后 `unlock` 会发生什么？**
`unlock` 里的 Lua 会先 `GET` 拿到**别人的 value**（因为你的锁已过期、别人重新加了锁），比对失败返回 0。**所以你的锁不会误删别人的锁——这是安全的。**但问题是**互斥已经失效了**：这 10 秒里你和别人同时在执行临界区代码。**所以正确做法是用看门狗续期，或者 TTL 设得足够大（业务 P99 × 2）。**

**Q：Redisson 的 `tryLock(0, -1, SECONDS)` 里 `-1` 是什么？**
`leaseTime = -1` 表示**不指定租期，启用看门狗**（每次续期到 30 秒）。如果传了正数（如 `30`），就**不启用看门狗**，锁固定 30 秒后释放。**这是 Redisson 用户最容易搞错的参数**——很多人以为 `tryLock(0, 30, SECONDS)` 是「锁 30 秒并自动续期」，实际上它意味着「30 秒后无条件释放」。

**Q：`lock.isHeldByCurrentThread()` 这个判断有必要吗？**
**必要。**如果锁已经过期并被别人拿走，`unlock()` 会尝试释放不属于自己的锁——Redisson 内部会因为 `field` 不匹配而抛 `IllegalMonitorStateException`。**`isHeldByCurrentThread()` 先判断一下，避免异常。**这是一个非常实用的细节，面试说出来能看出是真用过而不是背的。

**Q：「Redisson 的看门狗会不会导致锁永远不释放？」**
**不会，但需要理解它的边界**：看门狗只在**客户端进程还活着且定时任务在跑**的情况下续期。如果进程被 kill（SIGKILL）、容器被 OOMKilled、机器掉电 → 定时任务消失 → **锁在最多 30 秒后自动过期**。**这正是 TTL 存在的意义：它保证「锁最终一定会被释放」，哪怕持有者已经不在了。**反过来说，只要你用 Redisson 的看门狗，就**必须接受「客户端活着时锁会一直被续期」**——如果业务真的卡死（死循环），锁会一直被续期，其他客户端永远拿不到。**所以业务侧也要有超时控制。**

**Q：Redisson 还有其他锁吗？**
有，而且都很实用：
- `getFairLock()`：公平锁（按请求顺序排队，用 List/Queue 实现）
- `getReadWriteLock()`：读写锁（读读不互斥、读写互斥）
- `getMultiLock()`：把多个锁组合成一个，要么全拿到要么全失败
- `getSemaphore()` / `getCountDownLatch()`：信号量 / 倒计时门闩
- `getRateLimiter()`：限流器

**但是**：`getFairLock` 的性能比普通锁差（要维护排队队列），`getMultiLock` 更像是 Redlock 的思想但不完全等价。**面试问到了解即可，别主动展开——展开太多容易被追问实现细节。**
:::

:::锚点
**这是你最强的一个点 —— 你有真实的分布式锁使用场景。**

**① 真实场景：rrmcontrol 的调优任务互斥**

你项目里 scheduler **每 60s 触发一次**、**多 pod 部署**，必须用 Redis 锁保证「同一时刻只有一个 pod 真正执行某个场所的调优任务」，否则任务会重复执行、后端计算量翻倍。

面试话术（可以直接用）：「我们的 scheduler 每 60 秒触发一次，服务是多 pod 部署，所以必须做任务互斥，我们用的是 Redis 的 `SET NX PX`。**这里有几个和标准方案不同的设计点：**」

**设计点 1：任务锁的粒度（最重要的判断）**
「我们把锁按**场所**维度拆（`rrm:tuning:lock:{siteId}`），不是一把全局锁。**如果用一个全局锁，所有场所的调优任务会被完全串行化，而 scheduler 是 60 秒触发一次——一旦一个场所的调优跑了 60 秒以上，后面的任务就会堆积。**按场所拆之后，不同场所可以并行调优，只有同一个场所的任务才互斥。」

**设计点 2：抢不到锁的 pod 直接跳过，不等待**
「没抢到锁的 pod **直接跳过本次 tick，不等待重试**。因为任务是周期性的，本 tick 不做下个 tick 还会来。**如果设计成等待，多个 pod 的线程会全部挂在那里，60 秒一次不断堆积，最终把线程池占满。**」

**设计点 3：锁的 TTL 必须覆盖任务最长耗时**
「锁的 TTL 必须大于调优任务的最坏执行时间。**如果 TTL 太短，任务还没跑完锁就过期了，另一个 pod 会拿到锁重复执行同一个调优——这不会造成数据损坏，但会白白浪费一次计算资源，而我们的 rrmcompute 在高量任务并发时是出现过 OOM 的。**所以锁的 TTL 和任务的并发度是有关联的。」

**② 你可以主动关联的一个点：pod 被 kill 时的锁释放**

面试话术：「因为我们多 pod 部署，pod 会滚动更新、被驱逐、被 OOMKilled，**所以进程不一定能执行到 `finally` 里的释放锁**——这是我最关注的一个点。**所以锁的 TTL 是我们的安全网：pod 被杀最多导致锁多占用一个 TTL 周期。**」

**这里可以串上你的真实故障**：「而且我们确实排过 pod 反复重启的问题——rrmcontrol 在国际环境因为 `write after end` 反复重启。**这类『进程生命周期不可预期』的场景，让我在写锁的时候天然会假设『finally 可能没机会执行』，所以 TTL 是必须的，不是可选的。**」**这个论证链条非常有说服力：不是背「TTL 防死锁」，而是从真实故障里推导出为什么必须。**

**③ 诚实边界**：你用的是 Node.js 的 Redis 客户端做的锁，**没有用过 Redisson**。面试时：
- 讲 Node.js 那一侧：你有真实的锁场景和经验，可以展开讲
- 讲 Java 的 Redisson：**明确说「Java 侧的 Redisson 我在补课，看的是看门狗和可重入的实现原理」**，然后把原理讲清楚（看门狗 30 秒、每 10 秒续期、`leaseTime=-1` 才启用、Hash 实现可重入）

**这个「真实的那侧深入讲，补课的那侧讲原理」的策略，比假装两侧都精通安全得多。**

**④ 一个加分细节**：你们用腾讯云 Redis，**主从切换由云厂商自动完成**——所以「主从切换丢锁」对你们不是理论问题，是可能真实发生的。面试话术：「云 Redis 的主从切换我控制不了，所以我们的任务互斥不能只依赖锁本身。**我们还有一层『任务状态校验』：即使两个 pod 同时进入临界区，第二个 pod 执行前会先检查任务状态，发现已经在执行就退出。锁是第一道防线，状态校验是第二道。**」——**「锁 + 状态双保险」是生产级的设计思路**，比单靠锁可靠得多。
:::

---

## 13. Redlock 争议与强互斥方案

:::概念
Redlock = **向 N 个独立的 Redis 实例依次加锁，超过半数成功且总耗时小于锁有效期才算拿到锁**。
争议的核心：**它依赖时钟，而时钟不可信；它没有 fencing token，下游无法拒绝过期持有者。**
记忆钩子：**「Redlock 解决的是『Redis 单点挂了』，但没解决『持锁者以为自己还持锁』——后者才是分布式锁的真正难题。」**
:::

:::提问
- Redlock 是什么？怎么实现的？
- Redlock 有什么问题？为什么有争议？
- 什么场景该用 Redlock，什么场景不该用？
- 有没有比 Redlock 更可靠的方案？
:::

:::答案
### Redlock 的完整算法

```
前提：准备 N 个**完全独立**的 Redis 实例（不是主从，是各自独立的节点），N 通常取 5

加锁流程：
① 记录开始时间 T0
② 依次向 N 个实例发送：
     SET resource_name my_random_value NX PX 30000
   （每个请求都带**很短的超时**，比如 50ms，避免卡在一个实例上）
③ 统计成功数：必须满足
     - 成功数 >= N/2 + 1（最常见的是 3 个）
     - AND 总耗时（T1 - T0）< 锁的有效期（30000ms）
④ 两个条件都满足 → 加锁成功，锁的**实际有效期 = 原有效期 - 加锁耗时**
   否则 → 加锁失败，**必须向所有实例发送删除请求**（包括那些没加上的）
```

**关键点：加锁总耗时要算进锁的有效期里** —— 如果花 2 秒才加到 3 个实例，那锁的剩余有效期只有 28 秒。**这个细节说明设计者意识到了时钟和延迟问题。**

```bash
# 手动模拟 Redlock 的加锁过程（5 个实例，3 个成功即算成功）
for host in 10.11.2.65 10.11.2.66 10.11.2.67 10.11.2.68 10.11.2.69; do
  start=$(date +%s%3N)
  result=$(redis-cli -h $host SET resource:lock "uuid-123" NX PX 30000)
  echo "$host -> $result"
done
# 成功 3 个以上 + 总耗时 < 30000ms → 加锁成功
```

### 争议的完整脉络

**Martin Kleppmann（《Designing Data-Intensive Applications》作者）的批评（2016）**，核心三点：

**① 依赖时钟，而时钟不可信**

Redlock 靠「锁的有效期」来判断安全性。但有效期是基于**各节点自己的时钟**计算的：
- 如果节点 A 的时钟**走得快**，它认为锁已经过期就删掉了 → 而客户端还以为自己持有锁
- NTP 校时、虚拟机时钟漂移、闰秒都可能造成时钟跳变
- Redlock 的官方文档承认了这一点，并建议「不要手动调整系统时钟」——**但这在运维上是不可控的假设**

**② 没有 fencing token（最致命的一点）**

即使锁「同时被两个客户端持有」的概率很小，**一旦发生，下游存储层无法识别谁是过期的持有者**。

**fencing token 方案**：
```
① 每次成功加锁，锁服务返回一个**单调递增的版本号**（fencing token）
② 客户端在写下游存储时**带上这个版本号**
③ 存储层记录「已见过的最大版本号」，**拒绝版本号更小的写请求**
→ 即使两个客户端同时持锁，旧的那个（版本号更小）的写会被存储层拒绝
```

**Redis 的 `SET NX` 不返回版本号** —— 所以要实现 fencing token 得自己在锁服务里维护一个计数器（如 `INCR` 一个全局序号）。**这是 Redis 锁相比 ZooKeeper 的根本劣势**（ZK 的 `zxid`/`cversion` 天然单调递增）。

**③ GC 停顿 / 网络延迟导致「过期但不知道」**

```
时刻   客户端 A
─────────────────────────────────────────
T0     加锁成功（有效期 30s）
T1     ↓ JVM 发生长时间 GC（35 秒）或进程被挂起
T31    锁过期（A 完全不知道，因为它在 STW 中）
T32    客户端 B 加锁成功，开始写共享资源
T33    A 从 GC 中恢复，**依然认为自己在持锁**，继续写共享资源
       → **两个客户端同时写，互斥完全失效**
```

**关键**：客户端没有机制能立即知道「我的锁已经过期了」——它只知道自己设了 30 秒 TTL，但无法感知挂起期间过了多久。**这个问题不是 Redis 特有，ZooKeeper 也有（会话超时），但 ZK 的临时节点会随会话失效自动删除，且客户端能通过会话事件感知。**

**antirez（Redis 作者）的回应**：
- 批评者混淆了「效率型锁」和「正确性型锁」——**Redlock 适合做「效率优化」的锁（避免重复劳动），不适合做「正确性保证」的锁（防止并发写坏数据）**
- 如果你需要「正确性」，就应该用 fencing token，而 fencing token 可以在任何锁之上实现
- 时钟问题可以通过「不和 NTP 抢时钟」等运维手段缓解

### 结论：什么时候用，什么时候不用

| 使用场景 | 推荐方案 | 理由 |
|---|---|---|
| **防重复劳动**（重复执行 = 浪费资源，不会写坏数据） | **单机 Redis 锁（SET NX PX）** 足够 | 即使双持锁，后果只是多跑一次任务 |
| **防重复劳动 + Redis 单点不可接受** | 主从 + 哨兵/集群的 Redis 锁 | 云托管已经保证高可用 |
| **正确性关键**（双持锁会导致数据错误/资损） | **ZooKeeper / etcd（Raft/ZAB，天然强一致）** | 写需要过半确认，且提供版本号 |
| **正确性关键 + 不想引入 ZK** | **fencing token + 存储层校验** | 在任意锁之上都能做，成本更低 |
| **不想引入任何新组件** | **数据库唯一约束 / `SELECT FOR UPDATE`** | 最简单最可靠，性能差但能用 |

**一句话总结**：「**Redlock 在实践中不是主流选择** —— 要高性能就用单机 Redis 锁（配合业务幂等），要强一致就用 ZooKeeper/etcd 或数据库唯一约束。Redlock 处在中间地带：比单机慢（要访问 N 个实例），比 ZK 弱（没有版本号）。」

### ZooKeeper 锁的实现与优势

```
加锁：在 /locks/order 下创建**临时顺序节点** /locks/order/lock-000000001
      获取 /locks/order 的所有子节点，判断自己是不是序号最小的
      - 是 → 拿到锁
      - 不是 → 对「前一个节点」注册 watch，等它删除时被唤醒
解锁：删除自己的临时节点（或会话断开自动删除）
```

**ZK 的优势**：
1. **会话断开自动删除临时节点** —— 客户端进程死了，ZK 感知到会话超时（`sessionTimeout`）后自动删除节点，**不需要靠 TTL 兜底，也没有「TTL 到点但持有者不知道」的问题**（ZK 会通过会话事件通知客户端）
2. **临时顺序节点天然支持排队**（公平锁），不需要轮询
3. **版本号（`cversion`/`zxid`）单调递增** —— 天然支持 fencing token
4. **写需要过半确认**（ZAB 协议），不会出现「主从切换丢锁」

**ZK 的劣势**：
1. **性能低** —— 每次加锁解锁都是一次写操作，需要集群过半确认（几十毫秒）
2. **运维成本高** —— 要多维护一套 ZK 集群（虽然很多人用 K8s 上的 etcd 替代）
3. **sessionTimeout 内的「僵尸客户端」问题** —— 客户端 GC 停顿期间会话超时，节点被删，恢复后同样会「以为自己还持锁」（**和 Redis 是同一个问题**）

**etcd 的优势**（现代替代品）：基于 Raft，租约（lease）+ 事务（txn）实现锁，**有 `mod_revision` 可以做 fencing token**，且运维成本比 ZK 低（K8s 自带 etcd）。
:::

:::拓展
**fencing token 的完整实现（面试能画出来就非常加分）**

```
┌────────────────────────────────────────────────────────┐
│  ① 客户端向锁服务申请锁，锁服务返回 (锁ID, token=10)    │
│                                                        │
│  ② 客户端写存储时带上 token：                          │
│     UPDATE resource SET value='x', token=10            │
│              WHERE id=1 AND token < 10                 │
│                                                        │
│  ③ 存储层：                                            │
│     - 若 current_token=9  → 10 > 9，接受，更新为 10    │
│     - 若 current_token=11 → 10 < 11，**拒绝**           │
│                                                        │
│  结果：即使客户端 A（token=10）在 GC 停顿后以为自己     │
│        还持锁，它的写也会被存储层拒绝                   │
└────────────────────────────────────────────────────────┘
```

**核心思想：把「互斥的判定」从锁服务下移到存储层。** 锁服务只负责「发一个递增号」，真正保证正确性的是存储层的条件更新。**这样即使锁服务本身不可靠，正确性也不受影响。**

**这个方案在你们的技术栈里是可行的** —— MongoDB 的 `findAndModify` / `updateOne` 支持条件更新和版本号字段，可以实现「乐观锁 + 版本号校验」。**面试话术**：「如果我们的调优任务需要更强的互斥保证，我可以在 MongoDB 的任务文档里加一个版本号字段，用条件更新做 CAS——**这样即使两个 pod 同时拿到锁，也只有一个的写会成功。**」

### 「幂等」是分布式锁之外的另一条路

**很多时候，正确的解法不是「加更强的锁」，而是「把操作做成幂等的」。**

| 场景 | 加锁思路 | 幂等思路 |
|---|---|---|
| AP 调优任务重复触发 | 锁保证只有一个 pod 执行 | **任务带上唯一 ID + 执行前检查状态**，重复触发直接跳过 |
| 重复扣款 | 分布式锁 | **订单号做幂等键**，重复请求直接返回上次结果 |
| 重复发通知 | 分布式锁 | **消息 ID 去重表**（`INSERT IGNORE`） |

**幂等的三种实现**：
1. **唯一索引**：`INSERT` 撞唯一约束就失败（最简单可靠）
2. **状态机**：任务状态从 `PENDING` → `RUNNING` 的更新是原子的（`UPDATE ... WHERE status='PENDING'`），影响行数为 0 说明已经被别人领走了
3. **去重表**：用一个「已处理消息 ID」表，处理前先 `INSERT`，冲突就跳过

**面试话术（层次最高的答法）**：「分布式锁解决的是『同一时刻只能有一个执行者』，但它有失效概率。**更根本的解法是让操作本身幂等**——这样即使锁失效导致重复执行，结果也是正确的。**我在做调优任务互斥时是两条腿走路：Redis 锁做第一道防线（避免浪费计算资源），任务状态校验做第二道（保证正确性）。**」
:::

:::追问
**Q：Redlock 到底能不能用？**
**能用，但通常没必要。** 理由：
1. **性能**：要访问 N 个实例，加锁延迟是单机的 N 倍（还要等最慢的那个）
2. **收益不明确**：它解决的是「单个 Redis 实例挂了」，但你如果用的是**哨兵/Cluster/云托管**，本身已经有高可用了——**Redlock 解决的是「Redis 单点」，而现代部署里单点本身就不是常态**
3. **没解决核心问题**：GC 停顿、时钟跳变、缺 fencing token 这些**真正会导致「双持锁」的问题，Redlock 一个都没解决**
4. **运维复杂**：要维护 5 个独立实例

**结论**：**与其上 Redlock，不如用「单机/哨兵 Redis 锁 + 业务幂等 + 状态校验」这个组合。** 这个组合的实现成本更低、可靠性反而更高。

**Q：为什么说「Redlock 和单机 Redis 锁的双持概率其实差不多」？**
因为**两者都会因为 GC 停顿导致双持**（这是主因），而 **Redlock 额外防范的「单机宕机」场景在你用哨兵/云托管时已经不存在了**。所以 Redlock 用 N 倍的延迟和复杂度，换来的边际收益很小。**这是 Kleppmann 批评的核心，也是业界的普遍结论。**

**Q：ZK 的 sessionTimeout 也解决不了 GC 停顿问题，那为什么 ZK 更可靠？**
**因为 ZK 有版本号（zxid/cversion）可以做 fencing token，而 Redis 的 `SET NX` 不返回任何单调递增的标识。** 换句话说：
- **Redis 锁**：双持锁 → 下游无法识别 → **数据错误**
- **ZK 锁**：双持锁（同样可能）→ 但可以用 `zxid` 做版本校验 → **下游拒绝旧持有者 → 数据正确**

**所以「ZK 更可靠」不是因为「它不会双持锁」，而是因为「它提供了解决双持锁后果的工具」。** 这个区分是这道题的真正深度所在，面试官听到会眼前一亮。

**Q：etcd 锁相比 ZK 怎么样？**
现代项目（尤其是 K8s 环境）**更推荐 etcd**：
- **运维成本低**：K8s 集群自带 etcd（但要小心「不要拿 K8s 的 etcd 跑业务」——那是控制面的命脉，业务负载会把控制面拖垮）
- **API 更现代**：gRPC + lease + txn，天然支持租约续期和 CAS
- **有 `mod_revision`**：可以做 fencing token
- **性能比 ZK 好**（Raft vs ZAB，且 etcd 的设计更简洁）

**但要注意**：etcd 的 lease 也是「租约到期自动删除」，**同样有 GC 停顿导致的双持问题**。所以结论还是那句：**要正确性靠 fencing token / 幂等，不要指望锁服务本身。**
:::

:::锚点
**诚实的定位：你没有用过 Redlock，也没有用过 ZooKeeper 锁。**但你有**更好的东西**——一个真实的、双持锁后果**可量化**的业务场景。这是这道题的真正切入点：

**① 你们的双持锁后果是什么？**

面试话术：「我们的调优任务如果两个 pod 同时执行，后果是**重复调优 + 计算资源翻倍**。**这不会写坏数据（因为调优结果是幂等的，后写的覆盖先写的），但会浪费计算资源——而我们的 rrmcompute 在高量任务并发时是出现过 OOM 的。**所以双持锁对我们来说是『性能问题』，不是『正确性问题』。」

**② 基于这个判断，选型结论自然出来了**

面试话术：「**因为双持锁的后果是性能问题而不是数据错误，所以单机 Redis 锁就足够了，不需要 Redlock，也不需要 ZooKeeper。**如果换成『调优结果直接控制硬件参数，重复下发会导致设备震荡』这种场景，那我就必须考虑更强的保证——**这时候我会优先加业务侧的『任务状态校验』而不是换锁组件，因为状态校验比换锁更直接地解决问题。**」

**这个论证链条是本手册里质量最高的一段**，因为它展示了：**识别问题性质（性能 vs 正确性）→ 匹配方案强度 → 优先用业务手段而非技术手段**。这正是面试官想看到的判断力。

**③ 可以主动说的一个细节（真实）**：你们的 Redis 是腾讯云托管，**主从切换由云厂商控制，你们无从干预**。所以：

面试话术：「云 Redis 的主从切换对我们来说是黑盒，所以我们不能假设锁『绝对不会丢』。**我们的做法是接受这个假设：锁是第一道防线，任务状态校验是第二道。**具体就是 —— 即使两个 pod 同时进入临界区，第二个执行前会先查任务状态（状态是 MongoDB 里的），发现是 `RUNNING` 就直接退出。」

**④ 关于 fencing token，你可以关联到 MongoDB**：

面试话术：「fencing token 的思路在我们的技术栈里是可以落地的——**MongoDB 的 `findAndModify` 支持条件更新，我可以在任务文档里放一个自增的版本号，用 `UPDATE ... WHERE version < newVersion` 来做 CAS。**这样即使锁失效，也只有版本号更大的那次写会生效。**我没有在生产实现过，但这个方案在我们现有组件上是可行的，不需要引入新组件。**」

**⑤ 不要做的事**：不要为了显得懂而强行讲 Redlock 的算法细节。**正确策略是：「Redlock 我知道它的算法（N 个实例、过半成功、耗时算进有效期）和它的争议（时钟依赖 + 无 fencing token），但我们的场景不需要它 —— 因为双持锁的后果是性能问题，单机锁足够。」** 这句话讲完就停，**不要再展开**。展开越多越容易在细节上被追着打。
:::

---
## 14. 大 key：发现、安全删除与预防 ★

:::概念
大 key 的危害不在「占用内存多」，而在**「操作它的时候会阻塞 Redis 单线程」**。
记忆钩子：**「大 key 的惩罚不是空间，是时间——它是单线程模型上的一颗定时炸弹，删除、过期、序列化、网络传输都会引爆它。」**
:::

:::提问
- 什么是大 key？怎么定义？
- 为什么不能直接 `DEL` 一个大 key？
- `UNLINK` 和 `DEL` 有什么区别？低版本怎么办？
- 怎么发现大 key？
- 怎么预防大 key？设计上要注意什么？
- 大 key 对持久化有什么影响？
:::

:::答案
### 什么算大 key

**没有官方标准，按「是否会引发问题」来定：**

| 类型 | 经验阈值 | 说明 |
|---|---|---|
| String | value > 10KB（保守 1KB） | 10KB 的 value 在网络传输、AOF 写入上已经明显 |
| Hash / Set / ZSet | 元素数 > 5000（保守 1000） | 元素多 → `HGETALL`/`SMEMBERS` 慢 + 删除慢 |
| List | 元素数 > 10000 | 同上 |
| **任何类型** | **单个 key 占用 > 1MB** | 这是运维层面的红线 |

**更实用的判断标准：如果一个 key 的操作（`HGETALL`/`DEL`/过期）耗时超过 1ms，它就是大 key。**

### 危害清单（面试要能答全）

| 危害 | 机制 |
|---|---|
| **删除阻塞** | `DEL` 要释放几百万元素的内存（`free()` 每个 dictEntry + SDS），主线程完全阻塞，**几百万元素的 Hash 删除可能几秒** |
| **过期阻塞** | `activeExpireCycle` 抽到过期的大 key 时，删除同样阻塞主线程 |
| **淘汰阻塞** | 内存满时淘汰大 key，同样阻塞 |
| **命令阻塞** | `HGETALL` / `SMEMBERS` / `LRANGE key 0 -1` 要构造大回复，O(N) 且内存翻倍 |
| **网络阻塞** | 大 key 的响应包可能几 MB，占满带宽，慢客户端还会撑爆输出缓冲区 |
| **Cluster 数据倾斜** | 一个槽上的大 key 让那个节点成为瓶颈，**加节点也解决不了**（槽是固定的） |
| **持久化开销** | AOF 重写时要把大 key 展开成大量命令；`BGSAVE` 时大 key 的页更容易被写触发 COW |
| **主从同步压力** | 大 key 的复制会产生大包，`client-output-buffer-limit replica` 容易被撑爆 → 从节点断连 → 全量重同步 |
| **fork 时间** | 大 key 所在的页在 fork 后更容易被写 → COW 开销增大 |

### 为什么不能直接 `DEL`（原理解释）

```bash
redis-cli DEL big:hash
# (integer) 1        ← 返回很快？不一定！
```

`DEL` 的流程：
```
① 从 keyspace（db->dict）中摘掉这个 key 的引用  ← 很快，O(1)
② 释放 value 对象的内存
    - 遍历 hashtable 的所有 bucket
    - 逐个 free dictEntry
    - 逐个 free SDS（每个 field + value）
    - 释放整个 hashtable
   ← **这一步在主线程执行，O(N)，几百万元素就是几百万次 free()**
```

**关键：`free()` 本身不快**（jemalloc 要维护元数据、可能要合并空闲块），几百万次 `free()` 累积起来是**几百毫秒到几秒**。而 Redis 是单线程 —— **这期间所有其他客户端的命令全部排队等待**。

```bash
# 实测：构造一个大 Hash 然后删，观察阻塞
redis-cli eval "for i=1,1000000 do redis.call('hset', KEYS[1], 'f'..i, 'v'..i) end return redis.call('hlen', KEYS[1])" 1 big:hash
# 注意：这个 Lua 本身也会阻塞很久，生产绝对不要跑

# 更好的构造方式：用 pipeline
seq 1 1000000 | awk '{print "HSET big:hash f"$1" v"$1}' | redis-cli --pipe

# 然后测删除耗时
redis-cli --latency-history &     # 另开一个终端观察延迟
time redis-cli DEL big:hash       # 观察这个命令的实际耗时
```

### 安全删除方案一：`UNLINK`（4.0+，首选）

```bash
redis-cli UNLINK big:hash
# (integer) 1
```

**`UNLINK` 的原理**：

```
① 主线程：从 keyspace 中摘掉 key 的引用    ← O(1)，立即返回
② 主线程：把 value 对象放进一个「待异步释放」队列
③ 后台线程 bio_lazy_free：从队列里取出来，慢慢 free()  ← 不阻塞主线程
```

**于是 `UNLINK` 的耗时从「O(N) 几秒」变成「O(1) 微秒级」**，内存释放在后台完成。

**配套的 `lazyfree` 配置——让其他删除路径也异步**：

```bash
redis-cli config get lazyfree-lazy-user-del     # no（默认：DEL 不异步）
redis-cli config get lazyfree-lazy-eviction     # no
redis-cli config get lazyfree-lazy-expire       # no
redis-cli config get lazyfree-lazy-server-del   # no

# 全部打开（推荐大内存实例这么配）
redis-cli config set lazyfree-lazy-user-del yes       # DEL 等效 UNLINK
redis-cli config set lazyfree-lazy-eviction yes       # 淘汰时异步释放
redis-cli config set lazyfree-lazy-expire yes         # 过期时异步释放
redis-cli config set lazyfree-lazy-server-del yes     # RENAME 等隐式删除时异步
redis-cli config set lazyfree-lazy-user-flush no      # FLUSHALL/FLUSHDB（8.0 默认已改 yes）
redis-cli config rewrite
```

**`lazyfree-lazy-user-del yes` 的副作用**：`DEL` 不再保证「命令返回时内存已释放」。所以「删了 key 内存没降」是正常的（后台还在释放）。**要有监控配合，否则会误判为内存泄漏。**

**查看后台释放线程的情况**：
```bash
redis-cli info stats | grep lazyfree
# lazyfree_pending_objects:12345     ← 待释放的对象数，持续不降说明释放速度跟不上
redis-cli info memory | grep lazyfree_pending_objects
```

### 安全删除方案二：低版本（4.0 以下）分批渐进删除

**核心思想：把一次 O(N) 的删除拆成 N 次 O(1) 的小删除，每次删一小批，批间留出时间让主线程处理其他请求。**

```bash
# ① Hash —— HSCAN 游标迭代 + HDEL 批量删除
#!/bin/bash
KEY="big:hash"
CURSOR=0
while true; do
  # HSCAN 返回：游标 + 一批 field
  REPLY=$(redis-cli HSCAN "$KEY" $CURSOR COUNT 500)
  CURSOR=$(echo "$REPLY" | head -1)
  FIELDS=$(echo "$REPLY" | tail -n +2)

  if [ -n "$FIELDS" ]; then
    # 用 xargs 构造 HDEL 命令
    echo "$FIELDS" | xargs redis-cli HDEL "$KEY" > /dev/null
  fi

  [ "$CURSOR" = "0" ] && break
  sleep 0.01        # ★ 关键：让出时间片，给主线程喘息
done
redis-cli DEL "$KEY"    # 此时集合已空，DEL 是 O(1)
```

```bash
# ② Set —— SSCAN + SREM
CURSOR=0
while true; do
  REPLY=$(redis-cli SSCAN big:set $CURSOR COUNT 500)
  CURSOR=$(echo "$REPLY" | head -1)
  MEMBERS=$(echo "$REPLY" | tail -n +2)
  [ -n "$MEMBERS" ] && echo "$MEMBERS" | xargs redis-cli SREM big:set > /dev/null
  [ "$CURSOR" = "0" ] && break
  sleep 0.01
done
redis-cli DEL big:set

# ③ ZSet —— ZSCAN + ZREM
#    （或者用 ZREMRANGEBYRANK / ZREMRANGEBYSCORE 按范围批量删，更快）
CURSOR=0
while true; do
  REPLY=$(redis-cli ZSCAN big:zset $CURSOR COUNT 500)
  CURSOR=$(echo "$REPLY" | head -1)
  MEMBERS=$(echo "$REPLY" | tail -n +2 | awk 'NR%2==1')   # 奇数行是 member
  [ -n "$MEMBERS" ] && echo "$MEMBERS" | xargs redis-cli ZREM big:zset > /dev/null
  [ "$CURSOR" = "0" ] && break
  sleep 0.01
done
# 更优的 ZSet 删法：按排名范围批量删，每次删 500 个
# redis-cli ZREMRANGEBYRANK big:zset 0 499     ← 反复执行直到删空
```

```bash
# ④ List —— LTRIM 从两端截断（最优雅，因为 List 只能从两端操作）
redis-cli LLEN big:list
# 每次保留后面 N 个，前面的自动释放
while [ "$(redis-cli LLEN big:list)" -gt 1000 ]; do
  redis-cli LTRIM big:list 1000 -1      # 只保留第 1000 个之后的部分
  sleep 0.01
done
redis-cli DEL big:list

# 或者用 LPOP/RPOP 带 count 参数（6.2+），一次弹一批
# redis-cli LPOP big:list 500
```

```bash
# ⑤ String —— 直接 DEL 一般可接受
# String 的释放是「一次 free 一整块内存」，不像集合要遍历几百万元素
# 但如果 value 极大（几十 MB），也建议先 SET 成小值再 DEL（让大块内存即时释放）
redis-cli SET big:string "x"     # 覆盖成 1 字节，原来那块内存立即释放
redis-cli DEL big:string
```

### 安全删除方案三：`RENAME` + 后台慢删（最优雅）

**核心思路：先让 key 从业务视角「消失」，再把实际删除放到后台慢慢做。**

```bash
# ① 原子重命名：业务侧立刻看不到这个 key（O(1)）
redis-cli RENAME big:hash big:hash:deleting:1758170000
# 注意：RENAME 本身在 key 已存在时是 O(1)，但如果目标 key 存在会先删目标
# 更安全的是用「不存在的目标名」（带时间戳/随机数）

# ② 后台脚本慢慢删（不影响业务）
# 用上面的 HSCAN + HDEL 循环删 big:hash:deleting:1758170000
```

**为什么这是最优方案**：业务方对「key 消失」的感知是**立即的**（`RENAME` 是 O(1) 原子操作），而真正的删除压力被推迟到后台。**这跟「先摘引用、后释放内存」是同一个思想，只是用业务手段在 4.0 之前实现了 `UNLINK` 的效果。**

**注意 `RENAME` 的坑**：如果目标 key 已经存在，`RENAME` 会**删除目标 key**（而删除大目标 key 同样会阻塞）。所以目标名一定要用「带时间戳/随机数」的、大概率不存在的名字。

### `EXPIRE` 惰性删除的局限

**很多人以为「给大 key 设个 TTL 就安全了」——错。**

```bash
redis-cli EXPIRE big:hash 60
# 60 秒后：activeExpireCycle 随机采样抽到它 → 触发删除 → **同样是 O(N) 阻塞**
```

**关键区分**：
- `EXPIRE` 只是**标记**了过期时间，删除动作仍然由惰性删除/定期删除触发
- **定期删除的采样本身是随机的**，所以大 key 过期时同样会产生一次阻塞，只是时间点不确定
- **唯一能缓解的是 `lazyfree-lazy-expire yes`** —— 它让「过期删除」也走异步释放路径（把 value 丢给后台线程 free）

**结论**：`EXPIRE` **不是**大 key 的解决方案，`lazyfree-lazy-expire yes` 才是。

### 怎么发现大 key

**方法一：`redis-cli --bigkeys`（最常用）**

```bash
redis-cli --bigkeys
# ------- summary -------
# Sampled 1234567 keys in the keyspace!
# Total key length in bytes is 23456789 (avg len 19.00)
#
# Biggest string found 'user:1001:profile' has 102400 bytes
# Biggest list   found 'queue:tasks' has 50000 items
# Biggest hash   found 'site:1001:aps' has 3000000 fields
# Biggest set    found 'tags:all' has 120000 items
# Biggest zset   found 'rank:global' has 800000 members
#
# 1 strings with 102400 bytes (0.00% of keys, avg size 102400.00)
# ...
```

**原理和局限（重要）**：
- 用 `SCAN` 遍历全库 + 对每个 key 做 `STRLEN` / `LLEN` / `HLEN` / `SCARD` / `ZCARD`
- **只统计「元素个数」，不统计「字节大小」** —— 一个 100 万字段的 Hash 和一个 100 万字段的 Hash（每字段 1MB）看起来一样大
- **只找每类型最大的一个**（`--bigkeys` 的局限），不能列出 Top N
- **会遍历全库**，对大实例有压力（但用 `SCAN`，不是 `KEYS`，相对安全）
- **对从节点执行**同样是遍历，建议在从节点或低峰期跑

```bash
# 变体
redis-cli --bigkeys -i 0.1        # 每扫描 100 个 key 休息 0.1 秒（降低压力，推荐生产用）
redis-cli --memkeys               # 6.0+：按「内存占用」找最大的 key（比 --bigkeys 更准）
redis-cli --memkeys -i 0.1
```

**方法二：`MEMORY USAGE`（精确但要知道 key 名）**

```bash
redis-cli MEMORY USAGE big:hash
# (integer) 105383968              ← 字节数，约 100MB

redis-cli MEMORY USAGE big:hash SAMPLES 0    # SAMPLES 0 = 精确计算（慢）
redis-cli MEMORY USAGE big:hash SAMPLES 5    # 采样估算（默认 5，快）
```

**局限**：只能查**已知 key 名**的 key，不能用来「发现」大 key。适合「怀疑某个 key 大」时验证。

**方法三：`DEBUG OBJECT`（看序列化长度）**

```bash
redis-cli DEBUG OBJECT big:hash
# Value at:0x7f... refcount:1 encoding:hashtable serializedlength:105383968 lru:...
#                                                             ^^^^^^^^^^^^^ 序列化后的字节数
redis-cli DEBUG OBJECT big:hash | grep -o "serializedlength:[0-9]*"
```

**注意**：`DEBUG OBJECT` 是 `serializedlength`（RDB 编码后的长度），**和实际内存占用不完全一致**（实际内存还包含 hashtable 的桶、指针开销）。而且 `DEBUG` 命令在生产通常被禁用（`enable-debug-command`）。**它每次都要序列化整个对象，本身就很慢 —— 慎用。**

**方法四：RDB 离线分析（最安全，推荐生产用）**

```bash
# ① 从从节点或备份拿到 RDB 文件
# ② 用 rdb-cli（Go 版，快）分析，完全不占用线上资源
rdr keys dump.rdb --memory > all-keys.csv
sort -t',' -k2 -rn all-keys.csv | head -20      # 按内存排序取 Top 20 大 key

# ③ 或者用 redis-rdb-tools（Python 版）
rdb -c memory dump.rdb --bytes 10240 -f memory.csv    # 找 > 10KB 的 key
rdb -c justkeys dump.rdb -f keys.txt
rdb -c json dump.rdb -f all.json
```

**优势**：**零线上压力**、可以反复分析、能看到精确的内存占用和元素个数。**这是排查大 key 的首选方法**（前提是能拿到 RDB 文件，云 Redis 通常能从控制台下载备份）。

**方法五：监控告警（治本）**

```bash
# redis_exporter + Prometheus + Grafana
# 告警规则示例（PromQL）
# redis_memory_used_bytes / redis_memory_max_bytes > 0.8
# rate(redis_evicted_keys_total[5m]) > 0
# redis_keyspace_hits_total / (hits + misses) < 0.9

# 或者定期跑 --bigkeys 并把结果写进监控
```

### 怎么预防大 key（设计层面，最重要）

| 手段 | 具体做法 | 适用 |
|---|---|---|
| **拆 key（按业务维度）** | 一个 Hash 存 100 万字段 → 按用户 ID 取模拆成 100 个 Hash（`site:1001:aps:0` ~ `:99`） | Hash/Set/ZSet 元素数过大 |
| **排行榜保 Top N** | `ZREMRANGEBYRANK key 0 -1001` 只保留前 1000 名 | ZSet 排行榜无限增长 |
| **列表定长** | `LPUSH` + `LTRIM 0 999` 只保留最近 1000 条 | List 存最新记录 |
| **设 TTL** | 所有缓存 key 都带过期时间（含随机抖动） | 通用 |
| **压缩 value** | value 用 gzip / protobuf / MessagePack 序列化 | String value 过大 |
| **限制单 key 大小** | 写入前校验，超过阈值拒绝并告警 | 通用（业务侧兜底） |
| **不要用 `HGETALL`** | 改用 `HSCAN` 游标迭代 / `HMGET` 取指定字段 | 读路径 |
| **`OBJECT ENCODING` 巡检** | 定期检查关键 key 的编码，确认没发生 listpack → hashtable 的意外升级 | Hash/ZSet |

**「拆 key」的具体实现（业务侧）**：

```java
/** 把一个大 Hash 按 user 维度拆成 100 个分片 */
private String shardKey(String prefix, long userId, int shardCount) {
    int shard = (int) (userId % shardCount);
    return prefix + ":" + shard;
}

// 写：hset site:{siteId}:aps:{shard} apSn value
// 读单个：只用算一次分片，O(1)
// 读全部：要遍历 100 个分片（这是拆分的代价）—— 但通常业务不需要读全部
```

**拆分的取舍**：**拆分把「单次 O(N) 操作」变成「N 次小操作」，代价是「需要全量读取时要遍历所有分片」。** 所以要按「业务是否真的需要全量读」来决定。**如果业务只需要按维度读单个元素，拆分是纯赚的。**

### 大 key 对持久化的影响

| 影响 | 机制 | 缓解 |
|---|---|---|
| **AOF 重写变慢** | 大 key 要展开成大量命令写入新 AOF，且 `aof_rewrite_buf` 期间如果又修改了大 key，缓冲区会很大 | 避免修改大 key；分批写 |
| **AOF 文件膨胀** | 一个大 key 在 AOF 里可能是几百万条命令（`HSET` 每字段一条，虽然重写时会合并） | 重写 + 混合持久化 |
| **BGSAVE 的 COW 开销** | 大 key 占的页多，fork 后被写的概率大 → COW 内存增长快 | 拆分大 key；监控 `rdb_last_cow_size` |
| **主从同步** | 大 key 的复制产生大包，可能撑爆 `client-output-buffer-limit replica`（默认 256MB 硬限） → 从节点断连 → 全量重同步 | 拆分；调大 buffer limit；避免在同步期间写大 key |

```bash
# 主从同步缓冲区的限制（超限会强制断开从节点）
redis-cli config get client-output-buffer-limit
# normal 0 0 0
# slave 268435456 67108864 60
#       ^^^^^^^^^^ 硬限 256MB   ^^^^^^^^ 软限 64MB 持续 60 秒
# 8.0 起 "slave" 改名为 "replica"
redis-cli config get client-output-buffer-limit replica
```

**一个真实场景**：如果从节点同步期间主节点正在写一个大 key（比如 `HSET big:hash` 里插入一个 1MB 的 value），这个命令会原样复制给从节点。**如果从节点网络慢，缓冲区积压，超过 256MB 就会被主节点强制断开 → 触发全量重同步 → 又一轮 fork + RDB 传输 → 雪上加霜。** 这是「大 key + 主从」的经典恶性循环。
:::

:::拓展
**大 key 的「业务化」定义**

不要死记「10KB」「5000 个元素」，**要按「操作耗时」和「业务影响」定义**：

```
大 key = 对它做一次 O(N) 操作会阻塞主线程超过 X 毫秒的 key
```
X 取多少取决于业务对延迟的容忍度。**如果一个 key 的 `DEL` 耗时超过 10ms，它就已经在拖慢所有请求了。**

**一个极其常见的隐性大 key：`keyspace notification` 相关**

如果开了键空间通知（`notify-keyspace-events`），每个 key 的事件都要发布到 Pub/Sub。大 key 上的批量操作（如 `HDEL` 一批）会产生大量事件 → 事件风暴。**这个坑很少人提，但真实存在。**

**另一个隐性大 key：慢查询日志里的常客**

```bash
redis-cli SLOWLOG GET 10
# 1) (integer) 12345
#    (integer) 1758170001
#    (integer) 253000            ← 耗时 253ms！
#    (array) 1) "HGETALL" 2) "site:1001:aps"
```

**如果慢查询日志里反复出现同一个 key，那它一定是大 key。**这是「从现象反推原因」的一条捷径 —— 不用预先知道哪个 key 大，慢查询日志会告诉你。

**大 key 的自动化治理**（Java / Spring 侧）

```java
// 写入前校验（业务侧兜底）
public void hsetWithGuard(String key, String field, String value) {
    if (value != null && value.length() > 10 * 1024) {
        log.error("value 过大，拒绝写入: key={}, field={}, size={}",
                  key, field, value.length());
        throw new IllegalArgumentException("value 超过 10KB 限制");
    }
    Long size = redisTemplate.opsForHash().size(key);
    if (size != null && size > 5000) {
        log.error("Hash 元素数超限: key={}, size={}", key, size);
        throw new IllegalStateException("Hash 超过 5000 字段限制");
    }
    redisTemplate.opsForHash().put(key, field, value);
}
```

**注意**：`opsForHash().size()` 每次写都多一次网络往返，**生产上更推荐用「监控 + 告警 + 定期巡检」而不是每次写都校验**。上面这段代码适合关键路径，或者在容量已经稳定后下线。**这是个明确的取舍点，面试可以说出来。**
:::

:::追问
**Q：`UNLINK` 是立即删除了吗？会不会有「删了但还能读到」的问题？**
`UNLINK` 在**逻辑上立即删除**（key 从 keyspace 摘掉，后续 `GET` 返回 nil），**物理内存异步释放**。所以对业务来说，`UNLINK` 和 `DEL` 的可见行为**完全一致**，区别只在「内存什么时候真正归还给操作系统」。**这也是为什么 `lazyfree-lazy-user-del yes` 是安全的配置**——它不改变语义，只改变内存释放的时机。

**Q：主从复制的情况下，`UNLINK` 是怎么传播的？**
主节点执行 `UNLINK` 后，**向从节点传播的是 `DEL`**（因为从节点的内存释放由它自己处理，不需要让主节点同步「异步释放」这个行为）。所以从节点收到的是 `DEL` —— **意味着从节点仍然可能因为删除大 key 而阻塞**。这是一个容易被忽略的细节：**异步删除只在执行 `UNLINK` 的那个节点生效。**

**Q：`FLUSHALL` 会不会阻塞？**
会，而且是最严重的阻塞之一。Redis 4.0 起支持 `FLUSHALL ASYNC` / `FLUSHDB ASYNC`（异步释放，把整个 db 的 dict 丢给后台线程）。**8.0 起 `lazyfree-lazy-user-flush` 默认改为 yes**，也就是 `FLUSHALL` 默认就是异步的。**低版本上，`FLUSHALL` 一个 10GB 的实例可能阻塞好几秒。**

**Q：怎么在 Cluster 里找大 key？**
`redis-cli --cluster` 没有直接的 `--bigkeys`。做法是 **逐个节点跑**：

```bash
for node in 10.11.2.65:6379 10.11.2.66:6379 10.11.2.67:6379; do
  echo "===== $node ====="
  redis-cli -h ${node%:*} -p ${node#*:} --bigkeys -i 0.1
done
```

**更大的问题是 Cluster 下的数据倾斜**：一个大 key 只能落在一个槽上、一个节点上。所以 Cluster 里找大 key 的目的不只是「避免阻塞」，还是「避免某个节点的负载远高于其他节点」。**而拆 key 在 Cluster 下尤其重要**——因为拆分后的分片会自动分散到不同节点（只要分片 key 的哈希值落在不同槽上）。
:::

:::锚点
**这段你要非常克制，因为你没有真实的大 key 故障案例。**但你有两个强关联可以讲：

**① 你排查过「内存超预算」的故障 —— rrmcompute OOM（5Gi → 5.5GiB）**

面试话术：「我没有处理过 Redis 的大 key 故障，但我处理过**内存超预算**的故障 —— rrmcompute 现网 OOM 反复重启，最后内存从 5Gi 调到 5.5GiB。**这两件事的根源是同一个：资源占用超出预期，而且不是一次性超标，是慢慢积累然后突然爆掉。**」

**这个类比的杀伤力在于**：「大 key 也是这样 —— 它不是突然出现的，是某个 Hash 从 128 个字段慢慢涨到 300 万字段。**所以排查思路也一样：不看配置，看实时的数字（内存曲线、key 的规模分布），找到增长最快的那一个。**」

**② 你的 RRM 业务里有天然的大 key 风险点 —— 场所 × AP 的聚合数据**

面试话术（这段是真正的业务判断）：「我们的业务模型里有一个天然的『大 key 蓄水池』风险：**一个场所下面可能有几千个 AP，如果我把某个场所的所有 AP 状态存在一个 Hash 里（`site:1001:aps`），那大场所的 Hash 会非常大 —— 字段数上万、单 key 可能几 MB。** 这会导致三个问题：① `HGETALL` 慢；② 删除时阻塞；③ **在 Cluster 里这个 key 只能落在一个节点上，造成数据倾斜。**」

**对应的设计**：「所以按我们的模型，**应该按场所 ID 做二次分片**（比如 `site:1001:aps:0` ~ `:9`），把单个 key 的规模控制在几百个字段以内。**代价是『要读某个场所的全部 AP 时得遍历 10 个分片』——但我们的业务通常只需要按 AP 维度读单个，所以这个代价可以接受。**」

**③ 讲「预防」而不是「治理」**

面试话术：「我的理解是**大 key 的最优解是设计时就不产生它**，而不是事后治理。**因为治理方案（`UNLINK`、分批删、`RENAME` 后台删）都是补救手段，而拆分是根治**。所以如果让我 review 一个新的 Redis 使用场景，我会先问三个问题：**这个 key 的元素数量上限是多少？会不会随时间无限增长？需要全量读取吗？** 这三个问题的答案决定了 key 的结构设计和是否需要分片。」

**④ Java 侧的补课点**：`RedisTemplate` 的 `opsForHash().entries(key)` 等价于 `HGETALL`，`opsForList().range(key, 0, -1)` 等价于 `LRANGE key 0 -1`——**这两个 API 是大 key 最容易踩雷的地方**，因为写起来很自然，但它们会把整个集合拉到内存里。**正确做法是用 `scan` 系列**（Spring Data Redis 提供 `scan` API，但要自己处理游标）：

```java
// 不要这样用（大 key 会炸）
Map<Object, Object> all = redisTemplate.opsForHash().entries(bigKey);

// 用 scan 游标迭代
ScanOptions options = ScanOptions.scanOptions().count(500).match("f*").build();
try (Cursor<Map.Entry<Object, Object>> cursor =
         redisTemplate.opsForHash().scan(bigKey, options)) {
    while (cursor.hasNext()) {
        Map.Entry<Object, Object> entry = cursor.next();
        // 处理单个 entry
    }
}   // ★ Cursor 必须关闭，否则连接泄漏
```

**注意 `Cursor` 必须 close** —— 又是一个资源生命周期问题。**你们 rrmcontrol 的 `write after end` 就是资源生命周期管理缺陷，这个类比可以串起来。**
:::

---

## 15. 主从复制（全量同步与增量同步）

:::概念
复制分两种：**全量同步**（从节点第一次连接，主节点 `BGSAVE` 出 RDB 发过去）和**增量同步**（断线重连后只补发缺的那部分，靠 `repl_backlog` 环形缓冲区）。
记忆钩子：**「`runid` + `offset` 是复制的身份证；backlog 是最近一段时间的录像带——录像带里有就补发，没有就重来一遍全量。」**
:::

:::提问
- Redis 主从复制怎么工作的？
- 全量同步和增量同步分别是什么时候发生的？
- 什么是 `repl_backlog`？它的大小怎么定？
- 主从延迟怎么排查？
- 从节点会主动删除过期 key 吗？
:::

:::答案
### 建立复制与同步流程

```bash
# 从节点发起（两种写法，replicaof 是 5.0+ 的新名字）
redis-cli REPLICAOF 10.11.2.65 6379
# 老写法（仍支持）
redis-cli SLAVEOF 10.11.2.65 6379

# 取消复制，变成独立节点
redis-cli REPLICAOF NO ONE

# 常用配置
redis-cli config get replica-read-only       # yes（从节点默认只读）
redis-cli config get repl-backlog-size       # 1048576（1MB，默认偏小！）
redis-cli config get repl-backlog-ttl        # 3600
redis-cli config get repl-diskless-sync      # yes（6.0+）
redis-cli config get repl-diskless-sync-delay # 5
redis-cli config get repl-timeout            # 60
redis-cli config get repl-ping-replica-period # 10
redis-cli config get min-replicas-to-write   # 0
redis-cli config get min-replicas-max-lag    # 10
```

### 全量同步（第一次连接 / 无法增量）

```
从节点                                    主节点
  │                                         │
  │──① PSYNC ? -1 ─────────────────────────>│   （? -1 表示「我没有主节点信息」）
  │                                         │
  │<─② +FULLRESYNC <runid> <offset> ────────│   告诉从节点：我的 runid 和当前 offset
  │                                         │
  │                                         │──③ BGSAVE，生成 RDB
  │                                         │   （期间的新命令写入 replication buffer）
  │<─④ RDB 文件（或 diskless 走 socket）────│
  │                                         │
  │  ⑤ 从节点：清空自己的数据 → 加载 RDB      │
  │                                         │
  │<─⑥ replication buffer 里积压的写命令─────│
  │  ⑦ 从节点：执行这些命令，追平 offset      │
  │                                         │
  │──⑧ REPLCONF ACK <offset> 每秒上报一次──>│   持续的心跳 + 进度上报
  │<─⑨ 持续传播写命令（流式）────────────────│
```

**关键点**：
- **`runid`**：主节点的唯一标识（40 位随机十六进制）。从节点记住它，重连时上报，主节点用它判断「是不是同一个主节点」。
- **`offset`**：复制流的字节偏移量，**单调递增**。主从的 offset 差就是「延迟了多少字节」。
- **第 ⑥ 步的 replication buffer**：**每个从节点一个独立的缓冲区**（不是共享的），因为不同从节点的进度不同。这个缓冲区的上限由 `client-output-buffer-limit replica` 控制（默认硬限 256MB），**超限会强制断开从节点**。

**`diskless` 模式（6.0+ 默认）**：主节点 fork 出子进程后**直接把 RDB 写进从节点的 socket**，不落磁盘。省掉一次写盘 + 一次读盘。`repl-diskless-sync-delay 5` 表示「等 5 秒，看有没有其他从节点也要同步，一起做」——避免每个从节点都 fork 一次。

### 增量同步（断线重连）

**核心结构：`repl_backlog`（复制积压缓冲区）**

```
repl_backlog 是一个**固定大小的环形缓冲区**，主节点把最近传播的写命令都写进去，
并记录每个字节对应的 offset。

┌──────────────── repl_backlog (repl-backlog-size = 1MB) ─────────────────┐
│  已覆盖（被新数据覆盖，无法补发）  │  仍然保留的命令（可以补发）          │
└────────────────────────────────────────────────────────────────────────┘
                                    ↑                      ↑
                            repl_backlog_off      master_repl_offset（最新）
```

**断线重连的流程**：

```
从节点重连：PSYNC <runid> <从节点的offset>

主节点判断：
  ① runid 不一致？          → 全量同步（换了主节点）
  ② offset 不在 backlog 范围？→ 全量同步（缺的数据已经滚出缓冲区）
  ③ 都在？                   → **增量同步**，返回 +CONTINUE
                              只发 offset 之后的那部分命令
```

**所以 `repl-backlog-size` 决定了「断线多久内能增量同步」**：

```
需要的 backlog 大小 ≈ 平均写入速率(字节/秒) × 最长可容忍的断线时长(秒)

例：主节点写入速率 1MB/s，希望断线 60 秒内能增量同步
    → 需要 1MB/s × 60s = 60MB
    → 再加一倍余量 → 设 repl-backlog-size 128mb
```

**默认的 `1mb` 太小了** —— 一个写入 1MB/s 的实例，只要断线 1 秒以上就得全量重同步。**这是很多「从节点频繁全量重同步」问题的根因。**

```bash
# 检查 backlog 的实际使用情况
redis-cli INFO replication
# master_repl_offset:12345678
# repl_backlog_active:1
# repl_backlog_size:1048576
# repl_backlog_first_byte_offset:11337091
# repl_backlog_histlen:1008588
#                     ^^^^^^^^^ 已使用字节数，接近 size 就要调大！
```

**调大 backlog**：
```bash
redis-cli CONFIG SET repl-backlog-size 128mb
redis-cli CONFIG REWRITE
# 注意：调大后需要**从节点重新全量同步一次**才会生效（因为 backlog 是重新分配的）
```

### `INFO replication` 全部关键字段

```bash
# 主节点视角
redis-cli INFO replication
# role:master
# connected_slaves:2
# slave0:ip=10.11.2.66,port=6379,state=online,offset=12345678,lag=0
# slave1:ip=10.11.2.67,port=6379,state=online,offset=12345600,lag=1
#                                    ^^^^^^^^^^^^^^^^^^     ^^^^^^
#                                    offset 差 78 字节         延迟 1 秒
# master_failover_state:no-failover
# master_replid:8371b4fb1155b71f4a04d3e1bc3e18c4a990aeeb
# master_replid2:0000000000000000000000000000000000000000
# master_repl_offset:12345678
# second_repl_offset:-1
# repl_backlog_active:1
# repl_backlog_size:1048576
# repl_backlog_first_byte_offset:11337091
# repl_backlog_histlen:1008588

# 从节点视角
redis-cli INFO replication
# role:slave
# master_host:10.11.2.65
# master_port:6379
# master_link_status:up                ← **最关键：up 才是正常的**
# master_last_io_seconds_ago:0
# master_sync_in_progress:0
# slave_repl_offset:12345600
# slave_priority:100
# slave_read_only:1
# connected_slaves:0
# master_failover_state:no-failover
# master_replid:8371b4fb...
# master_repl_offset:12345678
# slave_repl_offset:12345600
# slave_read_only:1
```

**排查主从延迟的公式**：
```
延迟字节数 = master_repl_offset - slave_repl_offset
延迟时间   ≈ 延迟字节数 / 写入速率
```

### 主从延迟的原因

| 原因 | 说明 | 处置 |
|---|---|---|
| **网络带宽不足** | 复制流量占满带宽 | 提升带宽；避免在同步期间做大批量写 |
| **从节点执行慢** | 从节点 CPU 弱、或有大 key 操作 | 从节点配置不低于主节点 |
| **主节点写入量激增** | 大批量导入、`FLUSHALL` 后重建 | 错峰；用 pipeline 控制速率 |
| **从节点阻塞** | 从节点上的慢查询 / 大 key 删除 / fork | 从节点也要治理大 key |
| **`repl-backlog` 太小** | 频繁全量重同步（每次都要 fork + 传输 RDB） | **调大 `repl-backlog-size`** |
| **单线程复制** | 从节点应用命令是单线程的 | 无法改变（这是 Redis 的设计） |

### 从节点与过期 key（高频追问）

```
主节点发现 key 过期（惰性删除 or 定期删除）
   ↓
向从节点**显式传播一条 DEL 命令**
   ↓
从节点执行 DEL
```

**关键规则**：
1. **从节点不主动删除过期 key** —— 它只是被动等主节点的 `DEL`
2. **从节点读过期 key 时会返回 nil**（3.2+）—— 这是「逻辑判断」而不是「物理删除」。所以从节点上那份数据还在（占内存）
3. **3.2 之前从节点会返回过期数据** —— 这是历史 bug，已修复

**现象**：从节点的 `used_memory` 可能**高于**主节点，且 `expired_keys` 为 0（或很小）。这是正常的，不是故障。

**为什么这么设计**：保证主从数据一致。如果从节点自己删了，主节点还没删，那从节点的 `dbsize` 会比主节点小 —— 数据就不一致了。**「删除权收归主节点」是保证一致性的必要设计。**

**隐患**：如果主节点因为某些原因（比如从节点不知道的过期策略差异）没发 `DEL`，从节点的内存会持续高于主节点。这种情况极少，但出现过。
:::

:::拓展
**`replication buffer` vs `repl_backlog` —— 两个容易混淆的缓冲区**

| | `replication buffer` | `repl_backlog` |
|---|---|---|
| 数量 | **每个从节点一个** | 全局一个（所有从节点共享） |
| 作用 | 全量同步期间积压的新命令（RDB 还没传完） | 断线重连时判断能否增量同步 |
| 大小限制 | `client-output-buffer-limit replica`（默认硬限 256MB） | `repl-backlog-size`（默认 1MB） |
| 超限后果 | **强制断开从节点** | 无法增量 → 全量重同步 |
| 生命周期 | 从节点连上就创建，断了就销毁 | 有一个从节点就存在 |

**这两个缓冲区是「全量重同步」问题的两个入口**：
- `replication buffer` 超限 → 从节点被踢 → 重连 → 可能又超限 → **循环**
- `repl_backlog` 太小 → 断线后无法增量 → 全量同步 → `replication buffer` 又积压

**调优建议**：大写入量的实例，**两个都要调大**：
```bash
redis-cli CONFIG SET repl-backlog-size 128mb
redis-cli CONFIG SET client-output-buffer-limit "replica 512mb 128mb 60"
```

**`min-replicas-to-write`：防止脑裂丢数据**

```bash
redis-cli config get min-replicas-to-write    # 0（默认关闭）
redis-cli config get min-replicas-max-lag     # 10（秒）
```

**脑裂场景**：
```
主节点与从节点/哨兵网络分区 → 主节点仍然接受写入
                              ↓
                        哨兵在另一侧把从节点提升为新主
                              ↓
                        分区恢复后，旧主变成从节点 → **它在分区期间写的所有数据被丢弃**
```

**`min-replicas-to-write 1` 的含义**：如果**可用的从节点数量少于 1 个，主节点拒绝写入**。配合 `min-replicas-max-lag 10`（从节点延迟超过 10 秒就不算「可用」）。

**这样分区期间的旧主节点就不能写入了**（因为它看不到从节点）→ 不会产生「被丢弃的写」→ 数据更安全。

**代价**：如果从节点全部挂掉，主节点也**变成不可写**（哪怕主节点自己是健康的）。这是**「可用性换数据安全」的明确取舍**——高写入量的业务要谨慎开启。

**`WAIT` 命令：按需等待副本确认**

```bash
redis-cli SET important:key "value"
redis-cli WAIT 1 100
# (integer) 1        ← 1 个副本在 100ms 内确认了
# 参数：WAIT numreplicas timeout(ms)
```

`WAIT` 是**同步等待**（阻塞当前客户端），不会改变复制的异步本质，只是让**这一次写**知道「有没有被复制出去」。**用于对单次写有强可靠性要求的场景**（如分布式锁加锁后等待同步）。

**局限**：`WAIT` 只保证「此刻有 N 个副本收到了」，**不保证这些副本以后不会挂**。所以它不是强一致的保证，只是提高可靠性。**antirez 自己也强调：`WAIT` 用于提升可靠性，不构成强一致。**
:::

:::追问
**Q：全量同步时，从节点会清空自己的数据吗？**
会。从节点加载 RDB 前会执行 `FLUSHALL`（清空自己的数据），然后加载 RDB。**所以从节点的内存会先降后升**（先清空，再加载）。这个过程中从节点**处于 `loading` 状态，不响应请求**。**这是从节点扩容/重建时的一个可用性窗口。**

**Q：`runid` 变了会怎样？**
从节点上报 `runid` 后，主节点发现和自己的 `master_replid` 不一致 → **直接全量同步**。所以：
- **主节点重启**（即使数据没丢）→ `runid` 会变（除非配置了 `replid` 持久化）→ 所有从节点全量重同步
- **主从切换**（哨兵/Cluster 提升新主）→ 新主的 `runid` 是新的 → 其他从节点要和新主全量同步

**优化手段**：Redis 4.0 引入了 `master_replid2`（记录第二个 replid）—— 主从切换后，新主会继承旧主的 replid 到 `replid2`，让从节点**可以尝试增量同步**而不是全量。**这就是 `psync2` 的改进点。**

**Q：为什么从节点默认是只读的？能改成可写吗？**
`replica-read-only yes` 是默认值，**强烈建议保持**。如果设成 `no`：
- 往从节点写入的数据**不会同步到主节点**（复制是单向的：主 → 从）
- 一旦发生主从切换，这些写入的数据**就丢了**
- 主从数据不一致，`dbsize` 对不上，排查困难

**唯一合理的场景**：从节点做临时计算/中间结果存储（数据可丢）。**但更规范的做法是「不要往从节点写」，用独立的 Redis 存临时数据。**

**Q：读写分离的坑是什么？**
**① 数据延迟**：写完主节点后立刻读从节点，可能读到旧值（复制还没完成）。**这是最常见的坑**。
**② 从节点故障**：从节点挂了之后，读请求要能优雅地切回主节点（客户端需要支持）。
**③ 主节点必须为所有从节点维护缓冲区**：从节点越多，主节点的内存开销越大（每个从节点一个 `replication buffer`）。

**处置**：**关键路径「写后立刻读」强制走主节点**（比如一个 session 内刚写的数据），或者用「写后延迟一小段时间再允许读从节点」。**这个和缓存一致性里的「延迟双删」是同一类问题——承认延迟存在，用策略绕过它。**
:::

:::锚点
**诚实的定位：你是 Redis 的使用方，不是运维方（云托管），所以主从复制不是你每天打交道的东西。**但你可以用两件事把它讲活：

**① 你的环境中「主从延迟」的真实后果**

面试话术：「我们用腾讯云 Redis，主从切换是云厂商做的，我不直接管复制。**但主从延迟的影响我是有感知的：如果 Redis 有主从延迟，而我们又把『配置查询』这类数据缓存上去，就可能出现『写完配置后立刻读，读到的还是旧配置』。** 我们的业务模型是**写少读多**（场所配置变更频率很低），所以这个窗口的业务影响很小——但如果是频繁变更的场景，就必须把这类读强制走主节点。」

**② 你有 Kafka 和 MongoDB 的复制经验可以横向对比**

面试话术：「Redis 的复制和 Kafka 的副本机制有明显的区别：**Kafka 的副本是『ISR（同步副本集合）+ 高水位』模型**——只有 ISR 里的副本都同步了，消息才算 committed，消费者才看得到，所以 Kafka 能提供更高的一致性保证。**Redis 的复制是纯异步的**——主节点写完就返回，从节点什么时候收到不确定，所以 `master_repl_offset` 和 `slave_repl_offset` 的差值就是延迟。**这个差异决定了两者的适用场景：Kafka 用来做需要可靠传输的消息通道，Redis 用来做可以容忍延迟的缓存。**」

**③ 可以真正用上的一个点：`min-replicas-to-write` 的思路**

面试话术：「Redis 有个 `min-replicas-to-write` 配置，含义是『可用从节点少于 N 个就拒绝写入』——**这是用可用性换数据安全，防止网络分区时旧主节点继续接受写然后被丢弃。** 这个思路在我们的任务调度场景里是有关联的：**如果某个 pod 发现『我看到的状态已经过期了』（比如说它和 MongoDB 的连接断了），那它就不应该继续执行调优任务** —— 这本质上也是『不能确信自己还是权威时就不要写』。」

**这个类比的层次很高**：把「Redis 防止脑裂写入」的思路迁移到「分布式任务调度中的自我保护」。**面试官听到这种跨场景的类比，会认为你的理解是真理解。**

**④ 不要做的事**：不要在面试里说「我搭过 Redis 主从集群并调优过 `repl-backlog-size`」——如果被追问「你们集群几个节点、backlog 设了多少、为什么设这个值」，编造必翻车。**正确说法是：「我们用的是云托管，主从切换是平台做的，我了解复制的原理和 `INFO replication` 的判读方法，但没有自己调过这些参数。」**
:::

---

## 16. 哨兵与 Cluster

:::概念
三个层次解决三个问题：**主从 = 备份 + 读写分离；哨兵 = 自动故障转移（高可用）；Cluster = 分片（容量和吞吐扩展）。**
记忆钩子：**「主从解决『数据别丢』，哨兵解决『挂了能自动换』，Cluster 解决『一台装不下/扛不住』。」**
:::

:::提问
- 哨兵是怎么做故障转移的？「主观下线」和「客观下线」什么区别？
- 哨兵选新主节点的规则是什么？
- Redis Cluster 为什么是 16384 个槽？
- `MOVED` 和 `ASK` 重定向什么区别？
- Cluster 有什么限制？
:::

:::答案
### 三种模式的定位

| | 主从 | 哨兵 Sentinel | Cluster |
|---|---|---|---|
| 解决 | 备份 / 读写分离 | **高可用（自动故障转移）** | **容量 + 吞吐横向扩展** |
| 数据分片 | 否（每节点全量） | 否 | **是（16384 槽）** |
| 故障转移 | **手动** | 自动 | 自动 |
| 客户端复杂度 | 低 | 中（要走哨兵拿地址） | 高（要处理重定向） |
| 最少节点 | 2 | **3 个哨兵 + 1 主 N 从** | **3 主 3 从** |
| 多 key 操作 | 支持 | 支持 | **要求同槽** |
| 支持 db 索引 | 16 个 | 16 个 | **只支持 db0** |

### 哨兵（Sentinel）

```bash
# 最小配置 sentinel.conf
sentinel monitor mymaster 10.11.2.65 6379 2
#                                             ^ quorum：至少 2 个哨兵同意才判定客观下线
sentinel auth-pass mymaster <password>
sentinel down-after-milliseconds mymaster 30000    # 30 秒无响应 → 主观下线
sentinel parallel-syncs mymaster 1                  # 故障转移时同时向几个从同步（1 最安全但最慢）
sentinel failover-timeout mymaster 180000           # 故障转移超时 180 秒
sentinel deny-scripts-reconfig yes                  # 安全加固
```

**启动哨兵**：
```bash
redis-sentinel /etc/redis/sentinel.conf --sentinel
# 或者
redis-server /etc/redis/sentinel.conf --sentinel

# 查看哨兵状态
redis-cli -p 26379 SENTINEL masters
redis-cli -p 26379 SENTINEL master mymaster
redis-cli -p 26379 SENTINEL replicas mymaster
redis-cli -p 26379 SENTINEL get-master-addr-by-name mymaster
# 1) "10.11.2.66"      ← 故障转移后主节点已经变了
# 2) "6379"
redis-cli -p 26379 SENTINEL failover mymaster     # 手动触发故障转移（演练用）
```

**故障转移完整流程**：

```
① 主观下线（sdown）：单个哨兵发现主节点超过 down-after-milliseconds（30s）无响应
      ↓
② 客观下线（odown）：该哨兵向其他哨兵询问「你也认为它挂了吗？」
      收到 >= quorum（2）个确认 → 标记为客观下线
      ↓
③ 选举 Leader 哨兵（Raft 类似）：
      - 每个哨兵都可以发起选举，先到先得（谁先发起，投谁）
      - 需要获得 **超过半数** 的哨兵投票（不是 quorum，是总数/2+1）
      - 一轮没选出就等 failover-timeout 后重试
      ↓
④ Leader 哨兵从从节点中选择新主节点：
      筛选条件（按顺序）：
        - 排除：已下线、断线时间过久（down-after-milliseconds × 10）、
                优先级为 0（replica-priority 0 表示永不提升）
        - 排序：① replica-priority 最小（默认 100，数字越小优先级越高）
                ② 复制 offset 最大（数据最新的）
                ③ runid 最小（字典序，兜底规则保证唯一）
      ↓
⑤ 执行切换：
      - 向新主发送 REPLICAOF NO ONE（变成主节点）
      - 向其他从节点发送 REPLICAOF <新主>（改为复制新主）
      - 把旧主标记为从节点（如果它恢复了）
      ↓
⑥ 通过 Pub/Sub 频道 __sentinel__:hello 广播新配置（哨兵之间 + 客户端可以订阅）
```

**为什么哨兵至少要 3 个**：
- **2 个哨兵 + quorum=2**：任何一个挂了，剩下的那个永远无法达到 quorum，**故障转移瘫痪**
- **3 个哨兵 + quorum=2**：挂 1 个还能工作
- **选举需要「超过半数」**（不是 quorum）：3 个哨兵时，超过半数是 2 —— **所以 quorum 和选举过半是两个不同的门槛**，这是常被混淆的点

**客户端怎么感知新主**：客户端连接哨兵集合，通过 `SENTINEL get-master-addr-by-name` 拿主节点地址，并订阅 `+switch-master` 事件。Java 侧用 `JedisSentinelPool` 或 Lettuce + `RedisSentinelConfiguration`（Spring Boot 配 `spring.redis.sentinel.master` 和 `nodes`）。

**哨兵的脑裂问题**：
```
场景：主节点与哨兵/从节点网络分区，主节点仍然接受写入
      → 哨兵在另一侧把从节点提升为新主
      → 分区恢复后，旧主降级为从节点，**分区期间的写入被丢弃**

防护：min-replicas-to-write 1 + min-replicas-max-lag 10
     → 旧主看不到从节点 → 拒绝写入 → 不产生会被丢弃的数据
```
（详见第 15 题的拓展部分）

### Redis Cluster

```bash
# 创建集群（3 主 3 从）
redis-cli --cluster create \
  10.11.2.65:6379 10.11.2.66:6379 10.11.2.67:6379 \
  10.11.2.68:6379 10.11.2.69:6379 10.11.2.70:6379 \
  --cluster-replicas 1

# 检查集群状态
redis-cli --cluster check 10.11.2.65:6379
redis-cli --cluster info 10.11.2.65:6379

# 查看节点和槽位
redis-cli -c -p 6379 CLUSTER INFO
redis-cli -c -p 6379 CLUSTER NODES
redis-cli -c -p 6379 CLUSTER SLOTS

# 计算 key 落在哪个槽
redis-cli -p 6379 CLUSTER KEYSLOT user:1001
# (integer) 10778

# 扩容：加入新节点，然后重新分片
redis-cli --cluster add-node 10.11.2.71:6379 10.11.2.65:6379
redis-cli --cluster reshard 10.11.2.65:6379
# 交互式：要迁移多少个槽、目标节点 ID、从哪些节点迁

# 删除节点（先迁走槽位）
redis-cli --cluster del-node 10.11.2.65:6379 <node-id>
```

**关键配置**：
```bash
redis-cli config get cluster-enabled              # yes
redis-cli config get cluster-node-timeout         # 15000（15 秒）
redis-cli config get cluster-require-full-coverage # yes（默认！见下）
redis-cli config get cluster-replica-validity-factor # 10
redis-cli config get cluster-allow-replica-migration # yes
redis-cli config get cluster-migration-barrier     # 1
redis-cli config get cluster-announce-ip           # 容器/ NAT 环境必须显式配
redis-cli config get cluster-announce-port
redis-cli config get cluster-announce-bus-port
```

### 为什么是 16384 个槽位

**作者 antirez 的官方解释（面试能说出前两条就够了）**：

1. **心跳包的带宽**：Cluster 节点间通过 gossip 交换槽位信息，用的是**位图（bitmap）**。16384 个槽 = 16384 bit = **2KB**；如果是 65536 个槽 = **8KB**。节点间每 100ms 就要发 PING/PONG，**带宽差 4 倍**。
2. **集群规模**：Redis Cluster 设计上**节点数不超过 1000 个**。16384 个槽分给 1000 个节点，平均每节点 16 个槽——**足够用**。而 65536 个槽在 1000 个节点时每节点 65 个，收益不明显但带宽成本高。
3. **槽位号压缩**：节点配置文件中用 bitmap 存槽位，16384 位正好是 2KB，压缩后很小（配置里出现的都是 0，压缩率极高）。

**注意：这是工程权衡，不是数学必然。**其他方案（如 Codis 用 1024 个槽、一致性哈希）也能工作，16384 是关键权衡的产物。

### 路由：CRC16 + 槽位

```bash
# 客户端计算路由：CRC16(key) mod 16384
redis-cli -p 6379 CLUSTER KEYSLOT user:1001      # 10778
redis-cli -p 6379 CLUSTER KEYSLOT user:1002      # 9245（不同槽 → 可能在不同节点）
```

```bash
# hash tag：用 {} 强制多个 key 落在同一个槽
redis-cli -p 6379 CLUSTER KEYSLOT "{user1001}:profile"   # 9902
redis-cli -p 6379 CLUSTER KEYSLOT "{user1001}:orders"    # 9902 ← 同一个槽！
# 注意：计算的是 **大括号内的内容** 的 CRC16
```

**hash tag 的用途**：
```bash
# 不做 hash tag：MGET 跨槽会报错
redis-cli -c -p 6379 MSET user:1001:a 1 user:1001:b 2 user:1002:a 3
# (error) CROSSSLOT Keys in request don't hash to the same slot

# 用 hash tag：同一个用户的所有 key 落在一个槽，MGET 可以工作
redis-cli -c -p 6379 MSET "{user1001}:a" 1 "{user1001}:b" 2
# OK
redis-cli -c -p 6379 MGET "{user1001}:a" "{user1001}:b"
# 1) "1"
# 2) "2"
```

**Lua 脚本、事务（MULTI/EXEC）、`SUNIONSTORE`、`ZUNIONSTORE` 都要求「所有 key 在同一个槽」** —— 所以 Cluster 下这些功能要么用 hash tag，要么用不了。**这是 Cluster 最主要的限制。**

### `MOVED` 与 `ASK` 重定向

| | `MOVED` | `ASK` |
|---|---|---|
| 什么时候 | 槽**已经**归属其他节点 | 槽**正在迁移**，key 已经在目标节点 |
| 含义 | **永久重定向**：请更新你的路由表，以后这个槽都找它 | **临时重定向**：这一次去那个节点拿，**不要更新路由表** |
| 客户端动作 | 更新本地槽位映射 + 重试请求到新节点 | 先向目标节点发 `ASKING`，再发命令，**不改路由表** |

```bash
# 触发 MOVED（用非集群模式连集群，会看到重定向）
redis-cli -p 6379 GET user:1001
# (error) MOVED 10778 10.11.2.66:6379
# 用 -c 参数让 redis-cli 自动跟随重定向
redis-cli -c -p 6379 GET user:1001
# "value"      ← 自动跟到正确节点
```

**槽迁移的完整流程**（面试常问「扩容时数据怎么搬」）：
```
① 向目标节点发：CLUSTER SETSLOT <slot> IMPORTING <源节点ID>
② 向源节点发：  CLUSTER SETSLOT <slot> MIGRATING <目标节点ID>
   此时：源节点上「还存在」的 key 正常响应；
         源节点上「已不存在」的 key 返回 ASK（让客户端去目标节点拿）
③ 循环迁移 key：
     CLUSTER GETKEYSINSLOT <slot> <count>   ← 拿到该槽上的 key 列表
     MIGRATE <目标主机> <端口> "" 0 <timeout> KEYS <key1> <key2>...
④ 迁移完成后，向集群中**所有节点**广播：
     CLUSTER SETSLOT <slot> NODE <目标节点ID>
   此后该槽的请求返回 MOVED（永久重定向）
```

**`MIGRATE` 是同步阻塞的** —— 迁移大 key 时源节点会阻塞。**所以运维时要避免迁移大 key**，这也是大 key 的又一个危害。

### gossip 协议与故障转移

**gossip 的通信方式**：
- 每个节点每 **100ms** 从「已知节点列表」中**随机选 5 个**发送 `PING`
- 收到 `PING` 的节点回复 `PONG`
- **`PING`/`PONG` 里携带**：自己知道的节点列表、各节点的槽位分布（bitmap）、各节点的状态（在线/疑似下线）
- 选 5 个是「**部分随机**」：其中会优先选「最近没通信过的」和「有过故障的」，保证信息传播速度

**故障转移流程**：
```
① 主观下线（PFAIL）：节点 A 在 cluster-node-timeout（15s）内没收到节点 B 的 PONG
② 客观下线（FAIL）：节点 A 通过 gossip 询问其他节点
     收到 **超过半数主节点** 的 PFAIL 确认 → 标记 B 为 FAIL
③ 从节点发起选举（类似 Raft）：
     - B 的从节点发现主节点 FAIL，且自己有资格（复制 offset 足够新）
     - 向其他主节点发送投票请求
     - 得票 **超过半数主节点** 且自己是负责该槽的主节点 → 提升为主节点
④ 广播：新主接管 B 的槽位，通过 gossip 广播新配置
⑤ 如果失败（没选出）→ 等 cluster-node-timeout × 2 后重试
```

**`cluster-node-timeout` 的影响**：**它决定「多久判定一个节点下线」**。默认 15000ms。
- 设太小 → 网络抖动就触发故障转移 → 频繁切换（甚至有主从都切换的风险）
- 设太大 → 真挂了要等很久才切换 → 服务不可用时间长
- **经验值：5000~15000ms**，取决于网络质量

**`cluster-require-full-coverage`（默认 `yes`，这个默认值很坑）**：
```bash
redis-cli -c -p 6379 CONFIG GET cluster-require-full-coverage
# yes（默认）
```
含义：**只要有任何一个槽没有节点负责（比如某组主从全挂了），整个集群拒绝所有请求**（返回 `CLUSTERDOWN`）。**好处**是一致性有保证；**坏处**是「一个小分片挂了导致整个集群不可用」。

**建议设为 `no`**：可用的槽继续服务，只有访问不可用槽的请求失败。**这是「可用性优先」的选择，生产上更常见。**

```bash
redis-cli -c -p 6379 CONFIG SET cluster-require-full-coverage no
redis-cli -c -p 6379 CONFIG REWRITE
```
:::

:::拓展
**Cluster 的限制清单（面试要能列出来）**

| 限制 | 说明 | 绕过方式 |
|---|---|---|
| **多 key 操作要同槽** | `MGET`/`MSET`/`SUNION`/`ZUNIONSTORE`/**Lua**/`MULTI` 都要求同槽 | **hash tag** `{user1}:a` |
| **只支持 db0** | `SELECT` 命令不可用 | 用 key 前缀模拟命名空间 |
| **不支持 `KEYS`**（单节点上可用但不完整） | 每个节点只能看到自己的 key | 用 `SCAN` + 逐节点扫描 |
| **不支持跨槽的 `SCAN`** | 要逐节点扫 | 客户端维护节点列表，逐个扫 |
| **`cluster-require-full-coverage` 默认 yes** | 一个槽不可用整个集群拒绝服务 | 设为 `no` |
| **节点数上限约 1000** | gossip 的通信开销 | 拆分多个集群 |
| **客户端要支持 Cluster 协议** | 要处理 `MOVED`/`ASK` | 用 Jedis Cluster / Lettuce / Redisson |
| **运维复杂** | 扩容要 `reshard`（迁移槽 + 数据） | 用云托管（腾讯云/阿里云的集群版） |

**Cluster vs 一致性哈希**：

| | 一致性哈希（如 Codis） | Redis Cluster（哈希槽） |
|---|---|---|
| 分片单位 | 虚拟节点（可任意多） | **固定 16384 槽** |
| 扩容 | 加节点 → 一部分虚拟节点转移 | **手动/自动 `reshard` 指定槽的归属** |
| 控制粒度 | 细（虚拟节点数） | **粗但显式**（可以精确指定「哪几个槽给哪个节点」） |
| 数据迁移 | 按虚拟节点范围 | `MIGRATE` 逐 key |
| 官方支持 | 否（第三方） | **是** |

**哈希槽的优势**：**「槽」是一个显式的、可指定的单位**。运维可以精确控制「把 1000 个槽从 A 迁到 B」，也可以做「同槽的多 key 操作」（用 hash tag）。**一致性哈希做不到这种显式控制。**

**Cluster 的客户端选型（Java）**：
- **Jedis Cluster**：`JedisCluster`（同步，简单）
- **Lettuce**：`RedisClusterClient`（基于 Netty，异步，Spring Boot 默认）
- **Redisson**：`RedissonClient`（支持 Cluster 模式，且分布式对象（锁、Map）都能用）

**Spring Boot 配 Cluster**：
```yaml
spring:
  redis:
    cluster:
      nodes:
        - 10.11.2.65:6379
        - 10.11.2.66:6379
        - 10.11.2.67:6379
      max-redirects: 3          # 跟随重定向的最大次数
    timeout: 3000ms             # ★ 命令超时，一定要配
    lettuce:
      pool:
        max-active: 16
        max-idle: 8
        min-idle: 2
        max-wait: 1000ms
```

**`max-redirects` 的作用**：客户端跟随 `MOVED` 重定向的次数上限。设太小（如 1）在集群扩容/迁移期间会大量失败，设太大（如 10）会放大异常请求的开销。**3 是常见值。**

**云托管的集群版**：腾讯云 Redis 的集群版对外暴露一个**统一的代理地址**（不发 `MOVED`，代理内部转发），所以客户端**可以用单机模式连**——这是云厂商替你把 Cluster 的复杂度吃掉了。**面试时如果能说出「云托管的集群版通常提供代理层，客户端无感」，是很加分的实践认知。**
:::

:::追问
**Q：哨兵和 Cluster 都要至少 3 个节点，为什么？**
**奇数原则是为了选举能「超过半数」。** 3 个节点时，挂 1 个还剩 2 个，超过半数是 2 —— 能选出。2 个节点时挂 1 个只剩 1 个，超过半数是 2 —— 选不出来。**所以任何基于过半投票的协议（Raft、ZAB、Redis Sentinel、Redis Cluster）都建议用奇数个节点。**

**Q：Cluster 里一个分片的主从都挂了会怎样？**
取决于 `cluster-require-full-coverage`：
- `yes`（默认）：**整个集群返回 `CLUSTERDOWN`，所有请求失败**
- `no`：该分片负责的槽不可用（访问这些槽报错），**其他槽正常服务**

**这也是为什么生产建议设成 `no`** —— 「一个分片挂了导致全站不可用」的爆炸半径太大。

**Q：`cluster-node-timeout` 设多少？**
默认 **15000ms（15 秒）**。权衡：
- **设小（如 3000ms）**：故障发现快（3 秒就切换），但**网络抖动容易误判**，导致频繁故障转移
- **设大（如 30000ms）**：不容易误判，但故障恢复慢（30 秒服务不可用）

**经验值**：**内网环境 5000~10000ms，跨机房/网络不稳 15000~30000ms。** 判断依据是「网络抖动的 P99 延迟」——`timeout` 应该大于网络抖动的最大延迟。

**Q：Redis Cluster 能保证强一致吗？**
**不能。** 原因：
1. **复制是异步的** —— 主节点写入成功就返回，不等待从节点确认
2. **故障转移会丢数据** —— 主节点挂了，从节点可能还没收到最后一批写就成为了新主
3. **脑裂期间旧主仍可写**（除非配了 `min-replicas-to-write`）

**所以 Redis Cluster 提供的是「高可用 + 扩展性」，不是「强一致」。** 强一致要用 etcd/ZooKeeper（Raft/ZAB 写需过半确认）。**这个结论必须能一句话说出来。**

**Q：为什么 Cluster 不支持 `SELECT`？**
因为「多个 db」和「分片」在语义上冲突：如果支持 16 个 db，那每个 db 都要有 16384 个槽，槽的元数据量 ×16，gossip 的心跳包也要 ×16。**所以 Cluster 只保留 db0，用 key 前缀来模拟命名空间。**这也是「简化设计换带宽」的又一个例子。
:::

:::锚点
**诚实的定位：你用云托管 Redis，主从/哨兵/Cluster 大概率是平台配置的。**但这个点反而可以说得很漂亮：

**① 你的真实环境**

面试话术：「我们用腾讯云 Redis（`10.11.2.65:6379`），高可用是云厂商提供的。**所以我最关心的不是『怎么搭哨兵』，而是『故障切换期间我的应用会发生什么』——这决定了我要配什么。**」

**② 从「使用者视角」讲高可用（这是你的优势，不是劣势）**

面试话术：「云 Redis 做主从切换的时候，客户端会短暂连不上。**所以我做的两件事是：① 配命令级超时（不能让请求无限等）；② 对 Redis 的调用做降级——缓存读不到就查 MongoDB，锁拿不到就跳过本次任务。**这些不是『运维知识』，是『应用侧必须做的防御』。**而且我一般认为：不管下游多可靠，应用侧都要假设它会挂。**」

**这个回答的层次比背哨兵选举流程高得多** —— 它展示的是「从消费者视角设计系统」的思维。**面试官如果是做后端的，会更欣赏这种答法。**

**③ 可以主动提的一个真实风险：主从切换 + 分布式锁**

面试话术：「云 Redis 的主从切换对我们有一个具体的风险：**如果我们在主节点上加了一个调优任务锁，然后主节点挂了、从节点被提升，那个锁可能就丢了。** 这时候另一个 pod 可能拿到同一把锁。**所以我们的任务互斥不能只依赖锁——还有一层『任务状态校验』：执行前先查任务状态（状态在 MongoDB 里），发现已经在执行就退出。**」

**这个论证链条（云环境 → 主从切换 → 锁丢失 → 用状态校验兜底）非常好，因为它把一个理论问题落到了一个真实的架构决策上。**

**④ 如果你了解 Kafka 的分区，可以横向对比 Cluster 分片**

面试话术：「Redis Cluster 的分片和 Kafka 的分区思路类似但有关键差异：**Kafka 的分区数是可以任意指定的，而 Redis Cluster 的槽位是固定 16384 个**。这导致了不同的运维方式：Kafka 扩容要「重新分配分区」（可能影响很多 key），Redis Cluster 扩容是「迁移槽位」（可以精确控制迁多少）。**而且 Redis Cluster 的槽位固定带来了一个好处：同槽的多 key 操作可以用 hash tag 保证原子性，Kafka 没有这个概念。**」

**⑤ 不要做的事**：不要编造「我搭建过 3 主 3 从的 Cluster 并做过 reshard」。**正确说法**：「Cluster 的槽位机制、gossip 通信、`MOVED`/`ASK` 重定向我知道原理，也用过 `redis-cli -c` 观察过重定向，**但我们生产用的是云托管，没有自己运维过集群。**」——如果你连 `redis-cli -c` 都没试过，那就诚实说「我了解原理」。**面试官对有边界感的候选人评价更高。**
:::

---
## 17. Lua 脚本、事务与 Pipeline

:::概念
三者解决三个不同问题：**Pipeline 减少网络往返（不保证原子）；`MULTI/EXEC` 把命令打包（不保证原子性，出错不回滚）；Lua 脚本整体原子执行（单线程执行整段脚本）。**
记忆钩子：**「Pipeline 省 RTT，事务打包但不回滚，Lua 才是真原子——要原子就用 Lua。」**
:::

:::提问
- Redis 事务和数据库事务有什么区别？
- `MULTI/EXEC` 能回滚吗？
- Lua 脚本为什么是原子的？有什么坑？
- Pipeline 和事务什么区别？
- 扣库存应该用哪种方式？
:::

:::答案
### 四者对比（核心表）

| 特性 | 单独命令 | Pipeline | `MULTI/EXEC` 事务 | Lua 脚本 |
|---|---|---|---|---|
| **原子性** | 单条命令原子 | **否**（中间可插入其他客户端命令） | **不保证**（运行时错误不回滚） | **是**（整段脚本不被插入） |
| 目的 | — | **减少网络 RTT** | 打包 + 乐观锁（`WATCH`） | 多条命令的原子执行 |
| 网络往返 | N 次 | **1 次** | 2 次（`MULTI` + `EXEC`） | 1 次 |
| 执行出错 | 报错 | 某条失败不影响其他 | **继续执行后续命令**（不回滚） | 脚本中断，**但已执行的命令不回滚** |
| 能读中间结果做判断 | — | 不能 | 不能 | **能**（`if...then`） |
| 复杂度 | O(1) | O(N)（客户端累加） | O(N) | O(N) |

### Pipeline（流水线）

**问题**：每个命令都要等一次 RTT（往返延迟）。**内网 RTT 约 0.1~1ms，如果一次业务要发 100 条命令，光网络就 10~100ms。**

**Pipeline 的做法**：客户端把 N 条命令一次性发出去，**不等回复**，然后一次性读回所有回复。

```bash
# redis-cli 的 --pipe 模式（批量导入）
seq 1 100000 | awk '{print "SET key:"$1" value"$1}' | redis-cli --pipe
```

```java
// Java 侧：Spring Data Redis 的 executePipelined
List<Object> results = redisTemplate.executePipelined(
    (RedisCallback<Object>) connection -> {
        StringRedisConnection conn = (StringRedisConnection) connection;
        for (int i = 0; i < 10000; i++) {
            conn.set("key:" + i, "value" + i);
        }
        return null;      // ★ 必须返回 null，实际结果通过 executePipelined 的返回值拿到
    });
```

**Pipeline 的关键限制**：
1. **不是原子的** —— 命令之间有间隙，其他客户端的命令可以插进来
2. **命令之间无法依赖** —— 不能「先读结果再决定下一条命令」
3. **一次别发太多** —— 客户端要缓存所有命令和回复，**几十万条会让客户端 OOM**。建议每批 **1000~10000 条**，分批发送
4. **服务端要缓存所有回复** —— 客户端不读，服务端的输出缓冲区会积压（超过 `client-output-buffer-limit normal` 会被强制断开）

### `MULTI/EXEC` 事务

```bash
redis-cli MULTI
# OK
redis-cli SET k1 v1
# QUEUED            ← 命令入队，不执行
redis-cli INCR counter
# QUEUED
redis-cli EXEC
# 1) OK
# 2) (integer) 43   ← 一次性执行所有入队的命令
```

**两类错误的行为完全不同（必考）**：

| 错误类型 | 例子 | 行为 |
|---|---|---|
| **入队时错误**（语法/命令不存在） | `MULTI` 后执行 `INCR`（参数个数错）、不存在的命令 | **整个事务被拒绝**，`EXEC` 返回错误，**所有命令都不执行** |
| **运行时错误** | 对 String 执行 `LPUSH k v`（类型错误） | **错误的那条失败，其余命令继续执行并生效**，`EXEC` 的返回里对应位置是错误 |

**所以 Redis 事务不保证原子性**：

```bash
redis-cli MULTI
redis-cli SET k1 v1
redis-cli LPUSH k1 x        # k1 是 String，这条会失败
redis-cli SET k2 v2
redis-cli EXEC
# 1) OK
# 2) (error) WRONGTYPE Operation against a key holding the wrong kind of value
# 3) OK                     ← **k2 被设置了！没有回滚**
```

**为什么 Redis 不支持回滚**：作者 antirez 的设计哲学——**「运行时错误都是编程错误，应该在开发阶段被发现，而不是在生产用回滚来掩盖」**，而且回滚需要额外的 undo log，成本高、收益低。

**`WATCH`：事务里的乐观锁（CAS）**

```bash
# 客户端 A
redis-cli WATCH stock:1001
redis-cli GET stock:1001           # 读到 10
redis-cli MULTI
redis-cli DECRBY stock:1001 1
redis-cli EXEC
# (integer) 9

# 如果 WATCH 之后、EXEC 之前有别人改了 stock:1001：
# → EXEC 返回 (nil)，表示事务失败，需要重试
```

```java
// Java 侧：SessionCallback + watch
public boolean deductStock(String key, int qty) {
    return Boolean.TRUE.equals(redisTemplate.execute(new SessionCallback<Boolean>() {
        @Override
        public Boolean execute(RedisOperations ops) {
            ops.watch(key);                          // ① WATCH
            Integer stock = (Integer) ops.opsForValue().get(key);
            if (stock == null || stock < qty) {
                ops.unwatch();
                return false;                        // 库存不足
            }
            ops.multi();                             // ② 开启事务
            ops.opsForValue().decrement(key, qty);   // ③ 入队
            List<Object> results = ops.exec();       // ④ 提交，被别人改过则返回 null
            return results != null;
        }
    }, key));
}
```

**`WATCH` 的机制**：`WATCH` 的 key 被修改时（包括**过期删除**、**被其他客户端的写命令修改**），事务被打断，`EXEC` 返回 `nil`。**客户端要做「读-改-写」的循环重试**（通常重试 3~5 次）。

**`WATCH` 的坑**：
- **key 过期也会触发** —— 如果 WATCH 的 key 恰好在事务期间过期，`EXEC` 会失败
- **必须循环重试** —— 不重试的话高并发下失败率很高
- **`WATCH` 的 key 不能过多** —— 每个 WATCH 的 key 都要在客户端和 Redis 里记录状态
- **`WATCH` 后必须 `UNWATCH` 或 `EXEC`/`DISCARD`** —— 连接归还到连接池时，未清理的 WATCH 状态会污染下一个使用者

**这个最后一条是 Java 侧的真实坑**：如果用连接池，WATCH 之后没有 EXEC/DISCARD/UNWATCH，连接被还回池子，下一个拿到这条连接的请求会一直被 WATCH 影响。**`SessionCallback` 内部会处理，但自己直接用 `RedisConnection` 就要小心。**

### Lua 脚本（真正的原子）

```bash
EVAL script numkeys key [key ...] arg [arg ...]
```

```lua
-- 示例 1：分布式锁释放（第 12 题）
if redis.call('get', KEYS[1]) == ARGV[1] then
    return redis.call('del', KEYS[1])
else
    return 0
end
```

```lua
-- 示例 2：原子扣库存（检查 + 扣减，这是 WATCH 方案的更优替代）
-- KEYS[1]=库存key  ARGV[1]=扣减数量
local stock = tonumber(redis.call('get', KEYS[1]))
if stock == nil then
    return -1                    -- 库存不存在
end
if stock < tonumber(ARGV[1]) then
    return -2                    -- 库存不足
end
redis.call('decrby', KEYS[1], ARGV[1])
return stock - tonumber(ARGV[1])
```

```bash
# 调用
redis-cli EVAL "local s = tonumber(redis.call('get', KEYS[1])); if s == nil then return -1 end; if s < tonumber(ARGV[1]) then return -2 end; redis.call('decrby', KEYS[1], ARGV[1]); return s - tonumber(ARGV[1])" 1 stock:1001 2
# (integer) 8

# 用文件更清晰
redis-cli --eval deduct.lua stock:1001 , 2
# 注意：--eval 里 KEYS 和 ARGV 用逗号（,）分隔
```

**为什么 Lua 是原子的**：**Redis 单线程执行命令，执行整个 Lua 脚本期间不会处理任何其他客户端的命令** —— 所以脚本内的多个 `redis.call` 之间不可能被插入。**这是「原子」的准确含义：不可分割、不被干扰，而不是「失败会回滚」。**

**注意：Lua 脚本出错时，已执行的命令不会回滚** —— 和事务一样。所以脚本要写得健壮（先检查后执行）。

### Lua 的五个坑（面试深度分水岭）

**① 脚本必须快 —— 否则阻塞整个 Redis**

```bash
redis-cli config get lua-time-limit      # 5000（毫秒）
```

脚本执行超过 `lua-time-limit`（默认 5 秒）后，**其他客户端发命令会收到 `BUSY Redis is busy running a script`**。此时只能：

```bash
redis-cli SCRIPT KILL        # 只能杀掉「还没执行写命令」的脚本
redis-cli SHUTDOWN NOSAVE    # 已经写过的话，只能强杀 Redis（会丢数据）
```

**所以脚本里绝对不能有大循环、大 key 遍历。** `for i=1,1000000 do redis.call('hset', ...) end` 这种写法会让 Redis 卡死。

**② 不要在脚本里用随机数/时间（除非用 effect replication）**

```
问题：Redis 有两种复制模式
  - 旧模式（5.0 前）：**复制脚本本身**，从节点重新执行
    → 如果脚本里有 math.random() 或 TIME，主从执行结果不同 → **主从数据不一致**
  - 新模式（5.0+ 默认）：**effect replication（效果复制）**
    → 主节点把脚本产生的「写命令」复制给从节点，而不是复制脚本
    → 从节点不执行脚本，只执行产生的命令 → 主从一致
```

**Redis 5.0 起 `effect replication` 是默认行为**，所以现在可以放心用随机数。**这个「5.0 前后行为不同」的版本差异是个很好的加分点。**

**③ 全局变量污染**

```lua
-- 错误：不小心创建了全局变量（会污染后续脚本执行的环境）
count = 1

-- 正确：用 local
local count = 1
```
**Lua 里不加 `local` 的变量是全局的，会在 Redis 的 Lua 环境里常驻** —— 这会导致「上一个脚本的变量影响了下一个脚本」的诡异 bug。

**④ KEYS 必须显式声明（Cluster 下尤其重要）**

```lua
-- 错误：把 key 拼在 ARGV 里
redis.call('get', ARGV[1])            -- Cluster 下无法判断槽位！

-- 正确：所有 key 通过 KEYS 传
redis.call('get', KEYS[1])
```
**Cluster 下，Redis 会检查脚本访问的所有 key 是否在同一个槽**（通过 `numkeys` 参数声明的数量）。如果 key 藏在 ARGV 里，Redis 无法校验，脚本在跨槽时行为不可预期。**所以规范是：所有 key 都通过 KEYS 传。**

**⑤ `redis.call` vs `redis.pcall`**

| | 出错时 |
|---|---|
| `redis.call` | **抛错并终止脚本** |
| `redis.pcall` | **返回一个 Lua table 描述错误**，脚本继续执行 |

需要「容忍某个命令失败并继续」时用 `pcall`，比如尝试删除一个可能不存在的 key。

### 该用哪个：决策树

```
需要「读结果 → 判断 → 写」的原子操作吗？
   ├─ 是 → **Lua 脚本**（扣库存、锁释放、限流）
   └─ 否
       ├─ 需要「多个 key 一起改，且失败要能检测到并发修改」→ **WATCH + MULTI/EXEC**
       └─ 只是「批量发送减少 RTT」→ **Pipeline**
```

**扣库存的标准答案**：**Lua 脚本**（`if stock >= qty then decrby`）。`WATCH` 方案虽然能用，但高并发下失败率高、要重试，Lua 一次就成。**注意：真正的库存扣减不应该只靠 Redis（Redis 会丢数据），而是 Redis 做预扣 + DB 做最终一致。**
:::

:::拓展
**`EVALSHA`：避免每次传输脚本**

```bash
# ① 先加载脚本，拿到 SHA1
redis-cli SCRIPT LOAD "return redis.call('get', KEYS[1])"
# "4e6d8fc8bb01276962cce5371fa795a7763657ae"

# ② 之后用 SHA1 调用（不需要传脚本内容，省带宽）
redis-cli EVALSHA 4e6d8fc8bb01276962cce5371fa795a7763657ae 1 mykey

# ③ 如果脚本没被加载过会报错 NOSCRIPT，客户端要处理：重新 SCRIPT LOAD 再重试
redis-cli EVALSHA 0000000000000000000000000000000000000000 1 mykey
# (error) NOSCRIPT No matching script. Please use EVAL.

# 检查脚本是否在
redis-cli SCRIPT EXISTS 4e6d8fc8bb01276962cce5371fa795a7763657ae
redis-cli SCRIPT FLUSH       # 清空脚本缓存（慎用）
redis-cli INFO memory | grep lua    # 看脚本缓存占用的内存
```

**Java 侧的标准做法**：
```java
DefaultRedisScript<Long> script = new DefaultRedisScript<>();
script.setScriptText("if redis.call('get', KEYS[1]) == ARGV[1] then return redis.call('del', KEYS[1]) else return 0 end");
script.setResultType(Long.class);

// Spring Data Redis 内部会用 EVALSHA，遇到 NOSCRIPT 自动回退到 EVAL 并缓存
Long result = redisTemplate.execute(script, Collections.singletonList(lockKey), requestId);
```
**Spring Data Redis 已经帮你处理了 `SCRIPT LOAD` + `NOSCRIPT` 回退** —— 这是用框架的好处，但面试时要能说出「它底层用的是 EVALSHA，失败会回退到 EVAL」。

**`FUNCTION`：Redis 7.0 的新脚本模型**

Redis 7.0 引入了 **Functions**（基于 Lua 的服务器端函数库），**用 `FUNCTION LOAD` 注册一个函数库，客户端用 `FCALL` 调用**。相比 `EVAL` 的改进：
- **脚本随数据持久化**（存在 RDB/AOF 里，重启后还在，不需要客户端重新加载）
- **函数库是一个整体**（可以包含多个函数，共享代码）
- **支持在不重启的情况下更新**（`FUNCTION LOAD REPLACE`）

```bash
redis-cli FUNCTION LOAD "#!lua name=mylib
redis.register_function('my_unlock', function(keys, args)
  if redis.call('get', keys[1]) == args[1] then
    return redis.call('del', keys[1])
  else
    return 0
  end
end)"

redis-cli FCALL my_unlock 1 lock:order uuid-123
redis-cli FUNCTION LIST
redis-cli FUNCTION STATS
```

**但要注意**：`FCALL` 在 Cluster 下**必须跟 `FCALL_RO` 或明确的 key 声明**，且函数库要在所有节点上一致加载。**目前生产上 `EVAL` 还是主流**，Functions 是新选择。**面试提一句「7.0 引入了 Functions 解决脚本持久化问题」就够了，别展开。**

**Redis 事务的 ACID 分析（面试最爱问）**

| 特性 | Redis 事务 | 说明 |
|---|---|---|
| **原子性 A** | **不满足** | 运行时错误不回滚，部分命令已生效 |
| **一致性 C** | 满足 | 事务内的命令要么全入队要么全部拒绝（入队时错误） |
| **隔离性 I** | 部分满足 | 单线程执行保证「执行不被打断」，但**没有「读已提交」的隔离级别概念**，`WATCH` 只是乐观锁 |
| **持久性 D** | 取决于配置 | `appendfsync always` 才保证持久；`everysec` 丢 1 秒 |

**结论：Redis 事务不满足 ACID 的「原子性」。** 这个表格答出来，面试官基本不会再追问。
:::

:::追问
**Q：为什么 Redis 事务不支持回滚？**
antirez 的设计哲学：**「运行时错误（如类型错误 `WRONGTYPE`）都是编程错误，应该在开发和测试阶段暴露，而不是在生产靠着回滚把错误数据默默吃掉。」** 而且实现回滚需要维护 undo log（记录每条命令的逆操作），成本高、复杂度高，而 Redis 的定位是「快」。**所以 Redis 事务只保证「命令按顺序执行且不被打断」，不保证「失败回滚」。**

**Q：那扣库存到底用 Lua 还是 `WATCH`？**
**Lua 更好**，原因：
1. `WATCH` 是乐观锁，高并发下冲突率高，要循环重试，**重试本身又增加冲突**（活锁风险）
2. Lua 一次执行，无重试
3. Lua 逻辑写在服务端，客户端代码更简洁

**但要注意**：`WATCH` 的价值在于**「跨多个 key 的 CAS」**且**逻辑复杂到不适合写 Lua** 时。**Lua 的缺点是逻辑在服务端难调试、难版本管理。** 实际选型：「简单逻辑用 Lua，复杂逻辑用 `WATCH` 或移到应用层用分布式锁」。

**Q：Lua 脚本里的 `KEYS` 数量有上限吗？**
有实际限制。`EVAL` 的 `numkeys` 参数要显式声明，**且 Cluster 下所有 key 必须在同一个槽**。另外，脚本的**参数和返回值都要经过 Lua 和 Redis 类型转换**（Lua 没有整数类型，都是 double，所以返回值会有精度问题——**大整数要返回字符串**）。

**`redis.call` 的返回值转换规则**：
```
Redis 返回              → Lua 类型
nil / 不存在            → false
状态回复 (OK)           → {ok="OK"}
错误回复                → {err="..."}
整数                    → number（Lua 的 double，⚠️ 超过 2^53 有精度问题）
批量回复                → table
多批量回复              → table（嵌套）
```
**所以「脚本返回一个大的 Snowflake ID 会精度丢失」是个真实的坑** —— 要用 `tostring()` 返回字符串。

**Q：Pipeline 里的命令能保证顺序吗？**
**能保证顺序（服务端按接收顺序执行），但不能保证原子（中间可插入其他客户端命令）。** 这是 Pipeline 和 Lua 的关键区别。另外，**Pipeline 里的命令如果有一条失败，其他命令照样执行**（和事务的运行时错误行为一样）。

**一个容易忽略的点**：Pipeline 的回复是**按发送顺序返回的**，客户端要按序解析。如果用 `executePipelined` 且 callback 里返回 `null`，结果顺序和发送顺序一一对应。**如果 callback 里做了条件分支（某些情况下不发命令），顺序会对不齐** —— 这是 Spring Data Redis 的一个常见坑。
:::

:::锚点
**诚实定位：你没有写过生产级的 Lua 脚本。**但分布式锁这一块**如果你用的实现里有 Lua（大多数 Node.js 锁库都有 release 脚本），那就是真实的**。策略：

**① 从一个真实的、你一定能讲清的点切入**

面试话术：「Lua 我理解最深的一个场景是**分布式锁的释放**——因为 `GET` 和 `DEL` 必须原子，不然会出现『判断是自己的锁 → 中间锁过期被别人拿到 → 你删了别人的锁』这个问题。**我在用 Redis 锁做任务互斥时，释放锁的脚本就是这个模式。**」

**② 如果面试官追问「你自己写过 Lua 吗」，诚实回答 + 展示理解**

面试话术：「锁的释放脚本我是照着标准写法用的，**没有自己从零写过复杂的业务脚本**。但我清楚 Lua 的三个约束：**① 必须快（超过 `lua-time-limit` 会让整个 Redis 返回 BUSY，只能 `SCRIPT KILL` 或强杀）；② 所有 key 要通过 `KEYS` 传（Cluster 下要校验槽位）；③ 变量要用 `local`（否则污染全局环境）。** 如果我需要写扣库存这类脚本，我知道用 `if stock >= qty then decrby` 这个结构，**并且要返回字符串而不是大整数（Lua 的 number 是 double，超过 2^53 会丢精度）。**」

**③ 把「事务 vs Lua」的选型判断讲出来（这是你能展现判断力的地方）**

面试话术：「我不太倾向在生产用 `MULTI/EXEC`。**因为 Redis 事务不回滚——运行时错误只是报错，后面的命令照常执行。** 这意味着你在事务里写错了类型，会得到一个「一半成功」的状态，比直接失败更难排查。**所以我更倾向：要么用 Lua（原子且有判断能力），要么用 Pipeline（承认非原子、只是批量发送），要么用分布式锁 + 应用层逻辑。** `WATCH` 的乐观锁方案我也只在「并发冲突率低」的场景才用，因为高并发下重试成本高。」

**④ 一个真实关联：你们的调优任务状态机**

面试话术：「我们的调优任务有状态流转（待执行 → 执行中 → 已完成）。**如果用 Redis 做状态判断，用 Lua 就能实现「原子地检查状态并更新」**——比如 `if status == 'PENDING' then set status='RUNNING'; return 1 else return 0 end`。**这比「先 GET 再 SET」安全得多，因为两步之间可能被其他 pod 插入。** 不过我们的任务状态存在 MongoDB 里，用的是条件更新（`findAndModify`）做 CAS，**思路和 Lua 是一样的：把「检查 + 修改」变成一次原子操作。**」

**这个类比非常好**：**MongoDB 的条件更新**和 **Redis 的 Lua** 是同一问题的两个实现（原子 CAS），**你能跨中间件看出这个共性，说明是真的理解了「原子性」这个抽象概念，而不是背 Redis 命令。**
:::

---

## 18. Redis 做消息队列的局限（对比 Kafka）

:::概念
Redis 能当队列用：**List（最简单，无 ACK）→ Stream（5.0+，有消费组和 ACK，可当轻量 MQ）**。
但**消息队列的核心需求是「可靠性 + 可回溯 + 水平扩展」，这三点 Redis 都不如专业 MQ。**
记忆钩子：**「List 是队列的雏形，Stream 是队列的完整版，Kafka 是队列的工业版。」**
:::

:::提问
- 用 Redis 做消息队列有哪些方式？
- Stream 和 Kafka 有什么区别？
- List 做队列有什么问题？
- 为什么你们项目用 Kafka 不用 Redis 队列？
:::

:::答案
### 三种实现方式对比

| 特性 | List（`LPUSH`+`BRPOP`） | Pub/Sub | **Stream**（5.0+） |
|---|---|---|---|
| 消息持久化 | 有（在 List 里） | **无**（发完就丢） | 有 |
| 消费者组 | 无 | 无 | **有**（`XGROUP`） |
| ACK 机制 | **无** | 无 | **有**（`XACK`） |
| 消息回溯 | 不支持（弹出即删） | 不支持 | **支持**（按 ID 重读） |
| 消费失败重试 | 要自己做 | — | **`XPENDING` + `XCLAIM`** |
| 广播（多消费组） | 不支持 | **支持** | **支持**（多个 group 各读一份） |
| 阻塞读 | `BRPOP` | `SUBSCRIBE` | `XREAD BLOCK` |
| 适用 | 简易任务队列 | 实时通知（可丢） | 轻量 MQ |

### List 做队列

```bash
# 生产者
redis-cli LPUSH queue:tasks '{"id":1,"type":"tuning"}'
# 消费者（阻塞等待，最多 5 秒）
redis-cli BRPOP queue:tasks 5
# 1) "queue:tasks"
# 2) "{\"id\":1,\"type\":\"tuning\"}"
```

**三个致命问题**：

1. **无 ACK → 丢消息**：`BRPOP` 弹出后消息就从 List 里删了。如果消费者在**弹出后、处理完成前**崩溃，这条消息就丢了。
2. **无消费者组 → 无法水平扩展消费**：多个消费者 `BRPOP` 同一个 key 确实能分摊（这是 List 的天然队列能力），但**无法做「一个消息被多个组各处理一次」的广播**。
3. **无法回溯/重放**：消息弹出就没了。

**「可靠队列」的改进版（`LMOVE` 模式）**：

```bash
# ① 从待处理队列弹出，同时放进「处理中」队列（原子操作）
redis-cli LMOVE queue:pending queue:processing LEFT RIGHT
# LMOVE source destination LEFT|RIGHT LEFT|RIGHT     （6.2+，替代已废弃的 RPOPLPUSH）

# ② 处理成功后，从「处理中」移除
redis-cli LREM queue:processing 1 '<消息内容>'

# ③ 后台任务扫描「处理中」队列，把超时的消息移回「待处理」（处理消费者崩溃的情况）
```

**这个模式（待处理队列 + 处理中队列 + 超时回收）就是「至少一次投递」的实现**。**代价**：消息要存两份、要维护超时扫描、`LREM` 需要精确匹配内容（低效）。**Stream 就是把这个模式内置了**（`PEL` = 处理中队列，`XCLAIM` = 超时回收）。

### Pub/Sub

```bash
# 订阅
redis-cli SUBSCRIBE channel:notify
# 发布
redis-cli PUBLISH channel:notify "hello"
```

**核心缺陷：不持久化。** 消息发出后，**没有订阅者的订阅者就完全收不到**（不像 Kafka 可以回溯）。所以 Pub/Sub 只适合**「实时通知，丢了无所谓」**的场景：配置变更广播、缓存失效广播、集群节点通信（哨兵就用 Pub/Sub 的 `__sentinel__:hello` 频道）。

**一个隐藏问题**：Pub/Sub 的消息会占用客户端的**输出缓冲区**。如果某个订阅者处理很慢，缓冲区积压，**超过 `client-output-buffer-limit pubsub`（默认 32MB 硬限 / 8MB 软限 60 秒）就会被强制断开**。

### Stream（5.0+）

```bash
# 生产消息（* 让 Redis 生成 ID：毫秒时间戳-序号）
redis-cli XADD stream:tasks '*' type tuning siteId 1001
# "1758170000000-0"

redis-cli XLEN stream:tasks
redis-cli XRANGE stream:tasks - +          # 读全部
redis-cli XRANGE stream:tasks - + COUNT 10
redis-cli XREVRANGE stream:tasks + - COUNT 10    # 倒序读最近 10 条

# 创建消费者组（0 表示从头开始消费，$ 表示只消费新消息）
redis-cli XGROUP CREATE stream:tasks group1 0
redis-cli XINFO GROUPS stream:tasks

# 消费者读消息（> 表示只要没投递过的）
redis-cli XREADGROUP GROUP group1 consumer1 COUNT 10 BLOCK 5000 STREAMS stream:tasks '>'

# 确认消费（ACK）
redis-cli XACK stream:tasks group1 1758170000000-0

# 查未确认的消息（PEL：Pending Entries List）
redis-cli XPENDING stream:tasks group1
# 1) (integer) 3                     ← 有 3 条未确认
# 2) "1758170000000-0"               ← 最小 ID
# 3) "1758170005000-0"               ← 最大 ID
# 4) 1) 1) "consumer1" 2) "2"        ← 各消费者的未确认数

redis-cli XPENDING stream:tasks group1 - + 10    # 看具体是哪些消息
redis-cli XCLAIM stream:tasks group1 consumer2 60000 1758170000000-0
#  消费者 consumer2 认领一条「60 秒未确认」的消息

# 截断（控制内存，~ 表示近似，让 Redis 按整块删）
redis-cli XTRIM stream:tasks MAXLEN ~ 1000000
redis-cli XADD stream:tasks MAXLEN ~ 1000000 '*' type tuning    # 写的时候顺便截断

redis-cli XINFO STREAM stream:tasks        # 查看流的完整信息
redis-cli XDEL stream:tasks 1758170000000-0   # 删单条（但不影响 PEL）
```

**Stream 的核心概念**：

| 概念 | 说明 |
|---|---|
| **消息 ID** | `毫秒时间戳-序号`，**单调递增**，所以 Stream 天然有序 |
| **消费者组（Consumer Group）** | 一个组内的多个消费者**分摊**消息（每条消息只给组内一个消费者）；**不同组各读全量**（广播） |
| **PEL（Pending Entries List）** | 已投递但未 `XACK` 的消息。**这就是「处理中队列」的内置实现** |
| **`XCLAIM`** | 认领别人超时未确认的消息 → **这就是「超时回收」的内置实现** |
| **`XAUTOCLAIM`**（6.2+） | `XCLAIM` 的自动版，一次扫描并认领多条 |

**Stream vs Kafka 的功能对照**：

| 能力 | Redis Stream | Kafka |
|---|---|---|
| 持久化 | AOF/RDB（**可能丢 1 秒**） | **磁盘日志**（多副本，`acks=all` 不丢） |
| 分区/分片 | **无**（一个 Stream 就是一个 key，只能在一个节点上） | **Partition**（可任意多，并行消费） |
| 顺序保证 | 全局有序 | **分区内有序**（跨分区无序） |
| 消费者组 | 有 | 有 |
| 消费位点 | 有（ACK + PEL） | 有（offset 提交） |
| 消息回溯 | **支持**（按 ID 重读） | **强支持**（按 offset / 时间重置） |
| 消息保留 | `XTRIM` 手动/自动截断（**按条数**） | **按时间/大小保留**（`retention.ms` / `retention.bytes`） |
| 死信队列 | 无（要自己用 PEL 实现） | 无原生（要自己实现，但有成熟模式） |
| 集群扩展 | **单 key 无法扩展** | **加分区就能扩展** |
| 吞吐 | 万级（受单节点限制） | **十万~百万级** |
| 内存成本 | **数据在内存**（贵） | 数据在磁盘（便宜） |
| 运维 | 简单（已有 Redis） | 要维护 Kafka 集群 + ZK/KRaft |

**Stream 最本质的两个短板**：
1. **数据在内存** —— 消息堆积 1000 万条 × 1KB = 10GB 内存，成本远高于磁盘
2. **无法水平扩展** —— 一个 Stream 是一个 key，在 Cluster 里只能落在一个槽/一个节点上。**加节点不能提升单个 Stream 的吞吐**。这就是 Kafka 有 Partition 而 Stream 没有的根本差异。

### 结论：什么时候用什么

| 场景 | 推荐 |
|---|---|
| 轻量、数据量小、已有 Redis、能容忍偶尔丢消息 | **Stream** |
| 实时通知，丢了无所谓 | Pub/Sub |
| 简易任务分发，可容忍重复和丢失 | List |
| **大吞吐、要可靠、要回溯、要多消费组** | **Kafka** |
| 复杂路由、延迟消息、死信队列 | RabbitMQ / RocketMQ |

**面试结论一句话**：「**Redis 做 MQ 的门槛是「消息量小 + 能容忍内存成本 + 不需要水平扩展」。越过这三条就得上 Kafka。**」
:::

:::拓展
**Kafka 的关键机制（你要能对比着讲，因为你真的用过）**

| 机制 | 说明 |
|---|---|
| **分区（Partition）** | 一个 topic 分成多个 partition，**partition 内有序，跨 partition 无序**。分区数决定并行度 |
| **offset** | 消费者在分区内的位置，**由消费者自己提交**（自动或手动） |
| **消费组（Consumer Group）** | 组内一个分区只被一个消费者消费；**消费者数 > 分区数时多余的消费者空闲** |
| **重平衡（Rebalance）** | 消费者加入/离开时重新分配分区。**重平衡期间消费暂停**（Stop The World），生产环境要避免频繁重平衡 |
| **ISR（In-Sync Replicas）** | 和 leader 保持同步的副本集合。**只有 ISR 都同步了，消息才算 committed** |
| **`acks` 参数** | `0`（不等确认）/ `1`（leader 确认）/ `all`（ISR 全部确认） |
| **高水位（HW）** | 消费者只能读到高水位之前的消息（保证一致性） |
| **幂等生产者** | `enable.idempotence=true`（PID + 序列号去重） |

**关键对比点（面试的加分项）**：

```
Redis Stream 的「位点」是 Redis 内部维护的 PEL（服务端状态）
Kafka 的「位点」是消费者维护并提交的 offset（可以重置、可以回溯）

Redis Stream 的「重试」靠 XCLAIM 手动认领
Kafka 的「重试」靠消费者不提交 offset（下次 poll 会重读）

Redis Stream 的「扩展」只能垂直（单节点）
Kafka 的「扩展」靠加 partition + 加消费者（水平）
```

**「消费位点存在哪」这个差异很重要**：Redis 把 PEL 存在服务端（所以 Redis 要维护「谁在处理哪条消息」的状态，消息堆积会占用额外内存），Kafka 把 offset 存在 `__consumer_offsets` topic 里（所以 Kafka 本身不需要维护「谁在处理哪条」，更轻量）。**这就是「Kafka 更适合大吞吐」的一个底层原因。**

**`XTRIM MAXLEN ~` 里的 `~` 是什么意思**

```bash
redis-cli XTRIM stream:tasks MAXLEN 1000000      # 精确：删到正好 100 万条（可能很慢）
redis-cli XTRIM stream:tasks MAXLEN ~ 1000000    # 近似：按内部节点（radix tree node）整块删
```
**`~` 表示「近似」** —— Stream 底层是 radix tree（每个节点存一批消息），**按节点整块删除比逐条删除快得多**。所以 `~` 的实际结果可能是 100 万零几百条。**生产上一定要用 `~`**，精确截断在大量消息时很慢。

**「Redis 做 MQ」的真实案例：延迟队列**

**Stream 不适合做延迟队列**（不能按时间取）。**延迟队列用 ZSet**（第 3 题）更合适：

```bash
# score = 到期时间戳
redis-cli ZADD delay:queue 1758170100 '{"taskId":"t1"}'

# 轮询取到期的（后台任务每秒钟跑一次）
redis-cli ZRANGEBYSCORE delay:queue 0 1758170000 LIMIT 0 100

# 取出后立即删除（原子性靠 Lua 保证「取+删」）
```
```lua
-- 原子地取出并删除到期任务（避免多个消费端重复取）
local tasks = redis.call('ZRANGEBYSCORE', KEYS[1], 0, ARGV[1], 'LIMIT', 0, ARGV[2])
if #tasks == 0 then return {} end
for i, task in ipairs(tasks) do
    redis.call('ZREM', KEYS[1], task)
end
return tasks
```

**这段 Lua 值得注意的地方**：`ZRANGEBYSCORE` 和 `ZREM` 之间**必须原子**，否则两个消费者会拿到同一批任务。**这是「Lua 解决并发取任务」的经典用法。**
:::

:::追问
**Q：为什么不用 Redis 的 List 做延迟队列？**
因为 List **只能从两端取，没有「按时间排序」的能力**。要做延迟队列必须能「按到期时间取出」，这需要有序结构 → **ZSet**。**这是「数据结构决定能力」的一个典型例子**：选错了结构，功能就实现不了（或者实现得极其别扭）。

**Q：Stream 的消息会一直占内存吗？**
会，**必须主动控制**。三种方式：
1. `XTRIM MAXLEN ~ N`（按条数，用 `~` 近似截断）
2. `XADD` 时带 `MAXLEN ~ N`（写入时顺便截断）
3. **`XDEL` 单条删除**（6.2+ 支持，但**不影响 PEL**——如果消息还在 PEL 里，删了 Stream 里的数据，`XCLAIM` 时会找不到内容）

**注意一个细节**：`XDEL` 删除的消息如果还在某个消费者组的 PEL 里，**PEL 里仍然有这条 ID**（只是对应的内容没了）。所以 `XPENDING` 里会出现「ID 存在但内容为空」的情况。**这是 Stream 的一个不优雅之处。**

**Q：Stream 的消费组能自动负载均衡吗？**
**不会自动均衡。** 组内多个消费者是通过 `XREADGROUP ... '>'` **竞争式地抢新消息**（谁空了谁来拿），一旦某个消费者拿到一批消息，这些消息就归属它（在 PEL 里）。**没有 Kafka 那种「重平衡」机制。** 如果一个消费者处理慢，它的 PEL 会越来越大，**要靠 `XAUTOCLAIM` 手动把超时的消息转移给其他消费者**。

**这也是 Stream 需要「额外维护逻辑」的地方** —— 你需要一个后台任务定期 `XAUTOCLAIM`，否则消费者挂了之后消息就永久卡在它的 PEL 里。**Kafka 不需要这个，因为它的重平衡是协议层自动处理的。**

**Q：你们为什么用 Kafka 不用 Redis Stream？**
**这是你的真实场景，要答得具体**：

「三个原因：
1. **上报量大** —— RRM 是无线资源管理，AP 会持续上报数据，**消息量大，Redis 用内存存队列成本太高**，Kafka 是磁盘持久化，成本差一个量级。
2. **要能回溯** —— 排查问题时需要重新消费历史消息（比如某个场所的数据算错了，要重放），Kafka 的 offset 可以重置，Redis Stream 的 `XTRIM` 截断后就没了。
3. **多消费组** —— 同一个上报数据可能被多个下游消费（rrmcompute 算调优、yw-aioptimize 做 AI 优化），Kafka 的多消费组天然支持，**Redis Stream 虽然也支持多组，但单 Stream 无法水平扩展，吞吐上不去**。」

**这三条正好对应 Kafka 的三个核心优势：磁盘持久化（成本）、offset 可重置（回溯）、分区（水平扩展）。这个回答的结构非常好。**
:::

:::锚点
**这是你最有底气的对比题之一 —— 因为你真的用 Kafka，也真的用 Redis。**

**① 你的真实技术栈**

rrmcontrol 是 **Node.js + Kafka（`10.11.2.111:9092`）+ Redis（`10.11.2.65:6379`）+ MongoDB（`10.11.2.140:27017`）**。RMM 四个微服务 rrmcontrol / rrmserver / rrmcompute / yw-aioptimize 通过 Kafka 传递数据。

**② 「为什么用 Kafka 不用 Redis 队列」的标准答案**（上面追问里那段，可以直接用）

**③ 主动补充一个「职责边界」的判断**

面试话术：「我们架构里 Kafka 和 Redis 的职责是很清楚的：**Kafka 负责『数据流』——可靠传输、可回溯、多消费组；Redis 负责『状态』——缓存和分布式协调。** 这两个不能互换，因为它们的持久化模型完全不同：**Kafka 的数据在磁盘上、有副本、按 offset 可以被多个消费者独立读取；Redis 的数据在内存里、复制是异步的、Stream 的消息一旦被 ACK 和 trim 就没了。**」

「这个边界如果搞混了，会出现两类问题：**把流数据放 Redis → 内存成本爆炸；把状态放 Kafka → 每个消费组都要重放全量历史来恢复状态，效率极低。**」

**这个「数据流 vs 状态」的区分是后端架构的核心概念**，能主动说出来是明显的加分。

**④ 可以真实关联的一个细节：消费者组**

面试话术：「RRM 里同一份 AP 上报数据会被多个下游消费 —— rrmcompute 用来算调优，yw-aioptimize 用来做 AI 优化，**这就是 Kafka 多消费组的典型用法：每个组独立维护 offset，互不影响。** 如果换 Redis Stream 虽然也支持多组，但**单 Stream 无法水平扩展，而上报量是会随接入设备数增长的，这是我们不能接受的。**」

**⑤ 一个诚实的补充**：如果你不确定 Kafka 的具体配置（分区数、副本数、`acks` 设置），**不要编**。可以说：「Kafka 的运维配置是团队统一管的，我主要在用客户端侧 —— 消费、提交 offset、处理重平衡。**配置层面我记得 `acks` 和 `min.insync.replicas` 是保证不丢消息的两个关键参数。**」

**⑥ 如果面试官问「如果用 Redis 做 MQ 你会怎么做」**：

面试话术：「如果一定要用 Redis，我会用 **Stream** 而不是 List，因为 Stream 有 ACK 和消费组。**并且必须配三件事：① `XTRIM MAXLEN ~` 控制内存；② 后台任务定期 `XAUTOCLAIM` 回收超时消息；③ 监控 `XPENDING` 的数量（积压指标）。** 这三件事缺一个都会在生产出问题 —— **`XPENDING` 监控尤其重要，它就是 Redis 版的「消费延迟告警」。**」

**这段回答展示的是「知道用什么」+「知道要配什么监控」**，比单纯说「用 Stream」完整得多。
:::

---

## 19. 线上排查与调优 SOP ★

:::概念
Redis 排查的入口只有三类：**慢查询（`SLOWLOG`）→ 大 key（`--bigkeys`）→ 延迟事件（`LATENCY`）**；手段只有两个：**`INFO` 看指标 + 客户端监控告警**。
记忆钩子：**「卡顿先看慢日志，内存先看 `INFO memory` 和 `--bigkeys`，连接数先看 `CLIENT LIST`——三类现象三个入口。」**
:::

:::提问
- Redis 变慢了怎么排查？
- 常用哪些命令和工具？
- 要监控哪些指标？
- 内存突然涨了怎么定位？
- 连接数暴涨怎么处理？
:::

:::答案
### 排查入口一：慢查询

```bash
redis-cli config get slowlog-log-slower-than    # 10000（微秒 = 10ms）
redis-cli config get slowlog-max-len            # 128（保存的条数，是 List，满了 FIFO 淘汰）

# 调整：生产建议设为 5ms（5000），并把 max-len 调大
redis-cli CONFIG SET slowlog-log-slower-than 5000
redis-cli CONFIG SET slowlog-max-len 1000
redis-cli CONFIG REWRITE

# 查看慢日志
redis-cli SLOWLOG GET 10
# 1) 1) (integer) 12345                       ← 日志 ID
#    2) (integer) 1758170001                  ← 时间戳
#    3) (integer) 253000                      ← 耗时（微秒）= 253ms
#    4) 1) "HGETALL"                          ← 命令
#       2) "site:1001:aps"                     ← 参数
#    5) "10.11.2.100:54321"                    ← 客户端地址
#    6) "app-rrm-1"                            ← 客户端名称（CLIENT SETNAME 设置的）

redis-cli SLOWLOG LEN          # 慢日志条数
redis-cli SLOWLOG RESET        # 清空
```

**注意**：`slowlog-log-slower-than` 的计时**不包含网络传输时间**（只统计命令执行），也**不统计阻塞在排队里的时间**。所以「慢日志里没有慢命令但客户端感觉慢」是可能的 —— 那说明瓶颈在别处（网络、fork、AOF fsync、CPU 竞争）。

**`commandstats` 找 CPU 消耗大户**：

```bash
redis-cli INFO commandstats
# cmdstat_get:calls=9987654,usec=8998765,usec_per_call=0.90,rejected_calls=0,failed_calls=0
# cmdstat_hgetall:calls=12345,usec=5000000,usec_per_call=405.00,rejected_calls=0,failed_calls=0
#                            ^^^^^^^^^^^ 总耗时                     ^^^^^^^^^^^ 单次耗时
# 找：单次耗时高（usec_per_call 大）或总耗时占比高的命令
```

**排序技巧**：
```bash
redis-cli INFO commandstats | grep cmdstat | \
  awk -F'[,=]' '{print $6, $2}' | sort -rn | head -10
# 按「单次调用耗时」排前 10
```

### 排查入口二：大 key

（详见第 14 题，这里只列命令）

```bash
redis-cli --bigkeys -i 0.1          # 按元素数找大 key（生产加 -i 降低压力）
redis-cli --memkeys -i 0.1          # 6.0+ 按内存找大 key
redis-cli --hotkeys                 # 需 LFU 策略，找热点 key
redis-cli MEMORY USAGE <key>        # 已知 key 名，精确查内存
redis-cli OBJECT ENCODING <key>     # 看编码（listpack 还是 hashtable）
redis-cli DEBUG OBJECT <key>        # 看 serializedlength（生产可能被禁用）
rdr keys dump.rdb --memory          # RDB 离线分析（最安全）
```

### 排查入口三：延迟事件

```bash
redis-cli config get latency-monitor-threshold   # 0（默认关闭）
redis-cli CONFIG SET latency-monitor-threshold 100   # 超过 100ms 记录

redis-cli LATENCY LATEST
# 1) 1) "command"                     ← 事件类型
#    2) (integer) 1758170001          ← 最近一次的时间戳
#    3) (integer) 253                  ← 最近一次延迟（毫秒）
#    4) (integer) 890                  ← 历史最大延迟
redis-cli LATENCY HISTORY command    # 某个事件的历史记录
redis-cli LATENCY RESET              # 重置统计
redis-cli LATENCY DOCTYPE            # 帮助

# 客户端侧测延迟
redis-cli --latency                  # 持续采样基准延迟
redis-cli --latency-history          # 分时段看延迟分布（最能看出周期性尖刺）
redis-cli --intrinsic-latency 100    # 测「机器本身」的延迟（排除 Redis）
```

**`--intrinsic-latency` 很关键**：它测的是「进程在 100 秒内最长被阻塞多久」。**如果这个值本身就很高（比如 50ms），说明是操作系统/宿主机的问题（CPU 抢占、内存交换、虚拟化），不是 Redis 的问题。** 这是「先排除环境，再排查应用」的通用原则。

### `INFO` 分区与关键指标

```bash
redis-cli INFO
# 分区：server / clients / memory / persistence / stats / replication / cpu / cluster / keyspace
```

| 分区 | 关键字段 | 怎么看 |
|---|---|---|
| **server** | `redis_version`、`uptime_in_seconds`、`hz`、`config_file` | 版本、运行时长、配置生效情况 |
| **clients** | `connected_clients`、`blocked_clients`、`maxclients` | 连接数是否异常；`blocked_clients` 高 = 有大量阻塞命令 |
| **memory** | `used_memory_human`、`used_memory_rss_human`、`used_memory_peak_human`、`maxmemory_human`、`mem_fragmentation_ratio`、`mem_allocator` | **`mem_fragmentation_ratio < 1` = 在用 swap（最危险）** |
| **persistence** | `rdb_last_bgsave_status`、`aof_last_write_status`、`aof_delayed_fsync`、`rdb_last_cow_size` | 持久化是否健康 |
| **stats** | `keyspace_hits`、`keyspace_misses`、`evicted_keys`、`expired_keys`、`total_connections_received`、`rejected_connections`、`instantaneous_ops_per_sec` | **命中率**、淘汰情况、被拒连接 |
| **replication** | `role`、`connected_slaves`、`master_link_status`、`master_repl_offset`、`slave_repl_offset` | 主从健康与延迟 |
| **cpu** | `used_cpu_sys`、`used_cpu_user` | CPU 消耗趋势 |
| **cluster** | `cluster_enabled` | 是否集群模式 |
| **keyspace** | `db0:keys=1234,expires=567,avg_ttl=0` | 各 db 的 key 数、带过期的 key 数 |

**核心指标的判读**：

```bash
# ① 命中率（最重要）
redis-cli INFO stats | grep -E "keyspace_hits|keyspace_misses"
# 命中率 = hits / (hits + misses)，低于 90% 要排查

# ② 内存
redis-cli INFO memory | grep -E "used_memory_human|used_memory_rss_human|used_memory_peak_human|mem_fragmentation_ratio"
# mem_fragmentation_ratio：
#   1.0 ~ 1.5  正常
#   > 1.5      碎片严重 → 开 activedefrag 或重启
#   < 1        已使用 swap → 性能严重下降，必须立即处理

# ③ 连接
redis-cli INFO clients
# connected_clients:1234
# blocked_clients:5           ← 有 5 个客户端阻塞在 BLPOP/BRPOP 之类
# maxclients:10000
redis-cli INFO stats | grep rejected_connections
# rejected_connections:0       ← >0 说明连接数超过了 maxclients

# ④ 淘汰（内存不够的信号）
redis-cli INFO stats | grep -E "evicted_keys|expired_keys"
redis-cli INFO memory | grep maxmemory_human
```

### 内存暴涨的排查步骤

```bash
# ① 确认是 Redis 自己涨了，还是 RSS 涨了（含碎片）
redis-cli INFO memory
# used_memory  → Redis 分配器统计的数据占用
# used_memory_rss → 操作系统看到的物理内存（含碎片、COW、子进程）

# ② 看 key 数量变化
redis-cli DBSIZE
redis-cli INFO keyspace
# db0:keys=12345678,expires=12000000,avg_ttl=1850000

# ③ 找大 key（最可能的原因）
redis-cli --bigkeys -i 0.1

# ④ 看是不是客户端缓冲区涨了
redis-cli CLIENT LIST
# 注意看 omem（output buffer 内存）和 tot-mem
redis-cli CLIENT LIST | awk '{print $2, $12}' | sort -k2 -rn | head -20

# ⑤ 看是不是 fork/COW 造成的
redis-cli INFO persistence | grep -E "rdb_last_cow_size|rdb_bgsave_in_progress|aof_rewrite_in_progress"

# ⑥ 看内存碎片
redis-cli MEMORY DOCTOR        # 给出建议（诊断结论）
redis-cli MEMORY STATS         # 详细的内存分布
```

**`MEMORY DOCTOR` 的输出示例**：
```
Hi Sam, this instance is empty or is using very little memory, my issues detector
can't do anything in these conditions. Please, leave for your mission on Earth and
fill me with some interesting data, I'm done with this planet.
```
（Redis 的彩蛋文化。真正有问题时会给具体建议，比如「内存碎片率高，建议开启 activedefrag」。）

### 连接数暴涨的处理

```bash
redis-cli CLIENT LIST
# id=1 addr=10.11.2.100:54321 fd=8 name=app-rrm-1 age=3600 idle=0 flags=N db=0 sub=0 psub=0
#                                                          ^^^^^^^^^^  ^^^^^^^
#                                                          age: 连接存活时长  idle: 空闲时长
# multi=-1 qbuf=0 qbuf-free=0 argv-mem=0 obl=0 oll=0 omem=0 tot-mem=20512
#                                            ^^^^^^^^^^^^^^^^^ 输出缓冲区相关
# events=r cmd=get user=default redir=-1 resp=2

# 按客户端 IP 统计连接数
redis-cli CLIENT LIST | grep -o 'addr=[0-9.]*' | sort | uniq -c | sort -rn | head

# 按连接名（如果客户端设置了 CLIENT SETNAME）统计
redis-cli CLIENT LIST | grep -o 'name=[^ ]*' | sort | uniq -c | sort -rn

# 杀掉指定的客户端
redis-cli CLIENT KILL ID 12345
redis-cli CLIENT KILL ADDR 10.11.2.100:54321
redis-cli CLIENT KILL TYPE normal        # 杀所有普通客户端（危险）
redis-cli CLIENT KILL MAXAGE 3600        # 杀存活超过 1 小时的连接
```

**连接数暴涨的四个常见原因**：
1. **应用侧连接池泄漏** —— 拿了连接没归还（`finally` 忘了，和锁忘记释放是同一类 bug）
2. **应用侧没复用连接** —— 每次请求新建连接（性能灾难）
3. **空闲连接没有回收** —— `timeout` 设成 0（默认不超时），连接累积
4. **某个客户端在快速重连** —— 通常是它自己出错了（如 `READONLY You can't write against a read only replica`）

```bash
# 相关配置
redis-cli config get timeout          # 0（默认，客户端空闲不断开；建议设 300）
redis-cli config get tcp-keepalive    # 300
redis-cli config get maxclients       # 10000（还要看 ulimit -n）
redis-cli config get client-output-buffer-limit
# normal 0 0 0
# replica 268435456 67108864 60
# pubsub 33554432 8388608 60
```

**`client-output-buffer-limit` 的三个类别**：
- `normal`：普通客户端（默认不限，**风险** —— 一个慢客户端可能吃光内存，建议设 `normal 256mb 64mb 60`）
- `replica`：从节点（默认硬限 256MB）
- `pubsub`：Pub/Sub 客户端（默认 32MB 硬限）

### 慢查询 → 大 key → fork → 磁盘 → swap 的排查链

**面试要能按这个顺序往下走**：

```
现象：客户端 P99 变高
  ① 查慢日志
     SLOWLOG GET 100 → 有慢命令？
       有 → 是哪类命令？
               KEYS/HGETALL/SMEMBERS 大 key 操作 → 查大 key（--bigkeys）
               DEL 大 key → 改用 UNLINK
               Lua 脚本 → 检查脚本逻辑
               SORT/ZUNIONSTORE → 业务侧优化
       没有 → 往下走
  ② 查 fork（周期性的延迟尖刺，周期 = save 间隔或 AOF 重写）
     INFO stats | grep latest_fork_usec
     INFO persistence | grep rdb_last_cow_size
  ③ 查 AOF fsync
     INFO persistence | grep aof_delayed_fsync
  ④ 查 swap（最隐蔽）
     INFO memory | grep mem_fragmentation_ratio    → < 1 就是在用 swap
     free -h                                       → 系统 swap 使用量
  ⑤ 查 CPU 竞争
     INFO cpu
     top -p $(pgrep redis-server) → 看是 Redis 自己 CPU 高，还是被别的进程抢
     用 --intrinsic-latency 100 排除宿主机问题
  ⑥ 查网络
     redis-cli --latency          → 基准延迟
     如果是跨机房访问 → 网络 RTT 就是瓶颈，考虑就近部署
```

**这个排查链的价值在于「顺序」** —— 从「最可能是自己代码问题」到「最可能是环境问题」，每一步都能排除一类原因。
:::

:::拓展
**必须监控的指标清单（生产上线 checklist）**

| 类别 | 指标 | 告警阈值建议 |
|---|---|---|
| 可用性 | `redis_up`（能否 ping 通） | 立即告警 |
| 延迟 | `redis_commands_duration_seconds`（P99） | > 10ms |
| 内存 | `used_memory / maxmemory` | > 80% |
| 内存 | `evicted_keys` 增速 | > 0 就值得关注 |
| 内存 | `mem_fragmentation_ratio` | > 1.5 或 **< 1** |
| 命中率 | `keyspace_hits / (hits + misses)` | < 90% |
| 连接 | `connected_clients / maxclients` | > 80% |
| 连接 | `rejected_connections` | > 0 |
| 阻塞 | `blocked_clients` | 突增 |
| 持久化 | `rdb_last_bgsave_status` / `aof_last_write_status` | != ok |
| 持久化 | `aof_delayed_fsync` | 增长 |
| 复制 | `master_link_status` | != up |

**工具链**：
- **`redis_exporter`**（Prometheus 官方推荐的 Redis exporter）+ Prometheus + Grafana
- **云托管自带的监控**（腾讯云/阿里云 Redis 控制台有内置的指标和告警）
- **应用侧监控**（Micrometer / Spring Boot Actuator 的 Redis 指标，能看到「客户端视角」的延迟）
- **`redis-cli --stat`**（命令行实时面板，临时排查用）

```bash
redis-cli --stat
# ------- data ------ --------------------- load -------------------- - child -
# keys       mem      clients blocked requests            connections
# 1234567    1.85G    42      0       987654321 (+12)     1234
# 每秒钟刷新一次，快速看趋势
```

**`MONITOR` 命令（慎用）**

```bash
redis-cli MONITOR
# 打印所有命令（含来自从节点/其他客户端的）
```
**生产禁用理由**：① 每个命令都要复制一份给监控客户端，**吞吐量下降明显**；② 输出量巨大，**容易打爆监控端的缓冲区**（而且这个客户端属于 `normal` 类别，会占内存）；③ 命令里可能含敏感数据（`AUTH` 密码、业务数据）。**临时排查可以用，但必须限时（几秒钟）且用 `timeout` 自动退出。**

**内存碎片整理（`activedefrag`）**

```bash
redis-cli config get activedefrag                  # no（默认关闭，4.0+ 支持）
redis-cli config get active-defrag-ignore-bytes    # 100mb（碎片小于这个不整理）
redis-cli config get active-defrag-threshold-lower # 10（碎片率低于 10% 不整理）
redis-cli config get active-defrag-threshold-upper # 100
redis-cli config get active-defrag-cycle-min       # 5（最低占用 5% CPU）
redis-cli config get active-defrag-cycle-max       # 75（最高占用 75% CPU）

# 开启（内存碎片率高时）
redis-cli CONFIG SET activedefrag yes
redis-cli CONFIG REWRITE
```

**原理**：**在线做内存整理**（把分散的小块内存合并成大块），由主线程在空闲时间片做。**代价是消耗 CPU**（所以有 `cycle-min/max` 控制占用比例）。**收益是 `mem_fragmentation_ratio` 下降、RSS 回落。**

**触发时机**：`mem_fragmentation_ratio > 1.5` 且碎片总量超过 `active-defrag-ignore-bytes`（100MB）。
:::

:::追问
**Q：`SLOWLOG` 里没有慢命令，但客户端感觉很慢，可能是什么原因？**
四个方向（按概率）：
1. **网络 RTT** —— 跨机房访问，每次命令的往返延迟就有几十毫秒。**用 `redis-cli --latency` 从应用机器上测**。
2. **fork 造成的周期性尖刺** —— fork 阻塞主线程时，命令在排队但没被执行，所以不计入慢日志。**看 `latest_fork_usec`**。
3. **AOF fsync 阻塞** —— `everysec` 策略下，如果 fsync 卡住，主线程会等。**看 `aof_delayed_fsync`**。
4. **客户端侧问题** —— 连接池耗尽（拿不到连接要等）、客户端 GC、线程池满。**这个最容易误判成「Redis 慢」**。

**判断方法**：在**应用机器上**跑 `redis-cli --latency -h <redis>`。如果这里也慢，是网络或 Redis；如果这里快但应用慢，是**应用侧的问题**（连接池、GC、线程）。

**Q：`evicted_keys` 一直在涨怎么办？**
说明内存不够，缓存在被持续淘汰。**三层处置**：
1. **短期**：确认 `maxmemory-policy` 是不是预期的（`allkeys-lru`）；如果是 `noeviction` 则会出现写报错而不是淘汰
2. **中期**：**找出占内存最多的是什么**（`--bigkeys`、RDB 离线分析）→ 治理大 key / 加 TTL / 拆分
3. **长期**：扩容（加内存或上 Cluster）

**注意**：`evicted_keys` 本身不是坏事（缓存的正常机制），**关键是看它是否导致命中率下降**。如果淘汰的是冷数据、命中率稳定，那是健康的；如果命中率跟着掉，说明热数据在被淘汰。

**Q：`blocked_clients` 高说明什么？**
说明有很多客户端阻塞在**阻塞命令**上（`BLPOP`、`BRPOP`、`BLMOVE`、`XREAD BLOCK`、`WAIT`）。**可能的原因**：
1. **这是正常的** —— 如果有 100 个消费者在 `BRPOP` 等任务，`blocked_clients` 就是 100
2. **任务生产不足** —— 消费者太多但没消息，全在等
3. **`WAIT` 命令用多了** —— 每个 `WAIT` 都会把客户端标记为 blocked

**关键**：`blocked_clients` 本身**不占用 CPU**（Redis 在等待时不消耗资源），但**占用连接**。所以要看它是否接近 `maxclients`。

**Q：怎么确认线上跑的是哪个版本的 Redis？**
```bash
redis-cli INFO server | grep -E "redis_version|redis_mode|os|arch_bits|multiplexing_api"
# redis_version:7.2.4
# redis_mode:standalone
# os:Linux 5.15.0-91-generic x86_64
# arch_bits:64
# multiplexing_api:epoll
```
**这个和你们核对镜像里文件 md5 是一个思路** —— **确认线上到底是什么状态，而不是相信「应该是什么」。** 面试时如果聊到排查方法，这个类比很加分。
:::

:::锚点
**这段你有真实的方法论可以迁移，要重点用。**

**① 你的排查 SOP 是从 rrmcompute OOM 里长出来的**

面试话术：「我排查线上问题有一套固定的顺序：**先确认现象归属（是应用抛错还是被外部杀掉）→ 再看实时指标（不看配置，看数字）→ 再定位到具体的代码或数据 → 最后处置 + 加防线。** 这个方法是从 rrmcompute 现网 OOM 的排查里形成的 —— **那次的关键教训是：日志里没有 `OutOfMemoryError` 栈（说明不是 JVM 抛的，是 cgroup 杀的进程），所以第一步『确认现象归属』比什么都重要。**」

**② 套用到 Redis 上**

面试话术：「同样的顺序用到 Redis 上：
- **第一步确认现象归属**：是 Redis 自己慢，还是网络慢，还是应用侧慢（连接池、GC）？**`--intrinsic-latency` 排除宿主机、`--latency` 从应用机器上测，两步就能定位。**
- **第二步看实时指标**：`INFO memory`、`INFO stats`，**先看 `mem_fragmentation_ratio`（< 1 说明在用 swap，这是最危险也最隐蔽的情况）**，再看命中率和 `evicted_keys`。
- **第三步定位到具体的 key**：`--bigkeys` 或者慢日志里反复出现的 key。
- **第四步处置 + 加防线**：治完加监控告警，让同样的故障下次能提前发现。」

**③ 把「加防线」这一步讲实**

面试话术：「rrmcompute 那次我们不只是把内存从 5Gi 调到 5.5GiB —— **还加了 API 侧的资源限制和堆使用率告警**。**这个习惯我用在 Redis 上就是：所有缓存 key 必须带 TTL、监控命中率和 `evicted_keys`、定期跑 `--bigkeys` 巡检。** 我不太相信『一次修好』，**我更相信『修好 + 能发现复发』。**」

**④ 一个非常真实的短板要坦白**

面试话术：「我的排查工具主要用 `INFO`、`SLOWLOG`、`--bigkeys`、`CLIENT LIST` 这几个。**像 `LATENCY MONITOR`、`MEMORY DOCTOR`、`MEMORY STATS` 这些我知道但没在真实故障里用过。** 而且我们的 Redis 是腾讯云托管，**能看到控制台的监控，但 `DEBUG` 这类命令是禁用的。**」

**⑤ 转 Java 后的一个实际变化（重要）**

面试话术：「从 Node.js 转到 Java，Redis 的排查视角有一个变化：**Node.js 的 ioredis 客户端会暴露连接状态和重连事件，排查时能直接看到客户端视角的问题；而 Java 的 Lettuce/Jedis 走连接池，很多问题（连接泄漏、池耗尽）表现为『请求等待』而不是『Redis 报错』。** 所以我现在的习惯是**两端都要看**：Redis 侧看 `connected_clients` 和 `CLIENT LIST`，应用侧看连接池的活跃连接数和等待时间 —— **这两边的数字必须对得上，对不上就说明有问题。**」

**这个「两端对账」的思路很专业** —— 它体现的是「同一个系统在不同视角下的观测必须一致」这个工程直觉。**面试官如果是做基础架构的，会非常认可。**
:::

---

> 📌 **本文档使用方式**：默认折叠答案，先自己回答「面试官会怎么问」，再点开对照。
> 手机上建议开启**自测模式**（答案按钮变灰），逐题过；连续两遍能说全，就可以上考场了。
>
> **答不出来的优先级**：第 12 题（分布式锁，你有真实场景）> 第 14 题（大 key，原文档的空白）> 第 3/4 题（数据结构 + 内存）> 第 9/10 题（击穿雪崩）> 第 5/6 题（持久化）> 其余。
> **必背三句话**：① 「单线程执行命令，所以单条命令原子」；② 「NX 防并发、PX 防死锁、唯一值防误删、Lua 保原子」；③ 「缓存和 DB 的强一致做不到，因为两个系统无法原子提交」。
