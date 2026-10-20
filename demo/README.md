# HuiCode 面试演示

## 启动

在仓库根目录执行：

```powershell
.\demo\reset-demo.ps1
.\demo\start-demo.ps1
```

演示模式使用离线 Provider，不需要 API Key。它仍然经过真实的 Agent Loop、工具注册、权限检查、文件读取、文件编辑、命令执行和结果回灌。

## 推荐演示流程

1. 输入“帮我看看这个项目的代码结构”，展示 `Find` 调用和结果回灌。
2. 输入“读取入口文件内容”，展示 `Read` 工具和 Markdown 回复。
3. 输入“把默认问候改成中文，然后运行测试”，展示 `Read -> Edit -> Bash` 的自动循环。
4. 输入 `/plan`，再输入“规划一下如何给 greet 增加语言参数”，展示只读规划模式。
5. 输入 `/do` 返回执行模式，说明权限系统、上下文管理和 Provider 抽象。

## 面试讲解主线

```text
用户输入
  -> Provider 流式响应
  -> Agent Loop 解析工具调用
  -> Tool Registry 查找工具
  -> Permission Engine 检查
  -> 工具执行
  -> 结果写回历史
  -> Provider 继续决定下一步
```

现场重点讲三件事：Provider 层统一了不同协议，Agent Loop 把工具结果重新喂给模型，权限和 Worktree 把自动修改限制在可控范围内。

## 现场故障处理

- 看到网络/API 错误：执行 `Ctrl+C`，重新运行 `start-demo.ps1`，离线 Demo 不依赖网络。
- 演示项目被改乱：执行 `reset-demo.ps1` 后重新启动。
- 想展示真实 Provider：复制配置为本地文件，填入自己的环境变量或 API Key，再去掉 `--demo`。
