# 📘 学习手册 07 · JVM

> 配套《面试八股复习计划》第 2 节 JVM + PDF 第 56-60 页
> 结构：**概念（常显）→ 面试官会怎么问（常显）→ 答案与原理（点开）→ 拓展 + 追问 + 项目锚点**
> Java 岗必考；本文按「能扛住追问」标准编写，含可执行命令与真实排查 SOP

---

## 1. JVM 内存区域划分（运行时数据区）

:::概念
线程私有：程序计数器、虚拟机栈、本地方法栈；线程共享：堆、方法区/元空间。外加一块不受堆限制的直接内存。
一句话记：**栈管方法调用、堆管对象、元空间存类**。
:::

:::提问
- 讲一下 JVM 的内存结构？
- 哪些区域线程私有，哪些共享？
- 堆内部怎么划分？新生代为什么是 8:1:1？
- 元空间和永久代什么区别，为什么 JDK8 要换掉？
:::

:::答案
**区域总表**

| 区域 | 线程 | 存什么 | 异常 | 相关参数 |
|---|---|---|---|---|
| 程序计数器 | 私有 | 当前字节码行号 | 无 | — |
| 虚拟机栈 | 私有 | 栈帧（局部变量表/操作数栈/动态链接/返回地址） | StackOverflowError | `-Xss` |
| 本地方法栈 | 私有 | native 方法（就是 node-ffi 调 C 那层） | StackOverflowError | `-Xss` |
| **堆** | 共享 | 对象实例、数组 | OutOfMemoryError | `-Xms` `-Xmx` |
| **方法区/元空间** | 共享 | 类元信息、运行时常量池、JIT 后的静态结构 | OOM: Metaspace | `-XX:MaxMetaspaceSize` |
| 直接内存 | — | NIO DirectByteBuffer 堆外内存 | OOM: Direct buffer memory | `-XX:MaxDirectMemorySize` |

**堆内部分代**

```
┌─────────────────── 堆（-Xms / -Xmx）───────────────────┐
│  新生代 Young（1/3）           │   老年代 Old（2/3）      │
│  ┌──────┬──────┬──────┐        │                        │
│  │ Eden │ S0   │ S1   │        │  标记-整理 / 复制        │
│  │  8   │  1   │  1   │        │                        │
│  └──────┴──────┴──────┘        │                        │
│        ← Minor GC              │       ← Major / Full GC │
└────────────────────────────────────────────────────────┘
```

**为什么新生代是 8:1:1**：新生代里 98% 的对象朝生夕死，存活对象极少。Eden 拿 80% 撑住分配量，两块 Survivor 各 10% 轮流做复制目标（永远有一块是空的）。10% 足够放下存活对象，比「1:1 复制」浪费一半空间划算得多。

**栈溢出 vs 堆溢出**

| | StackOverflowError | OOM: Java heap space |
|---|---|---|
| 根因 | 栈深度超限（递归太深 / 死递归） | 堆中对象太多且不可回收 |
| 参数 | `-Xss` 每线程栈大小 | `-Xms` / `-Xmx` |
| 查什么 | 递归出口、无限循环调用链 | dump 看谁在占内存 |

**JDK8 为什么用元空间替代永久代**

1. 永久代**在堆里**（受 `-Xmx` 挤占），大小固定（`-XX:MaxPermSize`），很容易 `OOM: PermGen space`
2. 永久代的调优极难：GC 与老年代绑定，要等 Full GC 才回收
3. 元空间改用**本地内存（Native Memory）**，默认不设上限，也可用 `-XX:MaxMetaspaceSize` 控制
4. JDK7 已把字符串常量池和静态变量移到堆，是过渡；JDK8 彻底移除永久代
:::

:::拓展
**直接内存为什么容易漏**

NIO 的 `DirectByteBuffer` 分配在堆外，由 `Cleaner`（虚引用）在 GC 时触发释放。堆内那个 `DirectByteBuffer` 对象很小，堆压力不大 → 迟迟不 GC → 堆外内存一直不还。现象是「堆很健康但进程 RSS 一直涨、最后被容器 OOMKilled」。

排查：启动加 `-XX:NativeMemoryTracking=summary`，然后 `jcmd <pid> VM.native_memory summary` 看各区域占用。Netty、Kafka 客户端、gRPC 都是直接内存大户。
:::

:::追问
**Q：栈帧大小是编译期确定的吗？**
大部分是——局部变量表大小、操作数栈深度在编译期算好写在 `Code` 属性里。但逃逸分析带来的「栈上分配」是运行时优化，属于另一回事。

**Q：一个对象从创建到回收，会经过哪些区域？**
TLAB（Eden 内线程私有的分配缓冲区）→ Eden → Survivor S0/S1 轮流复制 → 达到年龄阈值（默认 15）或大对象 → 老年代 → 回收。

**Q：方法区里到底存什么？**
类元信息（Class 结构、字段/方法描述符）、运行时常量池、静态变量（JDK7+ 已移到堆）、以及 `Class` 对象本身。注意：JIT 编译后的代码不在方法区，在独立的 **Code Cache**。
:::

:::锚点
rrmcompute 现网 OOM 的真实教训：容器内存 limit ≠ 堆大小。`-Xmx5g` 的 Pod，实际 RSS = 堆 + 元空间 + 线程栈（`-Xss` × 线程数）+ 直接内存 + Code Cache。我们把内存从 5Gi 调到 5.5GiB（requests=3Gi），本质是把「堆 + 非堆」的总和撑开——因为高量任务并发时，除了堆，线程栈和元空间也在涨。

**容器环境两条铁律**：① 必须显式设 `-Xmx`（别让 JVM 自己按宿主机物理内存猜，会猜成节点总内存然后被 OOMKilled）；② `-Xmx` 要比容器 limit 留出 **25% 以上**余量给非堆。被 cgroup OOMKilled（Exit Code 137）时，日志里**看不到** `OutOfMemoryError`，只有 K8s 的 `OOMKilled` 事件——这个区别很多人踩过。
:::

---

## 2. 类加载机制（加载-验证-准备-解析-初始化）

:::概念
五个阶段：**加载 → 验证 → 准备 → 解析 → 初始化**（之后才是使用和卸载）。
最容易被追问的一句：**准备阶段给静态变量赋「默认值」（0/null），初始化阶段执行 `<clinit>` 赋「真实值」**。
:::

:::提问
- 讲一下类加载的过程？
- 准备阶段和初始化阶段有什么区别？
- 什么情况会触发类初始化？什么情况不会？
- 静态代码块和静态变量赋值的执行顺序？
:::

:::答案
**五阶段**

| 阶段 | 做什么 | 关键点 |
|---|---|---|
| 加载 | 读 .class 字节码，生成 `Class` 对象 | 来源可以是文件/网络/动态代理生成 |
| 验证 | 校验字节码合法性 | 文件格式、元数据、字节码、符号引用四类校验 |
| **准备** | 给静态变量分配内存并赋**默认值** | `static int a = 10` 此时 a = **0**；`static final int b = 10` 直接是 10（常量在编译期已确定） |
| 解析 | 符号引用 → 直接引用 | 可以延迟到首次使用时才解析 |
| **初始化** | 执行 `<clinit>` | 静态变量赋真实值 + 静态代码块；**按代码书写顺序**执行 |

**触发初始化的 6 种「主动引用」**

1. `new`、读写静态字段（非 final 常量）、调用静态方法
2. 反射 `Class.forName()`
3. 初始化子类时先初始化父类
4. 虚拟机启动时的主类
5. `MethodHandle` / `VarHandle` 解析结果
6. 默认方法（接口的 default）的实现类被初始化时

**不触发初始化的 3 种「被动引用」**

1. 通过子类引用父类的静态字段 → 只初始化父类，不初始化子类
2. 定义数组 `Foo[] arr = new Foo[10]` → 不初始化 Foo
3. 引用编译期常量 `static final` → 常量在编译期进了调用方的常量池（已折叠）
:::

:::拓展
**`<clinit>` 是线程安全的**

JVM 保证一个类的 `<clinit>` 只被一个线程执行，其他线程阻塞等待。所以「静态内部类 Holder 单例」是天然线程安全的懒加载写法——这正好解释了手册 11 里那个单例为什么会推荐它。

**类卸载（卸载条件很苛刻，三者同时满足）**

1. 该类的**所有实例**都已被回收
2. 加载该类的 **ClassLoader** 已被回收
3. 该类的 `Class` 对象没有被任何地方引用

热部署场景下 ClassLoader 被静态字段 / ThreadLocal / 线程池引用住，条件 2 永远不成立 → 类卸载不掉 → **元空间泄漏**（详见第 11 题）。
:::

:::追问
**Q：静态变量和静态代码块的执行顺序？**
按**书写顺序**。`static { a = 1; } static int a = 2;` 最终 a = 2；反过来则 a = 1。这是常见笔试题。

**Q：`Class.forName()` 和 `ClassLoader.loadClass()` 区别？**
`Class.forName` 默认会**执行初始化**（第二个参数可关）；`loadClass` 只到加载阶段，**不初始化**。JDBC 老代码用 `Class.forName("com.mysql.Driver")` 就是为了触发静态代码块注册驱动。

**Q：`<init>` 和 `<clinit>` 区别？**
`<clinit>` 是类构造器（静态代码 + 静态变量），一个类一个；`<init>` 是实例构造器（实例变量 + 构造方法体），每个构造器一个。
:::

:::锚点
你的项目里有两处能讲：① **node-ffi 加载 `.so`** 和 JVM 加载 native 库是同构的——`System.loadLibrary()` 会触发 `JNI_OnLoad`，跟 `<clinit>` 的角色一样（库级初始化钩子）。② Spring 启动慢，很大一部分就是「扫描 + 反射加载类 + 生成代理类」的开销——这跟你查 Metaspace 涨得快是同一件事的两面。
:::

---

## 3. 类加载器与双亲委派

:::概念
三层加载器：**Bootstrap（C++ 实现，加载 JDK 核心）→ Platform/Ext（扩展库）→ Application（classpath 应用类）**，另有自定义加载器。
规则：收到加载请求先**逐级向上委派**，父能加载就用父的，全失败才自己加载。两个好处：**安全（防核心类被篡改）+ 唯一（同一个类只被加载一次）**。
:::

:::提问
- 什么是双亲委派机制？为什么需要它？
- 有哪些类加载器？各加载什么？
- 什么时候会「破坏」双亲委派？举几个真实例子。
- 怎么自己写一个类加载器？
:::

:::答案
**委派链**

```
Bootstrap ClassLoader   ← C++ 实现，加载 $JAVA_HOME/lib（rt.jar / java.base）
        ↑ 委派
Platform ClassLoader    ← JDK9+ 从 Extension 改名，加载扩展库
        ↑ 委派
Application ClassLoader ← 加载 classpath / -cp 指定的应用类
        ↑ 委派
Custom ClassLoader      ← 自定义，如 Tomcat、Spring Boot 的 LaunchedURLClassLoader
```

**两个作用**

1. **安全**：自己写一个 `java.lang.String` 不会被加载——请求一路上委派到 Bootstrap，发现核心库已有，直接用核心库的。防止核心 API 被替换。
2. **唯一性**：同一份 class 文件被不同路径加载，也只会得到一个 `Class` 对象，避免 `instanceof` / 类型转换莫名失败。

**三次「破坏」**

| 场景 | 谁破坏 | 为什么 |
|---|---|---|
| SPI（JDBC、SLF4J） | 线程上下文类加载器 | 接口在核心库（Bootstrap 加载），实现类在应用 classpath（App 加载），父加载器看不到子加载器的类 → 用 `Thread.currentThread().getContextClassLoader()` 反向加载 |
| Tomcat / Web 容器 | `WebAppClassLoader` 子优先 | 多个 WebApp 要用不同版本的同一个库，必须隔离 → 先自己加载，加载不到再委派父 |
| OSGi / 热部署 | 网状委派 | 按包级别细粒度委派，支持模块热插拔 |
:::

:::拓展
**Spring Boot 的 LaunchedURLClassLoader**

Spring Boot fat jar 里的依赖不在文件系统上（嵌在 jar 的 `BOOT-INF/lib/` 里），所以自定义了加载器从嵌套 jar 里读字节流。这是「不用打破委派、只是换加载来源」的例子——重写 `findClass` 而不是 `loadClass`。

**怎么自定义类加载器**

```java
public class MyLoader extends ClassLoader {
    private final String baseDir;

    public MyLoader(String baseDir) {
        super(ClassLoader.getSystemClassLoader().getParent()); // 指定父
        this.baseDir = baseDir;
    }

    @Override
    protected Class<?> findClass(String name) throws ClassNotFoundException {
        byte[] bytes = readBytes(baseDir, name);      // 自己去读字节码
        if (bytes == null) throw new ClassNotFoundException(name);
        return defineClass(name, bytes, 0, bytes.length);
    }
}
```

要打破委派（子优先），才去重写 `loadClass`。**能用 `findClass` 解决的就别碰 `loadClass`**——重写 `loadClass` 是元空间泄漏的常见源头。
:::

:::追问
**Q：父加载器加载不了，子加载器能加载吗？**
不能。委派是单向的（子 → 父）；父没有「向下看」的能力。这正是 SPI 必须用线程上下文加载器的原因。

**Q：同一个 class 文件被两个不同的 ClassLoader 加载，是同一个类吗？**
不是。JVM 里类的唯一标识 = `ClassLoader + 全限定名`。这也是 Tomcat 能同时跑两个不同版本 Spring 的原理。

**Q：`ClassNotFoundException` 和 `NoClassDefFoundError` 区别？**
前者是显式加载时找不到（`Class.forName` / `loadClass` 抛）；后者是编译期在、运行期类初始化失败或找不到（`Error`，通常是依赖缺失或静态代码块抛异常）。
:::

:::锚点
你排查过的 `rrmcontrol` 国际环境 pod 反复重启（`write after end`）是 Node.js 的问题，但**同一类问题的 Java 版本**就是 ClassLoader 泄漏：连接池、定时器、监听器没注销，持有 ClassLoader → 元空间涨 → 容器 OOMKilled。面试官问「你遇到过内存泄漏吗」，你可以用容器里的现象（pod 反复重启、看不到堆栈）反推「这多半不是业务异常，而是资源没释放」——这个判断力比背八股值钱。
:::

---

## 4. 对象的内存布局与对象头

:::概念
对象 = **对象头（Mark Word + 类型指针）+ 实例数据 + 对齐填充**。
对象头里的 **Mark Word** 同时存 hashCode、GC 年龄、锁状态——它是 `synchronized` 锁升级的物理载体，这是把「对象布局」和「并发」串起来的关键。
:::

:::提问
- 一个对象在内存里占多大？对象头里有什么？
- 对象头多大？什么是压缩指针？
- 为什么对象大小要 8 字节对齐？
- 对象是怎么创建的？并发创建怎么保证安全？
:::

:::答案
**布局**

```
┌─────────── 对象头（Header）───────────┐
│ Mark Word（8 字节）                    │  ← hashCode / GC 年龄 / 锁状态 / 偏向线程
│ 类型指针 Klass Pointer（4 或 8 字节）  │  ← 指向方法区的 Class
├─────────── 实例数据（Instance Data）───┤  ← 各字段值
├─────────── 对齐填充（Padding）─────────┤  ← 补齐到 8 字节整数倍
```

64 位 JVM 开启压缩指针时，对象头 = 8 + 4 = **12 字节**。

**Mark Word 64 位的状态切换**（这就是锁升级）

| 锁状态 | 存储内容 | 标志位 |
|---|---|---|
| 无锁 | hashCode(31) + 分代年龄(4) + 偏向位0 | 01 |
| 偏向锁 | 偏向线程 ID(54) + epoch + 年龄 | 01 |
| 轻量级锁 | 指向栈中 Lock Record 的指针 | 00 |
| 重量级锁 | 指向 Monitor（ObjectMonitor）的指针 | 10 |
| GC 标记 | 空（不存 hashCode） | 11 |

**压缩指针**：64 位 JVM 里引用本来要 8 字节，开启 `-XX:+UseCompressedOops`（默认开）后用 4 字节存「偏移量 / 8」，堆小于 32G 时够用。**所以堆不要刚好设到 32G——超过后压缩指针失效，内存反而更紧张。**

**对象创建 5 步**

1. 检查类是否已加载（没加载先走类加载）
2. 分配内存：堆规整 → **指针碰撞**；堆有碎片 → **空闲列表**
3. 内存置零（保证字段有默认值）
4. 设置对象头（Mark Word、类型指针）
5. 执行 `<init>`（构造方法）

**并发安全**：CAS + 失败重试，或 **TLAB（Thread Local Allocation Buffer）**——每个线程在 Eden 里先划一块私有缓冲区，各自分配互不干扰。
:::

:::拓展
**对齐填充不是为了好看**

CPU 读内存是按「缓存行（Cache Line，通常 64 字节）」读的。字段按 8 字节对齐可以避免一个字段跨两个缓存行（false sharing 伪共享的物理基础）。`@Contended` 注解就是靠填充把热点字段隔离到不同缓存行。
:::

:::追问
**Q：为什么偏向锁在 JDK15 之后被默认关闭了？**
偏向锁的「撤销」需要 STW（safepoint），在高并发/大量锁竞争场景下开销大于收益，而且实现复杂难维护。JDK15 起 `-XX:-UseBiasedLocking` 成为默认。
:::

:::锚点
你在 rrmcompute 里处理 OOM 时，如果算过「一个 OptHistory 文档对象在堆里占多大」——那就用上了这套：对象头 12 字节 + 字段 + 对齐。dump 分析工具（MAT）显示的 retained size 也是同一套逻辑。**如果你在面试里能说出「容器 -Xmx5g 大概能放多少这种对象」这种量级估算，面试官会觉得你真的摸过内存。**
:::

---

## 5. 垃圾回收：可达性分析与三种算法

:::概念
判活用**可达性分析**（从 GC Roots 出发，不可达就是垃圾）；回收用三种算法：**标记-清除（有碎片）、复制（新生代）、标记-整理（老年代）**。
为什么不用引用计数？**循环引用会漏判**。
:::

:::提问
- 怎么判断一个对象是垃圾？
- GC Roots 有哪些？
- 为什么不用引用计数？
- 三种回收算法分别用在哪？新生代为什么用复制？
:::

:::答案
**GC Roots（五类）**

1. 虚拟机栈中引用的对象（局部变量）
2. 方法区中静态属性引用的对象
3. 方法区中常量引用的对象（字符串常量池）
4. 本地方法栈中 JNI 引用的对象
5. JVM 内部引用：基本类型 Class 对象、常驻异常对象（NPE/OOM）、系统类加载器

**四种引用**

| 引用 | 回收时机 | 典型用途 |
|---|---|---|
| 强引用 | 永不回收（除非不可达） | 普通 `new` |
| 软引用 | 内存不足时回收 | 缓存 |
| 弱引用 | 下次 GC 就回收 | `ThreadLocalMap` 的 key、`WeakHashMap` |
| 虚引用 | 对象被回收时收到通知 | `DirectByteBuffer` 的 Cleaner |

**三种算法**

| 算法 | 过程 | 优点 | 缺点 | 用在哪 |
|---|---|---|---|---|
| 标记-清除 | 标记垃圾 → 直接清除 | 简单 | **内存碎片**，大对象可能分配失败 | CMS |
| 复制 | 存活对象复制到另一半 | 无碎片、快 | 浪费空间 | 新生代（Eden:S0:S1 = 8:1:1） |
| 标记-整理 | 存活对象移到一端 → 清边界外 | 无碎片 | 移动对象要 STW，慢 | 老年代 |

**分代假设**：绝大多数对象朝生夕死（弱分代假说）→ 新生代用复制（存活率低，复制成本小）；熬过多次 GC 的是「老不死」→ 老年代用标记-整理。
:::

:::拓展
**三色标记法**（并发标记的理论基础）

- 白色：未访问（最终仍白的 = 垃圾）
- 灰色：自己访问了，成员还没访问完
- 黑色：自己和成员都访问完

**并发标记的两个问题**

1. **漏标**（对象消失）：黑色对象新指向了白色对象，且灰色对象到该白色对象的引用被删除 → 白色对象被误回收。解决：**增量更新（CMS，写屏障记录新引用，重新标记时重扫）** 或 **原始快照 SATB（G1，记录旧引用，按开始时的快照标记）**
2. **浮动垃圾**：标记期间新产生的垃圾本轮收不掉，留到下一轮

**Stop-The-World**：可达性分析必须在一个「一致性快照」上进行，所以初始标记和重新标记阶段要 STW。**调优的本质就是压缩 STW 总时长。**
:::

:::追问
**Q：为什么新生代 Survivor 是两块轮流用？**
复制算法的要求：永远留一块空的目的地。刚经历过 Minor GC 存活的对象在 S0，下次 GC 复制到 S1，S0 清空——角色互换。

**Q：对象什么时候进老年代？**
① 年龄达到 `-XX:MaxTenuringThreshold`（默认 15）；② **动态年龄判断**：Survivor 中相同年龄对象总和 > Survivor 一半，该年龄及以上的直接晋升；③ 大对象（超过 `-XX:PretenureSizeThreshold`）直接进老年代。

**Q：`finalize()` 能救回对象吗？**
能，但只能救一次，且不保证执行时机。**生产禁用**，用 try-with-resources / Cleaner 替代。
:::

:::锚点
排查 rrmcompute 内存问题时的核心判断：**「GC 后老年代能否回落到基线」是区分「内存泄漏」和「内存不够」的唯一标准**。回不去、且逐次抬高 = 泄漏（对象被长期引用住）；回得去但很快又满 = 单纯不够用（调大堆或限并发）。这个判断比看代码快得多。
:::

---

## 6. 垃圾回收器：CMS vs G1（及 ZGC）

:::概念
**CMS**：并发标记清除，低停顿但有碎片，JDK9 起废弃。**G1**：Region 化堆、可预测停顿、无碎片，JDK9+ 默认。**ZGC**：染色指针 + 读屏障，停顿 < 10ms，JDK15+ 生产可用。
选型一句话：**吞吐优先 Parallel，低延迟 G1，极致低延迟 ZGC。**
:::

:::提问
- CMS 和 G1 有什么区别？
- G1 怎么做到「可预测停顿」？
- 项目里用什么收集器？为什么？
- 什么是 concurrent mode failure？
:::

:::答案
**对比**

| | CMS | G1 |
|---|---|---|
| 分代 | 物理连续分代 | Region 化（逻辑分代） |
| 算法 | 标记-清除 | 整体标记-整理，Region 间复制 |
| 碎片 | **有** | 无 |
| 停顿 | 低但不稳定 | **可预测**（`-XX:MaxGCPauseMillis` 目标） |
| 大对象 | 直接进老年代 | Humongous Region |
| 状态 | JDK9 废弃，JDK14 移除 | JDK9+ 默认 |

**G1 四个阶段**

1. 初始标记（STW，很短）—— 标记 GC Roots 直接可达对象
2. 并发标记（与业务并发）—— 遍历整个对象图，用 **SATB** 记录快照
3. 最终标记（STW，很短）—— 处理 SATB 队列里的遗留引用
4. 筛选回收（STW）—— 按 **回收收益/成本模型** 排序 Region，优先回收垃圾最多的（Garbage First 的来源），在停顿目标内挑最大收益组合

**可预测停顿的本质**：G1 不是「一次收完」，而是「在给定时间预算内收收益最高的那批 Region」。停顿目标越小，每次收的 Region 越少，GC 次数越多。

**CMS 四阶段**：初始标记（STW）→ 并发标记 → 重新标记（STW，用**增量更新**）→ 并发清除。
:::

:::拓展
**收集器全景与选型**

| 收集器 | 分代 | 停顿 | 适用 |
|---|---|---|---|
| Serial | 单线程 | 长 | 客户端小程序、容器里单核 |
| ParNew | 并行新生代 | 中 | 配 CMS 用 |
| Parallel Scavenge / Old | 并行 | 中 | **吞吐优先**（批处理、离线计算） |
| CMS | 并发 | 低但不稳 | 已废弃 |
| **G1** | Region | 可预测 | **默认选择**，4G~32G 堆最佳 |
| ZGC / Shenandoah | 不分代（ZGC16+ 分代） | **< 10ms** | 超大堆（TB 级）、极致低延迟 |

**常用参数**

```bash
# 通用（容器环境推荐）
-XX:+UseG1GC
-XX:MaxGCPauseMillis=200          # 期望最大停顿（软目标）
-XX:MaxRAMPercentage=75.0         # 按容器 limit 算堆，替代写死 -Xmx
-XX:+HeapDumpOnOutOfMemoryError
-XX:HeapDumpPath=/data/dump

# 容器里强烈建议显式关掉这个（JDK8u191 之前不识别 cgroup）
-XX:+UseContainerSupport          # JDK10+ 默认开
```

**为什么容器里用 `-XX:MaxRAMPercentage` 而不是写死 `-Xmx`**：同一个镜像要在不同规格的 Pod 上跑，写死堆大小会导致小规格 OOMKilled、大规格浪费。按 limit 百分比算，一次配置到处跑。
:::

:::追问
**Q：什么是 concurrent mode failure？**
CMS 并发清除期间，老年代被新晋升的对象填满（预留空间不足）→ 被迫退化成 **Serial Old 单线程 Full GC**（STW 超长）。预防手段：`-XX:CMSInitiatingOccupancyFraction=70` 提前触发、`-XX:+UseCMSInitiatingOccupancyOnly` 固定阈值。

**Q：G1 的 Humongous 对象是什么？**
大于等于 Region 一半的对象（Region 默认堆的 1/2048）。它占用连续的 Humongous Region，分配和回收成本都高。**频繁出现 Humongous 分配说明有大对象反复创建**，日志里会看到 `Humongous` 字样——这是 G1 特有的调优点。

**Q：ZGC 为什么能做到 < 10ms？**
染色指针（把标记信息存在 64 位指针的高位里）+ 读屏障（读取引用时顺带修正）+ 并发转移。代价是吞吐下降、内存占用更高。
:::

:::锚点
你们 K8s 环境里的服务（rrmcompute 等）基本都是容器 + JVM。面试时可以直接讲：**「我们按容器 limit 的 75% 设堆（`-XX:MaxRAMPercentage`），收集器用 G1，因为服务是长连接 + 实时调优任务，要求停顿可控；现网 rrmcompute 之前用 5Gi 堆时在高量任务下出现过 OOM 重启，后来加到 5.5GiB 并限制任务并发。」** —— 这段话里有选型、有参数、有故障、有处置，是一段完整的工程叙事。
:::

---

## 7. JMM（Java 内存模型）与 volatile

:::概念
JMM 定义了**多线程间共享变量的可见性规则**：变量存主内存，线程操作自己工作内存里的副本，靠 volatile / synchronized / final 保证同步。
**volatile 保可见性 + 禁止指令重排，但不保证原子性。**
:::

:::提问
- volatile 有什么作用？能替代 synchronized 吗？
- 什么是可见性、原子性、有序性？
- happens-before 规则是什么？
- DCL 单例为什么要加 volatile？
:::

:::答案
**三个问题**

| 问题 | 含义 | 解决手段 |
|---|---|---|
| 可见性 | 一个线程改了，另一个线程看不见（各自读缓存副本） | volatile、synchronized、final |
| 原子性 | 操作不可分割（`i++` 其实是读-改-写三步） | synchronized、Lock、AtomicXxx |
| 有序性 | 编译器和 CPU 会重排指令 | volatile、synchronized、happens-before |

**volatile 的两个语义**

1. **可见性**：写操作立即刷回主内存，读操作直接从主内存读，并使其他线程的副本失效
2. **禁止重排**：插入内存屏障（LoadLoad / StoreStore / LoadStore / StoreLoad），禁止 volatile 前后的指令越过它重排

**关键结论：`volatile` 不保证原子性**。`volatile int i; i++` 在多线程下依然会丢更新。要原子性得用 `synchronized` 或 `AtomicInteger`（CAS）。

**happens-before 六条**

1. 程序顺序：同一线程内，前面的操作 hb 后面的操作（**只是保证单线程语义，多线程下不保证**）
2. 监视器锁：解锁 hb 后续对该锁的加锁
3. volatile：对 volatile 变量的写 hb 后续的读
4. 线程启动：`Thread.start()` hb 新线程里的所有操作
5. 线程终止：线程里所有操作 hb 其他线程检测到它结束（`join()` 返回）
6. 传递性：A hb B，B hb C ⇒ A hb C
:::

:::拓展
**DCL 单例为什么必须 volatile**

```java
private static volatile Singleton INSTANCE;   // volatile 不可省！

static Singleton get() {
    if (INSTANCE == null) {
        synchronized (Singleton.class) {
            if (INSTANCE == null) INSTANCE = new Singleton();
        }
    }
    return INSTANCE;
}
```

`new Singleton()` 编译后是三步：① 分配内存 ② 初始化对象 ③ 把引用赋给 INSTANCE。**② 和 ③ 可能重排**。若先执行 ③（引用已非 null，但对象还没初始化），另一个线程在第一次 `if` 检查时看到 `INSTANCE != null`，直接拿去用 —— 拿到一个**半成品对象**。`volatile` 禁止了这个重排。

**MESI 缓存一致性协议**：现代 CPU 靠 MESI 维护多核缓存一致性（Modified/Exclusive/Shared/Invalid）。volatile 的内存屏障本质上是在触发缓存行的失效与同步。

**伪共享（False Sharing）**：两个不相关的变量落在同一个缓存行，一个核改了导致另一个核的缓存行失效。解决：填充（`@Contended`）或让变量独占缓存行。Disruptor 框架的性能秘诀之一。
:::

:::追问
**Q：`synchronized` 和 `volatile` 怎么选？**
只需要「一个线程写、多个线程读」的状态标志位 → volatile（轻量）。需要「复合操作的原子性」 → synchronized / Lock / 原子类。

**Q：`volatile int i; i++` 会怎样？**
丢失更新。因为 `i++` = 读 i → 加 1 → 写回，中间可能被其他线程插进来。正确做法：`AtomicInteger.incrementAndGet()`（CAS 自旋）。

**Q：final 为什么能保证可见性？**
final 字段在构造器里写完后，JMM 要求「写 final 字段」与「把该对象引用赋给其他变量」之间不能重排 —— 所以正确构造的对象，其他线程一定看到 final 字段的正确值（不用加锁）。
:::

:::锚点
你是 Node.js 出身，这里有一个**很能体现理解深度的对比**：Node 主线程单线程执行 JS，不存在共享内存的可见性问题（cluster/worker_threads 之间靠消息传递而非共享变量）；而 JVM 里线程是真并行、共享堆。**所以「为什么 JS 不需要 volatile」这个问题的答案，恰好证明了 JMM 存在的意义**。面试里主动做这个对比，比只会背六条 happens-before 强得多。
:::

---

## 8. 逃逸分析与栈上分配

:::概念
JIT 的**逃逸分析**判断对象会不会「逃出」方法：不逃逸就在**栈上分配**（随方法结束自动销毁，不进堆、不参与 GC），或做**标量替换**、**锁消除**。
:::

:::提问
- 什么是逃逸分析？能带来哪些优化？
- 栈上分配和堆上分配的区别？
- 逃逸分析一定生效吗？
:::

:::答案
**什么算「逃逸」**

| 情形 | 是否逃逸 |
|---|---|
| 对象只在方法内使用，不被返回 | 不逃逸 → 可优化 |
| 对象作为返回值返回 | 逃逸 |
| 对象赋值给静态字段 / 成员字段 | 逃逸 |
| 对象作为参数传给**未知方法** | 保守认为逃逸 |

**三种优化**

1. **栈上分配**：不逃逸对象直接在栈帧里分配，方法返回即销毁 —— 减少 GC 压力
2. **标量替换**：把对象拆成若干局部变量（把「聚合量」拆成「标量」），对象根本不创建
3. **锁消除**：对象只在单线程内使用 → 加在它上面的锁直接去掉（StringBuffer 在局部变量里用就会触发）

**开启**：`-XX:+DoEscapeAnalysis`（JDK6u23+ 默认开），`-XX:+EliminateAllocations`（标量替换，默认开）。
:::

:::拓展
**JIT 分层编译（Tiered Compilation）**

- C1（Client）：编译快、优化浅 → 方法刚热起来时用
- C2（Server）：编译慢、优化深（逃逸分析就在这层）
- 方法被调用到阈值（`-XX:CompileThreshold`，C1 默认 1500，C2 默认 10000）才被编译

**Code Cache 的坑**：JIT 编译产物放在 Code Cache（独立区域，`-XX:ReservedCodeCacheSize`，默认 240M）。Code Cache 满了之后 JIT 停止编译、退回解释执行 → **性能莫名劣化但 GC 正常**。日志里会看到 `CodeCache is full. Compiler has been disabled.`
:::

:::追问
**Q：逃逸分析一定生效吗？**
不一定。① 可以通过 `-XX:-DoEscapeAnalysis` 关闭；② 只有 C2 编译过的热点方法才做（前几次执行是解释器/C1，没优化）；③ 对象太大或方法太复杂时分析会放弃。

**Q：栈上分配的对象会参与 GC 吗？**
不会。它随栈帧销毁，不进入堆，GC 根本看不到它。这也是「减少小对象分配能减轻 GC」的原理。

**Q：为什么说「不要过早优化」？**
因为逃逸分析这类优化是 JIT 自动做的，手写「对象池」反而可能破坏 JIT 的优化（对象被长期引用住了，逃逸了），还可能引入内存泄漏。
:::

:::锚点
你在 rrmcompute 处理内存暴涨时，如果代码里有「循环里创建临时对象」（比如每次计算都 new 一个结果包装对象），那就是 GC 压力的直接来源。**面试时讲「我们通过减少循环内的大对象创建 + 限制并发任务数把内存压下来了」，比笼统说「优化了内存」具体得多。**
:::

---

## 9. 排查命令与调优总览

:::概念
`jps` 找进程 → `jstat` 看 GC → `jmap` 出堆转储 → `jstack` 看线程栈 → `jinfo` 看参数 → **`jcmd` 万能**。
调优目标只有两个：**减少 Full GC 次数** + **控制单次停顿时长**。
:::

:::提问
- 线上 CPU 100% 怎么排查？
- 内存泄漏怎么定位？
- 常用 JVM 参数有哪些？
- 你会用哪些工具？
:::

:::答案
**命令速查**

| 命令 | 用途 | 危险度 |
|---|---|---|
| `jps -l` | 列出 JVM 进程 | 安全 |
| `jstat -gcutil <pid> 1000` | 每秒打印各区使用率 + GC 次数/耗时 | 安全 |
| `jstat -gc <pid> 1000` | 更详细（含各代容量与用量） | 安全 |
| `jmap -heap <pid>` | 堆配置与使用概况 | 安全 |
| `jmap -histo:live <pid>` | 类直方图（**会触发 Full GC**） | ⚠️ 慎用 |
| `jmap -dump:format=b,file=x.hprof <pid>` | 堆转储 | ⚠️ **STW，生产慎用** |
| `jstack <pid>` | 线程栈，死锁检测 | 安全（短暂 STW） |
| `jinfo -flags <pid>` | 查看运行参数 | 安全 |
| `jcmd <pid> GC.heap_info` | jcmd 版堆信息 | 安全 |
| `jcmd <pid> VM.native_memory summary` | 本地内存明细 | 需预设 NMT |

**CPU 100% 排查五步**

```bash
1. top                     # 找到 CPU 高的 Java 进程 PID
2. top -Hp <pid>           # 找到该进程内 CPU 高的线程 TID
3. printf "%x\n" <TID>     # TID 转十六进制（jstack 里的 nid 是十六进制）
4. jstack <pid> > stack.txt
5. grep -A 30 "nid=0x<hex>" stack.txt   # 定位到具体代码行
```

**内存泄漏排查五步**

```bash
1. jstat -gcutil <pid> 5000              # 看 O 区是否 GC 后不回落、逐次抬高
2. jmap -dump:format=b,file=/tmp/heap.hprof <pid>   # 取两份 dump（间隔 30min 更准）
3. 用 MAT 打开 → Leak Suspects 报告
4. 看 Dominator Tree（支配树）找 retained size 最大的对象
5. 对可疑对象右键 → Path to GC Roots → exclude weak/soft references
```

**关键参数**

```bash
-Xms4g -Xmx4g                     # 建议设成相等，避免动态扩容抖动
-XX:MaxRAMPercentage=75.0         # 容器环境推荐
-XX:MetaspaceSize=256m -XX:MaxMetaspaceSize=512m
-Xss512k                          # 每线程栈，线程多时要调小（容器里线程数受限）
-XX:+HeapDumpOnOutOfMemoryError -XX:HeapDumpPath=/data/dump
-XX:+UseG1GC -XX:MaxGCPauseMillis=200
-XX:+PrintGCDetails -Xloggc:/data/logs/gc.log     # JDK8
-Xlog:gc*:file=/data/logs/gc.log:time,uptime      # JDK9+
```
:::

:::拓展
**arthas —— 线上诊断的神器**（阿里开源，不停机 attach）

```bash
# 启动
curl -O https://arthas.aliyun.com/arthas-boot.jar
java -jar arthas-boot.jar          # 选进程号

# 常用命令
dashboard                # 实时面板：线程 + 内存 + GC
thread                   # 列出所有线程及 CPU 占用
thread -n 3              # CPU 最高的 3 个线程栈
thread -b                # 直接找出阻塞其他线程的「死锁元凶」
heapdump /tmp/a.hprof    # 导出堆
jad com.xxx.Service      # 反编译线上类（确认跑的是哪个版本！）
watch com.xxx.Service method '{params, returnObj}' -x 3   # 方法出入参观测
trace com.xxx.Service method          # 方法内部调用链路耗时
profiler start / stop    # 生成火焰图
```

`jad` 这个命令特别有用——**能确认线上跑的到底是哪个版本的代码**，跟你们核对镜像里文件 md5 是一个思路。

**async-profiler**：低开销采样，生成火焰图（`-e cpu` / `-e alloc` / `-e lock`）。
:::

:::追问
**Q：`jmap -dump` 会 STW 吗？生产能用吗？**
会。堆越大停顿越久（几十秒到几分钟）。生产三板斧：① 提前配 `-XX:+HeapDumpOnOutOfMemoryError` 让它自动转储；② 从**从节点**或**流量低谷**再做；③ 用 `jcmd` 的 `GC.heap_dump` 或 arthas 的 `heapdump`（相对温和）。

**Q：容器里怎么排查？**
`kubectl exec -it <pod> -- bash` 进容器（前提是镜像里有 JDK 而不是只有 JRE，JRE 没有 jmap/jstack，要装 `openjdk-devel` 或用 arthas）。更稳的做法是**把 dump 目录挂成 PVC/宿主目录**，OOM 时 dump 自动落盘，Pod 重启也不丢。

**Q：`jstat -gcutil` 里各列什么意思？**
`S0 S1 E O M` = Survivor0 / Survivor1 / Eden / Old / Metaspace 使用率（%）；
`CCS` = 压缩类空间；`YGC YGCT` = 新生代 GC 次数 / 总耗时；
`FGC FGCT` = Full GC 次数 / 总耗时；`GCT` = 总 GC 耗时。**重点盯 `O`（老年代）和 `FGC`**。
:::

:::锚点
你们现网是 K8s + 容器，进容器排查要过跳板机。简历/面试里可以这样讲：「**线上问题定位走 kubectl exec 进容器用 jcmd/jstat 看 GC 指标，配合现网日志和监控；涉及堆内存问题会挂 PV 存 dump，避免 Pod 重启丢失现场。**」——这个细节说明你处理过真实的生产环境约束，而不是在本地 IDE 里玩。
:::

---

## 10. GC 日志怎么读 ★

:::概念
GC 日志是内存调优的**唯一事实来源**——所有猜测都要用它验证。
判读只看三个维度：**频率**（多久一次）、**效果**（GC 后能否回落）、**停顿**（单次多长）。
一句话判据：**GC 后回落不到基线且逐次抬高 = 内存泄漏；回得去但频率高 = 分配率过高或堆太小。**
:::

:::提问
- GC 日志怎么开启？
- 日志里每个字段是什么意思？
- 怎么从 GC 日志判断有没有内存泄漏？
- Minor GC 很频繁但 Full GC 正常，有问题吗？
:::

:::答案
**开启方式**

```bash
# JDK8
-XX:+PrintGCDetails
-XX:+PrintGCDateStamps
-XX:+PrintHeapAtGC                 # 每次 GC 前后打印堆详情
-Xloggc:/data/logs/gc.log
-XX:+UseGCLogFileRotation -XX:NumberOfGCLogFiles=10 -XX:GCLogFileSize=50M

# JDK9+（统一日志框架，更推荐）
-Xlog:gc*:file=/data/logs/gc.log:time,uptime,level,tags:filecount=10,filesize=50M
-Xlog:gc+heap=debug:file=/data/logs/gc.log     # 想看堆详情加这段
```

**一行真实日志逐字段拆**（JDK8 + ParallelGC 格式）

```
2026-09-18T10:23:41.512+0800: 4231.876: [GC (Allocation Failure)
  [PSYoungGen: 655360K->52480K(752640K)] 812345K->221465K(2048000K), 0.0314521 secs]
  [Times: user=0.21 sys=0.02, real=0.03 secs]
```

| 片段 | 含义 |
|---|---|
| `2026-09-18T10:23:41.512+0800` | 墙钟时间（必须开 `PrintGCDateStamps`，否则只有 uptime 没法对日志） |
| `4231.876` | JVM 启动以来的秒数（uptime） |
| `[GC` | **Minor GC**；`[Full GC` 才是 Full GC |
| `(Allocation Failure)` | 触发原因：分配失败。其他常见：`Metadata GC Threshold`（元空间到阈值）、`System.gc()`、`Ergonomics`、`Humongous Allocation`（G1 大对象） |
| `[PSYoungGen: 655360K->52480K(752640K)]` | **新生代** GC 前→后（总容量）。回收掉 602880K |
| `812345K->221465K(2048000K)` | **全堆** GC 前→后（总容量） |
| `0.0314521 secs` | **本次停顿时间**（0.03 秒 ≈ 31ms） |
| `[Times: user=0.21 sys=0.02, real=0.03]` | user=多核 CPU 总耗时，sys=系统调用耗时，**real=墙钟停顿**。`user/real > 核数` 说明多线程并行 |

**三种形态判读（核心）**

| 形态 | GC 日志表现 | 结论 | 处置 |
|---|---|---|---|
| **内存泄漏** | Full GC 后老年代**降不下去**（如始终 1.6G/2G），且逐次抬高；Full GC 越来越频繁 | 对象被长期引用 | 取 dump 用 MAT 找 GC Roots 引用链 |
| **内存不足** | GC 后能回落到低位（如降到 200M），但**很快就又满**，Minor GC 极频繁 | 分配率高 / 堆偏小 | 调大堆、减少对象分配（循环内 new）、提高新生代比例 |
| **停顿过长** | 单次 `real` > 1s，尤其 Full GC | 堆太大或收集器不合适 | 换 G1 设 `MaxGCPauseMillis`；或拆分堆 |

**辅助命令（和日志交叉验证）**

```bash
jstat -gcutil <pid> 5000     # O 列百分比 + FGC 计数，最直观
jstat -gccause <pid> 5000    # 多看一列 LGCC：上次 GC 原因
```

**内存泄漏的判据（背下来）**

> 连续观察几次 Full GC，如果 `Full GC 后的老年代占用` 这个数值**基本不降或持续抬高**，就是泄漏。反之每次都回落到同一基线，就是单纯不够用。
:::

:::拓展
**G1 日志长什么样**

```
[2026-09-18T10:23:41.512+0800][info][gc,start] GC(123) Pause Young (Normal) (G1 Evacuation Pause)
[2026-09-18T10:23:41.545+0800][info][gc,phases] GC(123)   Evacuate Collection Set: 28.1ms
[2026-09-18T10:23:41.546+0800][info][gc,heap] GC(123) Eden regions: 210->0(240)
[2026-09-18T10:23:41.546+0800][info][gc,heap] GC(123) Survivor regions: 5->12(30)
[2026-09-18T10:23:41.546+0800][info][gc,heap] GC(123) Old regions: 180->186(600)
[2026-09-18T10:23:41.547+0800][info][gc,phases] GC(123)   Other: 0.9ms
[2026-09-18T10:23:41.547+0800][info][gc] GC(123) Pause Young (Normal) (G1 Evacuation Pause) 394M->197M(1600M) 34.071ms
```

关注点变了：**Region 为单位计数**（不是字节），看 `Old regions` 是否单调上涨，看 `Pause` 后面的毫秒数（就是 STW 时长），看 `Humongous` 有没有频繁出现。

**在线分析工具**：GCeasy（上传日志出报告，免费额度够用）、GCParser、`gcviewer`。生产排障时先传日志生成趋势图，比人肉 grep 快得多。

**Node.js 的类比**：Node 没有 GC 日志，但 `node --trace-gc --max-old-space-size=2048 app.js` 会打印每次 GC 前后大小和耗时，判读逻辑完全一样——**看回收后能否回落**。
:::

:::追问
**Q：Minor GC 很频繁但 Full GC 正常，有问题吗？**
看程度。Minor GC 本身很快（几十 ms），频繁但每次停顿短、且对象确实朝生夕死，是正常的。**但如果 Minor GC 后存活对象大量涌入老年代（促销率高），就会把老年代撑满导致 Full GC** —— 这时要查「是不是有大对象」或「Survivor 太小」。判据是 `jstat -gcutil` 里 `O` 列是否在缓涨。

**Q：日志写爆磁盘怎么办？**
必须配滚动：JDK8 用 `-XX:+UseGCLogFileRotation`；JDK9+ 用 `-Xlog:...:filecount=10,filesize=50M`。**GC 日志开启后每秒可能写几 KB 到几 MB**，不滚动是生产事故隐患。

**Q：停顿时间（real）比 CPU 时间（user）短正常吗？**
正常。`real < user` 说明 GC 是多线程并行的（多个核同时干活，墙钟时间小于 CPU 累计时间）。若 `real ≈ user` 说明是单线程 GC（Serial），该换收集器了。
:::

:::锚点
rrmcompute 现网 OOM 排查时，时间线应该这样串（面试可以直接讲）：

**现象** → Pod 反复重启，K8s 事件里是 `OOMKilled`，应用日志里**看不到** `OutOfMemoryError`（这是关键区别！）
**为什么看不到堆栈** → 被 cgroup 杀的是进程，不是 JVM 自己抛的 OOM，所以没有 Java 堆栈
**怎么定位** → ① 看 Pod 的 memory limit 历史曲线，确认是内存打满被杀；② 进容器 `jstat -gcutil` 看 `O`（老年代）和 `FGC`，发现 GC 后老年代回落但很快又满 → **不是泄漏，是不够用**；③ 结合业务日志确认是「高量调优任务」并发进入时内存暴涨
**处置** → 内存 5Gi → 5.5GiB（requests=3Gi），同时限制任务并发度、检查有没有无界的缓存/集合增长
**反思** → 「容器里堆大小必须和 limit 联动（`-XX:MaxRAMPercentage`），且要留 25% 给非堆」
:::

---

## 11. 方法区/元空间满了怎么办 ★

:::概念
报错特征：JDK8+ 是 `java.lang.OutOfMemoryError: Metaspace`，JDK7- 是 `PermGen space`。
根因 90% 是两类：**动态生成类太多**（代理/字节码增强）或 **ClassLoader 泄漏**（旧加载器被引用住，它加载的所有类都卸载不掉）。
:::

:::提问
- 元空间为什么会满？
- 怎么排查是哪个类加载器泄漏？
- 怎么避免？
- 什么情况会动态生成大量类？
:::

:::答案
**为什么会满（三个原因）**

| 原因 | 具体场景 |
|---|---|
| **动态生成类太多** | CGLIB / JDK 动态代理（Spring AOP 每个被代理 Bean 一个类）、反射、JSP/Groovy 编译、ASM/ByteBuddy 字节码增强（APM Agent、Mockito）、Lambda（`LambdaMetafactory` 生成的类） |
| **ClassLoader 泄漏**（最常见） | 热部署 / redeploy 时旧 ClassLoader 被**静态字段、ThreadLocal、线程池、监听器、JDBC Driver 注册表、缓存**引用住 → 卸载条件不成立 → 它加载的所有类永久驻留 |
| 常量池膨胀 | 大量 `intern()` 字符串（JDK7+ 字符串常量已在堆，影响较小） |

**四步排查**

```bash
1. 确认是元空间，不是堆
   jstat -gcutil <pid> 5000
   # 看 M（Metaspace）与 MU/MC 两列：持续上涨且 Full GC 后不回落 → 元空间问题

2. 看有多少 ClassLoader、各加载了多少类
   jmap -clstats <pid>
   # 输出每个 ClassLoader 的 class count。
   # 若 ClassLoader 数量和类数量随时间单调上涨 → 泄漏实锤

3. 看类是否只加载不卸载
   -XX:+TraceClassLoading -XX:+TraceClassUnloading   # 启动时加
   # 或 jcmd <pid> VM.classloader_stats

4. 找是谁引用住了 ClassLoader
   jmap -dump:format=b,file=/tmp/heap.hprof <pid>
   # MAT 打开 → 搜 ClassLoader → Path to GC Roots（exclude weak/soft）
   # 常见元凶：静态 Map、ThreadLocal、线程池、Timer、监听器列表、日志框架的 appender
```

**怎么办**

治标（马上恢复服务）：

```bash
-XX:MaxMetaspaceSize=512m     # 先调大（默认无上限，受本地内存限制）
# 或者直接重启 Pod
```

治本（杜绝复发）：

1. **修 ClassLoader 泄漏**：静态字段不持有 ClassLoader；`ThreadLocal` 用完必须 `remove()`（线程池场景是重灾区）；注销监听器 / `DriverManager.deregisterDriver`；Agent 卸载
2. **限制动态类生成**：有接口时优先 JDK 动态代理而不是 CGLIB；**Spring AOP 切点别写太宽**（`execution(* com..*(..))` 会给几乎所有 Bean 生成代理类）；缓存代理类而不是每次重复生成
3. **设上限 + 监控告警**：`-XX:MaxMetaspaceSize` 明确设一个值，让它**早点暴露**而不是吃光本地内存拖垮宿主机；对 Metaspace 使用率设阈值告警
:::

:::拓展
**为什么 Metaspace 默认无上限反而危险**

元空间在本地内存，默认上限约等于物理内存。若单机跑多个容器，一个泄漏的 JVM 会**偷偷吃掉宿主机内存**，最后是宿主机整体 OOM 或者被 K8s 判定超限驱逐——比设上限后自己先报错更糟。所以**生产必须设 `-XX:MaxMetaspaceSize`**。

**JDK8 vs JDK8+ 的差异**

| | 永久代（≤JDK7） | 元空间（JDK8+） |
|---|---|---|
| 位置 | JVM 堆内 | 本地内存（堆外） |
| 参数 | `-XX:MaxPermSize` | `-XX:MaxMetaspaceSize` |
| 默认上限 | 有限（易 OOM） | 无限（受物理内存限制） |
| GC 时机 | 只能等 Full GC | 元空间达阈值就触发 GC（日志里 `Metadata GC Threshold`） |

**Metaspace 的 GC 触发**

日志里出现 `[GC (Metadata GC Threshold)` 就说明**这次 GC 是元空间快满触发的**，不是堆不够——这是一个很容易被误判的信号。
:::

:::追问
**Q：`jmap -clstats` 输出里怎么判断泄漏？**
看两件事：① `ClassLoader` 实例**数量**是否单调上涨（每次 redeploy 多一个且旧的不消失）；② 某个 ClassLoader 的 `class count` 很大且持续增长。**正常稳态下这两个数都应该收敛。**

**Q：为什么热部署最容易泄漏？**
每次 redeploy 都 new 一个 ClassLoader 加载整个应用。只要有一处（一个静态字段、一个没 remove 的 ThreadLocal、一个活着的线程）引用住旧 ClassLoader，整套旧类就都留下。这就是 **Tomcat 内存泄漏警告**（`The web application appears to have started a thread but has failed to stop it`）的由来——Tomcat 会在 shutdown 时主动清理一批已知泄漏点。

**Q：Lambda 也会生成类？**
会。每个 Lambda 表达式在运行时通过 `LambdaMetafactory` 生成一个实现类。大量不同的 Lambda（尤其在循环/动态场景）会持续生成类。正常代码里静态 Lambda 是复用的，问题不大。

**Q：`-XX:MetaspaceSize` 和 `-XX:MaxMetaspaceSize` 区别？**
前者是**首次触发 GC 的阈值**（初始高水位，默认约 21M，太小会导致启动期频繁 GC），后者是硬上限。生产建议两个都设，例如 `-XX:MetaspaceSize=256m -XX:MaxMetaspaceSize=512m`。
:::

:::锚点
你项目里最相关的两个点：

① **Spring AOP 切点范围**——如果写过 `@Around("execution(* com.h3c..*(..))")` 这种宽切点，每个被匹配的 Bean 都会生成代理类，Bean 多的时候元空间增长明显。面试时可以说「我们控制切点范围，只对需要的注解标记的方法织入」。

② **rrmcompute 内存调优的另一半故事**——调内存时不只调堆，元空间也要一起看。如果当时只调 `-Xmx` 没动 `-XX:MaxMetaspaceSize`，元空间仍然可能撞顶。**能说出「容器内存 = 堆 + 元空间 + 线程栈 + 直接内存 + Code Cache」这个公式，并知道每一块怎么配参数，就已经超过大多数候选人。**
:::

---

## 12. 线上 OOM / Full GC 频繁排查实战 ★

:::概念
OOM 分四类，**每类的排查路径完全不同**：
`Java heap space`（对象太多）/ `Metaspace`（类太多）/ `GC overhead limit exceeded`（GC 白干）/ `unable to create new native thread`（线程数爆了）。
**先分类，再排查**——这一步错了后面全白做。
:::

:::提问
- 线上 OOM 怎么排查？
- Full GC 频繁怎么定位？
- 堆 dump 怎么分析？
- 容器里 OOMKilled 和 Java OOM 有什么区别？
:::

:::答案
**OOM 四类对照表（先分类）**

| 报错 | 含义 | 根因方向 | 处置 |
|---|---|---|---|
| `OOM: Java heap space` | 堆装不下 | 内存泄漏 or 堆太小 or 大对象 | dump + MAT 分析 |
| `OOM: Metaspace` | 类元信息装不下 | 动态生成类多 / ClassLoader 泄漏 | 见第 11 题 |
| `OOM: GC overhead limit exceeded` | 98% 时间在 GC，但回收不到 2% 内存 | **堆太小**（不是泄漏） | 调大堆、减对象分配 |
| `OOM: unable to create new native thread` | 线程数超过系统限制 | 线程泄漏 / 每线程栈太大 | 查线程池、调小 `-Xss`、调 `ulimit` |
| `OOM: Direct buffer memory` | 直接内存耗尽 | NIO/Netty 未释放 | 见第 1 题拓展 |

**完整排查 SOP（七步）**

```
① 先看现象归属
   - 是 Pod 重启（K8s OOMKilled，Exit Code 137）还是应用抛 OOM？
   - 前者=容器级，没有 Java 堆栈；后者=JVM 级，有堆栈

② 确认是不是 GC 问题
   jstat -gcutil <pid> 5000
   看：O（老年代）是否接近 100%？FGC 是否快速上涨？GC 后 O 能否回落？

③ 留现场（最关键的一步，别先重启！）
   jmap -dump:format=b,file=/data/dump/heap.hprof <pid>
   或提前配好 -XX:+HeapDumpOnOutOfMemoryError

④ 看 GC 日志确认时间线
   - GC 后老年代不回落 → 泄漏
   - GC 后回落但很快满 → 不够用

⑤ MAT 分析 dump
   - Leak Suspects（自动报告，先看这个）
   - Dominator Tree（支配树）→ 按 retained size 排序，找最大的
   - 对可疑对象 → Path to GC Roots（exclude weak/soft）→ 找到持有链

⑥ 对照代码定位
   常见元凶：静态 Map/List 无界增长、缓存没设 TTL/上限、
             ThreadLocal 没 remove、监听器没注销、
             大查询结果集一次性加载进内存、循环里 new 大对象

⑦ 处置 + 加防线
   短期：调大内存 / 限流 / 重启
   长期：给缓存加上限（LRU/Caffeine maximumSize）、
         分页查库、加监控告警（堆使用率、FGC 频率）
```

**MAT 三个必看视图**

| 视图 | 看什么 |
|---|---|
| Leak Suspects | 自动给出「疑似泄漏点」和它占的字节数，第一眼就看这个 |
| Dominator Tree | 按 **retained size**（该对象支配的总内存）排序，找真正的内存大户 |
| Histogram | 按类聚合的实例数/占用，快速看「哪个类实例最多」 |

**一个反直觉的点**：`jmap -histo` 里**实例数最多的类往往不是元凶**（大量小对象是正常的）。要看 **retained size**——一个 `HashMap` 实例只有几百字节，但它支配的 Entry 可能有几个 G。
:::

:::拓展
**容器里 OOMKilled vs Java OOM —— 必须分清**

| | Java OOM | 容器 OOMKilled |
|---|---|---|
| 谁杀的 | JVM 自己抛异常 | cgroup / Linux OOM Killer |
| Exit Code | 1 | **137** |
| 有无堆栈 | 有 `OutOfMemoryError` 堆栈 | **没有！日志戛然而止** |
| 触发条件 | 堆/元空间到上限 | 进程 RSS 超过容器 memory limit |
| 排查入口 | GC 日志 + dump | `kubectl describe pod` 看 Last State、看节点 dmesg |

**为什么 `-Xmx` 设成等于 limit 会死**：堆用满了还有元空间、线程栈、直接内存、Code Cache 要占内存 → RSS 超 limit → 被 OOMKilled。所以 `-Xmx` 只能占 limit 的 **70~75%**。

**K8s 里怎么保住 dump**

```yaml
volumes:
  - name: dump-dir
    persistentVolumeClaim:
      claimName: app-dump-pvc      # dump 落 PVC，Pod 重启也不丢
containers:
  - name: app
    resources:
      limits:
        memory: "6Gi"              # 堆设 4.5g（75%）
    env:
      - name: JAVA_OPTS
        value: >-
          -Xms4g -Xmx4g
          -XX:MaxMetaspaceSize=512m
          -XX:+HeapDumpOnOutOfMemoryError
          -XX:HeapDumpPath=/data/dump
```
:::

:::追问
**Q：`GC overhead limit exceeded` 和 `Java heap space` 有什么区别？**
`Java heap space` 是「实在塞不下了」；`GC overhead limit exceeded` 是「还有一点空间，但 GC 花了 98% 时间只回收了不到 2%，判定为无效劳动」而提前抛错。**前者多半是泄漏，后者多半是堆太小**——这个区分能直接决定你是去调参数还是去查代码。

**Q：没有 dump 怎么办？**
靠 GC 日志 + `jstat` 历史数据 + 业务日志时间线反推。但信息量差一个量级，所以 **`-XX:+HeapDumpOnOutOfMemoryError` 是生产必配项**，成本极低收益极高。

**Q：`unable to create new native thread` 怎么排查？**
① `jstack <pid> | grep "java.lang.Thread.State" | wc -l` 看线程总数；② `jstack <pid> | grep -c "pool-"` 看线程池是否无界；③ 常见根因是**线程池用了无界队列 + 无限创建线程**（`Executors.newCachedThreadPool()` 是经典坑）；④ 每线程占 1M 栈（`-Xss`），1000 线程就是 1G 内存。
:::

:::锚点
**rrmcompute OOM 案例（面试完整讲法）**

> 现象：现网 rrmcompute 的 Pod 反复重启，K8s 事件里是 `OOMKilled`，但应用日志里没有 `OutOfMemoryError` 堆栈。
>
> 第一层判断：日志没有 Java 堆栈 → 不是 JVM 自己抛的，是 cgroup 杀的进程。这说明**进程总 RSS 超过了容器 limit**，不只是堆的问题。
>
> 第二层定位：进容器 `jstat -gcutil` 观察，老年代在 GC 后能回落，但很快又涨满 → 不是典型泄漏，是**内存确实不够用**。结合业务日志，确认是高量调优任务并发进入时内存暴涨（大场所任务同时触发计算）。
>
> 第三层处置：内存 5Gi 调到 5.5GiB（requests 保持 3Gi），同时限制任务并发度、检查有无界的缓存/集合增长。
>
> 反思：容器里内存是一个**总和预算**——堆 + 元空间 + 线程栈 + 直接内存 + Code Cache。只调 `-Xmx` 是治不了 OOMKilled 的，必须按 limit 反算各块参数，并且留下 25% 余量。

讲完这段，再补一句**防御性改进**：「后来我们在启动参数里显式配了 `-XX:MaxRAMPercentage=75` 和 `MaxMetaspaceSize` 上限，并给堆使用率加了告警阈值」——从「救火」到「建防线」，这是面试官最想听的成长轨迹。
:::

---

> 📌 **本文档使用方式**：默认折叠答案，先自己回答「面试官会怎么问」，再点开对照。
> 手机上建议开启**自测模式**（答案按钮变灰），逐题过；连续两遍能说全，就可以上考场了。
