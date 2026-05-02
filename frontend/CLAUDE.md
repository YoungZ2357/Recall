# Recall Frontend

React + TypeScript + Vite 前端，对接后端 REST API（`http://localhost:8000`）。

## 技术栈

| 层 | 技术 |
|----|------|
| 框架 | React 19 |
| 语言 | TypeScript ~6.0（严格模式） |
| 构建 | Vite 8 |
| UI 组件库 | Ant Design（antd） |
| 包管理 | npm |

## 常用命令

```bash
cd frontend
npm install          # 安装依赖
npm run dev          # 开发服务器（默认 http://localhost:5173）
npm run build        # 类型检查 + 构建
npm run lint         # ESLint
```

## TypeScript 严格模式

`tsconfig.app.json` 必须包含 `"strict": true`。当前已启用的检查（`noUnusedLocals`、`noUnusedParameters` 等）保持不变，`strict` 在此基础上叠加。

## 目录结构（规划）

```
src/
├── api/            # API 调用封装（fetch wrapper、类型定义）
│   └── types.ts    # 从 docs/api_protocol.md 复制的 TypeScript 类型
├── components/     # 通用组件
├── pages/          # 页面组件（Documents、Search）
├── hooks/          # 自定义 hooks
├── App.tsx
└── main.tsx
```

## API 协议

完整类型定义和端点说明见 `../docs/api_protocol.md`。`src/api/types.ts` 直接复制该文件的"类型汇总"部分，保持与后端 `schemas.py` 一致。

Vite dev proxy 配置（`vite.config.ts`）：
```ts
server: {
  proxy: {
    '/api': 'http://localhost:8000',
    '/generate': 'http://localhost:8000',
  }
}
```

## 命名规范

| 类别 | 风格 | 示例 |
|------|------|------|
| 文件 | kebab-case | `document-list.tsx`、`use-search.ts` |
| 变量 / 函数 | camelCase | `fetchDocuments()`、`isLoading` |
| 组件 / 类型 / 接口 | PascalCase | `DocumentList`、`SearchResultItem` |
| 常量 | UPPER_SNAKE_CASE | `BASE_URL`、`DEFAULT_TOP_K` |

## UI 规范

- 所有 UI 组件优先使用 Ant Design（`antd`），不引入其他组件库
- 布局使用 `Layout`、`Sider`、`Content`；表格用 `Table`；表单用 `Form`
- 错误提示用 `message.error()` 或 `notification`；加载态用 `Spin` 或 Table 自带 `loading`
- 不自定义全局 CSS reset，使用 antd 默认主题；局部样式用 CSS Modules（`*.module.css`）
- 配色方案使用 `../docs/coloring.md`

## 已规划页面

| 页面 | 路径 | 说明 |
|------|------|------|
| 文档管理 | `/documents` | 上传、列表（含 sync_status）、删除 |
| 搜索 | `/search` | 搜索框 + 结果列表 + α/β/γ 评分明细可视化 |

## Hard Rules

1. 不绕过 TypeScript 严格模式（禁用 `any`，`// @ts-ignore` 须有说明）
2. API 类型必须与 `docs/api_protocol.md` 保持一致，不自造字段名
3. SSE 流式处理（`/generate` stream 模式）使用 `EventSource` 或 `fetch` + `ReadableStream`，不用第三方 SSE 库
4. 不硬编码后端地址——dev 环境走 Vite proxy，生产环境通过环境变量 `VITE_API_BASE`
