# 📘 学习手册 06 · Java 基础

> 配套《面试八股复习计划》第 2 节 Java 基础 + PDF 第 7-36 页
> 你选了全量复习——但 PDF 有 90 题，这里精选**面试出现率最高的 20 题**精讲，其余按 PDF 原文过一遍即可
> 模板：**一句话结论 → 详细解释 → 面试话术/例题**
> 投酷开/工行/银行系/国企 Java 岗前必过

---

## 🧱 核心语言（1-10 题）

### 1. hashCode() 和 equals() 的关系
**一句话结论**：equals 相等 → hashCode 必相等；hashCode 相等 → equals 不一定相等（哈希碰撞）；所以重写 equals 必须重写 hashCode。
**详细解释**：
- 约定：两个对象 equals 相等，hashCode 必须相同；否则 HashMap 里"相等的对象"散到不同桶，查不到
- 流程（HashMap 查找）：先算 hashCode 定位桶 → 桶内再用 equals 比对
- 为什么先比 hashCode：hashCode 是算哈希（O(1)），equals 逐字段比（开销大）；先哈希快速定位，减少 equals 调用
- HashSet 去重：add 时先 hashCode 定位，桶空直接加；桶非空再 equals 判断是否重复
**话术/例题**：背"equals 相等 → hash 相等，反之不成立"。追问：只重写 equals 不重写 hashCode 会怎样？→ HashMap 中相等的对象被当成两个，出现重复 key/查不到。

### 2. HashMap 底层实现？为什么线程不安全？
**一句话结论**：数组+链表（红黑树，JDK8+），按 key 哈希定位桶；并发下扩容/覆盖会导致数据丢失甚至死循环（JDK7）。
**详细解释**：
- 结构：Node<K,V>[] table；put 流程：hash(key) → 定位桶 → 空直接放，冲突挂链表（长度>8 且容量≥64 转红黑树）
- 扩容：负载因子默认 0.75，size > capacity×0.75 时扩容 2 倍，重新散列（rehash，JDK8 优化为高低位拆分）
- 为什么线程不安全：
  - 并发 put 覆盖（两个线程同时插入同一桶，后写覆盖先写）
  - JDK7 头插法 + 扩容时并发会形成环形链表 → 死循环（CPU 100%）
  - size 计算不原子
- 线程安全替代：ConcurrentHashMap（分段/细粒度锁 + CAS）、Hashtable（全表锁，已淘汰）、Collections.synchronizedMap
**话术/例题**：能讲"数组+链表+红黑树 + 0.75 扩容"就是合格；补一句 JDK7 头插法环形链表是加分。追问：为什么 8 才转红黑树？→ 泊松分布，链表长度 8 的概率极低；转树为了防极端哈希碰撞 O(n)。

### 3. ConcurrentHashMap 如何保证线程安全
**一句话结论**：JDK8 放弃分段锁，用 **CAS + synchronized 锁单个桶节点**，细粒度并发（读无锁）。
**详细解释**：
- JDK7：Segment 分段锁（继承 ReentrantLock），锁粒度 = 段
- JDK8：Node 数组 + 对单个桶的头节点 synchronized + 扩容/计数用 CAS（如 baseCount、sizeCtl）
- 读：volatile 保证可见性，无锁；写：桶空用 CAS 插入，桶非空锁头节点
- 扩容：多线程协助扩容（transfer），不阻塞读
- 特点：读并发极高，写并发按桶分散
**话术/例题**：一句"JDK8 锁桶不锁表" + "CAS + volatile"。追问：和 Hashtable 区别？→ Hashtable 锁整个表，并发度低（都同步方法）。

### 4. String / StringBuffer / StringBuilder 区别
**一句话结论**：String 不可变（final + 每次修改生成新对象），StringBuffer 线程安全可变，StringBuilder 线程不安全但最快（单线程推荐）。
**详细解释**：
- String：`private final char[] value`，不可变 → 安全、可缓存 hash、适合做 HashMap key；拼接大量字符串会产生大量中间对象
- StringBuffer：方法 synchronized，线程安全，性能低
- StringBuilder：不同步，单线程下拼接字符串最优（循环拼接用这个）
- String 不可变的好处：常量池复用、线程安全、hash 稳定
**话术/例题**：选型一句话"单线程 StringBuilder，多线程 StringBuffer，常量 String"。追问：为什么 String 设计成不可变？→ 常量池复用 + 安全 + hash 缓存。

### 5. 重载和重写的区别
**一句话结论**：重载=同方法名不同参数（编译期、同类内），重写=子类覆写父类方法（运行期、虚函数机制）。
**详细解释**：
- 重载 overload：方法名相同、参数列表不同（个数/类型/顺序）；返回类型不参与判断；编译期确定调哪个（静态绑定）
- 重写 override：子类方法签名与父类相同（参数+返回，返回可协变）；权限不能更小、异常不能更宽；运行期确定（动态绑定）
- 检查注解：@Override 让编译器校验
**话术/例题**：一句"重载看参数，重写看继承；重载静态绑定，重写动态绑定"。

### 6. == 和 equals() 的区别
**一句话结论**：== 比较引用地址（基本类型比较值），equals 默认也是地址比较但可重写为内容比较。
**详细解释**：
- ==：基本类型比值，引用类型比地址
- equals：Object 默认实现就是 ==（地址比较）；String/包装类等重写为内容比较
- 所以 `new String("a") == new String("a")` 是 false，`.equals` 是 true
- 字符串比较永远用 equals 或 `Objects.equals`（防 null）
**话术/例题**：一句"== 比地址（基本类型比值），equals 默认地址可重写为内容"。追问：Integer 缓存？→ -128~127 有 IntegerCache，`Integer a=127,b=127; a==b` 为 true，128 为 false。

### 7. Java 集合框架（List/Set/Map）
**一句话结论**：Collection（List 有序可重复 / Set 无序唯一）+ Map（键值对）；ArrayList/LinkedList、HashSet/TreeSet、HashMap/TreeMap 是主要实现。
**详细解释**：
- List：ArrayList（动态数组，随机访问快）、LinkedList（双向链表，头尾操作快）、Vector（同步，淘汰）
- Set：HashSet（哈希，无序）、LinkedHashSet（插入序）、TreeSet（红黑树，有序）
- Map：HashMap（哈希无序）、LinkedHashMap（插入序，LRU 可用）、TreeMap（红黑树按 key 有序）、ConcurrentHashMap（并发）
- 共同点：迭代器（Iterator）遍历；快速失败（fail-fast：遍历中修改抛 ConcurrentModificationException）
**话术/例题**：能说出每个接口的"特性+底层+典型实现"就过关。追问：ArrayList 和 LinkedList 什么时候用？→ 随机访问 ArrayList，频繁头尾增删 LinkedList（实际都少用 LinkedList）。

### 8. ArrayList 和 LinkedList 区别（含扩容）
**一句话结论**：ArrayList 动态数组（查快增删慢，扩容 1.5 倍），LinkedList 双向链表（头尾快中间慢，无扩容）。
**详细解释**：
- ArrayList：底层 Object[]，默认容量 10，满时扩容 **1.5 倍**（JDK8：old + old>>1）；尾插 O(1)，中间插/删 O(n)（搬移）；随机访问 O(1)
- LinkedList：双向链表节点，头尾插入 O(1)，中间 O(n) 遍历找；随机访问 O(n)
- 实际：多数场景 ArrayList 更优（cache 局部性、内存紧凑）
- 多线程：都不是线程安全，用 CopyOnWriteArrayList
**话术/例题**：重点记"ArrayList 扩容 1.5 倍（区别于 HashMap 2 倍）"。追问：为什么 ArrayList 扩容不是 2 倍？→ 1.5 倍兼顾空间浪费与搬移次数（2 倍浪费 50% 空间）。

### 9. 异常体系（Checked/Unchecked、finally）
**一句话结论**：Throwable → Error（JVM 级，不处理）和 Exception（可处理）；Exception 分 Checked（编译期必须处理）和 RuntimeException（运行期）；finally 保证资源释放。
**详细解释**：
- Error：OutOfMemoryError、StackOverflowError——不捕获
- Checked：IOException、SQLException——必须 try-catch 或 throws
- Unchecked（RuntimeException）：NPE、IndexOutOfBounds、ClassCast——可捕获可不捕获
- try-catch-finally：finally 不管是否异常都执行（资源释放）；**finally 里 return 会覆盖 try 的 return**
- try-with-resources（JDK7）：自动关闭 AutoCloseable，推荐
**话术/例题**：能分层说"Error 不处理 / Checked 必须处理 / RuntimeException 看情况"。追问：finally 一定会执行吗？→ 不一定：System.exit() 或 JVM 崩溃时不执行。

### 10. 反射机制
**一句话结论**：运行期动态获取类的信息（字段/方法/构造器）并操作对象，是框架（Spring 等）的基础。
**详细解释**：
- Class 对象：`Class.forName()` / `obj.getClass()` / `类名.class`
- 能力：getDeclaredMethods/Fields、setAccessible 暴力访问私有、Method.invoke 动态调用
- 用途：Spring IOC（反射创建 Bean）、注解解析、动态代理、序列化框架
- 缺点：性能低（绕过 JIT 优化）、破坏封装、代码可读性差
**话术/例题**：一句"运行期操作类结构，框架基石"，提性能损耗。

---

## 🧵 并发与线程（11-16 题）

### 11. 线程的几种状态
**一句话结论**：NEW → RUNNABLE →（BLOCKED / WAITING / TIMED_WAITING）→ TERMINATED，由锁/等待触发切换。
**详细解释**：
- NEW：创建未 start
- RUNNABLE：就绪或运行中（Java 把 ready+running 合并）
- BLOCKED：等 synchronized 锁
- WAITING：wait/join 无限等待（需 notify）
- TIMED_WAITING：sleep/wait(ms) 限时等待
- TERMINATED：结束
- 常见转换：sleep → TIMED_WAITING；wait → WAITING；拿锁失败 → BLOCKED
**话术/例题**：背状态机 + 每个状态怎么进入/退出。追问：sleep 和 wait 区别？→ sleep 不释放锁，wait 释放锁（必须持锁调用）。

### 12. 创建线程的几种方式
**一句话结论**：继承 Thread、实现 Runnable、实现 Callable（有返回值）、线程池（推荐）；本质都是 Thread + 任务。
**详细解释**：
1. 继承 Thread：重写 run()，简单但 java 单继承
2. 实现 Runnable：run() 无返回值，推荐（解耦）
3. 实现 Callable + FutureTask：call() 有返回值可抛异常
4. **线程池 ExecutorService**：最推荐（复用线程、控制并发、管理生命周期）
**话术/例题**：答"4 种 + 推荐线程池"。追问：Callable 和 Runnable 区别？→ 有返回值、可抛异常。

### 13. 线程池参数与执行流程
**一句话结论**：核心线程数 → 任务队列 → 最大线程数 → 拒绝策略，四个环节逐级处理任务。
**详细解释**（ThreadPoolExecutor 7 参数）：
- corePoolSize 核心线程 / maximumPoolSize 最大 / keepAliveTime 空闲存活 / workQueue 任务队列 / threadFactory / handler 拒绝策略
- 流程：提交任务 → ① 线程 < 核心数：新建核心线程执行；② 否则入队列；③ 队列满且线程 < 最大数：新建非核心线程；④ 队列满且线程 = 最大数：走拒绝策略
- 拒绝策略：AbortPolicy（抛异常，默认）/ CallerRunsPolicy（调用者线程执行）/ DiscardPolicy（丢弃）/ DiscardOldest（丢最老）
- 队列：LinkedBlockingQueue（无界，几乎不用非核心线程）/ ArrayBlockingQueue（有界）/ SynchronousQueue（不存直接转）
**话术/例题**：把 4 步流程背下来是线程池题的标准答法。追问：无界队列+最大线程数配置会怎样？→ 队列永远不满，非核心线程永不创建，拒绝策略失效（这就是"无界队列时拒绝策略怎么搞"考点）。

### 14. synchronized 原理与优化
**一句话结论**：synchronized 是 JVM 内置锁（monitor），JDK6 后做了锁升级：无锁 → 偏向锁 → 轻量级锁 → 重量级锁。
**详细解释**：
- 用法：方法、代码块（锁对象）；可重入（同一线程可重复进入）
- 实现：对象头 Mark Word 记录锁状态；monitor（管程）是重量级实现
- **锁升级**（减少重量级锁开销）：
  - 偏向锁：无竞争时 CAS 记录线程 id，后续同线程直接进（可撤销）
  - 轻量级锁：有竞争时 CAS 自旋尝试（短等待）
  - 重量级锁：自旋失败升级，线程阻塞（OS 互斥量）
- 非公平：新线程可以插队（synchronized 是非公平锁）
**话术/例题**：讲"锁升级路径"就是源码级理解。追问：为什么非公平？→ 效率：唤醒有开销，允许插队提高吞吐。

### 15. synchronized 和 ReentrantLock 的区别
**一句话结论**：synchronized 是关键字（自动释放），ReentrantLock 是 API（手动释放、可中断、可公平、可超时、支持多条件）。
**详细解释**：
| | synchronized | ReentrantLock |
|---|---|---|
| 用法 | 关键字 | lock()/unlock()（finally 释放） |
| 释放 | 自动 | 必须手动 |
| 可中断 | ❌ | ✅ lockInterruptibly |
| 超时 | ❌ | ✅ tryLock(timeout) |
| 公平 | 非公平 | 可公平可非公平 |
| 条件 | wait/notify | 多个 Condition（精准唤醒） |
| 底层 | monitor | AQS（AbstractQueuedSynchronizer） |
- 高并发复杂场景用 ReentrantLock（超时/中断/多条件），简单互斥 synchronized 就够
**话术/例题**：列差异表 + 场景选择。追问：AQS 是什么？→ 双向队列 + state 状态 + CAS，ReentrantLock/CountDownLatch/Semaphore 都基于它。

### 16. CAS 机制与 ABA 问题
**一句话结论**：CAS（比较并交换）= 内存值==期望值才更新（原子指令）；ABA 是"值改了又改回来"被误判；用版本号解决。
**详细解释**：
- CAS 操作：`CAS(内存地址, 期望值, 新值)`，底层 CPU 原子指令（cmpxchg）
- 用处：无锁并发（AtomicInteger、ConcurrentHashMap 桶插入）
- **ABA 问题**：线程 1 读 A → 线程 2 改成 B 又改回 A → 线程 1 CAS 成功但数据其实被动过
- 解决：AtomicStampedReference（版本号 stamp）、AtomicMarkableReference（布尔标记）
- CAS 局限：只能保证一个变量、自旋消耗 CPU、ABA
**话术/例题**：讲清 CAS 三步 + ABA 场景（栈顶指针回收等）。追问：和 synchronized 对比？→ CAS 无锁乐观（轻量），synchronized 悲观（重量）；CAS 适合竞争小。

---

## 🔥 其他高频（17-20 题）

### 17. 类加载机制与双亲委派
**一句话结论**：加载 → 验证 → 准备 → 解析 → 初始化；类加载器自底向上委派给父加载器，父能加载就不自己加载——保证核心类不被篡改。
**详细解释**：
- 加载器层级：Bootstrap（rt.jar，C++ 写）→ Extension/Platform（扩展）→ Application（classpath）→ 自定义
- **双亲委派**：子加载器先委托父加载器，父加载不了才自己加载
- 为什么：防止自定义 java.lang.String 覆盖 JDK 的（安全）；保证类唯一性（同类只加载一次）
- 破坏场景：SPI（JDBC 驱动）用线程上下文加载器反着来
**话术/例题**：背"委派链 + 安全目的"。追问：能不能自己写 java.lang.String？→ 能编译不能加载（Bootstrap 已加载，父加载器优先）。

### 18. JVM 内存区域
**一句话结论**：线程私有（虚拟机栈/本地方法栈/程序计数器）+ 线程共享（堆/方法区/元空间）；堆存对象，栈存局部变量。
**详细解释**：
- 程序计数器：当前执行字节码行号（唯一无 OOM）
- 虚拟机栈：栈帧（局部变量表/操作数栈/方法返回），StackOverflowError
- 本地方法栈：native 方法（node-ffi 类比）
- **堆**：对象实例，GC 主战场（新生代/老年代）
- **方法区/元空间**（JDK8+）：类信息、常量、静态变量；元空间用本地内存（不再 OOM 于堆）
- 直接内存：NIO DirectBuffer（堆外，native 层）
**话术/例题**：画图 + 一句"栈管方法，堆管对象"。追问：对象一定在堆上吗？→ 逃逸分析后可栈上分配（JIT 优化）。

### 19. GC 与垃圾回收器
**一句话结论**：可达性分析（GC Roots）判断垃圾，分代回收；回收器 G1 是默认（区域化+可预测停顿），CMS 是并发标记清除。
**详细解释**：
- 判断：可达性分析（GC Roots：栈/静态/常量引用），不可达才回收；引用计数有循环引用缺陷不用
- 分代：新生代（Eden+S0+S1，复制算法，Minor GC 频繁）+ 老年代（标记整理，Major/Full GC）
- 回收器：Serial/Parallel（吞吐）/CMS（并发、标记清除、碎片）/G1（JDK9+ 默认，Region 分块，可预测停顿目标）
- G1：把堆分 Region，跟踪各 Region 垃圾占比，优先回收垃圾多的（Garbage First）；可设置 -XX:MaxGCPauseMillis
- 调优目标：减少 Full GC、控制停顿；命令 jstat/jmap/GC 日志
**话术/例题**：答"可达性 + 分代 + 默认 G1"。追问：G1 和 CMS 区别？→ G1 区域化+可预测停顿+无碎片，CMS 标记清除有碎片+并发失败退化。

### 20. ThreadLocal 原理与内存泄漏
**一句话结论**：ThreadLocal 给每个线程一份变量副本（线程内共享、线程间隔离）；底层 Thread 里有 ThreadLocalMap，key 弱引用，但 value 强引用 → 线程池场景需 remove 防泄漏。
**详细解释**：
- 用法：`ThreadLocal<T>` set/get；每个线程的 Thread 对象持有 ThreadLocalMap（key=ThreadLocal，value=值）
- 实现：不是 ThreadLocal 存值，是 Thread 里 map 存（key 是弱引用 ThreadLocal）
- **内存泄漏**：key 是 WeakReference（ThreadLocal 被回收后 key 变 null），但 value 强引用 → 如果线程长期存活（线程池），Entry 永远清不掉 → 泄漏
- 解决：**用完必须 remove()**；或在 finally 里 remove
- 场景：请求上下文（用户信息）、SimpleDateFormat 线程安全、连接管理
**话术/例题**：能讲出"弱引用 key + 强引用 value"的泄漏机制是深度题。追问：为什么 key 设计成弱引用？→ 让 ThreadLocal 对象本身可被回收，但这也导致 value 泄漏，所以 remove 是正解。

---

## 📝 本章自测（闭卷）

1. 为什么重写 equals 必须重写 hashCode？HashMap 查找流程
2. HashMap JDK8 结构 + 扩容时机 + 为什么线程不安全
3. String/StringBuffer/StringBuilder 区别与选型
4. 线程 6 状态 + sleep/wait 区别
5. 线程池 4 步执行流程 + 拒绝策略
6. 锁升级路径（偏向→轻量→重量）
7. synchronized vs ReentrantLock 差异
8. CAS 三步 + ABA 怎么解决
9. 双亲委派机制 + 为什么要这样设计
10. ThreadLocal 为什么泄漏？怎么防

> 完成自测后回 PDF 第 7-36 页过一遍其余 Java 基础题（约 70 题快速浏览）
