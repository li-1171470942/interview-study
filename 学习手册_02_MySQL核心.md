# 📘 学习手册 02 · MySQL 核心

> 配套《面试八股复习计划》第 2 节 MySQL 部分 + PDF 第 36-48 页
> 结构：**概念（常显）→ 面试官会怎么问（常显）→ 答案与原理（点开）→ 拓展 + 追问 + 项目锚点**
> 索引 / 事务 / MVCC / 锁 / 日志五块是命门；全文含可直接执行的 SQL 与真实排查 SOP

---

## 1. 什么情况索引会失效（讲透「为什么」）

:::概念
索引失效不是玄学——**本质是 B+ 树没法用「有序性」定位到你要的那段区间**。归纳成三类：
① **破坏排序结构**（违反最左前缀、前导模糊 `%x`）；② **索引列被加工**（函数、运算、隐式类型转换）；③ **优化器算完代价觉得全表扫更便宜**（区分度低、回表成本高、统计信息不准）。
记忆钩子：**「结构 / 加工 / 代价」三分类**，比零散背场景稳。
:::

:::提问
- 什么情况下索引会失效？说几个。
- `LIKE '%abc'` 为什么失效？`LIKE 'abc%'` 为什么可以？
- 隐式类型转换一定会失效吗？`WHERE id = '1'`（id 是 int）会不会？
- 为什么性别、状态这种字段建了索引也用不上？
- `!=`、`NOT IN` 是不是一定不走索引？
- 加了索引但还是走了全表扫，你怎么排查？
:::

:::答案
### 一、核心判据：能不能在 B+ 树里二分定位

联合索引 `(a,b,c)` 在 B+ 树里的排序规则是：**先按 a 排，a 相同按 b 排，b 相同再按 c 排**。
所以只有拿到 a 的等值条件，才能确定 b 的「有序区间」在哪一段。跳过 a 直接 `WHERE b = 2`，b 在整棵树里是**分段有序、整体无序** → 无法二分 → 只能扫全部叶子节点。

```sql
-- 建表（后面所有例子都用它）
CREATE TABLE `t_user` (
  `id`         BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  `name`       VARCHAR(50)     NOT NULL,
  `phone`      VARCHAR(20)     NOT NULL,          -- 注意：字符串类型
  `age`        INT             NOT NULL,
  `sex`        TINYINT         NOT NULL,          -- 区分度极低
  `city`       VARCHAR(30)     DEFAULT NULL,
  `created_at` DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `idx_name_age_city` (`name`, `age`, `city`),
  KEY `idx_phone` (`phone`),
  KEY `idx_created_at` (`created_at`),
  KEY `idx_sex` (`sex`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
```

### 二、六类失效场景：为什么 + 怎么改

| 场景 | 例子 | 为什么失效 | 正确写法 |
|---|---|---|---|
| **违反最左前缀** | `idx_name_age_city`，`WHERE age=20` | age 在树里整体无序 | 补上 `name`，或另建 `(age)` 索引 |
| **前导模糊** | `WHERE name LIKE '%鑫'` | 无法确定起始键值，只能从头扫 | `LIKE '鑫%'`；全文场景用全文索引/ES |
| **函数作用于索引列** | `WHERE YEAR(created_at)=2026` | 树里存的是原始值，不是 `YEAR()` 的结果 | 改成范围：`created_at >= '2026-01-01' AND created_at < '2027-01-01'` |
| **列参与运算** | `WHERE age + 1 = 21` | 同上，运算后与索引值无对应关系 | 移项：`WHERE age = 20` |
| **隐式类型转换（列侧）** | `phone` 是 varchar，`WHERE phone = 13800138000` | MySQL 把 **列** 转成数字再比：`CAST(phone AS DOUBLE) = 13800138000`，等于对列用函数 | `WHERE phone = '13800138000'` |
| **OR 连接无索引列** | `WHERE name='a' OR city='b'`（city 无索引） | 要判断 city 只能全表扫，OR 整体无法只用 name 索引 | 给 city 建索引（可走 index_merge），或拆成两条 `UNION ALL` |

### 三、隐式转换有「方向性」——这是最容易被追问的点

**结论：把「列」转成别的类型 → 失效；把「常量」转成列的类型 → 不失效。**

| 写法 | 列的转换方向 | 是否失效 |
|---|---|---|
| `phone = 13800138000`（phone 是 varchar） | 列 `phone` → DOUBLE | ❌ **失效** |
| `id = '1'`（id 是 int） | 常量 `'1'` → INT | ✅ **不失效** |
| `phone = '13800138000'` | 无需转换 | ✅ 不失效 |

原因：MySQL 的比较规则是「**两边都是字符串就按字符串比，只要有一边是数字就都按数字比**」。列一旦被转成数字，索引里存的原字符串值就对不上了。

验证方式：

```sql
-- 在 EXPLAIN 的 warning 里能看到优化器改写后的样子
EXPLAIN SELECT * FROM t_user WHERE phone = 13800138000;
SHOW WARNINGS\G
-- 输出里会出现：where cast(t_user.phone as double) = 13800138000
```

### 四、字符集/排序规则不同导致的失效（联合查询里的隐形杀手）

两张表 JOIN，关联列一个是 `utf8mb4`、一个是 `utf8`（或 `utf8mb4_general_ci` vs `utf8mb4_0900_ai_ci`），MySQL 需要先做字符集转换再比较 → **等于在列上套了一层转换函数** → 被驱动表的索引失效。

```sql
-- 排查：看字符集和排序规则是否一致
SELECT TABLE_NAME, COLUMN_NAME, CHARACTER_SET_NAME, COLLATION_NAME
FROM information_schema.COLUMNS
WHERE TABLE_SCHEMA = 'your_db' AND COLUMN_NAME = 'order_no';

-- 修：统一字符集
ALTER TABLE t_order MODIFY COLUMN order_no VARCHAR(32)
  CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci NOT NULL;
```

**MySQL 8.0 的默认字符集已经从 `latin1` 改成 `utf8mb4`、默认排序规则改成 `utf8mb4_0900_ai_ci`**，所以 5.7 升级到 8.0 时，老表的 `utf8mb4_general_ci` 和新表的 `utf8mb4_0900_ai_ci` 混用会造成 JOIN 失效，这是升级期最典型的一类「索引莫名失效」。

### 五、`!=` / `NOT IN` / `IS NOT NULL`：不是「一定失效」，是「代价高」

这三种常被说成「绝对失效」，其实是**优化器基于代价决定**：

- `!=`：等价于两个区间 `(-∞, val)` 和 `(val, +∞)`，可以走索引，但要扫的叶子页很多。若 `val` 的区分度很高（比如 `id != 1`），优化器大概率直接全表扫。
- `NOT IN`：同 `!=`；**并且子查询里如果有 NULL，结果集永远为空**（见第 7 题），这是另一个坑。
- `IS NOT NULL`：可空列上「非 NULL 的行」占比很大时，回表次数太多，优化器倾向全扫；`IS NULL` 反而常常走索引（NULL 值在索引里占比小）。

判断标准只有一条：**满足条件的行数占全表比例**。经验阈值大约在 **20%~30%** 以上时，优化器倾向于放弃索引走全表扫。

```sql
-- 看真实行数占比
SELECT COUNT(*) FROM t_user WHERE sex != 1;   -- 9000
SELECT COUNT(*) FROM t_user;                  -- 10000  → 90%，必然全扫
```

### 六、优化器主动放弃索引（最容易被误判为「索引失效」）

| 原因 | 具体表现 | 处置 |
|---|---|---|
| **区分度太低** | `sex` 只有 0/1，走索引回表 5000 次，不如直接全表扫 | 别建这种单列索引；需要时建联合索引（如 `(status, created_at)`） |
| **回表成本 > 全表扫** | 二级索引要「先拿主键再回表」，随机 IO 多 | 用覆盖索引消除回表；或做延迟关联（见第 6 题） |
| **统计信息不准** | 大批量写入/删除后，`SHOW INDEX` 的 `Cardinality` 严重失真 | `ANALYZE TABLE t_user;` 重新采样 |
| **索引选择度估算错误** | 优化器预判走索引要扫的行更多 | 用 `FORCE INDEX` 临时验证（**只在确认后短用，不要长期写死**） |

```sql
-- 看基数（Cardinality）判断区分度：越接近行数越好
SHOW INDEX FROM t_user;
-- 重新收集统计信息
ANALYZE TABLE t_user;
-- 强制走索引做对比验证
SELECT * FROM t_user FORCE INDEX(idx_sex) WHERE sex = 1;
-- 看优化器到底在犹豫什么
EXPLAIN SELECT * FROM t_user WHERE sex = 1;
```

### 七、一条「索引失效」的排查链路（能背下来最好）

```text
① EXPLAIN 看 type / key / rows / filtered
   - key = NULL 且 type = ALL  → 真的没走索引
   - key 有值但 rows 很大      → 走是走了，但优化器评估代价高
② SHOW WARNINGS 看优化器改写后的 SQL（隐式转换会被打印出来）
③ SHOW INDEX 看 Cardinality，判断区分度；必要时 ANALYZE TABLE
④ 检查列的类型 / 字符集 / 排序规则是否与查询条件一致
⑤ 检查索引定义，确认最左前缀是否被满足
⑥ 确认条件列的「命中行数占比」，超过 ~30% 就别指望索引了
```

### 八、兜底原则

**别过度建索引**。索引不是免费的：每次 INSERT/UPDATE/DELETE 都要维护所有相关索引；每多一个索引，写放大一次、buffer pool 里可缓存的业务数据页就少一分。建索引的原则是「**为高频、高区分度、能形成覆盖的查询建**」，而不是「WHERE 里出现过的列都建」。

原文档只列了场景，没有讲清「为什么」，这段可以补上：

| 失效场景 | 一句话根因 |
|---|---|
| 最左前缀 | B+ 树按联合索引列顺序分层有序，跳过前导列则后续列整体无序 |
| 函数/运算 | 索引用「原始值」建的有序结构，被加工后的值与它无关 |
| 隐式转换 | 列被转成数字 → 等价于对列用了 `CAST()` |
| 前导模糊 | 起点未知，无法二分，只能从叶子链头开始扫 |
| OR 无索引列 | 全表扫的代价被 OR 传染给了整个条件 |
| 区分度低 | 满足条件的行太多，回表开销超过顺序全扫 |
:::

:::拓展
**覆盖索引是「失效」的最大解药**

只要查询需要的列全在索引里，就不用回表——此时 `type` 可能是 `index`（全索引扫描）而不是 `ALL`。`type=index` 虽然也是「扫全部叶子」，但扫描的是**索引页**而非**数据页**，页数少得多，所以快很多。

```sql
-- 只需要 name 和 age，都在 idx_name_age_city 里
EXPLAIN SELECT name, age FROM t_user WHERE name = '李鑫';
-- Extra: Using index  → 覆盖索引，无回表
```

**`index_merge`（索引合并）——OR 场景的救命稻草**

```sql
ALTER TABLE t_user ADD KEY idx_city (city);
EXPLAIN SELECT * FROM t_user WHERE name = 'a' OR city = 'b';
-- type: index_merge
-- Extra: Using union(idx_name_age_city,idx_city); Using where
```

能用但不总用得上：**or 两侧必须都是索引列**，且优化器要认为合并比全表扫便宜。太复杂时反而退化成 `ALL`。

**MySQL 8.0 的新工具：降序索引 + 隐藏索引**

```sql
-- 8.0 支持真正的降序索引（5.7 语法接受但实际忽略 DESC）
ALTER TABLE t_user ADD KEY idx_city_time (city, created_at DESC);

-- 隐藏索引：想删索引又怕出事，先隐藏观察
ALTER TABLE t_user ALTER INDEX idx_sex INVISIBLE;   -- 优化器不再用它
ALTER TABLE t_user ALTER INDEX idx_sex VISIBLE;     -- 反悔
-- 开优化器开关，让隐藏索引立刻生效不用重建
SET optimizer_switch = 'use_invisible_indexes=on';
```

`INVISIBLE` 是灰度删索引的正确姿势——**先隐藏、观察一周慢查询告警、确认无影响再真正 DROP**。
:::

:::追问
**Q：`LIKE 'abc%'` 一定走索引吗？**
不一定。如果 `abc` 前缀的选择性太差（比如 `name LIKE '的%'`），优化器依然可能全表扫。另外**字段字符集是 `utf8mb4` 时，`LIKE` 的匹配是按 `_ci`（大小写不敏感）排序规则来的，和 B+ 树的排序规则一致才能用索引**——排序规则不一致同样会失效。

**Q：联合索引 `(a,b,c)`，`WHERE b=2 AND c=3` 完全用不上吗？**
不是「完全」，是**用不上最左前缀的顺序定位**。极端情况下优化器可能走「覆盖索引全扫 + 在索引里过滤」，即 `type=index` + `Extra: Using where`。如果只查 a/b/c 三列（覆盖索引），这比全表扫还是快一些。所以准确表述是：**不能用于定位，但可用于覆盖扫**。

**Q：为什么 `WHERE age = 20 AND name = 'x'` 顺序反了也能用索引？**
优化器会用 `name` 和 `age` 的等值条件一起做键值定位，**SQL 里 WHERE 的书写顺序不影响**（`age` 和 `name` 是等值的，优化器会自行组合最左前缀）。真正影响的是「有没有断档」——等值条件只要连续覆盖最左若干列即可。

**Q：`SELECT *` 为什么会拖慢索引使用？**
`SELECT *` 让覆盖索引不可能成立，必然回表。而且 `SELECT *` 会把大字段（TEXT/BLOB）一起捞出来，行更大、网络传输更多。**优化第一步就是把 `SELECT *` 改成列清单。**
:::

:::锚点
你在 MongoDB 上做过一次非常典型的同类排查：上报数据量大 → 查询慢 → `explain()` 看到 **COLLSCAN**（全集合扫描）→ 建了复合索引 `{taskId, apSN, RI}` + 分片 → 从秒级降到毫秒。

**这套经验可以一比一迁移过来讲**：

> 「MongoDB 的复合索引和 MySQL 的联合索引遵循同一套最左前缀逻辑——`{taskId, apSN, RI}` 只有带上 `taskId` 才能定位，跳过 `taskId` 直接按 `apSN` 查就是 COLLSCAN。MySQL 这边除了最左前缀，还多了「回表」这一层代价，所以同一个 `EXPLAIN` 的思路在两边都适用：**先看有没有走索引，再看走索引扫了多少行**。」

如果你在面试里被追问「那 MySQL 你实操过吗」，**别硬编生产经历**，就用这套话术：

> 「MySQL 我目前是补课状态，生产上主存储是 MongoDB。但索引这块的逻辑是相通的——我在 Mongo 上用 `explain()` 定位过 COLLSCAN 并建复合索引把慢查询从秒级压到毫秒，MySQL 的 `EXPLAIN` 我也是按同样的思路看 `type`、`key`、`rows`、`Extra` 四列。我知道 MySQL 多出来的是回表和 buffer pool 这两层，正好是我现在在补的部分。」

**坦诚 + 展示迁移能力 + 说出差异点**，比编一段没做过的经历安全得多——面试官一追问细节就露馅。
:::

---

## 2. 为什么 MySQL 用 B+ 树做索引

:::概念
**B+ 树是「为磁盘 IO 次数最少」而生的结构**：非叶子节点只存键不存数据 → 单页扇出大 → 树矮 → IO 次数少；叶子节点用双向链表串起来 → 范围查询和排序直接顺着链表走。
一句话：**矮胖 + 叶子有序 = 少的随机 IO + 强的范围能力。**
:::

:::提问
- 为什么用 B+ 树，不用 B 树、红黑树、哈希表？
- B+ 树为什么能把树高压到 3~4 层？
- 一页 16KB 是怎么算扇出的？
- B+ 树的范围查询为什么快？
- 为什么不用跳表/有序数组？
:::

:::答案
### 一、先明确约束：这是「磁盘索引」，不是「内存索引」

评估任何一个数据结构做索引，只看一个指标：**从根走到目标叶子，要读几次磁盘页**。
一次磁盘随机读的耗时量级是 **0.1ms 级**（SSD）/ **10ms 级**（机械盘），而一次内存比较是 **纳秒级**。所以在索引结构里，**IO 次数是唯一重要的成本**，树高就是 IO 次数。

### 二、四种结构横向对比

| 结构 | 查找复杂度 | 范围查询 | 树高（1000 万行） | 判断 |
|---|---|---|---|---|
| **哈希表** | O(1) | ❌ **完全不行** | — | 等值快，`BETWEEN`/`ORDER BY` 直接用不了 |
| **红黑树 / BST** | O(log n) 但**是二叉** | ✅ 中序即可 | **~23 层** = 23 次 IO | 内存结构，磁盘上 IO 次数爆炸 |
| **B 树** | O(log n)，多叉 | ⚠️ 需要中序遍历，跨层跳 | ~3 层，但**节点存数据** | 单节点能放的键少 → 扇出小 → 树更高 |
| **B+ 树** | O(log n)，多叉 | ✅ **叶子双向链表** | **3~4 层** | ✅ InnoDB 的选择 |

### 三、扇出（fan-out）怎么算出来的

InnoDB 一个数据页默认 **16KB**（`innodb_page_size`，默认 16384，可在初始化时设成 4K/8K/32K/64K，建库后不可改）。

**非叶子节点**（只存「键 + 6 字节子页指针」）：

```text
假设主键是 BIGINT：8 字节
非叶子节点每项 = 8(键) + 6(页指针) ≈ 14 字节
单页可放  16384 / 14 ≈ 1170 个指针
```

**叶子节点**（存整行数据）：
一行数据假设 1KB，则一页放 16 行。

**三层 B+ 树能装多少行？**

```text
根页(1)  → 1170 个中间页
中间层 1170 个页 → 1170 × 1170 ≈ 136.9 万个叶子页
叶子层 136.9 万页 × 16 行/页 ≈ 2190 万行
```

**结论：三层 B+ 树能索引 2000 万行量级的数据，查任意一行最多 3 次磁盘 IO。** 而红黑树需要 23 次。这就是 B+ 树赢的全部理由。

而且**根节点和中间层几乎常驻 buffer pool**（热点页），实际 IO 往往只有 1~2 次。

### 四、B 树 vs B+ 树：差在哪

| 维度 | B 树 | B+ 树 |
|---|---|---|
| 非叶子节点存什么 | **键 + 数据** | **只存键** |
| 单页能放的键数 | 少（数据占了大半） | 多 → **扇出大、树更矮** |
| 数据出现的位置 | 每一层都可能命中 | **只在叶子** |
| 叶子之间 | 无连接 | **双向链表** |
| 范围查询 | 需要回到父节点做中序遍历，**跨层跳跃** | 定位起点后**顺着链表顺序扫** |
| 等值查询最坏 IO | 可能更少（提前命中） | 固定到叶子，但树矮所以更少 |

一句话：**B 树牺牲了「单节点容量」换「提前命中」，而磁盘场景下扇出比提前命中值钱得多。**

### 五、为什么不用其他结构

- **有序数组**：二分查找 O(log n) 很快，但**插入要搬动后面所有元素**，写性能灾难。
- **跳表（Redis ZSet 用的）**：内存结构，靠多层索引加速；没有「页」的概念，一次跳转可能触发多次指针追逐，与磁盘局部性冲突。
- **LSM 树（RocksDB / HBase / MongoDB WiredTiger 可选的）**：写优化（顺序追加 + 后台合并），读放大，适合写多读少。

### 六、InnoDB 页的内部结构（能被追问的深度）

```text
┌───────────────── Page (16KB) ─────────────────┐
│ File Header (38B)      页号、前后页指针、校验和   │
│ Page Header (56B)      记录数、堆顶指针、槽数     │
│ Infimum + Supremum     页内最小/最大记录的虚拟边界 │
│ User Records           真正的行记录（按主键有序）  │
│ Free Space             未使用空间                │
│ Page Directory         稀疏槽位，每 4~8 条记录一个 │
│ File Trailer (8B)      校验和，与 Header 比对     │
└───────────────────────────────────────────────┘
```

**页内查找靠 Page Directory 做「页内二分」**，不需要从头扫记录链表——这是 B+ 树每一层内部也能二分的物理基础。

### 七、维护与查看

```sql
-- 页大小（只能在初始化 mysqld --initialize 时通过 --innodb-page-size 指定）
SHOW VARIABLES LIKE 'innodb_page_size';

-- 看表实际占多少页 / 多少行
SELECT
  TABLE_NAME,
  TABLE_ROWS,
  ROUND(DATA_LENGTH / 1024 / 1024, 2)  AS data_mb,
  ROUND(INDEX_LENGTH / 1024 / 1024, 2) AS index_mb,
  ROUND(DATA_LENGTH / 16384, 0)        AS approx_pages
FROM information_schema.TABLES
WHERE TABLE_SCHEMA = 'your_db' AND TABLE_NAME = 't_user';
```

**注意 `TABLE_ROWS` 是估算值**（InnoDB 按采样统计），准确行数要 `SELECT COUNT(*)`。
:::

:::拓展
**为什么 MySQL 主键建议用自增 BIGINT**

B+ 树的叶子节点是按主键有序排列的**连续页**。

- **自增主键**：新行永远插在最右侧的页 → **顺序追加 + 页分裂只发生在最右边界**（甚至能预分配整页），磁盘写入是顺序的。
- **UUID / 随机主键**：新行要插到树的随机位置 → 目标页大概率不在 buffer pool 中 → **随机读 + 页分裂 + 页碎片**。页分裂还会让页填充率降到 50%，索引文件体积直接翻倍。

```sql
-- 看页的填充率 / 碎片情况
SELECT
  TABLE_NAME,
  DATA_FREE,                              -- 碎片空间（字节）
  ROUND(DATA_LENGTH  / 1024 / 1024, 2) AS data_mb,
  ROUND(DATA_FREE    / 1024 / 1024, 2) AS free_mb
FROM information_schema.TABLES
WHERE TABLE_SCHEMA = 'your_db';

-- 整理碎片（会锁表，用 gh-ost / pt-online-schema-change 在线做）
ALTER TABLE t_user ENGINE=InnoDB;
OPTIMIZE TABLE t_user;
```

**UUID 真的必须用怎么办？**
① 用**有序 UUID**（UUID v7 / ULID / 雪花算法），保证单调递增；② 用自增主键做聚簇索引，UUID 只做**唯一二级索引**（此时 UUID 不参与聚簇索引排序，页分裂问题消失）。

**`innodb_page_size` 选 16KB 还是更大**

| 页大小 | 扇出 | 适用场景 |
|---|---|---|
| 4KB / 8KB | 小 | NVMe 小页 SSD、写密集 |
| **16KB（默认）** | 中 | 通用，官方默认值 |
| 32KB / 64KB | 大 | 数据仓库、机械盘顺序扫 |

**页大小建库后不可改**，只能 `mysqldump` 导出后用新页大小重建实例。生产上选默认 16KB 就是对的。
:::

:::追问
**Q：B+ 树的高度怎么算出来的？**
`树高 = ⌈log_扇出(行数)⌉`。扇出 ≈ 1170（非叶）、约 16 行/叶（1KB 行）。2000 万行时 `log_1170(20000000/16) ≈ 2`，加上根节点共 **3 层**。数据行越大，叶子页行数越少，需要的叶子页越多，树高可能到 4 层。**所以「大字段拆表」不只是省 IO，还能降低树高。**

**Q：为什么 MySQL 说 B+ 树「支持范围查询」，而哈希索引不行？**
哈希索引存的是 `hash(键值) → 行指针`，哈希值的大小顺序与原值**没有任何关系**。`WHERE id BETWEEN 100 AND 200` 在哈希表里必须逐行算哈希判断（等价于全扫）。B+ 树则天然按值有序，`range` 定位起点后顺叶子链扫即可。

**Q：`EXPLAIN` 里的 `type=range` 和 `type=index` 有什么区别？**
`range`：利用 B+ 树有序性**定位到区间起点**再扫一段（真正的范围查找）。
`index`：**全索引扫描**，从头到尾扫完所有叶子，只是扫的是索引页而非数据页。
排序：`const > eq_ref > ref > range > index > ALL`。

**Q：联合索引 `(a,b)` 的叶子节点长什么样？**
按 `(a,b)` 复合排序：先 a 有序，a 相同再 b 有序。叶子节点存的是 `(a, b, 主键)`。所以 `WHERE a=1 AND b>2` 能精准定位；`WHERE b=2` 不能——因为 b 在整棵树里只是「每个 a 分组内有序」。
:::

:::锚点
你在 MongoDB 里用的 WiredTiger 引擎，**默认索引结构也是 B+ 树**（B-Tree 的一种），只有在写密集场景才建议换 LSM 的配置。你和同事讨论「Mongo 索引为什么能撑住海量上报数据」时的那套「页 + 扇出 + 树高」逻辑，和 InnoDB 完全一致。

面试可以直接讲：

> 「RRM 的上报数据量大，我们的主力存储是 MongoDB，集合 `clbDetail` 上建了复合索引 `{taskId, apSN, RI}`。它的索引结构是 WiredTiger 的 B+ 树，和 InnoDB 一样是靠页分裂维护有序性的——**这就是为什么我们坚持让分片键和常用查询的最左前缀对齐：一旦查询条件跳过了 `taskId`，就退化成了全集合扫描（COLLSCAN），跟 MySQL 里跳过最左列是一样的后果。**」

再补一句差异点，显示你知道两边不是一回事：

> 「两边最大的不同是 MySQL 必须有聚簇索引，二级索引都要回表；MongoDB 的 `_id` 索引和普通索引在结构上其实是同一层，没有「回表」这个概念，代价模型不一样。」
:::

---

## 3. 聚簇索引、二级索引与回表

:::概念
**聚簇索引 = 主键索引，叶子节点直接放整行数据**（数据即索引、索引即数据）。
**二级索引（非聚簇索引）= 叶子节点只放「索引列 + 主键值」**，查非索引列要**先在二级索引拿到主键，再回聚簇索引拿整行**——这一步叫**回表**。
一句话记：**主键索引一次到位，二级索引要「查两次」。**
:::

:::提问
- 什么是聚簇索引？和二级索引有什么区别？
- 什么是回表？怎么避免？
- 什么是覆盖索引？它和索引下推有什么区别？
- 为什么主键建议自增？UUID 主键有什么问题？
- 没有主键的表，InnoDB 用什么做聚簇索引？
- 一张表能有几个聚簇索引？
:::

:::答案
### 一、两种索引的物理结构差异

```text
聚簇索引（PRIMARY，叶子 = 整行）
         [根页: 主键区间 → 子页指针]
                    │
      ┌─────────────┴─────────────┐
   [中间页]                    [中间页]
      │                             │
 [叶子页: id=1 整行][id=2 整行][id=3 整行] ← 双向链表

二级索引（idx_name，叶子 = 索引列 + 主键）
         [根页: name 区间 → 子页指针]
                    │
        [叶子页: ('李鑫', 1001)][('王五', 1002)] ← 只有 name + id
                                    │
                                    └── 要取 age/city，必须拿 1002 回聚簇索引
```

### 二、回表到底慢在哪

一次「`SELECT * FROM t_user WHERE name='李鑫'`」的执行过程：

```text
① 在 idx_name_age_city 上找到 name='李鑫' 的叶子记录 → 拿到主键 id = 1001
② 带着 id=1001 回到聚簇索引，从根页再走一遍 → 拿到整行
③ 若 name='李鑫' 有 50 行 → 上面两步重复 50 次 = 50 次随机 IO
```

**关键代价是「随机 IO」**：第 ① 步的叶子页是顺序读（按 name 有序），第 ② 步回表的 50 个主键在聚簇索引里**位置随机**，可能落在 50 个不同的页上。buffer pool 命中还好，命中不了就是 50 次磁盘随机读。

### 三、覆盖索引：消灭回表

**定义**：查询需要的所有列，都能在同一个索引里拿到 → 不需要回表。

```sql
-- idx_name_age_city(name, age, city) 覆盖了 SELECT 的所有列
EXPLAIN SELECT name, age, city FROM t_user WHERE name = '李鑫';
-- type: ref   key: idx_name_age_city
-- Extra: Using index          ← 出现这个就是覆盖索引
```

| 写法 | 是否覆盖 | Extra 表现 |
|---|---|---|
| `SELECT name, age FROM t_user WHERE name='x'` | ✅ | `Using index` |
| `SELECT name, age FROM t_user WHERE city='x'` | ✅ 扫全索引 | `Using where; Using index` |
| `SELECT name, id FROM t_user WHERE name='x'` | ✅（二级索引叶子自带主键） | `Using index` |
| `SELECT * FROM t_user WHERE name='x'` | ❌ 必然回表 | `NULL` 或 `Using where` |

**注意**：二级索引的叶子天然包含主键值，所以「索引列 + 主键」这个组合**永远是覆盖的**，不需要额外把主键加进索引定义里。

### 四、索引下推（ICP, Index Condition Pushdown）

**MySQL 5.6+ 引入**。作用是**把 WHERE 中「能用索引列判断但这部分不参与定位」的条件下推到存储引擎层**，减少回表次数。

```sql
-- 索引 (name, age, city)，查询里 age 是范围，city 无法用于定位
SELECT * FROM t_user WHERE name = '李鑫' AND age > 20 AND city = '成都';
```

| | 没有 ICP（5.5 及以前） | 有 ICP（5.6+，默认开） |
|---|---|---|
| 存储引擎做的事 | 按 `name='李鑫'` 取出**所有**主键，全部回表 | 在索引里先过滤 `age>20 AND city='成都'`，**只回表命中的** |
| 回表次数 | name 匹配多少行就回表多少次 | 只剩真正满足的行 |
| Extra | `Using where` | **`Using index condition`** |

**ICP 的适用条件**：① 必须是二级索引（聚簇索引没有回表，谈不上下推）；② WHERE 条件里**既有能用于定位的索引列，又有不能定位但同属该索引的列**；③ 存储引擎必须支持（InnoDB / MyISAM 都支持）。

```sql
-- ICP 开关
SHOW VARIABLES LIKE 'optimizer_switch'\G        -- 找 index_condition_pushdown=on
SET SESSION optimizer_switch = 'index_condition_pushdown=off';   -- 临时关掉做对比
```

**ICP vs 覆盖索引，别搞混**：

| | 覆盖索引 | 索引下推 ICP |
|---|---|---|
| 解决什么 | **不回表**（省掉第 ② 步） | **少回表**（减少第 ② 步的次数） |
| Extra | `Using index` | `Using index condition` |
| 依赖 | 索引包含所有查询列 | WHERE 有索引内可判断的非定位条件 |

### 五、没有主键时，InnoDB 怎么选聚簇索引

优先级（依次）：

1. **显式定义的主键**（`PRIMARY KEY`）
2. 没有主键 → 选**第一个所有列都 NOT NULL 的唯一索引**（Unique Key）作为聚簇索引
3. 都没有 → **自动创建一个 6 字节的隐藏列 `DB_ROW_ID`** 作为聚簇索引

**一张表只能有一个聚簇索引**（因为数据只有一份），但可以有任意多个二级索引。

**`DB_ROW_ID` 是全局共享的递增计数器**，高并发插入时会成为**热点争用点**（所有表抢同一个全局变量）。所以「**生产表永远显式定义主键**」是一条硬规矩。

### 六、回表次数的量化：什么时候该建覆盖索引

```sql
-- 看回表规模：满足条件的行数 × 每行回表开销
SELECT COUNT(*) FROM t_user WHERE name = '李鑫';
-- 假设是 20000 行 → 20000 次随机 IO，必须优化

-- 方案 A：把查询列改成索引覆盖
SELECT name, age, city FROM t_user WHERE name = '李鑫';

-- 方案 B：扩展联合索引，把回表用的列也放进去（索引会变大，写变慢）
ALTER TABLE t_user ADD KEY idx_name_sex (name, sex);

-- 方案 C：延迟关联（见第 6 题）
SELECT u.* FROM t_user u
JOIN (SELECT id FROM t_user WHERE name = '李鑫' LIMIT 20) t ON u.id = t.id;
```

### 七、一张表核对表（面试可以照着说）

| 概念 | 叶子存什么 | 一次查询几次「树查找」 | 关键 Extra |
|---|---|---|---|
| 聚簇索引 | 整行 | 1 | — |
| 二级索引 + 回表 | 索引列 + 主键 | 2 | `Using where` |
| 二级索引 + 覆盖 | 索引列 + 主键 | 1 | `Using index` |
| 二级索引 + ICP | 索引列 + 主键 | 2（但次数大幅减少） | `Using index condition` |
:::

:::拓展
**`Using index` vs `Using index condition` vs `Using where` 三者关系**

| Extra 组合 | 含义 |
|---|---|
| `Using index` | 覆盖索引，不回表 |
| `Using index; Using where` | 覆盖索引，但过滤条件里有索引里没法判断的部分，在 server 层过滤 |
| `Using index condition` | 走了 ICP，部分条件下推到引擎层 |
| `Using where`（无 `Using index`） | 回表了，且在 server 层做了过滤 |
| **什么都没有** | 直接用索引定位、回表、无额外过滤 —— 这是最理想的情况 |

**索引列顺序的实战原则**

1. **等值条件列排前面**，范围条件列排后面（范围之后的列无法用于定位）
2. **区分度高的列排前面**（能更快缩小范围）
3. **把 `ORDER BY` 的列接在等值列后面**，可以消掉 `Using filesort`
4. **把高频查询的 SELECT 列补进索引**，制造覆盖

```sql
-- 不好的顺序：age 是范围条件，放在 city 前面
KEY idx_wrong (name, age, city)    -- WHERE name=? AND age>? AND city=?  → city 用不上定位
-- 更好的顺序：city 等值放前面
KEY idx_better (name, city, age)   -- WHERE name=? AND city=? AND age>? → 三列都能用
```
:::

:::追问
**Q：为什么二级索引的叶子节点要存主键，而不是存行地址？**
因为行地址会变。InnoDB 的数据行在页内会移动（页分裂、行迁移、`OPTIMIZE TABLE`），如果二级索引存物理地址，每次数据移动都要更新所有二级索引。**存主键（逻辑位置）则只需要主键不变，二级索引就永远有效。** 代价就是多一次回表查找——用「查找多一层」换「更新少一轮」。

**Q：覆盖索引的「索引」是不是越大越好？**
不是。索引列越多，单个索引项越大 → 单页能放的项越少 → 扇出变小、树变高、`INDEX_LENGTH` 变大、buffer pool 能缓存的页变少，而且每次写都要维护。**经验做法：把「高频查询的过滤列 + 排序列 + 少量返回列」放进联合索引，而不是无脑把列全塞进去。** 返回列很多的大宽查询，宁可回表。

**Q：`SELECT * ` 一定比 `SELECT 具体列` 慢吗？**
**是的，但取决于结果集大小和网络带宽。** 两个层面：① 覆盖索引失效，必然回表；② 行变大，buffer pool 和网络传输都更吃紧。在小结果集上差异不明显，但在**大表 + 高 QPS** 下是数量级差异。另外还有工程意义：`SELECT *` 让表结构调整（加列）无声无息地影响所有查询。

**Q：为什么 InnoDB 的 `count(*)` 不能像 MyISAM 那样直接返回元数据？**
因为 MyISAM 没有 MVCC，全表只有一份数据；InnoDB 有 MVCC，**不同事务在同一时刻能看到的行数可能不同**（有未提交的插入/删除），所以根本没有一个「全局行数」能返回。见第 15 题。
:::

:::锚点
你在 MongoDB 上的 `clbDetail` 集合用的是复合索引 `{taskId, apSN, RI}`。**MongoDB 的 `_id` 索引和其他索引在存储层其实都是 B 树，没有 MySQL 这种「聚簇/二级」的分层**——这一点正好是你用来对比的素材。

面试话术：

> 「MySQL 的二级索引和 MongoDB 的普通索引有个本质区别：**MySQL 的所有二级索引叶子都存主键，查非索引列必须回表，所以覆盖索引是个高频优化手段；MongoDB 虽然也有「索引项指向文档」这一层，但没有 MySQL 那种按主键组织的聚簇结构，代价模型不太一样。** 我在 Mongo 上做过的是：给 `clbDetail` 建 `{taskId, apSN, RI}` 复合索引配分片，把 `explain()` 里的 COLLSCAN 变成 IXSCAN，查询从秒级到毫秒。**这个经验让我对 MySQL 的 `Extra: Using index`（覆盖索引）特别敏感——因为两者的优化目标完全一致：让查询所需的数据尽量都在索引里完成，不要回主表。**」

**注意**：不要编造你在 MySQL 上做过覆盖索引优化。上面的说法里，你讲的是 Mongo 的实操 + MySQL 的理解，这是真实且安全的表述。
:::

---

## 4. 联合索引、最左前缀与索引分类

:::概念
联合索引 `(a,b,c)` 的排序规则：**先按 a 排，a 相同按 b 排，b 相同按 c 排**——所以只能从最左边开始连续匹配。
**最左前缀原则**：`(a)`、`(a,b)`、`(a,b,c)` 能用定位；`(a,c)` 只能用到 `a`；`(b)`、`(b,c)`、`(c)` **不能用于定位**。
记忆钩子：**「等值连续覆盖最左若干列有效，中间断档就停」**。
:::

:::提问
- 什么是联合索引的最左前缀原则？
- 索引 `(a,b,c)`，`WHERE a=1 AND c=3` 用到几列？
- `WHERE a=1 AND b>2 AND c=3` 用到几列？
- 索引有哪些分类？你平时怎么决定建什么索引？
- 为什么性别这种字段不适合建索引？
- 索引越多越好吗？
:::

:::答案
### 一、最左前缀的物理原理

联合索引在 B+ 树里的键是**按列顺序拼起来的复合键** `(a, b, c)`，排序比较规则就是「字典序」：

```text
(a,b,c) 的排序结果示例：
(1, 10, 100)
(1, 10, 101)
(1, 20, 100)   ← a 相同看 b，b 相同看 c
(1, 20, 105)
(2, 10, 100)   ← a 变了，b 重新从最小开始
(2, 30, 200)
```

**关键洞察：跳过 a 直接约束 b，b 的值在整棵树里只是「每个 a 段内有序」，全局无序** → 无法二分定位 → 不能用索引定位。
这就是最左前缀原则的全部物理含义，**不是 MySQL 规定的规则，是 B+ 树结构决定的必然结果。**

### 二、逐种情况拆解

索引 `idx_abc (a, b, c)`：

| WHERE 条件 | 用于定位的列 | 说明 |
|---|---|---|
| `a=1` | a | ✅ 完整 |
| `a=1 AND b=2` | a, b | ✅ 完整 |
| `a=1 AND b=2 AND c=3` | a, b, c | ✅ 完整 |
| `a=1 AND c=3` | **只有 a** | c 不能定位；但**若 c 在索引里，可作为 ICP 在引擎层过滤** |
| `b=2` | **无** | 断档，退化；覆盖索引时可 `type=index` 全扫 |
| `b=2 AND c=3` | **无** | 同上 |
| `a=1 AND b>2 AND c=3` | a, b（范围） | **b 是范围 → b 之后的 c 不能用于定位**，c 可走 ICP |
| `a=1 AND b=2 AND c>3` | a, b, c | ✅ b 是等值，c 的范围可以定位 |
| `a>1 AND b=2` | 只有 a | a 是范围，后面的 b 失效定位 |

**「范围之后的列失效」这条最容易忘**：定位到范围起点后，B+ 树只能一路向叶子链尾部扫，后面的列不再参与定位。

### 三、排序与最左前缀的配合（这是「索引消除 filesort」的诀窍）

```sql
-- 索引 (a, b, c)
-- ✅ 能消除 filesort：ORDER BY 的列紧跟等值列之后
SELECT * FROM t WHERE a = 1 ORDER BY b, c;

-- ✅ 也 OK：a 等值 + b 范围，按 b 排序仍有序
SELECT * FROM t WHERE a = 1 AND b > 10 ORDER BY b;

-- ❌ 不能消除：ORDER BY 跳过 a，且 a 不是等值
SELECT * FROM t WHERE a > 1 ORDER BY b;

-- ❌ 不能消除：ASC/DESC 混用（8.0 前的降序索引是摆设）
SELECT * FROM t WHERE a = 1 ORDER BY b ASC, c DESC;
```

**`Using filesort` 不等于「用磁盘排序」**：MySQL 会在 `sort_buffer_size`（默认 256KB）里排，装不下才落盘做外部排序。所以 `Using filesort` 在小结果集上影响有限，**大结果集才是真问题**。

### 四、索引分类

**按数据结构分**

| 类型 | 支持的操作 | 限制 |
|---|---|---|
| **B+ 树** | 等值、范围、排序、前缀匹配 | 默认，InnoDB 唯一常用类型 |
| **哈希** | 等值 | 只有 Memory 引擎支持；InnoDB 有自适应哈希索引（内部自动，不可手动建） |
| **全文（FULLTEXT）** | 文本分词检索 | 中文需 `ngram` 分词器，大文本检索一般用 ES 替代 |
| **R 树** | 空间数据 | 需 GIS 场景（MyISAM 才有空间索引） |

**按用途分**

| 类型 | 特点 | 约束 |
|---|---|---|
| 主键索引 | 聚簇、唯一、非空 | 一张表只能一个 |
| 唯一索引 | 值唯一，**允许多个 NULL** | 唯一性检查会加锁 |
| 普通索引 | 只加速 | 无约束 |
| 联合索引 | 多列复合，最左前缀 | 列序很关键 |
| 前缀索引 | `KEY idx(name(10))` 只取前 N 个字符 | 不能用于覆盖索引/ORDER BY |
| 函数索引（8.0.13+） | `KEY ((CAST(data AS CHAR(10))))` | 表达式必须与查询里完全一致 |

**按存储分**

| 类型 | 含义 |
|---|---|
| 聚簇索引 | 叶子存整行（主键） |
| 非聚簇/二级索引 | 叶子存索引列 + 主键 |

### 五、建索引的决策清单

**该建**

1. 高频出现在 `WHERE` 等值条件里的高区分度列
2. 用于 `JOIN` 的关联列（**被驱动表的关联列必须建索引**）
3. `ORDER BY` / `GROUP BY` 的列（配合最左前缀）
4. 能形成**覆盖索引**的「过滤列 + 排序列 + 少量返回列」组合

**不该建**

| 情形 | 原因 |
|---|---|
| **区分度极低**（性别、布尔、状态只有几个值） | 索引选择性差，优化器往往仍全表扫；还白占空间、拖慢写入 |
| **表很小**（几百行以内） | 全表扫比回表还快，索引没意义 |
| **频繁更新的列** | 每次更新都要维护索引，写放大 |
| **很少被查询的列** | 纯浪费 |
| **大字段（TEXT/BLOB）** | 单个索引项太大，扇出骤降；改用前缀索引 |
| **已有联合索引前缀覆盖的列** | 冗余，如已有 `(a,b)` 就不用再建 `(a)` |

**区分度量化**：

```sql
-- 选择性 = 不重复值 / 总行数，越接近 1 越好
SELECT
  COUNT(DISTINCT sex)  / COUNT(*) AS sel_sex,     -- 2/10000 = 0.0002  → 极差
  COUNT(DISTINCT city) / COUNT(*) AS sel_city,    -- 30/10000 = 0.003  → 差
  COUNT(DISTINCT name) / COUNT(*) AS sel_name;    -- 0.95 → 好

-- 直接看优化器统计的基数
SHOW INDEX FROM t_user;
-- Cardinality 列：越接近总行数，区分度越好
```

### 六、索引数量的代价

```sql
-- 看表上有多少索引、各占多少空间
SELECT
  INDEX_NAME,
  GROUP_CONCAT(COLUMN_NAME ORDER BY SEQ_IN_INDEX) AS cols,
  ROUND(SUM(STAT_VALUE * @@innodb_page_size) / 1024 / 1024, 2) AS size_mb
FROM mysql.innodb_index_stats
WHERE database_name = 'your_db' AND table_name = 't_user'
  AND stat_name = 'size'
GROUP BY INDEX_NAME;
```

**写放大公式（粗略）**：一次 `INSERT` 要更新 **1 个聚簇索引 + N 个二级索引**，每个索引至少一次页修改 + 一次 redo 写入。表上有 8 个索引时，写入成本至少是只有主键时的 9 倍。

**经验上限**：OLTP 表索引数量控制在 **5~6 个以内**。超过说明索引设计有问题（大概率有冗余索引，或者把多个查询硬塞到一张表上）。
:::

:::拓展
**冗余索引与重复索引的识别**

```sql
-- 用 sys schema 直接查冗余/重复索引（MySQL 5.7+）
SELECT * FROM sys.schema_redundant_indexes WHERE table_schema = 'your_db';
SELECT * FROM sys.schema_unused_indexes   WHERE object_schema = 'your_db';
```

- **重复索引**：完全相同的列顺序（`(a,b)` 建了两次）
- **冗余索引**：`(a)` 被 `(a,b)` 的最左前缀覆盖 → `(a)` 可以删

**`sys.schema_unused_indexes` 依赖 `performance_schema`**，需要开启：

```sql
-- 确认 performance_schema 开着（默认 ON，但部分场景监控关了索引统计）
SHOW VARIABLES LIKE 'performance_schema';
UPDATE performance_schema.setup_instruments
   SET ENABLED = 'YES' WHERE NAME LIKE '%index%';
```

**MySQL 8.0 不可见索引：安全删索引的正确姿势**

```sql
-- ① 先隐藏，观察（唯一索引不能设为 invisible）
ALTER TABLE t_user ALTER INDEX idx_sex INVISIBLE;
-- ② 观察 1~2 周：慢查询告警、QPS、P99 有没有变化
-- ③ 无影响再真正删除
DROP INDEX idx_sex ON t_user;
-- ④ 有影响就立刻恢复
ALTER TABLE t_user ALTER INDEX idx_sex VISIBLE;
```

**MySQL 8.0.13+ 函数索引**

```sql
-- 场景：必须按 JSON 字段或函数结果查询，又不想改 SQL
ALTER TABLE t_user
  ADD KEY idx_name_lower ((LOWER(name)));

-- 查询必须和索引表达式完全一致才会命中
EXPLAIN SELECT * FROM t_user WHERE LOWER(name) = 'lixin';
```
:::

:::追问
**Q：联合索引 `(a,b,c)`，`WHERE a=1 AND c=3` 真的完全用不上 c 吗？**
不是。分两种情况：① **需要回表**（`SELECT *`）：c 只能在 server 层过滤，回表次数等于 `a=1` 的行数；② **覆盖索引**（`SELECT a,b,c`）：如果 MySQL 8.0 有 ICP，c 会下推到引擎层在索引里过滤（`Using index condition`），回表/返回的行数减少。**所以「用不上」指不能用于定位，不等于不能用于过滤。**

**Q：`EXPLAIN` 里的 `key_len` 怎么推出用了几列索引？**
`key_len` 是索引项在 B+ 树里实际参与比较的字节数。看它的值就能反推用了几列（见第 5 题）。

**Q：`ORDER BY a, b DESC` 这种混合排序，8.0 能走索引吗？**
MySQL 8.0 支持真正的降序索引：`KEY idx (a ASC, b DESC)`。只要索引定义和 ORDER BY 的顺序、方向完全一致，就能消除 filesort。**5.7 之前 `DESC` 在索引定义里只是语法糖，实际仍按升序存**，这是经典的版本差异题。

**Q：前缀索引为什么不能用于 `ORDER BY` 和覆盖索引？**
前缀索引只存前 N 个字符，**原值无法还原** → 不能用于返回值（覆盖）也不能用于排序（排序需要完整值）。它只能用于「定位 + 回表」。所以前缀长度的选择标准是：**让前缀的选择性接近完整列的选择性**。

```sql
-- 找最优前缀长度
SELECT
  COUNT(DISTINCT LEFT(name, 5))  / COUNT(*) AS p5,
  COUNT(DISTINCT LEFT(name, 10)) / COUNT(*) AS p10,
  COUNT(DISTINCT LEFT(name, 20)) / COUNT(*) AS p20,
  COUNT(DISTINCT name) / COUNT(*) AS full
FROM t_user;
-- 选第一个接近 full 的长度
```
:::

:::锚点
**这是你最好讲的一道题——因为你在 MongoDB 上的实战和它一模一样。**

你们 `clbDetail` 集合的复合索引是 `{taskId, apSN, RI}`，当初这么建，本质上就是最左前缀原则：**必须先给 `taskId` 才能定位到某个调优任务的数据段**，跳过 `taskId` 直接按 `apSN` 查就是 COLLSCAN。

面试话术：

> 「我在 RRM 项目里处理过上报数据的慢查询。集合 `clbDetail` 数据量很大，早期的查询没有走索引，`explain()` 里是 COLLSCAN。后来我们按查询模式建了复合索引 `{taskId, apSN, RI}`——**这三列的顺序不是随便排的，是按最左前缀排的：`taskId` 是必带的高区分度条件，`apSN` 其次，`RI` 只在前面两列确定后才有序。跟 MySQL 联合索引是同一套逻辑。** 加上分片之后，访问模式从集合扫描变成索引扫描，查询从秒级降到毫秒。」

**被追问「MySQL 上你有没有做过类似的事」时，老实回答**：

> 「MySQL 在生产上我还没实操过调优，我目前的主力存储是 MongoDB。但我知道两者在这里有个关键差别：**MySQL 的二级索引要回表，所以除了最左前缀，还要考虑覆盖索引、ICP 这些；MongoDB 没有回表这一层，但它的分片键选择和索引前缀是强绑定的。** 我这两周正在补 MySQL 的执行计划和锁这一块。」

**别编生产 MySQL 经历** —— 面试官问「那张表多少行、什么业务、索引叫啥、优化前后 QPS 多少」你就答不上来了。真话 + 展示出你在系统性补课，反而更可信。
:::

---

## 5. 慢查询定位：从 slow log 到 pt-query-digest

:::概念
**没有监控就没有优化。** 慢查询定位的标准链路：
**开启慢日志 → 采集 → 聚合排序（按总耗时，不是按单次耗时）→ 锁定 TOP SQL → `EXPLAIN` 分析 → 改写/加索引 → 回归验证。**
一句话记：**先找到「消耗总时间最多」的 SQL，而不是「单次最慢」的 SQL。**
:::

:::提问
- 线上一条 SQL 突然变慢，你怎么排查？
- 慢查询日志怎么开？影响性能吗？
- `long_query_time` 设多少合适？
- 你会用哪些工具分析慢日志？
- 正在跑的 SQL 怎么看到？怎么杀掉？
- 慢日志里 `Rows_examined` 很大说明什么？
:::

:::答案
### 一、开启慢查询日志（先看默认值）

```sql
-- 查看当前配置
SHOW VARIABLES LIKE 'slow_query_log';                    -- 默认 OFF
SHOW VARIABLES LIKE 'slow_query_log_file';               -- 默认 <hostname>-slow.log
SHOW VARIABLES LIKE 'long_query_time';                   -- 默认 10（秒）
SHOW VARIABLES LIKE 'log_queries_not_using_indexes';     -- 默认 OFF
SHOW VARIABLES LIKE 'log_slow_admin_statements';         -- 默认 OFF
SHOW VARIABLES LIKE 'min_examined_row_limit';            -- 默认 0
SHOW VARIABLES LIKE 'log_output';                        -- 默认 FILE，可设 TABLE
```

**按需开启**（`SET GLOBAL` 是运行时生效、重启失效；写进 `my.cnf` 才永久生效）：

```sql
SET GLOBAL slow_query_log = ON;
SET GLOBAL long_query_time = 1;                          -- 单位：秒，支持小数如 0.5
SET GLOBAL log_queries_not_using_indexes = ON;           -- ⚠️ 慎用，见下
SET GLOBAL log_slow_admin_statements = ON;               -- 记录 ALTER/ANALYZE 等
SET GLOBAL log_output = 'FILE,TABLE';                    -- 同时写入文件和 mysql.slow_log 表
```

**写进 `my.cnf`（推荐，永久生效）**：

```ini
[mysqld]
slow_query_log            = 1
slow_query_log_file       = /var/log/mysql/slow.log
long_query_time           = 1
log_queries_not_using_indexes = 0
min_examined_row_limit    = 100
log_slow_extra            = 1        # 8.0.14+：额外记录线程ID、Bytes_sent 等
```

**⚠️ `log_queries_not_using_indexes = ON` 的生产风险**：它会把**所有没走索引的 SQL** 都记下来，即使执行很快。在高并发小表查询场景下（比如配置表、字典表的全扫），**慢日志会以每秒几百 MB 的速度膨胀，直接写爆磁盘**。正确用法：临时开几分钟采样，采完立刻关。

```sql
-- 采样用法
SET GLOBAL log_queries_not_using_indexes = ON;
-- ...等 60 秒...
SET GLOBAL log_queries_not_using_indexes = OFF;
```

### 二、一条慢日志长什么样（逐字段拆）

```text
# Time: 2026-09-18T11:03:22.418371+08:00
# User@Host: app_rw[app_rw] @ [10.20.3.15]  Id: 84213
# Query_time: 4.218735  Lock_time: 0.000142  Rows_sent: 20  Rows_examined: 4126350
SET timestamp=1785000000;
SELECT o.id, o.order_no, u.name
FROM t_order o JOIN t_user u ON o.user_id = u.id
WHERE o.status = 2 AND o.created_at >= '2026-01-01'
ORDER BY o.created_at DESC
LIMIT 20;
```

| 字段 | 含义 | 怎么用 |
|---|---|---|
| `Time` | 该条 SQL 被记录的时间 | 和时间线（发布、流量高峰、定时任务）对齐 |
| `User@Host` / `Id` | 哪个账号、从哪个 IP、连接 ID | 定位是哪个应用/哪个连接池 |
| **`Query_time`** | 执行总耗时（秒） | 主指标 |
| **`Lock_time`** | 等锁耗时（秒） | **若占比高 → 不是 SQL 慢，是锁冲突**，查锁不查索引 |
| `Rows_sent` | 返回给客户端行数 | 通常不大 |
| **`Rows_examined`** | 扫描了多少行 | **`Rows_examined / Rows_sent` 比值巨大 → 索引没走好/扫描过量** |
| `SET timestamp=` | Unix 时间戳 | 用于脚本过滤 |

**核心判据**：
- `Lock_time` 高 → **锁等待问题**（长事务、间隙锁冲突），走第 12 题的排查。
- `Rows_examined` 远大于 `Rows_sent` → **索引问题**，`EXPLAIN` 分析。
- 两者都不高但 `Query_time` 高 → **网络传输 / 客户端处理慢 / 排序落盘**。

### 三、查询正在执行的 SQL

```sql
-- 最常用：看当前所有连接
SHOW FULL PROCESSLIST;

-- 从 information_schema 看（可加条件筛选长事务）
SELECT id, user, host, db, command, time, state, info
FROM information_schema.processlist
WHERE command != 'Sleep' AND time > 5
ORDER BY time DESC;

-- MySQL 8.0：performance_schema 里看更细（含线程、阶段）
SELECT
  t.processlist_id, t.processlist_user, t.processlist_time,
  e.event_name, e.timer_wait / 1e12 AS seconds,
  t.processlist_info
FROM performance_schema.threads t
JOIN performance_schema.events_statements_current e USING (thread_id)
WHERE e.timer_wait > 5 * 1e12
ORDER BY e.timer_wait DESC;

-- 杀掉长事务（谨慎！确认业务影响后再执行）
KILL QUERY 84213;    -- 只终止当前语句，连接保留
KILL 84213;          -- 终止整个连接
```

**⚠️ `KILL` 是破坏性操作，生产执行前必须确认**：① 该 SQL 属于哪个业务；② 是否在事务中（`KILL` 会触发回滚，大事务回滚可能比原 SQL 更慢）；③ 是否有从库延迟。**不要习惯性 KILL，回滚一个百万行的事务可能锁住你几十分钟。**

### 四、工具链

| 工具 | 定位 | 优缺点 |
|---|---|---|
| `mysqldumpslow`（官方自带） | 按 SQL 模式聚合，输出总耗时排序 | 轻量、无需安装；功能少，SQL 显示被截断 |
| **`pt-query-digest`**（Percona Toolkit） | **生产标准**，输出完整报表 | 功能最强：按总耗时排序、展示 95 分位、EXPLAIN 计划、采样 |
| `SHOW FULL PROCESSLIST` | 实时，看「此刻」 | 看不到历史 |
| `performance_schema` | 历史聚合（按 SQL 指纹） | 有开销、配置复杂 |
| `sys.schema_*` 视图 | 把 `performance_schema` 包装成人话 | 5.7+ 才有；数据依赖 P_S 开启 |
| APM / 慢日志平台 | 全链路 | 需要基建投入 |

**`mysqldumpslow` 常用姿势**：

```bash
# 按总耗时降序，取前 20 条
mysqldumpslow -s t -t 20 /var/log/mysql/slow.log

# 按平均耗时排序，只看 SELECT，忽略数字差异（把数字替换成 N）
mysqldumpslow -s at -t 20 -g "SELECT" /var/log/mysql/slow.log

# 参数说明
# -s t   按 query time 排序（总耗时）
# -s at  按 average query time 排序
# -s c   按出现次数排序
# -s l   按 lock time 排序
# -t N   取前 N 条
# -g XX  只匹配包含 XX 的 SQL
# -a     显示真实数字，不折叠为 N
```

**`pt-query-digest` 才是生产首选**：

```bash
# 分析慢日志，输出报表（默认按总耗时排序）
pt-query-digest /var/log/mysql/slow.log > /tmp/slow_report.txt

# 只看前 10 条，按总耗时
pt-query-digest --limit 10 /var/log/mysql/slow.log

# 按时间窗口过滤（比如只看发布后那 30 分钟）
pt-query-digest --since '2026-09-18 11:00:00' --until '2026-09-18 11:30:00' /var/log/mysql/slow.log

# 直接对 performance_schema 做分析（不需要慢日志文件）
pt-query-digest --processlist h=localhost,u=root,p=pwd --interval 0.1

# 报告里最有用的三段：
#   1) Profile  ：按「Response time」占比排序，找 TOP 1 占比
#   2) Rank      ：每条 SQL 的 pct（占总耗时百分比）、Calls、R/Call
#   3) EXPLAIN   ：对抽样 SQL 自动跑 EXPLAIN
```

**关键认知：按「总耗时占比」排序，不是按单次耗时**。一条 3ms 的 SQL 每秒跑 5000 次，总耗时 15 秒/秒，比一条 2 秒但每分钟跑 1 次的 SQL 危害大 450 倍。

### 五、`performance_schema` / `sys` 视图（5.7+ 的历史聚合）

```sql
-- 按 SQL 指纹（digest）聚合，看总耗时 TOP20
SELECT
  DIGEST_TEXT,
  COUNT_STAR                                          AS exec_count,
  ROUND(SUM_TIMER_WAIT / 1e12, 2)                     AS total_sec,
  ROUND(AVG_TIMER_WAIT / 1e9, 2)                      AS avg_ms,
  ROUND(MAX_TIMER_WAIT / 1e9, 2)                      AS max_ms,
  SUM_ROWS_EXAMINED, SUM_ROWS_SENT,
  SUM_NO_INDEX_USED,  SUM_NO_GOOD_INDEX_USED
FROM performance_schema.events_statements_summary_by_digest
ORDER BY SUM_TIMER_WAIT DESC
LIMIT 20;
```

**`SUM_NO_INDEX_USED > 0` 就是「这条 SQL 从没走过索引」的直接证据。**

**MySQL 8.0 的 `sys` 视图（更直接）**：

```sql
-- 总耗时 TOP：谁在吃 CPU
SELECT * FROM sys.statement_analysis
ORDER BY total_latency DESC LIMIT 20;

-- 全表扫 TOP 语句
SELECT * FROM sys.statements_with_full_table_scans
ORDER BY total_latency DESC LIMIT 20;

-- 没走索引的语句
SELECT * FROM sys.statements_with_no_index LIMIT 20;

-- 用了临时表的语句
SELECT * FROM sys.statements_with_temp_tables
ORDER BY total_latency DESC LIMIT 20;

-- 表级 IO 统计（谁读得最多）
SELECT * FROM sys.schema_table_statistics
ORDER BY total_latency DESC LIMIT 20;

-- 没被用过的索引（删索引的依据）
SELECT * FROM sys.schema_unused_indexes;
```

**8.0 里 `sys` 视图默认就装好**（5.7 也有，但语句不同）。`performance_schema` 默认 `ON`，但 `events_statements_summary_by_digest` 有个上限：

```sql
SHOW VARIABLES LIKE 'performance_schema_digests_size';   -- 默认 10000
-- 超过 10000 种不同的 SQL 指纹后，新的会被归到 "DIGEST_TEXT=NULL" 的桶里
-- 若业务 SQL 种类极多，需要调大
```

### 六、一条慢 SQL 的完整定位链路（背下来）

```text
① 发现
   - 告警：监控平台（P99 / QPS 下跌）/ 慢查询告警
   - 用户反馈：接口超时
   - 例行巡检：sys.statement_analysis

② 确认范围
   SHOW FULL PROCESSLIST;                    -- 是「此刻在跑」还是「历史慢」
   SELECT * FROM sys.statement_analysis ORDER BY total_latency DESC LIMIT 20;

③ 取证据
   - 慢日志：慢日志文件 / mysql.slow_log 表
   - 聚合：pt-query-digest / mysqldumpslow -s t
   - 关键指标：Query_time / Lock_time / Rows_examined / Rows_sent

④ 分叉判断（这一步决定后面查什么）
   Lock_time 高          → 锁问题（第 12 题）
   Rows_examined 远超 Rows_sent → 索引问题（第 1、4、6 题）
   扫描行数正常但慢       → 排序落盘 / 大字段 / 网络 / 客户端（第 6 题）

⑤ 分析
   EXPLAIN / EXPLAIN ANALYZE / EXPLAIN FORMAT=JSON
   对照索引定义（SHOW INDEX）、表结构与行数

⑥ 改写
   加索引 / 改 SQL 写法（消除 OR、改深分页、拆子查询）/ 改表结构

⑦ 验证
   生产前：在预发/从库用真实数据量压测
   上线后：对比 EXPLAIN 的 rows、对比 P99、观察慢日志是否还有该指纹
   ⚠️ 别忘了回滚预案：新索引可 DROP，SQL 改写要能一键回退
```

### 七、生产上量级参考

| 指标 | 健康值 | 说明 |
|---|---|---|
| `long_query_time` | 1 秒（核心业务可放宽到 0.5） | 设太小慢日志会爆 |
| 单条 SQL QPS | 视业务 | 单表 QPS 过 5000 就该考虑缓存/拆分 |
| `Rows_examined / Rows_sent` | < 100 | 超过说明扫描过量 |
| buffer pool 命中率 | > 99% | 见下方查询 |
| `Threads_running` | < CPU 核数 × 2 | `SHOW STATUS` 查看 |

```sql
-- 缓冲池命中率（核心健康指标）
SHOW STATUS LIKE 'Innodb_buffer_pool_read%';
-- Innodb_buffer_pool_read_requests  逻辑读次数
-- Innodb_buffer_pool_reads          物理读次数（没命中缓存）
-- 命中率 = 1 - reads / read_requests，健康值 > 99%

-- 关键运行指标
SHOW GLOBAL STATUS WHERE Variable_name IN (
  'Threads_connected','Threads_running','Queries','Slow_queries',
  'Innodb_row_lock_waits','Innodb_row_lock_time_avg'
);
-- Slow_queries 会累计，用来验证「开启慢日志后是否真的抓到了」
```
:::

:::拓展
**`performance_schema` 的开销与取舍**

`performance_schema` 默认有开销（约 5%~10% 的额外 CPU），高并发下可以关闭不需要的 instrument：

```sql
SHOW VARIABLES LIKE 'performance_schema%';

-- 关掉不需要的采集项（按需）
UPDATE performance_schema.setup_consumers SET ENABLED = 'NO'
 WHERE NAME NOT LIKE 'events_statements%';
UPDATE performance_schema.setup_instruments SET ENABLED = 'NO', TIMED = 'NO'
 WHERE NAME LIKE 'wait/io/file/%';
```

**`log_output = 'TABLE'` 的坑**

```sql
SET GLOBAL log_output = 'TABLE';
SELECT * FROM mysql.slow_log ORDER BY start_time DESC LIMIT 10;
-- 坑：mysql.slow_log 是 CSV 引擎，行数多时查询很慢，而且不能建索引
-- 正确组合：log_output = 'FILE,TABLE'，分析用 FILE，临时查用 TABLE
```

**`log_slow_extra = ON`（8.0.14+）能多看到什么**

```text
# 开启后会额外输出：
#   Thread_id: 84213             线程 ID（对应 performance_schema.threads）
#   Errno: 0
#   Bytes_sent: 2048             返回给客户端的字节数 ← 大字段问题的线索
#   Rows_affected: 0
#   Tmp_tables: 1                临时表数量 ← Using temporary 的量化
#   Tmp_disk_tables: 0           落盘临时表 ← >0 说明 sort_buffer / tmp_table_size 不够
#   Tmp_table_sizes: 32768
#   Sort_merge_passes: 0         外部排序归并次数 ← >0 说明排序落盘了
#   Sort_scan / Sort_range
```

**`Tmp_disk_tables > 0` 和 `Sort_merge_passes > 0` 是两个「SQL 写了但没报错，性能却崩了」的隐形信号。**

```sql
-- 相关参数
SHOW VARIABLES LIKE 'tmp_table_size';        -- 默认 16M（内存临时表上限）
SHOW VARIABLES LIKE 'max_heap_table_size';   -- 默认 16M（取二者较小值生效）
SHOW VARIABLES LIKE 'sort_buffer_size';      -- 默认 256K（每连接，别设太大）
SHOW VARIABLES LIKE 'join_buffer_size';      -- 默认 256K
SHOW VARIABLES LIKE 'read_rnd_buffer_size';  -- 默认 256K
```

**`sort_buffer_size` / `join_buffer_size` 是「每连接」分配**，设成 64M 在 500 连接下就是 32GB 内存——**这是最常见的 MySQL 内存配置事故**。
:::

:::追问
**Q：开启慢日志会影响性能吗？**
影响很小但非零。写入慢日志是一次追加写 + 后续 fsync，测量基准是「每秒命中慢日志的 SQL 条数」。`long_query_time = 1` 时通常只有个位数 QPS 命中，开销可忽略。**真正有风险的是 `log_queries_not_using_indexes = ON`——它会让大量快 SQL 命中，日志量爆炸。**

**Q：为什么慢日志里有的 SQL 看起来不慢也被记录了？**
三个原因：① `log_queries_not_using_indexes = ON`（未走索引即记录，与耗时无关）；② `long_query_time` 设得为 0 或极小；③ `log_slow_admin_statements = ON` 记录了 DDL；④ 慢日志记录的是**实际执行耗时**，可能包含锁等待（`Lock_time`）——SQL 本身很快，但等锁等了 4 秒。

**Q：`Rows_examined` 和 `EXPLAIN` 的 `rows` 为什么对不上？**
`EXPLAIN` 的 `rows` 是**优化器基于统计信息的估算值**（可能偏差几个数量级，尤其是统计信息过期时）；`Rows_examined` 是**实际扫描行数的精确值**。**两者差距巨大时，第一反应是 `ANALYZE TABLE` 更新统计信息。** MySQL 8.0 还可以用 `EXPLAIN ANALYZE` 拿到实际值。

**Q：从库上的慢查询算不算问题？**
算，但优先级不同。从库慢通常是**主从延迟**的结果（从库要重放主库的写，还要承担查询压力）。处置：① 确认从库的 `Seconds_Behind_Master`；② 从库上不该跑 OLAP 大查询，报表类查询走独立只读实例；③ 从库可以设 `long_query_time` 更小，专门抓延迟放大的语句。
:::

:::锚点
**MongoDB 有几乎一模一样的一套机制，你的实操经验可以直接对照。**

MongoDB 的慢查询方案：

```javascript
// ① 打开数据库分析器（profiler）—— 对应 MySQL 的 slow_query_log
db.setProfilingLevel(1, { slowms: 100 })   // 记录超过 100ms 的操作
db.getProfilingStatus()

// ② 查最近的慢操作 —— 对应慢日志
db.system.profile.find().sort({ ts: -1 }).limit(10).pretty()

// ③ 看扫描行数 vs 返回行数 —— 对应 Rows_examined / Rows_sent
db.system.profile.find(
  { ns: "oasis.clbDetail" },
  { op: 1, millis: 1, "docsExamined": 1, "nreturned": 1, planSummary: 1 }
).sort({ millis: -1 }).limit(20)

// ④ 看执行计划 —— 对应 EXPLAIN
db.clbDetail.find({ taskId: "...", apSN: "..." }).explain("executionStats")
// 关注 totalDocsExamined / totalKeysExamined / executionTimeMillis
// stage: COLLSCAN(全集合扫) / IXSCAN(索引扫) / FETCH(回表)
```

**面试话术**：

> 「慢查询定位这套方法论我在 RRM 项目里是实操过的，只是工具是 MongoDB 的版本。我用 profiler 采集慢操作，看 `docsExamined` 和 `nreturned` 的比值——这个思路跟 MySQL 里看 `Rows_examined` 和 `Rows_sent` 完全一致。当时发现 `clbDetail` 集合的查询 `docsExamined` 是返回行数的几十万倍，`explain()` 显示是 COLLSCAN，建了复合索引 `{taskId, apSN, RI}` 并做分片后改善到毫秒级。**MySQL 这边我目前是补课状态，知道对应的工具是慢日志 + `pt-query-digest` + `performance_schema` 按 SQL 指纹聚合，方法论是同一套：先按总耗时占比排序找 TOP SQL，再分叉判断是锁问题还是索引问题。**」

**主动坦白的加分点**：说出「先按总耗时排序而不是按单次耗时排序」这个判据——这是「做过真事」和「背过文档」的分界线。
:::

---

## 6. 深分页优化与排序成本

:::概念
`LIMIT 200000, 20` 的代价不是「返回 20 行」，而是**「先扫描并丢弃 200000 行」**，而且每行都可能伴随一次回表。
**三种解法**：
① **游标分页** `WHERE id > last_id LIMIT 20`（最优，要求主键有序且不跳页）；
② **延迟关联**（JOIN 先取主键再回表）；
③ **业务限制**（不让用户翻那么深 / 限制最大页码）。
:::

:::提问
- 深分页为什么慢？怎么优化？
- `LIMIT 1000000, 10` 内部是怎么执行的？
- 游标分页有什么缺点？
- `ORDER BY` 不能走索引时会怎样？
- 大表分页 + 多字段排序怎么处理？
:::

:::答案
### 一、`LIMIT m, n` 的真实执行过程

```sql
SELECT * FROM t_order ORDER BY id LIMIT 200000, 20;
```

```text
① 走聚簇索引（或二级索引），从第一行开始顺序读
② 读到的每一行都交给 server 层判断「要不要」
③ 前 200000 行：直接丢弃（但每行都已经付了读取 + 可能的回表代价）
④ 第 200001 ~ 200020 行：返回
```

**核心问题：offset 越大，被丢弃的行越多，而丢弃之前的工作量一分没少。**
若只有二级索引、还要回表：**200020 次回表**，其中 200000 次的结果被丢掉。这是真正的杀手。

### 二、三种解法

#### 解法 1：游标分页（最优，但要求不跳页）

```sql
-- 第一页
SELECT * FROM t_order ORDER BY id LIMIT 20;
-- 记住返回的最后一行的 id = 100020

-- 下一页
SELECT * FROM t_order WHERE id > 100020 ORDER BY id LIMIT 20;
-- EXPLAIN：type=range，rows=20  ← 只扫 20 行！
```

| 对比项 | `LIMIT 200000, 20` | `WHERE id > 100020 LIMIT 20` |
|---|---|---|
| `EXPLAIN` type | `index` / `ALL` | **`range`** |
| 扫描行数 | 200020 | **20** |
| 回表次数 | 200020 | 20 |
| 复杂度 | O(offset + n) | **O(n)** |
| 能否跳页 | ✅ | ❌ 只能上一页/下一页 |
| 要求 | — | **排序列唯一且单调**（主键或时间戳） |

**注意**：如果是 `ORDER BY created_at DESC` 且 `created_at` 有重复值，需要**复合游标**：

```sql
-- 排序键不唯一时，用 (created_at, id) 两列做游标
SELECT * FROM t_order
WHERE (created_at, id) < ('2026-09-18 11:00:00', 100020)
ORDER BY created_at DESC, id DESC
LIMIT 20;
-- 需要索引：(created_at DESC, id DESC)（8.0 支持真降序索引）
```

#### 解法 2：延迟关联（必须跳页时用）

```sql
-- 原写法：200020 次回表
SELECT * FROM t_order ORDER BY created_at DESC LIMIT 200000, 20;

-- 优化：先在索引上翻页拿到 20 个主键，再回表 20 次
SELECT o.*
FROM t_order o
JOIN (
  SELECT id FROM t_order ORDER BY created_at DESC LIMIT 200000, 20
) t ON o.id = t.id;
```

**原理**：内层子查询只查 `id`，如果 `ORDER BY` 的列上正好有索引且 `id` 是二级索引的叶子内容（**覆盖索引**），那么内层是**纯索引扫描、零回表**，200000 行的扫描代价大幅降低（只扫索引页，不碰数据页）。外层只回表 20 次。

```sql
-- 验证内层是否覆盖索引
EXPLAIN SELECT id FROM t_order ORDER BY created_at DESC LIMIT 200000, 20;
-- Extra 应该出现 Using index
```

**注意 MySQL 8.0 的优化器改进**：8.0 对派生表有 `derived_merge` 优化，可能把子查询合并掉导致延迟关联失效。确认方式就是 `EXPLAIN` 看执行计划是否还是「先子查询再 JOIN」。

#### 解法 3：业务侧限制（最省事、最有效）

- 限制最大可翻页数（如只允许翻到第 500 页，再往后要求加筛选条件）
- UI 上用「无限滚动 / 游标」替代「页码跳转」
- 提供**近似结果**：`SHOW TABLES` 那种估算（不适合精确场景）
- 搜索类需求外迁到 ES（ES 的 `search_after` 就是游标分页，`from + size` 深翻页同样有 10000 上限）

### 三、`ORDER BY` 的成本

**两种情况**：

| 情况 | 表现 | 成本 |
|---|---|---|
| 走索引排序 | `Extra` 里**没有** `Using filesort` | 0，索引本身有序 |
| 需要 filesort | `Extra: Using filesort` | 在 `sort_buffer_size`（默认 256KB）里排；装不下 → 落盘 → `Sort_merge_passes` |

```sql
-- 看排序是否落盘
SHOW SESSION STATUS LIKE 'Sort%';
-- Sort_merge_passes > 0  → 发生了外部排序归并，必须优化
-- Sort_scan / Sort_range  → 排序方式
```

**消除 filesort 的两种方式**：

```sql
-- 索引 (status, created_at)
-- ✅ 无 filesort：等值列 + 排序列顺序一致
EXPLAIN SELECT * FROM t_order WHERE status = 2 ORDER BY created_at DESC;

-- ✅ 无 filesort：ORDER BY 带 LIMIT 时，优化器可能选用「优先队列」而非完整排序
EXPLAIN SELECT * FROM t_order WHERE status = 2 ORDER BY created_at DESC LIMIT 20;
-- Extra: Using index condition; Backward index scan

-- ❌ filesort：排序列与索引顺序不一致
EXPLAIN SELECT * FROM t_order WHERE status = 2 ORDER BY amount DESC;
```

**MySQL 8.0 的「优先队列优化」**：当 `ORDER BY ... LIMIT n` 且 n 很小时，8.0 可能改用堆排序（只维护 n 个元素），而不是全排。这需要在 `EXPLAIN FORMAT=JSON` 里看不到，但 `Extra` 会有变化。

### 四、大表分页的完整优化清单

```sql
-- 场景：订单列表，支持按状态筛选、按时间倒序、分页

-- ① 建立匹配查询的联合索引
ALTER TABLE t_order ADD KEY idx_status_created (status, created_at DESC, id DESC);

-- ② 用游标分页改写
SELECT id, order_no, amount, created_at
FROM t_order
WHERE status = 2
  AND (created_at, id) < ('2026-09-18 11:00:00', 100020)
ORDER BY created_at DESC, id DESC
LIMIT 20;
-- EXPLAIN 应为：type=range, key=idx_status_created, Extra=Using index condition

-- ③ 必须跳页时用延迟关联
SELECT o.* FROM t_order o
JOIN (
  SELECT id FROM t_order
  WHERE status = 2
  ORDER BY created_at DESC, id DESC
  LIMIT 200000, 20
) t ON o.id = t.id;

-- ④ 确认统计信息新鲜
ANALYZE TABLE t_order;
```

### 五、常见误区

| 误区 | 纠正 |
|---|---|
| 「加了 `LIMIT` 就快」 | `LIMIT` 只限制**返回**行数，不限制**扫描**行数。`LIMIT 200000,20` 照样扫 200020 行 |
| 「`ORDER BY` 有索引就一定不 filesort」 | 要**顺序和方向都对上**才算；`ASC/DESC` 混用（8.0 前）会失效 |
| 「延迟关联一定更快」 | 要求内层是**覆盖索引**。如果内层还要回表，那就是「两次回表」，更慢 |
| 「`SELECT *` 加索引就能解决分页」 | 覆盖索引必须包含所有 SELECT 的列，列太多时索引膨胀的代价可能超过收益 |
| 「游标分页能替代所有场景」 | 不能跳页、不能随机访问。运营后台的「跳到第 5000 页」需求必须用延迟关联或限制 |
:::

:::拓展
**`Backward index scan`（反向扫描）**

MySQL 8.0 引入了「反向扫描索引」的能力：`ORDER BY created_at DESC` 在升序索引上可以**从叶子链尾部往前扫**，不必 filesort。`EXPLAIN` 里会出现 `Backward index scan`。

```text
Extra: Using where; Backward index scan
```

**但它有代价**：反向扫描在 B+ 树里是「逆着页内记录链表走」，预读（read-ahead）机制基本失效。所以如果表本身是需要大量顺序读的，**建真正的降序索引可能更好**：

```sql
-- 8.0：真正的降序索引
ALTER TABLE t_order ADD KEY idx_created_desc (created_at DESC);
```

**其他数据库的深分页方案（横向对比）**

| 数据库 | 深分页写法 | 特点 |
|---|---|---|
| **MySQL** | `LIMIT m, n` | offset 有代价 |
| **PostgreSQL** | `LIMIT n OFFSET m` | 只支持 `OFFSET m`，**不支持 `LIMIT m, n`**（语法差异，见第 20 题） |
| **MongoDB** | `skip(m).limit(n)` | `skip` 同样要遍历，深 skip 一样慢；推荐用 `_id > last` 或 `search_after` 思路 |
| **Elasticsearch** | `from + size` / `search_after` | `from+size` 有 `max_result_window`（默认 10000）上限；`search_after` 是游标分页 |

**ES 的 `search_after` 和 MySQL 的游标分页是同一个思路**（用上一页的排序值作为下一页的起点），两边的限制也一样（不能跳页）。
:::

:::追问
**Q：`WHERE id > 100020` 为什么必须有索引才有效？**
如果没有索引，`WHERE id > 100020` 仍然要全表扫（找出所有满足的 id）。**游标分页的前提是「排序列上有索引」，这样 `range` 定位到起点后只需顺序扫 20 行。** 主键天然有索引，所以用主键做游标最省事。

**Q：延迟关联为什么要求内层是覆盖索引？**
内层 `SELECT id FROM t_order ORDER BY created_at DESC LIMIT 200000, 20`：
- 如果 `created_at` 上有索引，且索引叶子含 `id`（**二级索引叶子一定含主键**），那么内层查询完全在索引里完成，**不回表**，扫描的只是索引页。
- 如果需要回表（比如 `SELECT * `），那 200000 次回表一次不少，延迟关联就没有任何收益。

**Q：`COUNT(*)` 配合分页为什么也是性能问题？**
后台列表通常要「总数 + 当页数据」。`SELECT COUNT(*) FROM t_order WHERE status = 2` 在 InnoDB 里要扫描所有满足条件的行（见第 15 题）。优化方式：① 用 `COUNT(*)` 走覆盖索引（`idx_status_created` 可以覆盖）；② 业务上改成「是否有下一页」判断（查 `LIMIT n+1`）；③ 维护计数表（分状态计数，用触发器或应用双写）。

```sql
-- 用「多查一行」判断是否有下一页，彻底避免 count
SELECT id, order_no FROM t_order WHERE status = 2 ORDER BY id LIMIT 21;
-- 应用层：返回前 20 条，若有第 21 条则 hasMore = true
```

**Q：带条件的深分页（`WHERE status=2 AND created_at>x`）游标怎么写？**
`WHERE status = 2 AND (created_at, id) < (?, ?) ORDER BY created_at DESC, id DESC LIMIT 20`。索引 `(status, created_at DESC, id DESC)` 的等值列 `status` 放最前，后面紧跟排序列——正好是最左前缀 + 排序优化的组合。
:::

:::锚点
**深分页这个问题，你在 MongoDB 上踩过几乎一模一样的坑。**

MongoDB 的 `skip()` 和 MySQL 的 `OFFSET` 是同一类问题：

```javascript
// 慢：skip 要跳过 200000 个文档，每个都要访问
db.clbDetail.find({ taskId: "T001" }).skip(200000).limit(20)

// 快：游标分页（思路与 MySQL 完全一致）
db.clbDetail.find({ taskId: "T001", _id: { $gt: lastId } }).limit(20)
```

**面试话术**：

> 「深分页这个问题我在 MongoDB 上遇到过。RRM 的上报数据 `clbDetail` 是按 `taskId` 维度查的，数据量大，早期导出场景用了 `skip` 深翻页，慢得明显。**`skip` 和 MySQL 的 `OFFSET` 是同一类代价：都要先把前面 N 条走一遍再丢掉。** 后来改成基于 `_id` 的游标翻页（`_id > lastId`），并且把分片键和查询条件对齐，才达标。

> MySQL 这边我知道有三条路：**游标分页最优但要求不跳页，延迟关联适合必须跳页的场景（前提是内层能走覆盖索引），最省事的是业务上限制翻页深度。** 如果是「列表页 + 总数」的场景，还可以用查 `LIMIT n+1` 判断有没有下一页，把 `COUNT(*)` 这个大头也省掉。」

**加分细节**：主动提到「延迟关联的前提是内层覆盖索引，否则等于两次回表」——这个前提条件很多人会漏，说出来能立刻区分出「背过」和「想过」。
:::

---

## 7. 子查询为什么不走索引（派生表、semi-join、NOT IN 的 NULL 陷阱）

:::概念
**子查询慢的三个根因**：
① `FROM` 子查询（派生表）在 5.7 会被**物化成无索引的临时表**，外层对它扫全表；
② `IN` 子查询里的表可能被反复执行 N 次（关联子查询），或者优化器放弃了 semi-join 改写；
③ **`NOT IN` 的子查询结果里有 `NULL` 时，整个条件永远不为真**，退化成全表扫甚至返回空集。
记忆钩子：**「派生表无索引 / 关联子查询 N 次 / NOT IN 遇 NULL 全完」。**
:::

:::提问
- 子查询为什么不走索引？怎么优化？
- `IN` 和 `EXISTS` 怎么选？
- 关联子查询为什么慢？
- `NOT IN` 有什么坑？
- 什么是 semi-join？有哪些执行策略？
- `SELECT ... WHERE id IN (SELECT ...)` 优化器会怎么改写？
:::

:::答案
### 一、子查询出现在哪三个位置，问题各不同

```sql
-- ① FROM 子查询（派生表 / derived table）
SELECT * FROM (SELECT user_id, COUNT(*) c FROM t_order GROUP BY user_id) t WHERE t.c > 10;

-- ② WHERE 里的 IN / NOT IN 子查询
SELECT * FROM t_user WHERE id IN (SELECT user_id FROM t_order WHERE status = 2);

-- ③ WHERE 里的 EXISTS / NOT EXISTS（关联子查询）
SELECT * FROM t_user u WHERE EXISTS (SELECT 1 FROM t_order o WHERE o.user_id = u.id);
```

### 二、派生表：5.7 会物化，8.0 会合并

**MySQL 5.7 及以前**：`FROM` 里的子查询会被**物化（Materialization）**成一张临时表。临时表**默认没有索引**（除非优化器自动加索引，`derived_merge` 不适用时），外层查询对它的过滤只能全扫。

```sql
-- 5.7 的执行计划
EXPLAIN SELECT * FROM (SELECT * FROM t_order WHERE status = 2) t WHERE t.user_id = 100;
-- id=1 table=t   type=ALL  Extra=Using where        ← 外层全扫临时表
-- id=2 table=o   type=ALL  Extra=Using where        ← 内层也全扫
```

**MySQL 8.0 引入了 `derived_merge`（派生表合并）优化，默认开启**：优化器会把 `FROM` 子查询「展平」成一个普通 JOIN，让外层的条件下推到内层，从而用上索引。

```sql
-- 8.0 的执行计划（derived_merge 生效）
EXPLAIN SELECT * FROM (SELECT * FROM t_order WHERE status = 2) t WHERE t.user_id = 100;
-- id=1 table=o  type=ref  key=idx_user_status  Extra=Using index condition
--              ↑ 子查询被合并掉了，直接查基表并走了索引
```

**但 `derived_merge` 不是万能的**，以下情况无法合并，仍然物化：

| 阻断合并的写法 | 例子 |
|---|---|
| 子查询里有 `GROUP BY` / `DISTINCT` / `LIMIT` / 聚合函数 | `(SELECT user_id, COUNT(*) FROM ...GROUP BY user_id)` |
| 子查询里有 `UNION` / `UNION ALL` | `(SELECT a FROM t1 UNION SELECT a FROM t2)` |
| `SELECT` 列表里有子查询 | `(SELECT (SELECT MAX(x) FROM y))` |
| 子查询是 `LEFT JOIN` 的右表且外层有 WHERE 引用它 | — |

```sql
-- 查看 optimizer_switch 里 derived_merge 的状态
SHOW VARIABLES LIKE 'optimizer_switch'\G
-- derived_merge=on

-- 关掉做对比（验证是否真的合并了）
SET SESSION optimizer_switch = 'derived_merge=off';
EXPLAIN SELECT * FROM (SELECT * FROM t_order WHERE status = 2) t WHERE t.user_id = 100;
-- 此时会看到物化的临时表 + type=ALL
SET SESSION optimizer_switch = 'derived_merge=on';
```

**💡 MySQL 5.7 的补救手段**：5.7 无法自动合并时，优化器会给物化临时表**自动加索引**（`Using index for temporary table`，需要 `derived_merge` 关闭且 `optimizer_switch` 里 `materialization` 相关开关开启）。但可靠性远不如 8.0。

**最保险的做法：直接把派生表改成 JOIN。**

```sql
-- 改成 JOIN（任何版本都能用索引）
SELECT u.user_id, COUNT(*) AS c
FROM t_order u
WHERE u.status = 2
GROUP BY u.user_id
HAVING c > 10;
```

### 三、`IN` 子查询：semi-join 的四种策略

`semi-join`（半连接）的含义：**只要左表某行在右表里能找到匹配，就返回左表这一行，且只返回一次**（不产生笛卡尔积的重复行）。

**前提**：SQL 是「子查询结果只用于过滤、不参与外部计算」的形式（没有 `NOT IN`、没有在 SELECT 列表里等）。优化器会尝试把它改写成 semi-join，然后从下面四种策略里选：

| 策略 | 适用条件 | 机制 | `EXPLAIN` 里的标志 |
|---|---|---|---|
| **FirstMatch** | 通用，默认候选 | 从外表的每一行出发，到内表找第一条匹配就停（不继续找剩余匹配） | `Extra` 里出现 `FirstMatch(表名)` |
| **LooseScan** | 内表的关联列有索引且值有重复（索引松散扫描） | 在内表索引上跳跃扫描，每组重复值只取一个 | `Extra` 里出现 `LooseScan(m..n)` |
| **Materialization** | 内表数据量小 | 把内表**物化成带索引的临时表**，再和外表做 JOIN | `Extra` 里出现 `Start temporary / End temporary` |
| **DuplicateWeedout** | 内表一值对多行时用来去重 | 建临时表记录已匹配的外表行 id，避免重复返回 | `Extra` 里出现 `Start temporary / End temporary` |

```sql
-- 看优化器选了什么策略
EXPLAIN SELECT * FROM t_user
WHERE id IN (SELECT user_id FROM t_order WHERE status = 2)\G

-- 关闭 semi-join，退回「先物化子查询再 IN」的朴素做法（做对比）
SET SESSION optimizer_switch = 'semijoin=off';
EXPLAIN SELECT * FROM t_user
WHERE id IN (SELECT user_id FROM t_order WHERE status = 2)\G
SET SESSION optimizer_switch = 'semijoin=on';
```

**`SHOW WARNINGS` 能直接看到改写后的 SQL**——这是最有用的一招：

```sql
EXPLAIN SELECT * FROM t_user WHERE id IN (SELECT user_id FROM t_order WHERE status = 2);
SHOW WARNINGS\G
-- 输出里会看到类似：
-- /* select#1 */ select `t_user`.`id` from `t_user`
--   semi join (`t_order`) where (`t_order`.`user_id` = `t_user`.`id`)
--   ↑ 明确告诉你改写成了 semi join
```

### 四、关联子查询（EXISTS / 相关子查询）：N 次执行

```sql
-- 关联子查询：内层引用了外层的 u.id
SELECT * FROM t_user u
WHERE EXISTS (SELECT 1 FROM t_order o WHERE o.user_id = u.id AND o.status = 2);
```

**朴素执行方式**：外层每扫一行 `u`，就把内层子查询**完整执行一次**（把 `u.id` 代进去）。外表 100 万行 → 内层执行 100 万次（每次可能很快，加起来很慢）。

**优化器通常能把它改写成 semi-join**，规则与 `IN` 相同：

```sql
EXPLAIN SELECT * FROM t_user u
WHERE EXISTS (SELECT 1 FROM t_order o WHERE o.user_id = u.id AND o.status = 2)\G
-- 理想是关键点：`o.user_id` 上有索引，被驱动表走 ref/eq_ref，而不是每行全扫
```

**关键：无论优化器怎么改写，`t_order.user_id` 上必须有索引。** 没有索引时，任何策略都退化成「每次找都要全表扫 t_order」——这就是「子查询不走索引」最常见的真相：

> **不是「子查询」这个语法不走索引，而是子查询关联的那个列上本来就没有索引。**

### 五、`IN` vs `EXISTS`：小表驱动大表

**核心原则：让「小结果集」驱动「大表」，且被驱动表的关联列有索引。**

| 场景 | 推荐写法 | 原因 |
|---|---|---|
| 子查询结果集小，外层表大 | **`IN`** | 先把小结果集拿出来，再拿它去大表上按索引查 |
| 外层结果集小，子查询表大 | **`EXISTS`** | 外层每行一次探测；外层小则探测次数少 |
| 两者都大 | 都不理想，改成 **JOIN** | 让优化器自由选择驱动顺序 |
| 不确定 | **统一改 JOIN** | 最稳，且优化器有两个方向可选 |

```sql
-- IN：适合子查询结果小
SELECT * FROM t_big WHERE id IN (SELECT id FROM t_small WHERE flag = 1);

-- EXISTS：适合外层结果小
SELECT * FROM t_small s WHERE EXISTS (SELECT 1 FROM t_big b WHERE b.id = s.id);

-- 统一改 JOIN（优化器可选驱动顺序）
SELECT DISTINCT s.* FROM t_small s JOIN t_big b ON b.id = s.id WHERE b.flag = 1;
-- 注意：JOIN 可能产生重复行，需要 DISTINCT（这本身有代价）
```

**MySQL 8.0 的变化**：8.0 里 `IN` 子查询的 semi-join 优化更激进，`IN` 和 `EXISTS` 的性能差异**已经不明显**（优化器都会尝试同样的改写）。5.7 及以前差异更明显。

### 六、`NOT IN` 的 NULL 陷阱（面试官最爱考）

**规则**：`x NOT IN (v1, v2, ..., NULL)` 在 SQL 三值逻辑下**永远不返回真**（因为 `x <> NULL` 的结果是 `UNKNOWN`，不是 `TRUE`），所以**只要子查询结果里有任意一个 NULL，整个 `NOT IN` 查询返回空集**。

```sql
-- 演示
CREATE TABLE t_a (id INT);
CREATE TABLE t_b (id INT NULL);
INSERT INTO t_a VALUES (1), (2), (3);
INSERT INTO t_b VALUES (1), (NULL);

-- 期望返回 2, 3，实际返回 空
SELECT * FROM t_a WHERE id NOT IN (SELECT id FROM t_b);

-- 验证：加上 IS NOT NULL 就正常了
SELECT * FROM t_a WHERE id NOT IN (SELECT id FROM t_b WHERE id IS NOT NULL);
-- 返回 2, 3
```

**性能层面的额外后果**：因为结果可能为空，优化器**不敢把 `NOT IN` 改写成 anti-join**（5.7 里不支持，8.0 部分支持），只能退化成**「对每个外层行扫描一遍内层结果集」**，即全表扫。

**正确写法（三种）**：

```sql
-- ① 显式排除 NULL（最直接）
SELECT * FROM t_a WHERE id NOT IN (SELECT id FROM t_b WHERE id IS NOT NULL);

-- ② 改成 EXISTS 的反面（anti-join，8.0 支持较好）
SELECT * FROM t_a a WHERE NOT EXISTS (SELECT 1 FROM t_b b WHERE b.id = a.id);

-- ③ 改成 LEFT JOIN + IS NULL（最通用的 anti-join 手写形式）
SELECT a.* FROM t_a a
LEFT JOIN t_b b ON a.id = b.id
WHERE b.id IS NULL;
```

### 七、子查询优化的通用清单

| 问题 | 处置 |
|---|---|
| `FROM` 子查询被物化 | 优先改写成 JOIN；确认 `derived_merge=on`；避免在派生表里写 `GROUP BY`/`LIMIT` |
| `IN` 子查询慢 | 确认内表关联列有索引；`SHOW WARNINGS` 看有没有走 semi-join；改 JOIN |
| 关联子查询 N 次执行 | 改 JOIN；确保被驱动表关联列有索引 |
| `NOT IN` 遇 NULL | 加 `IS NOT NULL` / 改 `NOT EXISTS` / 改 `LEFT JOIN ... IS NULL` |
| 不确定优化器在干什么 | `EXPLAIN` + **`SHOW WARNINGS`**（看改写后的 SQL）+ `EXPLAIN FORMAT=JSON` |
| 5.7 环境 | 派生表优化能力弱，**能改 JOIN 就改 JOIN** |
:::

:::拓展
**`EXPLAIN FORMAT=JSON` 里的 `materialized_from_subquery`**

```sql
EXPLAIN FORMAT=JSON
SELECT * FROM t_user WHERE id IN (SELECT user_id FROM t_order WHERE status = 2)\G
```

JSON 输出里如果出现 `materialized_from_subquery`，说明子查询被物化了；出现 `"using_temporary_table": true` 说明用了临时表；出现 `"attached_condition"` 可以看到条件下推到哪一层。这比文本格式信息多得多。

**`optimizer_switch` 里与子查询相关的开关**

```sql
SHOW VARIABLES LIKE 'optimizer_switch'\G
-- semijoin=on                       总开关
-- firstmatch=on                     FirstMatch 策略
-- loosescan=on                      LooseScan 策略
-- duplicateweedout=on               DuplicateWeedout 策略
-- materialization=on                物化（含 semi-join 的物化策略）
-- derived_merge=on                  派生表合并
-- subquery_materialization_cost_based=on   是否按代价决定物化
-- condition_fanout_filter=on
```

**调优时的正确姿势**：用 `SET SESSION`（只影响当前连接）逐个开关做 A/B 对比，**不要动 GLOBAL**——生产上全局改优化器开关是最容易引发事故的操作之一。

```sql
-- 典型对比实验
SET SESSION optimizer_switch = 'semijoin=off';
EXPLAIN ANALYZE SELECT ...;
SET SESSION optimizer_switch = 'semijoin=on';
EXPLAIN ANALYZE SELECT ...;
-- 用 EXPLAIN ANALYZE（8.0.18+）看真实耗时，比只看 rows 估算靠谱得多
```

**为什么 ORM 更容易踩这个坑**

MyBatis-Plus、JPA 这类 ORM 在 `IN` 集合很大时（比如 `WHERE id IN (10000 个 id)`）会生成超大 SQL：① SQL 解析本身耗时；② 优化器在选择访问路径上耗时；③ 可能放弃索引直接全扫。**处置：把大 `IN` 改成 `JOIN` 临时表，或者按 1000 个一批拆分执行。**
:::

:::追问
**Q：`IN (子查询)` 和 `IN (常量列表)` 在执行计划上有什么区别？**
`IN (常量列表)` 是纯值列表，优化器直接用索引做**多等值查找**（`type=range`，`Extra` 里可能是 `Using index condition`），代价可预估。
`IN (子查询)` 需要先把子查询算出结果集，再决定用什么策略（semi-join 四种之一或物化）。**所以子查询会多一层不确定性，`EXPLAIN` 里会看到多一行 id=2 的执行计划。**

**Q：`SELECT ... WHERE id IN (SELECT ...)` 被改写成 JOIN 后，为什么不用 `DISTINCT`？**
因为 semi-join 的语义就是「左表行只要匹配上就返回**一次**」，优化器在内部处理了去重（用 DuplicateWeedout 策略时通过临时表去重），不需要用户写 `DISTINCT`。**你自己改写成普通 `JOIN` 时反而必须加 `DISTINCT`，否则可能返回重复行——这是手写改写时的常见错误。**

**Q：`NOT EXISTS` 和 `LEFT JOIN ... IS NULL` 哪个更快？**
MySQL 8.0 里两者都能被优化器识别成 anti-join，性能接近。5.7 里 `NOT EXISTS` 的优化支持更好一些。**但 `LEFT JOIN ... IS NULL` 必须先确认 `b.id` 是非空的**——如果 `b.id` 可为 NULL，`WHERE b.id IS NULL` 会把「左表有行、右表全是 NULL」的匹配行也一起算进去，结果就错了。**`NOT EXISTS` 的语义最安全。**

**Q：为什么说「子查询不走索引」这个说法不准确？**
因为索引失效的原因从来不是「用了子查询」，而是：① 子查询的结果被物化成**临时表**（临时表默认无索引）；② 关联子查询的**被驱动列上没有索引**；③ 优化器放弃了改写。**只要把子查询改写成 JOIN 并且关联列上有索引，一切就正常了。** 面试时说「子查询不走索引」而不解释机制，会被追问到底。
:::

:::锚点
**这道题对你有个特别现实的落点：Java 后端最容易写出的「N+1 查询」问题，本质就是关联子查询的翻版。**

```java
// 典型 N+1：查 100 个用户，然后循环里每个人查一次订单
List<User> users = userMapper.selectAll();
for (User u : users) {
    List<Order> orders = orderMapper.selectByUserId(u.getId());  // 执行 100 次 SQL
}

// 改成批量：一次查完
List<Long> ids = users.stream().map(User::getId).collect(toList());
List<Order> orders = orderMapper.selectByUserIds(ids);          // 一条 IN 查询
```

**面试话术**：

> 「我在 RRM 项目里主要用 MongoDB，Java 这块在补，但有一类问题是两边共通的：**循环里发查询导致的 N 次调用**。在 Mongo 里对应的是在循环里做 `findOne`，我们一般会改成一次 `$in` 查回来再在内存里分组。**MySQL 里的『关联子查询对外表每行执行一次』和这个完全是同一类问题**——所以我在写 MyBatis 时会特别注意不要写出循环里查库的代码，要么批量 `IN`，要么手写 JOIN 一次拿回来。」

**如果被追问「MySQL 的 `NOT IN` 你怎么处理」**：

> 「`NOT IN` 我会主动避开。因为只要子查询结果里有一个 NULL，整个条件在 SQL 三值逻辑下就永远不为真，查询直接返回空集——这是逻辑错误而不只是性能问题。**我一般改用 `NOT EXISTS` 或者 `LEFT JOIN ... WHERE 右表.id IS NULL`，语义更安全，而且 MySQL 8.0 能把它们识别成 anti-join。**」

**注意**：上面讲的是「我知道并且会主动规避」，而不是「我在生产 MySQL 上被 `NOT IN` 坑过」。**不要给 SQL 错误编一个项目故事**——这类问题面试官一追问「哪张表、什么业务、发现过程是什么」就没法圆了。把「我知道原理 + 我知道怎么规避」讲清楚，本身就是合格的回答。
:::

---

## 8. EXPLAIN 逐列详解 ★

:::概念
`EXPLAIN` 是 SQL 优化的**唯一入口**。抓住四列就够用：**`type`（怎么访问）、`key`（用了哪个索引）、`rows`（估算扫多少行）、`Extra`（有没有额外的坑）**。
再进一阶：`key_len` 反推用了几列索引，`filtered` 看条件下推后还剩多少，`EXPLAIN FORMAT=JSON` 看代价，`EXPLAIN ANALYZE` 看真实耗时。
:::

:::提问
- `EXPLAIN` 里各个字段是什么意思？
- `type` 有哪些取值？什么算合格？
- `key_len` 怎么推出的用了几列索引？
- `filtered` 是什么意思？
- `Using filesort` / `Using temporary` 要紧吗？
- `EXPLAIN` 的 `rows` 和实际差很多怎么办？
:::

:::答案
### 一、先建一张表，后面所有输出都基于它

```sql
DROP TABLE IF EXISTS `t_order`;
CREATE TABLE `t_order` (
  `id`         BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  `order_no`   VARCHAR(32)     NOT NULL,
  `user_id`    BIGINT UNSIGNED NOT NULL,
  `status`     TINYINT         NOT NULL DEFAULT 0,   -- 0待付 1已付 2已发 3完成
  `amount`     DECIMAL(12,2)   NOT NULL,
  `remark`     VARCHAR(200)    DEFAULT NULL,
  `created_at` DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_order_no` (`order_no`),
  KEY `idx_user_status` (`user_id`, `status`),
  KEY `idx_status_created` (`status`, `created_at`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
```

### 二、一份真实 EXPLAIN 输出

```sql
EXPLAIN SELECT o.id, o.order_no, o.amount
FROM t_order o
WHERE o.user_id = 1001 AND o.status = 2
ORDER BY o.created_at DESC
LIMIT 10\G
```

```text
*************************** 1. row ***************************
           id: 1
  select_type: SIMPLE
        table: o
   partitions: NULL
         type: ref
possible_keys: idx_user_status,idx_status_created
          key: idx_user_status
      key_len: 9
          ref: const,const
         rows: 32
     filtered: 100.00
        Extra: Using index condition; Using filesort
1 row in set, 1 warning (0.00 sec)
```

### 三、逐列拆解

| 列 | 本例的值 | 含义 | 怎么用 |
|---|---|---|---|
| **`id`** | 1 | 查询中每个 `SELECT` 的序号。**id 相同 → 从上往下执行；id 不同 → 数字大的先执行** | 定位子查询/UNION 的执行顺序 |
| **`select_type`** | `SIMPLE` | 查询类型，见下方表格 | 判断有没有子查询、UNION、派生表 |
| `table` | `o` | 正在访问的表（或别名）。`<derived2>` 表示派生表，`<union1,2>` 表示合并结果 | 找到慢在哪张表 |
| `partitions` | `NULL` | 命中的分区 | 分区表才关心 |
| **`type`** | `ref` | **访问类型**，最重要的一列，见下方排序表 | 目标是 `ref` 及以上，避免 `ALL` |
| `possible_keys` | `idx_user_status,idx_status_created` | **理论上可用**的索引 | 有值但 `key` 是 NULL → 优化器算完代价放弃了索引 |
| **`key`** | `idx_user_status` | **实际选用**的索引 | 为 NULL 就是没走索引 |
| **`key_len`** | `9` | 索引中**实际参与比较**的字节数 | **反推用了几列索引**，见下方计算 |
| `ref` | `const,const` | 与索引列做比较的对象（`const` = 常量，`表.列` = 关联列） | `const` 说明是常量等值，性能好 |
| **`rows`** | `32` | **估算**要扫描的行数（越小越好） | 与实际差太多 → `ANALYZE TABLE` |
| **`filtered`** | `100.00` | 存储引擎返回的行中，**再经过 WHERE 过滤后剩下的百分比** | 该值很低说明扫了很多无用行，考虑 ICP 或调整索引 |
| **`Extra`** | `Using index condition; Using filesort` | 附加信息，**藏坑最多的一列** | 见下方对照表 |

### 四、`select_type` 取值

| 值 | 含义 |
|---|---|
| `SIMPLE` | 简单查询，无子查询/UNION |
| `PRIMARY` | 最外层查询 |
| `SUBQUERY` | SELECT 列表或 WHERE 里的**非关联**子查询（只执行一次） |
| `DEPENDENT SUBQUERY` | **关联**子查询（外层每行执行一次）← **重点排查对象** |
| `UNCACHEABLE SUBQUERY` | 结果不能被缓存的子查询 |
| `DERIVED` | `FROM` 里的子查询（派生表），可能被物化 |
| `MATERIALIZED` | 被物化的子查询 |
| `UNION` / `UNION RESULT` | UNION 的各分支 / 合并结果 |
| `DEPENDENT UNION` | UNION 里依赖外层的分支 |

**看到 `DEPENDENT SUBQUERY` 就要警觉**——它几乎总意味着「外层每行执行一次子查询」。

### 五、`type` 排序（从好到坏）

| type | 含义 | 一句话判据 |
|---|---|---|
| `system` | 表只有一行（系统表） | 理论最优，实际极少 |
| `const` | 通过主键/唯一索引**等值**查到**最多一行** | 常量级，最快 |
| `eq_ref` | JOIN 时被驱动表**用主键/唯一索引等值匹配**，每次匹配一行 | 多表 JOIN 的最优 |
| `ref` | 用**非唯一索引**等值匹配，可能多行 | ✅ **合格线** |
| `fulltext` | 全文索引 | 特殊场景 |
| `ref_or_null` | 类似 `ref` 但额外查 NULL 行 | 类似 ref |
| `index_merge` | 索引合并（OR 两侧都是索引列） | 次优，注意会不会退化成 ALL |
| `range` | 索引**范围**扫描（`>`, `<`, `BETWEEN`, `IN`, `LIKE 'x%'`） | ✅ 合格 |
| `index` | **全索引扫描**（扫所有叶子，但扫的是索引页不是数据页） | ⚠️ 勉强，比 ALL 好 |
| `ALL` | **全表扫描** | ❌ 必须优化 |

```sql
-- const：主键等值
EXPLAIN SELECT * FROM t_order WHERE id = 100;
-- type: const   key: PRIMARY   rows: 1

-- eq_ref：被驱动表用主键等值 JOIN
EXPLAIN SELECT * FROM t_order o JOIN t_user u ON o.user_id = u.id WHERE o.id = 100;
-- 预期：u 那行 type=eq_ref, key=PRIMARY

-- range：范围查询
EXPLAIN SELECT * FROM t_order WHERE id BETWEEN 100 AND 200;
-- type: range

-- ALL：没走索引
EXPLAIN SELECT * FROM t_order WHERE amount > 100;
-- type: ALL   key: NULL   rows: 全表行数
```

### 六、`key_len` 怎么算（重点，面试高频）

**`key_len` = 索引中实际参与比较的列，各自的字节数之和。**

**各类型的字节数**：

| 类型 | 字节 | 说明 |
|---|---|---|
| `TINYINT` | 1 | |
| `SMALLINT` | 2 | |
| `MEDIUMINT` | 3 | |
| `INT` | 4 | |
| `BIGINT` | 8 | |
| `FLOAT` | 4 | |
| `DOUBLE` | 8 | |
| `DATE` | 3 | |
| `DATETIME` | **5**（MySQL 5.6+） | 5.5 及以前是 8 |
| `TIMESTAMP` | 4 | |
| `CHAR(n)` | n × 字符集字节数 | utf8mb4 = 4 字节/字符，但索引里按实际最大 3 字节算 |
| `VARCHAR(n)` | n × 字符集字节数 + 2 或 3 | 长度标识；≤255 用 1 字节，>255 用 2 字节 |

**额外规则**：**列允许为 NULL，`key_len` 加 1 字节**（NULL 标志位）。

**计算示例**（用第 1 题的表 `idx_name_age_city (name VARCHAR(50), age INT, city VARCHAR(30))`，字符集 utf8mb4）：

```text
name  VARCHAR(50)：50 × 4 + 2(变长) = 202，NOT NULL 不加
age   INT(11)：4，NOT NULL 不加
city  VARCHAR(30)：30 × 4 + 2 = 122，可为 NULL → +1 = 123

只用到 name           → key_len = 202
用到 name + age       → key_len = 202 + 4 = 206
用到 name + age + city→ key_len = 206 + 123 = 329
```

```sql
-- 实测验证
EXPLAIN SELECT * FROM t_user WHERE name = '李鑫'\G
-- key_len: 202   → 只用了 name 一列

EXPLAIN SELECT * FROM t_user WHERE name = '李鑫' AND age = 30\G
-- key_len: 206   → 用了两列

EXPLAIN SELECT * FROM t_user WHERE name = '李鑫' AND age = 30 AND city = '成都'\G
-- key_len: 329   → 三列全用上

EXPLAIN SELECT * FROM t_user WHERE name = '李鑫' AND city = '成都'\G
-- key_len: 202   → 只有 name！city 跳过了 age，没能用于定位
```

**`key_len` 是验证「最左前缀到底用了几列」的唯一硬证据**，比看 SQL 猜靠谱得多。

**关于 utf8mb4 的 3 还是 4**：B+ 树的 `key_len` 计算用的是**字符集的最大字节数**。`utf8mb4` 最大 4 字节，但 InnoDB 索引计算时对 `VARCHAR` 用的是 **4 字节/字符**（5.5 是 3，因为当时 utf8mb4 支持不完整）。所以 `VARCHAR(50)` 在 utf8mb4 下是 `50×4+2 = 202`。**不同版本可能有 1 字节差异，用 `EXPLAIN` 实测最准。**

```sql
-- 用 >255 字符的 VARCHAR 会多 1 字节长度标识
ALTER TABLE t_user ADD COLUMN addr VARCHAR(300);
-- VARCHAR(300)：300 × 4 + 2 = 1202，可空再 +1
```

### 七、`filtered` 是什么意思

**`filtered` = 存储引擎返回的行中，经过 WHERE 剩余条件过滤后仍保留的百分比。**

- `rows × filtered%` ≈ 最终参与后续操作（JOIN / 排序）的行数
- `filtered = 100.00` 表示引擎返回的行**全部**满足条件（理想）
- `filtered` 很低（如 `5.00`）说明**引擎返回了大量的无效行** —— 这是 ICP 或索引设计不足的信号

```sql
-- filtered 低的典型例子
EXPLAIN SELECT * FROM t_order WHERE user_id = 1001 AND remark LIKE '%加急%'\G
-- rows: 32  filtered: 10.00
-- 含义：引擎按 user_id 返回 32 行，但只有 10% 满足 remark 条件 → 白扫 29 行
```

**注意**：`filtered` 在 MySQL 5.7 之前**恒为 100.00**（不真实计算），**5.7 起才真正估算**。所以老版本上这一列没有参考价值。

### 八、`Extra` 常见值对照表（坑都在这里）

| Extra 值 | 含义 | 好坏 | 处置 |
|---|---|---|---|
| **`Using index`** | **覆盖索引**，不需要回表 | ✅ 好 | 保持 |
| **`Using index condition`** | 走了 **ICP**（索引下推），条件下推到引擎层过滤 | ✅ 好 | 保持 |
| `Using where` | 在 server 层做了过滤 | ⚠️ 中性 | 结合 `rows` 判断；若 rows 很大则需优化 |
| **`Using filesort`** | **需要额外排序**（不能在索引里直接得到有序结果） | ⚠️ 有代价 | 加/改索引让排序走索引；小结果集可接受 |
| **`Using temporary`** | **用了临时表**（常见于 `GROUP BY`、`DISTINCT`、`UNION`） | ⚠️ 有大代价 | 改索引让 GROUP BY 走索引顺序；或改写 SQL |
| `Using join buffer (hash join)` | 被驱动表没索引，用了 JOIN BUFFER | ❌ 差 | 给被驱动表关联列加索引 |
| `Using MRR` | 用了 Multi-Range Read（把随机回表转成顺序读） | ✅ 好 | 由 `optimizer_switch` 控制 |
| `Using index for group-by` | GROUP BY 走了松散索引扫描 | ✅ 很好 | 保持 |
| `Backward index scan` | 反向扫描索引 | ⚠️ 中性 | 8.0 特性，深分页/倒序时出现 |
| `Impossible WHERE` | WHERE 恒为假，不查表直接返回空 | ✅ 不耗时 | 检查 SQL 逻辑是否写错 |
| `Select tables optimized away` | 优化器用索引元数据直接算出结果（如 `MIN/MAX` 走索引） | ✅ 最好 | 保持 |
| `Distinct` | 优化器优化了 DISTINCT | ✅ | 保持 |
| `Start temporary` / `End temporary` | 用了 semi-join 的物化/去重策略 | ⚠️ 中性 | 见第 7 题 |
| `No tables used` | 没有 FROM 或 FROM DUAL | ✅ | — |
| `Zero limit` | `LIMIT 0`，直接返回空 | ✅ | — |

**两个最容易出问题的组合**：

```text
Using temporary; Using filesort     ← GROUP BY + ORDER BY 组合，双杀，必须优化
Using join buffer (hash join)       ← 被驱动表缺索引，典型 N 次全表扫
```

### 九、`EXPLAIN FORMAT=JSON`：看到「代价」

文本格式看不到优化器的**代价估算**，JSON 格式能：

```sql
EXPLAIN FORMAT=JSON
SELECT o.id, o.order_no FROM t_order o
WHERE o.user_id = 1001 AND o.status = 2
ORDER BY o.created_at DESC LIMIT 10\G
```

关键字段：

```json
{
  "query_block": {
    "select_id": 1,
    "cost_info": {
      "query_cost": "12.35"                ← 整个查询的估算代价
    },
    "ordering_operation": {
      "using_filesort": true,              ← 确认发生了 filesort
      "cost_info": { "sort_cost": "3.20" },← 排序单独的代价
      "table": {
        "table_name": "o",
        "access_type": "ref",
        "possible_keys": ["idx_user_status","idx_status_created"],
        "key": "idx_user_status",
        "used_key_parts": ["user_id","status"],   ← ★ 直接告诉你用了几列！比 key_len 直观
        "key_length": "9",
        "ref": ["const","const"],
        "rows_examined_per_scan": 32,
        "rows_produced_per_join": 32,
        "filtered": "100.00",
        "cost_info": {
          "read_cost": "8.75",
          "eval_cost": "0.32",
          "prefix_cost": "9.07",           ← 到这一步的累计代价
          "data_read_per_join": "512"
        },
        "used_columns": ["id","order_no","user_id","status","created_at"],
        "attached_condition": "((`o`.`user_id` = 1001) and (`o`.`status` = 2))"
      }
    }
  }
}
```

**`used_key_parts` 是 JSON 格式独有的好东西**——它直接把「索引用了几列、用了哪几列」列出来，不用你手算 `key_len`。**`query_cost` 可以用来做 A/B 对比：改写 SQL 后对比代价是否下降。**

```sql
-- 用 JSON 格式做改写前后的代价对比
EXPLAIN FORMAT=JSON SELECT ...\G | grep query_cost
```

### 十、`EXPLAIN ANALYZE`（MySQL 8.0.18+）：看真实执行

`EXPLAIN` 给的是**估算**，`EXPLAIN ANALYZE` 会**真正执行** SQL，输出**实际**的行数和耗时。

```sql
EXPLAIN ANALYZE
SELECT o.id, o.order_no FROM t_order o
WHERE o.user_id = 1001 AND o.status = 2
ORDER BY o.created_at DESC LIMIT 10;
```

```text
-> Sort: o.created_at DESC, limit input to 10 row(s) per chunk  (cost=12.35 rows=32) (actual time=0.312..0.318 rows=10 loops=1)
    -> Filter: ((o.user_id = 1001) and (o.status = 2))  (cost=9.07 rows=32) (actual time=0.048..0.276 rows=32 loops=1)
        -> Index lookup on o using idx_user_status (user_id=1001, status=2)  (cost=9.07 rows=32) (actual time=0.042..0.241 rows=32 loops=1)
```

| 字段 | 含义 |
|---|---|
| `cost=12.35 rows=32` | **估算**的代价和行数（和 `EXPLAIN` 一致） |
| `actual time=0.312..0.318` | **实际**耗时：第一个数是「返回第一行」的时间，第二个是「返回所有行」的时间（单位 ms） |
| `actual ... rows=10` | **实际**返回行数 |
| `loops=1` | 这个算子被执行了几次。**`loops` 很大就是「被驱动表被反复执行」的铁证** |
| `->` 缩进 | 缩进层次 = 执行计划的树形结构，**最内层最先执行** |

**`EXPLAIN ANALYZE` 的代价：它会真的跑一遍 SQL**（写操作会真的写）。**生产上慎用，尤其是 UPDATE/DELETE。** 分析大表查询时，加个 `LIMIT` 或先在从库上跑。

**注意它不显示 `Extra` 列**，但树形输出里已经包含了关键信息（`Sort` 节点 = filesort，`Temporary table` 节点 = 临时表）。

### 十一、一条完整的使用流程

```text
① EXPLAIN 看四列：type / key / rows / Extra
   - type=ALL 或 key=NULL  → 没走索引，回到索引设计（第 1、4 题）
   - Extra 有 filesort/temporary → 索引顺序不匹配，调整索引列顺序
   - rows 很大但 filtered 很低  → 条件下推不足，考虑 ICP / 改索引

② key_len 验证最左前缀用了几列（或直接看 FORMAT=JSON 的 used_key_parts）

③ EXPLAIN FORMAT=JSON 看 query_cost，作为改写前的基线

④ 改写 SQL / 加索引，再看一次 EXPLAIN，对比 query_cost 和 rows

⑤ EXPLAIN ANALYZE 验证真实耗时（8.0.18+，注意只在非生产或加 LIMIT）

⑥ 上线后回看慢日志：该 SQL 指纹是否还出现；对比 P99
```

### 十二、EXPLAIN 版的「体检清单」

| 检查项 | 合格标准 |
|---|---|
| `type` | ≥ `range`（关键查询最好是 `ref` / `eq_ref`） |
| `key` | 不为 NULL |
| `possible_keys` 有值但 `key` 为 NULL | 需要 `ANALYZE TABLE` 或调优索引 |
| `rows` | 与实际结果集同量级 |
| `filtered` | 尽量接近 100 |
| `Extra` | 没有 `Using temporary`；`Using filesort` 仅在结果集小时可接受 |
| `Extra` | 尽量出现 `Using index`（覆盖索引）或 `Using index condition`（ICP） |
| `key_len` | 与预期用到的列数一致 |
:::

:::拓展
**`optimizer_trace`：看优化器「怎么想」的（进阶）**

```sql
-- 开启 trace（只对当前 session）
SET optimizer_trace = 'enabled=on';
SET optimizer_trace_max_mem_size = 1048576;   -- 默认 1M

SELECT * FROM t_order WHERE user_id = 1001 AND status = 2;

-- 查看优化器评估了哪些执行计划、各自代价多少
SELECT TRACE FROM information_schema.OPTIMIZER_TRACE\G

SET optimizer_trace = 'enabled=off';
```

输出是超长 JSON，里面有 `considered_execution_plans`（候选计划及各计划代价）、`rejected_plans`（被拒的计划和原因）。**当你想知道「为什么优化器不走我建的那个索引」时，这是唯一能给出确切答案的工具。**

**常见被拒原因**：

- `"cause": "cost"` —— 代价比别的方案高（最常见）
- `"chosen": false, "cause": "no matching row in const table"` —— 等值查常量表
- `"cause": "not applicable"` —— 该索引不适用于当前查询结构

**`histogram`（8.0 直方图统计）：解决「某列倾斜严重，优化器估算不准」**

```sql
-- 对倾斜严重的列建直方图
ANALYZE TABLE t_order UPDATE HISTOGRAM ON status, user_id WITH 128 BUCKETS;

-- 查看
SELECT * FROM information_schema.COLUMN_STATISTICS
WHERE TABLE_NAME = 't_order';

-- 删除
ANALYZE TABLE t_order DROP HISTOGRAM ON status;
```

**典型场景**：`status` 列 99% 的行是 0，只有 1% 是 2。没有直方图时优化器可能以为分布均匀，走错索引。**建直方图后估算准确，能显著改善这类「倾斜列」的执行计划**——这是 8.0 相对 5.7 的一个实质进步。

**`EXPLAIN` 的三个格式对比**

| 格式 | 输出 | 适合场景 |
|---|---|---|
| `EXPLAIN` | 表格 | 日常快速看 |
| `EXPLAIN FORMAT=JSON` | JSON，含代价和 `used_key_parts` | 深入分析、对比代价 |
| `EXPLAIN FORMAT=TREE` | 树形（8.0.16+） | 看执行顺序 |
| `EXPLAIN ANALYZE` | 树形 + 真实耗时（8.0.18+） | 验证估算是否准确 |
| `EXPLAIN FOR CONNECTION <id>` | 看**正在执行**的连接的执行计划 | 观察线上慢 SQL 的实时计划 |
:::

:::追问
**Q：`rows` 是估算的，错得离谱怎么办？**
三个原因和处置：
① **统计信息过期** → `ANALYZE TABLE t_order;`（MySQL 8.0 的 `information_schema_stats_expiry` 默认 86400 秒，即缓存一天，可以设成 0 强制实时读）
② **列数据分布严重倾斜** → 建**直方图**（`ANALYZE TABLE ... UPDATE HISTOGRAM`）
③ **WHERE 条件之间强相关**（如 `city='成都' AND province='四川'`）→ 优化器按「独立事件」估算，必然偏 → 用 `EXPLAIN ANALYZE` 拿真实值，或改写 SQL 让优化器不用猜

```sql
-- 8.0 强制实时统计（默认缓存 24 小时）
SET SESSION information_schema_stats_expiry = 0;
SELECT * FROM information_schema.TABLES WHERE TABLE_NAME = 't_order';
```

**Q：`Using filesort` 一定慢吗？**
不一定。三种情况可以接受：
① **结果集很小**（`LIMIT 10` 配合 `ORDER BY`，优化器用优先队列只维护 10 个元素）；
② **数据量小**，在 `sort_buffer_size`（默认 256KB）内完成，不落盘；
③ **排序本身是业务必需的**（如按 `amount` 排序又没有对应索引），此时加索引的写代价大于收益。
**判断依据**：看慢日志的 `Sort_merge_passes`（>0 说明落盘了）和 `Tmp_disk_tables`。

**Q：`type=index` 和 `type=ALL` 都是「扫全部」，差别在哪？**
扫的对象不同。`type=index` 扫的是**二级索引的叶子页**，一个索引项可能只有几十字节；`type=ALL` 扫的是**聚簇索引的叶子页（数据页）**，一行可能几百字节到几 KB。所以同样的行数，`index` 扫描的页数可能只有 `ALL` 的 1/10。**而且扫索引往往配合 `Extra: Using index`（覆盖），完全不需要回表。** 但 `type=index` 仍然是「全扫」，只适合小表或索引很窄的场景。

**Q：为什么 `EXPLAIN` 显示的索引和实际跑的索引不一样？**
因为 `EXPLAIN` 是**估算**，运行时的实际计划可能因为数据变化、统计信息更新而变化。要确定线上真实执行的计划，用 `EXPLAIN FOR CONNECTION <连接id>`：

```sql
SHOW FULL PROCESSLIST;          -- 找到正在跑的慢 SQL 的 Id
EXPLAIN FOR CONNECTION 84213;   -- 看它此刻真实的执行计划
```
:::

:::锚点
`EXPLAIN` 就是你熟悉的 MongoDB `explain()` 的 MySQL 版本，**列名字不同，判断逻辑一致**：

| MongoDB | MySQL | 含义 |
|---|---|---|
| `planSummary: COLLSCAN` | `type: ALL` | 全表/全集合扫描（没走索引） |
| `planSummary: IXSCAN` | `type: range` / `ref` | 走索引 |
| `stage: FETCH` | 回表 | 拿索引项后再取完整文档/行 |
| `totalDocsExamined` | `rows` | 扫描了多少文档/行 |
| `nreturned` | 实际返回行数 | 返回了多少 |
| `totalKeysExamined` | — | MySQL 没有直接对应（看 `key_len`） |
| `executionStats.executionTimeMillis` | `EXPLAIN ANALYZE` 的 `actual time` | 真实耗时 |
| `rejectedPlans` | `optimizer_trace` 的 `rejected_plans` | 被优化器否掉的候选计划 |
| `indexBounds` | `key_len` + `ref` | 索引用到哪个区间 |

**面试话术**：

> 「执行计划分析我在 RRM 项目里做得比较多，只是工具是 MongoDB 的。我们的慢查询是通过 `explain('executionStats')` 定位的——看 `planSummary` 是 COLLSCAN 还是 IXSCAN，看 `totalDocsExamined` 和 `nreturned` 的比值。**当时 `clbDetail` 集合查一个调优任务的上报数据，`docsExamined` 是返回行数的几十万倍，说明扫描严重过量，建了 `{taskId, apSN, RI}` 复合索引 + 分片后降到毫秒级。**

> MySQL 这边，`EXPLAIN` 我是按同样的逻辑看的：**先看 `key` 是不是 NULL（有没有走索引），再看 `type`（走得好不好），再看 `rows` 和 `filtered`（扫了多少、白扫多少），最后看 `Extra` 有没有 filesort 和 temporary。** MySQL 比 Mongo 多出来的两个维度我特别关注：一是**回表**（`Extra` 里有没有 `Using index`），二是**索引下推**（`Using index condition`）——这两个是 Mongo 的 `explain()` 里没有的概念，也是我目前在补的部分。」

**加分点**：主动说出 `key_len` 能反推用了几列索引、`EXPLAIN FORMAT=JSON` 里有 `used_key_parts` 更直观。这两个细节一说出来，面试官就知道你真的读过执行计划，而不是背了 `type` 的排序表。
:::

---

## 9. 事务四大特性（ACID）及实现原理

:::概念
**A** 原子性 → **undo log**（回滚）
**C** 一致性 → 其他三个特性 + 业务约束**共同保证**（是目的，不是手段）
**I** 隔离性 → **MVCC + 锁**
**D** 持久性 → **redo log**（WAL）
一句话记：**「原子靠 undo、持久靠 redo、隔离靠 MVCC+锁、一致靠兜底」。**
:::

:::提问
- ACID 分别靠什么实现？
- 为什么需要 undo log 和 redo log 两份日志？
- 一致性是最难保证的吗？
- 事务的隔离性具体是怎么做到的？
- 事务的提交过程是怎样的？
:::

:::答案
### 一、四特性的机制映射（核心表）

| 特性 | 含义 | 实现机制 | 失效场景 |
|---|---|---|---|
| **原子性 Atomicity** | 事务内的操作要么全成功、要么全回滚 | **undo log**（记录反向操作，回滚时逆序执行） | 无（除非日志损坏） |
| **一致性 Consistency** | 事务前后数据库的约束与业务规则不被破坏 | **其他三个特性 + 主键/唯一/外键/CHECK 约束 + 业务代码** | 应用逻辑写错（如转账只扣款没入账） |
| **隔离性 Isolation** | 并发事务互相不干扰 | **MVCC（快照读）+ 锁（当前读）** | 隔离级别设得太低 |
| **持久性 Durability** | 提交后即使宕机也不丢 | **redo log（WAL）** + `innodb_flush_log_at_trx_commit` | 该参数设为 0/2 时可能丢 |

**「一致性是目的，另外三个是手段」**——这句话说出来能立刻区分「背过的」和「想过的」。**数据库本身不保证业务一致性**：如果代码里把「扣款」和「加钱」写在两个不同事务里，ACID 一个也救不了你，得靠分布式事务或业务补偿。

### 二、原子性：undo log 怎么做到回滚

**undo log 是逻辑日志，记录的是「如何撤销这次修改」**：

| 操作 | undo log 里记录的内容 | 回滚时做什么 |
|---|---|---|
| `INSERT` | 该行的主键（或 `DB_ROW_ID`） | `DELETE` 掉这一行 |
| `DELETE` | 该行的完整内容 | 重新 `INSERT` 回去 |
| `UPDATE` | 被修改列的**旧值**（实际上保存的是整行的旧版本） | 把列改回旧值 |

**关键点**：undo log 本身也是要写盘的（它记录在 undo 表空间里），而且**undo log 的写入也受 redo log 保护**（因为 undo 也是数据页）。这就是「redo 保护 undo」的嵌套关系。

```sql
-- undo 表空间
SHOW VARIABLES LIKE 'innodb_undo%';
-- innodb_undo_directory   默认 ./    undo 文件所在目录
-- innodb_undo_tablespaces 默认 2     undo 表空间个数（8.0 起只读，由系统自动管理）
-- innodb_max_undo_log_size 默认 1G   单个 undo 表空间上限（超过触发 truncate）
-- innodb_undo_log_truncate 默认 ON   自动收缩 undo 空间

-- 从 8.0 起，undo 表空间固定为 undo_001、undo_002（不再有回滚段数量参数）
SELECT NAME, FILE_SIZE FROM information_schema.INNODB_TABLESPACES
WHERE NAME LIKE 'innodb_undo%';
```

**长事务的代价**：undo log 不能清理 → undo 表空间膨胀 → MVCC 版本链变长（每次快照读都要沿链回溯很多版本）→ 整个数据库变慢。**这是「禁止长事务」最硬的技术理由。**

```sql
-- 找长事务（运行超过 60 秒的事务）
SELECT trx_id, trx_state, trx_started,
       TIMESTAMPDIFF(SECOND, trx_started, NOW()) AS duration_sec,
       trx_mysql_thread_id, trx_query
FROM information_schema.INNODB_TRX
WHERE TIMESTAMPDIFF(SECOND, trx_started, NOW()) > 60
ORDER BY trx_started;

-- MySQL 8.0：更长的事务历史（需要开启 innodb_monitor 相关配置）
SELECT * FROM performance_schema.events_transactions_history_long
ORDER BY TIMER_WAIT DESC LIMIT 10;

-- 相关参数
SHOW VARIABLES LIKE 'innodb_trx_wait_timeout';   -- 无此参数，用 innodb_lock_wait_timeout
SHOW VARIABLES LIKE 'innodb_rollback_on_timeout';-- 默认 OFF：超时回滚整条语句而不是整个事务
```

### 三、持久性：redo log 的 WAL 机制

**WAL（Write-Ahead Logging）：先写日志，再写数据页。**

```text
【不写日志，直接改数据页】
  UPDATE → 找到数据页（可能不在 buffer pool，要先从磁盘读 16KB）
         → 修改页内容
         → 把 16KB 的页写回磁盘   ← 随机 IO，慢！
  问题：一次改一个字段，却要写整个 16KB 页；而且多页修改时无法保证原子

【WAL：改内存 + 顺序写日志】
  UPDATE → 数据页在 buffer pool 里（不在就先读进来）
         → 修改内存中的页，标记为"脏页"   ← 内存操作，快
         → 把"某个页的某处改成了什么"顺序追加到 redo log
         → redo log 按策略刷盘（fsync）    ← 顺序 IO，快
  之后：后台线程慢慢把脏页刷到磁盘（checkpoint）
  崩溃恢复：拿 redo log 重放，把没刷盘的修改补上
```

**为什么 redo log 快**：① **顺序追加**（不像数据页是随机写）；② **日志条目小**（记的是「页号 + 偏移 + 新值」，不是整页）。

```sql
-- redo log 相关参数
SHOW VARIABLES LIKE 'innodb_log_file_size';        -- 5.7/8.0.30 前：每个 redo 文件大小，默认 48M
SHOW VARIABLES LIKE 'innodb_log_files_in_group';   -- 默认 2（所以默认总容量 96M）
SHOW VARIABLES LIKE 'innodb_redo_log_capacity';    -- 8.0.30+ 新参数，默认 100M，替代上面两个
SHOW VARIABLES LIKE 'innodb_flush_log_at_trx_commit'; -- ★ 默认 1

-- 8.0.30+ 查看 redo 文件
SELECT * FROM performance_schema.innodb_redo_log_files;
```

**`innodb_flush_log_at_trx_commit` 三种取值（必考）**：

| 值 | 行为 | 崩溃丢数据 | 性能 | 适用 |
|---|---|---|---|---|
| **1（默认）** | 每次 `COMMIT` 都 `fsync` 到磁盘 | 不丢 | 最差 | **金融/订单等不能丢数据的场景** |
| `2` | 每次 `COMMIT` 写 OS 缓存，**每秒** `fsync` | **OS 崩溃丢 1 秒**；MySQL 进程崩溃不丢 | 中 | 大多数业务 |
| `0` | 每秒写 OS 缓存并 `fsync`（提交时不写） | **丢最多 1 秒** | 最好 | 日志类、可丢数据 |

```sql
-- 生产建议：区分重要性设置
SET GLOBAL innodb_flush_log_at_trx_commit = 1;   -- 核心库
```

**`innodb_flush_log_at_trx_commit=1` + `sync_binlog=1` 称为「双 1 配置」**，是金融级不丢数据的标准配置（代价是每个事务至少两次 fsync）。

```sql
SHOW VARIABLES LIKE 'sync_binlog';   -- 默认 1（8.0 起默认就是 1，5.7 默认 0）
```

### 四、隔离性：MVCC + 锁

- **快照读**（普通 `SELECT`）：靠 **MVCC** 读历史版本，不加锁 → 读写不互斥，这是 InnoDB 并发高的核心原因。
- **当前读**（`SELECT ... FOR UPDATE` / `UPDATE` / `DELETE` / `INSERT`）：读最新版本并加锁 → 靠**记录锁 / 间隙锁 / 临键锁**保证。

详见第 10、11、12 题。

### 五、一次 `UPDATE` 的完整生命周期

```text
① 事务开始，分配 trx_id（InnoDB 内部，全局递增）
② 找到目标行：
   - 需要在 buffer pool 里先定位到页（不在就从磁盘读 16KB）
   - 加行锁（排他锁）
③ 生成 undo log：把该行的旧版本写进 undo 表空间
   - 旧版本里的 DB_TRX_ID = 上一个修改它的事务 id
   - DB_ROLL_PTR 指向更早的版本（形成版本链）
④ 修改 buffer pool 中的页，标记为脏页
   - 该行的 DB_TRX_ID 更新为当前事务 id
   - DB_ROLL_PTR 指向第 ③ 步写的 undo 记录
⑤ 写入 redo log（记为 prepare 状态）
⑥ 写入 binlog
⑦ 提交：redo log 标记为 commit（两阶段提交完成）
⑧ 返回客户端成功
⑨ 后台：checkpoint 线程把脏页刷回磁盘；purge 线程清理不再需要的 undo
```

### 六、事务的基本操作

```sql
-- 显式事务
START TRANSACTION;         -- 或 BEGIN
UPDATE accounts SET balance = balance - 100 WHERE id = 1;
UPDATE accounts SET balance = balance + 100 WHERE id = 2;
COMMIT;                    -- 或 ROLLBACK

-- 保存点（部分回滚）
START TRANSACTION;
UPDATE a SET x = 1;
SAVEPOINT sp1;
UPDATE b SET y = 2;
ROLLBACK TO SAVEPOINT sp1;   -- 只回滚 b 的修改
COMMIT;                       -- a 的修改仍会提交

-- 自动提交开关
SHOW VARIABLES LIKE 'autocommit';   -- 默认 ON
SET autocommit = 0;                 -- 关闭后，每条语句都在一个隐式事务里（记得手动 COMMIT！）

-- 查看当前事务
SELECT * FROM information_schema.INNODB_TRX\G
```

**⚠️ DDL 会隐式提交**：`ALTER TABLE`、`CREATE TABLE`、`DROP TABLE`、`TRUNCATE` 在 MySQL 里都会**隐式提交当前事务**。所以「事务里做 DDL」在 MySQL 里是不可能的（PostgreSQL 可以，见第 20 题）——这是两个数据库的一个本质差异。
:::

:::拓展
**崩溃恢复的三阶段**

| 阶段 | 做什么 | 依据 |
|---|---|---|
| **分析（Analysis）** | 找出崩溃时的活跃事务、最后一个 checkpoint 位置 | redo log |
| **重做（Redo）** | 从 checkpoint 开始前滚，把已提交的事务重放 | redo log（**无论事务是否提交都要重放**） |
| **回滚（Undo）** | 把未提交的事务回滚掉 | undo log |

**关键细节：redo 阶段会把「未提交事务的修改」也一起重放**（因为 redo 是物理层日志，它不知道事务语义）。然后再由 undo 阶段把这些修改撤销。**这就是「先前滚再回滚」的含义。**

**`innodb_force_recovery`：数据损坏时的应急开关**

```sql
-- my.cnf 里配置，取值 1~6
[mysqld]
innodb_force_recovery = 1    # 1=忽略损坏页；6=完全跳过 redo
```

**⚠️ 危险操作**：`≥4` 会导致数据页变成只读（无法写入），只能用于 `mysqldump` 抢救数据。**用完之后必须立即改回 0 并重启**，否则数据会持续损坏。

**XA 事务与分布式事务**

跨库场景下 MySQL 支持 XA：

```sql
XA START 'xid1';
UPDATE db1.t SET ...;
XA END 'xid1';
XA PREPARE 'xid1';
-- 另一个库也走同样的流程
XA COMMIT 'xid1';
```

**但生产上很少直接用 XA**：① 性能差（有 `innodb_lock_wait_timeout` 之外的额外超时）；② 协调者挂了会留下悬挂事务。**实际项目里用的是 Seata / TCC / 本地消息表**这类方案。
:::

:::追问
**Q：为什么不能只保留 redo log，不要 undo log？**
分工不同：**redo 保证「已提交的不丢」，undo 保证「未提交的不留」**。redo 是物理层日志，它记录的是「页的修改」，崩溃恢复时会把所有修改（含未提交的）都重放；如果没有 undo，未提交事务的修改就永久留在数据里了。**而且 undo 还承担 MVCC 版本链的存储职责**——这是它独立存在的第二个理由（见第 11 题）。

**Q：`innodb_flush_log_at_trx_commit=1` 就一定不丢数据吗？**
不绝对。三种仍可能丢的情况：① **磁盘本身缓存没落盘**（企业级 SSD 有掉电保护通常没事，普通盘可能丢）；② **`sync_binlog != 1` 时主从复制丢事件**；③ **从库还没同步**（异步复制下主库挂了，已提交但未同步到从库的数据在主从切换后丢失）。所以「不丢」是分层的：单机不丢（双 1）≠ 集群不丢（要半同步 + 多数派）。

**Q：为什么说「一致性」是最重要的？**
因为它是 ACID 的**目的**，AID 是**手段**。业务上的「一致性」包括：账户余额不能为负、订单状态机不能跳变、库存不能超卖——**这些没有一个是数据库能自动保证的**。数据库只保证「你写的这些 SQL 要么全生效要么全不生效」，但**「你写的是不是正确的 SQL」得你自己负责**。

**Q：事务提交了但客户端没收到响应，怎么办？**
这是分布式系统的经典问题（「提交确认丢失」）。处置：① 客户端用**幂等**设计（唯一键 + `INSERT ... ON DUPLICATE KEY UPDATE`，或者给业务加幂等号）；② 重试时先查状态确认是否已提交；③ 不要在超时后盲目重试写操作。**这是面试官问「幂等怎么做」常常会延伸到的方向。**
:::

:::锚点
**这道题有一个很实在的落点：MongoDB 从 4.0 起支持多文档事务，但你们 RRM 的主存储大概率没用它。**

MongoDB 的事务能力对比：

| | MongoDB | MySQL InnoDB |
|---|---|---|
| 单文档原子性 | ✅ 天然保证（文档内所有字段） | ✅ 行级 |
| 多文档事务 | 4.0+ 副本集支持；4.2+ 分片集群支持 | ✅ 一直支持 |
| 隔离级别 | `readConcern` / `writeConcern` 组合，语义不同 | 标准四级 |
| 分片集群事务 | 4.2+ 支持，但**性能代价显著** | — |

**面试话术**：

> 「RRM 项目的主力存储是 MongoDB，我们是**靠『单文档原子性 + 业务幂等』来保证一致性的，没有依赖多文档事务**——因为跨分片事务在 Mongo 里性能代价很高，我们的调优任务是按 `taskId` 维度天然隔离的，正好落在同一个分片键上，大部分场景单文档更新就够了。

> MySQL 这边，ACID 的实现链路我是清楚的：**原子性靠 undo log 记录反向操作，持久性靠 redo log 的 WAL 先写日志再刷数据页，隔离性靠 MVCC 管快照读、锁管当前读，一致性是前三者加业务约束共同兜的结果。** 我特别注意到 MySQL 有个和 Mongo 完全不同的约束：**DDL 会隐式提交事务**，所以在 MySQL 里「事务里做 DDL」是不可能的，这一点 PostgreSQL 反而允许——这也是我在做 MySQL/PgSQL 兼容适配时踩到的一个差异点。」

**坦白策略**：不强求把「ACID 实现」讲成项目经历。**这道题本来就是原理题，讲清机制 + 说出「Mongo 里我是怎么做的 / MySQL 里机制是什么」的对比，比硬编一个 MySQL 事务故事安全得多。**
:::

## 10. 事务隔离级别与幻读

:::概念
四级：**读未提交（RU）→ 读已提交（RC）→ 可重复读（RR）→ 串行化（Serializable）**，级别越高隔离越好、并发越差。
**MySQL 默认 `REPEATABLE READ`**（Oracle / PostgreSQL / SQL Server 默认都是 RC，这是个必考的差异点）。
三大并发问题：**脏读、不可重复读、幻读**——注意 MySQL 的 RR 靠 **MVCC + 临键锁**，比标准 RR 更强（标准 RR 不防幻读）。
:::

:::提问
- MySQL 有哪几种隔离级别？默认是哪个？
- 脏读、不可重复读、幻读分别是什么？被哪个级别解决？
- 为什么 Oracle 默认 RC，MySQL 默认 RR？
- RR 级别下还会有幻读吗？
- 怎么查看和修改隔离级别？
- RC 和 RR 在实现上差在哪（ReadView 生成时机）？
:::

:::答案
### 一、各级别的定义与对比

| 隔离级别 | 脏读 | 不可重复读 | 幻读 | 实现方式 |
|---|---|---|---|---|
| **读未提交 RU** | ❌ 会 | ❌ 会 | ❌ 会 | 直接读最新数据，不加任何控制 |
| **读已提交 RC** | ✅ 不会 | ❌ 会 | ❌ 会 | **每次 `SELECT` 都生成新 ReadView** |
| **可重复读 RR** | ✅ 不会 | ✅ 不会 | ✅ **基本不会** | **只在第一次 `SELECT` 生成 ReadView，整个事务复用** + 临键锁 |
| **串行化 Serializable** | ✅ 不会 | ✅ 不会 | ✅ 不会 | 所有 `SELECT` 加共享锁，读写互斥 |

### 二、三个并发问题到底是什么

**用同一个场景串起来讲（面试这样讲最清楚）**：

```sql
-- 初始：SELECT balance FROM accounts WHERE id = 1;  → 100
```

| 问题 | 时序 | 现象 |
|---|---|---|
| **脏读** | T1 把余额改成 200（**未提交**）→ T2 读到 200 → T1 回滚 | T2 读到了一个**从未真正存在过**的值 |
| **不可重复读** | T1 读余额 = 100 → T2 改成 200 并提交 → T1 **再读一次**得到 200 | 同一事务内**两次读同一条记录，值不一样**（针对 `UPDATE`） |
| **幻读** | T1 查 `WHERE status=2` 得到 5 行 → T2 插入 1 行 status=2 并提交 → T1 **再查得到 6 行** | 同一事务内**两次查，行数变了**（针对 `INSERT`/`DELETE`） |

**「不可重复读」和「幻读」的关键区别**：
- 不可重复读 → 针对**已有行被修改**（值的差异），锁定已有行就能解决
- 幻读 → 针对**行数变化**（新增/删除），必须锁住「区间」才能解决 → 所以要**间隙锁**

### 三、查看和修改隔离级别

```sql
-- 查看（8.0 起 transaction_isolation 是新名字，tx_isolation 是 5.7 及以前的旧名）
SELECT @@transaction_isolation;                          -- 8.0
SELECT @@tx_isolation;                                   -- 5.7
SHOW VARIABLES LIKE 'transaction_isolation';

-- 会话级修改（只影响当前连接，测试时用）
SET SESSION TRANSACTION ISOLATION LEVEL READ COMMITTED;
SET SESSION transaction_isolation = 'READ-COMMITTED';    -- 等价写法

-- 全局修改（影响新连接，重启失效；要永久生效必须写 my.cnf）
SET GLOBAL TRANSACTION ISOLATION LEVEL READ COMMITTED;

-- my.cnf 永久配置
-- [mysqld]
-- transaction-isolation = READ-COMMITTED
```

### 四、RC 和 RR 的实现差异：ReadView 的生成时机

这是**这道题最有区分度的一问**。

| | RC | RR |
|---|---|---|
| ReadView 生成时机 | **每次 `SELECT` 都重新生成** | **只在事务内第一次 `SELECT` 时生成，之后复用** |
| 效果 | 每次读都能看到「此刻最新已提交」的数据 | 整个事务看到的都是「第一次读那一刻的快照」 |
| 不可重复读 | ❌ 会发生 | ✅ 不会发生 |
| undo log 保留 | 可较早清理 | **必须保留到事务结束**（长事务会撑大 undo） |

```sql
-- 演示：在 RR 下同一事务两次读结果一致
SET SESSION TRANSACTION ISOLATION LEVEL REPEATABLE READ;
START TRANSACTION;
SELECT balance FROM accounts WHERE id = 1;    -- 100
-- （另一个连接 UPDATE 成 200 并 COMMIT）
SELECT balance FROM accounts WHERE id = 1;    -- 仍是 100！（快照读）
COMMIT;
SELECT balance FROM accounts WHERE id = 1;    -- 200

-- 在 RC 下重做一次，第二次会读到 200
```

### 五、为什么 MySQL 默认 RR，Oracle 默认 RC

| 角度 | MySQL RR | Oracle RC |
|---|---|---|
| 历史原因 | MySQL 早期 binlog 只有 `STATEMENT` 格式，**RC + STATEMENT 会导致主从不一致**（同一语句在主从上执行结果不同），所以默认 RR 并用间隙锁保证顺序 | Oracle 用 SCN（系统变更号）实现一致性读，RC 是更自然的默认 |
| 二进制日志 | **`binlog_format=STATEMENT` 时必须用 RR**（否则 `UPDATE ... WHERE` 在主从会改到不同的行） | — |
| 间隙锁 | RR 加间隙锁 → 并发插入受影响；但能防幻读 | RC 不加间隙锁 → 并发插入好；但有幻读 |
| 现代实践 | **`binlog_format=ROW`（5.7+ 默认）后，很多互联网公司主动改成 RC** | 一直 RC |

**互联网公司改 RC 的三个理由**（面试常问）：
1. **减少间隙锁**：RR 的间隙锁在高并发插入场景下容易死锁；RC 下 `SELECT ... FOR UPDATE` 只加记录锁（除唯一性检查外）
2. **提升并发**：RC 下 undo log 可以更早被 purge，版本链更短，快照读更快
3. **与 Oracle 行为一致**：方便迁移

```sql
-- 确认 binlog 格式（ROW 是 5.7+ 默认）
SHOW VARIABLES LIKE 'binlog_format';   -- ROW
```

### 六、RR 下还有幻读吗

**分快照读和当前读两种情况**：

| 场景 | RR 下是否幻读 | 原因 |
|---|---|---|
| **快照读**（普通 `SELECT`） | ✅ 不会 | 整个事务复用同一个 ReadView，新插入的行对看不到 |
| **当前读**（`FOR UPDATE` / `UPDATE` / `DELETE`） | ✅ 基本不会 | 加**临键锁（Next-Key Lock）**，锁住区间，其他事务插不进来 |
| **先快照读，再当前读** | ⚠️ **会** | 见下方「经典的半幻读场景」 |
| **先快照读，再当前读，再快照读** | ⚠️ 第二次快照读**看不到**新行 | ReadView 没变，所以看到的还是老快照 |

**经典的「半幻读」场景（面试官爱考）**：

```sql
-- 表 t 中 id 有 1, 2, 3
-- 事务 T1（RR）
START TRANSACTION;
SELECT * FROM t WHERE id > 2;         -- 快照读，看到 id=3（1 行）

-- 事务 T2 插入 id=5 并提交
COMMIT;

-- T1 继续
UPDATE t SET name = 'x' WHERE id > 2; -- 当前读！此时看到了 id=3 和 id=5，都改了
SELECT * FROM t WHERE id > 2;         -- 快照读，看到 id=3 和 id=5（2 行）← 幻读！
COMMIT;
```

**原因**：`UPDATE` 是当前读，它读到了 T2 新插入的 id=5，并把该行的 `DB_TRX_ID` 改成了 T1 的事务 id。**由于这一行现在是自己改的，后面的快照读就可见了** —— 于是行数从 1 变成了 2。

**这段讲出来，面试官基本会认为你真的理解 MVCC。** 标准答案是「RR 下快照读不会幻读，但当前读之后会出现「读到自己改动的行」的情况」。

### 七、隔离级别的实际选型

| 场景 | 建议 |
|---|---|
| 默认的 OLTP 业务 | **RR**（MySQL 默认，兼容性最好） |
| 高并发写入、有大量范围条件和 `FOR UPDATE` | **RC**（减少间隙锁和死锁） |
| 报表类 / 需要读最新数据 | RC |
| 金融强一致、有跨行约束 | RR 或 Serializable（但性能代价大，一般用 RR + 应用层乐观锁） |
| 主从复制 | **必须与主库一致**（不一致会导致从库重放结果偏离） |

```sql
-- 检查主从隔离级别是否一致（不一致会导致复制数据不一致）
-- 在主库和从库分别执行
SELECT @@transaction_isolation;
```
:::

:::拓展
**`innodb_lock_wait_timeout` 与隔离级别的关系**

```sql
SHOW VARIABLES LIKE 'innodb_lock_wait_timeout';   -- 默认 50 秒
```

RR 下因为间隙锁更多，等锁超时的概率比 RC 更高。**50 秒的默认值偏长**，互联网业务通常调到 **5~10 秒**，让快失败代替长时间挂住连接：

```sql
SET GLOBAL innodb_lock_wait_timeout = 10;
-- my.cnf: innodb-lock-wait-timeout = 10
```

**`innodb_rollback_on_timeout`**

```sql
SHOW VARIABLES LIKE 'innodb_rollback_on_timeout';   -- 默认 OFF
```

默认 OFF 时，**锁等待超时只回滚当前这一条语句，不回滚整个事务**——这意味着你的事务可能处于「改了一半」的状态，后续代码如果直接 `COMMIT`，会提交一个不完整的事务。**这是一个隐蔽的数据一致性风险。**

**处置**：要么设成 ON（超时回滚整个事务），要么在应用层捕获 `Lock wait timeout exceeded` 异常后**显式 `ROLLBACK`**。

**PostgreSQL 的隔离级别语义（对比，第 20 题会再提）**

| | MySQL RR | PostgreSQL RR |
|---|---|---|
| 幻读 | 靠间隙锁防（快照读靠 MVCC） | 靠 MVCC 快照防（不加间隙锁） |
| 更新冲突 | 后写者阻塞等待 | **`ERROR: could not serialize access due to concurrent update`** 直接报错回滚 |
| 实际强度 | 介于标准 RR 与 Serializable 之间 | 接近 Serializable 的「快照隔离」 |

**PostgreSQL 的 RR 不加间隙锁，而是「如果发现要更新的行在快照后被别人改过，直接报错让你重试」。** 这个差异在跨库适配时非常重要（见第 20 题）。
:::

:::追问
**Q：RC 下会出现幻读吗？**
会。RC 每次 `SELECT` 都生成新 ReadView，能看到新提交的插入（幻读）；且 RC 下 `SELECT ... FOR UPDATE` **不加间隙锁**（只加记录锁），所以其他事务可以自由插入。

**Q：RR 下间隙锁是不是一定加？**
不是。有几种情况不加或不生效：
① **唯一索引等值查询且命中记录** → 退化为**记录锁**（唯一性已保证不会插入同值）；
② **唯一索引等值查询但未命中** → 加**间隙锁**（还要防插入）；
③ **非唯一索引等值查询** → **临键锁**，且向后扫描到第一个不满足条件的记录为止；
④ **普通 SELECT（快照读）** → 完全不加锁；
⑤ 隔离级别是 RC → 不加间隙锁。

**Q：串行化级别下，普通 `SELECT` 会加什么锁？**
在 MySQL 里，Serializable 会把普通 `SELECT` **隐式转换成 `SELECT ... LOCK IN SHARE MODE`**（加共享锁）。所以读写、写写都互斥，并发极差，实际生产几乎不用。

**Q：为什么说 MySQL 的 RR 比标准 SQL 的 RR 更强？**
标准 SQL 定义的 RR **只保证不可重复读不出现，不保证不幻读**。MySQL 的 RR 通过**临键锁**额外把幻读也防住了（当前读场景），所以常被描述为「MySQL RR ≈ 标准 SQL 的 Serializable 的一部分」。**这也是为什么 MySQL 敢把 RR 设成默认级别。**
:::

:::锚点
**这道题你在 MongoDB 上有一个直接的对照点：MongoDB 的 `readConcern` 和 MySQL 的隔离级别是同一类概念的两种表达。**

```javascript
// MongoDB 的读关注级别（readConcern）
db.clbDetail.find({ taskId: "T001" }).readConcern("local")      // ≈ 读已提交/脏读边缘
db.clbDetail.find({ taskId: "T001" }).readConcern("majority")   // ≈ 读已提交（多数派已确认）
db.clbDetail.find({ taskId: "T001" }).readConcern("snapshot")   // ≈ 可重复读（快照）
db.clbDetail.find({ taskId: "T001" }).readConcern("linearizable") // ≈ 串行化
```

**面试话术**：

> 「MySQL 的隔离级别是四级，默认 RR；MongoDB 这边没有一个叫『隔离级别』的概念，但 `readConcern` 的 `local / majority / snapshot / linearizable` 本质上是同一类东西——**区别是 Mongo 把『读到什么版本』和『写要确认到几个节点』拆成了 `readConcern` + `writeConcern` 两个正交的维度，而 MySQL 的隔离级别只描述读的可见性。**

> RR 和 RC 的实现差异我印象最深的是 **ReadView 的生成时机**：RC 是每次 `SELECT` 都生成一个新的，RR 只在第一次生成然后整个事务复用——这就是『不可重复读在 RR 下不出现』的全部原因。另外我还知道一个容易被忽略的点：**RR 下的『半幻读』场景——先快照读、再当前读（UPDATE），当前读会读到别人新插入的行并且把它的 trx_id 改成自己的，之后的快照读就能看到它了。**」

**加分策略**：最后这句「半幻读」的细节，是能把「背过隔离级别表」和「真的理解 MVCC」区分开的题眼。**但不要编造在任何数据库上遇到过这个 bug**——就说是从原理推导的。
:::

---

## 11. MVCC 原理 ★（undo log 版本链 + ReadView 可见性算法）

:::概念
MVCC = **「每行保留多个历史版本，读的时候按规则挑一个可见的版本」**，从而实现「读不加锁」。
两个组件：
**① undo log 版本链**——每行有两个隐藏列 `DB_TRX_ID`（最后改它的事务 id）和 `DB_ROLL_PTR`（指向 undo 里的上一个版本），一串起来就是版本链。
**② ReadView**——读视图，包含四个字段 `m_ids / min_trx_id / max_trx_id / creator_trx_id`，用一套**四步判断**决定某个版本是否可见。
:::

:::提问
- MVCC 是怎么实现的？
- 什么是 ReadView？里面有什么？
- 版本链怎么形成的？undo log 起了什么作用？
- 可见性是怎么判断的？能不能一步步说？
- RC 和 RR 的 ReadView 生成时机有什么不同？
- MVCC 能解决幻读吗？
:::

:::答案
### 一、隐藏字段：MVCC 的物理基础

InnoDB 每一行都有三个隐藏列（用户不可见）：

| 隐藏列 | 长度 | 含义 |
|---|---|---|
| **`DB_TRX_ID`** | 6 字节 | **最后一次修改（插入或更新）这一行的事务 id** |
| **`DB_ROLL_PTR`** | 7 字节 | **回滚指针**，指向 undo log 中该行的**上一个版本** |
| `DB_ROW_ID` | 6 字节 | 没有主键且没有非空唯一索引时，用作聚簇索引键（见第 3 题） |

```sql
-- 8.0 可以用这个方式"看到"隐藏列（了解即可，别在生产用）
-- 8.0.30+ 支持通过 information_schema 查看部分信息
SELECT * FROM information_schema.INNODB_TABLES WHERE NAME LIKE '%t_order%';
```

### 二、版本链：一次 UPDATE 怎么产生新版本

假设初始：`id=1, name='A'`，由事务 100 插入。

```text
【初始状态】（当前行）
  id=1, name='A', DB_TRX_ID=100, DB_ROLL_PTR=null

【事务 200 执行 UPDATE t SET name='B' WHERE id=1】
  ① 把当前行（旧版本）复制到 undo log 里：
     undo 记录 u1: { id=1, name='A', DB_TRX_ID=100, DB_ROLL_PTR=null }
  ② 修改当前行：
     id=1, name='B', DB_TRX_ID=200, DB_ROLL_PTR → u1

【事务 300 执行 UPDATE t SET name='C' WHERE id=1】
  ① 把当前行（name='B'）复制到 undo log：
     undo 记录 u2: { id=1, name='B', DB_TRX_ID=200, DB_ROLL_PTR → u1 }
  ② 修改当前行：
     id=1, name='C', DB_TRX_ID=300, DB_ROLL_PTR → u2
```

**版本链形态**：

```text
当前行 [name=C, trx=300] ──roll_ptr──> u2 [name=B, trx=200] ──> u1 [name=A, trx=100] ──> null
          ▲ 最新                                                          ▲ 最早
```

**关键点**：
- **每次更新都往链头加一个版本**（当前行永远是最新的）
- 链是**单向的，只能从新往旧回溯**
- **回滚用同一份 undo**：`ROLLBACK` 就是把链头换回旧版本
- **purge 线程**会清理「没有任何 ReadView 还需要」的旧版本 → 长事务会让 purge 无法清理 → undo 膨胀

### 三、ReadView 的四个字段（必须背）

**ReadView 是在「读的那一刻」对「当前活跃事务」拍的一张快照。**

| 字段 | 含义 |
|---|---|
| **`m_ids`** | 生成 ReadView 时，**当前所有「已启动但未提交」的事务 id 列表** |
| **`min_trx_id`** | `m_ids` 中的**最小值**（没有活跃事务时为下一个待分配的事务 id） |
| **`max_trx_id`** | 生成 ReadView 时，**系统下一个将要分配的事务 id**（注意：不是 `m_ids` 的最大值，而是「下一个」） |
| **`creator_trx_id`** | **创建这个 ReadView 的事务自己的 id** |

**图示**（假设当前事务是 300，活跃事务是 200 和 250，下一个待分配是 400）：

```text
  trx_id 编号轴：
  ... 100 ──────── 200 ──────── 250 ──────── 300(自己) ──────── 400(下一个待分配)
      已提交      ↑活跃        ↑活跃                    ↑max_trx_id
                                      ↑creator_trx_id
                 └──── m_ids = [200, 250] ────┘
        └── min_trx_id = 200
```

- `m_ids = [200, 250]`
- `min_trx_id = 200`
- `max_trx_id = 400`
- `creator_trx_id = 300`

### 四、可见性判断算法（四步，逐步写清）

**给定一个版本记录的 `trx_id`，判断它是否对本事务可见：**

```text
步骤 1：trx_id == creator_trx_id ？
   → 是：这个版本是「自己改的」，可见 ✅
   （自己当然要看得见自己的修改）

步骤 2：trx_id < min_trx_id ？
   → 是：这个版本由一个「在 ReadView 生成前就已经提交」的事务写的，可见 ✅

步骤 3：trx_id >= max_trx_id ？
   → 是：这个版本由一个「在 ReadView 生成之后才启动」的事务写的，
        对本事务来说是"未来的事"，不可见 ❌

步骤 4：min_trx_id <= trx_id < max_trx_id
   说明这个事务在 ReadView 生成时"可能活跃、也可能已提交"，要查 m_ids：
   4a. trx_id 在 m_ids 中 → 该事务当时还活跃（未提交）→ 不可见 ❌
   4b. trx_id 不在 m_ids 中 → 该事务当时已提交 → 可见 ✅

如果判定为「不可见」：
   → 顺着 DB_ROLL_PTR 找到上一个版本，重复步骤 1~4
   → 直到找到一个可见的版本，或者链走到头（都没有 → 该行对本事务不存在）
```

**可视化记忆法**：

| trx_id 落在哪个区间 | 结论 | 原因 |
|---|---|---|
| `= creator_trx_id` | **可见** | 自己的修改 |
| `< min_trx_id` | **可见** | 早就提交了 |
| `>= max_trx_id` | **不可见** | 我拍快照之后才开始的 |
| 在 `[min, max)` 且**在 m_ids 里** | **不可见** | 拍快照时还没提交 |
| 在 `[min, max)` 且**不在 m_ids 里** | **可见** | 拍快照时已经提交了 |

### 五、走一遍完整例子

```text
场景：ReadView 生成时，活跃事务 = [200, 250]，下一个待分配 = 400，自己是 300
     即 min_trx_id = 200, max_trx_id = 400, creator_trx_id = 300, m_ids = [200, 250]

版本链：当前行[trx=250] → u1[trx=200] → u2[trx=150] → u3[trx=100]
```

| 版本 | trx_id | 判断过程 | 结论 |
|---|---|---|---|
| 当前行 | 250 | 步骤 4：250 在 [200,400) 且 **在 m_ids 里** | ❌ 不可见（250 当时未提交） |
| u1 | 200 | 步骤 4：200 在 [200,400) 且 **在 m_ids 里** | ❌ 不可见（200 当时未提交） |
| u2 | 150 | 步骤 2：150 < 200（min_trx_id） | ✅ **可见** → 返回这个版本 |
| u3 | 100 | 不再看 | — |

**最终读到 `u2` 的版本（trx=150 的那个）。**

### 六、RC 与 RR 的差异（就是 ReadView 生成时机）

| | RC（读已提交） | RR（可重复读） |
|---|---|---|
| 生成时机 | **每次 `SELECT` 都重新生成一个 ReadView** | **只在事务内第一次 `SELECT` 时生成一次，后续复用** |
| 效果 | 每次读都能看到「截至此刻最新提交」的数据 | 整个事务读到的都是「第一次读那一刻」的快照 |
| 不可重复读 | 会发生 | 不会发生 |
| 典型表现 | 同一事务两次 `SELECT` 结果可能不同 | 同一事务两次 `SELECT` 结果必然相同（快照读） |

```sql
-- 自己动手验证（开两个会话）
-- 会话 A
SET SESSION TRANSACTION ISOLATION LEVEL REPEATABLE READ;
START TRANSACTION;
SELECT balance FROM accounts WHERE id = 1;   -- 读第一次：100

-- 会话 B
UPDATE accounts SET balance = 200 WHERE id = 1;
COMMIT;

-- 回到会话 A
SELECT balance FROM accounts WHERE id = 1;   -- 读第二次：仍是 100（RR 复用 ReadView）
COMMIT;
SELECT balance FROM accounts WHERE id = 1;   -- 事务结束后：200

-- 把会话 A 的隔离级别改成 READ COMMITTED 再走一遍，第二次会读到 200
```

### 七、MVCC 能解决什么、不能解决什么

| 问题 | MVCC 能否解决 |
|---|---|
| 脏读 | ✅ 能（版本链上的未提交版本不可见） |
| 不可重复读（快照读） | ✅ 能（RR 复用 ReadView） |
| 幻读（快照读） | ✅ 能（新插入的行 trx_id ≥ max_trx_id，不可见） |
| 幻读（当前读） | ❌ **不能**，靠**临键锁**解决 |
| 更新丢失 | ❌ 不能，靠**当前读 + 锁**或**乐观锁（版本号）**解决 |

**一句话总结**：**MVCC 只管「快照读」，一切「当前读」和写冲突都归锁管。** 这就是第 9 题说的「隔离性 = MVCC + 锁」的由来。

### 八、快照读的「读时机」——ReadView 不是事务开始时创建的

**一个常被搞错的关键点**：RR 下 ReadView 是在**事务内第一次执行快照读（`SELECT`）时**创建的，**不是 `START TRANSACTION` 时**。

```sql
START TRANSACTION;                       -- 此刻还没创建 ReadView
-- （另一个事务插入了一行并提交）
SELECT * FROM t WHERE id > 2;            -- ★ 这一刻才创建 ReadView，能看到上面插入的那行
SELECT * FROM t WHERE id > 2;            -- 复用同一个 ReadView，结果一致
```

**推论**：如果一个 RR 事务里第一条语句是 `UPDATE`（当前读），之后再 `SELECT`，那么 `SELECT` 的 ReadView 是在 `UPDATE` 之后创建的——**这会改变它能看到哪些数据**。在排查「为什么读到了不该读到的数据」时，这是关键线索。

### 九、undo 与 purge：版本链的清理

```sql
-- 看 undo 表空间占用
SELECT NAME, FILE_SIZE, SPACE_TYPE FROM information_schema.INNODB_TABLESPACES
WHERE NAME LIKE 'innodb_undo%';

-- 看版本历史长度和 purge 进度
SHOW ENGINE INNODB STATUS\G
-- History list length: 12345      ← 版本链长度，越大说明 undo 堆积越多
-- （在 TRANSACTIONS 段落里）

-- 相关参数
SHOW VARIABLES LIKE 'innodb_max_undo_log_size';   -- 默认 1G（1073741824）
SHOW VARIABLES LIKE 'innodb_undo_log_truncate';   -- 默认 ON
SHOW VARIABLES LIKE 'innodb_purge_threads';       -- 默认 4
-- MySQL 8.0.23+ 新增
SHOW VARIABLES LIKE 'innodb_purge_batch_size';
```

**`History list length` 是判断「有没有长事务拖累 undo」的黄金指标**：正常值应该在几百到几千，**如果它持续上万甚至几十万，说明有长事务在阻止 purge**。

```sql
-- 找元凶：最老的事务
SELECT trx_id, trx_state, trx_started,
       TIMESTAMPDIFF(SECOND, trx_started, NOW()) AS sec,
       trx_mysql_thread_id, trx_query
FROM information_schema.INNODB_TRX
ORDER BY trx_started ASC LIMIT 5;
```

**典型的长事务制造者**：
- 应用侧：事务里调外部 HTTP 接口、发消息、等用户输入
- `autocommit = 0` 之后忘记 `COMMIT` 的连接
- 空闲连接（`Sleep` 状态）但事务没结束
- 备份工具在从库上开的一致性快照

```sql
-- 顺带清理：杀掉长时间 Sleep 且开着事务的连接（⚠️ 先确认业务影响）
SELECT id, user, host, db, command, time, state
FROM information_schema.processlist
WHERE command = 'Sleep' AND time > 600;
```
:::

:::拓展
**当前读读到的到底是什么版本**

当前读（`SELECT ... FOR UPDATE` / `UPDATE` / `DELETE`）**不走 MVCC 的可见性判断**，它读的是：

1. 先用「最新版本」定位到记录（可能通过唯一索引快速定位）
2. **如果最新版本的事务已提交 → 直接读**
3. **如果最新版本的事务未提交 → 等待它提交或回滚**（加锁等待，受 `innodb_lock_wait_timeout` 控制）
4. 读完之后**对读到的记录加锁**

```sql
-- 当前读的四种写法
SELECT * FROM t_order WHERE id = 1 FOR UPDATE;              -- 排他锁（X）
SELECT * FROM t_order WHERE id = 1 FOR SHARE;               -- 共享锁（S），8.0 新语法
SELECT * FROM t_order WHERE id = 1 LOCK IN SHARE MODE;      -- 5.7 语法，8.0 仍支持
UPDATE t_order SET status = 2 WHERE id = 1;                 -- 隐式当前读 + 加锁
DELETE FROM t_order WHERE id = 1;                           -- 同上
```

**8.0 新增的 `NOWAIT` / `SKIP LOCKED`（很实用）**：

```sql
-- NOWAIT：拿不到锁立即报错，不等待
SELECT * FROM t_order WHERE status = 0 LIMIT 1 FOR UPDATE NOWAIT;
-- 好处：不会被锁等 50 秒卡死连接

-- SKIP LOCKED：跳过已被锁定的行，直接取下一行
SELECT * FROM t_order WHERE status = 0 LIMIT 1 FOR UPDATE SKIP LOCKED;
-- 用途：多消费者抢任务（每个消费者拿一行，互不阻塞）—— 相当于用 MySQL 做了个简单的队列
```

**`SKIP LOCKED` 是 8.0 里最实用的新特性之一**，用它实现「任务抢占」比 `SELECT ... FOR UPDATE` + 重试要简洁得多。

**MVCC 在不同引擎/数据库的实现对比**

| | InnoDB | PostgreSQL | MongoDB(WiredTiger) |
|---|---|---|---|
| 旧版本存哪 | **undo log（独立表空间）** | **表空间内的旧行版本**（无独立 undo） | **WiredTiger 页内的历史版本** |
| 版本链方向 | 当前行 → 旧版本（链头最新） | 新版本 → 旧版本 | 类似 |
| 清理 | purge 线程 | VACUUM / autovacuum | 内部合并 |
| 长事务后果 | undo 膨胀、History list 增长 | **表膨胀（bloat）**，影响更大 | 缓存压力增大 |
| 快照语义 | ReadView + 四步判断 | `xmin` / `xmax` 事务快照 | `readConcern: snapshot` |

**PostgreSQL 的 MVCC 副作用更严重**：旧版本直接放在表文件里，不清理就导致表物理膨胀，`VACUUM` 是 PgSQL 运维的核心议题。**MySQL 的 undo 在独立表空间，膨胀只影响 undo 文件，业务表不受影响**——这是 InnoDB 设计上的一个优势。
:::

:::追问
**Q：为什么 `max_trx_id` 是「下一个待分配的 id」而不是「m_ids 的最大值」？**
因为要覆盖「ReadView 生成后、但在 `m_ids` 里没有记录到的事务」。假设 `m_ids=[200,250]`，最大活跃是 250，如果 `max_trx_id` 取 250，那么 251 到 399 之间的 id（这些事务在 ReadView 生成后才启动）就无法被区分——它们会被误判成「在 [min,max) 区间内但不在 m_ids 中 → 可见」。**取「下一个待分配 id」就保证了所有 `>= max_trx_id` 的事务一定是「我拍快照之后才开始的」，必然不可见。**

**Q：版本链会无限增长吗？读一个版本要回溯多少次？**
不会无限增长。**purge 线程**会清理「所有活跃 ReadView 都不需要」的旧版本。回溯次数取决于「链上有多少个未提交/对自己不可见的版本」——**如果一个长事务一直开着，purge 清理不掉，链会很长，每次查询都可能回溯几十上百次**。这就是「长事务拖慢整个库」的底层原因。

```sql
-- History list length 越大，说明链越长
SHOW ENGINE INNODB STATUS\G | grep -A 3 "TRANSACTIONS"
```

**Q：MVCC 下 `UPDATE` 一条被其他事务改过的行会怎样？**
保守做法是「等锁」：`UPDATE` 是当前读，会尝试对目标行加 X 锁，若已被其他事务持有则等待（最长 `innodb_lock_wait_timeout`，默认 50 秒），超时抛 `Lock wait timeout exceeded`。
**注意 MySQL 和 PostgreSQL 在这里行为不同**：MySQL 等待，PostgreSQL 在 RR 下直接报 `could not serialize access due to concurrent update` 让你重试。**MySQL 的行为更"温和"但可能掩盖并发冲突（等到了锁之后，基于新版本做的更新可能是基于错误假设的）。**

**Q：既然 MVCC 能防快照读的幻读，为什么还需要间隙锁？**
因为 **`UPDATE` / `DELETE` / `SELECT ... FOR UPDATE` 都是当前读，不走 MVCC**。如果没有间隙锁，一个事务在执行 `UPDATE t SET x=1 WHERE id>2` 时，另一个事务可以插入 `id=5` —— 这个新行可能会被 `UPDATE` 语句扫到（取决于执行时机），结果不可预期。**间隙锁的作用是「锁住区间，禁止插入」，从根本上保证范围操作的一致性。**
:::

:::锚点
**MongoDB 底层的 WiredTiger 引擎也实现了 MVCC，你的很多直觉可以直接迁移。**

WiredTiger 的 MVCC 与 InnoDB 的对照：

| | InnoDB | WiredTiger (MongoDB) |
|---|---|---|
| 旧版本存哪 | undo log（独立 undo 表空间） | 页内保留历史版本 + 磁盘上的更新记录 |
| 快照如何标识 | `ReadView`（`m_ids/min/max/creator`） | 事务 ID + `readConcern: snapshot` |
| 默认隔离 | RR（快照读不阻塞写） | `readConcern` 默认 `local` |
| 长事务后果 | undo 膨胀、History list 增长 | **缓存必须保留旧版本 → 缓存压力剧增** |

**面试话术**：

> 「MVCC 这块我在概念上是清楚的，而 MongoDB 的 WiredTiger 也是 MVCC 引擎，所以有些直觉是共通的。

> InnoDB 的实现是**两件东西配合**：① 每行有 `DB_TRX_ID` 和 `DB_ROLL_PTR` 两个隐藏列，每次更新时把旧版本写进 undo log，用回滚指针串成版本链；② 读的时候生成一个 ReadView，里面有四个字段——`m_ids`（活跃事务列表）、`min_trx_id`、`max_trx_id`、`creator_trx_id`，然后用四步判断当前版本可不可见：**自己的改的可见→小于 min 的可见→大于等于 max 的不可见→在 [min,max) 区间内再看在不在 m_ids 里。** 不可见就顺着回滚指针往上找。

> **RC 和 RR 的差别就在 ReadView 的生成时机：RC 每次 SELECT 都生成新的，RR 只在第一次 SELECT 生成然后复用。** 还有一个细节我比较在意——**RR 下 ReadView 是在「第一次快照读」时创建的，不是 `START TRANSACTION` 时**，所以事务里的语句顺序会影响看到的数据。

> 落到我自己的经验上：**我在 Mongo 上处理过一个问题，就是长时间持有快照会让 WiredTiger 缓存里必须保留大量旧版本，内存压力明显上升——这跟 InnoDB 里『长事务导致 undo 膨胀、History list 增长』是同一类问题。** 所以我们当时把批处理的读操作拆成了小的短事务，避免一个大批次从头到尾持有一个快照。」

**不要把 MongoDB 的经验说成 MySQL 的经验**。上面这段话里，你讲的是 Mongo 的实操 + InnoDB 的原理，两边都是真实且能对上的。
:::

---

## 12. InnoDB 锁：记录锁、间隙锁、临键锁与死锁

:::概念
InnoDB 的行级锁有三层粒度，**加锁的对象是「索引记录」和「索引记录之间的间隙」，不是数据行本身**（这一点极重要）：
**记录锁（Record Lock）** 锁单条索引记录；
**间隙锁（Gap Lock）** 锁两条记录之间的开区间 `(a, b)`，**只阻止插入，不阻止修改**；
**临键锁（Next-Key Lock）** = 记录锁 + 前面的间隙锁，左开右闭 `(a, b]`，是 RR 下的**默认加锁单位**。
一句话记：**「记录锁锁行、间隙锁锁缝、临键锁＝行+缝」；RR 用临键锁防幻读，RC 不用。**
:::

:::提问
- InnoDB 有哪些锁？记录锁、间隙锁、临键锁有什么区别？
- 为什么唯一索引等值查询只加记录锁，不加间隙锁？
- 间隙锁有什么用？为什么 RR 需要它？
- 死锁怎么产生的？怎么排查和避免？
- 什么是插入意向锁？
- 什么是意向锁（IS / IX）？为什么需要它？
:::

:::答案
### 一、锁的第一原理：InnoDB 锁的是「索引记录」

**InnoDB 的行锁加在索引记录上，而不是数据行上。**

推论（非常关键）：
- 如果查询**没有走索引**，InnoDB 无法定位到具体的索引记录 → **只能锁住整张表**（实际是锁住全部索引记录，效果等于表锁）
- **锁的粒度取决于索引的精度**：走唯一索引等值 → 只锁一行；走范围索引 → 锁一个区间

```sql
-- 演示：没走索引的 UPDATE 会锁住全表
-- 会话 A
START TRANSACTION;
UPDATE t_order SET status = 9 WHERE remark = 'xxx';   -- remark 无索引 → 全表所有行被锁

-- 会话 B（会被阻塞！即使改的是完全不同的行）
UPDATE t_order SET amount = 1 WHERE id = 999999;
-- ERROR 1205 (HY000): Lock wait timeout exceeded
```

**这就是「UPDATE 一定要走索引」的最硬理由**——不只是性能，是并发度。

### 二、三种锁的形态

```text
假设索引上有记录：id = 1, 5, 10, 15

【间隙（Gap）】：(-∞,1) (1,5) (5,10) (10,15) (15,+∞)  ← 全是开区间

【记录锁 Record Lock】：锁住 id=5 这一条记录
    1   [5]   10   15     ← 只有 5 被锁

【间隙锁 Gap Lock】：锁住 (1,5) 这个间隙，禁止在其中插入 id=2,3,4
    1  ░░░░░  5   10   15  ← 间隙被锁（但 1 和 5 本身不被锁）

【临键锁 Next-Key Lock】：锁住 (1,5]，即「间隙 (1,5) + 记录 5」
    1  ░░░░░ [5]  10   15  ← 左开右闭，这是 RR 下的默认单位
```

| 锁类型 | 锁什么 | 阻止什么 | 允许什么 |
|---|---|---|---|
| **记录锁** | 单条索引记录 | 其他事务的 `UPDATE`/`DELETE` 该行 | 其他事务在间隙里插入 |
| **间隙锁** | 两条记录之间的开区间 | **其他事务的 INSERT** | 其他事务修改已存在的记录 |
| **临键锁** | 记录 + 前面的间隙（左开右闭） | 两者都阻止 | — |
| **插入意向锁** | 一种特殊的间隙锁 | 不阻止同一间隙不同位置的插入 | 见下方 |

**关键：间隙锁之间是「相容」的**——两个事务可以对同一个间隙各加一个间隙锁，互不冲突（因为间隙锁的目的只是防插入，不是互斥）。**间隙锁只与「插入意向锁」冲突。**

### 三、插入意向锁（Insert Intention Lock）

**INSERT 操作在插入前会先加一个「插入意向锁」**——它是一种特殊的间隙锁，表示「我打算在这个间隙的某个位置插入」。

- **多个事务对同一个间隙的不同位置插入 → 不冲突**（插入意向锁之间相容）
- **插入意向锁与间隙锁冲突** → 一旦有人持有该间隙的间隙锁，插入会被阻塞

```sql
-- 演示：间隙锁阻塞插入
-- 会话 A（RR）
START TRANSACTION;
SELECT * FROM t_order WHERE id > 10 AND id < 20 FOR UPDATE;   -- 锁住 (10,20) 区间

-- 会话 B
INSERT INTO t_order (id, ...) VALUES (15, ...);
-- 阻塞！等待会话 A 提交或回滚
```

**为什么要有插入意向锁**：如果没有它，多个事务往同一间隙插入时，需要无法确定「谁先谁后」，容易产生死锁。有了它，InnoDB 能知道「各自的插入位置」，只在真正的位置冲突时才等待。

### 四、意向锁（IS / IX）：表级与行级的桥梁

**问题**：事务 A 想给表加表级锁，事务 B 持有行级锁——A 怎么知道「有没有行锁」？逐行检查太慢。

**解决**：InnoDB 引入了表级的**意向锁**：

| 锁 | 简称 | 作用 |
|---|---|---|
| 意向共享锁 | IS | 表示「本事务打算给某些行加 S 锁」 |
| 意向排他锁 | IX | 表示「本事务打算给某些行加 X 锁」 |

**加行锁前，必须先加对应的意向锁。**

**兼容矩阵**（✅ 相容，❌ 冲突）：

| | S（表） | X（表） | IS | IX |
|---|---|---|---|---|
| **S** | ✅ | ❌ | ✅ | ❌ |
| **X** | ❌ | ❌ | ❌ | ❌ |
| **IS** | ✅ | ❌ | ✅ | ✅ |
| **IX** | ❌ | ❌ | ✅ | ✅ |

**关键点**：**意向锁之间互相相容**（IS 和 IX 不冲突）。所以多个事务可以在同一张表上加行锁——只要不申请表锁，意向锁完全不构成阻碍。**意向锁的唯一作用就是「让表锁能快速判断是否存在行锁」。**

### 五、加锁规则（唯一索引 vs 非唯一索引）

**这是最容易被追问的细节。**

#### 情况 1：唯一索引等值查询，命中记录

```sql
-- id 是主键（唯一）
SELECT * FROM t_order WHERE id = 5 FOR UPDATE;
-- 加锁：id=5 上的【记录锁】。不加间隙锁！
```

**为什么不加间隙锁**：**唯一索引保证不会有第二行 id=5**，所以「防插入」这件事根本不需要——不存在「插一个新 id=5 进来」的情况。**这是唯一索引等值查询的一个显著优化。**

#### 情况 2：唯一索引等值查询，未命中记录

```sql
-- id=7 不存在（表里有 1, 5, 10）
SELECT * FROM t_order WHERE id = 7 FOR UPDATE;
-- 加锁：【间隙锁】锁住 (5, 10)
```

**为什么反而要加间隙锁**：因为目标不存在，必须阻止「有人在 (5,10) 里插入 id=7」——否则一个「查询不存在就插入」的业务逻辑会出现并发问题（这是 `INSERT ... ON DUPLICATE KEY` 的经典并发场景）。

#### 情况 3：非唯一索引等值查询

```sql
-- status 上有非唯一索引，索引值：1, 2, 2, 2, 3
SELECT * FROM t_order WHERE status = 2 FOR UPDATE;
-- 加锁：【临键锁】锁住 (1,2] 以及后续的 2、直到第一个不满足条件的记录
-- 实际是锁住 (1,2]，并且因为 2 有重复，会向后继续扫描加锁到 3 前
```

**规律**：非唯一索引等值查询 → **临键锁**，并且会**向后扫描到第一个不满足条件的记录**（这个是防止「插入的新行也是 status=2」）。

#### 情况 4：范围查询

```sql
SELECT * FROM t_order WHERE id >= 5 AND id < 15 FOR UPDATE;
-- 加锁：临键锁，锁住 (1,5], (5,10], (10,15)，一直到 15 记录本身
```

#### 汇总表（背下来）

| 查询类型 | 索引类型 | 命中情况 | 加锁 |
|---|---|---|---|
| 等值 | **唯一索引** | 命中 | **记录锁** |
| 等值 | **唯一索引** | 未命中 | **间隙锁** |
| 等值 | **非唯一索引** | 命中 | **临键锁**（+ 向后扫到第一个不满足的记录） |
| 范围 | 任意 | — | **临键锁**（范围内全部） |
| 等值 | **无索引** | — | **锁全表**（所有记录 + 所有间隙） |
| 任意 | 任意 | **RC 隔离级别** | **不加间隙锁**（只加记录锁） |

**最后一行是 RC 的核心优势**：RC 下不加间隙锁 → 并发插入不被阻塞 → 死锁概率大幅降低。

### 六、死锁

**产生的四个必要条件**（经典的操作系统理论，数据库里同样适用）：
1. 互斥（资源独占）
2. 请求与保持（拿着一个等另一个）
3. 不可剥夺（不能强行抢）
4. 循环等待（A 等 B，B 等 A）

**数据库能主动打破的是第 4 条**——通过**死锁检测**发现循环后，**回滚代价最小的事务**。

```sql
-- 死锁检测开关（默认 ON）
SHOW VARIABLES LIKE 'innodb_deadlock_detect';

-- 死锁相关参数
SHOW VARIABLES LIKE 'innodb_lock_wait_timeout';   -- 默认 50 秒
```

| 参数 | 默认值 | 行为 |
|---|---|---|
| `innodb_deadlock_detect = ON` | ON | 主动检测死锁环路，发现后**立即回滚代价最小的事务**，报 `ERROR 1213: Deadlock found` |
| `innodb_deadlock_detect = OFF` | — | 不检测，靠 `innodb_lock_wait_timeout` 超时兜底（**高并发下检测本身很耗 CPU，此时关掉反而更快**） |

**典型案例：两个事务以相反顺序更新两行**

```sql
-- 会话 A                       -- 会话 B
START TRANSACTION;              START TRANSACTION;
UPDATE t SET x=1 WHERE id=1;    UPDATE t SET x=1 WHERE id=2;
-- （A 持有 id=1 的锁）           -- （B 持有 id=2 的锁）
UPDATE t SET x=1 WHERE id=2;    UPDATE t SET x=1 WHERE id=1;
-- 等待 B 释放 id=2               -- 等待 A 释放 id=1
-- → 死锁！InnoDB 检测到后回滚其中一个：
-- ERROR 1213 (40001): Deadlock found when trying to get lock; try restarting transaction
```

**排查死锁**：

```sql
-- ① 看最近一次死锁的详细信息（最重要）
SHOW ENGINE INNODB STATUS\G
-- 找到 LATEST DETECTED DEADLOCK 段落，里面有：
--   TRANSACTION 1: 事务 id、正在执行什么、持有什么锁、等待什么锁
--   TRANSACTION 2: 同上
--   WE ROLL BACK TRANSACTION (1)  ← 被回滚的是哪个
--   以及涉及的具体索引记录

-- ② 开启死锁日志到错误日志
SHOW VARIABLES LIKE 'innodb_print_all_deadlocks';   -- 默认 OFF
SET GLOBAL innodb_print_all_deadlocks = ON;
-- 开启后每次死锁都会写入 error log，便于长期收集分析

-- ③ 8.0：从 performance_schema 看锁等待
SELECT * FROM performance_schema.data_locks;         -- 当前持有的锁（8.0 新表名）
SELECT * FROM performance_schema.data_lock_waits;    -- 锁等待关系
-- 5.7 对应：information_schema.INNODB_LOCKS / INNODB_LOCK_WAITS（8.0 已废弃）

-- ④ 简单版：只看当前等待
SELECT * FROM sys.innodb_lock_waits\G
```

**避免死锁的工程手段**：

| 手段 | 说明 |
|---|---|
| **统一加锁顺序** | 最有效。所有事务按同一顺序访问资源（如按主键升序更新），从根上消除循环等待 |
| **缩小事务范围** | 事务里不做网络调用、不等待用户输入、不做大量计算 |
| **走索引** | 避免锁全表；尽量用唯一索引等值定位 |
| **降级到 RC** | 不加间隙锁，死锁概率大幅下降 |
| **按固定顺序批量更新** | 批量操作时先 `ORDER BY id` 再逐条更新 |
| **应用层重试** | 捕获 `1213` 后重试（保证幂等）——**这是必须实现的兜底** |
| **拆分大事务** | 一次改 10000 行改成 10 次 1000 行 |

```sql
-- 批量更新时先排序，避免死锁
UPDATE t_order SET status = 3
WHERE id IN (SELECT id FROM (SELECT id FROM t_order WHERE status = 2 ORDER BY id LIMIT 1000) tmp);
-- 注意：MySQL 里 UPDATE 不能直接用同表的子查询，需要包一层派生表
```

### 七、查看锁的现状

```sql
-- 8.0：当前所有锁
SELECT
  ENGINE_LOCK_ID, ENGINE_TRANSACTION_ID,
  OBJECT_NAME, INDEX_NAME,
  LOCK_TYPE, LOCK_MODE, LOCK_STATUS, LOCK_DATA
FROM performance_schema.data_locks\G

-- LOCK_TYPE: TABLE / RECORD
-- LOCK_MODE:
--   X,REC_NOT_GAP   → 记录锁（排他）
--   X,GAP           → 间隙锁
--   X               → 临键锁（Next-Key）
--   X,INSERT_INTENTION → 插入意向锁
--   S,REC_NOT_GAP   → 共享记录锁
-- LOCK_STATUS: GRANTED（已获得）/ WAITING（等待中）  ← 找 WAITING 的
-- LOCK_DATA: 被锁的记录值（如 "5"、SUPREMUM PSEUDO RECORD）

-- 谁在等谁（8.0）
SELECT
  w.REQUESTING_ENGINE_TRANSACTION_ID AS waiting_trx,
  w.BLOCKING_ENGINE_TRANSACTION_ID   AS blocking_trx,
  r.OBJECT_NAME, r.LOCK_TYPE, r.LOCK_MODE, r.LOCK_DATA
FROM performance_schema.data_lock_waits w
JOIN performance_schema.data_locks r
  ON r.ENGINE_LOCK_ID = w.BLOCKING_ENGINE_LOCK_ID;

-- 友好版：sys 库直接告诉你阻塞关系
SELECT * FROM sys.innodb_lock_waits\G
-- 输出含 waiting_pid / blocking_pid / blocking_query / waiting_query
```

### 八、其他粒度的锁

| 锁 | 层级 | 说明 |
|---|---|---|
| **表锁** | 表 | `LOCK TABLES t READ/WRITE`；MyISAM 的唯一粒度 |
| **元数据锁 MDL** | 表 | 访问表时自动加。**`SELECT` 加 MDL 读锁，`ALTER` 加 MDL 写锁** —— 长查询会阻塞 DDL，DDL 会阻塞后续所有查询（包括 `SELECT`）。这是「改表引发雪崩」的根源 |
| **自增锁 AUTO-INC** | 表 | 控制 `AUTO_INCREMENT` 分配；`innodb_autoinc_lock_mode` 默认 2（交错模式，性能最好但 binlog 需 ROW 格式） |
| **谓词锁** | — | 空间索引专用 |

```sql
-- MDL 锁的查看（重要！线上 DDL 卡住时用）
SELECT * FROM performance_schema.metadata_locks WHERE LOCK_STATUS = 'PENDING'\G

-- 相关参数
SHOW VARIABLES LIKE 'lock_wait_timeout';            -- MDL 等待超时，默认 31536000 秒（1 年！）
SHOW VARIABLES LIKE 'innodb_autoinc_lock_mode';     -- 默认 2（8.0）/ 1（5.7）
SHOW VARIABLES LIKE 'max_write_lock_count';
```

**`lock_wait_timeout` 默认一年**：意味着一个拿不到 MDL 写锁的 `ALTER TABLE` 会一直挂着，同时**阻塞之后所有的查询**（因为 DDL 后面的查询要排队等 MDL）。**这就是为什么大表 DDL 必须用 `gh-ost` 或 `pt-online-schema-change`**，或者至少先设 `SET SESSION lock_wait_timeout = 5` 让它快速失败。
:::

:::拓展
**RR 下间隙锁的「副作用」**

间隙锁能防幻读，但代价是**并发插入能力下降 + 死锁概率上升**。

```text
【RR 下的经典死锁：间隙锁 + 插入意向锁】
索引上有：id = 10, 20

会话 A: SELECT * FROM t WHERE id > 10 AND id < 20 FOR UPDATE;   -- 锁住间隙 (10,20)
会话 B: SELECT * FROM t WHERE id > 10 AND id < 20 FOR UPDATE;   -- 同样拿到间隙锁（相容！）
会话 A: INSERT INTO t VALUES (15);   -- 申请插入意向锁 → 被 B 的间隙锁阻塞
会话 B: INSERT INTO t VALUES (16);   -- 申请插入意向锁 → 被 A 的间隙锁阻塞
-- → 死锁！

【解决】
① 降级到 RC（不加间隙锁）
② 避免在事务里做 "先 SELECT FOR UPDATE 再 INSERT" 的模式
③ 用 INSERT ... ON DUPLICATE KEY UPDATE 让数据库在一条语句里完成
```

**Rc 下的锁行为变化**

| | RR | RC |
|---|---|---|
| 间隙锁 | **加** | **不加** |
| 唯一索引等值未命中 | 间隙锁 | 只加记录锁（或无锁） |
| 范围查询 | 临键锁 | 记录锁（只锁扫到的行） |
| 幻读 | 当前读不会 | 会 |
| 并发插入 | 受影响 | 不受影响 |
| 死锁概率 | 高 | 低 |
| 半一致性读（`UPDATE` 时的优化） | 不用 | **会用**：先读最新版本判断是否满足 WHERE，不满足就释放锁跳过 |

**RC 的「半一致性读（semi-consistent read）」**：`UPDATE ... WHERE` 时，如果某行已被其他事务锁定但**不满足 WHERE 条件**，RC 下 InnoDB 会直接跳过它，不等锁。**这是 RC 在高并发写入场景下性能明显更好的一个关键原因。**

**MySQL 8.0 新增的锁相关能力**

```sql
-- ① NOWAIT：拿不到锁立即失败
SELECT * FROM t_order WHERE id = 1 FOR UPDATE NOWAIT;
-- ERROR 3572 (HY000): Statement aborted because lock(s) could not be acquired immediately and NOWAIT is set.

-- ② SKIP LOCKED：跳过被锁的行（做一个简单的队列）
START TRANSACTION;
SELECT * FROM task_queue WHERE status = 0 ORDER BY id LIMIT 1 FOR UPDATE SKIP LOCKED;
UPDATE task_queue SET status = 1, worker = 'w1' WHERE id = ?;
COMMIT;
-- 多个 worker 并发执行时，彼此不会阻塞，各自拿到不同的行

-- ③ data_locks / data_lock_waits 性能视图（替代 5.7 的 INNODB_LOCKS）
SELECT * FROM performance_schema.data_lock_waits;
```
:::

:::追问
**Q：为什么说「InnoDB 锁的是索引记录不是数据行」？**
因为 InnoDB 的行锁信息**存在索引记录上**（具体说是在聚簇索引或二级索引记录的锁位图中）。这解释了三件事：
① **`UPDATE` 不走索引就会锁全表**——因为没有索引记录可以定位，只能锁所有记录（等于锁表）；
② **走二级索引加锁时，会同时对二级索引记录和对应的聚簇索引记录加锁**（因为要回表改数据）；
③ **同一行的不同索引项可能被分别加锁**，这也是复杂死锁的来源。

**Q：`SELECT * FROM t WHERE id = 5 FOR UPDATE`，id 是主键，会锁哪些？**
只锁 `id=5` 这一条记录（**记录锁，不加间隙锁**）——因为主键唯一，不存在「插入另一个 id=5」的可能，无需间隙锁。**这是唯一索引等值命中的特例。**
但注意：**如果这条记录在二级索引上也要加锁**（比如同时通过 name 索引访问），则二级索引和聚簇索引都会加锁。

**Q：为什么 `SELECT ... FOR UPDATE` 在 RC 下不加间隙锁，但 RR 下要加？**
因为 RR 要保证「可重复读」的语义扩展到了「范围结果集一致」——如果不锁间隙，别的事务插入了新行，同一个事务两次执行同样的范围查询会得到不同结果（幻读）。RC 允许幻读，所以不需要间隙锁。

**Q：死锁是异常还是正常现象？**
**在有一定并发量的系统里，死锁是正常现象**，关键是：① 发生率低；② 应用能正确处理（重试）。**要求「零死锁」的团队通常是把并发压得很低**。正确的态度是：**监控死锁次数、分析死锁日志、优化加锁顺序、在应用层做幂等重试**，而不是试图完全消灭它。

```java
// 应用层的重试模板（Spring）
@Retryable(
    value = { CannotAcquireLockException.class, DeadlockLoserDataAccessException.class },
    maxAttempts = 3, backoff = @Backoff(delay = 100, multiplier = 2)
)
public void transfer(Long from, Long to, BigDecimal amount) { ... }
```

**Q：MDL 锁和行锁的区别？```
完全不同层：
- **行锁**保护**数据**（数据的一致性），由 InnoDB 实现；
- **MDL（元数据锁）**保护**表结构**（表定义不被并发修改），由 Server 层实现。
两者会互相影响：**一个长事务持有的 MDL 读锁会阻塞 `ALTER TABLE`；而 `ALTER TABLE` 请求的 MDL 写锁会阻塞后续所有查询。** 这是「大表 DDL 导致线上雪崩」的完整链条。

```sql
-- 线上 DDL 卡住时的标准自救流程
-- ① 找到持有 MDL 读锁的长事务
SELECT * FROM sys.schema_table_lock_waits\G
-- ② 或者直接看是否有长事务
SELECT trx_id, trx_started, TIMESTAMPDIFF(SECOND, trx_started, NOW()) AS sec, trx_mysql_thread_id
FROM information_schema.INNODB_TRX ORDER BY trx_started LIMIT 5;
-- ③ 杀长事务释放 MDL（确认业务影响后）
KILL <thread_id>;
```
:::

:::锚点
**RRM 项目里你没有做过 MySQL 上的锁分析，但 MongoDB 有对应的锁模型，切入点在这里。**

MongoDB 的锁模型演进：

| 版本 | 锁粒度 |
|---|---|
| 2.x | 全局锁 |
| 3.x | 数据库级锁 |
| **4.0+** | **WiredTiger 文档级（document-level）并发控制** + 意向锁 |

**WiredTiger 也使用「意向锁 + 文档锁」的模型**——和 InnoDB 的 `IX/IS` + 行锁是同一套设计思想：**先加意向锁声明意图，再加细粒度的文档锁。**

**面试话术**：

> 「MySQL 的锁这块我是从原理上理解的，生产上还没做过 MySQL 的锁冲突排查。但有几个点我特别有共鸣，因为 MongoDB 也有类似的模型。

> 第一，**InnoDB 的行锁是加在索引记录上的**——这意味着 `UPDATE` 一旦不走索引，锁的范围就是全表。**这条规律在 Mongo 里也有对应：WiredTiger 是文档级并发控制，但一个不带索引的更新条件会去全集合扫描，扫描过程中会接触大量文档，冲突概率和代价都会上升。** 所以我在写更新语句时，第一反应永远是确认更新条件走不走索引。

> 第二，**锁的粒度和隔离级别强相关**。RR 下的间隙锁是为了防幻读，代价是并发插入被阻塞、死锁概率上升——所以很多互联网公司会降级到 RC。**这个权衡我在 Mongo 里从另一个角度体会过：`readConcern` 从 `local` 提到 `snapshot` 或 `majority`，一致性更强但代价更高，本质上是同一个权衡。**

> 第三，**死锁在生产里是正常现象，关键是能不能及时发现和处理**。MySQL 这边靠 `SHOW ENGINE INNODB STATUS` 看最近一次死锁、`innodb_print_all_deadlocks` 长期收集、`performance_schema.data_lock_waits` 看实时等待；应用层要捕获 `1213` 做幂等重试。**我在 RRM 里做过的对应工作是：给调优任务的并发加限制、把大批量操作拆成小批次，本质上是"缩小事务范围、降低锁冲突窗口"这个思路。**」

**关键**：说「我从原理上理解，并且把 Mongo 的经验迁移过来」，**不要说「我在 MySQL 上调过锁参数」**。
:::

---

## 13. 三大日志：redo log / undo log / binlog 与两阶段提交

:::概念
| 日志 | 层级 | 类型 | 作用 |
|---|---|---|---|
| **redo log** | **InnoDB** | 物理日志（页的修改） | **崩溃恢复**（持久性），**循环写** |
| **undo log** | **InnoDB** | 逻辑日志（反向操作） | **回滚 + MVCC 版本链** |
| **binlog** | **Server 层** | 逻辑日志（SQL 或行变更） | **主从复制 + 数据恢复**，**追加写** |

「三大日志」的记忆钩子是**「redo 前滚、undo 回滚、binlog 复制」**。
**redo 是 InnoDB 独有的（MyISAM 没有），binlog 是所有引擎共用的（Server 层实现）。**
:::

:::提问
- MySQL 有哪几种日志？分别做什么？
- redo log 和 binlog 有什么区别？
- 为什么需要两阶段提交？不这样做会怎样？
- redo log 为什么是循环写？binlog 为什么是追加写？
- binlog 有几种格式？怎么选？
- 什么是组提交？
:::

:::答案
### 一、三大日志总表（核心）

| 维度 | **redo log** | **undo log** | **binlog** |
|---|---|---|---|
| **实现层级** | InnoDB 引擎层 | InnoDB 引擎层 | **Server 层**（所有引擎共用） |
| **日志类型** | **物理日志**（记录「某页某偏移改成了什么」） | **逻辑日志**（记录「如何撤销」） | **逻辑日志**（记录 SQL 或行变更） |
| **写入方式** | **循环写**（固定大小，覆盖式） | 追加写（在 undo 表空间内） | **追加写**（文件只增不减） |
| **主要作用** | **崩溃恢复**（持久性） | **回滚 + MVCC**（原子性 + 隔离性） | **主从复制 + 数据恢复** |
| **是否可关闭** | 不能 | 不能 | **可以**（`skip-log-bin`，但生产绝不该关） |
| **典型文件** | `ib_logfile0/1`（5.7）或 `#innodb_redo/`（8.0.30+） | `undo_001/002` | `binlog.000001` / `mysql-bin.000001` |
| **典型参数** | `innodb_log_file_size`（48M）<br>`innodb_redo_log_capacity`（8.0.30+，100M） | `innodb_undo_tablespaces`（2） | `binlog_format`（ROW）<br>`max_binlog_size`（1G） |
| **谁关心** | DBA 调优崩溃恢复速度 | MVCC 性能 | DBA 做复制/恢复，CDC 做数据订阅 |

### 二、redo log：WAL 与循环写

**redo log 记录的是「在某个数据页上做了什么修改」**，例如：

```text
把 表空间 5 号、页号 20、偏移量 100 处的 4 字节改成 0x00000002
```

**这不是「物理地址 + 物理值」吗？为什么叫物理日志？**
——对，**redo log 是物理日志**（准确说是「物理逻辑日志」）。它的好处是**幂等**：重放多少次结果都一样，因为记的是「改成什么」，不是「加多少」。

**循环写的机制**：

```text
┌──────────── redo log 文件组（总容量固定，如 96M / 1G）────────────┐
│                                                                  │
│  write pos ──────►                          ◄────── checkpoint   │
│  （当前写入位置）                              （已刷盘位置）       │
│                                                                  │
│  可写区域 = [write pos, checkpoint)  的空闲部分（顺时针）          │
│                                                                  │
└──────────────────────────────────────────────────────────────────┘

写入时 write pos 顺时针推进；
后台 checkpoint 把脏页刷盘后，checkpoint 也跟着顺时针推进；
当 write pos 追上 checkpoint → redo 空间满 → 必须停下来推进 checkpoint
（表现为"刷脏页变慢/卡顿"，日志里可能有 innodb_log_waits）
```

```sql
-- redo log 相关参数
SHOW VARIABLES LIKE 'innodb_log_file_size';        -- 默认 48M（MySQL 5.7/8.0.30 前）
SHOW VARIABLES LIKE 'innodb_log_files_in_group';   -- 默认 2 → 总容量 = 48M × 2 = 96M
SHOW VARIABLES LIKE 'innodb_redo_log_capacity';    -- 8.0.30+ 新参数，默认 100M
SHOW VARIABLES LIKE 'innodb_log_buffer_size';      -- 默认 16M，redo 的写缓冲
SHOW VARIABLES LIKE 'innodb_flush_log_at_trx_commit'; -- 默认 1

-- 8.0.30+ 看 redo 文件状态
SELECT * FROM performance_schema.innodb_redo_log_files;

-- 看 redo 使用情况
SHOW ENGINE INNODB STATUS\G
-- LOG 段落里有：
--   Log sequence number          1234567890   （当前 LSN）
--   Log buffer assigned up to    ...
--   Log flushed up to            ...
--   Pages flushed up to          ...           （checkpoint）
--   Last checkpoint at           ...
--   差值越大说明脏页积压越多
```

**redo log 太小会怎样**：checkpoint 追得紧，脏页必须频繁刷盘，`innodb_log_waits` 增加，**表现为写入抖动**。**经验值：让 redo 至少能容纳 1~2 小时的写入量。**

```sql
-- 8.0.30+ 直接改容量（在线生效）
SET GLOBAL innodb_redo_log_capacity = 2 * 1024 * 1024 * 1024;   -- 2G
-- 5.7 / 8.0.30 前需要改 my.cnf 后重启，且要先把 innodb_fast_shutdown 设为 0 或 1
```

### 三、binlog：三种格式与写入策略

**binlog 记录的是「逻辑变更」**，格式有三种：

| 格式 | 记录内容 | 优点 | 缺点 |
|---|---|---|---|
| **`STATEMENT`** | 原始 SQL 语句 | 日志小、可读性好 | **不确定函数（`NOW()`/`RAND()`/`UUID()`）导致主从数据不一致**；必须 RR 隔离级别 |
| **`ROW`**（5.7+ 默认） | **每一行的 before / after 值** | 绝对可靠、可做 CDC 订阅 | 日志大（批量更新时爆炸），难读 |
| **`MIXED`** | 自动选择：能用 STATEMENT 就用，不确定的用 ROW | 折中 | 仍然存在部分不确定场景 |

```sql
-- 查看当前格式
SHOW VARIABLES LIKE 'binlog_format';           -- ROW

-- 查看 binlog 相关配置
SHOW VARIABLES LIKE 'log_bin';                 -- ON
SHOW VARIABLES LIKE 'binlog_row_image';        -- FULL（默认，记录完整前像+后像）
SHOW VARIABLES LIKE 'max_binlog_size';         -- 默认 1G（1073741824）
SHOW VARIABLES LIKE 'sync_binlog';             -- 默认 1（8.0）；5.7 默认 0
SHOW VARIABLES LIKE 'binlog_expire_logs_seconds'; -- 默认 2592000（30天），旧参数 expire_logs_days

-- 动态开启（8.0 支持运行时开启，5.7 需要重启）
SET GLOBAL binlog_expire_logs_seconds = 604800;   -- 保留 7 天

-- 查看当前 binlog 文件列表和大小
SHOW BINARY LOGS;
SHOW MASTER STATUS\G    -- 8.0.22+ 也可以用 SHOW BINLOG STATUS

-- 查看某个 binlog 的内容（必须先转成可读格式）
-- 命令行执行：
-- mysqlbinlog --base64-output=DECODE-ROWS -v /var/lib/mysql/binlog.000001 | less
-- --start-datetime / --stop-datetime 按时间过滤
```

**`binlog_row_image` 的三种取值**：

| 值 | 记录内容 | 用途 |
|---|---|---|
| `FULL`（默认） | 前像 + 后像的**所有列** | 最安全，CDN/CDC 订阅需要 |
| `MINIMAL` | 前像只记主键、后像只记变化的列 | 日志小，但某些恢复场景信息不足 |
| `NOBLOB` | 与 FULL 相同但 BLOB/TEXT 未变的列不记 | 折中 |

**ROW + MINIMAL 是「日志瘦身」的常见组合**，但要确认下游（canal / Debezium 等 CDC）能接受。

### 四、两阶段提交（重点，面试高频）

**问题**：一次事务提交要写两份日志（redo log 和 binlog），**它们必须保持一致**。如果写完一份就崩溃了，会发生什么？

**不两阶段提交的两种崩溃场景**：

| 场景 | 情况 | 后果 |
|---|---|---|
| **先写 redo，后写 binlog**，写完 redo 后崩溃 | redo 已落盘，binlog 没有 | **主库有这行数据，从库没有**（从库靠 binlog 复制）→ **主从不一致** |
| **先写 binlog，后写 redo**，写完 binlog 后崩溃 | binlog 有，redo 没有 | **从库有这行数据，主库没有** → **主从不一致** |

**两种情况都会导致主从不一致，所以必须有一个机制让两份日志「要么都生效，要么都不生效」。**

**两阶段提交的流程**：

```text
【阶段一：Prepare】
  ① InnoDB 把修改写入 redo log，但标记为 "prepare" 状态
  ② Server 层把变更写入 binlog（此时 binlog 已落盘）
  ③ 通知 InnoDB："binlog 写好了，你可以提交了"

【阶段二：Commit】
  ④ InnoDB 把 redo log 中的该事务标记为 "commit"
  ⑤ 返回客户端成功
```

**崩溃恢复的判断规则（关键）**：

| redo log 状态 | binlog 状态 | 恢复动作 | 原因 |
|---|---|---|---|
| **prepare** | **完整**（有对应的 XID 事件） | **提交**（前滚） | binlog 已完整，从库能收到 → 主库也要有 |
| **prepare** | **不完整**（缺少或不完整） | **回滚** | 从库收不到 → 主库也不能有 |
| **commit** | 无论 | 已完成，不用处理 | 已提交 |

**判断依据**：redo log 的 prepare 记录里带了一个 **XID**（事务 id），恢复时用这个 XID 去 binlog 里找对应的**事务结束事件**（`Xid_log_event`）。找到了 → 提交；没找到 → 回滚。

**这就是两阶段提交的全部逻辑**：**用 binlog 是否完整作为「是否提交」的裁决依据。**

### 五、组提交（Group Commit）

**性能问题**：`innodb_flush_log_at_trx_commit=1` + `sync_binlog=1` 时，每个事务要 **fsync 两次**（一次 redo、一次 binlog）。fsync 是磁盘操作，一次可能几毫秒——**单连接 QPS 上限就被锁死在几百**。

**解决：组提交**。把多个并发事务的 fsync 合并成一次。

```text
【无组提交】
事务1: fsync(redo) → fsync(binlog)
事务2: fsync(redo) → fsync(binlog)
事务3: fsync(redo) → fsync(binlog)      总共 6 次 fsync

【有组提交】
事务1,2,3 一起: fsync(redo × 3) 一次 → fsync(binlog × 3) 一次
                                         总共 2 次 fsync（合并了！）
```

**binlog 的三阶段提交**（`binlog_group_commit_sync_delay` 相关）：

| 阶段 | 做什么 | 锁 |
|---|---|---|
| **FLUSH** | 把 binlog 从线程缓存写入文件 | 加 LOCK_log |
| **SYNC** | fsync 到磁盘 | 释放 LOCK_log |
| **COMMIT** | 引擎层提交（redo 标记 commit） | — |

**关键优化：`SYNC` 阶段在最前面的事务做 fsync 时，后面到达的事务可以「加入这个组」一起被 fsync**——这就是组提交的并行化来源。

```sql
-- 组提交相关参数
SHOW VARIABLES LIKE 'binlog_group_commit_sync_delay';   -- 默认 0（微秒），等待多少微秒再 fsync
SHOW VARIABLES LIKE 'binlog_group_commit_sync_no_delay_count'; -- 默认 0，攒够多少事务就立即 fsync

-- 调优示例：愿意牺牲 1ms 延迟换取吞吐提升
SET GLOBAL binlog_group_commit_sync_delay = 1000;          -- 等 1ms
SET GLOBAL binlog_group_commit_sync_no_delay_count = 100;  -- 或攒够 100 个
```

**用 `binlog_group_commit_sync_delay` 换吞吐的取舍**：设置了延迟意味着**每个事务的提交延迟至少增加这个值**，但能显著提升高并发下的吞吐（更多事务被合并到一次 fsync）。

```sql
-- 看组提交的效果
SHOW GLOBAL STATUS LIKE 'Binlog_commits';        -- binlog 提交次数
SHOW GLOBAL STATUS LIKE 'Binlog_group_commits';  -- 组提交次数
-- 比值 Binlog_commits / Binlog_group_commits = 平均每组几个事务
-- 理想值应该 > 1，越大说明合并效率越高
```

### 六、三种日志的完整生命周期

```text
【一次 UPDATE 的完整日志流程】

① 事务开始 → 分配 trx_id
② 定位目标行（buffer pool 中）→ 加行锁
③ 写 undo log：把旧版本写进 undo 表空间
④ 修改 buffer pool 中的页（标记脏页）
⑤ 写 redo log：把"页的修改"写入 redo log buffer
⑥ 写 undo log 的 redo（undo 也是数据页，也需要 redo 保护）
⑦ 事务提交（COMMIT）：
   ⑦a. redo log buffer 刷到磁盘，标记 prepare
   ⑦b. 写 binlog（先写 binlog cache，再刷盘）
   ⑦c. redo log 标记 commit（写入 commit 记录）
⑧ 返回客户端成功
⑨ 后台：
   - checkpoint 线程把脏页刷回磁盘（推进 checkpoint）
   - purge 线程清理不再需要的 undo（版本链裁剪）
   - binlog 文件按 max_binlog_size 滚动，按过期时间删除
```

### 七、参数速查与生产配置建议

```ini
[mysqld]
# ────── 持久性（核心） ──────
innodb_flush_log_at_trx_commit = 1     # 双 1 配置之一：不丢数据
sync_binlog                    = 1     # 双 1 配置之二（8.0 默认已是 1）

# ────── redo log ──────
innodb_log_file_size           = 1G    # 5.7/8.0.30 前；单文件大小
innodb_log_files_in_group      = 2     # 总容量 = 2G
# 8.0.30+ 改用：
innodb_redo_log_capacity       = 2G
innodb_log_buffer_size         = 64M   # 大事务多时可调大

# ────── binlog ──────
log_bin                        = ON
binlog_format                  = ROW   # 5.7+ 默认
binlog_row_image               = FULL  # 有 CDC 订阅必须 FULL
max_binlog_size                = 1G
binlog_expire_logs_seconds     = 604800  # 保留 7 天（默认 30 天）
sync_binlog                    = 1

# ────── 组提交调优（高并发写入场景） ──────
binlog_group_commit_sync_delay          = 0     # 先保守，压测后再调
binlog_group_commit_sync_no_delay_count = 0

# ────── 死锁排查 ──────
innodb_print_all_deadlocks     = ON
```

**关键：`redolog` 和 `binlog` 的空间要监控**。binlog 写满磁盘是生产事故第一名（尤其是 `binlog_format=ROW` + 大批量更新）。
:::

:::拓展
**`innodb_flush_log_at_trx_commit` 与 `sync_binlog` 的组合对照**

| `innodb_flush_log_at_trx_commit` | `sync_binlog` | 崩溃丢数据 | 性能 | 场景 |
|---|---|---|---|---|
| **1** | **1** | **不丢**（单机） | 最差 | 金融、订单、支付 |
| 1 | 0 | redo 不丢，但 binlog 可能丢 → **主从不一致** | 中 | ⚠️ 危险组合，不要用 |
| 2 | 1 | OS 崩溃丢 1 秒 | 中 | 一般业务 |
| 0 | 0 | 最多丢 1 秒 | 最好 | 日志、监控数据、可重算的数据 |

**「双 1」是生产默认配置**。如果要压榨性能，**先确认业务能否容忍丢 1 秒数据**，再考虑降级。

**MySQL 8.0.30+ 的 redo log 变化**

```sql
-- 8.0.30 起，innodb_log_file_size 和 innodb_log_files_in_group 被 deprecated
-- 统一用 innodb_redo_log_capacity 控制总容量（默认 100M）
SHOW VARIABLES LIKE 'innodb_redo_log_capacity';   -- 104857600（100M）

-- 在线调整容量（无需重启！这是 8.0.30 的一大改进）
SET GLOBAL innodb_redo_log_capacity = 4294967296; -- 4G

-- redo 文件现在是一组 32 个文件（放在 #innodb_redo 目录下）
SELECT * FROM performance_schema.innodb_redo_log_files\G
-- FILE_ID / FILE_NAME / START_LSN / END_LSN / SIZE_IN_BYTES / IS_FULL / CONSUMER_LEVEL
```

**`mysqlbinlog` 的实用姿势（数据恢复必备）**

```bash
# ① 把 binlog 解析成可读 SQL
mysqlbinlog --base64-output=DECODE-ROWS -v binlog.000001 > decoded.sql

# ② 按时间范围导出（误删数据后的恢复）
mysqlbinlog --start-datetime="2026-09-18 10:00:00" \
            --stop-datetime="2026-09-18 10:30:00" \
            binlog.000001 > recovery.sql

# ③ 按 position 范围导出（精确到误操作前后）
mysqlbinlog --start-position=1234 --stop-position=5678 binlog.000001 > recovery.sql

# ④ 直接管道回放（跳过误操作的 position）
mysqlbinlog --stop-position=1234 binlog.000001 | mysql -uroot -p
# （先恢复到误操作前，再跳过误操作，从之后的位置继续）
mysqlbinlog --start-position=5678 binlog.000001 | mysql -uroot -p

# ⑤ 按库过滤
mysqlbinlog --database=your_db binlog.000001 > recovery.sql
```

**这就是「误删数据怎么恢复」的标准答案**：`binlog` + 全量备份。**前提是 binlog 没被删——所以 `binlog_expire_logs_seconds` 不能设太小。**

**CDC（Change Data Capture）：binlog 的另一个大用途**

```text
业务库 ──写──► binlog ──► Debezium / Canal ──► Kafka ──► 下游系统
                        （伪装成从库拉 binlog，解析成事件）           ├─ 搜索索引（ES）
                                                                      ├─ 缓存刷新（Redis）
                                                                      └─ 数仓（ClickHouse/Hive）
```

```ini
# canal 的核心配置（伪装成 MySQL 从库）
canal.instance.master.address=127.0.0.1:3306
canal.instance.dbUsername=canal
canal.instance.dbPassword=canal
canal.instance.filter.regex=your_db\\..*     # 只订阅指定库
canal.instance.filter.black.regex=your_db\\.log_.*  # 排除日志表
```

**`canal` / `Debezium` 需要 `binlog_format = ROW` 且 `binlog_row_image = FULL`**（MINIMAL 会导致解析不到完整的前像）——这是配置 CDC 时最容易踩的坑。
:::

:::追问
**Q：为什么 redo log 是循环写，binlog 是追加写？**
因为**职责不同**：
- redo log 是**崩溃恢复用的，只需覆盖「尚未刷盘的那一段」**——一旦脏页刷盘了（checkpoint 推进），对应的 redo 就没有价值了，可以覆盖。所以用固定大小的环形结构，节省空间。
- binlog 是**复制和归档用的，需要保留完整历史**（从库可能滞后很久、需要做时间点恢复），所以只能追加，靠 `max_binlog_size` 滚动文件、靠过期时间删除。

**Q：`innodb_log_file_size` 调大有什么好处和坏处？**
**好处**：checkpoint 可以更晚推进 → 脏页刷盘更从容 → 写入更平稳（减少 `innodb_log_waits`）；崩溃恢复需要重放的范围更大——**但恢复时间也变长**。
**坏处**：崩溃恢复时间变长（要重放更多）；占用磁盘更多。
**权衡**：**不要超过 1~2 小时的写入量**，同时保证崩溃恢复能在可接受时间内完成（一般要求 < 30 分钟）。

**Q：为什么 `binlog_format=STATEMENT` 在 RC 下会主从不一致？**
经典例子：
```sql
-- 主库执行
DELETE FROM t WHERE status = 2 LIMIT 1;
```
STATEMENT 格式下，从库重放**同样的 SQL**。**但主从上 `status=2` 的行的物理顺序可能不同**（尤其是 RC 下不加间隙锁，主库上并发插入的行顺序和从库重放时不同），导致 `LIMIT 1` 删掉的是**不同的行**。
**ROW 格式记录的是「删了 id=100 这一行」**，从库直接按 id 删，不存在歧义。**这就是为什么要默认 ROW。**

**Q：两阶段提交能完全避免主从不一致吗？**
**能避免「崩溃导致的主从不一致」，但不能避免所有主从不一致**。仍可能不一致的场景：
① **异步复制下主库宕机，binlog 还没传到从库** → 从库缺数据（这不是两阶段的锅，是复制的锅）；
② **`binlog_row_image = MINIMAL` + 某些恢复场景** → 信息不足；
③ **从库手动写数据 / 从库执行了 `SET sql_log_bin=0`** → 人为破坏；
④ **从库重放过程中崩溃 + `relay_log_recovery` 关闭** → 中继日志损坏。
**两阶段提交解决的是「主库自己」的 redo 与 binlog 一致性问题，是必要条件不是充分条件。**

**Q：组提交能完全解决 fsync 的性能问题吗？**
不能完全。组提交的效果取决于**并发度**：并发越高，能合并的事务越多，效果越好。**单连接串行提交时组提交没有收益**（每次只有 1 个事务）。所以高并发写入场景，**用连接池提高并发 + 组提交**是配套的。
:::

:::锚点
**RRM 项目的技术栈里有 Kafka——这是这道题最好的落点，因为 Kafka 和 MySQL 在「日志」这件事上设计思想高度一致。**

对照表：

| 概念 | MySQL | Kafka |
|---|---|---|
| 写入模型 | **WAL**：先写 redo log，后写数据页 | **顺序追加**：只追加到 partition 末尾 |
| 日志结构 | redo log 循环写；binlog 追加写 | 追加写（segment 滚动） |
| 消费位点 | binlog 的 GTID / position | consumer offset |
| 归档策略 | `binlog_expire_logs_seconds` | `log.retention.hours` / `log.retention.bytes` |
| 复制 | 主从 binlog 复制 | partition 副本（ISR 机制） |
| 一致性级别 | `innodb_flush_log_at_trx_commit` | `acks=0/1/all` |
| 组提交 | group commit 合并 fsync | **`linger.ms` + `batch.size` 合并发送** |

**面试话术**：

> 「三大日志我理解得比较清楚，而且我在 RRM 项目里用 Kafka 做过数据链路，两边在『用日志换顺序写性能』这件事上的设计思想是共通的。

> MySQL 这边：**redo log 是 InnoDB 的物理日志，采用 WAL——先写日志再刷数据页，这样把随机的页写入变成了顺序的日志写入；它循环写，因为一旦脏页刷盘（checkpoint 推进），对应的 redo 就没用了，可以覆盖。binlog 是 Server 层的逻辑日志，追加写，用于主从复制和时间点恢复。undo log 记录反向操作，既用于回滚，也是 MVCC 版本链的载体。**

> **两阶段提交是为了让 redo log 和 binlog 保持一致**：先写 redo 并标记 prepare，再写 binlog，最后把 redo 标记成 commit。崩溃恢复时**用 binlog 是否完整来裁决**——binlog 完整就提交，不完整就回滚。如果不做两阶段提交，崩溃后会出现『主库有从库没有』或者『从库有主库没有』。

> 落到 Kafka 的类比：**redo log 的『先写日志再刷数据页』和 Kafka 的『只追加不修改』是同一个思路——把随机写变成顺序写。而两阶段提交解决的一致性问题，在 Kafka 那边对应的是 `acks=all` + ISR 机制。** 我做过 RRM 里 rrmcompute 和下游之间的数据传递，用的就是 Kafka，对『消息什么时候算真正落盘、消费位点怎么保证不丢不重』这些问题有过实际的调试经历。」

**注意**：讲 Kafka 时只讲你真实做过的（RRM 里用 Kafka 传数据是真实的）。**不要把 Kafka 的经验包装成「我调过 MySQL 的组提交参数」**。
:::

## 14. InnoDB 与 MyISAM 的区别

:::概念
**InnoDB：支持事务、行级锁、外键、崩溃恢复，是 5.5+ 的默认引擎，也是唯一值得用的引擎。**
**MyISAM：表级锁、不支持事务、不支持崩溃恢复（也谈不上恢复），只在极少数「只读、不要事务、数据能整体重建」的场景还有一点价值。**
记忆钩子：**「InnoDB 有事务 + 行锁 + redo，MyISAM 一个都没有，但它 count(\*) 快、索引文件小」。**
:::

:::提问
- InnoDB 和 MyISAM 有什么区别？
- 现在还会用 MyISAM 吗？什么场景？
- 为什么 MyISAM 的 `count(*)` 快？
- 怎么查看一张表用的是什么引擎？
- 怎么把 MyISAM 表转成 InnoDB？
:::

:::答案
### 一、核心差异全表

| 维度 | **InnoDB** | **MyISAM** |
|---|---|---|
| **事务** | ✅ 支持 ACID | ❌ 不支持 |
| **锁粒度** | **行级锁**（+ 间隙锁） | **表级锁**（读共享、写排他） |
| **外键** | ✅ 支持 | ❌ 不支持（语法接受但忽略） |
| **崩溃恢复** | ✅ **redo log 恢复** | ❌ 数据损坏后需要 `myisamchk` 修表，且可能丢数据 |
| **MVCC** | ✅ 支持 | ❌ 不支持 |
| **索引结构** | **聚簇索引**（数据即索引） | **非聚簇**（索引和数据文件分离） |
| **主键要求** | 建议显式定义；无主键会用隐藏 ROW_ID | 无强制要求 |
| **`count(*)`** | **慢**（需扫描，见第 15 题） | **快**（保存了行数元数据） |
| **全文索引** | 5.6+ 支持 | 早期就支持（现在无优势） |
| **压缩表** | 支持（`ROW_FORMAT=COMPRESSED`） | 支持（`myisampack`，只读压缩，效果好） |
| **数据文件** | `.ibd`（独立表空间）或 `ibdata1`（共享） | `.frm`（表定义）+ `.MYD`（数据）+ `.MYI`（索引） |
| **空间索引** | 5.7+ 支持（R 树） | 支持 |
| **并发能力** | **高**（行锁，读写不互斥） | **低**（写会阻塞所有读） |
| **适用场景** | **几乎所有 OLTP 场景** | 只读的历史归档表、数据仓库的只读维表（现在一般用列存替代） |

### 二、MyISAM 的 `count(*)` 为什么快

MyISAM 在数据文件头（`.MYD`）里**保存了一个整数，记录表的行数**。

```sql
-- MyISAM 的 count(*) 是 O(1)
SELECT COUNT(*) FROM myisam_table;   -- 直接读元数据返回
```

**为什么 InnoDB 不这么做**：
**InnoDB 有 MVCC，不同事务在同一时刻能看到的行数可能不同。**

```text
时刻 T：
  事务 A（已提交，插入了 100 行）→ 能看到 10000 行
  事务 B（未提交，插入了 50 行）→ 能看到 10050 行（自己插的可见）
  事务 C（RR，ReadView 在 A 提交前创建）→ 能看到 9900 行

——「表有多少行」这个问题在 InnoDB 里没有一个全局答案，
   必须针对「哪个事务、哪个时刻」分别计算，所以只能扫。
```

**这也是为什么 `SHOW TABLE STATUS` 的 `Rows` 列在 InnoDB 里是估算值**：

```sql
-- InnoDB：Rows 是估算值，可能有很大偏差
SHOW TABLE STATUS LIKE 't_order'\G
-- Rows: 9823456    ← 估算，不是精确值

-- MyISAM：Rows 是精确值
```

### 三、查看和转换引擎

```sql
-- ① 查看某张表的引擎
SHOW TABLE STATUS LIKE 't_order'\G
SELECT TABLE_NAME, ENGINE, TABLE_ROWS, ROW_FORMAT
FROM information_schema.TABLES
WHERE TABLE_SCHEMA = 'your_db';

-- ② 查看默认引擎
SHOW VARIABLES LIKE 'default_storage_engine';   -- InnoDB

-- ③ 查看实例里还有多少 MyISAM 表（上线前体检）
SELECT ENGINE, COUNT(*) AS table_count
FROM information_schema.TABLES
WHERE TABLE_SCHEMA NOT IN ('mysql','information_schema','performance_schema','sys')
GROUP BY ENGINE;

-- ④ 创建时指定引擎
CREATE TABLE t_x (...) ENGINE=InnoDB;

-- ⑤ MyISAM 转 InnoDB（会锁表，大表必须用 gh-ost / pt-online-schema-change）
ALTER TABLE t_x ENGINE=InnoDB;
-- 或者先导出再导入
-- mysqldump -uroot -p your_db t_x > t_x.sql
-- 改 SQL 里的 ENGINE=MyISAM 为 ENGINE=InnoDB，再导入

-- ⑥ 检查转换后是否有外键/事务相关的问题
SELECT * FROM information_schema.REFERENTIAL_CONSTRAINTS WHERE CONSTRAINT_SCHEMA='your_db';
```

**⚠️ `ALTER TABLE ... ENGINE=InnoDB` 会重建整张表**：大表上执行会长时间锁表 + 占用大量磁盘（重建期间新旧表共存）。**生产必须用在线 DDL 工具**：

```bash
# pt-online-schema-change（Percona Toolkit）
pt-online-schema-change \
  --alter "ENGINE=InnoDB" \
  D=your_db,t=t_x \
  --execute

# gh-ost（GitHub 开源，更灵活，支持暂停/限流）
gh-ost \
  --database=your_db --table=t_x \
  --alter="ENGINE=InnoDB" \
  --host=127.0.0.1 --user=root --password=xxx \
  --allow-on-master --execute
```

### 四、为什么现在几乎不该用 MyISAM

| 理由 | 说明 |
|---|---|
| **没有事务** | 业务里只要有「要么全成功要么全回滚」的需求，MyISAM 直接不可用 |
| **表级锁** | 一次写入会阻塞整张表的所有读——在高并发下等于串行 |
| **崩溃会丢数据/损坏** | 断电后 `.MYD` 可能损坏，需要手动 `myisamchk -r` 修复，且不能保证完整恢复 |
| **MySQL 5.5 起默认就是 InnoDB** | 官方路线已经明确 |
| **InnoDB 的 `count(*)` 劣势可以绕开** | 用计数表、Redis 计数、或 `LIMIT n+1` 判断 |
| **MyISAM 的全文索引优势已消失** | InnoDB 5.6+ 也支持全文索引；真正的文本检索应该用 ES |

**唯一还剩一点价值的场景**：**只读的历史归档表**（数据一次性导入、之后只查不写），此时 MyISAM 的表级锁不构成问题，索引文件也小。**但即使这样，也通常用 InnoDB + 只读从库更安全。**

### 五、引擎的横向扩展：还有哪些引擎

| 引擎 | 特点 | 用途 |
|---|---|---|
| **InnoDB** | 事务、行锁、MVCC、聚簇索引 | **默认，99% 场景** |
| MyISAM | 表锁、无事务、count 快 | 基本淘汰 |
| **Memory** | **数据在内存**（重启丢）、哈希索引、表锁 | 临时表、会话数据（**几乎被 Redis 替代**） |
| **Archive** | 高压缩比（10:1）、只支持 `INSERT` 和 `SELECT` | 日志归档（**已被 ClickHouse 等替代**） |
| **CSV** | 数据存成 CSV 文件 | 数据交换（**`mysql.slow_log` 用的就是它**） |
| **NDB (Cluster)** | 内存 + 分布式、高可用 | 电信级场景，极少见 |
| **RocksDB** | LSM 树、写优化 | 写密集场景（MyRocks），社区版不带 |
:::

:::拓展
**`ROW_FORMAT`：InnoDB 的行格式（比引擎更容易被追问）**

```sql
SHOW VARIABLES LIKE 'innodb_default_row_format';   -- 默认 DYNAMIC（8.0 / 5.7）
SHOW TABLE STATUS LIKE 't_order'\G                 -- 看 Row_format 列
```

| 行格式 | BLOB/TEXT 存法 | 特点 |
|---|---|---|
| `COMPACT`（5.6 前默认） | 前 768 字节存在行内，其余溢出页 | 行内数据多 |
| `REDUNDANT` | 老格式 | 已废弃 |
| **`DYNAMIC`**（5.7+ 默认） | 全部存在溢出页，行内只留 20 字节指针 | **行更短 → 单页放更多行 → 树更矮**；支持大索引前缀 |
| `COMPRESSED` | 同 DYNAMIC + 页压缩 | 省空间但 CPU 开销大，写入变慢 |

**`DYNAMIC` 的实际收益**：一个含 `TEXT` 列的表，`COMPACT` 下每行至少 768 字节被 TEXT 占着；`DYNAMIC` 下只剩 20 字节指针 → 单页能放的行数可能翻几倍 → 同样的查询扫的页更少。

```sql
-- 转换行格式（8.0 支持 INSTANT 算法的部分场景，但行格式转换一般需要重建表）
ALTER TABLE t_order ROW_FORMAT=DYNAMIC;
```

**索引前缀长度限制与行格式有关**

```sql
-- DYNAMIC/COMPRESSED：索引前缀最长 3072 字节
-- COMPACT/REDUNDANT：最长 767 字节
-- utf8mb4 下 3072 / 4 = 768 个字符
ALTER TABLE t_user ADD KEY idx_big (name(768));   -- DYNAMIC 下可以
```

**`innodb_file_per_table`：独立表空间**

```sql
SHOW VARIABLES LIKE 'innodb_file_per_table';   -- 默认 ON（5.6.6+）
```

| 值 | 数据存哪 | 优点 | 缺点 |
|---|---|---|---|
| **ON（默认）** | 每表一个 `.ibd` 文件 | **`DROP TABLE` 能立刻释放磁盘**；单表可 `OPTIMIZE`；可 `TRANSPORTABLE TABLESPACE` | 文件多 |
| OFF | 全部存在共享 `ibdata1` | 文件少 | **`DROP TABLE` 不释放空间**（ibdata1 只增不减）；无法单表操作 |

**生产必须保持 ON** —— 这是 `DELETE` 之后磁盘空间不释放问题的分界线。
:::

:::追问
**Q：InnoDB 的表一定会有主键吗？**
逻辑上一定会有**聚簇索引**（可能是隐式的 `DB_ROW_ID`），但不一定有显式的 `PRIMARY KEY`。**选聚簇索引的顺序**：显式主键 → 第一个全 NOT NULL 的唯一索引 → 隐藏的 `DB_ROW_ID`。**生产必须显式定义主键**，因为 `DB_ROW_ID` 是全局共享的递增计数器，高并发插入时会成为热点。

**Q：MyISAM 的表级锁是什么行为？**
- `SELECT` 加**读锁**（共享）：多个读可以并发。
- `INSERT`/`UPDATE`/`DELETE` 加**写锁**（排他）：**写会阻塞所有读和写**。
- 还有「**并发插入**」优化：表中间没有空洞时，允许 `SELECT` 和 `INSERT` 并发（但 `UPDATE`/`DELETE` 不行）。

**这在实际业务里的表现是：一张 MyISAM 表只要有写入，查询就会被卡住**——这是它被淘汰的核心原因。

**Q：`OPTIMIZE TABLE` 在两种引擎上行为一样吗？**
不一样：
- **MyISAM**：等价于 `myisamchk -r`，重建表、整理碎片、回收空间。**效果好。**
- **InnoDB**：等价于 `ALTER TABLE ... FORCE`（重建表 + 重建索引）。**能回收空间，但代价大（锁表 + 占双倍磁盘）。**

```sql
-- InnoDB 回收空间更推荐这个（8.0 支持在线，但仍有代价）
ALTER TABLE t_order ENGINE=InnoDB;   -- 重建表，回收碎片
-- 或者用 gh-ost / pt-online-schema-change 在线做
```

**注意：InnoDB 的 `DELETE` 不会把空间还给操作系统**（只标记为可复用，`DATA_FREE` 增大）。要真正缩小 `.ibd` 文件，必须重建表。

**Q：临时表用什么引擎？**
`CREATE TEMPORARY TABLE` 默认用 `default_tmp_storage_engine`（默认 InnoDB）。**MySQL 8.0 起内部临时表默认用 TempTable 引擎（内存 + 溢出到磁盘）**，比 5.7 的 Memory/MyISAM 组合更高效。

```sql
SHOW VARIABLES LIKE 'default_tmp_storage_engine';   -- InnoDB
SHOW VARIABLES LIKE 'internal_tmp_mem_storage_engine'; -- TempTable（8.0）
SHOW VARIABLES LIKE 'temptable_max_ram';            -- 默认 1G（8.0）
```
:::

:::锚点
**这道题对你有一个非常真实的落点：你在 RRM 里做过 MySQL 与 PostgreSQL 的兼容适配工作。**

**面试话术**：

> 「引擎这块我在生产上主要是原理层面的理解。MySQL 我用得最多的是补课和适配，主力存储是 MongoDB。

> 不过我的适配工作里有一个相关的体会：**InnoDB 是 MySQL 唯一值得用的引擎，因为它有事务和行级锁**。我是从另一个角度理解这件事的——**做 MySQL 和 PostgreSQL 兼容时，最大的差异之一就是『MySQL 的引擎能力是不统一的』**：同样的 DDL 在不同引擎上行为不同（`DROP TABLE` 能不能回滚、`count(*)` 快不快），而 PostgreSQL 只有一种存储引擎（Heap），行为完全统一，没有这种「同一个 SQL 在不同引擎上语义不同」的不确定性。

> 所以我在写兼容层的时候，会刻意避开那些依赖引擎特性的写法，比如不依赖 `count(*)` 的性能差异做设计，也不依赖 MyISAM 表级锁来做并发控制——**只依赖 InnoDB 的通用能力。**」

**不要编造「我把生产表从 MyISAM 迁到 InnoDB」的经历**。上面这段话讲的是真实的适配工作 + 从差异中产生的理解，安全且有说服力。
:::

---

## 15. `count(*)` / `count(1)` / `count(col)` / `count(主键)`

:::概念
**结论先行**：
1. **`count(*)` 和 `count(1)` 在 InnoDB 里性能完全一样**（8.0 优化器把它们优化成同一个执行计划），**都不取值**。
2. **`count(主键)` 也很快**（主键非空，不用判 NULL，但依然要遍历）。
3. **`count(col)` 最慢**——如果 `col` 可空，InnoDB 必须**取出每一行的 `col` 值判断是不是 NULL**，无法用「偷懒」的优化。
4. 语义差异：**`count(*)` / `count(1)` / `count(主键)` 统计所有行；`count(col)` 只统计 `col` 非 NULL 的行。**
5. **InnoDB 的 `count(*)` 慢不是「实现不好」，是 MVCC 导致的必然代价。**
:::

:::提问
- `count(*)` 和 `count(1)` 哪个快？
- `count(*)` 和 `count(col)` 有什么区别？
- 为什么 InnoDB 的 `count(*)` 比 MyISAM 慢？
- `count(*)` 会扫描全表吗？
- 大表统计行数有什么优化手段？
:::

:::答案
### 一、四种写法的语义差异（先搞清楚「统计什么」）

```sql
-- 建表
CREATE TABLE t_cnt (
  id   BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
  a    INT    NOT NULL,
  b    INT    NULL,          -- 可为 NULL
  KEY idx_a (a),
  KEY idx_b (b)
);
INSERT INTO t_cnt (a, b) VALUES (1, 10), (2, NULL), (3, 30), (4, NULL);

-- 验证语义差异
SELECT
  COUNT(*)    AS c_star,      -- 4  ← 所有行（含 b 为 NULL 的行）
  COUNT(1)    AS c_1,         -- 4  ← 同上
  COUNT(id)   AS c_pk,        -- 4  ← 主键非空，等于所有行
  COUNT(b)    AS c_b,         -- 2  ← 只数 b 非 NULL 的行！
  COUNT(a)    AS c_a          -- 4  ← a 是 NOT NULL，等于所有行
FROM t_cnt;
```

**关键**：

| 写法 | 统计范围 | 是否可能小于总行数 |
|---|---|---|
| `count(*)` | **所有行** | ❌ 不会 |
| `count(1)` | 所有行 | ❌ 不会 |
| `count(主键)` | 所有行（主键非空） | ❌ 不会 |
| `count(NOT NULL 列)` | 所有行 | ❌ 不会 |
| **`count(可空列)`** | **只统计该列非 NULL 的行** | ✅ **会！** |

```sql
-- 常见业务 bug：用可空列做 count 导致数字对不上
SELECT COUNT(phone) FROM t_user;     -- 有 phone 为 NULL 的用户 → 少算了
SELECT COUNT(*)     FROM t_user;     -- 正确
-- 或者用 count(distinct)
SELECT COUNT(DISTINCT b) FROM t_cnt; -- 2（去重后）
```

### 二、性能差异：InnoDB 内部的执行方式

| 写法 | 优化器怎么做 | 相对性能 |
|---|---|---|
| **`count(*)`** | 选**最小的可用索引**遍历，**不读取任何列值**，只累加行数 | **最快** |
| **`count(1)`** | 同 `count(*)`（8.0 里被优化成同一执行计划） | **一样快** |
| **`count(主键)`** | 遍历聚簇索引（或最小索引），取主键值（非空判断可省略） | 快（比 `count(*)` 略慢，因为要取值） |
| **`count(a)`（a 是 NOT NULL 且有索引）** | 遍历 `idx_a`，取 a 值（非空可省略） | 与 `count(主键)` 相当 |
| **`count(b)`（b 可空）** | **必须取出 b 的值，逐行判断 `IS NOT NULL`** | **最慢** |

```sql
-- 用 EXPLAIN 看执行计划（Extra 会显示 Using index 表示走覆盖索引）
EXPLAIN SELECT COUNT(*)  FROM t_cnt;   -- key: idx_a（最小的索引）  Extra: Using index
EXPLAIN SELECT COUNT(1)  FROM t_cnt;   -- key: idx_a              Extra: Using index
EXPLAIN SELECT COUNT(id) FROM t_cnt;   -- key: idx_a              Extra: Using index
EXPLAIN SELECT COUNT(b)  FROM t_cnt;   -- key: idx_b              Extra: Using index
```

**注意**：`EXPLAIN SELECT COUNT(*)` 里的 `rows` 就是估算的总行数，`type=index`。

### 三、为什么 InnoDB 的 `count(*)` 不能 O(1)

**核心原因：MVCC。**

```text
MyISAM：没有 MVCC，全表只有一份数据，行数是一个全局确定的数字
        → 在数据文件头存一个整数 → count(*) 直接返回 O(1)

InnoDB：有 MVCC，同一时刻不同事务看到的行数可能不同
        事务 A（已提交插入 100 行）→ 看到 10000 行
        事务 B（未提交插入 50 行）  → 看到 10050 行
        事务 C（ReadView 早于 A）   → 看到 9900 行
        → 「表有多少行」没有全局答案，必须按事务+时刻计算 → 只能扫
```

**所以 InnoDB 的优化不是「省掉扫描」，而是「让扫描尽量便宜」**：

1. **选最小的二级索引遍历**：二级索引叶子存的是「索引列 + 主键」，比聚簇索引叶子（整行）小得多 → 同样的行数，扫的页更少
2. **不取值**：`count(*)` 只累加计数器，不读取列值 → 省掉解包行的开销
3. **覆盖索引**：`Extra: Using index` 表示完全没有回表

**`SHOW TABLE STATUS` 的 `Rows` 是采样估算值**，可以拿来做近似统计（误差可能 10%+）：

```sql
SELECT TABLE_NAME, TABLE_ROWS
FROM information_schema.TABLES
WHERE TABLE_SCHEMA = 'your_db' AND TABLE_NAME = 't_order';
-- TABLE_ROWS 是估算值（默认采样 20 个页推算），偏差可能很大
```

### 四、大表统计行数的优化方案

| 方案 | 精度 | 性能 | 适用 |
|---|---|---|---|
| **`SELECT COUNT(*)`** | 精确 | 慢（O(n)） | 小表、低频场景 |
| **`SHOW TABLE STATUS` / `information_schema.TABLES`** | 估算（误差可能 10%+） | O(1) | 展示用（如"约 1.2 万条"） |
| **`LIMIT n+1` 判断有无下一页** | 页级精确 | 快 | 列表页「是否有更多」 |
| **计数表（单独一张表存计数）** | 精确 | O(1) | 高频读、允许最终一致 |
| **Redis 计数器** | 精确（Redis 可靠时） | O(1) | 高频读，可容忍不一致 |
| **近似值 + 定期精确校准** | 准精确 | 快 | 大规模展示场景 |

**计数表的实现（经典方案）**：

```sql
CREATE TABLE t_order_count (
  status   TINYINT PRIMARY KEY,
  cnt      BIGINT NOT NULL DEFAULT 0,
  updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
) ENGINE=InnoDB;

-- 应用层在事务里同步维护
START TRANSACTION;
INSERT INTO t_order (user_id, status, amount) VALUES (1001, 2, 99.00);
UPDATE t_order_count SET cnt = cnt + 1 WHERE status = 2;   -- 同事务内，保证一致
COMMIT;

-- 查询 O(1)
SELECT cnt FROM t_order_count WHERE status = 2;
```

**注意**：所有行的计数都更新到一行，会造成**热点行争用**（所有事务抢同一行锁）。**处置**：① 按 `status` 分行（不同状态不冲突）；② 或者用一个 `slot` 列取模打散成 N 行再 `SUM`。

**`LIMIT n+1` 方案（列表页最实用）**：

```sql
-- 不用 count，只判断「有没有下一页」
SELECT id, order_no FROM t_order WHERE status = 2 ORDER BY id LIMIT 21;
-- 应用层：返回前 20 条，rows.size() > 20 → hasMore = true
-- 好处：完全避免 count(*) 的全扫；坏处：拿不到精确总数
```

**Redis 计数方案**：

```
写路径：业务事务提交后 → 发 Kafka 消息 或 直接 INCR
       （推荐：binlog → canal → Redis INCR，与业务解耦，且天然最终一致）
读路径：GET order:count:status:2
校准：每天低峰期跑一次精确 count，覆盖 Redis 的值
```

**⚠️ 不要用触发器维护计数表**：触发器会隐式加入事务，增大事务范围和锁冲突，而且容易和批量操作（`LOAD DATA`、`INSERT ... SELECT`）产生意外行为。**用 binlog + canal 或应用层双写更可控。**

### 五、完整对照表（背下来）

| 写法 | 语义 | 能否用覆盖索引 | 是否取值 | 性能 |
|---|---|---|---|---|
| `count(*)` | 所有行 | ✅（最小索引） | ❌ 不取值 | **最快** |
| `count(1)` | 所有行 | ✅ | ❌ 不取值 | **= count(\*)** |
| `count(主键)` | 所有行 | ✅ | ✅ 取主键 | 略慢 |
| `count(NOT NULL 列)` | 所有行 | ✅（该列有索引时） | ✅ 取该列 | 略慢 |
| `count(可空列)` | **非 NULL 行** | ✅ | ✅ **取该列 + 判 NULL** | **最慢** |
| `count(distinct col)` | 去重后的非 NULL 值个数 | 可能用临时表 | ✅ | 慢，且可能有 `Using temporary` |
:::

:::拓展
**「`count(1)` 比 `count(*)` 快」是一个流传极广的误解**

```sql
-- 在 MySQL 8.0 里，这两条的执行计划完全一致
EXPLAIN FORMAT=JSON SELECT COUNT(*) FROM t_order\G | grep -E "key|used_key_parts"
EXPLAIN FORMAT=JSON SELECT COUNT(1) FROM t_order\G | grep -E "key|used_key_parts"
-- 输出完全相同
```

**历史来源**：MySQL 5.5 及更早版本里，`count(*)` 的实现路径和 `count(1)` 有细微差异，某些版本下 `count(1)` 略快。**但 5.6 之后优化器统一了处理，现在完全一样。**

**面试时的正确回答**：**「8.0（以及 5.6+）里 `count(*)` 和 `count(1)` 的执行计划完全一致，性能没有差别。真正有差别的是 `count(可空列)`，因为它必须取值判断 NULL。」**

**`count(*)` 的 `rows` 也能复用**

```sql
-- 优化器有时能直接给出结果（当表非常小且统计信息足够时）
EXPLAIN SELECT COUNT(*) FROM t_cnt;
-- rows 列就是估算的总行数，不需要真的执行

-- 对比
SELECT COUNT(*) FROM t_cnt;   -- 真正执行
```

**`count(*)` 与 `SQL_CALC_FOUND_ROWS`（已废弃）**

```sql
-- 老写法（不要用！MySQL 8.0.17 起已废弃）
SELECT SQL_CALC_FOUND_ROWS id, order_no FROM t_order WHERE status = 2 LIMIT 20;
SELECT FOUND_ROWS();
```

**为什么废弃**：`SQL_CALC_FOUND_ROWS` 为了返回总数，**必须扫描所有满足条件的行**（不能因为 `LIMIT` 而提前结束），代价和单独跑一个 `count(*)` 一样，但**额外增加了不确定性和优化器限制**。**正确做法：要么单独跑 `count(*)`，要么用 `LIMIT n+1` 判断 hasMore。**
:::

:::追问
**Q：`SELECT COUNT(*) FROM t` 在 InnoDB 里会扫全表吗？**
会扫「全部索引记录」，但**不会扫聚簇索引的数据页**。优化器会选**最小的那个二级索引**遍历，因为它只存「索引列 + 主键」，页数最少。所以 `EXPLAIN` 里 `key` 是某个二级索引，`Extra: Using index`。

**如果表上没有任何二级索引**，就只能扫聚簇索引（代价大得多）。**表上有一个很窄的二级索引，对 `count(*)` 是有明显帮助的。**

**Q：`count(*)` 和 `count(id)` 哪个快？**
理论上 **`count(*)` 略快**，因为它不需要取出 `id` 的值再判断非空；`count(id)` 要读每一行的 `id`。但差距很小（都是覆盖索引扫描）。**实际选择以语义清晰为准**——统计总数就用 `count(*)`，这是 SQL 标准规定的语法。

**Q：`count(distinct *)` 可以吗？**
**不可以**，语法错误。`count(distinct expr)` 只能跟单个表达式，`count(distinct col1, col2)` 在 MySQL 里也支持（多列去重），但 `count(distinct *)` 是语法错误。

```sql
SELECT COUNT(DISTINCT b) FROM t_cnt;            -- ✅
SELECT COUNT(DISTINCT a, b) FROM t_cnt;         -- ✅ MySQL 支持多列去重
SELECT COUNT(DISTINCT *) FROM t_cnt;            -- ❌ 语法错误
```

**Q：为什么我 `count(*)` 很快，别人说很慢？**
因为**表的大小不同**。10 万行的 `count(*)` 走覆盖索引可能只要 10ms；1000 万行要几秒。**感知差异来自数据量级，不是实现差异。**

**判据**：`count(*)` 的耗时 ≈ `(总行数 / 每页行数) × 页读取时间`。走覆盖索引时每页能放几百个索引项，所以百万行也就几千页。

**Q：分页场景「总数 + 当页数据」应该怎么做？**
四种方案按推荐度：
1. **`LIMIT n+1` 判断是否有下一页**（不显示总页数，适合 feed 流）← **最优**
2. **单独的 `count(*)` 走覆盖索引**（需要精确总数，且表不太大）
3. **计数表 / Redis**（需要精确总数，且高频调用）
4. **近似值**（只需要「约 1.2 万条」这种展示）

**实战建议**：先问产品「用户真的需要精确的总页数吗」。**大多数列表页其实只需要「有没有下一页」，这一个问题就能省掉全表扫描。**
:::

:::锚点
**这道题有一个很自然的切入点：你在 MongoDB 上用过 `count_documents` 和 `estimatedDocumentCount`，两者正好对应 MySQL 的精确 count 和估算 count。**

```javascript
// MongoDB 的两种计数
db.clbDetail.estimatedDocumentCount()                       // 读元数据，O(1)，但是估算
db.clbDetail.countDocuments({ taskId: "T001" })             // 精确，走索引但要扫描
db.clbDetail.countDocuments({ taskId: "T001" }, { hint: "taskId_1_apSN_1_RI_1" })  // 指定索引

// 关键：countDocuments 会走索引，estimatedDocumentCount 不看查询条件
// → estimatedDocumentCount 不能带查询条件！
```

**面试话术**：

> 「`count` 这个点我在 MongoDB 上有实操对应。MongoDB 里有两个计数 API：**`estimatedDocumentCount()` 读的是元数据，O(1) 但只能给全集合的估算值，不能带查询条件；`countDocuments()` 是精确计数，会走索引扫描。** 这跟 MySQL 里 `SHOW TABLE STATUS` 的 `Rows`（估算）和 `SELECT COUNT(*)`（精确）是完全对应的一组概念。

> InnoDB 的 `count(*)` 为什么慢，我是从 MVCC 角度理解的：**因为没有 MVCC 的 MyISAM 可以在文件头存一个整数，而 InnoDB 里不同事务在同一时刻看到的行数可能不一样——比如一个未提交的事务插入了 50 行，它自己能看到这 50 行，别人的 ReadView 看不到。所以『表有多少行』在 InnoDB 里根本没有一个全局答案，只能按事务和时刻去算。** 优化器能做的只是『选最小的二级索引遍历 + 不取值』，把扫描变便宜，而不是消灭扫描。

> `count(*)` 和 `count(1)` 性能相同的这个结论我确认过——8.0 里两者的执行计划完全一样。**真正有区别的是 `count(可空列)`，它会只统计非 NULL 的行，而且必须取出每一行的值来判断，所以最慢也最容易出业务 bug。**

> 落到工程上，我的做法是：列表页优先用 `LIMIT n+1` 判断有没有下一页，避免精确 count。**这个思路和我在 Mongo 里给 `clbDetail` 做查询优化时是一致的——能不做的全扫描就不做。**」

**加分点**：主动说出「`estimatedDocumentCount()` 不能带查询条件」这个 API 细节，能证明你真的用过而不是道听途说。
:::

---

## 16. 快照读与当前读

:::概念
**快照读（普通 `SELECT`）**：读 ReadView 可见的历史版本，**不加锁**，靠 **MVCC**。
**当前读（`SELECT ... FOR UPDATE` / `FOR SHARE` / `UPDATE` / `DELETE` / `INSERT`）**：读**最新已提交**版本并**加锁**，靠**锁机制**。
一句话记：**「MVCC 管快照读，锁管当前读」。** 这是把第 9、10、11、12 题全部串起来的那根线。
:::

:::提问
- 什么是快照读？什么是当前读？
- 哪些语句属于当前读？
- 为什么 `UPDATE` 是当前读？
- RR 下当前读加什么锁？为什么能防幻读？
- 同一事务里先快照读再当前读会怎样？
- `INSERT` 是当前读吗？它加了什么锁？
:::

:::答案
### 一、完整对照表

| 维度 | **快照读** | **当前读** |
|---|---|---|
| **语句形式** | 普通 `SELECT`（不加锁的查询） | `SELECT ... FOR UPDATE`<br>`SELECT ... FOR SHARE` / `LOCK IN SHARE MODE`<br>`UPDATE` / `DELETE` / `INSERT` |
| **读什么** | ReadView 里**可见的版本**（可能是历史版本） | **最新已提交的版本**（若被未提交事务持有锁则等待） |
| **加锁** | ❌ 不加锁 | ✅ 加锁 |
| **实现机制** | **MVCC**（undo log 版本链 + ReadView） | **记录锁 / 间隙锁 / 临键锁** |
| **是否阻塞** | 不阻塞，也不被写阻塞 | 会等锁（最长 `innodb_lock_wait_timeout`，默认 50 秒） |
| **RR 下是否防幻读** | ✅ 防（新插入行不可见） | ✅ 防（临键锁锁住区间） |
| **典型用途** | 普通业务查询 | 「先查后改」的场景（防并发覆盖） |

### 二、当前读的四种形式与加锁强度

| 语句 | 锁类型 | 阻塞其他事务的 |
|---|---|---|
| `SELECT ... FOR SHARE`（8.0）<br>`SELECT ... LOCK IN SHARE MODE`（5.7） | **共享锁（S）** | `UPDATE`/`DELETE`/`FOR UPDATE`（写操作） |
| `SELECT ... FOR UPDATE` | **排他锁（X）** | 所有加锁操作（含其他 `FOR UPDATE`） |
| `UPDATE` | **排他锁（X）**（隐式） | 同上 |
| `DELETE` | **排他锁（X）**（隐式） | 同上 |
| `INSERT` | **插入意向锁 + 可能的间隙锁**（隐式） | 与间隙锁冲突；唯一键冲突时会等待 |

```sql
-- 共享锁：多个读可以共存，但写被阻塞
START TRANSACTION;
SELECT * FROM t_order WHERE id = 1 FOR SHARE;      -- 8.0 语法
-- 另一个会话：UPDATE t_order SET amount = 1 WHERE id = 1;  → 阻塞

COMMIT;

-- 排他锁
START TRANSACTION;
SELECT * FROM t_order WHERE id = 1 FOR UPDATE;
-- 另一个会话：SELECT * FROM t_order WHERE id = 1 FOR SHARE;  → 也阻塞

COMMIT;
```

**8.0 的 `NOWAIT` / `SKIP LOCKED` 补充**：

```sql
-- NOWAIT：拿不到锁立即报错，不等 50 秒
SELECT * FROM t_order WHERE id = 1 FOR UPDATE NOWAIT;
-- ERROR 3572: Statement aborted because lock(s) could not be acquired immediately

-- SKIP LOCKED：跳过被锁定的行（做简单任务队列）
SELECT * FROM task_queue WHERE status = 0 ORDER BY id LIMIT 1 FOR UPDATE SKIP LOCKED;
```

### 三、`UPDATE` 为什么是当前读

```sql
UPDATE t_order SET status = 3 WHERE id = 100;
```

**执行过程**：

```text
① 定位 id=100 的记录 —— 这一步必须读「最新版本」
   如果读到的是旧快照（比如 status 已经被别的事务改成 9 了但还没提交），
   基于旧版本做的判断就会是错的 → 更新丢失

② 如果该记录被其他未提交事务锁定 → 等待（最长达 innodb_lock_wait_timeout）

③ 加排他锁（X）

④ 基于最新版本判断是否满足 WHERE 条件
   （RC 下还有"半一致性读"优化：不满足就直接跳过，不等锁）

⑤ 修改，并把新版本写入当前行，旧版本进 undo log
   → 新版本的 DB_TRX_ID 变成当前事务 id
```

**核心**：**`UPDATE` 必须读最新数据，否则并发更新会互相覆盖**。这是「更新丢失」问题的根源，也是必须用当前读的理由。

```sql
-- 演示更新丢失（如果用快照读实现 UPDATE 会怎样）
-- 初始：balance = 100
-- 事务 A 和 B 同时执行：
UPDATE accounts SET balance = balance + 10 WHERE id = 1;
-- 如果 A 读快照 100，算出 110；B 也读快照 100，算出 110
-- 最终 110 而不是 120 → 丢失了 A 的更新
-- 实际 InnoDB 用当前读 + 锁，B 会等 A 提交后读到 110 → 最终 120 ✅
```

### 四、RR 下当前读怎么防幻读

```sql
-- 场景：RR 隔离级别
-- 会话 A
START TRANSACTION;
SELECT * FROM t_order WHERE status = 2 FOR UPDATE;   -- 当前读，锁住 status=2 的所有范围
-- 加的是【临键锁】：(1,2] 及后续满足条件的区间

-- 会话 B
INSERT INTO t_order (status, ...) VALUES (2, ...);    -- 插入 status=2 的新行
-- 阻塞！因为插入意向锁与间隙锁冲突

-- 会话 A 提交后，B 才能插入
COMMIT;
```

**机制**：当前读加的是**临键锁**，它锁住了「范围内所有记录 + 记录之间的间隙」→ 其他事务无法在这个区间里插入新行 → 从物理上阻止了幻读。

**对比快照读**：快照读靠 ReadView 让新插入的行不可见（**逻辑上防幻读**），而当前读靠间隙锁让新行根本插不进来（**物理上防幻读**）。

```sql
-- RC 下不加间隙锁，所以会幻读
SET SESSION TRANSACTION ISOLATION LEVEL READ COMMITTED;
START TRANSACTION;
SELECT * FROM t_order WHERE status = 2 FOR UPDATE;   -- 只加记录锁，不锁间隙
-- 另一个会话可以自由 INSERT status=2 的新行
COMMIT;
```

### 五、快照读与当前读混用的经典问题

**「半幻读」场景**（第 10 题提过，这里完整走一遍）：

```sql
-- 表 t 有 id = 1, 2, 3；RR 隔离级别

-- 会话 A
START TRANSACTION;
SELECT * FROM t WHERE id > 2;                       -- 快照读，返回 id=3（1 行）

-- 会话 B
INSERT INTO t (id, name) VALUES (5, 'x');
COMMIT;

-- 会话 A 继续
UPDATE t SET name = 'y' WHERE id > 2;               -- 当前读！看到 id=3 和 id=5，两个都改了
SELECT * FROM t WHERE id > 2;                       -- 快照读，返回 id=3 和 id=5（2 行）← 幻读！
COMMIT;
```

**原因链条**：
1. 第一条 `SELECT` 创建了 ReadView（`max_trx_id` = 当时的下一个待分配 id）
2. 会话 B 的插入事务 id ≥ `max_trx_id` → 对会话 A 不可见
3. `UPDATE` 是当前读，**绕过 ReadView 直接读到最新版本**（id=5）
4. **`UPDATE` 把 id=5 这行的 `DB_TRX_ID` 改成了会话 A 自己的事务 id**
5. 第三条 `SELECT`：id=5 的 `trx_id == creator_trx_id` → **步骤 1 判定「自己的修改，可见」** → 于是看到了

**结论**：**「当前读会把别人新插入的行的 trx_id 改成自己的」是半幻读的根源。**

**⚡ 面试价值**：能完整讲出这个链条，基本可以确定你真的理解 MVCC 的可见性算法，而不是背了「RR 不幻读」这句话。

### 六、怎么选择：什么时候用当前读

| 场景 | 用法 | 说明 |
|---|---|---|
| 只读查询、报表 | **快照读**（普通 SELECT） | 不加锁，并发最好 |
| **「先查后改」**（如：查余额→判断→扣款） | **当前读**（`FOR UPDATE`）或**乐观锁** | 必须防并发覆盖 |
| 读到的数据用于写 | **当前读** | 快照数据可能已过期 |
| 只是展示给用户看 | **快照读** | 但注意 RR 下可能读到略旧的数据 |
| 抢任务 / 队列消费 | **`FOR UPDATE SKIP LOCKED`** | 8.0 推荐 |
| 高并发扣库存 | **`UPDATE ... WHERE stock >= n`** | 让条件判断和更新原子化，避免 `FOR UPDATE` 的锁开销 |

**「原子更新」是比 `FOR UPDATE` 更优的模式**：

```sql
-- ❌ 不好：先查后改，两次往返 + 长锁
START TRANSACTION;
SELECT stock FROM product WHERE id = 1 FOR UPDATE;   -- 加锁
-- 应用层判断 stock >= 1
UPDATE product SET stock = stock - 1 WHERE id = 1;
COMMIT;

-- ✅ 更好：条件写进 UPDATE，让数据库原子完成
UPDATE product SET stock = stock - 1 WHERE id = 1 AND stock >= 1;
-- 检查 affected rows：1 → 成功；0 → 库存不足
-- 好处：无显式锁持有时间，一条语句完成，天然防超卖
```

**这是「乐观锁思想」的数据库侧实现**——用条件更新代替显式锁定，在高并发下性能明显更好。

### 七、验证实验（自己动手做一遍）

```sql
-- 准备
CREATE TABLE t_lock (id INT PRIMARY KEY, v INT NOT NULL, note VARCHAR(20));
INSERT INTO t_lock VALUES (1, 100, 'init'), (5, 500, 'init'), (10, 1000, 'init');

-- ═══ 实验 1：快照读不加锁 ═══
-- 会话 A
SET SESSION TRANSACTION ISOLATION LEVEL REPEATABLE READ;
START TRANSACTION;
SELECT * FROM t_lock WHERE id = 1;       -- 快照读

-- 会话 B（能立即成功，不被阻塞）
UPDATE t_lock SET v = 200 WHERE id = 1;
COMMIT;

-- 会话 A
SELECT * FROM t_lock WHERE id = 1;       -- 仍是 100（快照）
COMMIT;

-- ═══ 实验 2：当前读加锁 ═══
-- 会话 A
START TRANSACTION;
SELECT * FROM t_lock WHERE id = 1 FOR UPDATE;   -- 加 X 锁

-- 会话 B（阻塞！）
UPDATE t_lock SET v = 300 WHERE id = 1;
-- 等 innodb_lock_wait_timeout（50 秒）后报错

-- 会话 A
COMMIT;   -- B 立刻拿到锁继续

-- ═══ 实验 3：观察间隙锁阻塞插入 ═══
-- 会话 A
START TRANSACTION;
SELECT * FROM t_lock WHERE id > 1 AND id < 10 FOR UPDATE;   -- 锁住 (1,10)

-- 会话 B（阻塞！）
INSERT INTO t_lock VALUES (7, 700, 'new');

-- 查看锁的状态（会话 C）
SELECT ENGINE_TRANSACTION_ID, OBJECT_NAME, INDEX_NAME,
       LOCK_TYPE, LOCK_MODE, LOCK_STATUS, LOCK_DATA
FROM performance_schema.data_locks
WHERE OBJECT_NAME = 't_lock'\G
-- 会看到 LOCK_MODE 为 X,GAP 或 X（临键锁），LOCK_DATA 显示被锁的区间
```
:::

:::拓展
**`FOR UPDATE` 的锁粒度实验：唯一索引 vs 非唯一索引**

```sql
-- 准备：id 是主键（唯一），status 是普通索引（非唯一）
SELECT * FROM performance_schema.data_locks WHERE OBJECT_NAME = 't_lock'\G

-- ① 主键等值 + 命中 → 记录锁
START TRANSACTION;
SELECT * FROM t_lock WHERE id = 5 FOR UPDATE;
-- 加锁结果：X,REC_NOT_GAP on id=5（只有记录锁，无间隙）

-- ② 主键等值 + 未命中 → 间隙锁
START TRANSACTION;
SELECT * FROM t_lock WHERE id = 7 FOR UPDATE;    -- 7 不存在
-- 加锁结果：X,GAP on (5,10)

-- ③ 非唯一索引等值 → 临键锁
START TRANSACTION;
SELECT * FROM t_lock WHERE status = 2 FOR UPDATE;
-- 加锁结果：X（临键锁）+ 向后扫描到第一个不满足条件的记录
```

**这个实验做一遍，第 12 题的加锁规则就再也不会忘。**

**`FOR UPDATE` 在 RR 和 RC 下的差异（实测对比）**

```sql
-- RC 下重复实验 3
SET SESSION TRANSACTION ISOLATION LEVEL READ COMMITTED;
START TRANSACTION;
SELECT * FROM t_lock WHERE id > 1 AND id < 10 FOR UPDATE;
-- 查看锁：只有 REC_NOT_GAP（记录锁），没有 GAP
-- 此时另一个会话可以自由 INSERT id=7

-- 结论：这就是「RC 并发插入能力强、死锁概率低」的直接原因
```

**`LOCK IN SHARE MODE` 的 8.0 别名**

```sql
-- 5.7 语法（8.0 仍支持，但会有 deprecation 提示）
SELECT * FROM t_order WHERE id = 1 LOCK IN SHARE MODE;

-- 8.0 新语法（推荐）
SELECT * FROM t_order WHERE id = 1 FOR SHARE;

-- 完整语法：锁定模式 + 等待策略
SELECT ... FOR UPDATE [OF table_name] [NOWAIT | SKIP LOCKED]
```
:::

:::追问
**Q：普通 `SELECT` 在什么情况下会变成当前读？**
三种情况：
① **隔离级别是 Serializable** → 普通 `SELECT` 自动加共享锁（等价于 `LOCK IN SHARE MODE`）；
② **在存储函数/触发器里**，某些场景会走当前读；
③ **语句本身触发了隐式当前读**，如 `INSERT ... SELECT`（SELECT 部分在某些情况下会加锁）、`UPDATE ... WHERE` 里的子查询。
**另外注意：`SELECT` 命中「一致性读快照」和「加锁读」是互斥的，不会混用。**

**Q：为什么说「`FOR UPDATE` 不一定是排他锁」？**
在**唯一索引等值命中**的场景下，`FOR UPDATE` 加的是**记录锁**；在**未命中**时加的是**间隙锁**（`X,GAP`）；在**非唯一索引/范围查询**下加的是**临键锁**。**这三者都是排他的，但阻塞的对象不同**——记录锁阻塞「改这行」，间隙锁阻塞「往这个区间插」。

**Q：`SELECT ... FOR UPDATE` 和 `UPDATE` 的锁有什么区别？**
`SELECT ... FOR UPDATE` 只加锁，**不修改数据、不产生 undo log**；`UPDATE` 加锁 **+ 修改数据 + 写 undo log + 写 redo log + 写 binlog**。但**加锁范围在相同 WHERE 条件下是一样的**（都是当前读、都按索引定位加锁）。
**所以「用 `FOR UPDATE` 提前锁住」并不能减少锁的量，只是把锁提前到你需要判断的时刻。**

**Q：为什么推荐「原子更新」而不是「先查后改」？**
三个理由：① **减少一次网络往返**；② **锁持有时间更短**（一条语句内完成，不是「查」和「改」之间隔着应用层处理时间）；③ **天然防超卖**（`WHERE stock >= 1` 在数据库里原子判断）。
**代价**：拿到结果后你只知道「成功/失败」，不知道具体库存是多少。**如果需要返回新值，可以在 `UPDATE` 后再 `SELECT` 一次，或者用 `RETURNING`（MySQL 不支持，PostgreSQL 支持，见第 20 题）。**

**Q：MVCC 和锁能同时存在吗？一个事务里既有快照读又有当前读会怎样？**
能，而且很常见。**关键规则**：一个事务里可以自由混用，**但当前读会"污染"快照读** —— 因为当前读会修改行的 `DB_TRX_ID`（把别人已提交但自己不可见的行，改成自己的事务 id），导致后续快照读能看到它（半幻读）。
**实务建议**：如果事务里需要一致性快照，**先做完所有读，再做写**；或者干脆全部用当前读。
:::

:::锚点
**MongoDB 的 `readConcern` 和 MySQL 的「快照读/当前读」是同一个维度的问题，这个类比非常干净。**

```javascript
// MongoDB 的读关注级别
db.clbDetail.find({ taskId: "T001" }).readConcern("local")       // 读最新（≈当前读）
db.clbDetail.find({ taskId: "T001" }).readConcern("majority")    // 读多数派已确认（≈当前读，更强）
db.clbDetail.find({ taskId: "T001" }).readConcern("snapshot")    // 读事务快照（≈快照读）
db.clbDetail.find({ taskId: "T001" }).readConcern("linearizable") // 线性一致（最强，性能最差）
```

**面试话术**：

> 「快照读和当前读这个划分我在 MongoDB 上有一个很直接的对应。MongoDB 的 `readConcern` 本质上是在回答同一个问题：**『这次读，我要读哪个时刻的数据？』**

> `readConcern: "local"` 就是读当前节点最新数据，接近 MySQL 的当前读；`readConcern: "snapshot"` 是读事务开始时的一致性快照，跟 MySQL 的 RR 快照读是一个意思；`"majority"` 是保证读到的数据已经被多数节点确认。**设计哲学和 MySQL 是一致的：读得越"新"、越"一致"，代价越高。**

> MySQL 这边的关键区分是：**快照读走 MVCC 不加锁，当前读要加锁。`UPDATE` 必须是当前读，否则会更新丢失。** 我还知道一个容易被忽略的细节——**RR 下快照读不幻读，但如果事务里先做了当前读（比如 `UPDATE`），当前读会把别人新插入的行的 trx_id 改成自己的，导致后续快照读能看到它，这就是『半幻读』。**

> 落到实践上：**我在 RRM 的 RRM 数据处理里尽量避免「读一大段然后写一大段」的长事务，因为长事务会让 WiredTiger 必须保留大量旧版本，缓存压力会明显上升——这跟 InnoDB 里长事务导致 undo 膨胀、History list 增长是同一类问题。** 所以我们把批处理拆成了小的短事务。」

**注意**：上面讲的是你真实的 Mongo 经验 + MySQL 的原理理解。**不要把它们混成「我在 MySQL 上遇到过长事务问题」。**
:::

---

## 17. drop / delete / truncate 的区别

:::概念
**DELETE 是 DML**（逐行删、走事务、可回滚、触发触发器、产生 binlog）；
**TRUNCATE 是 DDL**（整个清空、隐式提交、不可回滚、重置自增值、不触发触发器）；
**DROP 是 DDL 的加强版**（连表结构 + 索引 + 触发器 + 权限一起删）。
一句话记：**「delete 删行、truncate 清表、drop 删表」。**
:::

:::提问
- `DELETE`、`TRUNCATE`、`DROP` 有什么区别？
- 清空一张大表，用哪个？
- `TRUNCATE` 为什么不能回滚？
- `TRUNCATE` 会重置 `AUTO_INCREMENT` 吗？
- `TRUNCATE` 释放磁盘空间吗？
- 大表删除数据怎么做才安全？
:::

:::答案
### 一、核心对比表

| 维度 | **DELETE** | **TRUNCATE** | **DROP** |
|---|---|---|---|
| **SQL 分类** | **DML**（数据操作语言） | **DDL**（数据定义语言） | **DDL** |
| **删什么** | 满足 WHERE 的**行** | **全表所有行** | **表结构 + 数据 + 索引 + 触发器 + 权限** |
| **能否带 WHERE** | ✅ 能 | ❌ 不能 | ❌ 不能 |
| **可回滚** | ✅ **能**（走 undo log，事务内） | ❌ **不能**（隐式提交） | ❌ **不能** |
| **触发触发器** | ✅ 会 | ❌ 不会 | ❌ 不会 |
| **重置 `AUTO_INCREMENT`** | ❌ **不重置**（从上次最大值继续） | ✅ **重置为 1** | 表都没了 |
| **执行时间** | 慢（逐行删 + 写 undo + 写 binlog） | **快**（直接重建表空间） | **最快** |
| **binlog 量** | 大（`ROW` 格式下每行一条记录） | 小（一条 DDL 语句） | 小 |
| **锁** | 行锁（InnoDB） | **元数据锁 MDL**（瞬时） | 元数据锁 MDL |
| **InnoDB 空间释放** | ❌ **不释放**（只标记可用） | ✅ **释放**（重建表空间） | ✅ 释放 |
| **MyISAM 空间释放** | ❌ 不释放 | ✅ 释放 | ✅ 释放 |
| **能否闪回/恢复** | ✅ 从 binlog 恢复 | ⚠️ 只能从备份恢复 | ⚠️ 只能从备份恢复 |
| **高危程度** | 中 | **高**（不可回滚） | **极高** |

### 二、`DELETE` 的两个陷阱

```sql
-- 陷阱 1：DELETE 不重置 AUTO_INCREMENT
DELETE FROM t_order;                       -- 删掉所有行
INSERT INTO t_order (...) VALUES (...);    -- 新行 id 从「上次最大值 + 1」开始，不是 1
-- 想重置：
TRUNCATE TABLE t_order;                    -- 重置为 1
-- 或者
ALTER TABLE t_order AUTO_INCREMENT = 1;
-- 或者（8.0 支持）
ALTER TABLE t_order AUTO_INCREMENT = 1;    -- 但只能设成比当前最大值更大，不能变小
```

**⚠️ `ALTER TABLE ... AUTO_INCREMENT = 1` 在 InnoDB 里的限制**：不能把自增值设成**小于等于当前最大值**——InnoDB 会忽略它，仍然从最大值 + 1 开始。**唯一能真正重置的方式是 `TRUNCATE TABLE`。**

```sql
-- 陷阱 2：DELETE 不释放磁盘空间（InnoDB 独立表空间也是如此）
DELETE FROM t_order WHERE created_at < '2025-01-01';   -- 删了 800 万行
-- 磁盘空间没变！.ibd 文件大小不变，只是这些页被标记为"可复用"

-- 验证
SELECT TABLE_NAME, DATA_LENGTH, DATA_FREE
FROM information_schema.TABLES WHERE TABLE_NAME = 't_order';
-- DATA_FREE 会变得很大（可复用但未还给操作系统的空间）

-- 想真正还给操作系统：必须重建表
ALTER TABLE t_order ENGINE=InnoDB;          -- 会锁表（大表用 gh-ost）
-- 或者
OPTIMIZE TABLE t_order;                      -- InnoDB 下等价于 ALTER ... FORCE
```

### 三、`TRUNCATE` 的实现与代价

**InnoDB 的 `TRUNCATE` 实际上是「删掉旧表 + 建一张同结构的新表」**：

```text
① 申请 MDL 元数据锁（瞬时）
② 删除原表的表空间文件（.ibd）
③ 按原表定义创建新的空表空间
④ 重置 AUTO_INCREMENT
⑤ 返回成功
```

**优点**：快、释放空间、重置自增、几乎不写 binlog。
**缺点**：**不可回滚**（DDL 隐式提交）、不能带条件、**会丢失 `AUTO_INCREMENT` 的连续性**（如果有外部系统依赖 id 单调，会出问题）。

```sql
-- 基本用法
TRUNCATE TABLE t_order;

-- 对比：DELETE 全表 vs TRUNCATE（10 万行的实测差异）
-- DELETE FROM t_order;      → 几秒到几十秒（逐行删 + 写 undo/redo/binlog）
-- TRUNCATE TABLE t_order;   → 毫秒级
```

**⚠️ `TRUNCATE` 的权限要求**：需要 `DROP` 权限（因为内部会 DROP 再 CREATE）。只给 `DELETE` 权限的应用账号**不能执行 TRUNCATE**——这其实是好事（多了一层保护）。

### 四、大表删数据的安全做法

**直接 `DELETE FROM big_table WHERE created_at < '2025-01-01'`（删 800 万行）的后果**：

| 问题 | 说明 |
|---|---|
| **长事务** | 整个 DELETE 在一个事务里，undo 表空间暴涨，`History list length` 飙升 |
| **锁范围大** | 长时间持有大量行锁，阻塞其他写入 |
| **主从延迟** | 一个巨大事务在从库单线程重放，延迟可能到几十分钟 |
| **binlog 爆炸** | ROW 格式下每行一条记录，binlog 文件可能几十 GB |
| **一旦中断要回滚** | 回滚一个删了 500 万行的事务，可能比删除本身更慢 |

**正确做法：分批删除 + 加间隔。**

```sql
-- ① 分批删除（每次 1000 行，批间 sleep）
-- 应用层或脚本循环执行：
DELETE FROM t_order WHERE created_at < '2025-01-01' LIMIT 1000;
-- 检查 affected rows，为 0 则停止；否则 sleep 0.1~1 秒后继续

-- 有主键时用「按主键区间删」更快（避免每次扫描定位）
DELETE FROM t_order
WHERE id < 1000000 AND created_at < '2025-01-01'
ORDER BY id LIMIT 1000;
-- 记住上次的最大 id，下次从这里开始
```

```bash
# ② 用 pt-archiver 自动分批归档 + 删除（Percona Toolkit）
pt-archiver \
  --source h=127.0.0.1,D=your_db,t=t_order \
  --where "created_at < '2025-01-01'" \
  --limit 1000 \
  --commit-each \
  --purge \
  --sleep 0.5 \
  --progress 10000 \
  --statistics

# --purge     删除源表的数据（不加则只归档）
# --limit     每批行数
# --commit-each  每批一个事务
# --sleep     每批之间暂停（保护主库）
# --progress  每 N 行打印一次进度
```

**③ 更激进：用「换表」方案**

```sql
-- 适用：要保留的历史数据很少（如只留最近 3 个月）
-- ① 建新表，把要保留的数据插进去（INSERT ... SELECT 也分批）
CREATE TABLE t_order_new LIKE t_order;
INSERT INTO t_order_new SELECT * FROM t_order WHERE created_at >= '2026-06-01';  -- 分批执行

-- ② 原子切换（RENAME 是原子的）
RENAME TABLE t_order TO t_order_old, t_order_new TO t_order;
-- 或者 8.0 支持原子 DDL（RENAME TABLE 支持多表原子切换，8.0.13+）

-- ③ 确认无误后删除旧表（DROP 立刻释放空间）
DROP TABLE t_order_old;
```

**④ 最佳实践：用分区表从根上解决**

```sql
-- 按时间分区，删除历史数据 = DROP PARTITION（毫秒级，几乎零代价）
CREATE TABLE t_order (
  id BIGINT NOT NULL AUTO_INCREMENT,
  created_at DATETIME NOT NULL,
  ...
  PRIMARY KEY (id, created_at)     -- ★ 分区键必须是主键的一部分
) ENGINE=InnoDB
PARTITION BY RANGE (TO_DAYS(created_at)) (
  PARTITION p202601 VALUES LESS THAN (TO_DAYS('2026-02-01')),
  PARTITION p202602 VALUES LESS THAN (TO_DAYS('2026-03-01')),
  PARTITION p202603 VALUES LESS THAN (TO_DAYS('2026-04-01')),
  PARTITION pmax    VALUES LESS THAN MAXVALUE
);

-- 删除历史数据（毫秒级！）
ALTER TABLE t_order DROP PARTITION p202601;

-- 查看分区
SELECT PARTITION_NAME, TABLE_ROWS, DATA_LENGTH
FROM information_schema.PARTITIONS WHERE TABLE_NAME = 't_order';
```

**分区表是「定期删历史数据」场景的正解**——`DROP PARTITION` 是物理删除整个分区文件，不产生大量 binlog，不产生长事务。

### 五、误删数据的恢复路径

| 场景 | 恢复方案 |
|---|---|
| **`DELETE` 误删（事务未提交）** | `ROLLBACK` |
| **`DELETE` 误删（已提交），binlog 保留** | ① 从备份恢复到误操作前；② 用 `mysqlbinlog` 重放到误操作前的 position；③ **用工具从 binlog 反向生成 INSERT**（binlog2sql / my2sql） |
| **`TRUNCATE` 误执行** | 只能从备份恢复（binlog 里只有 DDL 语句，没有数据） |
| **`DROP TABLE` 误执行** | 只能从备份恢复；**`innodb_file_per_table=ON` 时理论上可以从 `.ibd` 文件抢救（极难）** |
| **有延迟从库** | **最快的恢复方式**：延迟从库上数据还在，停掉重放，导出恢复 |

```bash
# binlog2sql：从 binlog 生成回滚 SQL（误删后的救命工具）
python binlog2sql.py \
  -h127.0.0.1 -uroot -p'pwd' -d your_db -t t_order \
  --start-file='binlog.000123' \
  --start-datetime='2026-09-18 11:00:00' \
  --stop-datetime='2026-09-18 11:05:00' \
  -B > rollback.sql      # -B 生成回滚 SQL（INSERT 变 DELETE，DELETE 变 INSERT）
```

**关键结论：`TRUNCATE` 和 `DROP` 是「备份级」风险操作**——必须确保有以下防线：

1. **延迟从库**（延迟 1 小时），误操作后还有救
2. **定期全量备份 + binlog 保留足够长**
3. **应用账号不给 `DROP` 权限**（只有 DBA 账号有）
4. **`DELETE`/`UPDATE` 前先 `SELECT` 确认影响行数**
5. **开启 `sql_safe_updates`**（阻止不带 WHERE 的 UPDATE/DELETE）
:::

:::拓展
**`sql_safe_updates`：防止手滑的开关**

```sql
SHOW VARIABLES LIKE 'sql_safe_updates';   -- 默认 OFF

-- 开启后（建议在每个 DBA 会话里开启）
SET SESSION sql_safe_updates = 1;
DELETE FROM t_order;                       -- ❌ 拒绝执行：没有 WHERE 且没有 LIMIT
DELETE FROM t_order WHERE status = 2;      -- ❌ 拒绝：WHERE 列没有索引
DELETE FROM t_order WHERE id = 1;          -- ✅ 允许（WHERE 用了索引）
DELETE FROM t_order WHERE status = 2 LIMIT 100;   -- ✅ 允许（有 LIMIT）
UPDATE t_order SET status = 1;             -- ❌ 拒绝
```

**规则**：不带 WHERE 或 WHERE 不带索引的 UPDATE/DELETE 一律拒绝，除非带 `LIMIT`。

**8.0 的原子 DDL**

MySQL 8.0 引入了**原子 DDL**：一次 DDL 操作要么完全成功，要么完全回滚，不会出现「删了一半」的中间状态。

```sql
-- 8.0：DROP TABLE 支持多表原子操作
DROP TABLE t1, t2, t3;    -- 要么全成功，要么全失败（5.7 可能部分成功）

-- 相关
SHOW VARIABLES LIKE 'innodb_ddl_log%';
-- innodb_ddl_log 是原子 DDL 的实现（在 undo 表空间里记录 DDL 日志）
```

**注意：原子 DDL 指的是「DDL 本身的原子性」，不是「DDL 可以回滚」。** `TRUNCATE` 在 8.0 里依然是**不可回滚**的（它仍然是隐式提交的 DDL）。

**其他容易被忽略的 DDL 行为**

```sql
-- ① TRUNCATE 在 InnoDB 里会重置 AUTO_INCREMENT，但不会重置自增的持久化值
--    （8.0 起自增值写入了 redo log，重启后不再"回退"，这是 8.0 的一个重要修复）

-- ② DELETE 后想重置自增值
TRUNCATE TABLE t;

-- ③ 带外键的表不能 TRUNCATE（有引用时）
-- ERROR 1701: Cannot truncate a table referenced in a foreign key constraint

-- ④ TRUNCATE 是 DDL，会隐式提交当前事务
START TRANSACTION;
INSERT INTO t VALUES (1);
TRUNCATE TABLE t2;      -- 这里会隐式提交上面那个 INSERT！
ROLLBACK;               -- 回滚不掉，因为已经提交了
```

**最后这条是面试里很好的「陷阱题」**：`TRUNCATE`、`ALTER`、`CREATE`、`DROP` 都会**隐式提交当前事务**——这是 MySQL 特有的行为，PostgreSQL 里 DDL 是可以在事务里回滚的（见第 20 题）。
:::

:::追问
**Q：`DELETE` 后 `AUTO_INCREMENT` 不重置，为什么？**
因为自增值的分配是**独立的机制**。InnoDB 在内存里维护「下一个可用自增值」，`DELETE` 不会修改它。这样设计是有意的：
① **性能**：不用每次删除都重新扫描最大值；
② **避免主键复用**：如果重置了，新插入的行会复用已删除的主键，可能导致「已删除的数据的引用指向了新的数据」（比如外键、缓存 key、日志引用）。
**所以「不要依赖自增主键的连续性」是一条设计原则。**

```sql
-- 查看当前自增值
SHOW TABLE STATUS LIKE 't_order'\G   -- 看 Auto_increment 列
SELECT AUTO_INCREMENT FROM information_schema.TABLES WHERE TABLE_NAME = 't_order';
```

**Q：`TRUNCATE` 和 `DELETE` 谁更快？差多少？**
差距随数据量放大。10 万行：`DELETE` 几秒，`TRUNCATE` 几毫秒（**差千倍**）。1000 万行：`DELETE` 可能几十分钟，`TRUNCATE` 还是几毫秒。
**原因**：`DELETE` 要逐行处理（找到行 → 加锁 → 写 undo → 标记删除 → 写 binlog）；`TRUNCATE` 直接删文件 + 建新表。

**Q：`DROP` 之后磁盘空间立刻释放吗？**
**InnoDB + `innodb_file_per_table=ON`（5.6.6+ 默认）：立刻释放。**
**MyISAM 或 `innodb_file_per_table=OFF`：不释放**（空间在共享表空间 `ibdata1` 里，只标记为可复用）。
这就是**「生产必须保持 `innodb_file_per_table=ON`」**的原因。

```sql
SHOW VARIABLES LIKE 'innodb_file_per_table';   -- 确认是 ON
```

**Q：怎样在生产安全地清空一张大表？**
按场景选：

| 场景 | 方案 |
|---|---|
| **要保留表结构和自增从头开始** | `TRUNCATE TABLE t;`（大表也是毫秒级，但**不可回滚**，执行前必须二次确认 + 有备份） |
| **要按条件删除部分数据** | 分批 `DELETE`（`LIMIT 1000` + 间隔），或用 `pt-archiver` |
| **要保留的数据很少** | 建新表 → `INSERT ... SELECT` 分批迁 → `RENAME TABLE` 原子切换 → `DROP` 旧表 |
| **要定期删历史数据（长期需求）** | **改造成分区表**，用 `ALTER TABLE ... DROP PARTITION` |

**执行任何大表操作前的检查清单**：
1. 有无备份 / 延迟从库？
2. 是不是业务低峰期？
3. 会锁多久（预估）？
4. 主从延迟能接受吗？
5. 有回滚方案吗？
:::

:::锚点
**这道题有一个非常实在的落点：RRM 的上报数据（`clbDetail`）是典型的海量时序数据，必然有「定期清理历史数据」的需求。**

MongoDB 的对应方案：

```javascript
// ① MongoDB 的 TTL 索引（对应 MySQL 的分区表 DROP PARTITION 思路）
db.clbDetail.createIndex({ createdAt: 1 }, { expireAfterSeconds: 2592000 })   // 30 天自动删除
// 后台线程每分钟扫一次，删除到期的文档

// ② 直接删集合（对应 TRUNCATE，快但不可回滚）
db.clbDetail.drop()
db.clbDetail.deleteMany({})              // 对应 DELETE 全表，慢

// ③ 分片 + 按时间范围批量删（分批思路一致）
db.clbDetail.deleteMany({ taskId: { $in: [...] } })
```

**面试话术**：

> 「大表数据清理这个事我在 RRM 上有实际体会。**上报数据 `clbDetail` 是海量的时序数据，我们不可能无限存下去，所以清理策略是必须的。**

> MongoDB 里有两个选择：**一是 TTL 索引，让数据库后台自动删除过期文档——这个思路对应的就是 MySQL 的分区表 `DROP PARTITION`，都是『让存储层按时间维度物理删除』，代价远低于逐行删；二是大批量 `deleteMany`，但和 MySQL 的 `DELETE` 一样有长事务、复制延迟的问题，所以我们不会一次删几百天，而是按 taskId 或时间范围分批。**

> MySQL 这边我知道的核心区别是：**`DELETE` 是 DML，逐行删、可回滚、走 undo、不释放磁盘空间；`TRUNCATE` 和 `DROP` 是 DDL，隐式提交、不可回滚、快、释放空间。** 而且我特别注意到一个容易踩的坑：**`TRUNCATE` 会隐式提交当前事务**，所以不能把它放在事务里当普通操作。

> 落到工程规范上，我的习惯是：**任何大范围删除前先 SELECT 确认影响行数、确认有备份或延迟从库、业务低峰期执行、分批加间隔。** 这个习惯是从 RRM 处理海量数据的时候养成的——**在 MongoDB 里一次删太多会导致复制延迟和缓存压力，在 MySQL 里就是主从延迟和 undo 膨胀，本质是同一类问题。**」

**注意**：说「我从 Mongo 的经验里养成了这个规范」，不要说「我在 MySQL 上执行过 TRUNCATE 事故」。
:::

---

## 18. 主从复制与读写分离

:::概念
**「两个线程一条日志」**：
主库写 **binlog** → 从库 **IO 线程**拉取并写入 **relay log（中继日志）** → 从库 **SQL 线程**重放 relay log。
三种模式：**异步（默认，可能丢数据）/ 半同步（等至少一个从库确认）/ 全同步（性能差）**。
核心问题：**主从延迟**。解决方向：**并行复制 / 拆大事务 / 读写分离降级读主 / 缓存**。
:::

:::提问
- 主从复制的原理是什么？
- 主从延迟怎么产生的？怎么解决？
- 异步、半同步、全同步复制有什么区别？
- 什么是 GTID？比传统复制好在哪？
- 读写分离怎么做？读到旧数据怎么办？
- 主从切换怎么保证不丢数据？
:::

:::答案
### 一、复制流程（三个线程）

```text
┌─────────────── 主库 Master ───────────────┐
│  ① 业务写入 → 写 binlog                    │
│  ② Binlog Dump Thread：把 binlog 推给从库   │
└──────────────────┬────────────────────────┘
                   │ 网络传输 binlog events
                   ▼
┌─────────────── 从库 Slave ────────────────┐
│  ③ IO Thread：接收 binlog → 写入 relay log │
│  ④ SQL Thread：读 relay log → 在从库重放    │
│     （重放后也会写从库自己的 binlog，用于级联）│
└───────────────────────────────────────────┘
```

**三个线程各管一段**：

| 线程 | 位置 | 职责 |
|---|---|---|
| **Binlog Dump Thread** | 主库 | 每个从库一个，负责推送 binlog |
| **IO Thread** | 从库 | 拉取 binlog 写进 relay log |
| **SQL Thread** | 从库 | 读 relay log 并重放（**5.7+ 可以有多个，即并行复制**） |

**关键点**：**IO 线程和 SQL 线程是解耦的**——IO 线程可以快速把 binlog 拉到本地（relay log 积压），SQL 线程慢慢重放。**这就是为什么「主从延迟」通常出在 SQL 线程（重放慢），而不是网络。**

### 二、三种复制模式

| 模式 | 行为 | 数据安全 | 性能 | 默认 |
|---|---|---|---|---|
| **异步复制** | 主库写完 binlog 立即返回，不等从库 | **主库宕机可能丢已提交数据** | 最好 | ✅ MySQL 默认 |
| **半同步复制** | 主库等**至少一个从库**确认收到（写入 relay log）才返回 | 好（大幅降低丢数据概率） | 中（多一次网络往返） | 需插件开启 |
| **全同步复制** | 等**所有从库**重放完成才返回 | 最好 | 最差 | 不用 |

**半同步复制的两个版本**（**8.0 的重要变化**）：

| | 5.7 的 `rpl_semi_sync` | 8.0 的 `rpl_semi_sync` |
|---|---|---|
| 插件的库 | `semisync_master` / `semisync_slave` | `rpl_semi_sync`（插件名归并） |
| 确认时机 | **从库写完 relay log 就 ack** | 从库写完 relay log 就 ack（默认）<br>**8.0 可选「等重放完成」** |
| 超时行为 | 超时后退化成异步（**静默降级，有风险**） | 超时后退化成异步，但会**记录告警** |

```sql
-- 查看半同步状态
SHOW VARIABLES LIKE 'rpl_semi_sync%';
SHOW STATUS  LIKE 'Rpl_semi_sync%';
-- Rpl_semi_sync_master_status  ON/OFF
-- Rpl_semi_sync_master_yes_tx  / no_tx   成功/降级的次数

-- 安装插件（5.7/8.0 语法略有不同）
INSTALL PLUGIN rpl_semi_sync_master SONAME 'semisync_master.so';
INSTALL PLUGIN rpl_semi_sync_slave  SONAME 'semisync_slave.so';

-- 开启
SET GLOBAL rpl_semi_sync_master_enabled = ON;
SET GLOBAL rpl_semi_sync_slave_enabled  = ON;
SET GLOBAL rpl_semi_sync_master_timeout = 1000;   -- 1 秒超时后降级为异步（默认 10000ms）
```

**⚠️ `rpl_semi_sync_master_timeout` 的陷阱**：设为 10 秒（默认）意味着**如果所有从库都挂了，主库会卡住 10 秒才降级**——业务表现为「突发大延迟」。**生产建议调到 1 秒以内**。

### 三、GTID：更可靠的复制方式

**传统复制的痛点**：需要手动指定 `MASTER_LOG_FILE` + `MASTER_LOG_POS`，主从切换时定位点很麻烦，容易错。

**GTID（Global Transaction ID）**：每个事务在主库上分配一个全局唯一的 id。

```text
GTID 格式：source_id:transaction_id
例如：      3f8b1e2a-1234-11ef-9a3b-00163e0c1a2b:1-5000
            └────── 服务器 UUID ──────┘    └ 事务序号 ┘
```

```sql
-- 开启 GTID（必须写 my.cnf 并重启）
-- [mysqld]
-- gtid_mode = ON
-- enforce_gtid_consistency = ON

SHOW VARIABLES LIKE 'gtid_mode';
SHOW VARIABLES LIKE 'enforce_gtid_consistency';

-- 查看已执行的 GTID 集合
SELECT @@GLOBAL.gtid_executed\G

-- 用 GTID 建立复制（不用再记 file + pos）
CHANGE REPLICATION SOURCE TO
  SOURCE_HOST = '10.20.3.10',
  SOURCE_PORT = 3306,
  SOURCE_USER = 'repl',
  SOURCE_PASSWORD = 'xxx',
  SOURCE_AUTO_POSITION = 1;      -- ★ 自动按 GTID 定位

START REPLICA;
```

**8.0 的术语变化（重要）**：

| 5.7 及以前 | 8.0.22+ |
|---|---|
| `MASTER` / `SLAVE` | `SOURCE` / `REPLICA` |
| `CHANGE MASTER TO` | `CHANGE REPLICATION SOURCE TO` |
| `START SLAVE` / `STOP SLAVE` | `START REPLICA` / `STOP REPLICA` |
| `SHOW SLAVE STATUS` | `SHOW REPLICA STATUS` |
| `SHOW MASTER STATUS` | `SHOW BINLOG STATUS` |

**旧语法在 8.0 仍可用但会 deprecation 警告，8.0.22 起推荐新术语**。面试时用新术语会显得跟进得比较勤。

**GTID 的优势**：
1. **主从切换不用手工定位**（`SOURCE_AUTO_POSITION=1`）
2. **能自动跳过已执行的事务**（幂等性）
3. **能检测主从数据不一致**（`gtid_executed` 比对）
4. **级联复制、多源复制更简单**

### 四、主从延迟：原因与解法

**怎么看延迟**：

```sql
-- 从库上执行（8.0.22+ 用 SHOW REPLICA STATUS）
SHOW REPLICA STATUS\G
-- 关键字段：
--   Replica_IO_Running:  Yes        IO 线程是否正常
--   Replica_SQL_Running: Yes        SQL 线程是否正常
--   Seconds_Behind_Master: 0        延迟秒数（★ 最重要）
--   Relay_Log_Space:                 relay log 积压大小（★ 更可靠）
--   Replica_SQL_Running_State:      SQL 线程在干什么
--   Retrieved_Gtid_Set / Executed_Gtid_Set: IO 拉到的 vs SQL 执行到的（★ 最准）
--   Last_SQL_Error:                 SQL 线程报错（复制中断时看这里）
```

**`Seconds_Behind_Master` 不可靠的三个原因**：
1. **它比较的是「从库当前时间」和「正在重放的事件的 timestamp」**——如果从库没有新事件可重放（IO 断了），它会显示 **0**（假象！）
2. **它不反映 relay log 里积压的量**
3. **从库时钟不准时会算错**

**更可靠的指标**：`Retrieved_Gtid_Set` 和 `Executed_Gtid_Set` 的差值。

```sql
-- 用 GTID 差集算真实延迟（8.0 推荐）
SELECT
  GTID_SUBTRACT(
    (SELECT @@GLOBAL.gtid_executed),     -- 主库执行的（在从库上则是已重放的）
    ...
  );
-- 更实际的写法：在从库上比较
SELECT
  @@GLOBAL.gtid_executed AS executed,
  (SELECT VARIABLE_VALUE FROM performance_schema.replication_connection_status
    WHERE VARIABLE_NAME = 'RECEIVED_TRANSACTION_SET') AS received;
-- received - executed 的差集 = relay log 里还没重放的事务数 ★ 真实延迟

-- 8.0 有现成的视图
SELECT * FROM performance_schema.replication_applier_status_by_worker\G
SELECT * FROM sys.session\G
```

**延迟的五个原因与解法**：

| 原因 | 表现 | 解法 |
|---|---|---|
| **从库 SQL 线程单线程重放** | 主库高并发写入时延迟飙升 | **开启并行复制**（`replica_parallel_workers`） |
| **大事务**（一次删/改百万行） | 单个事务重放很久，延迟突然跳高 | 拆大事务（分批）；`binlog_row_image=MINIMAL` 减小日志 |
| **从库承担查询压力** | 从库 CPU 高，重放被挤 | 读写分离要留余量；重查询走独立只读实例 |
| **表上没有主键/唯一键** | ROW 格式下从库重放要全表扫找行 | **所有表必须有主键**（否则 ROW 复制极慢） |
| **网络带宽/延迟** | IO 线程落后 | 增大 `replica_net_timeout`；检查网络 |
| **从库单机配置低于主库** | 重放能力不足 | 从库配置不低于主库 |

**并行复制的演进（重要）**：

| 版本 | 机制 | 原理 |
|---|---|---|
| 5.6 | 按库并行（`DATABASE`） | 不同库的事务可以并行，**但单库压力大的业务完全无效** |
| **5.7** | **按组提交并行（`LOGICAL_CLOCK`）** | 主库上能**同时进入 prepare 阶段**的事务（同一组提交）在从库上可以并行重放 |
| **8.0** | **基于 WRITESET 的并行** | 用**行级别的哈希**判断事务之间是否有冲突，**冲突的才串行**，无冲突的可以并行 → 单库也有很好的并行度 |

```sql
-- 查看并行复制配置
SHOW VARIABLES LIKE 'replica_parallel_workers';      -- 8.0 默认 4（5.7 默认 0=关闭）
SHOW VARIABLES LIKE 'replica_parallel_type';         -- LOGICAL_CLOCK
SHOW VARIABLES LIKE 'replica_preserve_commit_order'; -- ON（保证提交顺序，避免从库数据跳变）

-- 8.0 的 WRITESET（默认开启）
SHOW VARIABLES LIKE 'binlog_transaction_dependency_tracking';  -- COMMIT_ORDER / WRITESET
SHOW VARIABLES LIKE 'transaction_write_set_extraction';        -- XXHASH64

-- 调大并行度（从库 CPU 核数的一半左右是常见起点）
SET GLOBAL replica_parallel_workers = 16;
```

**⚠️ 调大 `replica_parallel_workers` 的注意点**：
1. **`replica_preserve_commit_order` 必须为 ON**，否则从库上的数据可能短暂出现在「未来状态」（比如先看到 UPDATE 的结果，后看到 INSERT）
2. **Worker 数不是越大越好**——每个 worker 是一个线程，有调度开销

### 五、读写分离

```text
                    ┌──► 主库（读写）
应用 ──► 中间件 ────┤
                    ├──► 从库 1（只读）
                    └──► 从库 2（只读）
```

**实现方式**：

| 方式 | 说明 | 优点 | 缺点 |
|---|---|---|---|
| **应用层双数据源** | 代码里根据注解/方法名路由（Spring 的 `AbstractRoutingDataSource`） | 简单、可控 | 侵入业务代码 |
| **中间件代理** | ProxySQL / MaxScale / MyCat / ShardingSphere-Proxy | 业务无感 | 多一跳、需运维 |
| **ShardingSphere-JDBC** | 客户端 SDK，无额外部署 | 性能好 | 绑语言（Java） |

```java
// Spring 的 AbstractRoutingDataSource 简化示例（思路）
public class ReadWriteRoutingDataSource extends AbstractRoutingDataSource {
    @Override
    protected Object determineCurrentLookupKey() {
        return ReadWriteContext.isWrite() ? "master" : "slave";
    }
}

// 用法
@Transactional                        // 写：走主库
public void createOrder(Order o) { ... }

@Transactional(readOnly = true)       // 读：走从库
public Order getOrder(Long id) { ... }
```

**⚠️ `@Transactional(readOnly = true)` 的两个作用**：
1. 给路由一个**提示**（配合 `LazyConnectionDataSourceProxy` 才能真正生效）
2. **MySQL 8.0 起，`readOnly` 事务会被优化**（减少一些内部开销）

**但注意**：`readOnly` **只是一个提示，不会真的阻止写**（除非 `SET SESSION TRANSACTION READ ONLY`）。

### 六、读写分离后「读到旧数据」怎么解决

**场景**：用户下单成功 → 立即跳转订单详情 → 因为主从延迟，查不到刚下的订单。

| 方案 | 说明 | 代价 |
|---|---|---|
| **写后读主（强制走主库）** | 写操作后的一段时间内（如 1 秒）该用户的读都走主库 | 简单，但主库压力增加 |
| **按业务分流** | 重要操作（下单、支付）读主库，列表/报表读从库 | 需要业务识别 |
| **GTID 位点校验** | 记录写操作的 GTID，读从库前先确认从库已执行到该 GTID | 精确，实现复杂 |
| **本地缓存** | 写入后把结果放本地缓存，读时先查缓存 | 需要处理缓存一致性 |
| **延迟从库专门处理** | 从库不承担实时读 | 不解决问题，只是隔离 |
| **应用层重试** | 读不到就重试几次 | 治标不治本，增加延迟 |

**「写后读主」的最简实现**（Spring）：

```java
// 用一个 ThreadLocal 记录"本会话发生过写"
// 写操作后标记，读操作时若标记存在则走主库
// 需要配合过期时间（比如 1 秒后自动清除）

// 更常见的简化做法：直接用注解标注关键读走主库
@Transactional(readOnly = true)
public Order getOrderAfterCreate(Long id) {
    // 关键路径读主库
}

// ShardingSphere 的做法：HintManager
HintManager hintManager = HintManager.getInstance();
hintManager.setWriteRouteOnly();     // 强制走主库
try {
    orderMapper.selectById(id);
} finally {
    hintManager.close();
}
```

### 七、主从切换与数据安全

**主库故障时的两种切换**：

| 方式 | 说明 | 丢数据风险 |
|---|---|---|
| **手动切换** | DBA 介入，选最新的从库提升 | 最小（可以人工确认位点） |
| **自动切换（MHA / Orchestrator / 云 RDS）** | 自动选从库提升、切换 VIP | 有（异步复制下可能丢最后几个事务） |

**减少丢数据的三道防线**：

1. **半同步复制** → 保证主库返回成功时，至少一个从库已有 binlog
2. **`innodb_flush_log_at_trx_commit=1` + `sync_binlog=1`** → 保证主库自己已落盘
3. **`rpl_semi_sync_master_wait_for_slave_count`**（8.0）→ 设置需要确认的从库数量（默认 1，可设 2 实现多数派）

**⚠️ 半同步的「降级」陷阱**：从库全部挂掉时，主库超时后**自动降级为异步**——此时主库上的写入不再有从库保障。**这个降级过程中如果有主库故障，会丢数据。** 所以生产要做：
- `rpl_semi_sync_master_timeout` 设小（1 秒）
- **对 `Rpl_semi_sync_master_status` 做监控告警**
:::

:::拓展
**复制链路的完整监控项**

```sql
-- 从库：复制健康度（8.0.22+）
SHOW REPLICA STATUS\G
-- 必看字段：
--   Replica_IO_Running / Replica_SQL_Running: 两个都必须 Yes
--   Seconds_Behind_Master: 延迟秒数（不绝对可靠）
--   Last_IO_Error / Last_SQL_Error: 报错信息
--   Retrieved_Gtid_Set / Executed_Gtid_Set: ★ 最可靠的延迟指标
--   Relay_Log_Space: relay log 积压

-- 延迟的精确计算（GTID 差集）
SELECT GTID_SUBTRACT(
  (SELECT RECEIVED_TRANSACTION_SET FROM performance_schema.replication_connection_status
    WHERE CHANNEL_NAME = ''),
  (SELECT @@GLOBAL.gtid_executed)
) AS pending_gtids;
-- 结果为空 → 完全同步

-- 8.0 的复制性能视图
SELECT * FROM performance_schema.replication_applier_status_by_worker\G
-- 每个 worker 在做什么、处理了多少事务

-- 主库：看有多少从库连着
SHOW PROCESSLIST;     -- command = Binlog Dump 的就是从库连接
SELECT * FROM performance_schema.replication_connection_configuration;
```

**GTID 相关运维命令（很实用）**

```sql
-- ① 主从数据一致性校验（8.0.26+ 内置）
SHOW REPLICA STATUS\G
-- 对比 Retrieved_Gtid_Set 和 Executed_Gtid_Set

-- ② 跳过出错的事务（危险，只在明确知道原因时用）
STOP REPLICA;
SET GTID_NEXT = '3f8b1e2a-1234-11ef-9a3b-00163e0c1a2b:5001';   -- 手动指定下一个事务的 GTID
BEGIN; COMMIT;
SET GTID_NEXT = 'AUTOMATIC';
START REPLICA;
-- ⚠️ 这会造成主从数据不一致，只能作为应急手段

-- ③ 用 pt-table-checksum 校验主从数据一致性（Percona Toolkit）
-- pt-table-checksum --host=master --user=root --password=xxx --databases=your_db
-- pt-table-sync --print --replicate=percona.checksums h=master,D=your_db,t=t_order
```

**多源复制（8.0 支持得更好）**

```sql
-- 8.0 用 FOR CHANNEL 区分多个源
CHANGE REPLICATION SOURCE TO
  SOURCE_HOST='10.20.3.10', ..., FOR CHANNEL 'channel_1';
CHANGE REPLICATION SOURCE TO
  SOURCE_HOST='10.20.3.20', ..., FOR CHANNEL 'channel_2';

START REPLICA FOR CHANNEL 'channel_1';
START REPLICA FOR CHANNEL 'channel_2';

SHOW REPLICA STATUS FOR CHANNEL 'channel_1';
```

**`slave_parallel_workers=0` 的灾难**

```sql
-- 5.7 默认是 0（关闭并行复制）！如果从库是 5.7 且没改过，就是单线程重放
SHOW VARIABLES LIKE 'replica_parallel_workers';    -- 5.7 默认 0，8.0 默认 4
```

**这是很多「从库延迟很高」问题的第一原因**——检查这个参数应该放在排查延迟的第一步。
:::

:::追问
**Q：为什么 ROW 格式下「表没有主键」会导致从库重放极慢？**
ROW 格式记录的是「行的前后像」。但从库重放时，**必须找到那一行才能改**。如果没有主键（也没有唯一索引），从库只能做**全表扫描**来定位要改的行。主库上每秒几千次的更新，在从库上就变成每秒几千次全表扫描——**延迟瞬间爆炸**。
**这是「所有表都必须有主键」的第二条硬理由**（第一条是聚簇索引的页分裂问题）。

**Q：`Seconds_Behind_Master = 0` 就一定没延迟吗？**
**不一定！** 三种假象：
① **IO 线程断了**（网络问题）→ 没有新事件可重放 → 显示 0，但实际上主库还在写，从库已经落后很多；
② **relay log 里有积压但 SQL 线程刚好在重放一个短事务** → 瞬时显示 0；
③ **从库时钟比主库快** → 计算出的延迟偏小甚至为负（显示为 0）。
**可靠做法：比对 `Retrieved_Gtid_Set` 和 `Executed_Gtid_Set` 的差集，同时监控 `Relay_Log_Space`。**

**Q：主从复制能保证主从数据完全一致吗？**
**不能保证**，只保证「重放过程的确定性」。造成不一致的原因：
① **从库被人工写入**（`SET sql_log_bin=0` 后直接改从库数据）；
② **SQL 线程跳过错误事务**（`SET GTID_NEXT` 手动跳过）；
③ **`binlog_format=STATEMENT` + 不确定函数**（虽然 MIXED 会规避大部分）；
④ **主从表结构不一致**（从库少一列但重放时被忽略）；
⑤ **主从版本不同**导致行为差异（如 5.7 和 8.0 的排序规则差异）。
**所以生产要定期做一致性校验**（`pt-table-checksum`）。

**Q：读写分离后，事务里的读会走从库吗？**
**不能！** 这是读写分离的硬规则：**一个事务内的所有操作必须走同一个数据源**——因为跨数据源的事务根本不存在（`@Transactional` 的边界是一个 `DataSource`）。
**实现要点**：路由判断必须在**事务开始前**完成（所以要用 `LazyConnectionDataSourceProxy` 延迟连接获取时机，或者用 `@Transactional(readOnly=true)` 的注解在事务开启前决策）。
**常见 bug**：在 `@Transactional` 方法内部通过 `ThreadLocal` 切换数据源——**不生效**，因为连接已经开了。

**Q：主库挂了，从库提升为新主库，怎么保证不丢数据？**
三道防线（按重要性）：
① **半同步复制**（保证主库返回成功时至少一个从库已有数据）；
② **`rpl_semi_sync_master_wait_for_slave_count = 2`**（8.0，要求 2 个从库确认，实现多数派）；
③ **切换时选「GTID 最全」的从库提升**。
**但即使如此，异步降级期间的数据仍可能丢**——这就是为什么「不丢数据」在分布式系统里需要 Raft/Paxos 这类共识协议（MySQL 本身不提供，要靠 MySQL Group Replication 或云厂商的强一致实例）。
:::

:::锚点
**你在 RRM 里有非常真实的对应经验：项目跑在腾讯云现网和国际云两套环境上，数据是跨环境/跨地域的。**

MongoDB 的复制机制对照：

| | MySQL | MongoDB |
|---|---|---|
| 复制单位 | **事务（binlog event）** | **操作（oplog entry，幂等）** |
| 日志 | binlog | **oplog（local.oplog.rs，capped collection）** |
| 复制拓扑 | 主从 / 级联 / 多源 | **副本集（1 Primary + N Secondary）** |
| 同步机制 | IO 线程 + SQL 线程 | Secondary 的复制线程拉 oplog 并重放 |
| 确认机制 | 半同步（插件） | **`writeConcern: { w: "majority" }`** |
| 读一致性 | 隔离级别 | **`readConcern`** |
| 延迟监控 | `Seconds_Behind_Master` | **`rs.printSecondaryReplicationInfo()`** |
| 自动故障切换 | 需 MHA/Orchestrator | **副本集内置自动选举** |

```javascript
// MongoDB 查看复制延迟
rs.printSecondaryReplicationInfo()
// source: 10.20.3.11:27017
//     syncedTo: Fri Sep 18 2026 11:23:45 GMT+0800
//     0 secs (0 hrs) behind the primary

rs.status()          // 完整副本集状态
rs.printReplicationInfo()  // oplog 的时间窗口（能容纳多久的延迟）
```

**面试话术**：

> 「主从复制这块，MySQL 的机制我是清楚的，而 MongoDB 的副本集我是在 RRM 里实际用过的，两边可以对照着讲。

> MySQL 是**三个线程 + 一条日志**：主库写 binlog，从库的 IO 线程拉过来写进 relay log，SQL 线程再重放。**核心问题是主从延迟**，最常见的两个原因：一是**从库 SQL 线程单线程重放**（5.7 默认 `replica_parallel_workers=0`，8.0 默认 4）；二是**表没有主键**——ROW 格式下从库找不到目标行只能全表扫，延迟瞬间爆炸。

> MongoDB 这边是**副本集 + oplog**：Secondary 拉取 oplog 重放。**oplog 是幂等的**（记录的是操作而不是数据前后像），这一点和 MySQL 的 ROW 格式不同。我们用 `rs.printSecondaryReplicationInfo()` 看延迟，用 `writeConcern: majority` 保证写入被多数节点确认。

> 我在 RRM 里做过的一个相关实践是：**给报告数据量大的集合做分片时，会特别关注写关注点和读关注点的设置**——因为我们有部分报表查询可以容忍最终一致，但调优任务的写入不能丢。**这个『按数据重要性区分一致性要求』的思路，和 MySQL 里『核心库用半同步 + 双 1，日志库可以放宽』是一致的。**

> MySQL 的读写分离如果要做，我知道关键点是**事务内必须走同一个数据源**，路由要在事务开启前决定好，否则会出 bug。」

**注意**：说「我理解 MySQL 的主从机制 + 我在 Mongo 副本集上有实操」，**不要说「我配置过 MySQL 主从」**。而且上面提到的「部分查询可以容忍最终一致、调优任务写入不能丢」是对 RRM 场景的合理描述，不算编造。
:::

## 19. 分库分表与分片设计

:::概念
**分表扛数据量（单表行数），分库扛并发（连接数、IO）。**
**垂直拆分**按业务/字段切；**水平拆分**按分片键取模/范围/哈希。
三个核心难点：**跨库 JOIN、分布式事务、扩容迁移**。
一句话记：**「先优化、再读写分离、最后才分库分表」**——分库分表是最后手段，不是第一选择。
:::

:::提问
- 什么情况下需要分库分表？
- 垂直拆分和水平拆分的区别？
- 分片键怎么选？选错了会怎样？
- 分片后全局唯一 ID 怎么生成？
- 跨库 JOIN 和分页怎么解决？
- 扩容的时候怎么迁移数据？
- 分库分表的中间件有哪些？
:::

:::答案
### 一、先问：真的需要分库分表吗

**分库分表会引入巨大的复杂度，是「最后手段」。** 在这之前应该按顺序尝试：

| 优先级 | 手段 | 能撑到 |
|---|---|---|
| 1 | **SQL 与索引优化** | 消除慢查询，QPS 提升 10~100 倍 |
| 2 | **加缓存（Redis）** | 读 QPS 提升到 10 万级 |
| 3 | **读写分离** | 读扩展（从库数量线性扩展） |
| 4 | **垂直拆分**（按业务分库 / 大字段拆表） | 单库压力下降 |
| 5 | **归档冷数据** | 单表行数下降 |
| 6 | **分区表**（单库内） | 单表行数、清理效率 |
| 7 | **分库分表** | 终极方案 |

**触发分库分表的量化信号**：

| 信号 | 阈值 | 说明 |
|---|---|---|
| **单表行数** | **2000 万行以上**（B+ 树 3 层 → 4 层） | 不是硬限制，是「性能开始明显下降」的经验值 |
| **单表数据文件大小** | 50GB+ | 备份/DDL 变得困难 |
| **单库 QPS** | 单实例 5000~10000 | 视硬件和 SQL 复杂度 |
| **磁盘容量** | 单实例 2TB+ | 备份恢复窗口太长 |
| **单表 DDL 时间** | `ALTER TABLE` 超过 1 小时 | 运维不可控 |
| **连接数** | `max_connections` 被打满 | 分库可以分摊连接 |

**注意「2000 万行」这个数字要看场景**：如果单行很小（几十字节）、查询都走覆盖索引，5000 万行也可以很快。**关键是「热点数据能否常驻 buffer pool」**——如果活跃数据只有 1%，那表再大也没关系。

```sql
-- 评估表的真实规模
SELECT
  TABLE_NAME,
  TABLE_ROWS,
  ROUND(DATA_LENGTH  / 1024 / 1024 / 1024, 2) AS data_gb,
  ROUND(INDEX_LENGTH / 1024 / 1024 / 1024, 2) AS index_gb
FROM information_schema.TABLES
WHERE TABLE_SCHEMA = 'your_db'
ORDER BY DATA_LENGTH DESC
LIMIT 20;

-- 评估 buffer pool 是否够用（关键！）
SHOW VARIABLES LIKE 'innodb_buffer_pool_size';     -- 默认 128M，生产建议物理内存的 50%~70%
SHOW STATUS  LIKE 'Innodb_buffer_pool_read%';
-- 命中率 = 1 - Innodb_buffer_pool_reads / Innodb_buffer_pool_read_requests
-- 持续低于 99% → buffer pool 不够，先调这个再考虑分表
```

### 二、垂直拆分 vs 水平拆分

```text
【垂直拆分：按业务/字段切】

垂直分库：          ┌─ 订单库 ─┐
                    │  用户库  │  按业务域切
                    └─ 商品库 ─┘

垂直分表：          ┌─ 主表（id, name, status, created_at）─┐  高频访问的小字段
                    └─ 扩展表（id, content, detail, ...） ─┘  大字段（TEXT/BLOB）

【水平拆分：按行切】

                    ┌─ t_order_0 ─┐
t_order  ──────────┤  t_order_1  │  按分片键取模/范围
                    ├─ t_order_2  │
                    └─ t_order_3 ─┘
```

| 维度 | **垂直拆分** | **水平拆分** |
|---|---|---|
| **切什么** | 业务/字段 | 行 |
| **解决的问题** | 单库表太多、单表列太多、大字段拖累 | **单表行数太多** |
| **提升并发** | ✅ 不同业务落到不同库（连接数分摊） | ✅ 不同分片落到不同库 |
| **实现难度** | **低**（改连接配置 + 代码重构） | **高**（路由、分布式 ID、跨片查询、分布式事务） |
| **扩容** | 简单（加库） | **难**（要重分布数据） |
| **是否影响 SQL** | 业务代码要改（表不在一起了） | **SQL 也要改**（无法再跨片 JOIN） |
| **是否解决单表过大** | ❌ 不解决 | ✅ 解决 |

**垂直分表的「大字段拆出」实践**：

```sql
-- 原表：一行 2KB（其中 1.5KB 是 TEXT）
CREATE TABLE article (
  id BIGINT PRIMARY KEY,
  title VARCHAR(200),
  author VARCHAR(50),
  content TEXT,                -- ← 大字段
  created_at DATETIME
);
-- 一页 16KB 只能放 8 行 → 列表页扫 100 行要读 13 页

-- 拆表
CREATE TABLE article (             -- 只有高频小字段
  id BIGINT PRIMARY KEY,
  title VARCHAR(200),
  author VARCHAR(50),
  created_at DATETIME
);
CREATE TABLE article_content (     -- 大字段单独放，按需查
  id BIGINT PRIMARY KEY,
  content TEXT
);
-- 现在一页能放几百行 → 列表页快了；详情页多一次按主键查（很快）
```

**收益**：**降低树高**（第 2 题）、列表页扫描的页数大幅下降、buffer pool 利用率提升。

### 三、分片键的选择（最关键的设计决策）

**选择原则**：

| 原则 | 说明 |
|---|---|
| **1. 高频查询必带** | 分片键应该是**几乎所有查询都会带的条件**，否则会广播到所有分片 |
| **2. 分布均匀** | 避免数据倾斜（如按 `status` 分片 → 99% 数据挤在一个分片） |
| **3. 尽量单分片命中** | 一次查询只落到一个分片，避免跨片聚合 |
| **4. 不可变** | 分片键一旦确定不能修改（改了就要跨片迁移数据） |
| **5. 与业务路由一致** | 比如按 `user_id` 分片，就要保证「查用户的东西都是按 user_id 查」 |

**四种分片算法**：

| 算法 | 例子 | 优点 | 缺点 |
|---|---|---|---|
| **取模** | `user_id % 16` | 分布均匀 | **扩容要重分布所有数据** |
| **范围** | `user_id` 按 0~1000 万、1000 万~2000 万 | 扩容简单（加新范围）、范围查询友好 | **可能热点**（新用户都落在最后一片） |
| **哈希取模** | `hash(order_no) % 16` | 分布均匀 | 与取模同样有扩容问题；范围查不了 |
| **一致性哈希** | 虚拟节点环 | **扩容只迁移 1/N 数据** | 实现复杂；分布需虚拟节点优化 |
| **双倍扩容法** | 16 → 32 | 扩容时**只需拆分现有分片**（0→0,16；1→1,17） | 需要一次重新分布（但可在线做） |

```sql
-- 取模分片的查询示例（应用层或中间件生成表名）
-- 路由规则：table_index = user_id % 16
SELECT * FROM t_order_3 WHERE user_id = 1001 AND ...;    -- 1001 % 16 = 9? 这里只是示意

-- 问题：按订单号查就不知道在哪个分片
SELECT * FROM t_order WHERE order_no = 'NO12345';        -- ❌ 要广播到 16 张表

-- 解决：基因法（把 user_id 的低位"种"进 order_no）
-- order_no 的最后 4 位 = user_id 的后 4 位
-- 这样按 order_no 查也能反推出分片
```

**「基因法」细节**：生成订单号时，把 `user_id` 的低 N 位拼到订单号末尾。查询时从订单号末尾取出这 N 位，就能算出分片。

### 四、分片后的四个难题

#### 难题 1：全局唯一 ID

| 方案 | 原理 | 优点 | 缺点 |
|---|---|---|---|
| **UUID** | 随机 128 位 | 完全无依赖 | **无序 → 页分裂**（第 2 题）；占空间大 |
| **雪花算法（Snowflake）** | `时间戳(41) + 机器ID(10) + 序列号(12)` | 趋势递增、高性能、无中心依赖 | 依赖时钟（**时钟回拨要处理**）；机器 ID 要分配 |
| **号段模式** | 数据库批量发号（一次取 1000 个），内存里递增 | 高性能、**ID 连续** | 依赖数据库；**服务重启会浪费号段** |
| **Redis INCR** | 原子自增 | 简单、性能好 | 依赖 Redis 可用性 |
| **数据库自增表** | 一张 `sequence` 表 | 简单 | 性能瓶颈、单点 |
| **美团 Leaf** | 号段 + 雪花双模式 | 生产验证过 | 需部署 |

```sql
-- 号段模式的表结构
CREATE TABLE leaf_alloc (
  biz_tag     VARCHAR(128) PRIMARY KEY,   -- 业务标识
  max_id      BIGINT NOT NULL DEFAULT 1,  -- 当前已分配的最大 id
  step        INT    NOT NULL DEFAULT 1000,
  description VARCHAR(256),
  update_time TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
);
INSERT INTO leaf_alloc (biz_tag, max_id, step) VALUES ('order', 1, 1000);

-- 取号段（原子更新，返回新值）
UPDATE leaf_alloc SET max_id = max_id + step WHERE biz_tag = 'order';
SELECT max_id, step FROM leaf_alloc WHERE biz_tag = 'order';
-- 应用拿到 [max_id - step + 1, max_id] 这段，在内存里逐个分配
```

**雪花算法的时钟回拨问题**：如果服务器时钟被 NTP 往回调整，可能生成重复 ID。处置：① 回拨小于阈值（如 5ms）就等待；② 回拨较大就报警 + 拒绝服务；③ **用「号段模式」或「Leaf 的 snowflake 模式（用 ZooKeeper 分配 workerId）」规避**。

#### 难题 2：跨片 JOIN

| 方案 | 说明 | 适用 |
|---|---|---|
| **冗余字段** | 把被 JOIN 的字段冗余到主表（如订单表冗余 `user_name`） | **最常用**，以空间换时间 |
| **字段合并成宽表** | 把常用的关联数据打平成一张宽表 | 报表场景 |
| **应用层组装** | 分别查多张表，在应用内存里拼装 | 数据量小时可行 |
| **广播表（小表）** | 把字典表/配置表在每个分片都存一份 | 小表 JOIN |
| **ER 分片** | 把有父子关系的表按同一个分片键分片（订单和订单明细都按 `user_id` 分） | **最优解，设计时就要考虑** |
| **搜索引擎** | 把需要 JOIN 的数据同步到 ES，用 ES 做查询 | 复杂查询、报表 |

```sql
-- ER 分片示例：订单表和订单明细表都按 user_id 分片
-- t_order_0 ... t_order_15        （分片键 user_id）
-- t_order_item_0 ... t_order_item_15   （分片键 user_id）
-- 这样「查某用户的所有订单 + 明细」只落到一个分片，可以在分片内 JOIN ✅
```

**设计期就要规划 ER 分片**——这是分库分表方案里最容易做对也最容易做错的地方。

#### 难题 3：跨片分页与排序

```sql
-- 需求：按 amount 倒序，取第 10 页（每页 20 条）
-- 广播到 16 个分片，每个分片执行：
SELECT * FROM t_order_N ORDER BY amount DESC LIMIT 200, 20;
-- ❌ 错误！每个分片取 offset 200 是错的（各分片的第 200 条不是全局的第 200 条）

-- 正确做法：每个分片取前 (offset + limit) 条，归并后再取
SELECT * FROM t_order_N ORDER BY amount DESC LIMIT 0, 220;   -- 每片取前 220
-- 应用层/中间件归并 16 × 220 = 3520 条 → 排序 → 取第 201~220 条
```

**代价分析**：

| 操作 | 代价 |
|---|---|
| 广播查询 | N 个分片各一次查询（**N 倍放大**） |
| 内存归并 | 每片取 `offset + limit` 条 → 共 `N × (offset + limit)` 条要在内存排序 |
| 深分页 | offset 越大，归并的数据越多，**性能急剧恶化** |

**优化**：
1. **分片时就让排序键与分片键对齐**（比如按 `user_id` 分片，查询也按 `user_id` 过滤 + 排序 → 单分片）
2. **限制深分页**（业务上不让翻太深）
3. **游标分页**（但跨片游标很复杂）
4. **ES 扛复杂查询**（把数据同步到 ES，分页排序都交给 ES）

#### 难题 4：分布式事务

| 方案 | 一致性 | 复杂度 | 适用 |
|---|---|---|---|
| **不做分布式事务**（设计规避） | 最终一致 | 低 | **首选**：把相关数据放同一分片（ER 分片） |
| **本地消息表** | 最终一致 | 中 | 跨片异步操作 |
| **TCC**（Try-Confirm-Cancel） | 最终一致 | 高 | 资金类，要求较高一致性 |
| **Saga** | 最终一致 | 中高 | 长流程业务，有补偿逻辑 |
| **Seata AT 模式** | 最终一致 | 中 | 基于 undo 快照的自动回滚 |
| **XA** | 强一致 | 中 | **性能差，生产极少用** |

**最重要的原则：能用「设计规避」就不要用「分布式事务」。**
把需要事务保证的操作放到同一个分片（ER 分片），是成本最低的方案。

### 五、扩容迁移

**取模分片扩容的问题**：

```text
原：user_id % 4  → 4 个分片
扩：user_id % 8  → 8 个分片
结果：几乎所有的数据都要迁移！（因为 hash 值全变了）
```

**双倍扩容法（推荐）**：

```text
原：user_id % 4  → 分片 0, 1, 2, 3
扩：user_id % 8  → 分片 0..7
规则：分片 0 拆成 0 和 4；分片 1 拆成 1 和 5；分片 2 拆成 2 和 6；分片 3 拆成 3 和 7
     → 只需要「拆分」，不需要「重新哈希」，迁移量可控（通常是 50%）
```

**在线迁移的标准流程**：

```text
① 双写：新数据同时写旧表和新表
② 存量迁移：用工具（如 ShardingSphere-Scaling、DataX、pt-archiver）把老数据搬过去
③ 数据校验：对比新旧表的数据一致性
④ 灰度读：先让少量流量读新表，观察
⑤ 全量切读：全部读新表
⑥ 停双写：只写新表
⑦ 清理旧表
```

**⚠️ 每一步都要有回滚方案**。「双写」期间如果新表写失败，要有降级策略（至少保证旧表写成功）。

### 六、中间件

| 中间件 | 类型 | 语言/部署 | 特点 |
|---|---|---|---|
| **ShardingSphere-JDBC** | 客户端 SDK | Java | 无额外部署、性能好、社区活跃（Apache 顶级项目） |
| **ShardingSphere-Proxy** | 代理层 | 独立进程 | 语言无关、可集中管理 |
| **MyCat** | 代理层 | 独立进程 | 较老，社区活跃度下降 |
| **Vitess** | 代理层 | 独立进程 | YouTube 出品，K8s 友好，运维工具完善 |
| **TiDB / OceanBase** | 原生分布式 | 独立集群 | **不用改 SQL**（协议兼容 MySQL），但成本高 |

**ShardingSphere 的配置示例（YAML）**：

```yaml
dataSources:
  ds_0:
    dataSourceClassName: com.zaxxer.hikari.HikariDataSource
    driverClassName: com.mysql.cj.jdbc.Driver
    jdbcUrl: jdbc:mysql://10.20.3.10:3306/order_db_0
    username: app
    password: xxx
  ds_1:
    dataSourceClassName: com.zaxxer.hikari.HikariDataSource
    driverClassName: com.mysql.cj.jdbc.Driver
    jdbcUrl: jdbc:mysql://10.20.3.11:3306/order_db_1
    username: app
    password: xxx

rules:
  - !SHARDING
    tables:
      t_order:
        actualDataNodes: ds_${0..1}.t_order_${0..7}       # 2 库 × 8 表
        tableStrategy:
          standard:
            shardingColumn: user_id
            shardingAlgorithmName: t_order_inline
        keyGenerateStrategy:
          column: order_id
          keyGeneratorName: snowflake
    shardingAlgorithms:
      t_order_inline:
        type: INLINE
        props:
          algorithm-expression: t_order_${user_id % 8}
    keyGenerators:
      snowflake:
        type: SNOWFLAKE
        props:
          worker-id: 1
```

**选型建议**：
- **Java 技术栈 + 想少运维** → **ShardingSphere-JDBC**
- **多语言 / 想集中管理** → ShardingSphere-Proxy 或 Vitess
- **预算充足 + 不想改 SQL** → TiDB（协议兼容 MySQL，但要注意：**TiDB 的事务模型和热点问题与 MySQL 不同**）
:::

:::拓展
**分区表：不用中间件的「轻量分表」**

MySQL 5.1+ 原生支持分区（单库内，逻辑上是一张表，物理上多个文件）。

```sql
-- RANGE 分区（最常用：按时间）
CREATE TABLE t_order (
  id BIGINT NOT NULL,
  created_at DATETIME NOT NULL,
  amount DECIMAL(12,2),
  PRIMARY KEY (id, created_at)      -- ★ 分区键必须包含在主键/唯一键中
) ENGINE=InnoDB
PARTITION BY RANGE (TO_DAYS(created_at)) (
  PARTITION p202607 VALUES LESS THAN (TO_DAYS('2026-08-01')),
  PARTITION p202608 VALUES LESS THAN (TO_DAYS('2026-09-01')),
  PARTITION p202609 VALUES LESS THAN (TO_DAYS('2026-10-01')),
  PARTITION pmax    VALUES LESS THAN MAXVALUE
);

-- 查询时自动做「分区裁剪」（只扫命中的分区，EXPLAIN 的 partitions 列会显示）
EXPLAIN SELECT * FROM t_order WHERE created_at >= '2026-09-01'\G
-- partitions: p202609,pmax

-- 归档历史数据：毫秒级
ALTER TABLE t_order DROP PARTITION p202607;

-- 新增分区
ALTER TABLE t_order REORGANIZE PARTITION pmax INTO (
  PARTITION p202610 VALUES LESS THAN (TO_DAYS('2026-11-01')),
  PARTITION pmax    VALUES LESS THAN MAXVALUE
);
```

**分区表 vs 分库分表**：

| | 分区表（MySQL 原生） | 分库分表（中间件） |
|---|---|---|
| 部署复杂度 | **无**（不需要中间件） | 高 |
| SQL 兼容性 | **完全兼容**（就是一张表） | 要改 SQL（不能跨片 JOIN） |
| 跨分区查询 | ✅ 支持（自动合并） | ❌ 广播 + 归并 |
| 跨分区唯一索引 | ❌ **分区键必须在唯一键中** | ❌ 全局唯一要靠外部生成 |
| 提升并发 | ❌ **没有**（还是单实例） | ✅ 有 |
| 适用 | **单表行数大 + 定期删历史** | 需要水平扩展并发和容量 |

**⚠️ 分区表最常见的坑**：`PRIMARY KEY (id)` 会报错——**分区键必须是主键的一部分**。所以按时间分区时主键必须写成 `(id, created_at)`，这会带来一个副作用：**`id` 不再全局唯一**（要看组合）。

**「先分区表，后分库分表」是一个务实的演进路径**：分区表能解决「单表太大 + 定期删历史」，成本极低；只有当**单实例的并发/容量**也撑不住时，才上分库分表。

**分片 vs 分区的概念澄清**

| 术语 | 场景 | 说明 |
|---|---|---|
| **分区（Partitioning）** | 单实例内 | MySQL 原生，一张表物理上分文件 |
| **分表（Sharding）** | 单库多表 | 手工或中间件路由，如 `t_order_0`~`t_order_15` |
| **分库（Database Sharding）** | 多实例 | 库级别的拆分 |
| **分片（Shard）** | 泛称 | MongoDB 里的分片是「副本集 + 路由」的分布式集群 |
:::

:::追问
**Q：分片键选错了会怎样？**
最典型的错误：**选了一个查询不会带的字段**。比如订单表按 `order_id` 分片，但 90% 的查询是按 `user_id` 查 → **每次查询都要广播到所有分片，性能比不分片还差**（N 次查询 + 归并）。
**纠正原则**：分片键应该选**出现频率最高的 WHERE 条件**。如果实在有多组高频查询（按 `user_id` 和按 `order_no`），用「基因法」把分片信息编码进去，或者用一张「映射表」记录 `order_no → user_id`。

**Q：分片后 `count(*)`、`ORDER BY`、`GROUP BY` 怎么办？**
都要**广播 + 归并**：
- `count(*)` → 各分片 count 后求和（**这个能并行，代价可接受**）
- `ORDER BY ... LIMIT n` → 各分片取前 `offset + n` 条，归并排序（**深分页代价大**）
- `GROUP BY` → 各分片分组后归并（**要处理跨片的相同 key**）
- `MIN/MAX/SUM/AVG` → `MIN/MAX/SUM` 可简单归并；**`AVG` 不能简单平均**（要各分片返回 `SUM` 和 `COUNT`，再算总平均）

**`AVG` 的陷阱**：
```sql
-- ❌ 错误：AVG(AVG(x))
-- 分片 1 有 1 行（值 100）→ AVG = 100
-- 分片 2 有 100 行（值都是 1）→ AVG = 1
-- 简单平均 = (100 + 1) / 2 = 50.5   ← 错的！
-- 正确 = (100 + 100) / 101 = 1.98

-- ✅ 正确：各分片返回 SUM 和 COUNT，应用层汇总
SELECT SUM(s), SUM(c) FROM (
  SELECT SUM(amount) AS s, COUNT(*) AS c FROM t_order_0
  UNION ALL
  SELECT SUM(amount), COUNT(*) FROM t_order_1
  -- ...
) t;
-- AVG = SUM(s) / SUM(c)
```

**Q：分布式 ID 用 UUID 有什么问题？**
除了「无序导致页分裂」之外，还有：
① **占空间**：UUID 是 36 字符（字符串）或 16 字节（BINARY），而 BIGINT 是 8 字节 → 索引更大、页数更多；
② **可读性差**：排查问题时无法从 ID 看出时间；
③ **不适合做业务单号**（太长、无法给用户看）。
**结论**：**用雪花算法（BIGINT，趋势递增）或号段模式。** 如果必须用 UUID，用 `BINARY(16)` 存储（`UUID_TO_BIN(uuid, 1)` 可以重排成时间有序的格式）。

```sql
-- MySQL 8.0 的 UUID 优化
SELECT UUID_TO_BIN(UUID(), 1);        -- 第二个参数 1 表示重排为时间有序
SELECT BIN_TO_UUID(uuid_col, 1) FROM t;
```

**Q：为什么不直接用 TiDB / OceanBase？**
它们确实**不用改 SQL**（协议兼容 MySQL），运维也简单。但代价是：
① **成本高**（需要多节点集群）；
② **热点问题**（TiDB 的自增主键会集中在单个 Region，需要 `AUTO_RANDOM` 或 `SHARD_ROW_ID_BITS`）；
③ **性能特征不同**（分布式事务的延迟高于单机 MySQL）；
④ **需要专门的运维能力**。
**适用判断**：如果团队没有分库分表的经验、数据量在 TB 级、预算允许，TiDB 是比自研分片更好的选择。
:::

:::锚点
**⭐ 这是你整份手册里「项目锚点」最强的一道题——因为你在 MongoDB 上做过分片，而且是真实做过。**

```javascript
// MongoDB 分片集群的配置（RRM 场景）
// ① 启用分片
sh.enableSharding("oasis")

// ② 选分片键并建索引（必须！）
db.clbDetail.createIndex({ taskId: 1, apSN: 1, RI: 1 })
sh.shardCollection("oasis.clbDetail", { taskId: "hashed" })
// 或范围分片
sh.shardCollection("oasis.clbDetail", { taskId: 1 })

// ③ 查看分片分布
sh.status()
db.clbDetail.getShardDistribution()

// ④ 查看查询是否命中单分片（关键指标）
db.clbDetail.find({ taskId: "T001" }).explain("executionStats")
// 关注 shards 字段：只有目标分片被访问 vs 广播到所有分片
```

**面试话术（这段可以讲得很厚）**：

> 「分库分表我虽然在 MySQL 上没做过生产落地，但**分片这件事我在 MongoDB 上是实操过的**，而且 RRM 项目正好是海量上报数据的场景，所以我对这类问题的取舍有实际体会。

> 我们的集合 `clbDetail` 存的是 RRM 调优任务的上报数据，数据量很大，查询也慢。做过的优化分三层：**第一层是索引**——查 `explain()` 发现是 COLLSCAN，建了复合索引 `{taskId, apSN, RI}`；**第二层是分片**——因为单机容量和 IO 撑不住，做了分片，查询从秒级降到毫秒。

> 关于**分片键的选择**，我的体会是：**分片键必须选「最高频查询一定会带的字段」**。我们选 `taskId` 就是因为几乎所有查询都是围绕某个调优任务展开的——`taskId` 是一个任务维度的天然分区，既能保证单分片命中，又能保证数据分布相对均匀。**如果选错了，比如选一个查询不带的字段，每次查询都要广播到所有分片，比不分片还慢。**

> 另外我还注意到一个和 MySQL 分库分表完全对应的点：**MongoDB 的复合索引 `{taskId, apSN, RI}` 和分片键 `taskId` 是对齐的**——这一点很重要，因为**分片键在索引的最左前缀位置，才能保证「查询能路由到单分片」+「分片内能用索引」两件事同时成立**。这就是 MySQL 分库分表里说的『分片键应该和查询的最左前缀对齐』。

> 落到 MySQL 分库分表，我知道的几个关键难点：**① 全局唯一 ID（雪花算法或号段模式，不能用无序 UUID 因为会导致页分裂）；② 跨片 JOIN（最佳解是 ER 分片，把关联表按同一分片键分，从源头避免跨片）；③ 跨片分页（各分片取前 offset+limit 条再归并，深分页代价很大）；④ 扩容（用双倍扩容法避免全量重分布）。** 还有一个重要的原则是：**分库分表是最后手段，前面还有缓存、读写分离、垂直拆分、分区表这些成本更低的方案。**」

**这段为什么好**：① 讲了你真实做过的分片和索引优化；② 展示了你对分片键选择的理解（这是最核心的设计决策）；③ 用「复合索引最左前缀和分片键对齐」把 Mongo 经验和 MySQL 知识打通了；④ 主动说出 MySQL 分库分表的难点和「最后手段」原则，说明你没有盲目上手。

**唯一不能做的**：**不要说「我们做了 MySQL 分库分表」。** 说「分片这件事我在 Mongo 上做过，MySQL 的分库分表我知道这些难点和思路」。
:::

---

## 20. MySQL 与 PostgreSQL 兼容适配 ★

:::概念
**MySQL 和 PostgreSQL 虽然都兼容 SQL 标准，但「方言」差异很大**，尤其在：分页语法、UPSERT、空值函数、字符串拼接、自增列、大小写敏感、DDL 能否回滚、`GROUP BY` 严格性。
**做兼容适配的正确姿势：不是写一套 SQL 适配两边，而是「用抽象层（ORM/MyBatis 的 databaseId）+ 最小公共子集」。**
:::

:::提问
- MySQL 和 PostgreSQL 有哪些语法差异？
- 你们怎么做数据库兼容的？
- 分页写法两边有什么不同？
- UPSERT 怎么做？
- 为什么你们要同时支持两个数据库？
:::

:::答案
### 一、语法差异全表（适配工作核心）

| 场景 | **MySQL** | **PostgreSQL** | 备注 |
|---|---|---|---|
| **分页** | `LIMIT n OFFSET m`<br>**`LIMIT m, n`**（MySQL 特有） | `LIMIT n OFFSET m`<br>**不支持 `LIMIT m, n`** | ★ 最常踩的坑 |
| **UPSERT** | `INSERT ... ON DUPLICATE KEY UPDATE` | `INSERT ... ON CONFLICT (col) DO UPDATE SET` | ★ 语义略有不同 |
| **冲突即忽略** | `INSERT IGNORE` | `ON CONFLICT DO NOTHING` | |
| **空值替换** | `IFNULL(a, b)` | `COALESCE(a, b)` | **`COALESCE` 两边都支持，优先用它** |
| **NULL 判断** | `ISNULL(a)` | 无（用 `a IS NULL`） | 用 `a IS NULL` 最通用 |
| **字符串拼接** | `CONCAT(a, b)`<br>`\|\|` 默认是 OR | **`\|\|`**（标准） | MySQL 要设 `PIPES_AS_CONCAT` 才能用 `\|\|` |
| **引号** | 反引号 `` `col` `` | **双引号 `"col"`** | ★ 最直观的差异 |
| **字符串字面量** | 单引号 / 双引号都可 | **只认单引号**；双引号是标识符 | ⚠️ 危险 |
| **自增列** | `AUTO_INCREMENT` | `SERIAL` / `GENERATED ALWAYS AS IDENTITY` | |
| **随机数** | `RAND()` | `RANDOM()` | |
| **当前时间** | `NOW()` / `CURDATE()` / `UNIX_TIMESTAMP()` | `NOW()` / `CURRENT_DATE` / `EXTRACT(EPOCH FROM NOW())` | `NOW()` 通用 |
| **日期格式化** | `DATE_FORMAT(ts, '%Y-%m-%d')` | **`TO_CHAR(ts, 'YYYY-MM-DD')`** | 差异大 |
| **日期加减** | `DATE_ADD(ts, INTERVAL 1 DAY)` | `ts + INTERVAL '1 day'` | |
| **类型转换** | `CAST(x AS SIGNED/CHAR)` | `CAST(x AS INTEGER/TEXT)` | |
| **布尔类型** | `TINYINT(1)`，`TRUE`/`FALSE` 是 1/0 | **原生 `BOOLEAN`** | 驱动映射不同 |
| **大小写** | 表名大小写依赖 OS（Linux 敏感） | **标识符默认折叠为小写**，双引号才保留大小写 | |
| **`GROUP BY`** | 5.7 起默认 `ONLY_FULL_GROUP_BY`（严格） | **一直严格** | |
| **DDL 事务** | ❌ **DDL 隐式提交，不可回滚** | ✅ **DDL 在事务里可回滚** | ★ 本质差异 |
| **`UPDATE ... LIMIT`** | ✅ 支持 | ❌ 不支持 | |
| **`REPLACE INTO`** | ✅ 支持 | ❌ 不支持（用 `ON CONFLICT`） | |
| **`RETURNING`** | ❌ 不支持 | ✅ `INSERT/UPDATE/DELETE ... RETURNING *` | PG 很强 |
| **JSON** | `JSON` 类型 + `->` / `->>` | `JSONB`（更高效、可索引）+ `->` / `->>` | |
| **序列** | `AUTO_INCREMENT`（隐式） | **显式 `SEQUENCE`** | |
| **窗口函数** | 8.0+ 支持 | 长期支持 | |
| **CTE（`WITH`）** | 8.0+ 支持 | 长期支持；支持 `WITH RECURSIVE` | |
| **`TRUNCATE` 事务** | 不可回滚 | **可回滚**（在事务内） | |

### 二、分页：最容易踩的坑

```sql
-- MySQL：两种写法都支持
SELECT * FROM t_order ORDER BY id LIMIT 20 OFFSET 100;
SELECT * FROM t_order ORDER BY id LIMIT 100, 20;       -- MySQL 特有语法

-- PostgreSQL：只支持第一种
SELECT * FROM t_order ORDER BY id LIMIT 20 OFFSET 100;
SELECT * FROM t_order ORDER BY id LIMIT 100, 20;       -- ❌ 语法错误
```

**适配策略**：

1. **统一用 `LIMIT n OFFSET m`**（两边都支持）← **最简单有效**
2. ORM 层用 `PageHelper` / MyBatis-Plus 的分页插件，它根据 `databaseId` 生成不同 SQL
3. 自己写方言类：

```java
// 简化的方言抽象
public interface Dialect {
    String buildPageSql(String sql, int offset, int limit);
}

public class MySqlDialect implements Dialect {
    @Override
    public String buildPageSql(String sql, int offset, int limit) {
        return sql + " LIMIT " + offset + ", " + limit;
    }
}

public class PostgreSqlDialect implements Dialect {
    @Override
    public String buildPageSql(String sql, int offset, int limit) {
        return sql + " LIMIT " + limit + " OFFSET " + offset;
    }
}
```

**⚠️ `OFFSET` 的语义在两个库里是一致的**（都是「跳过 m 行」）。**但 MySQL 的 `LIMIT m, n` 里 `m` 是 offset、`n` 是行数**，顺序和 PostgreSQL 的 `LIMIT n OFFSET m` **相反**——这是最容易写错的地方。

```sql
-- 这两个是等价的（MySQL）
SELECT * FROM t LIMIT 100, 20;              -- 跳过 100 行，取 20 行
SELECT * FROM t LIMIT 20 OFFSET 100;        -- 同上
--                             ↑ offset
```

### 三、UPSERT：语义差异微妙

```sql
-- MySQL
INSERT INTO t_user_stat (user_id, order_count, updated_at)
VALUES (1001, 1, NOW())
ON DUPLICATE KEY UPDATE
  order_count = order_count + 1,
  updated_at  = NOW();

-- PostgreSQL
INSERT INTO t_user_stat (user_id, order_count, updated_at)
VALUES (1001, 1, NOW())
ON CONFLICT (user_id) DO UPDATE SET
  order_count = t_user_stat.order_count + 1,
  updated_at  = NOW();
```

**四个关键差异**：

| 差异 | MySQL | PostgreSQL |
|---|---|---|
| **冲突判定依据** | **任意唯一索引/主键冲突**（不指定具体是哪个） | **必须显式指定冲突列** `ON CONFLICT (col)` |
| **`INSERT IGNORE` 的副作用** | 会**忽略所有错误**（包括数据截断、外键失败、NULL 约束）—— 这是个大坑 | `ON CONFLICT DO NOTHING` 只忽略冲突 |
| **`VALUES()` 函数** | 旧写法 `VALUES(col)` 引用待插入值（**8.0.20 起已废弃**） | 用 `EXCLUDED.col` |
| **自增 id 消耗** | 即使走了 UPDATE 分支，**也会消耗一个自增值** | 同理会消耗序列值 |

```sql
-- ⚠️ MySQL 的 INSERT IGNORE 会吞掉所有错误
INSERT IGNORE INTO t_user (id, name) VALUES (1, 'a very long name exceeding column length');
-- 结果：静默截断或忽略，不报错 → 数据悄无声息地错了
-- 正确做法：用 ON DUPLICATE KEY UPDATE 只处理冲突，让其他错误正常抛出

-- MySQL 8.0.20+ 推荐写法（用别名替代 VALUES()）
INSERT INTO t_user_stat (user_id, order_count)
VALUES (1001, 1) AS new
ON DUPLICATE KEY UPDATE order_count = t_user_stat.order_count + new.order_count;
-- 旧写法（已废弃）：
-- ON DUPLICATE KEY UPDATE order_count = order_count + VALUES(order_count);

-- PostgreSQL 用 EXCLUDED 引用待插入的值
INSERT INTO t_user_stat (user_id, order_count)
VALUES (1001, 1)
ON CONFLICT (user_id) DO UPDATE SET
  order_count = t_user_stat.order_count + EXCLUDED.order_count;
```

### 四、空值函数与字符串函数

```sql
-- ① 空值替换：COALESCE 是两边都支持的标准函数 → 优先用它
-- MySQL
SELECT IFNULL(name, '未知') FROM t_user;
-- PostgreSQL
SELECT COALESCE(name, '未知') FROM t_user;
-- ✅ 通用写法
SELECT COALESCE(name, '未知') FROM t_user;

-- ② 字符串拼接
-- MySQL
SELECT CONCAT(first_name, ' ', last_name) FROM t_user;
-- PostgreSQL
SELECT first_name || ' ' || last_name FROM t_user;
-- ✅ 通用：还是用 CONCAT（PostgreSQL 也支持 CONCAT 函数！）
SELECT CONCAT(first_name, ' ', last_name) FROM t_user;
-- ⚠️ 注意：MySQL 的 CONCAT 遇到 NULL 返回 NULL；PostgreSQL 的 CONCAT 会跳过 NULL
-- 如果需要一致：MySQL 用 CONCAT_WS 或先 COALESCE

-- ③ 日期格式化（差异大，没法统一）
-- MySQL
SELECT DATE_FORMAT(created_at, '%Y-%m-%d %H:%i:%s') FROM t_order;
-- PostgreSQL
SELECT TO_CHAR(created_at, 'YYYY-MM-DD HH24:MI:SS') FROM t_order;
-- ✅ 折中：在应用层格式化（最简单）

-- ④ 日期加减
-- MySQL
SELECT DATE_ADD(NOW(), INTERVAL 7 DAY);
-- PostgreSQL
SELECT NOW() + INTERVAL '7 days';
-- ✅ 更通用：用参数传入起止时间，避免在 SQL 里做日期运算
```

**适配原则：能用标准 SQL 就用标准 SQL。**

| 需求 | 标准 SQL 写法（两边都支持） |
|---|---|
| 空值替换 | `COALESCE(a, b)` |
| 条件取值 | `CASE WHEN ... THEN ... ELSE ... END` |
| 字符串拼接 | `CONCAT(a, b)`（注意 NULL 语义差异） |
| 类型转换 | `CAST(x AS ...)`（但类型名不同） |
| 当前时间 | `CURRENT_TIMESTAMP` |
| 分页 | `LIMIT n OFFSET m` |

### 五、DDL 事务：一个本质差异

```sql
-- PostgreSQL：DDL 可以在事务里回滚
BEGIN;
CREATE TABLE t_temp (id INT);
ALTER TABLE t_user ADD COLUMN new_col INT;
ROLLBACK;                    -- ✅ 表没建、列没加，全部回滚！
-- PostgreSQL 因为这一点，迁移脚本可以做到「原子性」

-- MySQL：DDL 隐式提交，无法回滚
START TRANSACTION;
CREATE TABLE t_temp (id INT);       -- ★ 这里隐式提交了前面的事务！
ALTER TABLE t_user ADD COLUMN new_col INT;
ROLLBACK;                            -- ❌ 无效，前面的 DDL 已经生效
-- 结果：表建了、列加了，回滚不掉
```

**工程影响**：

| 场景 | MySQL | PostgreSQL |
|---|---|---|
| 迁移脚本失败 | **部分成功，要手工清理** | 全部回滚，干净 |
| 灰度发布 | 需要「向前兼容」的设计 | 可以整批回滚 |
| 分布式事务里的 DDL | 不可能 | 可以 |

**⚠️ MySQL 里 `TRUNCATE` / `ALTER` / `CREATE` / `DROP` 都是隐式提交点**——这是第 17 题提过的同一个知识点。**写迁移脚本时必须假设「每一步都可能部分成功」。**

### 六、兼容适配的工程实践

#### 实践 1：MyBatis 的 `databaseId`

```xml
<!-- mybatis-config.xml -->
<databaseIdProvider type="DB_VENDOR">
    <property name="MySQL"      value="mysql"/>
    <property name="PostgreSQL" value="postgresql"/>
</databaseIdProvider>
```

```xml
<!-- 同一个 Mapper 里按 databaseId 写不同 SQL -->
<select id="selectPage" resultType="Order">
    <if test="_databaseId == 'mysql'">
        SELECT * FROM t_order ORDER BY id LIMIT #{offset}, #{limit}
    </if>
    <if test="_databaseId == 'postgresql'">
        SELECT * FROM t_order ORDER BY id LIMIT #{limit} OFFSET #{offset}
    </if>
</select>

<!-- UPSERT 的兼容 -->
<insert id="upsertStat">
    <if test="_databaseId == 'mysql'">
        INSERT INTO t_user_stat (user_id, order_count) VALUES (#{userId}, 1)
        ON DUPLICATE KEY UPDATE order_count = order_count + 1
    </if>
    <if test="_databaseId == 'postgresql'">
        INSERT INTO t_user_stat (user_id, order_count) VALUES (#{userId}, 1)
        ON CONFLICT (user_id) DO UPDATE SET order_count = t_user_stat.order_count + 1
    </if>
</insert>
```

**MyBatis 会自动根据连接的元数据识别数据库类型**，不需要手工配置。

#### 实践 2：统一用「最小公共子集」

| 决策 | 做法 |
|---|---|
| 分页 | **统一 `LIMIT n OFFSET m`** |
| 空值 | **统一 `COALESCE`** |
| 时间格式化 | **放到应用层**，SQL 里只做过滤和排序 |
| UPSERT | **尽量避免**，改成「先查后写 + 乐观锁」或抽象成方法 |
| 自增主键 | 用 ORM 的 `useGeneratedKeys`，别手写 |
| 布尔 | 用 `TINYINT`/`SMALLINT` 显式存储，别依赖原生 BOOLEAN |
| 标识符 | **统一小写 + 下划线**，避免大小写问题 |
| 关键字 | 避开保留字做列名（如 `order`、`user`、`desc`） |

**列名避开保留字**：

```sql
-- ❌ 危险：order 是保留字
CREATE TABLE t (id INT, order INT);

-- PostgreSQL 里必须加双引号（并且以后每次都要加！）
CREATE TABLE t (id INT, "order" INT);
-- MySQL 里加反引号
CREATE TABLE t (id INT, `order` INT);

-- ✅ 推荐：加前缀或换名
CREATE TABLE t (id INT, order_no INT, sort_order INT);
```

#### 实践 3：CI 阶段做双库测试

```yaml
# docker-compose.yml：本地同时起 MySQL 和 PostgreSQL
services:
  mysql:
    image: mysql:8.0
    environment:
      MYSQL_ROOT_PASSWORD: root
      MYSQL_DATABASE: test_db
    ports: ["3306:3306"]

  postgres:
    image: postgres:16
    environment:
      POSTGRES_PASSWORD: root
      POSTGRES_DB: test_db
    ports: ["5432:5432"]
```

```xml
<!-- pom.xml：用 Maven profile 切换数据库跑同一套集成测试 -->
<profiles>
    <profile>
        <id>mysql</id>
        <properties><db.url>jdbc:mysql://localhost:3306/test_db</db.url></properties>
    </profile>
    <profile>
        <id>postgres</id>
        <properties><db.url>jdbc:postgresql://localhost:5432/test_db</db.url></properties>
    </profile>
</profiles>
```

**「同一套集成测试跑两个库」是兼容适配的核心保障**——比人工 review SQL 靠谱得多。

#### 实践 4：用 Testcontainers 做真实数据库测试

```java
@Testcontainers
class OrderRepositoryTest {

    @Container
    static MySQLContainer<?> mysql = new MySQLContainer<>("mysql:8.0");

    @Container
    static PostgreSQLContainer<?> postgres = new PostgreSQLContainer<>("postgres:16");

    // 同一套测试逻辑，对两个容器各跑一遍
}
```

### 七、兼容适配的取舍

**先问：真的需要同时支持两个数据库吗？**

| 情况 | 建议 |
|---|---|
| **客户环境既有 MySQL 也有 PG**（如私有化交付） | **必须适配**，用抽象层 + 最小公共子集 |
| **自己选型，能定一个** | **别适配**，选定一个，把优化做透 |
| **国产化替代需求** | 适配（可能还要加达梦、GaussDB、OceanBase） |
| **历史遗留要迁移** | 适配是过渡，最终要收敛到一个 |

**适配的隐性成本**：
1. **两套测试**（CI 时间翻倍）
2. **两倍的 SQL review 成本**
3. **性能特征不同**（在 MySQL 上快的 SQL 在 PG 上可能慢，反之亦然）
4. **无法使用任何一方的特有功能**（JSONB、`RETURNING`、全文索引、分区表语法都不同）
5. **ORM 的分页插件要各自配置**

**所以「能只支持一个就只支持一个」是对的工程判断。** 如果必须适配，就用「最小公共子集 + 抽象层 + 双库测试」这套组合拳。
:::

:::拓展
**ORM 层的差异（Hibernate / MyBatis-Plus）**

| 场景 | MySQL | PostgreSQL |
|---|---|---|
| 分页插件 | `PageHelper`（MySQL 方言） | 需配置对应的方言 |
| 主键生成 | `IDENTITY`（`AUTO_INCREMENT`） | `IDENTITY` 或 `SEQUENCE` |
| 布尔映射 | `TINYINT(1)` ↔ `Boolean` | `BOOLEAN` ↔ `Boolean` |
| 大文本 | `TEXT` / `LONGTEXT` | `TEXT` |
| 时间类型 | `DATETIME` / `TIMESTAMP` | `TIMESTAMP` / `TIMESTAMPTZ` |
| JSON | `JSON` | `JSONB`（推荐，可索引） |

```java
// MyBatis-Plus 的分页插件需要指定 DbType
@Bean
public MybatisPlusInterceptor mybatisPlusInterceptor() {
    MybatisPlusInterceptor interceptor = new MybatisPlusInterceptor();
    // 需要根据实际数据库设置；多数据库场景可用 DynamicTableNameInnerInterceptor 或自定义
    interceptor.addInnerInterceptor(new PaginationInnerInterceptor(DbType.MYSQL));
    return interceptor;
}
```

**MyBatis-Plus 的 `DbType` 是静态配置的**——如果同一套代码要跑两个库，需要自己做动态判断（比如用 `@ConditionalOnProperty` 或者自定义 `PaginationInnerInterceptor`）。

**`RETURNING`：PostgreSQL 的杀手锏（MySQL 没有）**

```sql
-- PostgreSQL：INSERT 后直接返回生成的值（包括自增 id 和其他列的默认值）
INSERT INTO t_order (user_id, amount) VALUES (1001, 99.00)
RETURNING id, order_no, created_at;

-- PostgreSQL：UPDATE 后返回被改的行
UPDATE t_order SET status = 3 WHERE status = 2
RETURNING id, status;

-- PostgreSQL：DELETE 后返回被删的行（做"移入回收站"很方便）
DELETE FROM t_order WHERE created_at < '2025-01-01'
RETURNING *;

-- MySQL 只能用：
INSERT INTO t_order (user_id, amount) VALUES (1001, 99.00);
SELECT LAST_INSERT_ID();        -- 只能拿自增 id，拿不到其他列的默认值
-- 或者（8.0 不推荐）
SELECT * FROM t_order WHERE id = LAST_INSERT_ID();
```

**MySQL 的 `LAST_INSERT_ID()` 有两个坑**：
① **它是连接级的**，必须用同一个连接（连接池下要注意，但 MyBatis 的 `useGeneratedKeys` 在同一个 PreparedStatement 里处理，是安全的）；
② **批量插入时只返回第一行的 id**（后续 id 是连续的，可以用 `id + n` 推算，但不保证在并发下安全）。

**JSON 类型：PostgreSQL 的 JSONB 强太多**

```sql
-- MySQL 8.0
SELECT * FROM t_order WHERE JSON_EXTRACT(ext, '$.channel') = 'app';
SELECT * FROM t_order WHERE ext->>'$.channel' = 'app';
-- 8.0.17+ 支持多值索引
ALTER TABLE t_order ADD INDEX idx_channel ((CAST(ext->>'$.channel' AS CHAR(20))));

-- PostgreSQL
SELECT * FROM t_order WHERE ext->>'channel' = 'app';
-- JSONB 可以建 GIN 索引，支持任意路径查询
CREATE INDEX idx_ext ON t_order USING GIN (ext);
SELECT * FROM t_order WHERE ext @> '{"channel": "app"}';
```

**结论**：**如果 JSON 字段是核心查询维度，PostgreSQL 的 JSONB + GIN 索引优势明显；MySQL 8.0 的函数索引/多值索引能做到，但灵活性和性能不如。**
:::

:::追问
**Q：为什么会有「同时支持 MySQL 和 PostgreSQL」的需求？**
三类原因：
① **私有化交付**：不同客户环境预装的数据库不同，产品必须两边都能跑；
② **国产化/信创要求**：某些环境要求用国产数据库（达梦、GaussDB、OceanBase 等，通常兼容 MySQL 或 PG 协议）；
③ **历史遗留**：公司内有多个团队用了不同的库，中间件/SDK 必须都支持。
**如果是「自己新起项目」，没有以上任一需求，就不要适配。**

**Q：`IFNULL` 和 `COALESCE` 有什么区别？为什么推荐 `COALESCE`？**
| | `IFNULL(a, b)` | `COALESCE(a, b, c, ...)` |
|---|---|---|
| 参数个数 | **只有 2 个** | 任意多个 |
| 标准 | MySQL 特有 | **SQL 标准，两边都支持** |
| 语义 | `a` 为 NULL 返回 `b` | 返回**第一个非 NULL** 的值 |
| PostgreSQL | ❌ 不支持 | ✅ |
**所以推荐 `COALESCE`——既通用，又能处理多级回退（`COALESCE(real_name, nickname, phone, '匿名')`）。**

**Q：`CONCAT` 在两边行为不同，怎么办？**
关键差异：**MySQL 的 `CONCAT` 遇到 NULL 返回 NULL；PostgreSQL 的 `CONCAT` 会跳过 NULL**。

```sql
-- MySQL
SELECT CONCAT('a', NULL, 'b');    -- 返回 NULL
-- PostgreSQL
SELECT CONCAT('a', NULL, 'b');    -- 返回 'ab'
```

**统一写法**：

```sql
-- 方式 1：先 COALESCE 再拼（语义明确）
SELECT CONCAT(COALESCE(a, ''), COALESCE(b, '')) FROM t;
-- ⚠️ 但 PostgreSQL 下 CONCAT('', '') = ''，MySQL 下也是 ''，一致了

-- 方式 2：用 CONCAT_WS（两边都支持，会跳过 NULL）
SELECT CONCAT_WS('-', a, b, c) FROM t;
-- MySQL 和 PostgreSQL 的 CONCAT_WS 都是"跳过 NULL 并用分隔符拼接"

-- 方式 3：在应用层拼接（最简单）
```

**`CONCAT_WS` 是更安全的选择**（`WS` = With Separator），它会跳过 NULL 并用指定分隔符连接。

**Q：PostgreSQL 的 `RETURNING` 对适配造成什么影响？**
如果代码依赖 `RETURNING`（比如「插入后立即拿到完整的记录」），MySQL 做不到，只能：
① **插入后 `SELECT` 一次**（多一次往返，且有并发风险——除非在同一事务内）；
② **用应用层生成主键**（雪花算法），插入后直接构造对象，不回查；
③ **只依赖 `LAST_INSERT_ID()`**（只能拿到自增 id）。
**推荐方案 ②**：应用层生成 ID + 插入时带上所有默认值 → 插入后不需要回查，天然兼容两边。

**Q：你们项目中实际遇到过哪些兼容问题？**
（这是你在真实适配工作里可以诚实回答的方向，用「问题 → 现象 → 处理」的结构讲）

常见的问题类型：
① **分页**：MySQL 的 `LIMIT m, n` 在 PostgreSQL 报语法错误 → 统一改成 `LIMIT n OFFSET m`；
② **UPSERT**：MySQL 的 `ON DUPLICATE KEY UPDATE` 在 PostgreSQL 不支持 → 抽象成方法，按 `databaseId` 走不同 SQL；
③ **空值函数**：`IFNULL` 在 PostgreSQL 报错 → 统一替换成 `COALESCE`；
④ **DDL 迁移**：PostgreSQL 下迁移脚本能整体回滚，MySQL 下部分成功 → **MySQL 侧必须写「幂等」的 DDL**（`CREATE TABLE IF NOT EXISTS`、判断列是否存在再加）；
⑤ **大小写**：PostgreSQL 把未加引号的标识符折成小写，而 MySQL 在 Linux 上区分大小写 → **统一用小写蛇形命名**；
⑥ **布尔类型**：MySQL 的 `TINYINT(1)` 和 PostgreSQL 的 `BOOLEAN` 在 JDBC 映射上有差异 → 显式指定类型。
:::

:::锚点
**⭐ 这是你简历上可以直接讲的真实工作——「项目里有 MySQL 与 PostgreSQL 兼容的适配工作」。这道题的价值在于：它证明了你有跨数据库抽象的设计意识，而且是你真实做过的事。**

**面试话术**：

> 「我在 RRM 项目里做过一部分数据库兼容的适配工作——我们的服务需要同时适配 MySQL 和 PostgreSQL，所以要把 SQL 里依赖特定数据库方言的地方抽出来。

> 我印象比较深的几类差异：
>
> **第一是分页**。MySQL 的 `LIMIT offset, count` 这个写法在 PostgreSQL 直接是语法错误，PostgreSQL 只认 `LIMIT count OFFSET offset`。所以我们统一改成了 `LIMIT n OFFSET m`——这是两边都支持的标准写法。
>
> **第二是 UPSERT**。MySQL 是 `INSERT ... ON DUPLICATE KEY UPDATE`，PostgreSQL 是 `INSERT ... ON CONFLICT (col) DO UPDATE SET`，而且 PostgreSQL 必须显式指定冲突的列，MySQL 是任意唯一键冲突都会触发。这一块没法用一套 SQL，我们用 MyBatis 的 `databaseId` 机制按数据库类型走不同的 SQL 片段。
>
> **第三是空值函数**。`IFNULL` 是 MySQL 特有的，PostgreSQL 不支持，我们统一替换成了 `COALESCE`——这个是 SQL 标准函数，两边都支持，而且能处理多个回退值。
>
> **第四是 DDL 的行为差异，这个是本质差异**。PostgreSQL 的 DDL 是可以在事务里回滚的，MySQL 的 DDL 会隐式提交。这意味着**迁移脚本在 MySQL 上失败会留下"部分成功"的中间状态**，所以我们在 MySQL 侧必须写幂等的 DDL（`CREATE TABLE IF NOT EXISTS`、加列前先判断是否存在），不能依赖事务回滚。
>
> **还有一个我觉得值得一提的是大小写问题**：PostgreSQL 会把不加双引号的标识符折叠成小写，而 MySQL 在 Linux 上表名是区分大小写的。所以我们的规范是**统一用小写蛇形命名**，从根上避开这个坑。
>
> 落到方法上，我的体会是：**做数据库兼容，最有效的不是「写一套 SQL 适配两边」，而是「用最小的公共子集 + 抽象层 + 双库集成测试」。** 比如分页统一用 `LIMIT n OFFSET m`、空值统一用 `COALESCE`，这些都是标准 SQL，可以避免大量分支；剩下没法统一的（UPSERT、`RETURNING`）才用 `databaseId` 分支。而且同一套集成测试要在两个库上各跑一遍，这比人工 review SQL 靠谱得多。」

**为什么这段好**：
1. **完全是真实工作**，不怕追问细节；
2. 展示了**抽象设计能力**（知道用最小公共子集 + 抽象层，而不是到处打补丁）；
3. 提到了**本质差异**（DDL 事务性）而不只是语法差异——这说明理解得深；
4. 提到了**验证手段**（双库集成测试），体现工程严谨性；
5. 用「问题 → 现象 → 处理」的结构讲，非常清晰。

**可以主动延伸的方向**：如果面试官继续问，你可以说：
> 「因为做了这个适配，我也顺手了解了一些 MySQL 特有而 PostgreSQL 没有或更强的能力。比如 **PostgreSQL 的 `RETURNING` 很好用**（INSERT/UPDATE/DELETE 能直接返回受影响的行），MySQL 只能靠 `LAST_INSERT_ID()` 拿自增 id；反过来 **PostgreSQL 的 MVCC 副作用更明显**——它的旧版本直接放在表文件里，不清理会导致表膨胀，所以 `VACUUM` 是 PgSQL 运维的核心议题，而 MySQL 的 undo 在独立表空间，膨胀不影响业务表。**这些差异让我意识到：兼容层只能解决语法问题，「性能特征」和「运维模式」的差异是没法靠抽象层抹平的。**」

**最后这句是加分项**——它说明你理解「兼容适配」的边界在哪里。
:::

---

## 📝 本章自测（闭卷）

### 第一轮：能说清楚（基础）

1. 说出 5 种索引失效场景，并解释**每一种的底层原因**（不能只说「会失效」）
2. 手画 B+ 树 vs B 树的结构差异，讲清「扇出」怎么算、为什么非叶子节点不存数据
3. 「聚簇索引 / 二级索引 / 覆盖索引 / 索引下推 / 回表」——这五个词各解释一句，并说明它们之间的关系
4. 事务的四个特性分别靠什么实现？为什么说「一致性是目的，其他三个是手段」？
5. 脏读、不可重复读、幻读的定义，以及各自被哪个隔离级别解决
6. `redo log` / `undo log` / `binlog` 各管什么？为什么需要两阶段提交？

### 第二轮：能讲深（追问防线）

7. 完整走一遍 MVCC 的可见性判断（ReadView 四个字段 + 四步算法 + 版本链回溯）
8. RC 和 RR 在实现上的唯一区别是什么？为什么这个区别能导致「不可重复读」？
9. 记录锁、间隙锁、临键锁的区别；唯一索引等值命中时为什么只加记录锁？
10. `EXPLAIN` 的 `type` 排序、`key_len` 怎么推出用了几列索引、`Extra` 里哪些值需要警惕
11. 子查询慢的三个根因（派生表物化 / 关联子查询 N 次执行 / `NOT IN` 遇 NULL）
12. 慢查询定位的完整链路（从开启慢日志到验证优化效果）

### 第三轮：能落到项目（差异化）

13. 讲一次你做过的 SQL/查询优化（**用 MongoDB 的 COLLSCAN → 复合索引 → 分片**那条线）
14. 深分页的三种解法及各自的适用前提
15. MySQL 和 PostgreSQL 的五个语法差异 + 一个本质差异（DDL 事务性）
16. 分片键选择的原则，以及你在 Mongo 上为什么选 `taskId`

### 口头自测的判据

**能连续说 60 秒不停、中间不出现「呃……那个……」、并且能主动说出「这里有个坑是……」，就算过关。**

三遍过不去的题，标记出来重点补——通常是「知道结论但不知道原因」的那种。

---

> 📌 **本文档使用方式**：默认折叠答案，先自己回答「面试官会怎么问」，再点开对照。
> MySQL 是你的补课项，**「能说清原理 + 坦诚没做过生产调优 + 展示从 MongoDB 迁移的能力」**是最安全的答题策略。
> **不要编造 MySQL 生产经历**——面试官一追问细节就会露馅，而坦然承认「这块在补」反而加分。
