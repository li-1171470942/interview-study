# 📘 学习手册 12 · MySQL 与 PostgreSQL 兼容

> 补充：MySQL 手册之外的数据库对比专题
> 背景：你日常用 PostgreSQL 16.8（代码质量扫描），投的岗位多是 MySQL 生态——面试官问"MySQL 和 PG 区别"正是你差异化机会
> 模板：**一句话结论 → 详细解释 → 面试话术/例题**

---

## 1. MySQL 和 PostgreSQL 选型
**一句话结论**：MySQL 简单生态大（互联网标配），PG 功能强合规全（JSON/数组/窗口函数/分区完善）；读多写少互联网场景 MySQL，复杂查询/数据分析/合规要求 PG。
**详细解释**：
| 维度 | MySQL | PostgreSQL |
|---|---|---|
| 定位 | 简单易用、生态最大 | 功能最全的开源数据库 |
| 存储引擎 | InnoDB/MyISAM 可切换 | 统一（无引擎概念） |
| 事务 | ACID（InnoDB） | ACID |
| 复杂查询 | 一般 | 强（窗口函数/CTE/递归/部分索引） |
| JSON | JSON 文本 | **JSONB（二进制，可索引）** |
| 扩展性 | 插件少 | 插件丰富（PostGIS 地理、Timescale 时序） |
| 社区/生态 | 极大（阿里/腾讯云原生支持） | 大（德哥等中文社区活跃） |
| 商业应用 | 互联网电商社交 | 金融/地理/数据分析/开源替代 Oracle |
**话术/例题**："MySQL 简单快生态大，PG 功能全数据强"——你两边都熟（PG 用在工作流、MySQL 在岗位要求），这是独特卖点。

## 2. 架构差异：存储引擎与数据组织
**一句话结论**：MySQL 分层引擎（InnoDB 表空间+聚簇索引），PG 每张表一堆文件（堆表组织，MVCC 靠元组版本）。
**详细解释**：
- MySQL InnoDB：**聚簇索引**（主键即数据），数据和索引一体；引擎可选
- PG：**堆表**（heap），索引是独立结构指向行（类似 MyISAM 的非聚簇）；无引擎概念，统一存储管理器
- 含义：MySQL 主键查找极快（一次定位），PG 二级索引查询可能回表；PG 顺序扫描+bitmap 扫描优化更强
- MySQL 一行即一条记录；PG 更新产生新版本元组（旧版本留 undo/vacuum 清理）
**话术/例题**："MySQL 聚簇索引管数据，PG 堆表+独立索引"一句话。追问：PG 为什么更新慢？→ 新版本元组 + vacuum 负担（见第 6 题）。

## 3. 自增 vs 序列（AUTO_INCREMENT / SERIAL）
**一句话结论**：MySQL 用 AUTO_INCREMENT，PG 用序列（SERIAL / IDENTITY），本质都是"取号器"但 PG 更灵活。
**详细解释**：
- MySQL：`id INT AUTO_INCREMENT PRIMARY KEY`，表级计数器；重启后按 max+1 续（有历史跳过问题）
- PG：`id SERIAL PRIMARY KEY`（内部建序列）；`id BIGINT GENERATED ALWAYS AS IDENTITY`（现代推荐）
- 序列特点：独立对象，可多个表共享/批量取 nextval；不随事务回滚（有空洞正常）
- 迁移注意：MySQL 自增迁移到 PG 要建序列并 setval 到当前最大值
**话术/例题**：一句"都是自增取号，PG 是独立序列对象"。追问：序列会重复吗？→ 回滚不回收，保证不重复但可能有空洞。

## 4. SQL 语法兼容差异（高频对比）
**一句话结论**：LIMIT/ON CONFLICT/COALESCE/类型转换/字符串拼接/日期函数 6 处最常见差异，迁移必踩。
**详细解释**：
| 场景 | MySQL | PostgreSQL |
|---|---|---|
| 分页 | LIMIT 10 OFFSET 20 | LIMIT 10 OFFSET 20（兼容） |
| 插入冲突 | INSERT IGNORE / ON DUPLICATE KEY UPDATE | **ON CONFLICT (col) DO UPDATE SET / DO NOTHING**（更强大，可指定冲突列） |
| 空值函数 | IFNULL(a,b) | COALESCE(a,b)（标准） |
| 类型转换 | CAST(a AS ...) / CONVERT | CAST / a::type |
| 字符串拼接 | CONCAT(a,b) / a||b（需模式） | **a || b**（标准） |
| 大小写 | 表名/列名 Windows 下不敏感 | 未加引号会折叠成小写（标识符大小写敏感要加双引号） |
| 日期函数 | NOW()/DATE_FORMAT | NOW()/CURRENT_DATE/TO_CHAR |
| 布尔 | 0/1 | TRUE/FALSE（也有兼容） |
**话术/例题**：背"ON CONFLICT vs ON DUPLICATE、IFNULL vs COALESCE、|| 拼接、标识符大小写"4 个高频差异。追问：迁移时 SQL 兼容性怎么查？→ 方言检测工具/explain 计划对照 + 回归测试。

## 5. 数据类型差异
**一句话结论**：PG 类型更丰富（数组/JSONB/枚举/几何/网络类型），MySQL 简单；JSON 是最大差异点。
**详细解释**：
| 场景 | MySQL | PostgreSQL |
|---|---|---|
| JSON | JSON（文本校验） | JSON（文本）+ **JSONB**（二进制、去重、可索引、GIN） |
| 数组 | 无原生 | **text[]/int[]**（原生数组） |
| UUID | 8.0+ 支持（存二进制） | UUID 原生 |
| 自增 | AUTO_INCREMENT | SERIAL/IDENTITY |
| 文本 | VARCHAR/TEXT | VARCHAR/TEXT（无长度差异，PG TEXT 无上限） |
| 数值 | DECIMAL | NUMERIC（更标准） |
| 枚举 | ENUM（改值麻烦） | CREATE TYPE 自定义枚举 |
| 网络 | 无 | inet/cidr/macaddr |
**话术/例题**："PG 类型武器库丰富（数组/JSONB/网络类型），JSON 用 JSONB"是核心卖点。追问：JSONB 比 JSON 好在哪？→ 二进制解析快、自动去重、可建 GIN 索引加速查询。

## 6. MVCC 与并发控制差异
**一句话结论**：两者都用 MVCC 实现读不阻塞写，但机制不同：MySQL 靠 undo log 版本链，PG 靠元组新旧版本 + vacuum 清理。
**详细解释**：
- MySQL：更新时旧版本进 **undo log** 版本链，新版本原地写（InnoDB）；隔离级别默认**可重复读（RR）**
- PG：更新生成**新版本元组**（堆里新增一行），旧版本保留，靠 **vacuum** 清理过期元组；隔离级别默认**读已提交（RC）**；PG 的 RR 用 SSI（可串行化快照隔离）更强
- PG 特点：DDL 可以事务化（建表改表可回滚）、锁更细（行锁+谓词锁）
- MySQL 的 RR 靠 MVCC+间隙锁基本防幻读；PG 的 RR 防幻读靠 SSI 或序列化
**话术/例题**："MySQL undo 版本链 vs PG 新版本元组"是深度题。追问：PG 为什么有 vacuum？→ 旧版本元组不清理表会膨胀，autovacuum 自动处理。

## 7. 索引差异
**一句话结论**：MySQL 主打 B+树（+哈希/全文），PG 有 B-tree/GIN/GiST/BRIN/部分索引/表达式索引，类型丰富得多。
**详细解释**：
- MySQL：B+树（默认）、Hash（MEMORY 引擎）、全文（InnoDB 5.6+）
- PG：**B-tree**（默认）、**GIN**（倒排，JSONB/全文搜索）、**GiST**（地理/范围）、BRIN（大数据量顺序）、**部分索引**（WHERE 条件索引）、**表达式索引**（函数索引）
- 实战：JSONB 字段查用 GIN 索引；地理查询 PostGIS 用 GiST；大数据量日志按时间用 BRIN
**话术/例题**："MySQL 一种打天下，PG 索引武器库"——你能讲 GIN/部分索引就是懂 PG。追问：什么时候用部分索引？→ 只查活跃状态的数据，索引只含 WHERE 子句匹配的行，小且快。

## 8. 复制与高可用
**一句话结论**：MySQL 用 binlog 逻辑复制（半同步可配），PG 用 WAL 物理流复制（同步/异步），PG 高可用生态更严谨。
**详细解释**：
- MySQL：binlog 复制（GTID 增强），读写分离常见；半同步需插件；MGR 组复制
- PG：**WAL 流复制**（物理复制，从库只读）+ 逻辑复制（表级，跨版本）；同步复制可配置同步级别（remote_apply）；主从切换用 Patroni/repmgr
- PG 优势：复制延迟低（流式）、支持同步复制保证不丢（类似半同步加强版）
- 监控：MySQL 主从延迟 SHOW SLAVE STATUS；PG pg_stat_replication
**话术/例题**："MySQL 逻辑复制 vs PG 物理流复制"一句话。追问：为什么 PG 同步复制能保证不丢？→ 主库等从库 WAL 落盘才提交（synchronous_commit）。

## 9. MySQL → PG 迁移注意点
**一句话结论**：语法（ON DUPLICATE→ON CONFLICT）、类型（自增→序列、JSON→JSONB）、大小写、驱动/ORM 方言，四类改造点。
**详细解释**：
1. **SQL 方言**：IFNULL→COALESCE、ON DUPLICATE→ON CONFLICT、DATE_FORMAT→TO_CHAR、`||` 拼接
2. **类型**：AUTO_INCREMENT→SERIAL/IDENTITY（setval 续号）、JSON→JSONB、ENUM→自定义类型
3. **大小写**：MySQL 表名不敏感 vs PG 折叠小写——统一小写命名
4. **ORM/驱动**：MySQL 驱动 mysql2/MySQLDialect vs PG pg/pg-promise/Dialect 切换；SQL 里反引号 → 双引号/标准
5. **工具**：pgloader 自动迁移（MySQL→PG 开源工具）、AWS DMS
6. **行为差异**：PG 事务中 DDL 可回滚、GROUP BY 更严格（要列全）、默认 RC 隔离
**话术/例题**：你能讲"迁移 4 类改造点"就是真做过跨库。追问：为什么有的公司从 MySQL 迁 PG？→ 需要 PG 的高级特性（JSONB/地理/合规）或替代 Oracle。

## 10. PostgreSQL 运维要点（加分）
**一句话结论**：vacuum 防膨胀、checkpoint 控落盘、WAL 归档做备份、参数调优（shared_buffers/work_mem）——PG 运维三板斧。
**详细解释**：
- **vacuum/autovacuum**：清理死元组防表膨胀（膨胀影响查询性能）；`VACUUM ANALYZE` 更新统计信息
- **checkpoint**：WAL 落盘时机，checkpoint 间隔影响恢复时间（-XX: checkpoint_completion_target）
- **备份**：pg_basebackup（物理）/ pg_dump（逻辑）+ WAL 归档（PITR 时间点恢复）
- **参数**：shared_buffers（建议内存 25%）、work_mem（排序/哈希内存）、maintenance_work_mem（vacuum/索引）
- **监控**：pg_stat_activity（活动会话/慢查询）、pg_stat_statements（SQL 统计）
**话术/例题**：能说出"autovacuum 防膨胀 + pg_stat_statements 看慢 SQL"就是有生产经验。追问：表膨胀了怎么处理？→ 手动 VACUUM FULL（重建表，锁表，低峰做）。

## 📝 本章自测（闭卷）
1. MySQL vs PG 选型一句话 + 三个核心差异
2. AUTO_INCREMENT 和 SERIAL 迁移怎么做
3. ON DUPLICATE KEY UPDATE → PG 对应什么
4. JSONB 比 JSON 强在哪，怎么建索引
5. 两者 MVCC 机制区别（undo 链 vs 新元组+vacuum）
6. PG 迁移四大改造点
7. PG 表膨胀原因和解决

> 完成自测后可回《面试八股复习计划》勾选 MySQL 相关题
