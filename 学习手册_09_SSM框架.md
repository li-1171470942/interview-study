# 📘 学习手册 09 · SSM 框架（Spring 系）

> 配套《面试八股复习计划》第 2 节 SSM + PDF 第 62-65 页
> 结构：**概念（常显）→ 面试官会怎么问（常显）→ 答案与原理（点开）→ 拓展 + 追问 + 项目锚点**
> 12 题覆盖 IoC/DI、Bean 生命周期、循环依赖与三级缓存、AOP 与代理选型、事务与 8 种失效、MVC 流程、注解、MyBatis、Boot 自动配置；按「能扛住连续追问」标准编写

---

## 1. Spring / SpringMVC / SpringBoot 三者职责与区别

:::概念
**Spring 是内核**（IoC 容器 + AOP + 事务抽象），**SpringMVC 是 Web 层**（基于 Servlet 的请求分发框架），**SpringBoot 是启动器**（自动配置 + 起步依赖 + 内嵌容器）。
一句话记：**Spring 管对象，MVC 管请求，Boot 管配置**。Boot 里装着 Spring 和 MVC。
:::

:::提问
- Spring、SpringMVC、SpringBoot 三者是什么关系？
- 为什么现在都用 SpringBoot 而不是原生 Spring？
- SpringBoot 到底帮你做了哪几件事？
- SpringBoot 2.x 和 3.x 有什么区别？为什么 3.0 要换 jakarta 包名？
- Spring、SpringBoot、SpringCloud 三者的层次关系？
:::

:::答案
**三者职责拆开看**

| | 定位 | 核心能力 | 关键类/注解 | 依赖关系 |
|---|---|---|---|---|
| **Spring Framework** | 基础容器 | IoC 容器、AOP、事务抽象、JDBC 抽象 | `ApplicationContext`、`@Autowired`、`@Transactional` | 无 |
| **SpringMVC** | Web 层（Spring 的一个模块） | 请求分发、参数绑定、视图渲染 | `DispatcherServlet`、`@RequestMapping` | 依赖 Spring core/web |
| **SpringBoot** | 脚手架/启动器 | 自动配置、起步依赖、内嵌容器、外部化配置 | `@SpringBootApplication` | 依赖 Spring + SpringMVC |

**Spring 的模块组成**（面试能报出模块名会显得不是只会用 Boot）

```
spring-core        核心工具 + 资源加载
spring-beans       BeanDefinition / BeanFactory
spring-context     ApplicationContext、事件、注解驱动  ← 通常说的"Spring 容器"
spring-aop         动态代理 + AspectJ 注解支持
spring-tx          事务抽象（PlatformTransactionManager）
spring-jdbc        JdbcTemplate + DataSource 抽象
spring-web/webmvc   Servlet 集成 + MVC 框架
spring-test        MockMvc、@SpringBootTest
```

**SpringMVC 的位置**：它是 `spring-webmvc` 模块，本质是一个 **Servlet**（`DispatcherServlet extends HttpServlet`）。所以它跑起来需要 Servlet 容器（Tomcat/Jetty/Undertow）。这一点是理解「内嵌 Tomcat」的前置知识。

**SpringBoot 到底做了 4 件事**

1. **起步依赖**：`spring-boot-starter-web` 把 spring-web、spring-webmvc、tomcat、jackson、validation 一次性带进来，版本由 `spring-boot-dependencies`（BOM）统一管，不用自己写 `<version>`
2. **自动配置**：`@EnableAutoConfiguration` + 条件注解，按 classpath 上有什么 jar 决定配什么 Bean（详见第 11 题）
3. **内嵌容器**：把 Tomcat 当普通依赖启动，`java -jar` 就能跑，不再需要装 Tomcat 打 war 包
4. **外部化配置 + 运维端点**：`application.yml` + 环境变量 + `@ConfigurationProperties`；Actuator 提供健康检查、指标

**一个最小可跑的 Boot 应用长什么样**

```java
@SpringBootApplication          // = @SpringBootConfiguration + @EnableAutoConfiguration + @ComponentScan
@RestController
public class DemoApplication {

    public static void main(String[] args) {
        SpringApplication.run(DemoApplication.class, args);
    }

    @GetMapping("/hello")
    public String hello(@RequestParam(defaultValue = "world") String name) {
        return "hello " + name;
    }
}
```

```xml
<!-- 一个 starter 就够了，不需要逐个引 spring-core/spring-web/spring-webmvc -->
<parent>
  <groupId>org.springframework.boot</groupId>
  <artifactId>spring-boot-starter-parent</artifactId>
  <version>2.7.18</version>
</parent>
<dependencies>
  <dependency>
    <groupId>org.springframework.boot</groupId>
    <artifactId>spring-boot-starter-web</artifactId>
  </dependency>
</dependencies>
```

**版本演进（被追问版本差异时的弹药）**

| 维度 | Spring Boot 2.6/2.7 | Spring Boot 3.0+ |
|---|---|---|
| JDK 基线 | JDK 8 | **JDK 17** |
| Spring Framework | 5.3.x | **6.0+** |
| 包名 | `javax.*`（servlet/annotation/persistence） | **`jakarta.*`** |
| 内嵌 Tomcat | 9.0.x（javax.servlet） | **10.1.x（jakarta.servlet）** |
| 自动配置清单位置 | `META-INF/spring.factories`（2.6）/ 2.7 起 `META-INF/spring/...AutoConfiguration.imports` | 只剩 `.imports`，`spring.factories` 的自动配置键移除 |
| GraalVM 原生镜像 | 需实验性 spring-native | **官方 AOT + native 支持** |

**为什么 3.0 要换 jakarta**：Java EE 在 2017 年被 Oracle 交给 Eclipse 基金会并更名 Jakarta EE，但 Oracle 不授权继续使用 `javax.*` 商标 → 所有规范包名必须重命名为 `jakarta.*`。这不是 Spring 的选择，是整个 Java 生态的强制迁移。**面试时能说出「不是 Spring 想改，是商标问题」这一步，就比只会背「3.0 用 JDK17」强。**

**Spring → SpringBoot → SpringCloud 的层次**

| 层 | 解决什么问题 | 代表组件 |
|---|---|---|
| Spring | 单个 JVM 内的对象管理 | IoC、AOP、TX |
| SpringBoot | 让单个应用「开箱即用」 | starter、auto-config、actuator |
| SpringCloud | 多应用之间的协作 | Nacos/Eureka（注册）、Gateway（网关）、Feign（调用）、Sentinel（限流）、Seata（分布式事务） |

**一条判断原则**：Boot 是「单体应用的装修队」，Cloud 是「分布式小区的物业」。前者解决配置和启动，后者解决服务发现、熔断、链路追踪。
:::

:::拓展
**怎么确认一个 Bean 到底是谁注册进来的**（排错必备）

```bash
# 1. 打开条件评估报告，看哪些自动配置生效/被跳过
java -jar app.jar --debug
#   或在 application.yml 里 debug: true
#   输出 CONDITIONS EVALUATION REPORT，分 Positive matches / Negative matches 两段

# 2. 直接看某个自动配置类为什么没生效
#    报告里会写 Exclusions / OnClassCondition 的匹配结果

# 3. Actuator 方式（生产更常用）
curl localhost:8080/actuator/conditions | jq
curl localhost:8080/actuator/beans      | jq '."contexts"'
```

`@ConditionalOnClass` 未生效是最高频的「Bean 没注入」根因：依赖没引进来（或 scope 是 `provided`）、依赖被 `exclude`、类被挪到别的模块。**排查顺序：先看 CONDITIONS EVALUATION REPORT，再怀疑自己的代码**——能省掉半小时瞎猜。

**war 包部署 vs 内嵌容器（SpringBoot 优缺点的那道题）**

| | 传统 war + 外部 Tomcat | Spring Boot 内嵌容器 |
|---|---|---|
| 部署 | 装 Tomcat → 放 war → 重启 Tomcat 影响所有应用 | `java -jar` 独立进程，互不影响 |
| 配置 | server.xml + web.xml 一堆 XML | `application.yml` 一个文件 |
| 扩缩容 | 一台机器一个 Tomcat 多个应用，粒度粗 | 一个应用一个进程，容器化/K8s 友好 |
| 资源占用 | 共享 Tomcat 内存 | 每个进程一个 JVM + 一个 Tomcat，内存偏高 |
| 问题排查 | 日志混在一起 | 日志独立，但自动配置是「黑盒」 |
:::

:::追问
**Q：SpringBoot 是「不用 Spring 了」吗？**
不是。Boot 没有替换任何东西，它是**在 Spring 之上做约定 + 自动装配**。`SpringApplication.run()` 最终调的还是 `ApplicationContext.refresh()`。你说不清这点，就容易被追到「那你讲讲 refresh 做了啥」。

**Q：SpringBoot 的缺点说两条。**
① 自动配置是黑盒：Bean 没生效时第一反应是「为什么」，需要会看 CONDITIONS EVALUATION REPORT；② 依赖升级容易踩兼容：BOM 锁版本，但第三方 starter（如某些中间件 SDK）不跟 Boot 版本同步，会出现 `NoSuchMethodError`；③ 内嵌容器 + 每个服务一个 JVM，内存占用比共享 Tomcat 高，容器里必须配 `-XX:MaxRAMPercentage`（这条正好接得上手册 07 的 JVM 内容）。

**Q：为什么 starter 只需要引一个依赖？**
starter 本身是**空的 jar**，只有 pom 和 `META-INF`，作用就是把一组「经验证能配合工作的依赖」传递进来。`spring-boot-starter-web` 展开后是 spring-webmvc + tomcat + jackson + validation。**这也是「starter 名字就是功能名」的原因**。
:::

:::锚点
你没有 Java 老项目（XML 配置 + 外置 Tomcat war 部署）的经历，所以「为什么用 Boot」这题**别硬编历史**。换个角度讲，把话题拉到你熟的地方：

> 「我之前的微服务是 Node.js 体系（RRM 组四个微服务 rrmcontrol / rrmserver / rrmcompute / yw-aioptimize），部署在 K8s 上，配置全部走 ConfigMap/环境变量，服务靠镜像里的进程直接起来。**SpringBoot 的内嵌容器 + 外部化配置，和这个模型是一一对应的**：`application.yml` ≈ ConfigMap、`java -jar` ≈ 容器 entrypoint、Actuator ≈ K8s 的 readiness/liveness probe。所以我理解 Boot 的价值不是『少写 XML』，而是**让一个 Java 应用变成一个可以被 K8s 编排的标准单元**。」

这个回答把「没用过老 Spring」变成了「理解部署模型」，而且完全基于你真实的 K8s 经验，不编造。
:::

---

## 2. IoC 与 DI（控制反转与依赖注入）

:::概念
**IoC 是一种思想**：对象的创建权和依赖装配权从业务代码反转给容器。**DI 是它的实现手段**：容器通过构造器 / Setter / 字段把依赖「塞」进去。
一句话记：**IoC 回答「谁 new」，DI 回答「怎么塞」**。收益是三件事：解耦（换实现不改调用方）、可测试（注入 Mock）、统一生命周期（单例/销毁回调都能集中管）。
:::

:::提问
- 什么是 IoC 和 DI？它们有什么关系？
- Spring 有哪几种注入方式？官方推荐哪种，为什么？
- `@Autowired` 是怎么找到 Bean 的？同类型有多个怎么办？
- 一个接口有多个实现，怎么按场景选一个？说说你实际怎么用的。
- 单例 Bean 会有线程安全问题吗？
- 容器启动时到底做了什么？Bean 什么时候被创建？
:::

:::答案
**IoC 前后的代码对比（这一段的对比讲出来，比背定义强）**

```java
// 没有 IoC：调用方知道实现类 + 知道怎么构造 → 换实现要改这里
public class OrderService {
    private PayService payService = new AliPayService(new HttpClient(), "https://...");
}

// 有 IoC：调用方只声明"我需要一个能支付的"，谁提供、怎么构造由容器决定
@Service
public class OrderService {
    private final PayService payService;          // 面向接口
    public OrderService(PayService payService) {  // 构造器注入
        this.payService = payService;
    }
}
```

`new` 从代码里消失，代价是**依赖关系变成了运行时的**——所以才有后面那一堆「Bean 找不到/找到多个」的问题。

**四个容易混的概念（高频追问点）**

| 名称 | 是什么 | 典型用法 |
|---|---|---|
| `BeanFactory` | 最底层的 IoC 容器接口，`getBean()` | 懒加载，几乎不直接用 |
| `ApplicationContext` | BeanFactory 的超集，加事件/资源/国际化/AOP | 99% 场景用的容器 |
| `FactoryBean<T>` | **一个能生产 Bean 的 Bean**，`getObject()` 返回的才是目标对象 | MyBatis 的 `MapperFactoryBean`、`SqlSessionFactoryBean` |
| `ObjectFactory<T>` | 延迟获取对象的函数式接口，`getObject()` | 三级缓存里存的就是它（详见第 4 题） |

`BeanFactory` 和 `FactoryBean` 在面试里混着问是常事——**记住区别：`BeanFactory` 是容器本身，`FactoryBean` 是被容器管理的一个「工厂」**。

**三种注入方式对比**

| | 构造器注入 | Setter 注入 | 字段注入（`@Autowired` 直接标在字段上） |
|---|---|---|---|
| 不可变性 | 可以 `final` | 不行 | 不行 |
| 依赖是否可空 | 强依赖、启动即报错 | 可空 | 可空 |
| 循环依赖 | **解决不了**（第 4 题） | 能（三级缓存） | 能（三级缓存） |
| 单元测试 | 直接 `new` | 需要 setter | 必须靠反射/容器 |
| 官方态度 | **推荐**（Spring 4.3 起单构造器不用写 `@Autowired`） | 可选依赖时用 | 不推荐（掩盖依赖过多的问题） |

**Spring 团队推荐构造器注入的三条理由**：① 依赖不可变、不为 null；② 依赖过多时构造函数参数会「长到刺眼」，倒逼你拆类；③ **有循环依赖时启动直接失败**——这是优点不是缺点，避免上线后才暴露设计问题。

**`@Autowired` 的解析链路**（`AutowiredAnnotationBeanPostProcessor` → `DefaultListableBeanFactory.doResolveDependency`）

1. 按**类型**在 BeanFactory 里找候选：`findAutowireCandidates`
2. 候选 > 1 时依次判断：`@Qualifier` 显式指定 → `@Primary` → `@Priority`/`Ordered` 最高优先级 → **字段名/参数名与 BeanName 相同**
3. 全部不匹配 → 抛 `NoUniqueBeanDefinitionException`
4. 没有候选 → `required=true` 抛 `NoSuchBeanDefinitionException`；`required=false` 注入 null

**多实现按场景选一个 —— 这是 DI 最有价值的实战用法**

```java
public interface Notifier { void send(String msg); }

@Component("sms")   @Slf4j class SmsNotifier   implements Notifier { ... }
@Component("email") @Slf4j class EmailNotifier implements Notifier { ... }
@Component("wecom") @Slf4j class WecomNotifier implements Notifier { ... }

@Service
public class AlertService {
    // 注入 Map：key = BeanName，value = 实例。新增渠道只要加一个 @Component，这里代码零改动
    private final Map<String, Notifier> notifierMap;

    public AlertService(Map<String, Notifier> notifierMap) {
        this.notifierMap = notifierMap;
    }

    public void alert(String channel, String msg) {
        Notifier n = notifierMap.get(channel);
        if (n == null) throw new IllegalArgumentException("未知渠道: " + channel);
        n.send(msg);
    }
}
```

```java
// 注入 List：按 @Order / Ordered 排序，用于责任链（风控规则、校验链）
@Service
public class RuleEngine {
    private final List<RiskRule> rules;    // Spring 自动按 @Order 升序注入
    public RuleEngine(List<RiskRule> rules) { this.rules = rules; }
}
```

**这两个用法（`Map<String, Bean>` + `List<Bean>`）是「策略模式 + Spring」的标准答案**，比说「解耦、易测试」这种空话强一个量级。注入 Map 的排序是字母序（BeanName 自然序），注入 List 才看 `@Order`——这个细节非常容易被追问。

**按环境切换实现**

```java
@Component
@ConditionalOnProperty(name = "app.pay.channel", havingValue = "alipay", matchIfMissing = true)
public class AliPayService implements PayService { ... }

@Component
@ConditionalOnProperty(name = "app.pay.channel", havingValue = "wechat")
public class WechatPayService implements PayService { ... }
```

**单例 Bean 的线程安全问题（必被追问）**

Spring 的 Bean 默认 `singleton`，**容器里只有一个实例，会被多线程同时调用**。所以：

| 有状态的东西 | 是否安全 | 正确做法 |
|---|---|---|
| 无状态 Service（只有方法、无成员变量） | 安全 | 默认就是 |
| Service 里存 `private String currentUser` | **不安全** | 改成方法参数传递 |
| 单例里注入原型 Bean 想每次拿新的 | 只能拿到那一个 | 用 `ObjectProvider<T>` 或 `@Lookup` 或 `@Scope(proxyMode)` |
| `SimpleDateFormat` 成员变量 | 不安全 | 换 `DateTimeFormatter`（不可变）或 `ThreadLocal` |

**根因**：`@Autowired` 的字段填充只发生在**容器启动时那一次**（详见第 3 题生命周期），所以单例里存的成员变量天然是「所有请求共享」。

**容器启动时干了什么（`AbstractApplicationContext.refresh()` 12 步，背下来很有用）**

```
1  prepareRefresh            准备上下文、记录启动时间、初始化 PropertySource
2  obtainFreshBeanFactory    创建/获取 DefaultListableBeanFactory，加载 BeanDefinition
3  prepareBeanFactory        注册内置依赖（BeanFactory、ApplicationEventPublisher 等）
4  postProcessBeanFactory    子类扩展（Web 容器在这里注册 request/session 作用域）
5  invokeBeanFactoryPostProcessors   ★ ConfigurationClassPostProcessor 解析 @Configuration/@ComponentScan/@Import/@Bean
6  registerBeanPostProcessors ★ 注册 BeanPostProcessor（AOP、@Autowired、@PostConstruct 都靠它）
7  initMessageSource         国际化
8  initApplicationEventMulticaster  事件广播器
9  onRefresh                 ★ ServletWebServerApplicationContext 在这里启动内嵌 Tomcat
10 registerListeners         注册事件监听器
11 finishBeanFactoryInitialization  ★ preInstantiateSingletons()：实例化所有非懒加载单例 Bean
12 finishRefresh             发布 ContextRefreshedEvent，清缓存
```

**第 5 步是「BeanDefinition 阶段」，第 11 步是「Bean 实例化阶段」**——这个分界点是理解「`@ConditionalOnMissingBean` 为什么在注册期就能判断」的关键（见第 11 题）。
:::

:::拓展
**`@Lazy` 与延迟初始化**

- `@Lazy` 标在 Bean 上：该 Bean 第一次被 `getBean` 时才创建
- `@Lazy` 标在注入点上：注入一个**代理**，真正调用方法时才去容器取——这是打断循环依赖的标准手段
- `spring.main.lazy-initialization=true`（Boot 2.2+）：全局延迟初始化，**启动快很多，但问题会推迟到第一次请求才暴露**——开发期可以用，生产慎用

**为什么 Bean 默认单例而不是每次 new**

对象创建在 Java 里是「分配内存 + 执行构造器 + 初始化依赖」，Spring 启动一次创建几百个 Bean，每次请求再创建一遍是纯浪费。单例 + 无状态是 Web 应用的主流模型；需要「每次新对象」的场景是少数的（有状态的计算上下文），那种才用 `prototype`。

**`prototype` 的两个坑**：① 容器不管理销毁（`@PreDestroy`/`DisposableBean` 不生效，需要调用方自己释放）；② 单例里注入原型，只会拿到那一个实例（要在容器里注册 `ObjectProvider` 或者用 `@Lookup` 才算每次新）。
:::

:::追问
**Q：`ApplicationContext` 和 `BeanFactory` 的区别？**
`BeanFactory` 是顶层接口，只提供最基本的容器能力，**默认懒加载**（getBean 才创建）；`ApplicationContext` 继承并扩展了它，加了事件发布、资源加载、国际化、AOP 集成，并且**默认在启动时预实例化所有单例**。实际项目里用的一律是 `ApplicationContext`，说得出这个「预实例化」的区别就够区分了。

**Q：`@Autowired` 标在字段上，Spring 是怎么把值塞进去的？**
不靠反射改字段那么简单——它走的是 `AutowiredAnnotationBeanPostProcessor` 的 `postProcessProperties`，拿到 `InjectionMetadata` 后用 `ReflectionUtils.makeAccessible(field)` + `field.set(bean, value)`。**关键点：这个时机在 Bean 实例化之后、初始化之前**（生命周期第 2 步），所以 `@PostConstruct` 里能安全使用注入的字段。

**Q：一个接口有 3 个实现，全部注入了 Map，怎么排除一个不要的？**
`Map` 注入会包含所有候选。要排除，可以用 `@Qualifier` 分组注解标在实现类上，然后注入 `Map<String, Notifier>` 时字段上再标同样的 `@Qualifier` —— Spring 会把 `@Qualifier` 当作**筛选器**（此时不再当作选择器用）。这是很多人不知道的用法（`@Qualifier` 作用在集合注入时是「过滤条件」）。

**Q：`@Autowired(required=false)` 和 `ObjectProvider` 哪个好？**
`ObjectProvider` 更好：它延迟到真正调用时才解析依赖，`getIfAvailable()` / `getIfUnique()` 语义清晰，而且能解决「单例注入原型」的问题，也不受循环依赖影响。唯一要注意的是：`getObject()` 在 Bean 未就绪时会抛，包一层 try 或先 `getIfAvailable()`。
:::

:::锚点
你现在的项目里没有 Java Spring 代码，所以这道题的锚点要**用「IoC 的思想你在 Node 里见过」来过渡**，然后给出一条面试策略：

> 「我们 RRM 的几个微服务是 Node.js 写的，模块之间用的是显式 `require` + 工厂函数，本质是**手工的依赖装配**——想换实现就得改调用点。Spring 的 IoC/DI 把这一步收到容器里，好处在**多实现切换**上特别明显：我们做告警通道时是 if/else 或者配置文件里读 channel 再 new 对应对象，Java 里一个 `Map<String, Notifier>` 注入就解决了，新增渠道不改调用方代码。」

**为什么这样讲是安全的**：你说的是「我们用的是显式 require + 工厂函数」这个架构事实（Node 项目的通用形态），表达的是你的理解，不涉及编造 Java 项目经历。面试官关心的是你是不是理解 IoC 的**价值边界**，而不是你写了多少行 Java。
:::

---

## 3. Bean 生命周期（7 步）

:::概念
**实例化 → 属性填充 → Aware 回调 → BeanPostProcessor 前置 → 初始化（三连）→ BeanPostProcessor 后置（AOP 在这里生成代理）→ 销毁**。
记忆钩子：**新（实例化）→ 填（依赖）→ 认（Aware）→ 前（前后置）→ 生（初始化三连）→ 后 → 死**。
最高频追问点：**AOP 代理是在第 6 步 `postProcessAfterInitialization` 生成的**，所以你注入到别处的其实是代理对象。
:::

:::提问
- 讲一下 Spring Bean 的生命周期？
- 生命周期里有哪几个扩展点？分别在什么时候被调用？
- `@PostConstruct`、`InitializingBean.afterPropertiesSet()`、`init-method` 三者的执行顺序？
- `BeanPostProcessor` 和 `BeanFactoryPostProcessor` 有什么区别？
- 销毁回调什么时候执行？prototype 的 Bean 会被销毁吗？
- `@Autowired` 注入发生在生命周期的哪一步？
:::

:::答案
**7 步全表（带真实类名和方法名，撑住追问）**

| 步骤 | 做什么 | 关键类 / 方法 | 触发的东西 |
|---|---|---|---|
| 1 实例化 | 调构造器创建对象（此时字段全是默认值，依赖还没注入） | `AbstractAutowireCapableBeanFactory.createBeanInstance()` → `determineConstructorsFromBeanPostProcessors()` | `SmartInstantiationAwareBeanPostProcessor.determineCandidateConstructors`（`@Autowired` 构造器推断）、`instantiateUsingFactoryMethod` |
| 2 属性填充 | 注入依赖、填配置值 | `populateBean()` → `InstantiationAwareBeanPostProcessor.postProcessProperties()` | `@Autowired`/`@Value`/`@Resource`/`@Inject` |
| 3 Aware 回调 | 把容器自身的能力「告诉」Bean | `invokeAwareMethods()` + `ApplicationContextAwareProcessor` | `BeanNameAware`、`BeanClassLoaderAware`、`BeanFactoryAware`、`ApplicationContextAware`、`EnvironmentAware` |
| 4 前置处理 | 初始化**前**的拦截 | `applyBeanPostProcessorsBeforeInitialization()` | `BeanPostProcessor.postProcessBeforeInitialization` |
| 5 初始化三连 | 执行初始化逻辑 | `invokeInitMethods()` | `@PostConstruct` → `InitializingBean.afterPropertiesSet()` → `init-method` |
| 6 后置处理 | 初始化**后**的拦截，**AOP 代理在这里生成** | `applyBeanPostProcessorsAfterInitialization()` | `AbstractAutoProxyCreator.postProcessAfterInitialization` → `wrapIfNecessary()` |
| 7 销毁 | 容器关闭时执行 | `DisposableBeanAdapter.destroy()` | `@PreDestroy` → `DisposableBean.destroy()` → `destroy-method` |

**初始化三连的严格顺序（必背）**

```
实例化（构造器）
   ↓
属性填充（@Autowired / @Value）
   ↓
Aware 接口回调（BeanNameAware / ApplicationContextAware ...）
   ↓
BeanPostProcessor.postProcessBeforeInitialization   ← @PostConstruct 在这里被触发
   ↓
InitializingBean.afterPropertiesSet()
   ↓
自定义 init-method（@Bean(initMethod="init")）
   ↓
BeanPostProcessor.postProcessAfterInitialization    ← AOP 代理在这里生成
   ↓
Bean 可以用 / 放入 singletonObjects 一级缓存
```

**`@PostConstruct` 属于哪一步是个考点**：它不是在「初始化」那一步执行的，而是由 `InitDestroyAnnotationBeanPostProcessor`（`CommonAnnotationBeanPostProcessor` 的父类）在 **`postProcessBeforeInitialization`** 阶段触发。所以它**严格早于** `afterPropertiesSet()`。

**可运行的验证代码（本地跑一遍，顺序就刻在脑子里了）**

```java
@Component
public class LifeCycleDemo implements BeanNameAware, ApplicationContextAware,
                                       InitializingBean, DisposableBean {

    public LifeCycleDemo() {
        System.out.println("1. 构造器（实例化）");
    }

    @Autowired
    private SomeDependency dep;

    @Override
    public void setBeanName(String name) {
        System.out.println("3. BeanNameAware = " + name);
    }

    @Override
    public void setApplicationContext(ApplicationContext ctx) {
        System.out.println("3. ApplicationContextAware");
    }

    @PostConstruct
    public void postConstruct() { System.out.println("4. @PostConstruct"); }

    @Override
    public void afterPropertiesSet() { System.out.println("5. afterPropertiesSet"); }

    public void customInit() { System.out.println("5. init-method"); }

    @PreDestroy
    public void preDestroy() { System.out.println("7. @PreDestroy"); }

    @Override
    public void destroy() { System.out.println("7. DisposableBean.destroy"); }
}
```

```java
// 注册一个 BeanPostProcessor 观察前后置回调
@Component
public class TracingBpp implements BeanPostProcessor {
    @Override
    public Object postProcessBeforeInitialization(Object bean, String beanName) {
        if (bean instanceof LifeCycleDemo) System.out.println("-- before init: " + beanName);
        return bean;
    }
    @Override
    public Object postProcessAfterInitialization(Object bean, String beanName) {
        if (bean instanceof LifeCycleDemo) System.out.println("-- after init: " + beanName);
        return bean;
    }
}
```

实际输出顺序：`1 构造器 → 2 属性填充（无打印） → 3 BeanNameAware → 3 ApplicationContextAware → -- before init → 4 @PostConstruct → 5 afterPropertiesSet → 5 init-method → -- after init → ... → 7 @PreDestroy → 7 DisposableBean.destroy`。

**`BeanPostProcessor` vs `BeanFactoryPostProcessor`（两个名字像，用途完全不同）**

| | `BeanFactoryPostProcessor` | `BeanPostProcessor` |
|---|---|---|
| 作用对象 | **BeanDefinition**（还没变成对象） | **Bean 实例**（已经 new 出来） |
| 时机 | `refresh()` 第 5 步，实例化之前 | `refresh()` 第 6 步注册，每个 Bean 创建时回调 |
| 典型实现 | `ConfigurationClassPostProcessor`、`PropertySourcesPlaceholderConfigurer` | `AutowiredAnnotationBeanPostProcessor`、`AbstractAutoProxyCreator`、`CommonAnnotationBeanPostProcessor` |
| 能做什么 | 改 Bean 定义、注册新定义、改占位符 | 包装/替换返回的实例（**AOP 就是替换成代理**） |

**记住这条**：`BeanFactoryPostProcessor` 改的是「图纸」，`BeanPostProcessor` 改的是「成品」。

**AOP 代理在第 6 步生成，这带来三个可观察的结论**

1. 你注入到别的 Bean 里的，**是代理对象，不是原始对象**——`@Autowired FooService foo; foo.getClass()` 打出来是 `FooService$$EnhancerBySpringCGLIB$$abc123`
2. 因为代理在第 6 步才产生，第 1~5 步里 `this` 还是原始对象 → **`@PostConstruct` 里调用自身的 `@Transactional` 方法不会走事务**（同理，自调用事务失效）
3. 如果一个 Bean 被提前暴露用于解决循环依赖（第 4 题），它的代理会在「属性填充阶段」就被创建，`AbstractAutoProxyCreator` 用 `earlyProxyReferences` 做去重，保证不重复生成

**销毁相关**

| 场景 | 行为 |
|---|---|
| 单例 Bean 容器关闭 | 依次调 `@PreDestroy` → `DisposableBean.destroy()` → `destroy-method` |
| `@Bean(destroyMethod = "")` | 显式关掉销毁方法（防止容器调用第三方库的同名方法，如 `SqlSessionFactory` 的 `close`） |
| **prototype Bean** | **容器不管销毁**，`@PreDestroy` 不生效，需要调用方自己释放 |
| `@Bean` 推断 | `@Bean` 默认自动推断 `close()`/`shutdown()` 作为销毁方法（`DisposableBeanAdapter.inferDestroyMethodIfNecessary`） |
:::

:::拓展
**生命周期里还有三个少被提及但很有用的扩展点**

| 扩展点 | 时机 | 典型用途 |
|---|---|---|
| `SmartInitializingSingleton.afterSingletonsInstantiated()` | 所有单例都实例化完成后（`preInstantiateSingletons` 末尾） | 启动后做一次性的缓存预热、注册定时任务 |
| `ApplicationListener<ContextRefreshedEvent>` | `refresh()` 第 12 步 | 启动后加载字典/全量刷新缓存 |
| `SmartLifecycle.start()` | `finishRefresh` → `DefaultLifecycleProcessor.startBeans` | 需要控制启动顺序的资源（MQ 消费者、Netty 服务）——**`@Scheduled` 的定时任务也是在这一步才开始可能触发** |

**为什么生产环境喜欢用 `SmartLifecycle` 而不是 `@PostConstruct` 做「启动时报文拉取」**：`@PostConstruct` 里依赖的 Bean 可能还没初始化完（虽然依赖链上的已就绪），而 `SmartLifecycle.start()` 在所有单例就绪后执行，还支持 `Phase` 控制先后顺序（数值越大越晚启动、越早停止）。

**Boot 2.2+ 的全局延迟初始化**

```yaml
spring:
  main:
    lazy-initialization: true   # 启动时只创建被依赖链拉起来的 Bean
```

启动时间能明显缩短，但**副作用是「Bean 循环依赖 / 配置错误」推迟到第一次请求才炸**，而且会破坏 `@PostConstruct` 里「启动即预热」的预期。开发期提速可以用，生产建议只对确知无关的模块用 `@Lazy` 局部延迟。
:::

:::追问
**Q：`@PostConstruct` 和 `afterPropertiesSet()` 有什么区别？**
功能上重叠，都在属性填充后执行。区别：`@PostConstruct` 是 JSR-250 标准注解（不绑定 Spring，写在 POJO 上也能被任何支持该规范的容器调用），`afterPropertiesSet()` 是 Spring 的 `InitializingBean` 接口（代码和 Spring 绑死，但能编译期检查）。**执行顺序是 `@PostConstruct` 先**。生产代码优先 `@PostConstruct`。

**Q：`:BeanPostProcessor` 为什么能「处理所有 Bean」？**
因为 `AbstractBeanFactory` 在 `initializeBean()` 里对**每个** Bean 都调用了 `applyBeanPostProcessorsBeforeInitialization` / `AfterInitialization`，遍历容器里所有 `BeanPostProcessor`。所以它是**全局钩子**，代价是每个 Bean 创建都要走一遍这个列表——**这也是 BeanPostProcessor 数量不能失控的原因**（每个都过一遍，启动时间上升）。

**Q：`@Autowired` 的字段在构造器里能用吗？**
不能。构造器在第 1 步，属性填充在第 2 步——构造器执行时字段还是 null。**这是「为什么推荐构造器注入」的另一个理由**：构造器注入的依赖在构造完成时就已就绪，不存在这个时序问题。

**Q：动态给一个 Bean 加功能，改哪一步？**
不改 Bean 本身，用 `BeanPostProcessor.postProcessAfterInitialization` 返回一个包装/代理对象（`AbstractAutoProxyCreator` 就是这么干 AOP 的）。**这才是 Spring 扩展的标准姿势**——不要改源码、不要加继承。
:::

:::锚点
你没有 Spring 项目经验，但这道题有一个**极强的类比锚点**：K8s 的 Pod 生命周期。

> 「Bean 生命周期这套『实例化 → 注入依赖 → 回调 → 初始化 → 用 → 销毁』，和我熟的 K8s Pod 生命周期是同构的：容器启动 → 初始化配置注入（ConfigMap/Secret 挂载）→ `postStart` 钩子 → 业务进程起来 → `readinessProbe` 通过才开始接流量 → 优雅停机时先 `preStop`、再收 SIGTERM。所以「**在哪个阶段做什么**」这个思维方式我是有的，Bean 生命周期只是把它换到了 JVM 进程内部。」
>
> 「具体到排错经验：我做 rrmcontrol 那个 `write after end` 反复重启的问题，本质就是**容器生命周期与连接生命周期没对齐**——连接已经关了但还有代码在写。放到 Spring 里，这就是『销毁阶段没释放资源』的同类问题：`@PreDestroy` 没写、`@Bean(destroyMethod="")` 把关闭逻辑关掉了、或者被包装的第三方客户端没有 `close()`。」

**为什么这个说法成立**：你的 `write after end` 故障是真实事实（国际环境 rrmcontrol pod 反复重启，硬编码功率上限场景下连接生命周期管理缺陷），把它映射到「生命周期管理」这一类问题上，是**能力迁移**而不是编造经历。
:::

---

## 4. 循环依赖与三级缓存 ★

:::概念
三级缓存是三个 Map：**一级 `singletonObjects`**（成品，可对外使用）、**二级 `earlySingletonObjects`**（半成品早期引用）、**三级 `singletonFactories`**（存 `ObjectFactory`，用来决定「要不要提前造 AOP 代理」）。
一句话记：**一级放成品，二级放半成品，三级放能造半成品的工厂**。
最核心的一句结论：**用三级而不是两级，是为了把「是否提前生成 AOP 代理」这个决策，从「实例化后立即执行」推迟到「真的有人来取早期引用时」才执行。**
:::

:::提问
- 什么是循环依赖？Spring 是怎么解决的？
- 为什么要三级缓存？两级不行吗？
- 三级缓存里分别存的是什么？
- 构造器注入的循环依赖为什么解决不了？
- prototype 的循环依赖能解决吗？
- Spring Boot 2.6 之后为什么默认禁止循环依赖了？
- 线上遇到循环依赖报错，你会怎么处理，为什么推荐重构而不是加 `@Lazy`？
:::

:::答案
**三个缓存的真实字段（都在 `DefaultSingletonBeanRegistry` 里，硬背下来）**

```java
// 一级：完整的成品。只有这个缓存里的 Bean 才能被 getBean 直接返回
private final Map<String, Object> singletonObjects = new ConcurrentHashMap<>(256);

// 二级：提前暴露的"半成品"引用（未完成属性填充/初始化），已确定其最终对外形态（可能是代理）
private final Map<String, Object> earlySingletonObjects = new ConcurrentHashMap<>(16);

// 三级：存 Lambda 工厂，调用 getObject() 时才知道要不要返回代理
private final Map<String, ObjectFactory<?>> singletonFactories = new HashMap<>(16);
```

**A 依赖 B、B 依赖 A 的完整流程（逐步编号，面试按这个顺序讲）**

```
① getSingleton("a", true)
   → 查一级：无 → 查二级：无 → 查三级：无
   → 标记 a 正在创建（singletonsCurrentlyInCreation.add("a")）
   → 进入 createBean("a") / doCreateBean("a")

② 实例化 a：createBeanInstance() → new A()
   （此刻 a 是个空壳，字段全 null）

③ 【关键】提前暴露：addSingletonFactory("a", () -> getEarlyBeanReference("a", mbd, a))
   → 往三级缓存 singletonFactories.put("a", lambda)
   → 注意：这里"先看看是否需要提前暴露"的开关是 earlySingletonExposure
     （条件是：单例 + allowCircularReferences + 正在创建中）

④ 属性填充 a：populateBean() → 发现要注入 b
   → getBean("b")  → 走 ①~③ 同样流程，b 也进了三级缓存

⑤ b 属性填充时发现要注入 a
   → getSingleton("a", true)
   → 一级无、二级无 → 三级命中！执行 ObjectFactory.getObject()
   → 也就是调用 getEarlyBeanReference("a", ...)
        ├─ 若 a 需要 AOP：此时调用 wrapIfNecessary() 提前生成代理对象
        └─ 若 a 不需要：直接返回原始对象 a
   → 把结果放进二级缓存 earlySingletonObjects.put("a", 结果)
   → 从三级缓存删除（singletonFactories.remove("a")）
   → b 拿到（可能是代理的）a，属性填充完成

⑥ b 继续走初始化三连 + 后置处理 → 完成后放入一级缓存
   → addSingleton("b", b)：一级 put，同时清掉二级/三级里 b 的残留

⑦ 回到 a：b 注入成功 → a 继续初始化三连 + 后置处理
   → 后置处理阶段 AbstractAutoProxyCreator.postProcessAfterInitialization 被调用
   → 内部判断：earlyProxyReferences.remove(cacheKey) != bean 才创建新代理
     （因为第 ⑤ 步已经提前创建过，这里就去重了 —— 保证不会生成两个不同代理）
   → addSingleton("a", a)：放入一级缓存，清理二级/三级
```

**"为什么要三级而不是两级" —— 这是这道题真正的分水岭**

假设只保留「一级 + 二级」，二级缓存要存早期引用，那么**必须在实例化之后、属性填充之前就把对象放进二级缓存**。此时会产生两个问题：

| 问题 | 展开 |
|---|---|
| **代理决策时机被迫提前** | 往二级缓存里放什么？放原始对象，则别人拿到的不是代理（AOP 失效）；放代理对象，则**必须在实例化后立刻判断这个 Bean 是否需要被代理**——而正常流程里这个判断是在 `postProcessAfterInitialization`（第 6 步）做的。提前做意味着：所有 Bean 在实例化后立即都要跑一遍「切点匹配 + 是否需要代理」的逻辑，而且此时 Bean 还没有完成属性填充，`@Autowired` 进来的字段都是 null，切点表达式里的条件判断可能不准 |
| **提前生成的代理无法撤销** | 一旦在二级缓存里放了代理并给了别人，这个引用就散出去了。如果 A 在后续初始化过程中因为某个条件**不需要**代理了（或需要不同的代理），也无法挽回 —— 拿到的对象和最终对象不是同一个，破坏单例语义 |

三级缓存用「存工厂而不是存对象」把这一步变成**懒执行**：`ObjectFactory.getObject()` 只在**真的有人来取早期引用时**才被调用一次（调用后立刻升到二级缓存并从三级移除，保证只执行一次）。

> 一句话总结：**三级缓存不是多存一层，而是把「要不要提前造代理」的决策从「必答题」变成「按需答题」。** 大多数 Bean 根本不会被循环依赖引用，它们的代理就老老实实在第 6 步正常生成，一条路径都不多走。

**二级缓存存在的意义（也会被追问）**：如果没有二级缓存，每次有人来取早期引用都要重新执行 `ObjectFactory.getObject()` —— 对需要 AOP 的 Bean 就是**重复生成代理类**（每次都是新对象，单例语义直接崩）。二级缓存保证「提前暴露的引用只被计算和生产一次」。

**四种循环依赖对照表**

| 注入方式 | 能否解决 | 为什么 |
|---|---|---|
| **Setter / 字段注入** | ✅ 能 | 实例化后可以先暴露引用，等属性填充时再注入对方 |
| **构造器注入** | ❌ 不能 | 三级缓存放的是「实例化**完成后**的 ObjectFactory」，而构造器注入要**在实例化时**就拿到对方 → 鸡生蛋问题，无法提前暴露 |
| **prototype 循环依赖** | ❌ 不能 | 原型 Bean 不进三级缓存（没有 `earlySingletonExposure`），直接抛 `BeanCurrentlyInCreationException` |
| **`@Async` / `@Transactional` 的代理** | ⚠️ 能但要小心 | 代理会被提前创建，靠 `earlyProxyReferences` 去重；但 `@Async` 的代理由 `AsyncAnnotationBeanPostProcessor` 生成、`@Transactional` 的由 `AbstractAutoProxyCreator` 生成，**两者都可能被提前生成的代理"抢跑"**，出现「注入进去的代理和最终的单例不是同一个」的告警 |

**构造器注入循环依赖的报错长这样（记下来）**

```
The dependencies of some of the beans in the application context form a cycle:

┌─────┐
|  a defined in file [.../A.class]
↑     ↓
|  b defined in file [.../B.class]
└─────┘

Action:
Relying upon circular references is discouraged and they are prohibited by default.
Update your application to remove the dependency cycle between beans.
As a last resort, it may be possible to break the cycle automatically by setting
spring.main.allow-circular-references=true.
```

**Spring Boot 2.6+ 默认禁止循环依赖的原因**：Spring 团队认为循环依赖几乎总是**设计问题的信号**（两个类职责纠缠），而三级缓存的这套机制复杂且容易在代理场景下出诡异问题（拿到不完整的对象、代理不一致）。所以在 2.6 把 `spring.main.allow-circular-references` 的默认值改成 `false`，**逼你在启动阶段就把设计问题暴露出来**。

**四种解法（按推荐度排序）**

```java
// 方案 1（最推荐）：重构，抽出第三个 Bean 或引入事件/接口解耦
//   A 和 B 都依赖 C，C 不依赖它们 → 循环消失

// 方案 2：Setter / 字段注入（把循环依赖变成"能解决"的那一类）
@Service
public class A {
    @Autowired private B b;      // 字段注入 → 走三级缓存
}

// 方案 3：@Lazy 打断（注入点加 @Lazy，注入的是个延迟代理）
@Service
public class A {
    private final B b;
    public A(@Lazy B b) { this.b = b; }
}

// 方案 4：ApplicationContextAware / ObjectProvider 手动延迟获取
@Service
public class A {
    private final ObjectProvider<B> bProvider;
    public A(ObjectProvider<B> bProvider) { this.bProvider = bProvider; }
    public void doSomething() { bProvider.getObject().x(); }
}
```

```yaml
# 只有在"必须立刻上线、又来不及重构"时才开（属于技术债，要建 issue 跟踪）
spring:
  main:
    allow-circular-references: true
```

**线上排查步骤（编号照做）**

1. 看启动异常栈：`BeanCurrentlyInCreationException` 后面会跟着 `Currently in creation:` 和完整的依赖环，**环上所有 BeanName 都在里面**，直接照着列出来
2. 如果环很大（5 个以上）→ 基本可以确定是「一个 God Service 被到处注入」，先做职责拆分
3. 如果环只有 2 个 → 看是不是「双向查询」场景（A 要查 B 的状态，B 要回调 A 的通知）→ 通常应该抽一个 `XxxFacade` 或者改成事件驱动（`ApplicationEventPublisher.publishEvent`）
4. 确认是构造器注入导致的 → 优先改成「其中一边用 `@Lazy`」而不是全局开开关
5. **不要**用 `@Autowired` 字段注入去"绕过"——那只是把编译期的错误藏到运行期
:::

:::拓展
**`getEarlyBeanReference` 的真实实现（这是三级缓存的灵魂方法）**

```java
// AbstractAutowireCapableBeanFactory#getEarlyBeanReference
protected Object getEarlyBeanReference(String beanName, RootBeanDefinition mbd, Object bean) {
    Object exposedObject = bean;
    if (!mbd.isSynthetic() && hasInstantiationAwareBeanPostProcessors()) {
        for (SmartInstantiationAwareBeanPostProcessor bp : getBeanPostProcessorCache().smartInstantiationAware) {
            // 关键：只有实现了 SmartInstantiationAwareBeanPostProcessor 的才能提前创建代理
            exposedObject = bp.getEarlyBeanReference(exposedObject, beanName);
        }
    }
    return exposedObject;
}
```

```java
// AbstractAutoProxyCreator：这里就是"提前生成 AOP 代理"的实现
@Override
public Object getEarlyBeanReference(Object bean, String beanName) {
    Object cacheKey = getCacheKey(bean.getClass(), beanName);
    this.earlyProxyReferences.put(cacheKey, bean);   // 打标记：这个 Bean 已经提前建过代理了
    return wrapIfNecessary(bean, beanName, cacheKey); // 真的去建代理
}

// 而正常的后置处理会检查这个标记，避免重复创建代理
@Override
public Object postProcessAfterInitialization(@Nullable Object bean, String beanName) {
    if (bean != null) {
        Object cacheKey = getCacheKey(bean.getClass(), beanName);
        if (this.earlyProxyReferences.remove(cacheKey) != bean) {  // 没提前建过 → 才建
            return wrapIfNecessary(bean, beanName, cacheKey);
        }
    }
    return bean;
}
```

**这段代码能解释一个经典的诡异现象**：循环依赖 + AOP 的 Bean，注入到环上其他 Bean 里的是**提前创建的代理**，而如果这个 Bean 后续被别的 `BeanPostProcessor` 又包装了一层，最终放进一级缓存的对象和早期暴露出去的对象就**不是同一个**。Spring 会在检测到这种情况时打日志：

```
Bean 'xxx' is not eligible for getting processed by all BeanPostProcessors
(e.g. not eligible for auto-proxying)
```

看到这条日志要警觉——它通常意味着有 Bean 被提前实例化了（不只是循环依赖，`@Bean` 方法里 `getBean()` 也会导致），会导致**该 Bean 上少了一些后置处理器的加工**。

**为什么原型 Bean 的循环依赖不能解决**

原型 Bean 每次 `getBean` 都创建新对象，容器不缓存实例，也就没有「提前暴露引用」的载体。Spring 在 `beforeSingletonCreation` 里对原型直接抛 `BeanCurrentlyInCreationException`。**注意：不是"不支持提前暴露"，而是原型 Bean 的生命周期语义和"提前暴露"根本不兼容**。

**一个反直觉的结论**：不要「为了能用三级缓存」而刻意把构造器注入改成字段注入。Spring 团队的意见是——**你现在遇到的循环依赖报错，是它在帮你发现设计问题**。三级缓存是一套「让老代码能跑起来」的兼容机制，不是一个应该被依赖的特性。
:::

:::追问
**Q：一级缓存和二级缓存的区别是什么？**
一级放的是**完整的、可以直接对外使用的单例**（走完生命周期第 6 步）；二级放的是**提前暴露的早期引用**（可能还没属性填充完、可能是代理）。二级只服务于循环依赖窗口期，一旦 Bean 完成初始化就进一级、二级里那份被清掉。所以「`getBean` 第一次查一级缓存」是正常的，二级缓存几乎是循环依赖专用的。

**Q：为什么要把「单例」和「提前暴露」绑定？**
因为只有单例才需要「同一个实例被多处共享」，提前暴露才有意义。原型 Bean 每次都是新对象，没有「同一个」的概念，暴露出去也没用。同理 `@Scope("request")` 的 Bean 也不会走这套机制。

**Q：循环依赖时"半成品"对象可能有几种状态？**
两种。① **原始对象**（不需要 AOP）：这类 Bean 提前暴露的就是它自己，后续初始化只是往它字段里填值 + 调初始化方法，最终进一级缓存的就是同一个对象；② **提前创建的代理**（需要 AOP）：暴露出去的是代理，代理内部 `target` 指向那个还没填充完的原始对象——所以**如果此时有人调用代理的方法，会读到还没注入的字段（NPE）**。这是循环依赖 + AOP 的经典坑，也是「不要依赖循环依赖」的最硬理由。

**Q：线上想确认某个 Bean 走了循环依赖路径，怎么看？**
开 debug 日志看 `DefaultSingletonBeanRegistry`，或者在启动参数加 `-Dspring.main.allow-circular-references=true` 临时放开，观察日志里是否出现 `Bean 'x' is not eligible for getting processed by all BeanPostProcessors`。更直接的办法是打一个 `BeanPostProcessor` 打印 `postProcessAfterInitialization` 的 beanName 和 `System.identityHashCode(bean)`，对比注入点的 hash，看是不是同一个对象。
:::

:::锚点
**这道题你完全没有 Java 实战，所以锚点的写法是「给一段不心虚的应答策略」——严禁编造。**

> 面试官如果问「你们项目里有循环依赖吗」，标准答法是：
>
> 「我目前主要在 Node.js 微服务里做开发，Java 侧还在补课，所以循环依赖我**没有在生产 Java 项目里处理过**。但从原理上我理解它是『两个对象在初始化时互相需要对方』的时序问题——Spring 的解法是**先暴露一个能拿到对象引用的"占位"**（三级缓存存的是工厂，不是成品），把时序问题转成了延迟解析。这个思路我在别的地方见过：**Node 里也偶发 `require` 循环引用导致拿到 `undefined` 的问题，解决方案同样是延迟到真正使用时再取（惰性 require / 运行时取属性），而不是在模块加载期就互相引用。** 所以我知道这类问题的统一解法是**打断时序依赖，而不是硬解**。」

**再加一层能力展示**（这部分是真的，可以说）：

> 「我们组现在用 CodeBuddy 这类 AI agent 改代码、我负责 review 后提交，我自己在推一个集成 Sonar 做静态代码分析的 AI 编程助手项目。**循环依赖这种问题恰恰是静态分析很容易抓的**——不用等启动报错。所以我的思路是：**能用工具在提交前拦住的问题，就不要留到运行时。**」

这段话零编造，同时把「我不熟」变成了「我知道怎么用工程手段防住」。**面试官对「不知道但知道怎么防」的人，评价远高于硬编经历的人。**
:::

---

## 5. AOP 原理与代理选型（JDK vs CGLIB）★

:::概念
Spring AOP = **运行期动态代理 + 切点匹配 + 通知链**。织入时机在 Bean 生命周期第 6 步（`postProcessAfterInitialization`）。
代理选型规则：**`proxyTargetClass=true` 或有接口就用 CGLIB/JDK**——更准确的说法是：**有接口 → JDK 动态代理；无接口 → CGLIB；但 Spring Boot 2.0 起默认 `proxy-target-class=true`，也就是一律用 CGLIB**。
:::

:::提问
- AOP 的实现原理是什么？
- JDK 动态代理和 CGLIB 有什么区别？Spring 怎么选？
- 为什么 Spring Boot 2.0 之后默认都改成 CGLIB 了？
- CGLIB 代理的类有什么限制？`final` 方法能代理吗？
- `proxyTargetClass` 这个参数是干什么的？
- 为什么 `@Transactional` 加在 private 方法上不生效？
- JDK 9 之后动态代理有什么变化？
:::

:::答案
**先分清两种「AOP」（这是第一个坑）**

| | Spring AOP | AspectJ |
|---|---|---|
| 织入时机 | **运行期**，动态代理 | 编译期（ajc）/ 编译后 / 类加载期（LTW） |
| 实现方式 | JDK Proxy / CGLIB | 直接改字节码，插入到目标方法内部 |
| 能拦截什么 | **只能拦 Spring Bean 的 public 方法** | 方法内任意位置、字段访问、构造器、静态方法 |
| 性能 | 有代理调用开销 | 无（编译期织入，就是普通代码） |
| 依赖 | spring-aop | aspectjweaver（Spring 只是**借用它的切点表达式解析器**） |

**关键认知**：`@Aspect`、`@Pointcut`、`execution(...)` 这套语法是 AspectJ 的，但 Spring AOP **没有**用 AspectJ 的织入器，只是**复用了它的注解和表达式解析**（`AspectJExpressionPointcut` 内部依赖 `org.aspectj.weaver` 做切点匹配）。所以「Spring AOP 是不是 AspectJ」这个问题，正确答案是：**注解是，织入不是**。

**JDK 动态代理 vs CGLIB 对比表**

| | JDK 动态代理 | CGLIB |
|---|---|---|
| 实现方式 | 反射生成实现接口的 `Proxy` 类 | ASM 生成目标类的**子类**字节码 |
| 依赖 | JDK 自带（`java.lang.reflect.Proxy`） | 需要第三方（Spring 已内嵌 repackage 版） |
| 前提条件 | **目标类必须实现接口** | 目标类不能被 `final` 修饰 |
| 不能代理 | 无接口的类、接口外的方法 | `final` 类、`final` 方法、`private` 方法（`static` 也不行） |
| 注入方式 | **只能按接口类型注入**（拿不到实现类类型） | 可以按实现类类型注入 |
| 调用开销 | 走 `InvocationHandler.invoke` → 一般还要 `Method.invoke`（反射） | 直接调子类方法 + `MethodProxy.invokeSuper`，不走反射 |
| 生成开销 | 只生成一个实现接口的小类，快 | 生成整个子类（含所有方法覆写），慢一些 |
| 构造器要求 | 无 | **Spring 4.0 起用 Objenesis 绕过，不要求有无参构造器** |

**"CGLIB 必须有无参构造器"是过时的八股**。Spring 4.0 之后 `CglibAopProxy` 默认使用 `ObjenesisCglibAopProxy`，用 `Objenesis`（不调构造器的实例化）创建代理实例。所以「目标类只有有参构造器」也能被 CGLIB 代理。**能主动纠正这一条，面试官会认为你读的是源码而不是八股文。**

**Spring 的选型逻辑（`DefaultAopProxyFactory.createAopProxy`，源码逻辑）**

```java
public AopProxy createAopProxy(AdvisedSupport config) {
    // 只要满足以下任一条件，就走 CGLIB
    if (config.isOptimize() || config.isProxyTargetClass() || hasNoUserSuppliedProxyInterfaces(config)) {
        Class<?> targetClass = config.getTargetClass();
        // 但如果目标本身是接口，或者已经是 JDK 代理，还是用 JDK
        if (targetClass.isInterface() || Proxy.isProxyClass(targetClass)) {
            return new JdkDynamicAopProxy(config);
        }
        return new ObjenesisCglibAopProxy(config);   // ← 注意是 Objenesis 版本
    }
    return new JdkDynamicAopProxy(config);
}
```

- `isOptimize()`：`@EnableAspectJAutoProxy(optimize=true)`，提前生成代理不用 CGLIB 的回调过滤器，性能优先
- `isProxyTargetClass()`：`proxyTargetClass=true` → 强制 CGLIB
- `hasNoUserSuppliedProxyInterfaces()`：**目标类压根没实现接口** → 只能用 CGLIB

**为什么 Spring Boot 2.0 起默认 `proxy-target-class=true`（这道题必须答对）**

```java
// AopAutoConfiguration（Boot 源码）
@ConditionalOnProperty(prefix = "spring.aop", name = "proxy-target-class",
                       havingValue = "true", matchIfMissing = true)   // ← matchIfMissing=true 就是默认值
static class CglibAutoProxyConfiguration { }

@ConditionalOnProperty(prefix = "spring.aop", name = "proxy-target-class",
                       havingValue = "false")
static class JdkDynamicAutoProxyConfiguration { }
```

三条理由，按重要性排：

1. **JDK 代理只能按接口注入，这是最痛的一点**。Service 实现了 `UserService` 接口，`@Autowired UserService` 没问题，但 `@Autowired UserServiceImpl` 会直接报「找不到 Bean」——因为容器里只有 `Proxy` 类，它只实现了接口，不是 `UserServiceImpl` 的子类。这让「按实现类注入」这种写法彻底不可用，迁移成本高
2. **注解写在实现类上时 JDK 代理会漏掉**。`@Transactional` 标在 `UserServiceImpl.update()` 上、接口 `UserService` 上没标 —— 用 JDK 代理时，`AopUtils` 通过接口方法找注解，找不到 → **事务失效**。CGLIB 代理的是子类，能直接看到实现类方法上的注解
3. **CGLIB 的调用路径更短**（不经过 `Method.invoke` 这层反射），在高频调用下开销更低。虽然 CGLIB 生成代理类更慢，但**生成是一次性的、调用是每次的**，这笔账在高频方法上划得来

**代价**：CGLIB 生成的子类需要能够覆写目标方法，所以 **`final` 方法和 `final` 类无法被代理**。这是默认切到 CGLIB 后最容易踩的坑。

**验证代码（把代理类型打出来，一眼看清）**

```java
@Service
public class UserServiceImpl implements UserService {
    @Override public String find(Long id) { return "user-" + id; }
}

@Component
@Slf4j
public class ProxyInspector implements ApplicationRunner {
    @Autowired private UserService userService;

    @Override
    public void run(ApplicationArguments args) {
        Class<?> clazz = userService.getClass();
        log.info("代理类 = {}", clazz.getName());
        // CGLIB:  UserServiceImpl$$EnhancerBySpringCGLIB$$3f1a2b  (父类是 UserServiceImpl)
        // JDK   :  com.sun.proxy.$Proxy42  /  jdk.proxy2.$Proxy42 (JDK9+)
        log.info("isAopProxy      = {}", AopUtils.isAopProxy(userService));
        log.info("isJdkProxy      = {}", AopUtils.isJdkDynamicProxy(userService));
        log.info("isCglibProxy    = {}", AopUtils.isCglibProxy(userService));
        log.info("终极目标类      = {}", AopProxyUtils.ultimateTargetClass(userService));
    }
}
```

**手写两种代理（理解原理的最好方式）**

```java
// ① JDK 动态代理：必须有接口
public class JdkProxyDemo {
    public static Object proxy(Object target) {
        Class<?>[] ifaces = target.getClass().getInterfaces();
        return Proxy.newProxyInstance(
            target.getClass().getClassLoader(),
            ifaces,
            (proxy, method, args) -> {
                System.out.println("before: " + method.getName());
                Object r = method.invoke(target, args);   // ← 反射调用（JDK18 前开销较大）
                System.out.println("after : " + method.getName());
                return r;
            });
    }
}
```

```java
// ② CGLIB：生成子类，能代理无接口的类
public class CglibProxyDemo {
    public static Object proxy(Class<?> targetClass) {
        Enhancer enhancer = new Enhancer();
        enhancer.setSuperclass(targetClass);
        enhancer.setCallback((MethodInterceptor) (obj, method, args, proxyMethod) -> {
            System.out.println("before: " + method.getName());
            Object r = proxyMethod.invokeSuper(obj, args);  // ← 直接调父类方法，不走反射
            System.out.println("after : " + method.getName());
            return r;
        });
        return enhancer.create();
    }
}
```

**JDK 9+ 动态代理的变化（版本差异题）**

| 版本 | 变化 |
|---|---|
| JDK 8 | 代理类由 `sun.misc.ProxyGenerator` 生成，通过 `Unsafe` 定义类，缓存在 `WeakCache` 里，代理类无名（`com.sun.proxy.$Proxy0`） |
| **JDK 9+** | 模块系统引入后，代理类生成器移入 `java.base` 内部实现；**代理类被定义在一个动态模块里，模块名形如 `jdk.proxy1` / `jdk.proxy2`**，代理类名变成 `jdk.proxy2.$Proxy42`。这对反射、`setAccessible`、模块可见性都有影响（`Proxy` 的 javadoc 里明确写了这一点） |
| **JDK 18** | **JEP 416：用 MethodHandle 重写核心反射**。`Method.invoke` 的实现从「生成字节码 + 手动堆栈操作」改为 MethodHandle 调用链 → **反射调用性能显著提升、去掉了一堆难以维护的内部类**。这意味着「JDK 动态代理因为走反射所以比 CGLIB 慢」这个结论在 JDK 18 之后被大幅削弱 |

**结论要这样讲**：JDK 9 起代理类的**生成开销**和**模块归属**变了；JDK 18 起反射调用的**执行开销**降下来了。所以「JDK 代理一定比 CGLIB 慢」在 JDK 18+ 已经不再是决定性理由——**Spring Boot 默认 CGLIB 的真正理由还是「按实现类注入」和「实现类上的注解能被看到」这两条工程性原因，跟性能关系不大。**

**切点表达式怎么写（面试让你手写一个切点）**

```
execution(* com.example.order.service..*.*(..))
   │       └─ 返回类型（* 表示任意）
   │            └─ 包路径（.. 表示本包及所有子包）
   │                 └─ 类名（* 任意类）
   │                      └─ 方法名（* 任意方法）
   │                           └─ (..) 任意参数
   └─ 切点指示符

// 组合切点
@Pointcut("execution(* com.example..service..*(..)) && @annotation(com.example.Log)")
// 按注解切（最推荐：粒度可控，不依赖包名约定）
@Around("@annotation(com.example.audit.AuditLog)")
// 按 Bean 名切
@Around("bean(userService)")
```

**切点写宽的代价**（这个问题正好接得上手册 07 第 11 题的元空间）：`execution(* com..*(..))` 会匹配到几乎所有 Bean —— 每个被匹配的 Bean 都要生成一个 CGLIB 代理类（`Xxx$$EnhancerBySpringCGLIB$$xxx`），Bean 数量多时**元空间增长明显、启动变慢**。所以切点要尽量收敛到「带特定注解的方法」。

**四个固定通知类型 + Around**

| 通知 | 执行时机 | 能否阻止方法执行 | 能否改返回值 |
|---|---|---|---|
| `@Before` | 方法前 | 抛异常可以 | 不能 |
| `@AfterReturning` | 正常返回后 | — | 不能（能读到结果） |
| `@AfterThrowing` | 抛异常后 | — | 不能（能读到异常） |
| `@After` | 相当于 finally | — | 不能 |
| **`@Around`** | 包住整个调用 | **能**（不调 `proceed()`） | **能** |

**`@Around` 必须调 `proceed()`**，忘了调就是方法直接被跳过（这是新手最常犯的错，也是最难查的错——业务方法根本没执行，日志里什么都不报）。
:::

:::拓展
**AOP 的失效场景（和事务失效同源，一起记）**

| 场景 | 为什么失效 | 修复 |
|---|---|---|
| 同类自调用 `this.method()` | `this` 是原始对象，不是代理 | `AopContext.currentProxy()`（需 `exposeProxy=true`）/ 注入自身 / 拆类 |
| 方法非 public | Spring AOP 只拦 public 方法（`AbstractFallbackTransactionAttributeSource.allowPublicMethodsOnly`） | 改成 public，或用 AspectJ 编译期织入 |
| `final` / `static` 方法 | CGLIB 无法覆写 final，static 不属于实例 | 去掉 final / 改成实例方法 |
| Bean 不是 Spring 管理的 | 自己 `new` 的对象没有代理 | 交给容器管理 |
| 切点表达式写错 | 根本没匹配上 | 开 `logging.level.org.springframework.aop=DEBUG` 看匹配了哪些方法 |
| 代理被自己绕过 | 通过别的引用直接调原始对象 | 统一走容器注入的引用 |

**`AopContext.currentProxy()` 的正确用法**

```java
@EnableAspectJAutoProxy(exposeProxy = true)   // 必须显式开，默认 false
@SpringBootApplication
public class App { }
```

```java
@Service
public class OrderService {
    public void outer() {
        // 拿到当前线程绑定的代理对象，再调用 → 走代理 → 事务/切面生效
        ((OrderService) AopContext.currentProxy()).inner();
    }

    @Transactional(rollbackFor = Exception.class)
    public void inner() { ... }
}
```

**注意 `exposeProxy = true` 的代价**：Spring 会把代理对象放进 `TransactionSynchronizationManager` 的 ThreadLocal（`NamedThreadLocal("Current AOP proxy")`），有轻微开销，且**在异步线程里取不到**。所以这是「救急方案」，长期还是拆类。

**AOP 在 Spring 生态里的广泛应用（说明你不是只知道 `@Transactional`）**

| 能力 | 注解 | 底层切面/拦截器 | 切面 order |
|---|---|---|---|
| 事务 | `@Transactional` | `TransactionInterceptor` | `Ordered.LOWEST_PRECEDENCE`（**最内层**） |
| 异步 | `@Async` | `AsyncExecutionInterceptor` | `Ordered.LOWEST_PRECEDENCE` |
| 缓存 | `@Cacheable` | `CacheInterceptor` | `Ordered.LOWEST_PRECEDENCE` |
| 重试 | `@Retryable` | Spring Retry 的 `RetryOperationsInterceptor` | 默认最低 |
| 限流/熔断 | `@SentinelResource` | Sentinel 的 `SentinelResourceAspect` | 可配 |
| 分布式锁 | 自定义 | 自定义 `@Around` | 需手动配 |
| 方法耗时 | 自定义 | 自定义 `@Around` | 需手动配 |

**为什么事务切面是 `LOWEST_PRECEDENCE`（最内层）**：事务要**尽可能贴近业务方法**——外层切面（比如日志、限流）应该在事务之外执行，否则它们的耗时会被算进事务里，导致长事务。**这个 order 关系是「多个切面共存时谁先谁后」这类追问的答案。**
:::

:::追问
**Q：`@Transactional` 加在 private 方法上为什么不生效？**
两层原因叠加：① Spring AOP 基于代理，**代理无法拦截非 public 方法**（`AbstractFallbackTransactionAttributeSource.computeTransactionAttribute` 里有 `if (allowPublicMethodsOnly() && !Modifier.isPublic(...)) return null;`，直接返回"没有事务属性"）；② 就算方法能拦到，`private` 方法在子类代理里也不可见。**同类自调用 + private 是两个失效原因叠加，写代码时就该避免。**

**Q：`final` 方法上的 `@Transactional` 为什么不生效？**
CGLIB 生成的是子类，`final` 方法不能被子类覆写 → 代理里没有这个方法 → 调用直接落到原始对象上。**注意：`final` 方法不会报错，只是静默不走事务**，比报错更危险。排查方式：`AopUtils.isAopProxy(bean)` 为 true 但方法没走切面 → 查方法是否为 final。

**Q：JDK 动态代理为什么必须实现接口？**
`Proxy.newProxyInstance` 生成的类 `extends Proxy implements <你的接口们>`，**Java 单继承** —— 它必须继承 `java.lang.reflect.Proxy`，所以不可能再去继承你的目标类，只能通过实现接口来"长得像"目标类型。这也解释了为什么它拿不到实现类类型。

**Q：怎么判断一个 Bean 是不是被代理了，是哪种代理？**
`AopUtils.isAopProxy(bean)` → 是否被代理；`AopUtils.isJdkDynamicProxy(bean)` / `AopUtils.isCglibProxy(bean)` → 哪种；`AopProxyUtils.ultimateTargetClass(bean)` → 拿到真正的目标类；`((Advised) bean).getAdvisors()` → 看有哪些通知（能看出是事务还是自定义切面）。**这几行在排查「切面为什么没生效」时非常有用。**
:::

:::锚点
**这道题的锚点用一个真实的项目对照来讲，不编 Java 经历：**

> 「我在推进的那个 **AI 编程助手 + Sonar 静态代码分析**的项目，本质和 AOP 解决的是同一类问题：**把跨模块的通用逻辑收口到一处，而不是散在每个业务代码里。** 区别是 Sonar 在**编译期/CI 阶段**做全量规则校验，AOP 在**运行期**做横切拦截。我现在在做的事，正好让我理解「收口」这件事的价值和代价——Sonar 规则写宽了会满屏误报（就像切点写宽了要生成一堆代理类），规则写窄了又抓不到问题（就像切点没匹配上，静默不生效）。」

**再加一段真实的技术对照**（这部分是完全真的）：

> 「AOP 的核心是『不改业务代码加功能』，这个思路我在 Node.js 里也一直在用——Express 中间件、Koa 的洋葱模型都是同一个东西。**但 Java 这边多了一个坑：因为织入靠代理，所以产生了「自调用不走代理」这类失效场景。** Node 中间件因为是在请求链路上显式串起来的，反而不存在这个问题。这是我理解的 Spring AOP 的最大成本：**能力换来的是隐式性，隐式性带来的是排错难度。**」

**为什么这段话有说服力**：你不是在背 AOP 定义，而是在**用两种技术栈对比说明你理解了它的设计代价**。这是「转 Java」候选人最能得分的表达方式——你的旧栈是资产，不是短板。
:::

---

## 6. AOP 的实际应用（真实可落地的 8 个场景）★

:::概念
判断一段逻辑该不该抽成切面，标准是两条：**① 与业务无关（业务代码不该知道它存在）；② 横跨多个方法（抽成工具类会到处传参）**。
最常用的不是「日志/事务/权限」这三个词，而是**「自定义注解 + `@Around` + 明确的副作用边界」**这个组合。
记住一条铁律：**切面里的资源获取与释放必须成对（`try/finally`），否则就是下一个 P0 故障。**
:::

:::提问
- AOP 在你们项目里怎么用的？举个实际例子。
- 除了日志和事务，AOP 还能做什么？
- 多个切面的执行顺序怎么控制？
- 分布式锁用 AOP 实现有什么坑？
- 切面里抛异常对事务有影响吗？
- 拦截器、过滤器、AOP 分别在什么时候用？
:::

:::答案
**8 个真实场景总表（面试直接按这个表讲，比说三个词强太多）**

| # | 场景 | 注解 | 切面做什么 | 副作用边界（最关键） | 坑 |
|---|---|---|---|---|---|
| 1 | **分布式锁** | `@DistributedLock` | `@Around` 里 Redis `SETNX` 加锁 → `proceed()` → `finally` 解锁 | 锁的持有范围必须**包住整个事务** | 切面 order 必须小于事务切面，否则锁先释放 |
| 2 | **接口幂等** | `@Idempotent` | 请求前查 Redis 幂等键，存在直接返回上次结果；不存在则 `setIfAbsent` 占位 | 在处理开始前占位，失败要删除占位 | 占位失败但业务失败 → 必须删 key，否则永久拒绝 |
| 3 | **链路追踪** | 无（或 `@TraceIgnore`） | `MDC.put("traceId", ...)` → `proceed()` → `finally MDC.clear()` | 必须在 finally 清理，否则线程池复用会串号 | 异步线程要手动传递 MDC |
| 4 | **慢调用监控** | `@Monitor` | 统计 P99、超阈值打点（Micrometer/Prometheus） | 无资源占用，但要避免高频打点 | 打点本身有开销，别在 QPS 上万的方法上全量采样 |
| 5 | **审计日志** | `@AuditLog` | `@Around` 记：谁、什么时间、调了什么、结果、耗时，异步落库 | 异步落库要 `afterCommit`，别在事务里写 | 大字段（请求体）不能全量落库 |
| 6 | **数据脱敏** | `@Desensitize` | 返回结果里手机号/身份证打码 | 只改返回值，不改库 | 反射遍历对象的开销 |
| 7 | **重试** | `@Retryable` | `@Around` 捕获指定异常重试 N 次 | 只对**幂等**操作重试 | 非幂等操作重试 = 重复下单 |
| 8 | **多数据源路由** | `@DS("slave")` | 切面写 `DynamicDataSourceContextHolder`，`finally` 清 | 必须在 `finally` 清理 ThreadLocal | 和事务切面 order 冲突（要在事务外层选好数据源） |

**场景 1：分布式锁（最值得讲透的一个，坑最多）**

```java
@Target(ElementType.METHOD)
@Retention(RetentionPolicy.RUNTIME)
public @interface DistributedLock {
    String key();              // SpEL 表达式，如 "#orderId"
    long waitMs() default 0;   // 等待锁的时间，0 = 不等待直接失败
    long leaseMs() default 30000;
}
```

```java
@Aspect
@Component
@Order(Ordered.HIGHEST_PRECEDENCE + 10)   // ★ 必须比事务切面（LOWEST_PRECEDENCE）靠外
@Slf4j
public class DistributedLockAspect {

    private final StringRedisTemplate redis;
    private static final String UNLOCK_LUA =
        "if redis.call('get', KEYS[1]) == ARGV[1] then return redis.call('del', KEYS[1]) else return 0 end";

    @Around("@annotation(lock)")
    public Object around(ProceedingJoinPoint pjp, DistributedLock lock) throws Throwable {
        String key = SpelUtils.parse(lock.key(), pjp);      // 解析 SpEL 得到业务 key
        String token = UUID.randomUUID().toString();        // ★ 唯一值，防止误删别人的锁
        Boolean ok = redis.opsForValue()
                          .setIfAbsent("lock:" + key, token, lock.leaseMs(), TimeUnit.MILLISECONDS);
        if (!Boolean.TRUE.equals(ok)) {
            throw new BizException("操作太频繁，请稍后重试");
        }
        try {
            return pjp.proceed();                            // 业务 + 事务都在锁内
        } finally {
            // ★ 用 Lua 保证"判断 + 删除"原子，避免删掉别人（超时后重入）的锁
            redis.execute(new DefaultRedisScript<>(UNLOCK_LUA, Long.class),
                          Collections.singletonList("lock:" + key), token);
        }
    }
}
```

**三个必须讲的坑**：

1. **锁必须包住事务**。如果锁切面在事务切面**内层**（order 更大），执行顺序就是：事务开启 → 加锁 → 业务 → 解锁 → **事务提交** —— 解锁发生在提交之前，另一个线程拿到锁后读到的是**未提交的数据**，锁形同虚设。这就是 `@Order` 必须比 `Ordered.LOWEST_PRECEDENCE` 小的原因。**能主动讲出这一点，说明你想过并发，不是背的。**
2. **解锁必须用 Lua 原子操作 + 唯一 token**。直接 `DEL` 会删掉别人的锁（自己的锁超时失效后，别人加锁成功，你执行完把别人的锁删了）。判断 token 和删除之间如果分两步，一样有竞态。
3. **锁的租期要覆盖业务最长耗时**。设 30s 但业务跑了 40s → 锁提前失效 → 并发进入。要么把 `leaseMs` 设够，要么用看门狗（Redisson 的 `lock()` 自动续期）。

**场景 2：幂等（和锁的区别是「防重」而不是「互斥」）**

```java
@Aspect @Component
@Order(Ordered.HIGHEST_PRECEDENCE + 20)
public class IdempotentAspect {
    @Around("@annotation(idem)")
    public Object around(ProceedingJoinPoint pjp, Idempotent idem) throws Throwable {
        String key = "idem:" + SpelUtils.parse(idem.key(), pjp);
        // setIfAbsent 成功 = 第一次请求；失败 = 重复请求
        Boolean first = redis.opsForValue().setIfAbsent(key, "1", idem.expire(), TimeUnit.SECONDS);
        if (!Boolean.TRUE.equals(first)) {
            throw new BizException("请勿重复提交");
        }
        try {
            return pjp.proceed();
        } catch (Throwable t) {
            redis.delete(key);      // ★ 业务失败要释放占位，允许用户重试
            throw t;
        }
    }
}
```

**注意**：幂等切面要「业务失败就删 key」，而锁切面要「无论如何都解锁」——**这两个场景的 `finally` 行为是相反的**，这是很容易被追问的细节。

**场景 3：链路追踪 / MDC 日志染色（成本最低、收益最高的一个切面）**

```java
@Aspect @Component
public class TraceAspect {
    private static final String TRACE_ID = "traceId";

    @Around("@within(org.springframework.web.bind.annotation.RestController)")
    public Object around(ProceedingJoinPoint pjp) throws Throwable {
        String traceId = Optional.ofNullable(MDC.get(TRACE_ID))
                                 .orElseGet(() -> UUID.randomUUID().toString().replace("-", ""));
        MDC.put(TRACE_ID, traceId);
        try {
            return pjp.proceed();
        } finally {
            MDC.clear();     // ★ 必须清！线程池会复用线程，不清就串号
        }
    }
}
```

```xml
<!-- logback-spring.xml：让每条日志都带上 traceId，线上排查全靠它 -->
<pattern>%d{yyyy-MM-dd HH:mm:ss.SSS} [%thread] [%X{traceId}] %-5level %logger{36} - %msg%n</pattern>
```

**异步线程的坑**：`@Async` 方法在另一个线程执行，MDC 是 ThreadLocal，子线程拿不到 —— 要用 `TaskDecorator` 把父线程的 MDC 复制到子线程：

```java
@Bean
public ThreadPoolTaskExecutor taskExecutor() {
    ThreadPoolTaskExecutor exec = new ThreadPoolTaskExecutor();
    exec.setCorePoolSize(8);
    exec.setMaxPoolSize(32);
    exec.setQueueCapacity(1000);
    exec.setThreadNamePrefix("biz-async-");
    exec.setTaskDecorator(runnable -> {                       // ★ 关键
        Map<String, String> ctx = MDC.getCopyOfContextMap();
        return () -> {
            if (ctx != null) MDC.setContextMap(ctx);
            try { runnable.run(); } finally { MDC.clear(); }
        };
    });
    return exec;
}
```

**场景 4：慢调用监控（生产环境的眼睛）**

```java
@Around("execution(* com.example..service..*(..))")
public Object monitor(ProceedingJoinPoint pjp) throws Throwable {
    long start = System.nanoTime();
    try {
        return pjp.proceed();
    } finally {
        long costMs = (System.nanoTime() - start) / 1_000_000;
        String name = pjp.getSignature().toShortString();
        Timer.builder("biz.method").tag("method", name).register(meterRegistry).record(costMs, TimeUnit.MILLISECONDS);
        if (costMs > 500) {                                   // 阈值 500ms
            log.warn("slow method: {} cost={}ms, args={}", name, costMs, safeArgs(pjp));
        }
    }
}
```

**为什么用 `System.nanoTime()` 而不是 `currentTimeMillis()`**：`nanoTime` 单调递增，不受 NTP 校时和系统时间跳变影响；`currentTimeMillis` 在服务器校时的时候会产生负数耗时。

**切面执行顺序（必背）**

| 机制 | 顺序 | 能拿到什么 | 典型用途 |
|---|---|---|---|
| `Filter` | 第 1 层（Servlet 容器） | `ServletRequest`、原始请求体 | 编码、CORS、请求体缓存（`ContentCachingRequestWrapper`）、全局 traceId |
| `HandlerInterceptor` | 第 2 层（DispatcherServlet 内） | `HandlerMethod`（知道要调哪个方法） | 登录校验、权限校验、接口耗时统计 |
| `AOP` | 第 3 层（方法调用） | 方法参数、注解、返回值 | 事务、锁、幂等、缓存 |
| `Controller` 方法 | 第 4 层 | 业务参数 | 业务逻辑 |

```
请求 → Filter#doFilter → DispatcherServlet#doDispatch
        → Interceptor#preHandle → AOP 前置 → Controller 方法
        → AOP 后置 → Interceptor#postHandle → Interceptor#afterCompletion → Filter 出栈
```

**多切面 order 规则**：`@Order` 数值**越小越靠外**（先进入、后退出），形成洋葱结构。`Ordered.HIGHEST_PRECEDENCE = Integer.MIN_VALUE`，`Ordered.LOWEST_PRECEDENCE = Integer.MAX_VALUE`。**事务、异步、缓存三个内置切面都是 `LOWEST_PRECEDENCE`（最内层）**。
:::

:::拓展
**切面里的异常处理：一个能让事务失效的隐形坑**

```java
// ❌ 错误写法：切面把异常吞了 → 事务切面（在内层）本来已经标记回滚，但外层吞掉异常后
//    如果异常根本没抛出方法边界，事务切面就认为"正常返回"→ commit
@Around("@annotation(xxx)")
public Object bad(ProceedingJoinPoint pjp) {
    try {
        return pjp.proceed();
    } catch (Exception e) {
        log.error("出错了", e);
        return null;             // ← 吞掉异常，事务不回滚
    }
}

// ✅ 正确写法：要么原样抛出，要么抛 RuntimeException
@Around("@annotation(xxx)")
public Object good(ProceedingJoinPoint pjp) throws Throwable {
    try {
        return pjp.proceed();
    } catch (Exception e) {
        log.error("出错了", e);
        throw e;                 // ← 让异常继续向上传播
    }
}
```

**注意 order 关系**：这里要分清两个方向。**内层切面抛出的异常，外层切面如果 catch 住不抛，事务是否回滚取决于事务切面有没有"看到"异常**。因为事务切面是最内层（`LOWEST_PRECEDENCE`），异常从业务方法抛出后**第一个经过的就是事务切面** → 事务切面看到异常 → 标记回滚 → 再抛给外层。**所以外层切面吞异常不会导致事务不回滚**（事务已经标记了）。反过来，事务切面在外层时就危险了。这个推导过程讲出来，比背结论有价值。

**切面里做 `@Transactional` 的「提交后」动作**

```java
@Around("@annotation(audit)")
public Object audit(ProceedingJoinPoint pjp, AuditLog audit) throws Throwable {
    Object result = pjp.proceed();
    // 事务可能还没提交！此时读库/发 MQ 都可能读到旧数据或引发一致性问题
    // 正确做法：注册事务同步回调，在提交后执行
    if (TransactionSynchronizationManager.isSynchronizationActive()) {
        TransactionSynchronizationManager.registerSynchronization(new TransactionSynchronization() {
            @Override public void afterCommit() {
                mqTemplate.send("audit-topic", buildMsg(pjp, result));
            }
        });
    } else {
        mqTemplate.send("audit-topic", buildMsg(pjp, result));
    }
    return result;
}
```

**`afterCommit` 是「事务提交后发消息」的标准答案**（事务提交前发 MQ，一旦回滚，消息已发出无法撤回）。

**切面不要做的事**：① 不要在切面里查数据库做权限校验（每次调用一次查询，QPS 高了就是灾难，应该用缓存或网关层做）；② 不要在切面里做耗时超过 1ms 的同步操作（会放大到所有被切方法上）；③ 不要用切面做参数校验（用 `@Valid` + `@ControllerAdvice`，更标准）。**「切面不是万能的，它有明确的适用边界」——这句话本身就是加分项。**
:::

:::追问
**Q：锁切面和事务切面的顺序搞反了会有什么后果？**
解锁发生在事务提交之前 → 并发线程拿到锁后读到**未提交的数据**（比如库存还是旧值）→ 超卖。这是生产事故级别的后果。**判断方法**：看 `@Order` 值，锁切面必须 `<` `Ordered.LOWEST_PRECEDENCE`（事务的默认 order）。更保险的做法是用 `@EnableTransactionManagement(order = Ordered.LOWEST_PRECEDENCE + 100)` 把事务切面压到最内层，给所有自定义切面留出空间。

**Q：`@Async` 和 `@Transactional` 同时标在一个方法上会怎样？**
`@Async` 在**新线程**里执行，而事务上下文是 TC 绑在 ThreadLocal（`TransactionSynchronizationManager.resources`）上的 → **新线程里没有事务上下文，等于没有事务**。而且两个切面 order 相同（都是 `LOWEST_PRECEDENCE`），顺序不确定。正确做法是：把事务方法单独抽出来，在异步方法里调用它（通过注入的代理调用，不能自调用）。

**Q：AOP 和拦截器都做不到的事情是什么？**
拦截**方法内部的调用**。AOP 只能拦「从代理进入的方法」，方法内部 `this.other()` 拦不到；AspectJ 编译期织入可以（字节码级别直接插到方法体里），所以有强需求时要用 `aspectj-maven-plugin` / LTW，代价是构建链变复杂。**这个边界的认知很重要**——不要一遇到 AOP 失效就怪配置，先想「这个调用有没有经过代理」。

**Q：怎么快速确认一个自定义切面生效了？**
三招：① 在切面里打日志，看有没有打印；② 加 `logging.level.org.springframework.aop=DEBUG`，日志会打印每个 Bean 的切面匹配结果（`CandidateAdvisors` / `Adding transactional method`）；③ 用第 5 题的 `AopUtils.isAopProxy()` + `((Advised) bean).getAdvisors()` 看代理上挂了哪些通知。**①最快，③最准。**
:::

:::锚点
**这道题你有两个真实可用的锚点，都不是编的。**

**锚点一：Sonar 静态代码分析项目（讲「收口」这个共同思想）**

> 「我推进的那个集成 Sonar 的 AI 编程助手，本质和 AOP 是同一个诉求：**把跨模块的通用规则收口**。区别是 Sonar 在 CI 阶段全量扫描（编译期），AOP 在运行期按切点拦截。我在做的过程中体会最深的一点是**规则粒度的取舍**——规则写太宽满屏误报，没人看；写太窄又漏问题。AOP 的切点表达式是一模一样的取舍：`execution(* com..*(..))` 会生成一堆代理类、拖慢启动（这也是我们手册里元空间增长的常见原因），所以我倾向用**按注解切**，只有明确标了注解的方法才被拦截。」

**锚点二：`write after end` 故障（讲「资源必须成对释放」）**

> 「切面里 `try/finally` 释放资源这件事，我是有真实教训的：我们国际环境的 rrmcontrol 因为 **"write after end" 反复重启**，根因就是硬编码功率上限的那个场景下**连接的生命周期管理有缺陷**——连接已经结束了，还有代码在往上面写。修复（commit `fd4ed739`）的方向就是把连接的生命周期和操作的生命周期对齐。**放到 AOP 里的道理完全一样：`@Around` 里加锁/加 traceId/切数据源，`finally` 里必须成对释放，否则线程池复用线程的时候就会串号或者锁泄漏。** 我对这类『成对操作』的敏感度是被真实故障练出来的。」

**这两段的用法**：场景一展示你的工程视野（不只是会写注解），场景二展示你有真实故障经验并且能迁移到 Java。**两段都不是编造的**——Sonar 项目在推进、rrmcontrol 故障和 commit 都是真的。
:::

---

## 7. 事务管理：源码链路 + 8 种失效场景 ★

:::概念
`@Transactional` = **AOP 代理 + `PlatformTransactionManager` + ThreadLocal 绑定 Connection**。声明式事务没有任何魔法，本质是「代理在方法前后调了 `begin` / `commit` / `rollback`」。
两条必须背的默认值：**默认只回滚 `RuntimeException` 和 `Error`**（Checked 异常不回滚）；**默认传播行为是 `REQUIRED`**。
一句判据：**事务失效 = 代理没生效，或 Connection 没绑定到当前线程。**
:::

:::提问
- `@Transactional` 的原理是什么？它是怎么做到多个 SQL 在同一个事务里的？
- `@Transactional` 什么时候会失效？说 5 种以上。
- 为什么同类方法内部调用事务不生效？怎么解决？
- 传播行为有哪几种？`REQUIRED` 和 `REQUIRES_NEW` 的区别？
- 默认回滚哪些异常？Checked 异常为什么不回滚？
- `@Transactional` 加在 Controller 上行不行？
- 事务和锁的顺序应该是什么样？
- 事务提交后要发消息，怎么做？
:::

:::答案
**源码链路（6 步，每一步的类名都要能报出来）**

```
① 代理生成
   AbstractAutoProxyCreator.postProcessAfterInitialization（Bean 生命周期第 6 步）
   → 发现方法/类上有 @Transactional
   → 由 InfrastructureAdvisorAutoProxyCreator 找到 TransactionInterceptor
   → 生成 JDK 或 CGLIB 代理

② 拦截
   调用事务方法 → TransactionInterceptor.invoke()
   → invokeWithinTransaction(invocation, targetClass, ...)
   → 从 @Transactional 里解析出 TransactionAttribute（传播、隔离、超时、rollbackFor、readOnly）

③ 开事务
   createTransactionIfNecessary()
   → PlatformTransactionManager.getTransaction(txAttr)
   → AbstractPlatformTransactionManager.getTransaction()
        ├─ doGetTransaction()   ← DataSourceTransactionManager 从连接池"借"连接
        ├─ 如果已有事务 → handleExistingTransaction()（处理传播行为）
        └─ 如果没有 → startTransaction() → doBegin()
              DataSourceTransactionManager.doBegin()：
                  con = dataSource.getConnection();
                  con.setAutoCommit(false);              // ★ 事务的本质
                  con.setTransactionIsolation(隔离级别);   // 如果配置了
                  con.setReadOnly(readOnly);

④ 绑定线程
   TransactionSynchronizationManager.bindResource(dataSource, new ConnectionHolder(con))
   → resources 是个 ThreadLocal<Map<Object, Object>>
   → ★ 这就是"多个 SQL 在同一个事务"的答案：同线程内任何地方拿到的都是同一个 Connection

⑤ 执行
   invocation.proceed()  → 业务方法
   → MyBatis/JdbcTemplate 内部调 DataSourceUtils.getConnection(dataSource)
   → 从 ThreadLocal 里取出 ConnectionHolder → 拿到同一个 Connection
   → （MyBatis 侧：SpringManagedTransaction.getConnection() 走的就是这条路径）

⑥ 收尾
   正常返回 → commitTransaction() → AbstractPlatformTransactionManager.commit()
                   → doCommit() → con.commit()
   抛异常   → completeTransactionAfterThrowing() → rollbackOn(ex) 判定是否回滚
                   → doRollback() → con.rollback()
   无论成败 → cleanupAfterCompletion()：
                   TransactionSynchronizationManager.unbindResource(dataSource)  // 解绑 ThreadLocal
                   con.setAutoCommit(true)                                        // 恢复
                   DataSourceUtils.releaseConnection(con, dataSource)             // 归还连接池
                   triggerAfterCompletion()                                       // 回调
```

**关键点解释（这几句是撑住追问的核心）**

| 问题 | 答案 |
|---|---|
| 为什么多个 SQL 在同一个事务？ | 第 ④ 步把 `Connection` 以 `ConnectionHolder` 的形式绑到当前线程的 `ThreadLocal`；MyBatis/JdbcTemplate 每次都从 `DataSourceUtils.getConnection()` 取，拿到的是同一个 Connection |
| 事务的物理本质是什么？ | `Connection.setAutoCommit(false)` + 最后 `commit()` 或 `rollback()`。数据库每一层都没变，就是 JDBC 那套 |
| 为什么事务不能跨线程？ | `TransactionSynchronizationManager.resources` 是 `ThreadLocal`，新线程里是空的 → 等于没有事务 |
| 隔离级别不配的话用谁？ | 用数据库默认。**MySQL InnoDB 默认 `REPEATABLE READ`**（靠 MVCC + 间隙锁，不是靠锁整个表） |
| `readOnly=true` 有什么用？ | `con.setReadOnly(true)` → MySQL 会跳过一些优化（如不写 undo 的某些路径）、某些驱动/中间件会路由到只读从库。**只在真正只读的方法上标**，别乱标 |

**7 种传播行为（这张表必须能画出来）**

| 传播行为 | 当前有事务时 | 当前无事务时 | 会挂起外层吗 | 典型用途 |
|---|---|---|---|---|
| **`REQUIRED`（默认）** | 加入当前事务 | 新建一个 | 否 | 99% 的场景 |
| `SUPPORTS` | 加入当前事务 | 以非事务方式执行 | 否 | 查询方法（有没有事务都行） |
| `MANDATORY` | 加入当前事务 | **抛异常** | 否 | 强制要求调用方开事务 |
| **`REQUIRES_NEW`** | **挂起外层，新开一个独立事务** | 新建一个 | **是** | 日志/审计：业务回滚了，日志也要留下 |
| `NOT_SUPPORTED` | 挂起外层，以非事务方式执行 | 非事务执行 | 是 | 大批量操作不想占事务 |
| `NEVER` | **抛异常** | 非事务执行 | 否 | 禁止在事务中调用 |
| **`NESTED`** | **只对 `DataSourceTransactionManager` 有效**：用 Savepoint。内层回滚不影响外层 | 同 `REQUIRED` | 否（不是挂起，是嵌套） | 部分失败不影响整体的批量操作 |

**`REQUIRED` vs `REQUIRES_NEW` 的物理差异**（这是最能体现深度的一个点）：

```
REQUIRED（默认）：
  外层 A 开事务 → 拿 Connection#1（autocommit=false）
    A 调 B → B 加入 A 的事务 → 还是 Connection#1
    B 抛异常标记回滚 → 整个事务（含 A）一起回滚

REQUIRES_NEW：
  外层 A 开事务 → 拿 Connection#1，挂起（存入 suspendedResources）
    A 调 B → B 新建事务 → 从连接池拿 Connection#2（autocommit=false）
    B 提交/回滚只影响 Connection#2 → Connection#2 归还，恢复 Connection#1
    A 继续，A 的回滚不影响 B 的结果
```

**由此推出一个真实的坑**：`REQUIRES_NEW` 会**额外占用一个数据库连接**。如果一处代码在循环里调了 `REQUIRES_NEW` 方法，或者嵌套三层（每层一个 `REQUIRES_NEW`），**连接池会被瞬间打满**（默认 HikariCP `maximumPoolSize=10`）。现象是请求卡住、`Connection is not available, request timed out after 30000ms`。**这个坑比「REQUIRES_NEW 会开新事务」这句话有价值得多。**

```yaml
# HikariCP 默认值（被追问参数时的弹药）
spring:
  datasource:
    hikari:
      maximum-pool-size: 10          # 默认 10
      minimum-idle: 10               # 默认 = maximum-pool-size
      connection-timeout: 30000      # 30s
      idle-timeout: 600000           # 10min
      max-lifetime: 1800000          # 30min，必须小于 MySQL 的 wait_timeout
      leak-detection-threshold: 20000  # 20s 未归还就打印堆栈（排查连接泄漏的神器）
```

**8 种事务失效场景（面试按这张表说，每说一条给一个修复方法）**

| # | 场景 | 根因 | 修复 |
|---|---|---|---|
| 1 | **同类自调用** `this.update()` | `this` 是原始对象不是代理，根本不经过 `TransactionInterceptor` | ① 拆到另一个 Bean ② 注入自身 `@Autowired private XxxService self;` ③ `AopContext.currentProxy()`（需 `exposeProxy=true`）④ 用 `TransactionTemplate` 手动包 |
| 2 | **方法不是 public** | `AbstractFallbackTransactionAttributeSource.computeTransactionAttribute` 里有 `allowPublicMethodsOnly()` + `!Modifier.isPublic()` → 直接返回 null，等于没有事务属性 | 改成 public。**注意 Spring 5.x + 纯代理模式下，protected/包级方法也不生效**（只有 AspectJ 模式支持非 public） |
| 3 | **`final` / `static` 方法** | CGLIB 无法覆写 final 方法，static 不属于实例 | 去掉 final |
| 4 | **异常被自己 catch 吞掉** | 代理看不到异常 → 认为"正常返回" → 走 commit | rethrow，或手动 `TransactionAspectSupport.currentTransactionStatus().setRollbackOnly()` |
| 5 | **抛的是 Checked 异常且没配 `rollbackFor`** | 默认只回滚 `RuntimeException` 和 `Error`（`DefaultTransactionAttribute.rollbackOn`） | `@Transactional(rollbackFor = Exception.class)` —— **这一条几乎应该成为团队规范** |
| 6 | **多线程 / `@Async`** | 事务上下文绑在 ThreadLocal，新线程里没有；代理也跨不过线程 | 抽成独立 Bean，在异步方法里调它 |
| 7 | **Bean 不是 Spring 管理的** | 手动 `new` 出来的对象没有代理 | 交给容器；工具类里的 Service 要通过注入传入 |
| 8 | **注解写在接口上 + JDK 代理** / 多数据源用错事务管理器 / 存储引擎是 MyISAM | ① JDK 代理按接口方法找注解，实现类上的注解看不到（Spring 官方文档明确说「接口上的注解在 CGLIB 下不会被继承」）；② 跨数据源要用对应的 `TransactionManager`；③ MyISAM 引擎不支持事务，SQL 无声无息地不回滚 | ① 注解统一写在**实现类**上；② 多数据源用 `@Transactional(transactionManager="xxxTxManager")`；③ 表必须是 InnoDB |

**第 5 条展开（最容易被忽略又最常出错）**

```java
// ❌ 默认配置下，IOException 是 Checked，不回滚！
@Transactional
public void save() throws IOException {
    orderMapper.insert(order);
    throw new IOException("磁盘满了");    // 数据已经插进去了
}

// ✅ 显式声明回滚所有异常
@Transactional(rollbackFor = Exception.class)
public void save() throws IOException { ... }
```

```java
// 源码依据：DefaultTransactionAttribute.rollbackOn()
public boolean rollbackOn(Throwable ex) {
    return (ex instanceof RuntimeException || ex instanceof Error);
}
```

**第 1 条展开：自调用的三种修法（给代码）**

```java
// 修法 1（推荐）：拆到独立 Bean —— 逻辑清晰、没有黑魔法
@Service
public class OrderService {
    private final OrderTxService orderTxService;      // 注入另一个 Bean
    public OrderService(OrderTxService s) { this.orderTxService = s; }
    public void outer() { orderTxService.inner(); }
}

@Service
public class OrderTxService {
    @Transactional(rollbackFor = Exception.class)
    public void inner() { ... }
}
```

```java
// 修法 2：注入自身（注意名字别冲突，用 @Lazy 防循环依赖）
@Service
public class OrderService {
    @Lazy @Autowired private OrderService self;
    public void outer() { self.inner(); }        // 走代理
    @Transactional(rollbackFor = Exception.class)
    public void inner() { ... }
}
```

```java
// 修法 3：编程式事务（最显式、最可控，适合"只有一段代码要事务"的场景）
@Service
public class OrderService {
    private final TransactionTemplate txTemplate;   // 自动注入 PlatformTransactionManager 即可构造

    public void outer() {
        txTemplate.execute(status -> {
            orderMapper.insert(o);
            if (错了) status.setRollbackOnly();
            return null;
        });
    }
}
```

**`@Transactional` 的 8 个常用属性**

```java
@Transactional(
    propagation   = Propagation.REQUIRED,          // 传播行为，默认 REQUIRED
    isolation     = Isolation.DEFAULT,             // 隔离级别，默认用数据库的
    timeout       = 30,                            // 秒；底层 Statement.setQueryTimeout
    readOnly      = false,                         // 只读优化；只读方法上标 true
    rollbackFor   = Exception.class,               // ★ 建议永远显式写
    noRollbackFor = BizWarnException.class,        // 业务警告不回滚
    transactionManager = "orderTxManager"          // 多数据源时指定
)
```

**两个"不失效但会出事"的实践问题**

| 问题 | 表现 | 处置 |
|---|---|---|
| **大事务** | 事务里做了 RPC / 发 MQ / 大量计算 → 事务时间长 → 锁持有久、undo log 膨胀、连接占满 | 事务里只留 DB 操作，其他全部移出事务；用 `TransactionSynchronization.afterCommit()` 处理后续动作 |
| **`@Transactional` 标在 Controller / 大方法上** | 事务范围过大，包含参数校验、日志、序列化 | 事务边界放在 Service 层的方法级，粒度越细越好。**「事务边界 == 一个业务原子操作」是唯一的判断标准** |

**事务提交后才发消息（`afterCommit`，生产必备）**

```java
// ❌ 事务里发 MQ：事务回滚了，消息已经发出去了 → 下游处理了不存在的数据
mqTemplate.send("order-created", order);

// ✅ 注册事务同步回调，提交后才发
TransactionSynchronizationManager.registerSynchronization(new TransactionSynchronization() {
    @Override public void afterCommit() {
        mqTemplate.send("order-created", order);
    }
});
```

**更稳的方案是本地消息表 / 事务消息**（RocketMQ 的事务消息、Seata 的 AT 模式），`afterCommit` 只能解决「不早发」，解决不了「提交成功但发消息失败」——那要靠本地消息表 + 定时补偿。
:::

:::拓展
**如何确认事务到底有没有生效（三步排查）**

```
① 打开事务调试日志（最直接）
   logging.level.org.springframework.transaction.interceptor=TRACE
   logging.level.org.springframework.jdbc.datasource.DataSourceTransactionManager=DEBUG
   → 日志会打印：Creating new transaction / Participating in existing transaction / Initiating
     transaction commit / Rolling back

② 代码里断言
   TransactionSynchronizationManager.isActualTransactionActive()   // 当前线程是否有真实事务
   TransactionSynchronizationManager.getCurrentTransactionName()   // 当前事务名（就是方法全限定名）

③ 看数据库
   SELECT * FROM information_schema.INNODB_TRX;      -- 当前活跃事务
   SHOW ENGINE INNODB STATUS;                        -- 事务详情和锁等待
   SHOW PROCESSLIST;                                 -- 看有没有 sleep 的长连接
```

**一个几乎万能的判断法**：在方法里打 `log.info("tx active = {}", TransactionSynchronizationManager.isActualTransactionActive())`。**打印 false 就一定是代理没生效**（自调用/非 public/final/Bean 不受管），打印 true 但数据没回滚就去查 `rollbackFor` 和异常是否被吞。

**隔离级别与 MySQL 的对应**

| Spring `Isolation` | MySQL 支持 | 解决的问题 |
|---|---|---|
| `DEFAULT` | 用数据库默认（InnoDB = RR） | — |
| `READ_UNCOMMITTED` | ✅ | 无 |
| `READ_COMMITTED` | ✅ | 脏读（Oracle/PG 的默认级别） |
| `REPEATABLE_READ` | ✅ **InnoDB 默认** | 脏读 + 不可重复读（MVCC 实现；间隙锁还挡住了大部分幻读） |
| `SERIALIZABLE` | ✅ | 全部，但并发度极低 |

**为什么互联网公司常把 MySQL 改成 RC（`READ-COMMITTED`）**：RR 的间隙锁（Gap Lock）在并发写入时容易死锁；RC 的锁粒度更小、并发更好。代价是丧失「可重复读」，需要应用层处理。**这是「你们线上用什么隔离级别」的加分回答。**

**`@Transactional` 和「锁」的边界（把第 6 题的锁切面接上来）**

```
正确顺序（从外到内）：加锁 → 开事务 → 业务 → 提交事务 → 解锁
错误顺序：            开事务 → 加锁 → 业务 → 解锁 → 提交事务   ← 解锁后数据还没提交，并发可乘之机
```

实现方式：`@Order` 让锁切面在外；或直接在业务方法里显式 `lock.lock(); try { ... } finally { lock.unlock(); }` 包住整个事务方法的调用（**在事务方法外调用**，即调用方加锁）。**第二种更不容易出错，因为它不依赖 order 的隐式约定。**
:::

:::追问
**Q：为什么默认不回滚 Checked 异常？**
Java 的设计哲学是：**Checked 异常表示「可预期的、调用方应该处理的」情况**（如文件不存在、网络抖动），设计者认为调用方会处理它，所以不主动回滚；`RuntimeException` 表示「编程错误或不可恢复的故障」，才需要回滚。这个设计在实际项目里经常不适用（业务校验异常通常是 Checked 或自定义非 RuntimeException），所以**团队规范里应该一律写 `rollbackFor = Exception.class`**。

**Q：`@Transactional` 的 `timeout` 是怎么实现的？**
`DataSourceTransactionManager` 在 `doBegin` 时记录事务开始时间；`Statement` 创建时由 `JdbcTemplate` 调 `statement.setQueryTimeout(seconds)`——**注意它是为了 SQL 级的超时，但实测在 MySQL 上只对部分语句生效（`setQueryTimeout` 在 MySQL 驱动里是另起一个线程执行 `KILL QUERY`）**。更可靠的超时是 `@Transactional(timeout)` + 应用层限时（`Future.get(timeout)`），或者数据库侧设 `innodb_lock_wait_timeout`（默认 50s）和 `max_execution_time`。

**Q：`NESTED` 和 `REQUIRES_NEW` 的区别到底是什么？**
| | `REQUIRES_NEW` | `NESTED` |
|---|---|---|
| 连接 | **新拿一个** Connection | **复用同一个** Connection |
| 实现 | 挂起外层事务 | JDBC Savepoint |
| 内层回滚 | 外层不受影响 | 回滚到 Savepoint，外层可继续 |
| 外层回滚 | 内层已提交的数据**保留**（如果内层先提交了） | 内层也一起回滚 |
| 支持范围 | 所有事务管理器 | **只支持 `DataSourceTransactionManager`**（JTA 不支持） |
| 连接池压力 | 大（嵌套 N 层占 N+1 个连接） | 无 |

**Q：`@Transactional` 加在类上和方法上，谁优先？**
方法级优先（`AbstractFallbackTransactionAttributeSource` 先找方法，再找类）。类级注解相当于给所有 public 方法一个默认配置，方法上写的会覆盖它。**实践建议：类级只放 `rollbackFor`，方法级放具体的传播/只读设置。**
:::

:::锚点
**这道题的锚点用「跨存储的一致性边界」来讲，不编造 Java 事务经历：**

> 「Java 的 `@Transactional` 我还没在生产项目里用过，但**事务的本质是划定一致性边界**这件事我理解——我们 RRM 那边用的是 MongoDB（集合 clbDetail / optHistory / autoSwitch / autoOptConfig），MongoDB 的单文档操作是原子的，**跨文档的原子性要靠显式事务（4.0+ 副本集才支持）**，所以我们在设计时更多是靠**单文档设计 + 幂等重放**来保证一致性，而不是靠一个大事务包住所有操作。这个取舍在 Java + MySQL 侧是相反的：因为有成熟的事务机制，反而容易写出**大事务**——把 RPC、发消息、计算全塞进 `@Transactional` 里，导致锁持有时间长、连接被占满。**我理解这两种模型的差异，所以我会主动把事务边界压到最细。**」

**再加一条你真实做过的、能呼应「失效场景」的经验**：

> 「第 6 条『多线程里没有事务上下文』这个问题，我有个非常具体的对照：我们之前排查 **rrmcompute 现网 OOM** 时，最后发现是**高量调优任务并发进入**导致内存暴涨——问题根源就是**并发任务之间共享了不该共享的东西**。事务的 ThreadLocal 隔离机制其实是在解决同一类问题的反面：**它保证了并发单位之间上下文不串**。所以我看到『事务不能跨线程』这条时，理解的是它的设计意图，而不只是记一条规则。**」

**注意**：这两段都只讲「我理解的设计意图」和「我真实遇到过的问题」，**没有说我在 Java 项目里用过事务**。转技术栈的候选人这样答，既诚实又展示迁移能力。
:::

---

## 8. SpringMVC 请求处理流程 ★

:::概念
主干只有一条：**`DispatcherServlet.doDispatch()`**。顺序是 **找 Handler → 找 Adapter → 前置拦截 → 执行 → 处理结果 → 后置拦截**。
一句话记：**`getHandler → getHandlerAdapter → applyPreHandle → handle → processDispatchResult → applyPostHandle`**。
`DispatcherServlet` 本身就是一个 `HttpServlet`，所以它跑在内嵌 Tomcat 里。
:::

:::提问
- 讲一下 SpringMVC 的完整请求流程？
- `DispatcherServlet` 里具体做了哪几件事？
- SpringMVC 有哪九大组件？
- `@RequestBody` 为什么只能读一次？怎么重复读？
- 拦截器和过滤器有什么区别？执行顺序是什么？
- 请求返回 404 / 405 / 415 / 400 分别卡在哪一步？
- 全局异常处理怎么做？
:::

:::答案
**`doDispatch()` 源码级流程（按这个顺序讲，一步不漏）**

```
1. getHandler(request)
   → 遍历所有 HandlerMapping（按 order 排序）
   → RequestMappingHandlerMapping 命中 → 返回 HandlerExecutionChain
     （内含 HandlerMethod + 匹配到的 Interceptor 列表）

2. getHandlerAdapter(handler)
   → 遍历所有 HandlerAdapter，找到 supports(handler) 为 true 的
   → 通常返回 RequestMappingHandlerAdapter

3. mappedHandler.applyPreHandle(request, response)
   → 依次执行所有 Interceptor#preHandle
   → ★ 任一返回 false：立刻 return，postHandle 和 afterCompletion 不会执行
     （注意：已执行过的 preHandle 对应的 afterCompletion 会执行，这是规范）

4. ha.handle(request, response, handler)
   → ServletInvocableHandlerMethod.invokeAndHandle()
        ├─ HandlerMethodArgumentResolver 解析参数（@RequestParam / @RequestBody / @PathVariable ...）
        ├─ 反射调用 Controller 方法
        └─ HandlerMethodReturnValueHandler 处理返回值
              @ResponseBody → RequestResponseBodyMethodProcessor
                            → HttpMessageConverter（MappingJackson2HttpMessageConverter）
                            → writeValue 到 response 输出流（application/json）

5. ModelAndView mv = ...（如果返回的是视图名而不是 @ResponseBody）

6. mappedHandler.applyPostHandle(request, response, mv)
   → 逆序执行 Interceptor#postHandle

7. processDispatchResult(request, response, mv, dispatchException)
   ├─ 有异常 → processHandlerException() → 遍历 HandlerExceptionResolver
   │     ExceptionHandlerExceptionResolver（处理 @ExceptionHandler / @ControllerAdvice）
   │     → ResponseStatusExceptionResolver（处理 @ResponseStatus）
   │     → DefaultHandlerExceptionResolver（处理框架内置异常，如 405/415）
   └─ 无异常 → render(mv, request, response) → ViewResolver 解析 → 渲染

8. mappedHandler.triggerAfterCompletion(request, response, ex)
   → 逆序执行 Interceptor#afterCompletion（一定执行，等于 finally）
```

**九大组件（`DispatcherServlet` 初始化时从 `DispatcherServlet.properties` 加载默认实现）**

| 组件 | 作用 | 默认实现 |
|---|---|---|
| `HandlerMapping` | URL → Handler | `RequestMappingHandlerMapping`（@RequestMapping）、`SimpleUrlHandlerMapping`（静态资源）、`WelcomePageHandlerMapping`（/index.html） |
| `HandlerAdapter` | 执行 Handler | `RequestMappingHandlerAdapter`、`HttpRequestHandlerAdapter` |
| `HandlerExceptionResolver` | 异常 → 响应 | `ExceptionHandlerExceptionResolver`、`ResponseStatusExceptionResolver`、`DefaultHandlerExceptionResolver` |
| `ViewResolver` | 逻辑视图名 → View | `ContentNegotiatingViewResolver`、`InternalResourceViewResolver` |
| `LocaleResolver` | 国际化区域 | `AcceptHeaderLocaleResolver` |
| `ThemeResolver` | 主题 | `FixedThemeResolver` |
| `MultipartResolver` | 文件上传 | 无默认（需自己注册 `StandardServletMultipartResolver`） |
| `FlashMapManager` | 重定向传参 | `SessionFlashMapManager` |
| `HandlerMappingIntrospector` | 缓存 HandlerMapping 信息供 `MvcUriComponentsBuilder` 用 | — |

**HandlerMapping 体系（被追问「静态资源和接口是怎么分开的」）**

| 实现 | 匹配什么 | order |
|---|---|---|
| `RequestMappingHandlerMapping` | 所有 `@RequestMapping` 方法 | 0 |
| `WelcomePageHandlerMapping` | `/` → `index.html` | 2 |
| `BeanNameUrlHandlerMapping` | Bean 名以 `/` 开头的 Handler | 2 |
| `SimpleUrlHandlerMapping` | 静态资源（`/**` → `classpath:/static/` 等） | `Integer.MAX_VALUE - 1` |
| `RouterFunctionMapping` | 函数式端点（WebFlux 风格） | 3 |

**注意 order 关系**：静态资源映射的 order 几乎最大（最后兜底），所以接口和静态资源重名时，**接口优先**。

**参数解析与返回值处理（一进一出两条链）**

```java
// 参数解析：HandlerMethodArgumentResolver 的实现（常用的 6 个）
@RequestParam        → RequestParamMethodArgumentResolver
@PathVariable        → PathVariableMethodArgumentResolver
@RequestBody         → RequestResponseBodyMethodProcessor（用 HttpMessageConverter 读 body）
@RequestHeader       → RequestHeaderMethodArgumentResolver
无需注解的 POJO     → ServletModelAttributeMethodProcessor（表单绑定）
HttpServletRequest   → ServletRequestMethodArgumentResolver

// 返回值处理：HandlerMethodReturnValueHandler
@ResponseBody / @RestController → RequestResponseBodyMethodProcessor
@ModelAndView / String           → ViewNameMethodReturnValueHandler
ResponseEntity                   → HttpEntityMethodProcessor
```

**`@RequestBody` 只能读一次的原因与解法**

原因：`ServletInputStream` 底层是 socket 的输入流，**只能顺序读一次**，读完就没法回到开头（`HttpMessageConverter` 读完 body 后，后面的 Filter/Interceptor/切面再读就是空）。

解法：用 `ContentCachingRequestWrapper` 把 body 缓存下来（Spring 自带）。

```java
@Component
@Order(Ordered.HIGHEST_PRECEDENCE)
public class RequestBodyCacheFilter extends OncePerRequestFilter {
    @Override
    protected void doFilterInternal(HttpServletRequest req, HttpServletResponse resp, FilterChain chain)
            throws ServletException, IOException {
        // 包一层，body 会被缓存在内存里，后续可重复读
        ContentCachingRequestWrapper wrapper = new ContentCachingRequestWrapper(req);
        try {
            chain.doFilter(wrapper, resp);
        } finally {
            // ★ 关键：body 只有在被读过之后才在缓存里
            byte[] body = wrapper.getContentAsByteArray();
            if (body.length > 0) {
                log.info("uri={} body={}", req.getRequestURI(), new String(body, StandardCharsets.UTF_8));
            }
        }
    }
}
```

**踩坑记录**：`ContentCachingRequestWrapper` 的 `getContentAsByteArray()` 在 `chain.doFilter` **之前**调用会返回空数组——因为缓存是「边读边存」的，必须等下游读过 body 才有内容。**这一条是踩过才知道的。**

**拦截器 vs 过滤器 vs AOP（三者对比，高频）**

| | `Filter` | `HandlerInterceptor` | AOP 切面 |
|---|---|---|---|
| 规范 | Servlet 规范 | SpringMVC | Spring AOP |
| 作用位置 | Servlet 容器，`DispatcherServlet` 之前 | `DispatcherServlet` 内部，Handler 之前 | 方法调用层 |
| 能否拿到 HandlerMethod | ❌ 不知道要调哪个方法 | ✅ 能（`HandlerMethod`） | ✅ 能（切点） |
| 能否拿到方法参数 | ❌ | 通过 `HandlerMethod` 反射拿 | ✅ 直接拿 |
| 能否改请求体/响应体 | ✅（wrap request/response） | 只能改 header/attribute | 能改返回值 |
| 能否注入 Spring Bean | ✅（注册为 Bean 时） | ✅ | ✅ |
| 典型用途 | 编码、CORS、traceId、body 缓存、XSS 过滤 | 登录校验、权限、接口耗时 | 事务、锁、幂等、缓存 |
| 执行顺序 | 最外层 | 中间层 | 最内层 |

**完整执行顺序（画出来随手就能讲）**

```
Filter#doFilter
   └─ DispatcherServlet#doDispatch
        └─ Interceptor#preHandle
             └─ AOP 前置通知
                  └─ Controller 方法
             └─ AOP 后置通知
        └─ Interceptor#postHandle
        └─ Interceptor#afterCompletion   ← 一定执行
   └─ Filter 出栈
```

**错误码定位表（这道表能直接用在排障上）**

| 状态码 | 异常 | 卡在哪一步 | 常见原因 |
|---|---|---|---|
| **404** | `NoHandlerFoundException`（默认被吞，返回 404） | 第 1 步 `getHandler` | 路径写错、`@RequestMapping` 前缀不匹配、`server.servlet.context-path` 配了 |
| **405** | `HttpRequestMethodNotSupportedException` | 第 2/4 步（Handler 找到了但方法不匹配） | GET 请求打到了 `@PostMapping` |
| **415** | `HttpMediaTypeNotSupportedException` | 第 4 步（`RequestResponseBodyMethodProcessor` 找不到能读的 converter） | 请求头 `Content-Type` 不是 `application/json`（漏了或写成 `text/plain`） |
| **400** | `HttpMessageNotReadableException` / `MethodArgumentNotValidException` | 第 4 步参数解析 | JSON 格式非法、字段类型不匹配、`@Valid` 校验失败 |
| **500** | 业务异常 | 第 7 步 | 未被 `@ExceptionHandler` 捕获 |

**「415 和 400 怎么区分」是很好的追问点**：415 = **读不了**（Content-Type 不支持转换器），400 = **读了但读不懂/校验不过**（JSON 语法错、类型不匹配）。

**全局异常处理的标准写法**

```java
@RestControllerAdvice
@Slf4j
public class GlobalExceptionHandler {

    @ExceptionHandler(BizException.class)          // 业务异常：已知、可预期
    public ResponseEntity<ApiResult> biz(BizException e) {
        log.warn("业务异常: {}", e.getMessage());
        return ResponseEntity.ok(ApiResult.fail(e.getCode(), e.getMessage()));
    }

    @ExceptionHandler(MethodArgumentNotValidException.class)   // @Valid 校验失败
    public ResponseEntity<ApiResult> valid(MethodArgumentNotValidException e) {
        String msg = e.getBindingResult().getFieldErrors().stream()
                      .map(f -> f.getField() + ": " + f.getDefaultMessage())
                      .collect(Collectors.joining("; "));
        return ResponseEntity.badRequest().body(ApiResult.fail(400, msg));
    }

    @ExceptionHandler(Exception.class)             // 兜底：未知异常，必须记完整堆栈
    public ResponseEntity<ApiResult> unknown(Exception e) {
        log.error("未预期异常", e);
        return ResponseEntity.status(500).body(ApiResult.fail(500, "系统繁忙，请稍后重试"));
    }
}
```

**三个注意点**：① `@RestControllerAdvice` = `@ControllerAdvice` + `@ResponseBody`，返回对象会被序列化成 JSON；② `@ExceptionHandler` 的匹配是**最具体的优先**（`BizException` 比 `Exception` 优先）；③ `@ExceptionHandler` **拿不到原始异常时**（被 `HandlerExceptionResolver` 包装过）要用 `e.getCause()` 挖。
:::

:::拓展
**`PathPatternParser` 与 `AntPathMatcher`（版本差异）**

| | `AntPathMatcher` | `PathPatternParser` |
|---|---|---|
| 引入 | 最早 | Spring 5.3 |
| 原理 | **运行时**用字符串/正则逐段匹配 | 启动时把模式**预解析成 AST**，运行时按 AST 匹配 |
| 性能 | 相对慢（每次请求都解析） | 快（解析一次，复用） |
| URI 变量解码 | 部分支持 | 支持，行为更规范 |
| 默认启用 | Spring 5.3 之前 | **Spring 6.0 起 `RequestMappingHandlerMapping` 默认启用** |

**面试价值**：被问「SpringMVC 性能优化点」时，「路径匹配从运行时字符串解析改成启动期 AST 预解析」是一个很专业的答案。配置方式：

```java
@Configuration
public class WebConfig implements WebMvcConfigurer {
    @Override
    public void configurePathMatch(PathMatchConfigurer configurer) {
        configurer.setPatternParser(new PathPatternParser());   // Spring 5.3~5.3.x 手动开
    }
}
```

**静态资源的默认配置（真实默认值）**

```yaml
spring:
  mvc:
    static-path-pattern: /**                              # 默认
  web:
    resources:
      static-locations: classpath:/META-INF/resources/,classpath:/resources/,classpath:/static/,classpath:/public/
```

**所以 `src/main/resources/static/a.png` 能被 `http://host/a.png` 访问到**——不用写任何 Controller。

```yaml
# 文件上传的真实参数
spring:
  servlet:
    multipart:
      max-file-size: 1MB          # 默认 1MB（单文件）
      max-request-size: 10MB      # 默认 10MB（整个请求）
```

**这条默认值坑过很多人**：上传稍大的文件直接报 `MaxUploadSizeExceededException`，但不知道默认只有 1MB。

**异步请求（`Callable` / `DeferredResult` / SSE）**

| 方式 | 何时用 | 注意 |
|---|---|---|
| `Callable<T>` | 阻塞式业务逻辑想放到容器线程池执行，释放 Tomcat 线程 | 会用 `SimpleAsyncTaskExecutor`，**每次新建线程**，生产必须配 `WebMvcConfigurer#configureAsyncSupport` 自定义线程池 |
| `DeferredResult<T>` | 结果由**另一个线程**（如 MQ 回调）设置 | 要设超时 `setTimeout`，否则请求挂死 |
| `ResponseBodyEmitter` / `SseEmitter` | 流式推送（SSE） | 长连接，注意 Tomcat 的 `connection-timeout` |
| `StreamingResponseBody` | 大文件下载 | 避免一次性加载到内存 |

**注意**：用了异步之后，**`ThreadLocal`（含事务、MDC）不会自动传递**——这和第 6、7 题讲的坑是同一个根因。
:::

:::追问
**Q：`preHandle` 返回 false 之后会发生什么？**
立刻返回，**不执行** `postHandle`，也**不执行** `handler`。但**已执行过 `preHandle` 的拦截器对应的 `afterCompletion` 会被调用**（逆序）——这是 SpringMVC 的契约，用来保证资源能释放。**面试里能答出「afterCompletion 会执行」这一句，说明你真的看过源码。**

**Q：`@ControllerAdvice` 和 `@ExceptionHandler` 的关系？**
`@ExceptionHandler` 定义「处理什么异常」，`@ControllerAdvice` 让它**全局生效**（否则只能处理本 Controller 内的异常）。`ExceptionHandlerExceptionResolver` 在解析异常时，先找本 Controller 内的 `@ExceptionHandler`，再找 `@ControllerAdvice` 里的。`@ControllerAdvice` 还支持 `basePackages` / `assignableTypes` 做范围限定。

**Q：`@ResponseBody` 是怎么变成 JSON 的？**
`RequestResponseBodyMethodProcessor` 遍历所有 `HttpMessageConverter`，找 `canWrite(返回类型, MediaType)` 为 true 的：`MappingJackson2HttpMessageConverter`（Jackson）→ `writeValue` 到 `response.getOutputStream()`。**如果要自定义序列化（如把 Long 转 String 防前端精度丢失），就是自己注册一个 `Jackson2ObjectMapperBuilderCustomizer`。**

**Q：一个请求进来，怎么知道它命中了哪个 Controller 方法？**
开 `logging.level.org.springframework.web=DEBUG`，日志会打印 `Mapped to HandlerExecutionChain with [...] and N interceptors`。或者用 Actuator 的 `/actuator/mappings` 端点，能看到**所有**已注册的 URL → HandlerMethod 映射——**排「接口 404 但代码明明写了」时最快的办法**。

**Q：Tomcat 的线程数和 SpringMVC 的处理线程是什么关系？**
Tomcat 的 worker 线程（`server.tomcat.threads.max`，默认 200）直接执行 `DispatcherServlet.doDispatch()` 的整个流程，**包括你的 Controller 代码**。所以 Controller 里的阻塞操作会占住 Tomcat 线程，200 个线程占满后请求就排队（进 `accept-count` 队列，默认 100）。**这就是「同步阻塞模型」的容量上限公式：并发能力 ≈ 线程数 × (1 / 单请求耗时占比)。**
:::

:::锚点
**锚点用你熟的 Node.js 中间件模型来讲「分层」这件事，非常自然：**

> 「SpringMVC 这套 `Filter → Interceptor → AOP → Controller` 的分层，和 Express 的中间件链是同一个模型——**都是『一串处理器按顺序过一遍请求』**。区别在 Spring 这边分得更细：Filter 在 Servlet 容器层（只能看原始请求）、Interceptor 在 SpringMVC 层（知道要调哪个方法）、AOP 在方法调用层（能拿到参数和返回值）。**我在 Node 里做接口时，鉴权、日志、traceId 全塞在中间件里，到 Java 这边就得分清楚放在哪一层**——比如「记录接口耗时」，放在 Interceptor 比放在 AOP 更合适，因为能拿到 HandlerMethod 信息，也不会因为事务切面的 order 关系被影响。」

**再加一条真实故障的呼应（完全可以讲）**：

> 「我们国际环境 rrmcontrol 那个 `write after end` 反复重启的问题，根因是**连接生命周期管理**——本质上和「一个 HTTP 请求进来、哪一层负责关闭什么资源」是同一类问题。**SpringMVC 里 `afterCompletion` 一定会执行、过滤器出栈时一定会执行，就是框架替你兜住了『资源成对释放』这件事。** 我经历过那个故障之后，对『哪一层负责收尾』这件事会特别敏感。」

**这两段都没有编造**：Node 中间件是事实，rrmcontrol 故障是事实。
:::

---

## 9. Spring 常用注解（全表 + 匹配规则）

:::概念
注解分四类：**声明 Bean**（`@Component` 系）、**注入依赖**（`@Autowired` 系）、**配置类**（`@Configuration`/`@Bean`）、**能力开关**（`@Transactional`/`@Async`/`@Cacheable`/`@PostConstruct`）。
记忆钩子：**「谁是我（组件注解）→ 我需要谁（注入注解）→ 我怎么配（配置注解）→ 我有什么能力（功能注解）」**。
最高频的对比题：**`@Autowired` vs `@Resource`**，以及 **`@Configuration` 的 full/lite 模式**。
:::

:::提问
- Spring 常用注解有哪些？分几类？
- `@Autowired` 和 `@Resource` 有什么区别？
- 一个接口多个实现，`@Autowired` 怎么选？注入失败报什么错？
- `@Value` 和 `@ConfigurationProperties` 有什么区别？
- `@Bean` 和 `@Component` 有什么区别？
- `@Configuration(proxyBeanMethods = false)` 是什么意思？
- `@PostConstruct` 在 JDK 11 / Spring Boot 3 里有什么变化？
- `@Transactional` 标在类上和标在方法上哪个优先？
:::

:::答案
**分组全表（按这四组记，面试能一口气报出来）**

| 组 | 注解 | 作用 | 关键点 |
|---|---|---|---|
| **声明 Bean** | `@Component` | 通用组件 | 所有派生注解的基础 |
| | `@Service` / `@Repository` / `@Controller` / `@RestController` | 语义化派生 | `@Repository` 会**自动转换 DAO 层的持久化异常**为 `DataAccessException` |
| | `@Configuration` | 配置类 | 内含 `@Component` |
| | `@Bean` | 方法级注册 Bean | 方法名 = BeanName，返回值类型 = Bean 类型 |
| | `@ComponentScan` | 扫描包 | `basePackages` / `excludeFilters`（Boot 默认扫主类所在包及子包） |
| | `@Import` / `@ImportResource` | 导入配置类 / XML | `@Import` 是自动配置的核心（第 11 题） |
| **注入依赖** | `@Autowired` | 按类型注入 | Spring 提供，`required=true` 默认 |
| | `@Qualifier` | 指定 Bean 名 | 在集合注入时变成**筛选器** |
| | `@Resource` | 按名称注入 | JSR-250，默认用字段名 |
| | `@Inject` | 按类型注入 | JSR-330，需额外依赖 |
| | `@Value` | 注入单个配置值 | 支持 `${}` 和 `#{}` |
| | `@Primary` | 同类型多候选时优先 | 优先级低于 `@Qualifier` |
| **配置相关** | `@ConfigurationProperties` | 绑定一组配置 | 支持松散绑定、类型安全、JSR303 校验 |
| | `@EnableConfigurationProperties` | 显式启用某个 Properties 类 | 不标 `@Component` 时用 |
| | `@PropertySource` | 加载额外配置文件 | Boot 里一般用不上（有 profile 机制） |
| | `@Profile` | 按环境生效 | `@Profile("prod")` / `@Profile("!test")` |
| **能力 / 生命周期** | `@Transactional` | 事务 | 见第 7 题 |
| | `@Async` | 异步执行 | 需 `@EnableAsync`；**不能跨线程传事务/MDC** |
| | `@Cacheable` / `@CacheEvict` / `@CachePut` | 缓存 | 需 `@EnableCaching` |
| | `@Scheduled` | 定时任务 | 需 `@EnableScheduling`；**默认单线程**，多个任务会互相阻塞 |
| | `@PostConstruct` / `@PreDestroy` | 生命周期回调 | 见第 3 题 |
| | `@Scope` | 作用域 | `singleton`（默认）/ `prototype` / `request` / `session` / `application` |
| | `@Lazy` | 延迟初始化 | 标在注入点可打断循环依赖 |
| **Web 层** | `@RequestMapping` 及 `@GetMapping` 等 | URL 映射 | `@GetMapping` = `@RequestMapping(method=GET)` |
| | `@RequestBody` / `@ResponseBody` | 请求体 / 响应体 | 走 `HttpMessageConverter` |
| | `@RequestParam` / `@PathVariable` / `@RequestHeader` | 参数绑定 | `required` 默认 true（除 `@PathVariable` 视版本） |
| | `@Valid` / `@Validated` | 参数校验 | `@Valid` 是 JSR-303，`@Validated` 是 Spring 的（支持分组） |
| | `@ControllerAdvice` / `@RestControllerAdvice` | 全局增强 | 全局异常、全局数据绑定、全局参数预处理 |
| **AOP** | `@Aspect` / `@Pointcut` / `@Around` 等 | 切面 | 见第 5 题 |

**`@Component` 的派生根（被追问「`@Service` 和 `@Component` 有什么区别」）**

```java
@Target(ElementType.TYPE)
@Retention(RetentionPolicy.RUNTIME)
@Component                    // ← 派生：本身就是一个 @Component
public @interface Service {
    @AliasFor(annotation = Component.class)   // ← value 属性"别名"到 @Component 的 value
    String value() default "";
}
```

**结论**：功能上完全等价（都只是被 `ClassPathBeanDefinitionScanner` 扫到），**区别只有语义**——`@Service` 表业务层、`@Repository` 表 DAO 层（**额外带异常转换**）、`@Controller` 表 Web 层。`@AliasFor` 是 Spring 的元注解「属性别名」机制，`@SpringBootApplication` 的 `scanBasePackages` 就是这样别名到 `@ComponentScan` 的。

**`@Autowired` vs `@Resource` vs `@Inject`（高频对比）**

| | `@Autowired` | `@Resource` | `@Inject` |
|---|---|---|---|
| 来源 | Spring | **JSR-250**（JDK 早期自带） | JSR-330 |
| 匹配方式 | **按类型** → 多候选时按名称 | **按名称**（字段名/属性名）→ 找不到再按类型 | 按类型 |
| 能否指定名字 | 要配 `@Qualifier` | `@Resource(name="xxx")` 一个属性搞定 | 要配 `@Named` |
| `required` | 有（`required=false`） | 无（必须存在） | 无（用 `Provider<T>` 延迟） |
| 支持位置 | 构造器 / Setter / 字段 / 参数 | 字段 / Setter | 构造器 / Setter / 字段 |
| 配合 `@Primary` | ✅ | ❌（先按名，名字不匹配就换类型找） | ✅ |

**记忆口诀**：**`@Autowired` 先看类型，`@Resource` 先看名字。**

**`@Autowired` 多候选的裁决顺序（源码链路，`DefaultListableBeanFactory.determineAutowireCandidate`）**

```
1. @Qualifier 显式指定 → 直接命中
2. @Primary 标记的 Bean → 命中
3. @Priority / Ordered 优先级最高的 → 命中
4. 字段名 / 参数名 == BeanName → 命中
5. 都不行 → NoUniqueBeanDefinitionException
   （提示：expected single matching bean but found 2: aaaService, bbbService）
```

**没有候选时报错**：`required=true`（默认）→ `NoSuchBeanDefinitionException`；`required=false` → 注入 null。

**报错速查**

| 异常 | 含义 | 处置 |
|---|---|---|
| `NoSuchBeanDefinitionException` | 找不到候选 | 类没被扫到（包路径不对）/ `@Component` 漏了 / 自动配置没生效 |
| `NoUniqueBeanDefinitionException` | 找到多个 | 加 `@Qualifier` 或 `@Primary`；或改成 `Map<String, T>` 注入 |
| `BeanCurrentlyInCreationException` | 循环依赖 | 见第 4 题 |
| `BeanDefinitionOverrideException` | Bean 重名（Boot 2.1+ 默认禁止覆盖） | 改名，或开 `spring.main.allow-bean-definition-overriding=true` |

**`@Value` vs `@ConfigurationProperties`**

| | `@Value("${a.b.c}")` | `@ConfigurationProperties(prefix="a.b")` |
|---|---|---|
| 注入粒度 | 单个字段 | 一组字段（整个类） |
| **松散绑定** | ❌ 必须**严格**写 `a.b.c`（`a.b-c` 不行） | ✅ `a.b.c` / `a.b-c` / `A_B_C` / 环境变量 `A_B_C` 都能绑 |
| 复杂类型 | 只能靠 SpEL 拼（`#{'${list}'.split(',')}`） | ✅ List / Map / 嵌套对象原生支持 |
| JSR-303 校验 | ❌ | ✅ `@Validated` + `@NotBlank` |
| 元数据提示 | ❌ | ✅（配 `spring-boot-configuration-processor` 后 IDE 有自动补全） |
| 适用 | 零散的一两个值 | 一组结构化配置（强烈推荐） |

**「松散绑定」这个词一定要说出来**，它是 `@ConfigurationProperties` 最大的价值——`application.yml` 里写 `my-app.max-conn`，环境变量里写 `MY_APP_MAXCONN`，都能绑到同一个字段。

```java
@Data
@Component
@ConfigurationProperties(prefix = "order")
@Validated                                     // ★ 开启 JSR-303 校验
public class OrderProperties {
    @NotBlank
    private String topic;                      // order.topic
    private int    timeoutSeconds = 30;        // order.timeout-seconds / ORDER_TIMEOUTSECONDS
    private List<String> channels;             // order.channels[0], order.channels[1]
    private Retry retry = new Retry();         // 嵌套对象 order.retry.*

    @Data
    public static class Retry {
        private int maxAttempts = 3;           // order.retry.max-attempts
        private long backoffMs = 200;
    }
}
```

```yaml
order:
  topic: order-created
  timeout-seconds: 60
  channels: [sms, email]
  retry:
    max-attempts: 5
```

**`@Bean` vs `@Component`（被追问「什么时候用哪个」）**

| | `@Component`（含派生） | `@Bean` |
|---|---|---|
| 作用对象 | **类**（自己写的类） | **方法**（第三方库的类） |
| 生效方式 | 组件扫描 | 配置类里的方法被调用 |
| BeanName | 类名首字母小写 | **方法名** |
| 能做条件装配 | 类上可以 | 方法上可以（`@ConditionalOnMissingBean` 常用） |
| 典型场景 | 自己的 Service/DAO | `RedisTemplate`、`DataSource`、`ThreadPoolExecutor`、`RestTemplate` |

**一句话**：**自己写的类用 `@Component`，第三方库的类用 `@Bean`。**

**`@Configuration(proxyBeanMethods = true/false)` —— 这个点答出来很加分**

```java
@Configuration                          // 默认 proxyBeanMethods = true（full 模式）
public class AppConfig {
    @Bean
    public A a() { return new A(); }

    @Bean
    public B b() { return new B(a()); }   // ★ 这里 a() 被 CGLIB 拦截了，返回的是容器里的那个单例
}
```

| | `proxyBeanMethods = true`（full） | `proxyBeanMethods = false`（lite） |
|---|---|---|
| 是否 CGLIB 增强配置类 | 是（生成 `AppConfig$$EnhancerBySpringCGLIB`） | 否 |
| `a()` 直接调用返回什么 | **容器里的单例**（方法被拦截，走 `getBean`） | **每次都 new 一个新对象** |
| 能否保证单例 | ✅ | ❌（要靠方法参数注入） |
| 启动开销 | 有（生成配置类的代理） | 无 |
| 用法 | 需要互相调用 `@Bean` 方法时 | 不互相调用时（推荐，尤其自动配置类） |

**lite 模式下的正确写法**：

```java
@Configuration(proxyBeanMethods = false)
public class AppConfig {
    @Bean
    public A a() { return new A(); }

    @Bean
    public B b(A a) { return new B(a); }   // ★ 用方法参数注入，而不是调 a()
}
```

**SpringBoot 的自动配置类全部用 `proxyBeanMethods = false`**（Boot 2.2 起），就是为了避免生成一堆配置类代理、加快启动。**这是「Boot 启动优化」的一个具体抓手。**

**`@PostConstruct` 的坐标变化（版本题）**

| 环境 | 坐标 |
|---|---|
| JDK 8 | `javax.annotation.PostConstruct`（JDK 自带） |
| **JDK 11+** | `javax.annotation` 从 JDK 移除（JEP 320）→ 需要引入 `javax.annotation-api` 或 `jakarta.annotation-api` |
| Spring Boot 2.x | 自带 `jakarta.annotation-api`（但包名仍是 `javax.*`） |
| **Spring Boot 3.x / JDK 17+** | 包名变成 **`jakarta.annotation.*`** |

**所以从 Boot 2 升到 3，所有 `javax.*` 的 import 都要改成 `jakarta.*`**（servlet、annotation、persistence、validation 都是）。这个改动量是升级 Boot 3 最大的成本之一——面试里说出来很能体现「你知道升级的代价在哪」。

**其他几个值得单独记的注解坑**

| 注解 | 坑 |
|---|---|
| `@Async` | 同类自调用不生效（同 AOP 失效原理）；**默认线程池** `SimpleAsyncTaskExecutor` **每次新建线程**，生产必须自定义 `ThreadPoolTaskExecutor` |
| `@Scheduled` | 默认**单线程**调度器，一个任务慢会阻塞其他任务 → 要配 `ThreadPoolTaskScheduler` 或 `spring.task.scheduling.pool.size` |
| `@Cacheable` | **自调用不生效**；key 默认是方法参数，多参数要显式写 `key = "#id + ':' + #type"`；`unless` 控制不缓存的条件 |
| `@Valid` vs `@Validated` | `@Valid` 支持嵌套对象校验，`@Validated` 支持**分组校验**（`@GroupSequence`），不能混用 |
| `@Transactional` 类级 vs 方法级 | 方法级优先 |
:::

:::拓展
**自定义组合注解（元注解的实战用法）**

```java
@Target(ElementType.TYPE)
@Retention(RetentionPolicy.RUNTIME)
@Documented
@RestController                                    // 组合了 @RestController
@RequestMapping("/api/v1")                         // 统一前缀
public @interface ApiV1Controller {
    @AliasFor(annotation = RequestMapping.class, attribute = "value")
    String[] value() default {};
}

// 使用：一行顶三行
@ApiV1Controller("/orders")
public class OrderController {
    @GetMapping("/{id}")
    public Order get(@PathVariable Long id) { ... }   // → /api/v1/orders/{id}
}
```

`@AliasFor` 是组合注解的关键：它让自定义注解的属性**透传**到被组合的元注解上。**SpringBoot 的 `@SpringBootApplication` 就是这么写的**（`scanBasePackages` 别名到 `@ComponentScan`，`exclude` 别名到 `@EnableAutoConfiguration`）。

**`@Scope` 与代理模式（单例注入 request 作用域的经典问题）**

```java
@Component
@Scope(value = WebApplicationContext.SCOPE_REQUEST, proxyMode = ScopedProxyMode.TARGET_CLASS)
public class RequestContext {
    private String userId;      // 每个请求独立的上下文
}
```

**为什么必须加 `proxyMode`**：单例 Bean 在启动时创建，而 request 作用域的 Bean 在请求到达时才有 —— 直接注入一个单例，容器启动时拿不到它。`proxyMode` 让注入的是个代理，**每次调用方法时才去容器里取当前请求对应的实例**。这就是「作用域代理」。

**注解的匹配与合并（`MergedAnnotations`，了解一下就够）**

Spring 5.2 起用 `MergedAnnotations` 统一处理「注解继承 + 元注解 + `@AliasFor`」。常见现象：**注解可以继承吗？** 类上的注解不会被继承（`@Inherited` 只对类生效且不跨接口），接口上的注解在有代理时也可能看不到（见第 7 题第 8 条）。**所以注解一律写在实现类上，这是最保险的规范。**
:::

:::追问
**Q：`@Autowired` 能注入静态字段吗？**
不能。`AutowiredAnnotationBeanPostProcessor` 处理的是**实例**的 `InjectionMetadata`，静态字段不属于实例。要用静态字段，只能通过 `@PostConstruct` 里的 setter 赋值，或者实现 `ApplicationContextAware` 手动 `getBean`（不推荐，等于把容器当全局变量）。**面试里被问到这个，答「技术上不支持，设计上也不建议——静态字段绕开了容器的生命周期管理」就够。**

**Q：`@Qualifier` 在集合注入时行为为什么不一样？**
当注入目标是 `Map`/`List` 时，`@Qualifier` 从「选择器」变成「过滤器」——Spring 会用 `@Qualifier` 的值去匹配**每个候选 Bean 上的同名 `@Qualifier` 注解**，只保留匹配的。这个行为在 `DefaultListableBeanFactory#findAutowireCandidates` 里通过 `QualifierAnnotationAutowireCandidateResolver` 实现。用法：给同组实现标同一个 `@Qualifier("pay")`，注入时字段上也标 `@Qualifier("pay")` → 只注入这一组。

**Q：`@Repository` 的「异常转换」具体是什么？**
Spring 用 `PersistenceExceptionTranslationPostProcessor` 给 `@Repository` 的 Bean 生成代理，把各个持久化框架的原生异常（`SQLException`、`MongoException`、`JpaSystemException`）统一转换成 Spring 的 `DataAccessException` 体系（`DuplicateKeyException`、`DataIntegrityViolationException` 等）。**好处是上层代码不用关心底层用的是 MySQL 还是 MongoDB**——这正好是你 MongoDB 背景能聊的点。

**Q：`@Profile` 和 `@ConditionalOnProperty` 有什么区别？**
`@Profile` 是按 `spring.profiles.active` 激活（粗粒度，一套一套切）；`@ConditionalOnProperty` 是按某个具体配置项的值（细粒度，逐个开关）。`@Profile` 内部就是用 `@Conditional` 实现的（`ProfileCondition`）。**组合用法：`@Profile("!test")` 表示非 test 环境才生效。**
:::

:::锚点
**这道题用一个真实的技术对照来讲 —— MongoDB 的 `@Repository` 异常转换：**

> 「`@Repository` 会把底层持久化异常统一转换成 Spring 的 `DataAccessException` 体系。这个设计我特别有共鸣，因为**我们 RRM 那边用的是 MongoDB**（clbDetail / optHistory / autoSwitch / autoOptConfig，还有 `{taskId, apSN, RI}` 这个复合索引），MongoDB 的异常体系和 MySQL 完全不一样（`DuplicateKeyException` 是 `MongoWriteException` 的 code 11000）。**如果没有这层统一抽象，上层业务代码就得为每种存储写一套异常处理。** 所以我理解 Spring 数据访问这层抽象的价值：**不是省代码，是把「存储差异」隔离在边界内。**」

**再加一句关于 AI 编程助手 + 注解的观察（真实的，且很讨巧）**：

> 「我们组现在用 CodeBuddy 这类 AI agent 生成/改代码，我负责 review 后提交。**review AI 生成的 Spring 代码时，我盯得最紧的就是注解**——AI 很容易写出『`@Transactional` 加在 private 方法上』『`@Async` 同类自调用』这种看起来对、实际失效的代码，因为它对注解的语义边界理解是概率性的。我推进的那个集成 Sonar 的静态分析助手，一个重点方向就是把这类『注解语义 → 实际行为』的规则做成可检查的规则。**这也倒逼我把每个注解的生效条件弄清楚——不是背用法，而是知道它在什么条件下会静默失效。**」

**为什么这两段都成立**：MongoDB 的集合名、索引、`{taskId, apSN, RI}` 都是真实事实；AI agent + Sonar 项目也是真实的。**注意措辞用的是「我理解/我盯得紧」而不是「我在 Java 项目里这么干过」，没有编造。**
:::

---

## 10. MyBatis：`#{}` 与 `${}`、Mapper 代理、缓存、插件 ★

:::概念
MyBatis 是**半自动 ORM**：SQL 你写，参数映射和结果映射它做。
**`#{}` → `PreparedStatement` 的 `?` 占位符（预编译，参数作为数据，防注入）；`${}` → 字符串直接拼接（参数参与 SQL 语法解析，有注入风险）。**
Mapper 接口没有实现类也能注入，是因为 MyBatis 用 **JDK 动态代理** 生成了 `MapperProxy`——**这跟 Spring AOP 默认 CGLIB 恰好是反面案例。**
:::

:::提问
- MyBatis 和 JDBC、Hibernate/JPA 有什么区别？
- `#{}` 和 `${}` 的区别？为什么 `#{}` 能防注入？
- Mapper 接口没有实现类，为什么能注入？
- MyBatis 的一级缓存和二级缓存有什么区别？为什么生产不建议开二级缓存？
- `<foreach>` 的 `collection` 属性怎么填？
- MyBatis 的插件是怎么实现的？能拦截哪些对象？
- 报 `Invalid bound statement (not found)` 是什么原因？
- MyBatis-Plus 和 MyBatis 什么关系？
:::

:::答案
**三种数据访问方案对比**

| | JDBC | MyBatis | JPA/Hibernate |
|---|---|---|---|
| SQL 控制 | 手写，完全可控 | **手写**，完全可控 | 框架生成，复杂 SQL 难控 |
| 映射 | 手工 `rs.getXxx()` | XML/注解配置映射 | 注解自动映射 |
| 上手成本 | 低但啰嗦 | 中 | 高（要懂 Session/脏检查/懒加载） |
| 优化空间 | 最大 | 大 | 中（要会看生成的 SQL） |
| 适合 | 教学/极简 | **国内主流**：复杂查询多、要精细优化 | 简单 CRUD 多的业务系统 |

**`#{}` vs `${}` 的底层差异（必须讲到编译层面）**

```
#{name}
  → 生成 SQL: WHERE name = ?
  → 走 PreparedStatement
  → DefaultParameterHandler.setParameters() 用 TypeHandler 把参数设进 PreparedStatement
  → ★ 参数在"数据库编译 SQL 之后"才填入 → 参数内容永远不能被当成 SQL 语法

${col}
  → 生成 SQL: WHERE name = '张三'   （直接拼进去）
  → 走 Statement（没有预编译）
  → ★ 参数参与 SQL 语法解析 → 参数里的 ' OR '1'='1 就成了 SQL 的一部分
```

**为什么 `#{}` 能防注入（一句话原理）**：`PreparedStatement` 的 SQL 结构在**预编译时就固定了**，参数是通过协议单独传输并按类型绑定到占位符上的，**数据库不会把参数内容再当语法解析一次**。所以参数里写什么都不可能改变 SQL 结构。

**反例演示**

```sql
-- #{} 的安全版本
SELECT * FROM orders WHERE name = #{name}
-- name 传 "x' OR '1'='1" → 参数被当作普通字符串 → 查不到东西

-- ${} 的危险版本
SELECT * FROM orders WHERE name = '${name}'
-- name 传 "x' OR '1'='1" → SQL 变成：
--   SELECT * FROM orders WHERE name = 'x' OR '1'='1'   → 全表数据泄露
```

**`${}` 必须有，但必须白名单**

```xml
<!-- ${} 唯一合理的用途：表名、排序字段、动态列名 —— 这些不能用 ? 占位符 -->
<select id="page" resultType="Order">
  SELECT * FROM ${tableName}
  ORDER BY ${sortField} ${sortOrder}
  LIMIT #{offset}, #{limit}
</select>
```

```java
// ★ 白名单校验（在 Service 层做，不能只靠前端）
private static final Set<String> ALLOWED_SORT = Set.of("id", "create_time", "amount");
private static final Set<String> ALLOWED_ORDER = Set.of("asc", "desc");

public void validate(String sortField, String sortOrder) {
    if (!ALLOWED_SORT.contains(sortField)) throw new BizException("非法排序字段");
    if (!ALLOWED_ORDER.contains(sortOrder.toLowerCase())) throw new BizException("非法排序方向");
}
```

**为什么不能用 `#{}` 传表名**：`?` 占位符只能替换**值**，不能替换**标识符**（表名、列名、关键字）。这是 JDBC 规范的硬限制，不是 MyBatis 的问题。

**Mapper 接口为什么能注入（完整链路，必背）**

```
① 启动扫描
   @MapperScan("com.example.mapper") → @Import(MapperScannerRegistrar)
   → MapperScannerConfigurer → ClassPathMapperScanner.doScan()
   → 把每个接口注册成一个 BeanDefinition
   → ★ 关键：beanClass 被替换成 MapperFactoryBean，并设置
        constructorArgumentValues: 原始接口类型
        propertyValues: sqlSessionFactory / sqlSessionTemplate

② 注入时
   getBean("orderMapper") → MapperFactoryBean.getObject()
   → SqlSessionTemplate.getMapper(OrderMapper.class)
   → Configuration.getMapper(...) → MapperRegistry.getMapper(...)
   → MapperProxyFactory.newInstance(mapperProxy)
   → ★ Proxy.newProxyInstance(...)  ← JDK 动态代理，因为目标一定是接口

③ 调用时
   orderMapper.selectById(1L)
   → MapperProxy.invoke(proxy, method, args)
   → 生成 MethodSignature（判断方法类型：SELECT/INSERT/UPDATE/DELETE/FLUSH）
   → MapperMethod.execute(sqlSession, args)
        → SqlSessionTemplate（线程安全，内部委托给 DefaultSqlSession）
        → Executor.query(...) → PreparedStatementHandler → JDBC → 结果集映射
```

**三个可以讲出来的细节**

1. **Mapper 必须是接口** → 只能 JDK 动态代理。这是 Spring AOP 默认走 CGLIB 的**反面案例**，能同时讲清「为什么 JDK 代理和 CGLIB 各有存在价值」。
2. **`SqlSessionTemplate` 是线程安全的**，`DefaultSqlSession` 不是——所以 MyBatis-Spring 用 `SqlSessionTemplate` 包了一层（内部用代理 + `SqlSessionUtils` 从 `TransactionSynchronizationManager` 取当前线程的 SqlSession）。
3. **和 Spring 事务共享连接**：`SqlSessionUtils.getSqlSession()` 会先查 `TransactionSynchronizationManager.getResource(sqlSessionFactory)`，有就复用 → **所以 MyBatis 的多个 SQL 能在同一个 Spring 事务里**。这就是第 7 题第 ④ 步的另一半。

**一级缓存 vs 二级缓存**

| | 一级缓存 | 二级缓存 |
|---|---|---|
| 作用域 | **SqlSession**（同一个会话内） | **namespace**（同一个 Mapper，跨 SqlSession） |
| 默认开关 | **默认开启**，关不掉（只能改 scope） | **默认关闭**，要 `<cache/>` 或 `@CacheNamespace` 显式开 |
| 底层 | `BaseExecutor.localCache`（`PerpetualCache`，就是个 HashMap） | `CachingExecutor` → `TransactionalCacheManager` → `PerpetualCache` |
| key | `CacheKey`：`statementId + offset + limit + sql + 参数` | 同左（加上 namespace） |
| 失效条件 | 同一个 SqlSession 内执行 **update/insert/delete**、`commit()`、`rollback()`、`clearCache()` | 该 namespace 内有写操作时清空 |
| 与 Spring 集成 | 每个请求一个 SqlSession → **作用范围基本就是一次请求内** | 跨请求生效（但**必须在同一个 JVM 内**） |
| 生产建议 | 开着，无害 | **不要开**（原因见下） |

**为什么生产不建议开二级缓存（三条硬理由）**

1. **脏读**：缓存按 namespace 隔离。`OrderMapper` 和 `OrderItemMapper` 都查了同一张表，`OrderItemMapper` 的写操作**不会清 `OrderMapper` 的缓存** → 读到旧数据。
2. **必须 `Serializable`**：二级缓存可能被写到磁盘（`TransactionalCache` 的 `flushCacheIfRequired`），要求对象可序列化 → 多一层序列化开销，还容易漏。
3. **分布式失效困难**：默认是**本地缓存**（`PerpetualCache` + `HashMap`）。多实例部署时实例 A 更新了库，实例 B 的二级缓存还在 → 脏数据。要解决就得换成 `RedisCache` 或开 `cache-ref`，复杂度陡增。

**结论**：**要缓存就用 Redis 显式做**（可控、能设 TTL、能主动失效），别指望 MyBatis 的二级缓存。**「二级缓存不该开」这个观点比背它的定义有价值。**

**动态 SQL 与 `<foreach>`（`collection` 属性最容易错）**

```xml
<!-- 批量插入：collection 怎么填见下面的表 -->
<insert id="batchInsert">
  INSERT INTO clb_detail (task_id, ap_sn, ri, value) VALUES
  <foreach collection="list" item="it" separator=",">
    (#{it.taskId}, #{it.apSn}, #{it.ri}, #{it.value})
  </foreach>
</insert>

<!-- IN 查询 -->
<select id="findByIds" resultType="ClbDetail">
  SELECT * FROM clb_detail WHERE id IN
  <foreach collection="ids" item="id" open="(" close=")" separator=",">
    #{id}
  </foreach>
</select>

<!-- 动态更新：用 <set> 自动去掉末尾逗号 -->
<update id="updateSelective">
  UPDATE clb_detail
  <set>
    <if test="value != null">value = #{value},</if>
    <if test="status != null">status = #{status},</if>
  </set>
  WHERE id = #{id}
</update>

<!-- 条件拼接：用 <where> 自动处理开头的 AND -->
<select id="search" resultType="ClbDetail">
  SELECT * FROM clb_detail
  <where>
    <if test="taskId != null">AND task_id = #{taskId}</if>
    <if test="apSn != null">AND ap_sn = #{apSn}</if>
  </where>
</select>
```

| `collection` 的值 | 场景 |
|---|---|
| `list` | 参数是 `List`，**没有 `@Param`** 时固定写 `list` |
| `array` | 参数是数组，**没有 `@Param`** 时固定写 `array` |
| **`@Param` 指定的名字** | 方法签名上有 `@Param("ids")` → 写 `ids`（**推荐，永远显式加 `@Param`**） |
| Map 的 key | 参数是 `Map` → 写对应的 key 名 |

**`<foreach>` 的性能坑**：`IN (?, ?, ?, ...)` 的占位符数量受数据库限制（MySQL `max_allowed_packet` 和预处理语句参数上限 65535）。**列表超过 1000 个元素时建议分批（每批 500~1000）**，否则容易报错或 SQL 解析变慢。

**MyBatis 插件（拦截器）**

```java
@Intercepts({
    @Signature(type = Executor.class, method = "query",
               args = {MappedStatement.class, Object.class, RowBounds.class, ResultHandler.class})
})
@Component
public class SqlCostInterceptor implements Interceptor {
    @Override
    public Object intercept(Invocation invocation) throws Throwable {
        long start = System.currentTimeMillis();
        try {
            return invocation.proceed();
        } finally {
            long cost = System.currentTimeMillis() - start;
            if (cost > 1000) {                       // 慢 SQL 阈值 1s
                MappedStatement ms = (MappedStatement) invocation.getArgs()[0];
                log.warn("slow sql: {} cost={}ms", ms.getId(), cost);
            }
        }
    }
}
```

**能拦截的四类对象**（记住这 4 个 + 能拦截的方法，被追问时能报出来）：

| 拦截对象 | 能拦截的方法 | 典型用途 |
|---|---|---|
| `Executor` | `update` / `query` / `flushStatements` / `commit` / `rollback` | **分页插件（PageHelper 在这里）**、SQL 耗时统计 |
| `StatementHandler` | `prepare` / `parameterize` / `batch` / `update` / `query` | SQL 改写（如强制加 `LIMIT`）、多租户加条件 |
| `ParameterHandler` | `getParameterObject` / `setParameters` | 参数加解密 |
| `ResultSetHandler` | `handleResultSets` / `handleOutputParameters` | **结果字段解密/脱敏**、字段类型转换 |

**插件链是层层包装的**：`Configuration` 里按注册顺序把 `Interceptor` 包成 `InterceptorChain`，`newExecutor` 时用 `interceptorChain.pluginAll(executor)` 逐层代理。

**`Invalid bound statement (not found)` 的 6 个原因（排障必备）**

1. **XML 没被打进包**：Maven 默认只打包 `src/main/java` 下的 `.java`，放在 `src/main/java/com/x/mapper/OrderMapper.xml` 的 XML 会被忽略 → 在 `pom.xml` 里加 `resources` 配置，或把 XML 放到 `src/main/resources/mapper/`
2. **`mapper-locations` 没配**或路径不对：`mybatis.mapper-locations=classpath:mapper/*.xml`
3. **namespace 写错**：必须与 Mapper 接口全限定名完全一致
4. **`<select id="xxx">` 与接口方法名不一致**（大小写敏感）
5. **接口上没加 `@Mapper`，也没配 `@MapperScan`** → 整个接口没被注册
6. **同名方法重载**：MyBatis 不支持 Mapper 方法重载（statementId 会冲突）

```yaml
mybatis:
  mapper-locations: classpath:mapper/**/*.xml      # ★ 生产必配
  type-aliases-package: com.example.domain
  configuration:
    map-underscore-to-camel-case: true             # ap_sn → apSn（默认 false！）
    default-statement-timeout: 30                  # SQL 超时 30s
    log-impl: org.apache.ibatis.logging.stdout.StdOutImpl   # 打印 SQL（仅开发）
```

**`map-underscore-to-camel-case` 默认是 `false`** —— 这是新手第一个坑：数据库 `ap_sn` 映射不到 Java 的 `apSn`，字段全是 null。**MyBatis-Plus 的默认值也是 false，但 SpringBoot 的 `mybatis-plus.configuration.map-underscore-to-camel-case` 在 `mybatis-plus-boot-starter` 里默认是 `true`** —— 这个差异很容易让人困惑。

**MyBatis-Plus 对照表**

| 能力 | 原生 MyBatis | MyBatis-Plus |
|---|---|---|
| 基础 CRUD | 每个方法写 XML | `BaseMapper<T>` 自带 `insert/selectById/updateById/deleteById` |
| 条件构造 | 手写 `WHERE` | `LambdaQueryWrapper<T>` 链式调用，**类型安全**（`Order::getStatus`） |
| 分页 | 自己写 `LIMIT` + 写 count 语句 | `MybatisPlusInterceptor` + `PaginationInnerInterceptor`，**自动拼 count** |
| 逻辑删除 | 手写 `WHERE deleted = 0` | `@TableLogic` + 全局配置 |
| 自动填充 | 手写 | `MetaObjectHandler`（`createTime`/`updateTime`） |
| 乐观锁 | 手写 version 判断 | `@Version` + `OptimisticLockerInnerInterceptor` |

```java
// MP 的分页配置（3.4+ 用 MybatisPlusInterceptor 替代了老的 PaginationInterceptor）
@Configuration
public class MybatisPlusConfig {
    @Bean
    public MybatisPlusInterceptor mybatisPlusInterceptor() {
        MybatisPlusInterceptor interceptor = new MybatisPlusInterceptor();
        interceptor.addInnerInterceptor(new PaginationInnerInterceptor(DbType.MYSQL));
        interceptor.addInnerInterceptor(new OptimisticLockerInnerInterceptor());
        interceptor.addInnerInterceptor(new BlockAttackInnerInterceptor());  // 禁止全表更新/删除
        return interceptor;
    }
}
```

```java
// Lambda 条件构造（推荐，编译期能发现字段名写错）
LambdaQueryWrapper<ClbDetail> qw = new LambdaQueryWrapper<ClbDetail>()
        .eq(ClbDetail::getTaskId, taskId)
        .eq(ClbDetail::getApSn, apSn)
        .eq(ClbDetail::getRi, ri)              // 正好命中复合索引 {taskId, apSN, RI}
        .orderByDesc(ClbDetail::getCreateTime);

Page<ClbDetail> page = clbDetailMapper.selectPage(new Page<>(1, 20), qw);
```

**`BatchInterceptor` 那条 `BlockAttackInnerInterceptor` 值得单独讲**：它能拦住「没有 WHERE 条件的 update/delete」——**这是线上最恐怖的事故类型之一**（`UPDATE user SET status = 0` 忘了 WHERE）。
:::

:::拓展
**`ExecutorType.BATCH` 与批量插入的三种方式**

| 方式 | 实现 | 适用 |
|---|---|---|
| `<foreach>` 拼一条大 INSERT | 一次性发一条大 SQL | **中小批量（几百到几千）最快** |
| `ExecutorType.BATCH` | JDBC `addBatch` / `executeBatch` | 大批量（万级），注意 **`flushStatements()` 和事务** |
| MP 的 `saveBatch` | 内部就是 `ExecutorType.BATCH` | 方便，默认每 1000 条 flush |

```java
// 原生 Batch 用法（注意：批量模式下的返回值可能不准，且必须 flush）
@Autowired private SqlSessionFactory sqlSessionFactory;

public void batchInsert(List<ClbDetail> list) {
    try (SqlSession session = sqlSessionFactory.openSession(ExecutorType.BATCH)) {
        ClbDetailMapper mapper = session.getMapper(ClbDetailMapper.class);
        for (int i = 0; i < list.size(); i++) {
            mapper.insert(list.get(i));
            if (i % 1000 == 999) { session.flushStatements(); }   // 分批 flush，防内存爆
        }
        session.flushStatements();
        session.commit();
    }
}
```

**`SELECT ... FOR UPDATE` 与 MyBatis 的配合**

```xml
<select id="lockById" resultType="Account">
  SELECT * FROM account WHERE id = #{id} FOR UPDATE
</select>
```

注意：**`FOR UPDATE` 必须在事务里才有意义**（`autocommit=true` 时加了锁立刻释放）。所以 `@Transactional` + `FOR UPDATE` 是配套出现的。另外要注意**加锁顺序**，多个事务以不同顺序锁多行会死锁。

**MyBatis 与多数据源的三个坑**

1. `@Transactional` 默认只用主数据源的事务管理器 → 从库操作不在同一事务里（实际上从库一般是只读，问题不大）
2. `dynamic-datasource-spring-boot-starter` 的 `@DS` 切面 order 必须**高于**事务切面，否则数据源在事务开始后才切，等于没切
3. 多数据源下的 MyBatis 配置要**一个个写**（每个数据源一套 `SqlSessionFactory`），不能只写一份全局配置

**和 MongoDB 的对照（你的强项接口）**

| | MySQL + MyBatis | MongoDB（你们 RRM 用的） |
|---|---|---|
| 事务 | 一条 SQL 天然原子，多 SQL 靠事务 | **单文档操作原子**，跨文档要显式事务（4.0+ 副本集） |
| 索引 | B+ 树，复合索引有**最左前缀**原则 | B 树，复合索引同样有最左前缀（`{taskId, apSN, RI}` 就要求查询带上 taskId） |
| 批量写 | `foreach` / `ExecutorType.BATCH` | `bulkWrite` / `insertMany(ordered=false)` |
| 慢查询定位 | `slow_query_log` + `EXPLAIN` | `db.setProfilingLevel(1, {slowms: 100})` + `explain("executionStats")` |
:::

:::追问
**Q：`#{}` 里的参数是怎么设进 `PreparedStatement` 的？**
`PreparedStatementHandler.parameterize()` → `DefaultParameterHandler.setParameters(ps)` → 遍历 `BoundSql` 里的 `ParameterMapping`，每个用对应的 `TypeHandler.setParameter(ps, i, value, jdbcType)` 调 `ps.setXxx(i, value, type)`。**注意：`DynamicSqlSource` 的 SQL 在运行时才拼好（`?` 的个数也是动态的），`RawSqlSource`（无动态标签）在启动时就编译好** —— 这是 MyBatis 性能上的一个小优化点。

**Q：`<if test="...">` 里为什么判断字符串要写 `!= ''`？**
OGNL 表达式对 `String` 和 `char` 的处理有个经典坑：`test="type == '1'"` 在 `type` 是 `String` 时会**把 `'1'` 当成 `char`** 比较，导致判断失败。正确写法：`test="type != null and type == '1'.toString()"` 或 `test="'1'.equals(type)"`。**这是真实踩过的坑，面试里说出来很加分。**

**Q：`useGeneratedKeys` 和 `keyProperty` 干什么？**
`<insert useGeneratedKeys="true" keyProperty="id">` 让 MyBatis 把自增主键写回实体对象的 `id` 字段（通过 `ps.getGeneratedKeys()`）。**注意：批量插入时只有部分数据库驱动支持把每个主键都回填，MySQL 只回填第一个** —— 需要拿到所有 id 的场景要循环插入或改用其他方案。

**Q：一级缓存为什么在 Spring 里「几乎没用」？**
因为 Spring 集成的模式是「一次请求/一个事务 = 一个 SqlSession」，请求结束后 SqlSession 关闭，缓存也就没了。**要真正命中一级缓存，得在同一个 SqlSession 内重复执行完全相同的查询**（同参数、同 SQL、同分页）——这种场景不多。**所以有人说「MyBatis 一级缓存没有存在的必要」是有道理的**：在没有事务的情况下，MyBatis-Spring 每次 `SqlSessionTemplate` 调用都可能开新的 SqlSession（`SqlSessionSynchronization` 只在事务中才绑定）。

**Q：`#{}` 里能写 `jdbcType` 吗？什么时候必须写？**
`#{name, jdbcType=VARCHAR}`。**Oracle 上必须写**：Oracle 驱动对 `null` 值如果不指定 `jdbcType` 会报 `Invalid column type`。MySQL 一般不用写。这是「你做的是 MySQL 还是 Oracle」这类问题的回答素材。
:::

:::锚点
**这道题是整本手册里你最好答的一题——因为索引和查询优化是你的真实战场。**

> 「MyBatis 的 `#{}` / `${}` 我理解得比较清楚，因为我平时查 MongoDB 也是同一套思路。**`${}` 就相当于把用户输入直接拼进查询条件里**，我们在 MongoDB 侧也会严格避免把外部值直接拼进 `$where` 或聚合管道——`$where` 能执行 JS，是最危险的操作符。所以『参数必须走绑定、不能参与语法解析』这个原则我是从另一个技术栈里带过来的。
>
> 索引这块我有真实经验：我们的 `clbDetail` 集合建了 `{taskId, apSN, RI}` 的复合索引，**查询时必须带上 `taskId` 才能走索引**（最左前缀原则）。这跟 MySQL 的复合索引是同一个规则，所以 MyBatis 里 `SELECT ... WHERE ap_sn = #{apSn}` 这种『跳过最左列』的查询会全表扫——**我看 EXPLAIN 的时候知道该看什么。**」

**再补一句「慢查询排查」的真实链路**（非常加分）：

> 「我们排查现网问题时，MongoDB 侧是开 `profiling` + `explain('executionStats')` 看有没有走索引、扫了多少文档；对应到 MySQL + MyBatis 就是 `slow_query_log` + `EXPLAIN` + 我在 MyBatis 插件里做的那个慢 SQL 拦截器打点。**工具不一样，但『先确认有没有走索引，再看扫描行数，最后看回表次数』这个顺序是完全一样的。**」

**为什么这么说能站住**：`clbDetail`、`{taskId, apSN, RI}` 复合索引都是你提供的真实事实；慢查询排查的**方法论**是你真实能力，只是换了个存储引擎表述。**零编造。**
:::

---

## 11. SpringBoot 自动配置原理 ★

:::概念
`@SpringBootApplication` = `@SpringBootConfiguration` + `@EnableAutoConfiguration` + `@ComponentScan`。
自动配置三步：**读候选清单（`.imports` / `spring.factories`）→ 用条件注解过滤 → 注册 BeanDefinition**。
最关键的一句话（必须答对）：**自动配置类是通过 `DeferredImportSelector` 延迟导入的，所以用户自己 `@ComponentScan` 扫到的 Bean 先注册，`@ConditionalOnMissingBean` 才判断得准 → 用户配置优先。**
:::

:::提问
- SpringBoot 自动配置的原理是什么？
- `@ConditionalOnClass` 和 `@ConditionalOnMissingBean` 分别在什么时机生效？
- 为什么用户自己定义的 Bean 能覆盖自动配置的 Bean？
- `@ConditionalOnClass` 引用了 classpath 上不存在的类，为什么不报 `NoClassDefFoundError`？
- Spring Boot 2.7 之后 `spring.factories` 有什么变化？
- 怎么关掉某个自动配置？怎么排查某个自动配置为什么没生效？
- 怎么自己写一个 starter？
:::

:::答案
**第一步：注解拆解**

```java
@SpringBootApplication
// 等价于下面三个注解：
@SpringBootConfiguration        // 本质是 @Configuration
@EnableAutoConfiguration        // ★ 自动配置的入口
@ComponentScan                  // 扫描主类所在包及子包
public @interface SpringBootApplication {
    @AliasFor(annotation = ComponentScan.class, attribute = "basePackages")
    String[] scanBasePackages() default {};
    @AliasFor(annotation = EnableAutoConfiguration.class, attribute = "exclude")
    Class<?>[] exclude() default {};
    // ...
}
```

```java
@Target(ElementType.TYPE)
@Retention(RetentionPolicy.RUNTIME)
@Import(AutoConfigurationImportSelector.class)          // ★ 核心
public @interface EnableAutoConfiguration { }
```

**第二步：完整链路（按这个顺序讲）**

```
① SpringApplication.run() → refreshContext() → refresh() → invokeBeanFactoryPostProcessors
   → ConfigurationClassPostProcessor.postProcessBeanDefinitionRegistry
   → ConfigurationClassParser.parse() 解析主配置类

② 解析到 @EnableAutoConfiguration → 里面有 @Import(AutoConfigurationImportSelector.class)

③ AutoConfigurationImportSelector 实现了 DeferredImportSelector
   → ★★ 它的 selectImports() 被推迟到"所有普通 @Import 和 @ComponentScan 都处理完之后"才执行
   → 这就是"用户 Bean 先注册、自动配置后注册"的根因

④ getAutoConfigurationEntry(annotationMetadata)
   ├─ getCandidateConfigurations()          读候选清单
   │    Boot ≤ 2.6: SpringFactoriesLoader.loadFactoryNames(
   │                   EnableAutoConfiguration.class, classLoader)
   │                → 读所有 jar 里的 META-INF/spring.factories
   │    Boot ≥ 2.7: ImportCandidates.load(AutoConfiguration.class, classLoader)
   │                → 读 META-INF/spring/org.springframework.boot.autoconfigure.AutoConfiguration.imports
   ├─ removeDuplicates()                    去重（合并多个 jar 的清单）
   ├─ getExclusions()                       处理 exclude / spring.autoconfigure.exclude
   ├─ fireAutoConfigurationImportEvents()   发事件
   └─ filter(configurations, metadata)      ★ 第一轮条件过滤（见下）

⑤ AutoConfigurationSorter 排序
   → @AutoConfigureOrder 显式指定
   → @AutoConfigureBefore / @AutoConfigureAfter 做拓扑排序
   → 剩下同级的按字母序

⑥ ConfigurationClassParser 把每个自动配置类当成普通配置类解析
   → 逐个 ConditionEvaluator.shouldSkip()  ★ 第二轮条件过滤（类级条件）
   → @Bean 方法上再评估一次（方法级条件）

⑦ ConfigurationClassBeanDefinitionReader.loadBeanDefinitions()
   → 注册 BeanDefinition（此时还没有任何 Bean 实例）
```

**两轮条件过滤的区别（这是这道题最深的一个点，答出来直接拉开差距）**

| 轮次 | 时机 | 谁在执行 | 怎么判断 | 影响 |
|---|---|---|---|---|
| **第一轮** | 读清单之后、排序之前 | `AutoConfigurationImportSelector.filter()` → `AutoConfigurationImportFilter`（`OnClassCondition` / `OnBeanCondition` / `OnWebApplicationCondition` 都实现了这个接口） | **`OnClassCondition` 用 ASM 读 `.class` 文件元数据（`SimpleMetadataReader`），不触发类加载** | 批量淘汰掉一大批不满足条件的自动配置类，**整个类根本不会被解析** |
| **第二轮** | 解析配置类、注册 BeanDefinition 时 | `ConditionEvaluator.shouldSkip()` → 具体的 `Condition` 实现 | `OnBeanCondition` 查 `BeanFactory` 里**已有的 `BeanDefinition`** | 决定这个配置类/`@Bean` 方法要不要注册 |

**`@ConditionalOnClass` 为什么不报 `NoClassDefFoundError`（必背结论）**

> `OnClassCondition` 的内部实现 `ClassNameFilter` 用 **ASM 字节码读取技术**（`SimpleMetadataReader`）解析 `.class` 文件的常量池，**只读字符串，不做类加载**（不调 `Class.forName`）。所以「这个类在不在 classpath 上」可以在**不初始化类**的前提下判断 —— 引用一个不存在的类不会触发 `NoClassDefFoundError`。
>
> 这也是**为什么 `@ConditionalOnClass` 的值可以写一个项目里根本没有的类**（比如写 `@ConditionalOnClass(name = "redis.clients.jedis.Jedis")`，没有 Jedis 依赖也不会崩）。

**第三: `@ConditionalOnMissingBean` 能生效的两个前提（一环扣一环）**

```
前提 1：DeferredImportSelector 延迟导入
   → 用户的 @ComponentScan 扫描结果先注册
   → 等自动配置类处理时，BeanFactory 里已经有用户的 BeanDefinition 了

前提 2：@ConditionalOnMissingBean 查的是 BeanDefinition，不是实例
   → 注册期就能判断，不需要等 Bean 实例化
   → 所以"用户配置优先"成立
```

**所以「为什么用户 Bean 能覆盖自动配置」的标准答案是**：
> **不是因为顺序上「后注册的覆盖先注册的」，而是因为自动配置类在注册前用 `@ConditionalOnMissingBean` 检查了一下「容器里是不是已经有同类型的 BeanDefinition 了」——发现有了，就整个 `@Bean` 方法跳过不注册。** 一个「让」的动作，而不是「覆盖」的动作。

**（补充）Bean 定义覆盖的默认行为**：Spring Boot 2.1 起，**同名 Bean 的定义覆盖默认被禁止**，会抛 `BeanDefinitionOverrideException`。所以「自动配置被覆盖」只能是靠 `@ConditionalOnMissingBean` 让位，不可能是同名的覆盖。

**三个常用条件注解的语义对照**

| 注解 | 判断什么 | 典型写法 |
|---|---|---|
| `@ConditionalOnClass` | classpath 上有没有这个类 | `@ConditionalOnClass(RedisOperations.class)` |
| `@ConditionalOnMissingClass` | classpath 上没有这个类 | 排除某些实现 |
| `@ConditionalOnBean` / `@ConditionalOnMissingBean` | 容器里有没有这个 Bean（**按类型**，可加 `name`） | `@ConditionalOnMissingBean(RedisTemplate.class)` |
| `@ConditionalOnProperty` | 配置项的值 | `@ConditionalOnProperty(prefix="spring.aop", name="proxy-target-class", havingValue="true", **matchIfMissing=true**)` |
| `@ConditionalOnWebApplication` | 是不是 Web 应用 | `@ConditionalOnWebApplication(type = Type.SERVLET)` |
| `@ConditionalOnResource` | 资源文件存不存在 | `@ConditionalOnResource(resources = "classpath:xxx.xml")` |
| `@ConditionalOnExpression` | SpEL 表达式 | 少用（性能差） |
| `@ConditionalOnSingleCandidate` | 恰好有一个候选 Bean | `@ConditionalOnSingleCandidate(DataSource.class)` |
| `@ConditionalOnJava` | JDK 版本 | `@ConditionalOnJava(range = Range.OLDER_THAN, value = JavaVersion.EIGHT)` |

**`@ConditionalOnProperty` 的两个必记细节**

1. **`matchIfMissing` 默认是 `false`** —— 不写就是「配置项必须存在且匹配才生效」
2. `havingValue` 不写时，判断的是「配置项存在且值不是 `false`」
3. 这三个细节组合起来就是第 5 题里 `spring.aop.proxy-target-class` 默认 CGLIB 的实现方式

**`@ConditionalOnMissingBean` 的一个硬限制（很容易被追问）**

```java
@Configuration(proxyBeanMethods = false)
public class MyAutoConfiguration {

    // ❌ 危险：如果另一个自动配置类（同样是自动配置）也定义了 DataSource，
    //    两者的注册顺序由 AutoConfigurationSorter 决定，@ConditionalOnMissingBean 的结果不确定
    @Bean
    @ConditionalOnMissingBean
    public DataSource dataSource() { ... }
}
```

**限制是**：`@ConditionalOnMissingBean` 只能看到**当前这个时刻已经注册的 BeanDefinition**。所以：
- **用户自己的 Bean 一定能看到**（`@ComponentScan` 和普通 `@Import` 先处理）✅
- **其他自动配置类的 Bean**：取决于 `@AutoConfigureBefore` / `@AutoConfigureAfter` 的排序 —— 没保证顺序时**结果不确定** ⚠️
- **运行时（`BeanDefinitionRegistryPostProcessor`）动态注册的 Bean**：看不到 ❌

**官方建议**：`@ConditionalOnMissingBean` 尽量配合 `name` 使用（`@ConditionalOnMissingBean(name = "myDataSource")`），或者在 `@Bean` 方法上把返回类型声明为**接口/抽象类**（判断依据是 `@Bean` 方法声明的返回类型，不是实例的真实类型）。

**版本变更：`spring.factories` → `AutoConfiguration.imports`**

| 版本 | 候选清单来源 | 说明 |
|---|---|---|
| Boot ≤ 2.6 | `META-INF/spring.factories` 里的 `org.springframework.boot.autoconfigure.EnableAutoConfiguration=...` | 一个文件放所有类型的扩展点（自动配置、监听器、初始化器…） |
| **Boot 2.7** | **`META-INF/spring/org.springframework.boot.autoconfigure.AutoConfiguration.imports`**（新）**+ `spring.factories`（兼容，两者都读）** | 过渡版本，旧的还能用但会打 deprecation 提示 |
| Boot 3.0 | **只读 `.imports`**，`spring.factories` 里的 `EnableAutoConfiguration` 键**彻底失效** | 老 starter 升 Boot 3 **必须**改文件名 |

**为什么要改**：`spring.factories` 把所有扩展点混在一个文件里（自动配置、`ApplicationContextInitializer`、`ApplicationListener`、`FailureAnalyzer`…），一是文件巨大难维护，二是**加载时要读全量再过滤**，性能也一般。拆成独立文件（`.imports` 每行一个类名）更快更清晰，而且 IDE 和构建工具更容易做静态分析。

**注意：`spring.factories` 并没有被完全废弃** —— `ApplicationContextInitializer`、`ApplicationListener`、`FailureAnalyzer`、`EnvironmentPostProcessor` 这些扩展点仍然用它。**只有 `EnableAutoConfiguration` 这一项被换掉了。**

**排查自动配置的三种方式**

```bash
# ① 启动加 --debug，输出条件评估报告（最全）
java -jar app.jar --debug
#   在 application.yml 里写 debug: true 效果一样
```

报告结构（能背出这个结构很加分）：

```
============================
CONDITIONS EVALUATION REPORT
============================

Positive matches:          ← 生效的自动配置 + 每个条件为什么通过
-----------------
   RedisAutoConfiguration matched:
      - @ConditionalOnClass found required class 'org.springframework.data.redis.core.RedisOperations'
      - @ConditionalOnMissingBean (types: ...) did not find any beans

Negative matches:          ← 没生效的自动配置 + 为什么没生效
-----------------
   RabbitAutoConfiguration:
      Did not match:
         - @ConditionalOnClass did not find required class 'com.rabbitmq.client.Channel'

Exclusions:                ← 被 exclude 掉的
Unconditional classes:     ← 没有条件的配置类
```

```bash
# ② Actuator 端点（生产环境）
curl localhost:8080/actuator/conditions | jq '.contexts."application".positiveMatches'
curl localhost:8080/actuator/beans      | jq            # 看所有 Bean 和它们的来源

# ③ 直接看某个 Bean 是谁注册的
#    在 conditions 报告里搜 BeanName，或者在 IDE 里给 Bean 定义打条件断点
```

**关闭某个自动配置的三种方式**

```java
// 方式 1：注解排除
@SpringBootApplication(exclude = {DataSourceAutoConfiguration.class})
public class App { }
```

```yaml
# 方式 2：配置文件排除（推荐，不用改代码）
spring:
  autoconfigure:
    exclude:
      - org.springframework.boot.autoconfigure.jdbc.DataSourceAutoConfiguration
      - org.springframework.boot.autoconfigure.security.servlet.SecurityAutoConfiguration
```

```yaml
# 方式 3：全局关掉所有自动配置（几乎不用）
spring:
  autoconfigure:
    exclude: "*"
```

**手写一个完整 starter（三件套，面试让你写能写出来）**

```java
// 1) 自动配置类
@AutoConfiguration                                  // Boot 2.7+ 专用注解（= @Configuration(proxyBeanMethods=false) + @AutoConfigureBefore/After 支持）
@ConditionalOnClass(SmsClient.class)                // 有 SmsClient 类才生效
@EnableConfigurationProperties(SmsProperties.class) // 绑定配置
public class SmsAutoConfiguration {

    @Bean
    @ConditionalOnMissingBean                       // ★ 用户自己配了就不用这个
    public SmsTemplate smsTemplate(SmsProperties props) {
        SmsTemplate t = new SmsTemplate();
        t.setEndpoint(props.getEndpoint());
        t.setTimeout(props.getTimeout());
        return t;
    }
}
```

```java
// 2) 配置属性类
@Data
@ConfigurationProperties(prefix = "sms")
public class SmsProperties {
    private String endpoint;
    private int timeout = 3000;
    private List<String> channels = new ArrayList<>();
}
```

```
// 3) 候选清单文件（路径和文件名一个字都不能错）
src/main/resources/META-INF/spring/
    org.springframework.boot.autoconfigure.AutoConfiguration.imports

// 文件内容就是一行一个类的全限定名：
com.example.sms.SmsAutoConfiguration
```

```xml
<!-- 4) 可选：加这个依赖，IDE 写 yml 时能自动补全，并生成 spring-configuration-metadata.json -->
<dependency>
  <groupId>org.springframework.boot</groupId>
  <artifactId>spring-boot-configuration-processor</artifactId>
  <optional>true</optional>
</dependency>
```

```
工程结构（官方推荐，starter 拆两个模块）：
  sms-spring-boot-autoconfigure/   ← 所有代码和 .imports 放这里
  sms-spring-boot-starter/         ← 只有 pom，依赖 autoconfigure + sms-client
```
:::

:::拓展
**`@AutoConfiguration` 与 `@Configuration` 的区别（Boot 2.7 新增）**

```java
@Target(ElementType.TYPE)
@Retention(RetentionPolicy.RUNTIME)
@Documented
@Configuration(proxyBeanMethods = false)     // ← 默认就是 lite 模式
@AutoConfigureBefore
@AutoConfigureAfter
public @interface AutoConfiguration {
    @AliasFor(annotation = Configuration.class)
    String value() default "";
}
```

| | `@Configuration` | `@AutoConfiguration` |
|---|---|---|
| `proxyBeanMethods` | 默认 **true**（full） | 默认 **false**（lite） |
| 排序注解 | 不能直接用 `@AutoConfigureBefore/After` | 可以直接用 |
| 生效来源 | 被扫描到 | 必须出现在 `.imports` 文件里 |

**所以「写自动配置类」时的两个规范**：① 用 `@AutoConfiguration` 而不是 `@Configuration`；② **不要用 `@ComponentScan`**（自动配置类里的 `@ComponentScan` 会破坏条件装配的语义，官方明确不推荐）。

**启动优化的几个具体抓手（把第 12 题的启动流程接上来）**

| 手段 | 效果 | 代价 |
|---|---|---|
| `spring.main.lazy-initialization=true` | 启动快（Bean 不预实例化） | 问题推迟到首次请求暴露 |
| 精简 starter（能不用 `spring-boot-starter-data-redis` 就别用） | 减少自动配置类和 Bean 数量 | 无 |
| `spring.jmx.enabled=false` | 少注册一堆 MBean | 无（生产基本不用 JMX） |
| AppCDS（`-XX:SharedArchiveFile`） | 类加载快 | 需要构建期生成归档 |
| `-XX:TieredStopAtLevel=1` | 启动快 | 运行期性能下降（只跑 C1） |
| Boot 3 AOT + native image | 启动从秒级到**毫秒级** | 反射/动态代理受限制，构建复杂 |

**三件套之外还要注意的「starter 反模式」**

1. 在自动配置类里 `@Autowired` 注入（应该用 `@Bean` 方法参数注入）
2. 在自动配置类里写 `@PostConstruct`（时机不可控，用 `SmartInitializingSingleton`）
3. 用 `@ComponentScan` 扫自己的包（会扫到不该扫的类，破坏条件装配）
4. 配置项不加默认值（用户不配就 NPE）
:::

:::追问
**Q：`@ConditionalOnBean` 和 `@ConditionalOnMissingBean` 为什么推荐用在自动配置类里、而不是普通 `@Configuration` 里？**
因为它们的判断依赖 **BeanDefinition 的注册顺序**。在自动配置类里顺序是**确定**的（`DeferredImportSelector` 保证用户配置先注册，`AutoConfigurationSorter` 保证自动配置之间的相对顺序）；在普通配置类里顺序**不确定**（取决于扫描顺序），会导致「有时候生效有时候不生效」这种最难查的问题。**官方文档明确写了这条警告**。

**Q：自动配置类里能拿到 `Environment` 吗？**
能，通过 `@Bean` 方法参数注入 `Environment`，或者直接用 `@ConditionalOnProperty` / `@Value`。但要注意**不要在字段上 `@Value`**（自动配置类本身也是个 Bean，字段注入的时机在配置类实例化时，而条件判断发生在更早的注册期）。

**Q：`@ConditionalOnClass` 用 ASM 判断，那 `@ConditionalOnMissingClass` 呢？**
同一个实现（`OnClassCondition`），只是判断逻辑反过来。**都不加载类。** 这是「条件注解为什么不会引发类加载副作用」的统一答案。

**Q：怎么知道某个配置文件里的属性对应哪个 `@ConfigurationProperties` 类？**
`spring-configuration-metadata.json`（由 `spring-boot-configuration-processor` 在编译期生成），IDE 就是读它做自动补全的。排查时可以直接 `jar tf xxx.jar | grep spring-configuration-metadata.json`，解压出来看。**Actuator 的 `/actuator/configprops` 端点也能看运行时的所有 `@ConfigurationProperties` 值** —— 排查「配置到底有没有读进去」时最好用。
:::

:::锚点
**这道题的锚点非常自然——你的 K8s 经验就是「声明式配置 + 条件生效」的另一种形态：**

> 「自动配置这套『**读候选清单 → 按条件过滤 → 有就用没有就兜底**』的机制，我理解起来没什么障碍，因为我天天在 K8s 里用类似的东西：**Kustomize 的 overlay、Helm 的 values、ConfigMap 的注入，本质上都是『声明式配置 + 有则覆盖无则默认』**。K8s 里 `default` 和 `overlay` 的关系，和 `@ConditionalOnMissingBean` 让位给用户 Bean 是同一个设计。
>
> 而且我对『**配置到底是哪来的**』这件事特别敏感——我们排查 rrmcompute 现网 OOM 的时候，第一步就是确认 **pod 实际生效的 resources.limits 是多少**，而不是看 YAML 里写了多少（因为可能有多个 overlay 叠加）。**SpringBoot 的 CONDITIONS EVALUATION REPORT 就相当于 K8s 的 `kubectl describe` + 生效值反查**——都是用来回答『最终生效的到底是什么、为什么是这个』。」

**再补一段真实的、非常加分的话**：

> 「我在推进的 **AI 编程助手 + Sonar** 项目，其实和自动配置有一个共同的工程命题：**怎么让『约定』既省事又不失控**。SpringBoot 的答案是「条件注解 + 可查询的评估报告」——默认帮你想好，但你能查清楚它到底做了什么决定。这一点我觉得比单纯『少写 XML』重要得多：**约定大于配置的前提是可观测，否则就是黑盒。**」
:::

---

## 12. SpringBoot 启动流程、优缺点与工程实践

:::概念
`SpringApplication.run()` 主干：**推断应用类型 → 准备环境 → 创建容器 → `refresh()`（12 步）→ 启动内嵌 Web 服务器 → 回调 Runner**。
记忆钩子：**「准备环境 → 造容器 → 刷容器（refresh 12 步，Tomcat 在第 9 步起来、单例 Bean 在第 11 步创建）→ 收尾」**。
`refresh()` 的第 9 步 `onRefresh` 启动 Tomcat，第 11 步 `finishBeanFactoryInitialization` 创建所有单例 —— **这两个位置搞清楚了，启动慢的问题就知道往哪查。**
:::

:::提问
- 讲一下 SpringBoot 的启动流程？
- `SpringApplication.run()` 里做了什么？
- 内嵌 Tomcat 是怎么启动的？关键参数有哪些？
- 启动有哪些扩展点 / 事件？
- 启动慢怎么优化？
- SpringBoot 的优缺点？
- SpringBoot 怎么做到优雅停机？
- SpringBoot 和 SpringCloud 什么关系？
:::

:::答案
**`SpringApplication.run()` 主干（12 步）**

```
① new SpringApplication(primarySources)
   ├─ deduceWebApplicationType()  ★ 推断应用类型
   │     classpath 有 DispatcherServlet          → SERVLET（Servlet Web 应用）
   │     classpath 只有 DispatcherHandler        → REACTIVE（WebFlux）
   │     都没有                                    → NONE（普通应用）
   ├─ 加载 META-INF/spring.factories 里的 ApplicationContextInitializer
   ├─ 加载 ApplicationListener
   └─ 推断 main 方法所在的类

② run(args)
   ├─ stopWatch.start()                    记录启动耗时
   ├─ 创建 BootstrapContext
   └─ new SpringApplicationRunListeners    发布事件用

③ listeners.starting() → 发布 ApplicationStartingEvent

④ prepareEnvironment()                    ★ 准备环境
   ├─ 创建 Environment（StandardServletEnvironment）
   ├─ 加载命令行参数（--server.port=9090）
   ├─ 触发 ApplicationEnvironmentPreparedEvent
   │     → ConfigDataEnvironmentPostProcessor 加载 application.yml / application-{profile}.yml
   │     （Boot 2.4+ 用新的 ConfigData API，支持 spring.config.import）
   └─ 绑定 spring.main.* 配置（bannerMode、webApplicationType、lazy-initialization）

⑤ printBanner()                          打印 banner

⑥ createApplicationContext()             ★ 创建容器（AnnotationConfigServletWebServerApplicationContext）

⑦ prepareContext()
   ├─ context.setEnvironment(environment)
   ├─ 执行所有 ApplicationContextInitializer
   ├─ 注册 primarySources 为 BeanDefinition（就是你的 @SpringBootApplication 类）
   └─ 发布 ApplicationContextInitializedEvent

⑧ refreshContext(context)                ★★ 核心：进 AbstractApplicationContext.refresh() 的 12 步
   ├─ 第 5 步 invokeBeanFactoryPostProcessors —— 解析配置类、自动配置
   ├─ 第 6 步 registerBeanPostProcessors
   ├─ 第 9 步 onRefresh —— ★ 内嵌 Tomcat 在这里创建并启动
   ├─ 第 11 步 finishBeanFactoryInitialization —— ★ 创建所有非懒加载单例 Bean
   └─ 第 12 步 finishRefresh —— 发布 ContextRefreshedEvent

⑨ afterRefresh()                         空实现（扩展点）

⑩ stopWatch.stop() → 打印 "Started App in X.XXX seconds"

⑪ listeners.started() → 发布 ApplicationStartedEvent

⑫ callRunners()                          ★ 依次执行 ApplicationRunner 和 CommandLineRunner
   → 再发布 ApplicationReadyEvent
```

**七个启动事件（按顺序，能报出来很专业）**

| 事件 | 时机 | 典型用途 |
|---|---|---|
| `ApplicationStartingEvent` | 最早，Environment 还没准备好 | 注册监听器 |
| `ApplicationEnvironmentPreparedEvent` | Environment 就绪，容器还没创建 | 改配置源（如从配置中心拉配置） |
| `ApplicationContextInitializedEvent` | 容器创建、BeanDefinition 还没加载 | 加 `ApplicationContextInitializer` |
| `ApplicationPreparedEvent` | BeanDefinition 加载完、还没 refresh | — |
| `ApplicationStartedEvent` | refresh 完成、Runner 还没跑 | 启动后但业务未就绪 |
| `ApplicationReadyEvent` | **Runner 跑完，完全就绪** | **启动后预热缓存、注册到注册中心** |
| `ApplicationFailedEvent` | 启动失败 | 告警 |

**判断"应用是否真的可用"要用 `ApplicationReadyEvent`，不是 `ApplicationStartedEvent`** —— 后者 Runner 还没执行完。

**内嵌 Tomcat 的启动链路**

```
ServletWebServerApplicationContext.onRefresh()                ← refresh() 第 9 步
→ createWebServer()
→ ServletWebServerFactory.getWebServer(getSelfInitializer())
→ TomcatServletWebServerFactory.getWebServer()
     ├─ new Tomcat()
     ├─ 创建 Connector（协议默认 org.apache.coyote.http11.Http11NioProtocol）
     ├─ 应用 ServerProperties（端口、地址、超时…）
     ├─ tomcat.start()
     └─ 把 DispatcherServlet 注册进去（通过 ServletContextInitializer）
→ 发布 ServletWebServerInitializedEvent
```

**关键参数与真实默认值**

```yaml
server:
  port: 8080                              # 默认 8080；0 = 随机端口（测试常用）
  address: 0.0.0.0
  servlet:
    context-path: /                       # 默认 /
  shutdown: graceful                      # ★ 优雅停机，默认 immediate
  tomcat:
    uri-encoding: UTF-8
    threads:
      max: 200                            # 默认 200（最大工作线程数）
      min-spare: 10                       # 默认 10（最小空闲线程）
    max-connections: 8192                 # 默认 8192（最大连接数）
    accept-count: 100                     # 默认 100（等待队列长度）
    connection-timeout: 20s               # 默认 20s
    keep-alive-timeout: 20s
    max-http-form-post-size: 2MB          # 表单 POST 最大值
    accesslog:
      enabled: true                       # 默认 false
      directory: /data/logs
      pattern: '%h %l %u %t "%r" %s %b %D'
spring:
  lifecycle:
    timeout-per-shutdown-phase: 30s       # 优雅停机等待时间
  mvc:
    async:
      request-timeout: 30s
```

**版本差异**：`server.tomcat.max-threads` 在 **Boot 2.3 起被废弃**，改成 `server.tomcat.threads.max`（同理 `min-spare-threads` → `threads.min-spare`）。老配置文件里用旧名，升级后会被忽略 —— **这是个真实的升级坑**。

**`max-connections` 与 `threads.max` 的关系（容量估算必问）**

```
Tomcat 模型（NIO）：
  max-connections = 8192        能同时保持的连接数（含 keep-alive 空闲连接）
  accept-count    = 100         连接数满了之后，操作系统的等待队列
  threads.max     = 200         真正干活的线程数

结论：
  · 连接可以保持 8192 个，但只有 200 个线程在处理
  · 请求来了但没空闲线程 → 排队（在 Tomcat 内部的 executor 队列里）
  · 只有当 max-connections 也满了，新连接才进 accept-count 队列
  · ★ 所以真正的并发处理能力上限 = threads.max × (1 / 单请求占用线程比例)
  · 如果每个请求 50ms，200 线程 → 理论 QPS ≈ 200 / 0.05 = 4000
```

**这个公式讲出来，面试官会认为你懂容量规划，而不是只会配置。**

**启动慢的排查与优化**

```
① 先量化：日志里有 "Started App in 12.345 seconds (JVM running for 13.1)"
   加 --debug 看自动配置数量；用 jvisualvm / async-profiler 采样启动过程

② 按耗时排序（从大到小）
   □ 自动配置类太多 → 精简 starter、exclude 不需要的
   □ 单例 Bean 创建慢 → 某个 Bean 的 @PostConstruct 里做了重活（拉远程配置、建连接池、扫全表）
                        → 拆到 ApplicationReadyEvent 里异步做
   □ 类加载开销 → AppCDS
   □ JIT 编译开销 → -XX:TieredStopAtLevel=1（只跑 C1，启动快、运行慢）
   □ 包扫描范围太大 → 精确配置 @ComponentScan / @MapperScan 的 basePackages
   □ 需要连接的外部依赖（DB/Redis/MQ）慢或超时 → 检查网络和超时配置
```

```yaml
# 三个低成本的优化（可以先上这三个）
spring:
  main:
    lazy-initialization: true        # 延迟初始化，启动明显变快
  jmx:
    enabled: false                   # 生产不用 JMX
```

```bash
# 启动耗时可视化（Spring Boot 2.4+ 支持）
java -jar app.jar -Dspring.application.admin.enabled=true
# 或者用 ApplicationStartup（BufferingApplicationStartup）记录每个步骤耗时
```

```java
// 用 ApplicationStartup 精确定位启动耗时的每一步
public static void main(String[] args) {
    SpringApplication app = new SpringApplication(App.class);
    app.setApplicationStartup(new BufferingApplicationStartup(2048));
    ConfigurableApplicationContext ctx = app.run(args);
    // 启动后 dump 出所有启动步骤的耗时
    ((BufferingApplicationStartup) app.getApplicationStartup()).dump(System.out);
}
```

**优雅停机（生产必须配）**

```yaml
server:
  shutdown: graceful                    # 收到 SIGTERM 后不再接受新请求，等待处理中的请求完成
spring:
  lifecycle:
    timeout-per-shutdown-phase: 30s     # 最多等 30s，超时强制关闭
```

```yaml
# K8s 侧的配合（这一步不做，优雅停机等于没配）
spec:
  containers:
    - name: app
      lifecycle:
        preStop:
          exec:
            command: ["sh", "-c", "sleep 5"]   # ★ 等 Endpoint 从 Service 摘除后再发 SIGTERM
      readinessProbe:                          # 用 actuator 的就绪探针
        httpGet: { path: /actuator/health/readiness, port: 8080 }
        initialDelaySeconds: 20
        periodSeconds: 5
      livenessProbe:
        httpGet: { path: /actuator/health/liveness, port: 8080 }
        initialDelaySeconds: 40
        periodSeconds: 10
```

```yaml
# 要开 readiness/liveness 端点
management:
  endpoint:
    health:
      probes:
        enabled: true
  endpoints:
    web:
      exposure:
        include: health,info,metrics,conditions,beans,env,threaddump,heapdump
  health:
    livenessstate:
      enabled: true
    readinessstate:
      enabled: true
```

**为什么要 `preStop: sleep 5`**：K8s 从 Service 的 Endpoint 摘除 Pod 是**异步**的，发 SIGTERM 时可能还有流量打进来。先 sleep 几秒等摘除完成，再让应用停止接受新请求，才能真的做到「零 502」。**这个细节是区分「知道优雅停机这个词」和「真的做过」的分界线。**

**SpringBoot 优缺点（和传统 SpringMVC + 外置 Tomcat 对比）**

| | 传统 war + 外置 Tomcat | Spring Boot |
|---|---|---|
| **配置** | 大量 XML（web.xml、applicationContext.xml、spring-mvc.xml） | 一个 `application.yml` + 自动配置 |
| **依赖管理** | 手工管版本，容易冲突 | BOM 统一管，starter 打包整组依赖 |
| **部署** | 装 Tomcat → 扔 war → 重启 Tomcat 影响所有应用 | `java -jar`，进程级隔离 |
| **容器化** | 镜像要装 Tomcat，镜像大 | 一个 jar = 一个进程，镜像小、启动快 |
| **监控** | 要自己接 JMX / 自己写健康检查 | Actuator 开箱即用 |
| **缺点 1** | — | **自动配置是黑盒**：Bean 没生效时要知道去看 CONDITIONS EVALUATION REPORT |
| **缺点 2** | — | **版本升级耦合**：第三方 starter 不跟 Boot 版本同步时，容易出现 `NoSuchMethodError` / `ClassNotFoundException` |
| **缺点 3** | — | **内存占用偏高**：每个服务一个 JVM + 内嵌容器 + 元空间，容器里必须配 `-XX:MaxRAMPercentage`（接手册 07） |
| **缺点 4** | — | **启动相对慢**：类扫描 + 自动配置 + JVM 预热；原生镜像能解决但改造成本高 |

**SpringBoot 与 SpringCloud 的关系与常用组件**

| 能力 | 组件 | 一句话 |
|---|---|---|
| 服务注册发现 | Nacos / Eureka / Consul | 服务启动时注册自己，调用方按名找 |
| 配置中心 | Nacos Config / Apollo | 配置集中管理 + 动态刷新（`@RefreshScope`） |
| 网关 | Spring Cloud Gateway | 路由、鉴权、限流（基于 WebFlux，非阻塞） |
| 服务调用 | OpenFeign / RestTemplate | 声明式 HTTP 客户端（接口 + 注解） |
| 负载均衡 | Spring Cloud LoadBalancer | 客户端负载均衡（替代 Ribbon） |
| 熔断限流 | Sentinel / Resilience4j | 失败快速返回，保护上游 |
| 链路追踪 | Sleuth + Zipkin / SkyWalking | traceId 贯穿全链路 |
| 分布式事务 | Seata | `@GlobalTransactional`（手册 04 第 27 题） |

**Boot 是基础框架（单体应用的能力），Cloud 是分布式协作的能力。** 一句话划清。
:::

:::拓展
**`BeanDefinitionOverrideException`：Boot 2.1 起默认禁止 Bean 覆盖**

```
The bean 'xxxService', defined in class path resource [...], could not be registered.
A bean with that name has already been defined in ... and overriding is disabled.
```

这是 Boot 2.1 的一个**故意行为变更**（之前允许静默覆盖，容易出诡异问题）。三种处置：

```yaml
# ① 改名（最正确）
# ② 显式开覆盖（临时救急，要知道自己在干什么）
spring:
  main:
    allow-bean-definition-overriding: true
```

**注意**：这个开关和 `@ConditionalOnMissingBean` 是**两件事**。前者管「同名 Bean 定义能不能覆盖」，后者管「要不要注册这个 Bean」。**自动配置的覆盖走的是后者，不需要开这个开关。**

**Banner 与启动日志（很小的细节，但能体现熟练度）**

```yaml
spring:
  banner:
    location: classpath:banner.txt
    charset: UTF-8
  main:
    banner-mode: off          # off / console / log（默认 console）
    log-startup-info: false   # 关闭启动时那堆 INFO 日志
```

**Profile 与多环境配置**

```yaml
# application.yml（主配置）
spring:
  profiles:
    active: ${SPRING_PROFILES_ACTIVE:dev}    # ★ 用环境变量覆盖，容器里最好用

---
# application-dev.yml
spring:
  datasource:
    url: jdbc:mysql://localhost:3306/demo

---
# application-prod.yml
spring:
  datasource:
    url: jdbc:mysql://prod-db:3306/demo
    hikari:
      maximum-pool-size: 50
```

```bash
# 优先级（从高到低，被追问时非常有用的知识）
1. 命令行参数             --server.port=9090
2. 环境变量               SERVER_PORT=9090
3. application-{profile}.yml（jar 外部的优先于内部的）
4. application.yml（jar 外部的优先于内部的）
5. @PropertySource
6. 默认值（SpringApplication 里 setDefaultProperties）
```

**Boot 2.4 之后 `spring.config.import` 引入了新的配置导入能力**：

```yaml
spring:
  config:
    import:
      - classpath:extra.yml
      - file:/etc/app/secret.yml        # 挂载的 Secret 文件
      - optional:nacos://config-center  # 配置中心（需对应实现）
      - configtree:/etc/app/secrets/    # K8s Secret 挂载成目录时用
    location: classpath:/config/        # 额外搜索路径
```

**`configtree:` 这个前缀就是专门给 K8s Secret/ConfigMap 挂载设计的** —— 把目录下的每个文件当成一个配置项。你有 K8s 经验，这一条可以主动讲，非常对口。
:::

:::追问
**Q：`ApplicationRunner` 和 `CommandLineRunner` 有什么区别？**
功能几乎一样，都在容器 refresh 完成、`ApplicationReadyEvent` 之前执行。区别是参数类型：`ApplicationRunner.run(ApplicationArguments)` 拿的是**结构化参数**（能区分 `--key=value` 选项参数和普通参数），`CommandLineRunner.run(String... args)` 拿的是**原始字符串数组**。推荐 `ApplicationRunner`。多个 Runner 之间可以用 `@Order` 控制顺序，**Runner 里抛异常会导致启动失败**（这个特性常用来做「启动自检」）。

**Q：为什么 `ApplicationReadyEvent` 才是"真正可用"的信号？**
因为它是 Runner 执行完之后发布的。如果你的服务在启动时要「预热缓存」「拉全量字典」「注册到注册中心」，这些逻辑通常在 Runner 里，`ApplicationStartedEvent` 时它们还没跑完 → 此时把流量放进来会失败。**K8s 的 readinessProbe 应该指向 `/actuator/health/readiness`，而这个端点的状态与 `ApplicationReadyEvent` 一致（由 `ReadinessStateHealthIndicator` 提供）。**

**Q：`spring.main.lazy-initialization=true` 有什么风险？**
① 循环依赖、Bean 找不到、配置错误这类问题**推迟到第一次请求才暴露**（启动不再报错，可能上线后才发现）；② 第一次请求会变慢（要现场创建 Bean，可能连锁创建一串）；③ 依赖 `@PostConstruct` 做预热的功能失效（Bean 被创建时才会执行）。**建议：只在明确的低风险模块上用 `@Lazy`，全局开关慎用。**

**Q：怎么在启动时做「依赖可用性检查」，不可用就快速失败？**
用 `ApplicationRunner` 或者在 `refresh()` 完成后主动 ping 依赖（DB `SELECT 1`、Redis `PING`、MQ 建连接）。**关键设计原则是「快速失败」**：K8s 里让 Pod 直接启动失败退出（`ExitCode != 0`），比起来了但每个请求都超时要好得多——前者会被 K8s 反复重启并触发告警，后者是「半死不活」状态，更难发现。**这条正好接得上你排查 rrmcontrol「pod 反复重启」的经验。**
:::

:::锚点
**这一题是你全篇最能把 K8s 经验变现的地方。**

> 「SpringBoot 的启动流程和**容器启动流程是同一套模型**，我很熟：
>  ① 准备环境（加载配置）→ 对应 K8s 的 **ConfigMap/Secret 挂载 + env 注入**
>  ② 创建容器 → 对应容器 runtime 创建容器
>  ③ refresh（起 Tomcat、创建单例 Bean）→ 对应**进程启动 + 初始化**
>  ④ Runner（预热）→ 对应 **`postStart` 钩子**
>  ⑤ `ApplicationReadyEvent` → 对应 **`readinessProbe` 通过、开始接流量**
>  ⑥ 优雅停机 → 对应 **`preStop` + SIGTERM**」

**再具体一点，讲你真实排查过的现象**：

> 「我们现网 **rrmcompute 的 Pod 反复重启**，K8s 事件里是 `OOMKilled`，应用日志里**看不到** `OutOfMemoryError`——因为这个杀是 cgroup 干的，不是 JVM 自己抛的。这件事让我对『**进程级生命周期 vs 应用级生命周期**』的边界特别敏感。放到 SpringBoot 里，就是 `server.shutdown=graceful` 必须配 `preStop: sleep 5`：**只配应用侧不配 K8s 侧，收到 SIGTERM 时 Endpoint 可能还没摘除，流量还在打进来 → 依然会 502。** 我们后来把内存从 5Gi 调到 5.5GiB（requests 保持 3Gi）也是同一个思路：**容器的资源上限和进程的实际使用必须对齐，不能只看一个数字。**」

**为什么这段话含金量高**：它把「SpringBoot 优缺点」这道很虚的题，落到了你**真实处理过的生产故障**上，而且给出了一个具体可执行的配置细节（`preStop: sleep 5`）。面试官听到这一段，会认为你有生产环境的手感——**这是转技术栈候选人最稀缺的东西。**
:::

---

> 📌 **本文档使用方式**：默认折叠答案，先自己回答「面试官会怎么问」，再点开对照。
> 手机上建议开启**自测模式**（答案按钮变灰），逐题过；连续两遍能说全，就可以上考场了。
> 🔁 **和手册 07（JVM）的联动**：第 5 题的切点过宽 → 元空间增长；第 12 题的容器内存 → `-XX:MaxRAMPercentage`；两本书一起看，Spring 的问题能答到 JVM 那一层。