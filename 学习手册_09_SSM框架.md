# 📘 学习手册 09 · SSM 框架（Spring 系）

> 配套《面试八股复习计划》第 2 节 SSM + PDF 第 62-65 页
> 模板：**一句话结论 → 详细解释 → 面试话术/例题**
> Java 岗（酷开/工行/银行系/国企）必考；你不是 Java 岗主打，但被问到的题就这几道，背熟即可

---

## 1. Spring / SpringMVC / SpringBoot 各自职责与区别
**一句话结论**：Spring 是核心容器（IOC + AOP），SpringMVC 是 Web 层框架（请求分发），SpringBoot 是"开箱即用"的整合启动器（自动配置 + 内嵌服务器）。
**详细解释**：
- **Spring**：IOC 容器（对象创建管理）+ AOP（切面）+ 事务管理——核心
- **SpringMVC**：基于 Spring 的 MVC Web 框架——DispatcherServlet 分发请求到 Controller
- **SpringBoot**：简化配置（自动配置 @EnableAutoConfiguration）、内嵌 Tomcat/Jetty、起步依赖（starter）、约定大于配置；本质还是 Spring 生态的封装
- 关系：SpringBoot 里包含 Spring + SpringMVC；用 SpringBoot 不用手动配 XML
**话术/例题**：一句"Spring 是内核、MVC 是 Web 层、Boot 是快速启动器"。追问：为什么用 SpringBoot 不用 Spring？→ 自动配置省去大量 XML，内嵌服务器一键启动。

## 2. Spring IOC（控制反转）和 DI（依赖注入）
**一句话结论**：IOC 把对象的创建和依赖管理交给容器（不再 new），DI 是容器自动注入依赖的方式——解耦 + 易测试。
**详细解释**：
- 控制反转：对象创建权从"代码里 new"反转给容器（IOC 容器启动时创建 Bean 存容器）
- 依赖注入：Bean 需要其他 Bean 时容器自动注入（构造器注入/Setter 注入/字段注入 @Autowired）
- 好处：解耦（改实现不改调用方）、方便测试（注入 Mock）、统一生命周期管理
- 类比 Node.js：NestJS 的 DI 就是同一思想（@Injectable + 构造函数注入）——你可以打通讲
**话术/例题**：一句"IOC 是思想，DI 是实现"。追问：Bean 默认是单例吗？→ 是（@Scope("singleton")），注意成员变量线程安全。

## 3. Spring AOP 面向切面
**一句话结论**：AOP 把横切逻辑（日志/事务/鉴权）从业务代码中抽出来，动态代理织入——不改业务代码加功能。
**详细解释**：
- 概念：切面（Aspect）、切点（Pointcut 表达式）、通知（Advice：Before/After/AfterReturning/AfterThrowing/Around）、连接点
- 实现原理：**动态代理**——JDK 动态代理（接口，InvocationHandler）/ CGLIB（类，继承子类）
- 典型应用：@Transactional 事务、日志切面、权限切面、性能监控
- 对比 Node.js：Express 中间件/Koa 洋葱模型就是 AOP 思想的体现
**话术/例题**：一句"代理 + 切点表达式 + 通知"，举例事务/日志。追问：JDK 代理和 CGLIB 区别？→ JDK 要求接口，CGLIB 走子类；Spring 优先 JDK，无接口用 CGLIB。

## 4. Spring 事务管理
**一句话结论**：@Transactional 声明式事务，默认只回滚 RuntimeException/Error（不回滚检查异常），本质是 AOP 代理 + 事务管理器。
**详细解释**：
- 原理：@Transactional 方法被代理拦截 → 开启事务 → 执行 → 成功提交/异常回滚
- 参数：propagation（传播行为：REQUIRED 默认/REQUIRES_NEW 新事务/NESTED 嵌套）、isolation（隔离级别）、rollbackFor（指定回滚异常）
- 坑：① 同类内部调用（this.method()）不走代理，事务失效；② 异常被 catch 吞了不触发回滚；③ rollbackFor 默认不含 Checked 异常
- 分布式事务：@GlobalTransactional（Seata）——参考手册 04 第 27 题
**话术/例题**：背"三个失效场景"（内部调用/吞异常/Checked 异常）是高频追问。追问：事务传播 REQUIRED 和 REQUIRES_NEW 区别？→ REQUIRED 加入现有事务，REQUIRES_NEW 挂起现有开新的。

## 5. SpringMVC 请求处理流程
**一句话结论**：请求 → DispatcherServlet（前端控制器）→ HandlerMapping 找 Controller → HandlerAdapter 执行 → 返回 ModelAndView/JSON → 响应。
**详细解释**：
1. 请求到 **DispatcherServlet**（统一入口）
2. HandlerMapping：根据 URL 找到对应 Controller 方法
3. HandlerAdapter：执行方法（参数绑定 @RequestParam/@RequestBody）
4. 返回结果 → ViewResolver 解析视图 / @ResponseBody 直接 JSON
5. 渲染响应
- 常用注解：@Controller/@RestController、@RequestMapping、@RequestBody、@PathVariable
**话术/例题**：背"DispatcherServlet → Mapping → Adapter"主流程。追问：@RestController 和 @Controller 区别？→ RestController = Controller + ResponseBody（直接返回 JSON）。

## 6. Spring 常用注解
**一句话结论**：组件（@Component/@Service/@Repository/@Controller）+ 注入（@Autowired/@Qualifier/@Value）+ Web（@RestController/@RequestMapping）+ 配置（@Configuration/@Bean）。
**详细解释**：
- @Component：通用组件；@Service（业务层）/@Repository（DAO）/@Controller（控制层）是语义化子注解
- @Autowired：按类型注入（配合 @Qualifier 按名）
- @Configuration + @Bean：Java 配置类里声明 Bean
- @Value：注入配置值；@ConfigurationProperties：绑定配置组
- 生命周期：@PostConstruct（初始化）/@PreDestroy（销毁）
**话术/例题**：背分组表。追问：@Autowired 和 @Resource 区别？→ Autowired 按类型（Spring），Resource 按名称（JSR-250）。

## 7. MyBatis 是什么？#{} 和 ${} 的区别
**一句话结论**：MyBatis 是半自动 ORM（SQL 自己写，映射框架管），#{} 预编译占位符（防注入），${} 字符串拼接（有注入风险）。
**详细解释**：
- MyBatis：SQL 写在 XML/注解，结果映射到对象；比 JPA 灵活（复杂 SQL 可控），比 JDBC 省事
- **#{}**：预编译 → `?` 占位符 + 参数绑定 → 防 SQL 注入
- **${}**：直接拼进 SQL → 注入风险 → 只能用于表名/排序字段（且要白名单校验）
- 动态 SQL：if/where/foreach/set 标签
**话术/例题**：一句"#{} 安全 ${} 危险" + 例子 `WHERE name = #{name}` vs `ORDER BY ${col}`。追问：MyBatis 和 MyBatis-Plus 区别？→ Plus 封装了通用 CRUD 不用写 SQL。

## 8. SpringBoot 自动配置原理
**一句话结论**：@SpringBootApplication 包含自动配置注解，启动时加载 META-INF/spring.factories 里的 AutoConfiguration，按条件注解（@ConditionalOnXxx）生效。
**详细解释**：
- @SpringBootApplication = @Configuration + @EnableAutoConfiguration + @ComponentScan
- @EnableAutoConfiguration → 导入 AutoConfigurationImportSelector → 读 spring.factories/imports 文件里所有自动配置类
- 每个自动配置类用 @ConditionalOnClass（有对应类才生效）/@ConditionalOnMissingBean（用户没配才生效）控制
- 例：有 spring-boot-starter-data-redis 且没自己配 RedisTemplate → 自动配一个
**话术/例题**：背"factories 文件 + 条件注解"两步。追问：怎么覆盖自动配置？→ 自己定义同类型 Bean（@ConditionalOnMissingBean 让你优先）。

## 9. SpringBoot 优缺点（和 SpringMVC 对比）
**一句话结论**：优点：快速启动、自动配置、内嵌服务器、生态丰富、微服务友好；缺点：版本升级兼容问题、自动配置"黑盒"难排查、内存占用偏高。
**详细解释**：
- 优点：starter 依赖管理、内嵌 Tomcat 一键启动、Actuator 监控、Config Server 微服务配套
- 缺点：大量自动配置若不知原理难排查（为什么 Bean 没生效）、依赖版本冲突（BOM 管理）、启动慢
- 对比：SpringBoot 2.x 内嵌服务器 vs 传统 war 包部署 Tomcat
**话术/例题**：优缺点各两条即可。追问：Spring Cloud 和 SpringBoot 关系？→ Boot 是基础框架，Cloud 是微服务全家桶（注册/网关/配置）。

## 10. Bean 的生命周期
**一句话结论**：实例化 → 属性注入 → Aware 回调 → 初始化（@PostConstruct/InitializingBean）→ 使用 → 销毁（@PreDestroy/DisposableBean）。
**详细解释**：
1. 实例化（构造器）
2. 依赖注入（属性填充）
3. Aware 回调（BeanNameAware/ApplicationContextAware）
4. BeanPostProcessor 前置处理
5. 初始化（@PostConstruct → InitializingBean.afterPropertiesSet → 自定义 init-method）
6. 使用
7. 销毁（@PreDestroy → DisposableBean.destroy）
**话术/例题**：背 7 步 + "初始化三连"顺序。追问：BeanPostProcessor 作用？→ 代理创建的关键点（AOP 就是在这里织入代理）。

## 📝 本章自测（闭卷）
1. Spring/MVC/Boot 三者关系一句话
2. IOC 和 DI 是什么，好处
3. AOP 实现原理（动态代理两种）
4. 事务失效三个场景
5. MVC 请求主流程
6. #{} 和 ${} 区别 + 为什么防注入
7. SpringBoot 自动配置两步原理

> 完成自测后回 PDF 第 62-65 页过 MyBatis 剩余题
