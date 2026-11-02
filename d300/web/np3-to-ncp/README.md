# NP3 → NCP 转档器（网页版）

单文件、纯客户端。拖进 NP3，直接下载 NCP。打开 `index.html` 即可用，不需要服务器。

- `index.html` —— 成品，配方已内嵌（38 KB）
- `template.html` —— 源模板，`/*__PRIORS__*/null` 是数据占位
- `preview.png` —— 截图

改完配方后重新生成：

```bash
cd ../../   # d300/
python tools/np3_to_ncp.py --build-web
```

算法与局限见 [`../docs/23-np3-to-ncp-converter.md`](../docs/23-np3-to-ncp-converter.md)。
