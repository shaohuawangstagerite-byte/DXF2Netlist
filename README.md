# DXF2Netlist

用 Python + ezdxf 将电气 DXF 图纸转成带来源的网表，再查询指定端子所在的完整导线网络。可用于接线关系核对，以及上层图纸分析工具的数据准备。

```text
DXF → netlist.json → chain-with-components.json
```

## 能做什么

- **提取图纸信息**：保存元件、端子、导线、文字及来源；名称和语义保留候选或未知状态。
- **生成完整 chain**：保留起点可达的分支、闭环、平行线和中间接点。这里的 chain 是连通子图，不限于一条线路。
- **补全元件资料**：附带链内元件的全部端子，用 `in_chain` 标明是否属于此次网络；其他端子不会扩大网络。
- **脱离 DXF 查询**：提取后只读取网表 JSON，仍可追溯保存的原图依据。

当前处理单张 DXF，主要支持 Model 空间的 LINE 和顶层带属性 INSERT。查询只沿 `wire` 展开，不判断触点动作或现场导通状态，也不自动拼接多张图纸。

## 快速使用

使用 Python 3.12，在项目根目录、已激活的虚拟环境中执行：

```shell
python -m pip install -r requirements.txt
python tools/extract.py input.dxf --output output/netlist
python tools/chain.py --netlist output/netlist/netlist.json --start PORT_ID --output output/chain
```

将 `input.dxf` 换成图纸路径，`PORT_ID` 换成网表中的端子 ID。输出目录必须尚不存在。查询结果为 `output/chain/chain-with-components.json`。环境设置及按名称、编号查询的方法见 [SPEC.md](SPEC.md)。

## SPEC 如何指导开发

[SPEC.md](SPEC.md) 定义输入范围、识别规则、输出含义和验收要求。开发按“规则 → 实现 → 验证”推进：

1. **先明确行为**：例如 R8 规定，没有显式连接依据的线段内部交叉不能形成连接。
2. **据此约束代码**：连接算法检查共享端点和显式接点，不能因为“看起来交叉”就连通，也不能针对某张图写特殊分支。
3. **按规则验证**：用合成用例区分普通交叉与显式接点；提取入口另做独立几何与连接检查，避免用生产算法自己的结果充当答案。

改变行为时，同步更新规格、实现、运行配置和验证；遇到证据不足的情况保留歧义，不为通过某个样例放宽标准。

[AGENTS.md](AGENTS.md) 规定开发协作方式；[rules/extraction.md](rules/extraction.md) 保存程序实际读取的规则参数。SPEC 用于指导开发和验收，不由程序自动执行。
