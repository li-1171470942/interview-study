# 学习手册_21_RRM无线资源管理_场景模式库.md

> **来源**：D:\l32524\projects\rrmProject\ 源码 + 文档
> **炼化日期**：2026-09-04
> **对标**：学习手册_19_并发场景模式库
> **待确认**：⚠️ 部分代码细节需结合实际代码确认，以下为基于文档的炼化

---

## 头部：材料清单

| 材料 | 路径 | 说明 |
|------|------|------|
| 云AP Netconf下发文档 | `docs/云AP调优Netconf下发格式.md` | v1.0, 2026-08-04 |
| 分布式RRM同步工具 | `docs/syncDistributedRrm_进度报告.md` | 2026-07-10~13 |
| 同步工具源码 | `rrmcontrol/src/controllers/AI-RRM/apis/syncDistributedRrm.js` | 核心同步逻辑~380行 |
| 四分支对比文档 | `docs/四分支对比分析_以acceptance为准_20260817.md` | 分支管理经验 |

---

## 模式一：异步消息 → 同步RPC补偿（Kafka消费可靠性）

### 【一句话】
Kafka消费失败时如何保证消息不丢失且最终一致？

### 【业务触发】
RRM系统中，设备侧调优结果通过Kafka消息（optType=45）上报到rrmserver。
若消费失败（网络抖动/服务重启），调优结果丢失，用户看到的状态与实际不符。

**代码位置**：`rrmserver/src/controllers/procKafka/procCRA.js`

### 【代码形态】
```javascript
// Kafka消费核心模式
async function processMessage(msg) {
    try {
        const data = JSON.parse(msg.value.toString());
        await processClbResult(data);
        // 手动提交offset，确保处理后才提交
        consumer.commitMessage(msg);
    } catch (err) {
        // 失败不走commit，消息不会被ack，会重新投递
        log.error(`消费失败: ${err.message}, 将重试`);
        // 可选：写入死信队列(DLQ)供后续人工处理
        await sendToDLQ(msg, err);
    }
}
```

### 【知识点串】
- **At-Least-Once**：手动commit确保处理后才确认
- **幂等消费**：数据库唯一索引防止重复处理
- **DLQ设计**：死信队列兜底，避免消息积压
- **重试策略**：指数退避，避免雪崩

### 【面试话术】
> "RRM的调优结果上报走Kafka，我接手时遇到过一个经典问题——消息消费失败后用户看到状态不对。后来我加了手动offset提交和死信队列：消费成功才commit，失败不commit会自动重投，重投3次还失败就进DLQ。同时在MongoDB的clbDetail表加了(taskId, apSN, RI)唯一索引，即使重复消费也不会写脏数据。"

### 【高频追问】

| 层次 | 追问 | 答案要点 |
|------|------|----------|
| 表层 | Kafka怎么保证消息不丢？ | 生产者确认(acks=all) + 消费者手动commit + 分区副本 |
| 原理 | 消费者自动提交offset的问题？ | 自动提交是按时间，不是按处理成功，可能丢消息 |
| 陷阱 | 重试导致重复消费怎么办？ | 幂等设计：数据库唯一索引 / 消息去重表 / 业务状态机判断 |
| 开放 | 如果要保证 Exactly-Once 呢？ | 事务性生产者 + 消费者幂等，或业务层去重 |

---

## 模式二：分布式锁防竞态（定时任务并发控制）

### 【一句话】
分布式环境下定时任务如何防止多实例重复执行？

### 【业务触发】
新AP上线触发调优（newApUpScheduler每60秒扫描）。K8s部署了多副本pod，如果不做并发控制，同一个shop的调优可能被多个pod同时触发。

**代码位置**：`rrmcontrol/src/controllers/AI-RRM/service/newApUpService.js` 的 `triggerClbForShop`

### 【代码形态】
```javascript
async function triggerClbForShop(shopId) {
    // 1. 获取分布式锁（Redis setNX + 过期时间）
    const lockKey = `newApClb:lock:${shopId}`;
    const lockValue = Date.now().toString();
    const acquired = await redis.set(lockKey, lockValue, 'EX', 300, 'NX');
    
    if (!acquired) {
        log.info(`shop=${shopId} 已被其他实例锁定，跳过`);
        return;
    }
    
    try {
        // 2. ⚠️ 关键：二次检查开关状态（防竞态）
        const switchStatus = await judgeAutoSwitch(shopId);
        if (!switchStatus) {
            log.info(`shop=${shopId} 自动调优已关闭，跳过`);
            return;
        }
        
        // 3. 执行业务逻辑
        await executeClbForShop(shopId);
    } finally {
        // 4. 释放锁
        await redis.del(lockKey);
    }
}
```

### 【知识点串】
- **Redis分布式锁**：SET + NX + EX 原子性获取
- **锁超时设计**：EX 300秒防止死锁（业务执行时间 < 300秒）
- **竞态窗口**：入队→执行之间用户关闭开关的竞态
- **二次检查**：获取锁后再次验证业务状态

### 【面试话术】
> "K8s多副本部署时，定时任务会并发执行同一个逻辑。我用Redis分布式锁解决：set NX获取锁，设300秒过期防止死锁。但这里有个坑——锁住之后到真正执行之间，用户可能把开关关了，所以我又在锁内加了二次检查judgeAutoSwitch。这其实是一个经典的'检查-执行'竞态问题，单靠锁不够，还得业务层再验证一次。"

### 【高频追问】

| 层次 | 追问 | 答案要点 |
|------|------|----------|
| 表层 | Redis分布式锁怎么实现？ | set key value NX EX 300，或 SETNX + EXPIRE |
| 原理 | 锁过期了业务还没执行完怎么办？ | 看门狗续期 / 锁粒度细化 / 业务补偿 |
| 陷阱 | Redis主从切换时锁丢了？ | Redlock算法 / Redisson实现 / 或接受最终一致性 |
| 开放 | 如果不用Redis用什么？ | Zookeeper / etcd / 数据库唯一索引 |

---

## 模式三：跨库数据同步（配置一致性）

### 【一句话】
两个服务各自维护同一份配置时，如何做一次性全量同步？

### 【业务触发】
AI RRM（我们）和 xmlconfmgr（另一个微服务）各自维护一份"分布式RRM开关"配置。需要把xmlconfmgr的配置同步到我们这边，统一管理。

**代码位置**：`rrmcontrol/src/controllers/AI-RRM/apis/syncDistributedRrm.js`

### 【代码形态】
```javascript
async function syncDistributedRrm() {
    // 1. 直连下游MongoDB（绕过HTTP网关权限问题）
    const xmlconfmgrDB = await connectMongo('xmlconfmgr', 'xmlconfmgr');
    const apgroupDB = await connectMongo('oasis-apgroup-manager', 'oasis-apgroup-manager');
    
    // 2. 场所级同步（shopId维度）
    const shopConfigs = await xmlconfmgrDB
        .collection('rrm_globalcfg_shop_config')
        .find({ $or: [{ isActive: true }, { isActive: { $exists: false } }] })
        .toArray();
    
    // 3. 逐条处理，按RRMStatus同步到autoSwitch/autoOptConfig
    for (const config of shopConfigs) {
        const { shopId, RRMStatus } = config;
        
        if (RRMStatus === 'true') {
            // 全开配置
            await upsertAutoSwitch(shopId, true);
            await upsertAutoOptConfig(shopId, SELF_DEC_ALL_ON);
        } else {
            // 全关配置，检查其他模式是否开着
            await upsertAutoOptConfig(shopId, SELF_DEC_ALL_OFF);
            const shouldKeepOpen = await checkOtherModes(shopId);
            if (!shouldKeepOpen) {
                await updateSwitchStatus(shopId, false);
            }
        }
    }
    
    // 4. 修改行数校验（幂等性保证）
    const result = await autoSwitchDB.updateOne(filter, update);
    if (result.modifiedCount === 0) {
        throw new Error('配置更新失败，可能数据不存在');
    }
}
```

### 【知识点串】
- **直连MongoDB**：绕过HTTP网关的权限限制
- **幂等设计**：$or 查询处理字段缺失的老数据 + modifiedCount校验
- **Upsert模式**：存在则更新，不存在则创建
- **全量扫描**：一次性同步，不依赖增量CDC

### 【面试话术】
> "两个微服务各自维护同一个配置，数据不一致了。我的解法是做了一个一次性同步工具：直连下游的MongoDB扫全量数据，然后按配置状态更新我们这边的表。实现时有两个坑——第一是下游的HTTP接口有权限限制，改成直连MongoDB绕过；第二是幂等性，老数据没有isActive字段，查询条件要改成$or兼容。最后加了modifiedCount校验，确保真正更新了才认为成功。"

### 【高频追问】

| 层次 | 追问 | 答案要点 |
|------|------|----------|
| 表层 | 怎么实现幂等更新？ | updateOne + modifiedCount校验 / 唯一索引冲突 |
| 原理 | 全量同步和增量同步的区别？ | 全量：数据量大时资源占用高；增量：依赖CDC/时间戳 |
| 陷阱 | 同步过程中数据又被改了怎么办？ | 乐观锁版本号 / 分布式事务 / 业务补偿 |
| 开放 | 如果要做实时同步呢？ | Change Stream / 消息队列 / binlog订阅 |

---

## 模式四：位掩码状态压缩（多频段开关）

### 【一句话】
3个频段×3种开关，如何用1个数字表示所有组合？

### 【业务触发】
云AP的实时调优开关（2.4G/5G/6G各有权道/功率/带宽开关）需要下发给设备。用位掩码将12个布尔压缩成3个数字。

**代码位置**：`autoOptService.js:937-953`

### 【代码形态】
```javascript
// 位掩码计算
const ChlClbMode = 
    (bandConfig['2.4GHz'].Ch ? 1 : 0) * 1 +   // 2.4G = 第0位 = 1
    (bandConfig['5GHz'].Ch ? 1 : 0) * 2 +     // 5G   = 第1位 = 2
    (bandConfig['6GHz'].Ch ? 1 : 0) * 4;      // 6G   = 第2位 = 4

// 例如：2.4G开+5G开+6G关 = 1 + 2 = 3
// 例如：3个频段全开 = 1 + 2 + 4 = 7
```

### 【知识点串】
- **位运算**：或/与/移位
- **状态压缩**：12个布尔 → 3个数字，网络传输量减少75%
- **位掩码优点**：可单独开关某位，可用单一值表示所有组合

### 【面试话术】
> "云AP有3个频段，每个频段有3种调优开关，如果分别传要12个参数。我用位掩码压缩：2.4G占第0位(权重1)，5G占第1位(权重2)，6G占第2位(权重4)。三个全开就是7，一个都不开就是0。设备收到后用按位与就能判断每个频段是否开启。"

### 【高频追问】

| 层次 | 追问 | 答案要点 |
|------|------|----------|
| 表层 | 位掩码有什么好处？ | 节省存储/传输、单一值表示多状态、位运算高效 |
| 原理 | 怎么单独关闭某个频段？ | 与掩码取反做或运算，如 `mode | 2` 强制开5G |
| 陷阱 | 超过8种状态怎么办？ | 扩展位数 / 改用字符串枚举 |
| 开放 | 还有什么场景适合位掩码？ | 权限位图、配置标志、状态码压缩 |

---

## 模式五：设备通信协议适配（云AP vs AC）

### 【一句话】
同一业务逻辑如何适配不同设备的不同协议？

### 【业务触发】
RRM需要同时支持AC设备和云AP，两者Netconf下发格式不同：
- AC：一条netconf含多AP数据
- 云AP：每AP单独一条netconf（并发500）

**代码位置**：`autoOptService.js` 的 `cloudAPsetProConfig`

### 【代码形态】
```javascript
async function sendToDevice(deviceType, configs) {
    if (deviceType === 'ac') {
        // AC：批量下发，一条含多AP
        await sendACConfig(configs);
    } else if (deviceType === 'cloudap') {
        // 云AP：每AP单独下发，并发控制
        await async.mapLimit(configs, 500, async (config) => {
            await sendCloudAPConfig(config);
        });
    }
}
```

### 【知识点串】
- **适配器模式**：统一接口，不同实现
- **并发控制**：async.mapLimit限制并发数
- **超时熔断**：总超时20秒自动停止

### 【面试话术】
> "RRM要同时支持AC和云AP两种设备，但它们的netconf格式完全不同。AC是一批AP放一条消息，云AP是每AP单独一条。我用适配器模式封装了差异，上层业务代码不用关心设备类型。并发方面，云AP要并发下发500个，我用了async.mapLimit控制，同时加了总超时20秒的熔断保护，防止设备响应慢时资源耗尽。"

### 【高频追问】

| 层次 | 追问 | 答案要点 |
|------|------|----------|
| 表层 | 怎么控制并发数？ | async.mapLimit / Promise池 / 信号量 |
| 原理 | 超时了怎么处理？ | 记录超时AP、返回部分成功、触发告警 |
| 陷阱 | 500并发会不会打爆设备？ | 分批下发 + 设备能力上报 + 降级策略 |
| 开放 | 如何监控下发成功率？ | 埋点统计成功/失败/超时，告警通知 |

---

## 附录：RRM项目数字锚点表

| 数字 | 来源故事 |
|------|----------|
| 60秒 | newApUpScheduler扫描间隔，每分钟检查一次新AP |
| 500 | 云AP并发下发上限，控制单批次请求量 |
| 20秒 | 云AP下发总超时，熔断保护 |
| 3频段 | 2.4G/5G/6G，WiFi7新增6GHz支持 |
| 4微服务 | rrmcontrol/rrmserver/rrmcompute/aioptimize |
| 289个 | AT环境扫描到的云AP autoSwitch记录 |
| 239/25 | 开启/关闭实时调优的AP数量比例 |

---

## 附录：技术债清单

| # | 技术债 | 位置 | 改法 |
|---|--------|------|------|
| 1 | 下游MongoDB连接信息未同步更新 | syncDistributedRrm.js | 依赖wlanpub配置，需确认连接地址 |
| 2 | 云AP功率范围硬编码上限 | RFservice.js | 应从设备能力上报获取 |
| 3 | 四分支同步依赖人工cherry-pick | - | 考虑CI自动化同步流水线 |

---

*本手册基于 D:\l32524\projects\rrmProject\ 文档炼化，部分代码细节待结合源码确认*
